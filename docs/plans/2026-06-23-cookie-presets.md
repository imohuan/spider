# Cookie 预设配置 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增 Cookie 预设管理功能 —— 按域名维度存储 EditThisCookie JSON，任务入队时自动匹配并注入 cookie，HTTP/Browser/CDP 三种模式均支持。

**Architecture:** 新表 `cookie_presets`（独立 CRUD）→ `queue API` 入队时按域名匹配并写入 `request_config.cookies` → `RequestPool` 三种模式在请求阶段读取并注入。前端用 AxDialog 弹窗管理预设。

**Tech Stack:** Python 3.13 + Flask + SQLite + Vue 3 + TypeScript + ax-ui-kit (AxDialog/AxButton/AxInput/AxSwitch)

---

### Task 1: Storage — cookie_presets 表 + CRUD

**Files:**
- Modify: `core/storage.py` → 在 `_SYSTEM_SCHEMA` 末端新增建表 SQL，新增 `upsert_cookie_preset` / `list_cookie_presets` / `delete_cookie_preset` / `get_cookie_preset` / `match_cookie_preset` 方法

**Step 1: 扩展 tests/test_storage.py，先写 failing test**

```python
def test_cookie_presets_schema_exists(storage):
    """cookie_presets 表存在且核心列齐全。"""
    storage._init_schema()
    cols = storage.execute("PRAGMA table_info(cookie_presets)", fetch="all")
    col_names = {r[1] for r in cols}
    assert col_names >= {"id", "name", "domain", "cookies_json", "enabled", "created_at", "updated_at"}


def test_upsert_cookie_preset(storage):
    storage._init_schema()
    cookies = [{"domain": "58.com", "name": "token", "value": "abc123"}]
    preset_id = storage.upsert_cookie_preset(
        name="58同城-登录",
        domain="jianyangshi.58.com",
        cookies=json.dumps(cookies, ensure_ascii=False),
    )
    assert preset_id >= 1

    row = storage.execute("SELECT * FROM cookie_presets WHERE id = ?", (preset_id,), fetch="one")
    assert row[1] == "58同城-登录"
    assert row[2] == "jianyangshi.58.com"


def test_match_cookie_preset(storage):
    storage._init_schema()
    storage.upsert_cookie_preset("58-已登录", "jianyangshi.58.com", '[{"name":"t","value":"v"}]')
    storage.upsert_cookie_preset("淘宝-已登录", "taobao.com", '[{"name":"s","value":"x"}]')

    # 精确域名匹配
    result = storage.match_cookie_preset("https://jianyangshi.58.com/shengyizr/pn2/")
    assert result is not None
    assert result[1] == "58-已登录"  # name 列

    # 不匹配
    result = storage.match_cookie_preset("https://www.baidu.com/")
    assert result is None
```

**Step 2: 跑测试确认 FAIL**

Run: `pytest tests/test_storage.py::test_cookie_presets_schema_exists tests/test_storage.py::test_upsert_cookie_preset tests/test_storage.py::test_match_cookie_preset -v`

Expected: FAIL — 方法不存在

**Step 3: 实现 — storage.py 加表 + 方法**

在 `_SYSTEM_SCHEMA` 尾部追加建表 SQL：

```sql
CREATE TABLE IF NOT EXISTS cookie_presets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    domain        TEXT NOT NULL,
    cookies_json  TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cookie_presets_domain ON cookie_presets(domain);
```

新增方法（写在 `Storage` 类末尾，`enqueue_image` 之后）：

