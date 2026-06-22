# test-url 重设计实现计划

> **For Claude:** 用 executing-plans 实现这个计划，逐任务推进。

**目标:** 重写 `/api/config/test-url` 走完整 Parser pipeline（fetch → parse → 返回结构化数据），前端不再让用户选择 Browser/HTTP 模式。

**架构:** 后端复用 `RequestPool` 的 fetch 逻辑 + `Registry.match()` 找到对应 Parser + `NoOpStorage` 屏蔽副作用（不入队/不存 DB/不下载图片），前端简化为 URL 输入 + 发送按钮。

**技术栈:** Python Flask + Playwright + httpx + Vue 3 + TypeScript

---

### Task 1: 实现 FakeStorage — 屏蔽写操作的存储代理

**目的:** Parser 在 test-url 场景下仍能调用 `self.storage.enqueue()` 等写方法，但实际不产生任何副作用。

**文件:**
- 创建: `core/fake_storage.py`

**Step 1: 创建 FakeStorage 代理类**

`core/fake_storage.py`:

```python
"""测试用 FakeStorage — 代理真实 Storage，屏蔽写操作。"""
from __future__ import annotations


class FakeStorage:
    """代理真实 Storage，屏蔽以下写操作:
    - enqueue() / enqueue_image() — 不入队新 URL/图片
    - save_business_data() — 不写入业务数据
    - create_request() / mark_request_* — 不创建请求记录
    其他方法（execute/ensure_business_table 等读操作）透传给真实 Storage。
    """

    def __init__(self, real_storage):
        self._s = real_storage

    # ── 屏蔽的写方法 ──

    def enqueue(self, url, **kwargs):
        return None

    def enqueue_image(self, url, **kwargs):
        return None

    def save_business_data(self, table_name, rows):
        return None

    def create_request(self, **kwargs):
        return -1

    def mark_request_success(self, **kwargs):
        pass

    def mark_request_failed(self, **kwargs):
        pass

    # ── 透传的读写方法 ──

    def execute(self, sql, params=(), fetch="none"):
        return self._s.execute(sql, params, fetch)

    def ensure_business_table(self, table_name, table_schema):
        self._s.ensure_business_table(table_name, table_schema)

    def cursor(self):
        return self._s.cursor()

    def close(self):
        pass  # 不关闭底层连接
```

**Step 2: 验证导入无语法错误**

```bash
python -c "from core.fake_storage import FakeStorage; print('OK')"
```

预期: `OK`

**Step 3: 提交**

```bash
git add core/fake_storage.py
git commit -m "feat: 添加 FakeStorage — 屏蔽写操作的测试用存储代理"
```

---

### Task 2: SimplePageParser 标记 requires_browser = True

**目的:** 所有继承 `SimplePageParser` 的 58 Parser（生意转让/二手车）都依赖 `on_page_created` 注入跳转守卫 JS、`on_page_loaded` 滚动懒加载，必须走浏览器模式。

**文件:**
- 修改: `parser/plugins/shengyizr/_base.py:70`

**Step 1: 修改 _base.py**

在 `SimplePageParser` 类定义中，`url_pattern` 后面添加：

```python
requires_browser = True   # 58 跳转守卫 + 懒加载依赖浏览器
```

位置：`parser/plugins/shengyizr/_base.py` 第 71 行后（`url_pattern = r"\.58\.com"` 下面）。

**Step 2: 验证**

```bash
python -c "
from parser.plugins.shengyizr.list import ShengyiZRListParser
from parser.plugins.shengyizr.detail import ShengyiZRDetailParser
print('ShengyiZRListParser.requires_browser:', ShengyiZRListParser.requires_browser)
print('ShengyiZRDetailParser.requires_browser:', ShengyiZRDetailParser.requires_browser)
"
```

预期: 两个都输出 `True`

**Step 3: 提交**

```bash
git add parser/plugins/shengyizr/_base.py
git commit -m "feat: SimplePageParser 标记 requires_browser=True"
```

---

### Task 3: RequestPool 新增 fetch_raw_html 方法

**目的:** 提取纯 fetch 逻辑（浏览器 new_page→goto→content 或 HTTP httpx.request）返回 HTML，不写 DB、不做 captcha 检测、不调用 parser.parse。

**文件:**
- 修改: `core/request_pool.py`（新增方法）

