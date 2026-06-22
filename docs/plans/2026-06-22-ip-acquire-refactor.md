# IP 按需获取 + 连通性检测 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把代理池从"预填+后台补"模式重构为 JIT（用时才买）模式，acquir 为空时异步买 1 个 IP 并验证连通性，不阻塞事件循环。

**Architecture:** acquire_async 查库池 → 有可用 IP 直接返回 → 池空则 await provider.fetch_async(1) 买一个 → 快速 HTTP 连通性检测 → 入数据库 → 返回。去掉 warmup / supplement_loop / supplement_interval 所有预补逻辑，只保留 health_check 后台清理线程。

**Tech Stack:** Python 3.13 + httpx.AsyncClient + asyncio + SQLite WAL

---

### 前置：确认当前代码基线

全量测试: 453 passed, 1 skipped

---

### Task 1: Provider 添加异步 fetch 方法

**Files:**
- Modify: `proxy/provider.py:39-66`

**Step 1: 在 ProxyProvider 基类新增 `fetch_async`**

```python
# 在 fetch() 方法之后添加:

async def fetch_async(self, num: int = 10, ttl: int = 60) -> list[ProxyRecord]:
    """异步拉取 IP，用于 acquire_async() 中不阻塞事件循环。

    :return: ``ProxyRecord`` 列表，失败返回空列表
    """
    if not self.api_url:
        logger.warning(f"[{self.name}] api_url 为空，跳过拉取")
        return []
    try:
        raw = await self._do_fetch_async(num, ttl)
        logger.info(f"[{self.name}] 拉取 {len(raw)} 个 IP")
        return raw
    except Exception as e:
        logger.error(f"[{self.name}] 异步拉取失败: {e}", exc_info=True)
        return []

async def _do_fetch_async(self, num: int, ttl: int) -> list[ProxyRecord]:
    """子类覆盖：异步调用 API。默认回退到同步 _do_fetch。"""
    return self._do_fetch(num, ttl)
```

**Step 2: JuliangProvider 覆盖 `_do_fetch_async`**

```python
# 在 JuliangProvider 的 _do_fetch 方法之后添加:

async def _do_fetch_async(self, num: int, ttl: int) -> list[ProxyRecord]:
    params = {"num": str(num), "result_type": "json"}
    async with httpx.AsyncClient(timeout=self.timeout) as client:
        resp = await client.get(self.api_url, params=params)
        resp.raise_for_status()
        text = resp.text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return self._parse_text(text)
    return self._parse_json(data)
```

**Step 3: 写测试**

- Modify: `tests/test_proxy_pool.py`

```python
@pytest.mark.asyncio
async def test_juliang_fetch_async_json():
    """异步拉取 JSON 格式。"""
    import httpx
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "code": 200,
        "data": {"proxy_list": [["1.1.1.1", 8080, "u", "p"]]},
    })
    mock_resp.raise_for_status = lambda: None
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
    p = JuliangProvider("http://test")
    recs = await p.fetch_async(num=1)
    assert len(recs) == 1
    assert recs[0].ip == "1.1.1.1"
```

**Step 4: 运行测试验证**

```bash
pytest tests/test_proxy_pool.py -v -q
```

预期: 新增 1 个测试通过，全量不变。

---

### Task 2: ProxyPool.acquire() 改为 async + 池空时当场买

**Files:**
- Modify: `proxy/pool.py:105-155`

**Step 1: 删除旧逻辑（warmup / supplement_loop / supplement_interval / _last_acquire_time / _supplement_lock）**

删除的方法和属性:
- `warmup()` (line 218-231)
- `supplement_interval` property (line 94-96)
- `start_supplement_loop()` (line 377-401)
- `stop_supplement_loop()` (line 403-411)
- `_supplement()` (line 244-293)
- `_supplement_lock` (line 70)
- `_supplement_thread` (line 67)
- `_supplement_stop` (line 69)
- `_last_acquire_time` (line 71)