```python
def upsert_cookie_preset(
    self, name: str, domain: str, cookies_json: str, preset_id: int | None = None
) -> int:
    """创建或更新 Cookie 预设。preset_id 为 None 时 INSERT，否则 UPDATE。

    :return: 预设 id
    """
    with self.get_connection() as conn:
        if preset_id is not None:
            conn.execute(
                "UPDATE cookie_presets SET name=?, domain=?, cookies_json=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (name, domain, cookies_json, preset_id),
            )
            return preset_id
        else:
            cursor = conn.execute(
                "INSERT INTO cookie_presets (name, domain, cookies_json) VALUES (?, ?, ?)",
                (name, domain, cookies_json),
            )
            return cursor.lastrowid


def get_cookie_preset(self, preset_id: int) -> tuple | None:
    """按 id 查询单条预设。"""
    return self.execute(
        "SELECT id, name, domain, cookies_json, enabled, created_at, updated_at "
        "FROM cookie_presets WHERE id=?",
        (preset_id,), fetch="one",
    )


def list_cookie_presets(self) -> list[tuple]:
    """列出全部预设（含禁用的），按 updated_at 倒序。"""
    return self.execute(
        "SELECT id, name, domain, cookies_json, enabled, created_at, updated_at "
        "FROM cookie_presets ORDER BY updated_at DESC",
        fetch="all",
    )


def delete_cookie_preset(self, preset_id: int) -> bool:
    """删除预设，返回是否删到了行。"""
    with self.get_connection() as conn:
        cur = conn.execute("DELETE FROM cookie_presets WHERE id=?", (preset_id,))
        return cur.rowcount > 0


def match_cookie_preset(self, url: str) -> tuple | None:
    """按 URL 域名匹配启用的 Cookie 预设。

    从 url 提取域名 → 查 cookie_presets WHERE domain=? AND enabled=1。
    返回完整行 tuple(id, name, domain, cookies_json, enabled, created_at, updated_at) 或 None。
    """
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    if not domain:
        return None
    return self.execute(
        "SELECT id, name, domain, cookies_json, enabled, created_at, updated_at "
        "FROM cookie_presets WHERE domain=? AND enabled=1 LIMIT 1",
        (domain,), fetch="one",
    )
```

**Step 4: 跑测试确认 PASS**

Run: `pytest tests/test_storage.py::test_cookie_presets_schema_exists tests/test_storage.py::test_upsert_cookie_preset tests/test_storage.py::test_match_cookie_preset -v`

Expected: 3 PASS

**Step 5: Commit**

```bash
git add core/storage.py tests/test_storage.py
git commit -m "feat(storage): add cookie_presets table and CRUD methods"
```

---

### Task 2: API — cookie_presets 蓝图

**Files:**
- Create: `web/api/cookie_presets.py`
- Modify: `web/api/__init__.py` → 注册新蓝图

**Step 1: 创建 web/api/cookie_presets.py**

```python
"""Cookie 预设管理 API。"""
from __future__ import annotations
import json
from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('cookie_presets', __name__)


@bp.route('', methods=['GET'])
def list_presets():
    s = Storage()
    rows = s.list_cookie_presets()
    items = [
        {
            'id': r[0],
            'name': r[1],
            'domain': r[2],
            'cookies_json': r[3],
            'enabled': bool(r[4]),
            'created_at': r[5],
            'updated_at': r[6],
        }
        for r in rows
    ]
    return jsonify({'items': items})


@bp.route('', methods=['POST'])
def create_or_update_preset():
    data = request.get_json(silent=True) or {}
    name = (data.get('name', '') or '').strip()
    domain = (data.get('domain', '') or '').strip()
    cookies_json = (data.get('cookies_json', '') or '').strip()

    if not name or not domain:
        return jsonify({'ok': False, 'error': 'name and domain are required'}), 400

    # 校验 cookies_json 是合法 JSON（不要求非空，允许空数组）
    if cookies_json:
        try:
            json.loads(cookies_json)
        except json.JSONDecodeError:
            return jsonify({'ok': False, 'error': 'cookies_json is not valid JSON'}), 400

    preset_id = data.get('id') or None
    try:
        s = Storage()
        new_id = s.upsert_cookie_preset(name=name, domain=domain, cookies_json=cookies_json, preset_id=preset_id)
        return jsonify({'ok': True, 'id': new_id})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@bp.route('/<int:pid>', methods=['DELETE'])
def delete_preset(pid: int):
    s = Storage()
    ok = s.delete_cookie_preset(pid)
    if ok:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'not found'}), 404


@bp.route('/<int:pid>/toggle', methods=['POST'])
def toggle_preset(pid: int):
    """切换 enabled 状态。"""
    row = Storage().get_cookie_preset(pid)
    if row is None:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    new_enabled = 0 if row[4] else 1
    Storage().execute(
        "UPDATE cookie_presets SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (new_enabled, pid), fetch="none",
    )
    return jsonify({'ok': True, 'enabled': bool(new_enabled)})


@bp.route('/<int:pid>', methods=['GET'])
def get_preset(pid: int):
    row = Storage().get_cookie_preset(pid)
    if row is None:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    return jsonify({
        'id': row[0], 'name': row[1], 'domain': row[2],
        'cookies_json': row[3], 'enabled': bool(row[4]),
        'created_at': row[5], 'updated_at': row[6],
    })
```