**Step 1: 添加 fetch_raw_html 方法**

在 `core/request_pool.py` 的 `RequestPool` 类中，`stats()` 方法前添加：

```python
async def fetch_raw_html(self, url: str, parser: Any, fetch_mode: str = "browser") -> dict:
    """纯 HTML 获取，无 DB 写入，供 test-url 等调试场景复用。

    浏览器模式执行: new_page → on_page_created → goto → on_page_loaded → content → close
    HTTP 模式执行: httpx request → response.text

    :return: dict { html, duration_ms, status_code, content_type, content_length }
    """
    import time as _time

    if fetch_mode == "http":
        # 构建假 task（用于 _fetch_http 的参数兼容）
        fake_task = {
            "id": -1, "url": url, "fetch_mode": "http",
        }
        result = await self._fetch_http(fake_task, parser, proxy_record=None)
        return {
            "html": result["html"],
            "duration_ms": result["duration_ms"],
            "status_code": result.get("status_code", 200),
            "content_type": result.get("response_headers", {}).get("content-type", ""),
            "content_length": result.get("response_size", 0),
        }

    # Browser 模式
    if self.browser is None or self.browser._browser is None:
        raise RuntimeError("浏览器未启动")

    t0 = _time.monotonic()
    page = await self.browser.new_page(url=None)

    try:
        # Parser 生命周期钩子（goto 前注入跳转守卫）
        on_page_created = getattr(parser, "on_page_created", None)
        if on_page_created is not None:
            await on_page_created(page, url)

        timeout_ms = self.config.get_int("request_timeout", 30) * 1000
        resp = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

        # Parser 页面加载后钩子（滚动懒加载）
        on_page_loaded = getattr(parser, "on_page_loaded", None)
        if on_page_loaded is not None:
            await on_page_loaded(page, url)

        # 等页面稳定
        html = ""
        for _retry in range(3):
            try:
                await page.wait_for_load_state("domcontentloaded")
                html = await page.content() if hasattr(page, "content") else ""
                if html and len(html) > 100:
                    break
            except Exception:
                await asyncio.sleep(1)

        duration_ms = int((_time.monotonic() - t0) * 1000)
        status = resp.status if resp else 0
        content_type = resp.headers.get("content-type", "") if resp else ""

        return {
            "html": html,
            "duration_ms": duration_ms,
            "status_code": status,
            "content_type": content_type,
            "content_length": len(html.encode("utf-8")),
        }
    finally:
        await self.browser.close_page(page)
```

**Step 2: 验证语法**

```bash
python -c "import ast; ast.parse(open('core/request_pool.py').read()); print('OK')"
```

预期: `OK`

**Step 3: 提交**

```bash
git add core/request_pool.py
git commit -m "feat: RequestPool 新增 fetch_raw_html 方法（纯 HTML 获取，无 DB 写入）"
```

---

### Task 4: dev.py 注入 request_pool 到 CRAWLER_COMPONENTS

**目的:** test-url API 需要通过 `request_pool.fetch_raw_html()` 获取 HTML。

**文件:**
- 修改: `dev.py:141-147`

**Step 1: 修改 CRAWLER_COMPONENTS**

在 `dev.py` 的 `app.config["CRAWLER_COMPONENTS"]` 字典中添加 `"request_pool"`:

```python
app.config["CRAWLER_COMPONENTS"] = {
    "storage": db,
    "config": config_mgr,
    "registry": registry,
    "scheduler": scheduler,
    "browser": browser,
    "request_pool": request_pool,   # ← 新增
}
```

**Step 2: 提交**

```bash
git add dev.py
git commit -m "feat: 注入 request_pool 到 CRAWLER_COMPONENTS"
```

---

### Task 5: 重写 /api/config/test-url 端点

**目的:** 走完整 Parser pipeline：匹配 Parser → 确定 fetch_mode → fetch HTML → parse → 返回结构化数据。

**文件:**
- 修改: `web/api/config_api.py:43-93`（替换 test_url 和 _test_browser 函数）

**Step 1: 重写 test_url 函数**