**Step 2: 新增 `acquire_async()`**

```python
async def acquire_async(self) -> ProxyRecord | None:
    """异步申请 IP，池空时自动购买并检测连通性。

    流程:
    1. 查池 → 有可用 IP → 返回
    2. 池空 → await provider.fetch_async(1) → 买 1 个
    3. 连通性检测 → 可用则写入数据库 → 返回
    4. 不可用 → 标记失败 → 重新买（最多 3 次）

    :return: ProxyRecord 或 None（禁用或买不到）
    """
    if not self.enabled:
        logger.debug("proxy_enabled=false，acquire 返回 None")
        return None

    # 先查池
    rec = self._acquire_from_pool()
    if rec is not None:
        return rec

    # 池空，买 IP
    if self.provider is None:
        logger.warning("无 provider，无法购买 IP")
        return None

    for attempt in range(3):
        try:
            records = await self.provider.fetch_async(num=1)
        except Exception as e:
            logger.error(f"购买 IP 失败 (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                return None
            await asyncio.sleep(1)
            continue

        if not records:
            logger.warning(f"购买 IP 返回空 (attempt {attempt+1}/3)")
            if attempt == 2:
                return None
            await asyncio.sleep(1)
            continue

        rec = records[0]
        expire_at = (datetime.now(timezone.utc)
                     + timedelta(seconds=self.ttl_seconds)).isoformat()

        # 连通性检测
        alive = await self._check_ip_alive(rec)
        if alive:
            # 写入数据库
            with self.storage.get_connection() as conn:
                conn.execute(
                    "INSERT INTO proxy_pool "
                    "(ip, port, protocol, city, username, password, "
                    " expire_at, use_count, max_use, status, fail_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'in_use', 0)",
                    (rec.ip, rec.port, rec.protocol or "http",
                     rec.city, rec.username, rec.password,
                     expire_at, self.max_use),
                )
                rec.id = conn.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0]
            logger.info(f"购买并验证 IP: {rec.ip}:{rec.port}")
            return rec
        else:
            logger.warning(f"IP 不可用: {rec.ip}:{rec.port} (attempt {attempt+1}/3)")
            # 不可用的 IP 不写入数据库
            if attempt == 2:
                return None
            await asyncio.sleep(0.5)

    return None
```

**Step 3: 保留同步 `acquire()` 作为降级/兼容（内部转发到异步）**

保留原有 `acquire()` 方法但改为先查池不买（仅用于不需要买的场景或后台线程）:

```python
def acquire(self) -> ProxyRecord | None:
    """同步申请 IP（仅查池，不购买）。

    用于 health_check 等不需要触发购买的场景。
    爬虫主流程请用 ``acquire_async()``。
    """
    if not self.enabled:
        return None
    return self._acquire_from_pool()
```

原 `acquire()` 的逻辑提取为 `_acquire_from_pool()`:

```python
def _acquire_from_pool(self) -> ProxyRecord | None:
    """从数据库池中取一个可用 IP，标记 in_use。"""
    now_iso = _now_iso()
    with self.storage.get_connection() as conn:
        row = conn.execute(
            "SELECT id, ip, port, protocol, city, expire_at, use_count, max_use, "
            "       username, password "
            "FROM proxy_pool "
            "WHERE status = ? AND expire_at > ? AND use_count < max_use "
            "ORDER BY last_used_at NULLS FIRST, fetched_at ASC "
            "LIMIT 1",
            (STATUS_IDLE, now_iso),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE proxy_pool SET status = ?, last_used_at = ? WHERE id = ?",
            (STATUS_IN_USE, now_iso, row["id"]),
        )
        rec = ProxyRecord(
            id=row["id"], ip=row["ip"], port=row["port"],
            protocol=row["protocol"], city=row["city"],
            expire_at=row["expire_at"], use_count=row["use_count"],
            max_use=row["max_use"],
            username=row["username"], password=row["password"],
        )
    logger.debug(f"acquire IP: {rec.ip}:{rec.port} (use_count={rec.use_count})")
    return rec
```