**Step 2: 注册到 web/api/__init__.py**

在 `register_blueprints` 尾部追加：

```python
from web.api.cookie_presets import bp as cookie_presets_bp
app.register_blueprint(cookie_presets_bp, url_prefix='/api/cookie-presets')
```

**Step 3: 手动测试 API**

```bash
# 启动服务器
cd web && python dev.py &
sleep 2

# 创建预设
curl -s -X POST http://localhost:5000/api/cookie-presets \
  -H 'Content-Type: application/json' \
  -d '{"name":"58-登录","domain":"jianyangshi.58.com","cookies_json":"[{\"domain\":\"58.com\",\"name\":\"token\",\"value\":\"abc\"}]"}'

# 列出
curl -s http://localhost:5000/api/cookie-presets | python -m json.tool

# 切换
curl -s -X POST http://localhost:5000/api/cookie-presets/1/toggle

# 删除
curl -s -X DELETE http://localhost:5000/api/cookie-presets/1
```

**Step 4: Commit**

```bash
git add web/api/cookie_presets.py web/api/__init__.py
git commit -m "feat(api): add cookie_presets CRUD blueprint"
```

---

### Task 3: queue API — 入队时自动匹配 Cookie

**Files:**
- Modify: `web/api/queue.py` → `create_task()` 内部新增 cookie 匹配逻辑

**验证需求：**
- 前端传了 `request_config` 且已含 `cookies` → 不覆盖（前端优先）
- 前端未传或未含 `cookies` → 自动匹配 `cookie_presets` 表，命中则注入
- 匹配失败（无匹配规则）→ 不注入，不影响入队

**修改点：** `web/api/queue.py:86` 行之后，`s.enqueue()` 调用之前插入匹配逻辑。

```python
# 85:    request_config = data.get('request_config') or None
# 86:     ← 插入 cookie 匹配逻辑
    # Cookie 预设自动匹配（不覆盖前端显式传入的 cookies）
    if not request_config or 'cookies' not in request_config:
        matched = s.match_cookie_preset(url)
        if matched is not None:
            try:
                preset_cookies = json.loads(matched[3])  # cookies_json 列
                if isinstance(preset_cookies, list) and len(preset_cookies) > 0:
                    request_config = request_config or {}
                    request_config['cookies'] = _convert_edit_this_cookie(preset_cookies)
            except (json.JSONDecodeError, Exception):
                pass  # 格式异常静默忽略，不影响入队
```

新增工具函数（文件顶部 `import json as _json` 之后）：

```python
def _convert_edit_this_cookie(raw: list) -> dict:
    """将 EditThisCookie JSON 转换为 httpx cookies 格式。
    
    EditThisCookie: [{"domain":"58.com","name":"token","value":"abc","path":"/",...}, ...]
    httpx 格式: {name: value, ...}
    """
    return {item["name"]: item["value"] for item in raw if "name" in item and "value" in item}
```

**手动测试：**

```bash
# 1. 先创建 cookie 预设
curl -s -X POST http://localhost:5000/api/cookie-presets \
  -H 'Content-Type: application/json' \
  -d '{"name":"58","domain":"jianyangshi.58.com","cookies_json":"[{\"domain\":\"58.com\",\"name\":\"x\",\"value\":\"y\"}]"}'

# 2. 入队（不带 cookies）
curl -s -X POST http://localhost:5000/api/queue \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://jianyangshi.58.com/shengyizr/"}'

# 3. 验证 queue 表 request_config 包含 cookies
sqlite3 data/58_crawler.db "SELECT request_config FROM queue ORDER BY id DESC LIMIT 1"
# 预期输出: {"cookies": {"x": "y"}}

# 4. 入队（前端已传入 cookies → 不覆盖）
curl -s -X POST http://localhost:5000/api/queue \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://jianyangshi.58.com/","request_config":{"cookies":{"custom":"val"}}}'

# 预期 request_config 保持 {"cookies":{"custom":"val"}}
```