```python
@bp.route("/test-url", methods=["POST"])
def test_url():
    """测试 URL — 走完整 Parser pipeline，返回 parse() 的结构化结果。

    Request body::

        {
            "url": "https://cd.58.com/shangpu/xxx.shtml",
            "parser": "ShengyiZRDetailParser"   // 可选，不传则自动匹配
        }

    Response::

        {
            "ok": true,
            "parser": "ShengyiZRDetailParser",
            "fetch_mode": "browser",
            "url_matched": true,
            "duration_ms": 2345,
            "data": [{"title": "...", "price_num": "...", ...}],
            "raw_preview": "<html>..."   // 前 5000 字符
        }
    """
    import asyncio
    import time as _time
    from flask import current_app

    from core.fake_storage import FakeStorage

    data = request.get_json()
    if not data or not data.get("url"):
        return jsonify({"ok": False, "error": "url is required"}), 400

    url = data["url"].strip()
    parser_name = (data.get("parser") or "").strip()

    components = current_app.config.get("CRAWLER_COMPONENTS", {})
    registry = components.get("registry")
    if not registry:
        return jsonify({"ok": False, "error": "Registry 未初始化"}), 503

    # ── 1. 匹配 Parser ──
    if parser_name:
        # 强制指定 Parser
        parser = None
        for cls in registry.classes:
            if cls.__name__ == parser_name:
                parser = registry.match(url)  # 通过 match 获取已实例化的 parser
                break
        if not parser:
            return jsonify({
                "ok": False,
                "error": f"Parser '{parser_name}' 不存在",
            }), 404

        # 验证 URL 匹配
        if not parser.matches(url):
            return jsonify({
                "ok": False,
                "error": f"URL 不匹配 Parser '{parser_name}' 的 pattern ({parser.url_pattern})",
            }), 400
    else:
        # 自动匹配
        parser = registry.match(url)
        if not parser:
            return jsonify({
                "ok": False,
                "error": "未找到匹配该 URL 的 Parser",
            }), 404

    # ── 2. 确定 fetch_mode ──
    config_mgr = components.get("config")
    requires_browser = getattr(parser, "requires_browser", False)
    if requires_browser:
        fetch_mode = "browser"
    else:
        fetch_mode = config_mgr.get("fetch_mode", "browser") if config_mgr else "browser"

    logger.info(
        f"POST /api/config/test-url parser={parser.__class__.__name__} "
        f"requires_browser={requires_browser} fetch_mode={fetch_mode} url={url[:80]}"
    )

    # ── 3. 注入 NoOpStorage，防止副作用 ──
    real_storage = components.get("storage")
    fake_storage = FakeStorage(real_storage) if real_storage else None
    parser.storage = fake_storage

    # ── 4. Fetch HTML + Parse ──
    request_pool = components.get("request_pool")

    async def _do():
        t0 = _time.perf_counter()

        # Fetch
        if request_pool is not None:
            fetch_result = await request_pool.fetch_raw_html(url, parser, fetch_mode)
            html = fetch_result["html"]
            fetch_duration_ms = fetch_result.get("duration_ms", 0)
        elif fetch_mode == "browser":
            # 降级：直接用 browser 裸抓（request_pool 不存在时）
            browser = components.get("browser")
            if not browser or not getattr(browser, "_browser", None):
                raise RuntimeError("浏览器未启动，且 request_pool 不可用")
            page = await browser.new_page(url=None)
            try:
                t_fetch = _time.perf_counter()
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                html = await page.content()
                fetch_duration_ms = int((_time.perf_counter() - t_fetch) * 1000)
            finally:
                await browser.close_page(page)
        else:
            # HTTP 降级
            import httpx as _httpx
            async with _httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                t_fetch = _time.perf_counter()
                resp = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                })
                html = resp.text
                fetch_duration_ms = int((_time.perf_counter() - t_fetch) * 1000)

        # Parse
        t_parse = _time.perf_counter()
        try:
            data_result = parser.parse(html, url)
        except Exception as e:
            logger.error(f"Parser {parser.__class__.__name__} parse 失败: {e}", exc_info=True)
            return {
                "ok": False,
                "error": f"Parse 失败: {e}",
                "error_type": type(e).__name__,
                "parser": parser.__class__.__name__,
            }

        parse_duration_ms = int((_time.perf_counter() - t_parse) * 1000)
        total_duration_ms = int((_time.perf_counter() - t0) * 1000)

        return {
            "ok": True,
            "parser": parser.__class__.__name__,
            "fetch_mode": fetch_mode,
            "url_matched": True,
            "duration_ms": total_duration_ms,
            "fetch_duration_ms": fetch_duration_ms,
            "parse_duration_ms": parse_duration_ms,
            "data": data_result if isinstance(data_result, list) else [],
            "data_count": len(data_result) if isinstance(data_result, list) else 0,
            "raw_preview": html[:5000] if html else "",
        }

    try:
        result = asyncio.run(_do())
        if "error" in result and not result.get("ok"):
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        logger.error(f"test-url 失败: {e}", exc_info=True)
        return jsonify({
            "ok": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }), 500
```