**Step 4: 先写测试再写代码（TDD）**

```python
import asyncio

@pytest.mark.asyncio
async def test_acquire_async_from_pool(pool):
    """池中有 IP 时直接返回。"""
    rec = await pool.acquire_async()
    assert rec is not None
    assert rec.ip == "1.1.1.1"

@pytest.mark.asyncio
async def test_acquire_async_pool_empty_buys_one(storage, cfg):
    """池空时异步买 1 个并返回。"""
    import httpx
    provider = MagicMock()
    provider.fetch_async = AsyncMock(return_value=[
        ProxyRecord(ip="2.2.2.2", port=8080, username="u", password="p"),
    ])
    p = ProxyPool(storage, cfg, provider)
    # Mock 连通性检测为成功
    p._check_ip_alive = AsyncMock(return_value=True)
    rec = await p.acquire_async()
    assert rec is not None
    assert rec.ip == "2.2.2.2"
    provider.fetch_async.assert_called_once_with(num=1)

@pytest.mark.asyncio
async def test_acquire_async_ip_dead_retries(storage, cfg):
    """IP 不可用时重试购买。"""
    provider = MagicMock()
    provider.fetch_async = AsyncMock(return_value=[
        ProxyRecord(ip="dead", port=8080),
    ])
    p = ProxyPool(storage, cfg, provider)
    p._check_ip_alive = AsyncMock(return_value=False)
    rec = await p.acquire_async()
    assert rec is None  # 3 次都失败
    assert provider.fetch_async.call_count == 3
```

**Step 5: 运行测试验证**

```bash
pytest tests/test_proxy_pool.py -v -q
```

---

### Task 3: IP 连通性检测

**Files:**
- Modify: `proxy/pool.py`

**Step 1: 新增 `_check_ip_alive()` 方法**

```python
async def _check_ip_alive(self, rec: ProxyRecord, timeout: float = 3.0) -> bool:
    """检测 IP 是否真实可用。

    用目标 IP 做代理发 HTTP GET 到 httpbin.org/ip，3 秒超时。

    :param rec: IP 记录
    :param timeout: 超时秒数
    :return: True 可用，False 不可用
    """
    auth = ""
    if rec.username and rec.password:
        auth = f"{rec.username}:{rec.password}@"
    proxy_url = f"http://{auth}{rec.ip}:{rec.port}"
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=httpx.Timeout(timeout),
        ) as client:
            resp = await client.get("http://httpbin.org/ip")
            return resp.status_code == 200
    except Exception as e:
        logger.debug(f"IP 检测失败 {rec.ip}:{rec.port}: {e}")
        return False
```

**Step 2: 写测试**

```python
@pytest.mark.asyncio
async def test_check_ip_alive_success():
    """IP 连通性检测通过。"""
    rec = ProxyRecord(ip="1.1.1.1", port=8080)
    pool = ProxyPool(MagicMock(), MagicMock(), None)
    import httpx
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
    alive = await pool._check_ip_alive(rec, timeout=1)
    assert alive is True

@pytest.mark.asyncio
async def test_check_ip_alive_fail():
    """IP 连通性检测失败（超时/连接拒绝）。"""
    rec = ProxyRecord(ip="1.1.1.1", port=8080)
    pool = ProxyPool(MagicMock(), MagicMock(), None)
    import httpx
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
    alive = await pool._check_ip_alive(rec, timeout=1)
    assert alive is False
```

---

### Task 4: RequestPool 切换为 async acquire

**Files:**
- Modify: `core/request_pool.py:195-230`

**Step 1: `_process_url_async` 中改为 await 调用**