**Commit:**

```bash
git add web/api/queue.py
git commit -m "feat(queue): auto-match cookie presets on task enqueue"
```

---

### Task 4: RequestPool — Browser/CDP 模式注入 Cookie

**Files:**
- Modify: `core/request_pool.py` → `_process_url_async` 中 Browser/CDP 分支加 cookie 注入，新增 `_extract_cookies_from_task` 辅助方法

**背景：** HTTP 模式已在 `_fetch_http():592` 读取 `rc.get("cookies", {})` 并传给 httpx。但 Browser/CDP 模式没有。

**Step 1: 新增辅助方法**（`_fetch_http` 方法之前，约 line 540）：

```python
def _extract_cookies_from_task(self, task: dict) -> list[dict]:
    """从 task.request_config 提取 cookies 并转为 Playwright 格式。
    
    queue 表 request_config.cookies 可能是：
    - httpx 格式 {name: value, ...}     → 转为 [{name, value, domain, path: "/"}]
    - EditThisCookie 格式 [{...}, ...]  → 原样返回

    :return: Playwright add_cookies 兼容的 cookie 列表
    """
    rc_str = task.get("request_config")
    if not rc_str:
        return []
    try:
        rc = json.loads(rc_str) if isinstance(rc_str, str) else rc_str
    except (json.JSONDecodeError, TypeError):
        return []
    cookies = rc.get("cookies", {})
    if not cookies:
        return []

    # httpx 格式 {name: value} → Playwright 格式
    from urllib.parse import urlparse
    domain = urlparse(task["url"]).netloc
    if isinstance(cookies, dict):
        return [
            {"name": k, "value": v, "domain": domain, "path": "/"}
            for k, v in cookies.items()
        ]
    # EditThisCookie 格式 [{name, value, domain, path, ...}]
    if isinstance(cookies, list):
        return cookies
    return []
```

**Step 2: Browser 模式注入**（`_browser_page_lifecycle` 调用之前，约 line 392）

在 `page = await self._browser_page_lifecycle(...)` 调用之前插入：

```python
# Cookie 注入（Browser 模式）
playwright_cookies = self._extract_cookies_from_task(task)
if playwright_cookies:
    try:
        # 需要先创建 page 获取 context，再注入 cookie，再 goto
        page = await self.browser.new_page(url=None, proxy=proxy_url)
        await page.context.add_cookies(playwright_cookies)
        
        on_page_created = getattr(parser, "on_page_created", None)
        if on_page_created is not None:
            await on_page_created(page, url)
        timeout_ms = self.config.get_int("request_timeout", 30) * 1000
        browser_start = time.monotonic()
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        browser_duration_ms = int((time.monotonic() - browser_start) * 1000)
        
        on_page_loaded = getattr(parser, "on_page_loaded", None)
        if on_page_loaded is not None:
            await on_page_loaded(page, url)
        on_wait_ready = getattr(parser, "on_wait_ready", None)
        if on_wait_ready is not None:
            await on_wait_ready(page)
    except Exception as e:
        logger.warning(f"Cookie 注入失败，降级为标准流程: {e}")
        page = None  # 触发下方标准 _browser_page_lifecycle
# 无 cookie 或注入失败了 → 走标准流程
if page is None:
    page, browser_duration_ms = await self._browser_page_lifecycle(
        self.browser, url, parser, proxy_url,
    )
```

⚠️ **简化版：** 如果觉得上面内联代码太多，可以复用 `_browser_page_lifecycle`，在其中加一个可选参数 `cookies: list[dict] | None = None`，page 创建后注入。

**推荐简化方案**（改 `_browser_page_lifecycle` 签名）：