**Step 2: 删除旧函数**

删除 `_test_browser` 函数（L95-136）和旧的 `_test_http` 函数（L139-209）。保留 `_parse_cookies` 辅助函数（HTTP 模式的请求参数现在不从 test-url 入口走了，但可能其他地方需要）。

**Step 3: 提交**

```bash
git add web/api/config_api.py
git commit -m "feat: 重写 test-url 走完整 Parser pipeline"
```

---

### Task 6: 前端 — 简化 testUrl API 签名 + 移除模式切换

**文件:**
- 修改: `web-ui/src/api/index.ts:48-56`（testUrl 签名）
- 修改: `web-ui/src/components/CrawlerSettingsDialog.vue`（移除 mode 切换，传 parser）

**Step 1: 修正 API 签名**

`web-ui/src/api/index.ts`:

```typescript
testUrl: (payload: {
  url: string
  parser?: string  // 可选，从 Parser 卡片进入时携带
}) => api.post('/config/test-url', payload),
```

**Step 2: 修改 CrawlerSettingsDialog**

`web-ui/src/components/CrawlerSettingsDialog.vue` 变更点：

A. **删除 `testMode` 和 HTTP 配置相关变量** (L15-25):
   - 删除 `testMode`、`testMethod`、`testHeaders`、`testCookies`、`testBodyType`、`testBodyContent`
   - 删除 `showBodyConfig` computed
   - 删除 `httpMethodOpts`、`bodyTypeOpts`

B. **修改 `runTest()` 函数** (L41-97):
   ```typescript
   async function runTest() {
     if (!testUrl.value.trim()) return
     testRunning.value = true
     testResult.value = null
     
     const payload: any = {
       url: testUrl.value.trim(),
     }
     if (props.parserName) payload.parser = props.parserName
     
     try {
       const result = await configApi.testUrl(payload)
       testResult.value = result
       
       addHistory({
         url: testUrl.value.trim(),
         // 移除 mode/method 等字段
       })
     } catch (err: any) {
       testResult.value = {
         ok: false,
         error: err?.message || err?.toString?.() || 'Unknown error',
         error_type: 'NetworkError',
       }
     } finally {
       testRunning.value = false
     }
   }
   ```

C. **修改 `restoreFromHistory()`** (L100-110):
   移除 mode/method/headers 等恢复逻辑。

D. **模板变更:**
   - 删除"请求模式"切换区（L209-231，Browser/HTTP 按钮）
   - 删除"HTTP 配置"区（L254-324，Method/Headers/Cookies/Body）
   - 在 URL 输入区下方显示后端返回的 `parser` 和 `fetch_mode` 信息（只读标签）
   - 结果区：已有 `data` 数组展示

**Step 3: 修正前端类型**

`useTestHistory` composable 的 history item 类型简化：
- 删除 `mode`、`method`、`headers`、`cookies`、`bodyType`、`bodyContent`
- 只保留 `url`、`createdAt`、`id`

**Step 4: 验证构建**

```bash
cd web-ui && pnpm build
```

预期: BUILD SUCCESS，无 TS 错误

**Step 5: 提交**

```bash
git add web-ui/src/api/index.ts web-ui/src/components/CrawlerSettingsDialog.vue web-ui/src/composables/useTestHistory.ts
git commit -m "feat: 前端简化 test-url — 移除 mode 切换，传递 parser 名称"
```

---

### Task 7: 运行现有测试确保无回归

**文件:**
- 测试目录: `tests/`

**Step 1: 运行全量测试**

```bash
python -m pytest tests/ -v --tb=short
```

预期: 所有现有测试通过（407 tests passed）

如果 test-url 相关的测试存在，需要更新。

**Step 2: 修复失败的测试**

如有失败，分析原因并修复。

**Step 3: 提交**

```bash
git commit -am "test: 修复 test-url 重设计导致的回归测试"
```