```python
# 原代码 (line 219-225):
proxy_record = None
proxy_url = None
if self.proxy_pool is not None:
    proxy_record = self.proxy_pool.acquire()
    if proxy_record is not None:
        proxy_url = self._build_proxy_url(proxy_record)

# 改为:
proxy_record = None
proxy_url = None
if self.proxy_pool is not None:
    proxy_record = await self.proxy_pool.acquire_async()
    if proxy_record is not None:
        proxy_url = self._build_proxy_url(proxy_record)
```

**Step 2: 检查是否有其他处调用 sync acquire**

```bash
rg "proxy_pool\.acquire\(" core/ --files-with-matches
```

预期: 只有 `request_pool.py` 在新流程中调用，旧的 `pool.py` 内部保留 sync `acquire()` 给 health_check 用。

---

### Task 5: 清理废弃代码

**Files:**
- Modify: `core/config_manager.py:37`
- Modify: `main.py:243-246, 277`
- Modify: `web-ui/src/views/ConfigView.vue:24, 91`

**Step 1: 删除 `proxy_supplement_interval` 配置项**

`config_manager.py` line 37: 删除 `("proxy_supplement_interval", ...)` 行

**Step 2: main.py 删除 warmup + supplement_loop 调用**

```python
# main.py:243-246
# 删掉 warmup() + start_supplement_loop()
# 改为只保留:
if config_mgr.get_bool("proxy_enabled", default=False):
    proxy_pool.start_health_check_loop()

# main.py:277
# 删掉 stop_supplement_loop()
```

**Step 3: 前端 ConfigView.vue**

- LABEL_MAP: 删除 `proxy_supplement_interval` 行
- CATEGORY_MAP tab 0: 从 key 数组中移除 `proxy_supplement_interval`

**Step 4: 更新 test_config_manager.py**

删除 `proxy_supplement_interval` 的默认值断言行（如果存在）。

---

### Task 6: 全文测试 + 清理

**Step 1: 运行全量测试**

```bash
pytest tests/ -q
```

**Step 2: 清理 ProxyPool 内部**

确认以下已删除：
- `warmup()`
- `start_supplement_loop()` / `stop_supplement_loop()`
- `supplement_interval` property
- `_supplement()`
- `_supplement_lock`
- `_supplement_thread`
- `_supplement_stop`
- `_last_acquire_time`

**Step 3: 更新前端 Web UI dist**

```bash
cd web-ui && pnpm build && cp -r dist/* ../web/static/
```

**Step 4: 提交**

```bash
git add -A
git commit -m "refactor: IP acquire JIT模式 + 连通性检测"
```

---

### 改动文件总览

| 文件 | 操作 | 内容 |
|------|------|------|
| `proxy/provider.py` | 修改 | 加 `fetch_async` / `_do_fetch_async` |
| `proxy/pool.py` | 重写 | sync acquire → async acquire_async + _check_ip_alive + 删 warmup/supplement |
| `core/request_pool.py` | 修改 | `proxy_pool.acquire()` → `await proxy_pool.acquire_async()` |
| `core/config_manager.py` | 修改 | 删 `proxy_supplement_interval` |
| `main.py` | 修改 | 删 warmup/supplement_loop 调用 |
| `web-ui/.../ConfigView.vue` | 修改 | 删 `proxy_supplement_interval` UI |
| `tests/test_proxy_pool.py` | 修改 | 新 async 测试 + 删废弃测试 + 修复现有 |
| `tests/test_config_manager.py` | 修改 | 修正默认值断言 |

---

### 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| `provider.fetch_async` 首次调用慢（巨量 API 延迟） | 低 | 仅池空时触发，正常情况 pool 有就复用 |
| `_check_ip_alive` 用国内 IP 访问 httpbin.org 可能慢 | 中 | 3s 超时，失败跳过重试下一个 |
| async 重构影响测试隔离 | 低 | 已有 asyncio-mode=strict，逐个测试迁移 |