```python
async def _browser_page_lifecycle(
    self, browser: Any, url: str, parser: Any, proxy_url: str | None,
    cookies: list[dict] | None = None,
) -> tuple[Any, int]:
    start = time.monotonic()
    page = await browser.new_page(url=None, proxy=proxy_url)

    # Cookie 注入（在 goto 之前）
    if cookies:
        try:
            await page.context.add_cookies(cookies)
        except Exception as e:
            logger.warning(f"Cookie 注入失败: {e}")

    # ... 后续 goto / 生命周期钩子不变
```

然后在 Browser/CDP 分支调用时传入：

```python
# Browser 分支
playwright_cookies = self._extract_cookies_from_task(task)
page, browser_duration_ms = await self._browser_page_lifecycle(
    self.browser, url, parser, proxy_url, cookies=playwright_cookies,
)

# CDP 分支 (同样修改 line 251)
playwright_cookies = self._extract_cookies_from_task(task)
page, cdp_duration_ms = await self._browser_page_lifecycle(
    self.cdp_browser, url, parser, proxy_url, cookies=playwright_cookies,
)
```

**Step 3: 跑现有测试确保无回归**

```bash
pytest tests/test_request_pool.py -v
```

**Step 4: Commit**

```bash
git add core/request_pool.py
git commit -m "feat(request-pool): inject cookies into browser/CDP mode from task config"
```

---

### Task 5: 前端 — CookiePresetsView 页面 + AxDialog 弹窗

**Files:**
- Create: `web-ui/src/views/CookiePresetsView.vue`
- Modify: `web-ui/src/router/index.ts` → 新增路由
- Modify: `web-ui/src/api/index.ts` → 新增 `cookiePresetsApi`
- Modify: `web-ui/src/components/layout/CrawlerSidebar.vue` → 新增加导航项

**Step 1: 新增 API 方法** (`web-ui/src/api/index.ts` 尾部追加)

```ts
export const cookiePresetsApi = {
  list: () => api.get('/cookie-presets'),
  get: (id: number) => api.get(`/cookie-presets/${id}`),
  save: (payload: { name: string; domain: string; cookies_json: string; id?: number }) =>
    api.post('/cookie-presets', payload),
  delete: (id: number) => api.del(`/cookie-presets/${id}`),
  toggle: (id: number) => api.post(`/cookie-presets/${id}/toggle`),
}
```

**Step 2: 新增路由** (`web-ui/src/router/index.ts` 在 `config` 路由之后插入)

```ts
{ path: 'cookie-presets', name: 'cookie-presets', component: () => import('@/views/CookiePresetsView.vue'), meta: { title: 'Cookie 预设', desc: 'cookie_presets 表 · 站点登录态管理' } },
```

**Step 3: 侧栏导航** (`web-ui/src/components/layout/CrawlerSidebar.vue`) 在「运维」组里追加

```ts
{ id: 'cookie-presets', name: 'Cookie 预设', icon: 'cookie', path: '/cookie-presets' },
```

放在 `config` 项之后。

**Step 4: 创建 CookiePresetsView.vue**

使用 `<AxDialog>` 做新增/编辑弹窗，`<AxButton>` / `<AxInput>` / `<AxSwitch>` 做列表和表单。

核心结构：
- 顶部工具栏：`<AxButton icon="add">添加 Cookie 预设</AxButton>`
- 预设列表卡片（每条：域名 + 名称 + 启用开关 + 编辑/删除按钮）
- 弹窗 `<AxDialog>`：name（AxInput）、domain（AxInput）、cookies_json（AxInput multiline，rows=8）、保存/取消

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { AxDialog, AxButton, AxInput, AxSwitch, useNotify } from '@/components/ui'
import { cookiePresetsApi } from '@/api'

const notify = useNotify()
const presets = ref<any[]>([])
const dialogOpen = ref(false)
const editing = ref<{ id?: number; name: string; domain: string; cookies_json: string }>({
  name: '', domain: '', cookies_json: '',
})

async function load() {
  const res = await cookiePresetsApi.list()
  presets.value = res.data.items
}

function openAdd() {
  editing.value = { name: '', domain: '', cookies_json: '' }
  dialogOpen.value = true
}

function openEdit(p: any) {
  editing.value = { id: p.id, name: p.name, domain: p.domain, cookies_json: p.cookies_json }
  dialogOpen.value = true
}

async function save(close: () => void) {
  const { name, domain, cookies_json, id } = editing.value
  if (!name.trim() || !domain.trim()) {
    notify.warning('名称和域名不能为空')
    return
  }
  await cookiePresetsApi.save({ name: name.trim(), domain: domain.trim(), cookies_json, id })
  notify.success(id ? '已更新' : '已创建')
  close()
  load()
}

async function remove(id: number) {
  await cookiePresetsApi.delete(id)
  notify.success('已删除')
  load()
}

async function toggle(id: number) {
  await cookiePresetsApi.toggle(id)
  load()
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-primary">Cookie 预设</h2>
      <AxButton icon="add" @click="openAdd">添加预设</AxButton>
    </div>

    <!-- 空状态 -->
    <div v-if="!presets.length" class="text-center py-12 text-secondary text-sm">
      暂无 Cookie 预设，点击「添加预设」创建
    </div>

    <!-- 预设卡片列表 -->
    <div class="grid gap-3">
      <div
        v-for="p in presets" :key="p.id"
        class="flex items-center justify-between p-4 rounded-lg border border-outline-variant bg-surface-container-low"
      >
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium text-primary truncate">{{ p.name }}</div>
          <div class="text-xs text-secondary mt-0.5">{{ p.domain }}</div>
          <div class="text-[10px] text-secondary mt-1">
            {{ (() => { try { const arr = JSON.parse(p.cookies_json); return Array.isArray(arr) ? `${arr.length} 条 cookie` : '' } catch { return '格式异常' } })() }}
          </div>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <AxSwitch :model-value="p.enabled" @update:model-value="toggle(p.id)" />
          <AxButton variant="ghost" size="icon" icon="edit" @click="openEdit(p)" />
          <AxButton variant="ghost" size="icon" icon="delete" @click="remove(p.id)" />
        </div>
      </div>
    </div>

    <!-- 弹窗 -->
    <AxDialog v-model="dialogOpen" :title="editing.id ? '编辑预设' : '添加预设'" icon="cookie">
      <template #default="{ close, setFocusableRef }">
        <div class="space-y-3">
          <AxInput :ref="setFocusableRef" v-model="editing.name" placeholder="预设名称（如：58同城-已登录）" />
          <AxInput v-model="editing.domain" placeholder="匹配域名（如：jianyangshi.58.com）" />
          <AxInput
            v-model="editing.cookies_json"
            placeholder="EditThisCookie 导出的 JSON（粘贴到这里）"
            multiline :rows="8"
          />
          <p class="text-[10px] text-secondary">
            使用 EditThisCookie 浏览器插件 → 导出 → 复制 JSON → 粘贴到上方输入框
          </p>
        </div>
      </template>
      <template #footer="{ close }">
        <AxButton variant="outline" @click="close">取消</AxButton>
        <AxButton @click="save(close)">保存</AxButton>
      </template>
    </AxDialog>
  </div>
</template>
```

**Step 5: 构建前端验证无编译错误**

```bash
cd web-ui && pnpm build
```

**Step 6: Commit**

```bash
git add web-ui/src/views/CookiePresetsView.vue web-ui/src/router/index.ts web-ui/src/api/index.ts web-ui/src/components/layout/CrawlerSidebar.vue
git commit -m "feat(ui): add CookiePresetsView with AxDialog for preset management"
```

---

### Task 6: 测试 — queues API 入队 cookie 匹配

**Files:**
- Create: `tests/test_cookie_presets_api.py`

```python
"""测试 cookie_presets 蓝图 API。"""
import json
import pytest
from web.app import create_app
from core.storage import Storage


@pytest.fixture
def app():
    app = create_app(db_path=":memory:")
    app.testing = True
    with app.app_context():
        Storage()._init_schema()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_create_and_list(client):
    resp = client.post("/api/cookie-presets", json={
        "name": "Test", "domain": "example.com",
        "cookies_json": '[{"name":"t","value":"v"}]',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"]
    assert data["id"] >= 1

    resp = client.get("/api/cookie-presets")
    data = resp.get_json()
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert item["name"] == "Test"
    assert item["domain"] == "example.com"


def test_toggle_and_delete(client):
    # 创建
    resp = client.post("/api/cookie-presets", json={
        "name": "T", "domain": "x.com", "cookies_json": "[]",
    })
    pid = resp.get_json()["id"]

    # 关闭
    resp = client.post(f"/api/cookie-presets/{pid}/toggle")
    assert resp.get_json()["enabled"] is False

    # 开启
    resp = client.post(f"/api/cookie-presets/{pid}/toggle")
    assert resp.get_json()["enabled"] is True

    # 删除
    resp = client.delete(f"/api/cookie-presets/{pid}")
    assert resp.get_json()["ok"]


def test_enqueue_cookie_matching(client):
    """入队时自动匹配 cookie 预设。"""
    # 创建预设
    client.post("/api/cookie-presets", json={
        "name": "TestLogin", "domain": "test.example.com",
        "cookies_json": '[{"name":"session","value":"abc123"}]',
    })

    # 入队（不传 request_config）
    resp = client.post("/api/queue", json={
        "url": "https://test.example.com/page",
    })
    assert resp.status_code == 200

    # 验证 request_config 被写入了 cookies
    s = Storage()
    row = s.execute(
        "SELECT request_config FROM queue WHERE url='https://test.example.com/page'",
        fetch="one",
    )
    assert row is not None
    rc = json.loads(row[0])
    assert "cookies" in rc
    assert rc["cookies"] == {"session": "abc123"}


def test_enqueue_preserves_existing_cookies(client):
    """入队时已传 cookies → 不覆盖。"""
    client.post("/api/cookie-presets", json={
        "name": "Login", "domain": "preserve.example.com",
        "cookies_json": '[{"name":"preset","value":"should-not-appear"}]',
    })
    resp = client.post("/api/queue", json={
        "url": "https://preserve.example.com/",
        "request_config": {"cookies": {"custom": "keep-me"}},
    })
    assert resp.status_code == 200
    s = Storage()
    row = s.execute(
        "SELECT request_config FROM queue WHERE url='https://preserve.example.com/'",
        fetch="one",
    )
    rc = json.loads(row[0])
    assert rc["cookies"] == {"custom": "keep-me"}
```

**Step 2: 跑测试**

```bash
pytest tests/test_cookie_presets_api.py -v
```

**Step 3: Commit**

```bash
git add tests/test_cookie_presets_api.py
git commit -m "test: add cookie_presets API integration tests"
```

---

### Task 7: 全量回归

**Step 1: 跑全部测试**

```bash
pytest tests/ -v --tb=short
```

确保之前 394+ 测试无回归。

**Step 2: 前端构建**

```bash
cd web-ui && pnpm build
```

**Step 3: 启动集成验证**

```bash
python main.py --serve
# 浏览器访问 http://localhost:5000 → 侧栏出现「Cookie 预设」
# 添加预设 → 入队任务 → 验证 request_config 含 cookies
```

---

## 变更总览

| 层 | 文件 | 操作 |
|---|---|---|
| Storage | `core/storage.py` | +schema +6 方法 |
| API | `web/api/cookie_presets.py` | 新建，6 个路由 |
| API | `web/api/__init__.py` | +1 blueprint |
| API | `web/api/queue.py` | +cookie 匹配逻辑 |
| Engine | `core/request_pool.py` | +Browser/CDP cookie 注入 |
| UI | `web-ui/src/views/CookiePresetsView.vue` | 新建页面 |
| UI | `web-ui/src/router/index.ts` | +1 route |
| UI | `web-ui/src/api/index.ts` | +cookiePresetsApi |
| UI | `web-ui/src/components/layout/CrawlerSidebar.vue` | +1 nav item |
| Test | `tests/test_storage.py` | +3 tests |
| Test | `tests/test_cookie_presets_api.py` | 新建，4 tests |
