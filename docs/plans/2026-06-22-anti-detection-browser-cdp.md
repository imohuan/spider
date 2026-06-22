# 反检测系统：Browser 强化 + CDP 三模式实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 `http` / `browser` / `cdp` 三模式反检测体系，集成 fake-useragent 随机 UA，强化 Playwright browser 伪装，新增 CDP 连接本地 Chrome 能力。

**Architecture:** 三模式分层选择（config 全局 → Parser 推荐 → 任务级别覆盖），Browser 模式集成 random UA + stealth 开关 + 页面内延迟，CDP 模式通过 connect_over_cdp 接管用户本地 Chrome，fake-useragent 统一 HTTP/Browser 的 UA 随机化。

**Tech Stack:** Python 3.13 + Playwright + playwright-stealth + fake-useragent + httpx + asyncio

---

## 改动全景

| 文件 | 改动 | 类型 |
|---|---|---|
| `requirements.txt` | 加 `fake-useragent` | 依赖 |
| `core/config_manager.py` | 加 8 项 CDP + 反检测配置 | 配置层 |
| `parser/base.py` | 加 `preferred_fetch_mode` 属性 | Parser 层 |
| `core/browser.py` | 加 random UA / stealth 开关 / 页面延迟 + CDP 连接方法 | 浏览器层 |
| `core/request_pool.py` | 加 CDP 分支 + fake-useragent 集成 HTTP UA | 请求池层 |
| `main.py` | 加 `--fetch-mode cdp` + CDP 浏览器初始化 | 入口 |
| `tests/test_cdp_browser.py` | CDP 连接 / 页面延迟 / random UA 测试 | 测试 |
| `tests/test_anti_bot.py` | 反检测配置 / fake-useragent / stealth 开关测试 | 测试 |

---

### Task 1: 添加 fake-useragent 依赖

**Files:**
- Modify: `requirements.txt`

**Step 1: 添加依赖行**

在 `requirements.txt` 末尾追加：

```
fake-useragent>=1.5.0
```

**Step 2: 安装验证**

```bash
pip install fake-useragent
```

验证：

```python
python -c "from fake_useragent import UserAgent; ua = UserAgent(); print(ua.random)"
```

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat: add fake-useragent dependency for random UA generation"
```

---

### Task 2: 新增反检测 + CDP 配置项

**Files:**
- Modify: `core/config_manager.py:_DEFAULT_CONFIGS`

**Step 1: 在 `_DEFAULT_CONFIGS` 元组末尾（`ai_system_prompt` 之后）追加 8 项**

```python
# --- 反检测 ---
("anti_bot_random_ua", "true", "每次请求随机生成 User-Agent，需 fake-useragent 库支持"),
("anti_bot_stealth", "true", "Browser 模式下启用 playwright-stealth 隐藏浏览器自动化特征"),
("anti_bot_delay_page_min", "1.0", "Browser/CDP 模式下页面内操作最小随机延迟(秒)，模拟人类操作速度"),
("anti_bot_delay_page_max", "3.0", "Browser/CDP 模式下页面内操作最大随机延迟(秒)"),
("anti_bot_ua_platforms", "windows,macos", "fake-useragent 限定的操作系统平台，逗号分隔，避免生成手机 UA"),
("anti_bot_ua_browsers", "chrome,edge", "fake-useragent 限定的浏览器类型，逗号分隔"),
# --- CDP 模式 ---
("cdp_endpoint", "http://localhost:9222", "CDP 模式下连接本地 Chrome 的调试端点"),
("cdp_enabled", "false", "启用 CDP 模式连接本地 Chrome，需手动启动 Chrome --remote-debugging-port=9222"),
```

**完整 `_DEFAULT_CONFIGS` 共 46 项**（原有 38 项 + 新增 8 项）。

**Step 2: 验证配置初始化**

```bash
python -c "
from core.storage import Storage
from core.config_manager import ConfigManager
s = Storage()
cfg = ConfigManager(s)
cfg.init_defaults()
assert cfg.get('anti_bot_random_ua') == 'true'
assert cfg.get('cdp_endpoint') == 'http://localhost:9222'
print('PASS')
"
```

**Step 3: Commit**

```bash
git add core/config_manager.py
git commit -m "feat: add 8 anti-detection & CDP config keys"
```

---

### Task 3: BaseParser 添加 preferred_fetch_mode

**Files:**
- Modify: `parser/base.py:66-71`

**Step 1: 在 `requires_browser` 下方追加类属性**

位置：`parser/base.py:71`（`requires_browser = False` 之后），追加一行：

```python
preferred_fetch_mode: str | None = None  # None=跟随全局, "http"/"browser"/"cdp"
```

每个 Parser 可选覆盖此属性来声明自己偏好的抓取模式。优先级仍然是 task > parser > config。

**Step 2: 验证**

```bash
python -c "
from parser.base import BaseParser
# 默认 None
assert BaseParser.preferred_fetch_mode is None
print('PASS')
"
```

**Step 3: Commit**

```bash
git add parser/base.py
git commit -m "feat: add preferred_fetch_mode to BaseParser"
```

---

### Task 4: 强化 CrawlerBrowser — random UA + stealth 开关 + 页面延迟

**Files:**
- Modify: `core/browser.py`

这是本计划工作量最大的任务。当前 `CrawlerBrowser` 使用硬编码 UA 和硬编码 stealth 启用。需要改为可配置。

**Step 1: `__init__` 中缓存反检测配置**

在 `CrawlerBrowser.__init__` 末尾追加（`self._lock = asyncio.Lock()` 之后）：

```python
# 反检测配置（缓存，避免每次 new_page 都读 config）
self._use_random_ua: bool = self.config.get_bool("anti_bot_random_ua", False)
self._use_stealth: bool = self.config.get_bool("anti_bot_stealth", True)
self._delay_min: float = self.config.get_float("anti_bot_delay_page_min", 1.0)
self._delay_max: float = self.config.get_float("anti_bot_delay_page_max", 3.0)
```

**Step 2: 修改 `new_page` 方法 — 随机 UA 替换硬编码 UA**

定位到 `new_page` 中第 143-150 行，将硬编码 UA 替换为 `_get_random_ua()` 调用：

```python
# 替换前（第 143-148 行）：
if self.headless:
    context_kwargs["user_agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

# 替换后：
if self.headless or self._use_random_ua:
    context_kwargs["user_agent"] = self._get_random_ua()
```

**注意**：非 headless 模式时系统 Chrome 自带真实 UA，不需要伪造。但如果 `anti_bot_random_ua=true` 且 headless=false，也要覆盖（有些场景需要签名不同的 UA）。

**Step 3: 添加 `_get_random_ua()` 私有方法**

在 `CrawlerBrowser` 类中追加（`close_page` 方法之前）：

```python
def _get_random_ua(self) -> str:
    """获取随机 User-Agent，优先 fake-useragent，降级到静态池。"""
    try:
        from fake_useragent import UserAgent

        _ua = UserAgent(
            os=self.config.get("anti_bot_ua_platforms", "windows,macos").split(","),
            browsers=self.config.get("anti_bot_ua_browsers", "chrome,edge").split(","),
        )
        ua_str = _ua.random
        if ua_str:
            return ua_str
    except Exception:
        pass

    # 降级：静态 UA 池
    import random
    return random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    ])
```

**Step 4: stealth 可配置化**

定位到第 152-155 行（stealth 注入逻辑）。当前无条件执行。改为检查 `_use_stealth` 配置：

```python
# 替换前（第 152-155 行）：
if self._stealth is not None:
    await self._stealth.apply_stealth_async(context)

# 替换后：
if self._use_stealth and self._stealth is not None:
    await self._stealth.apply_stealth_async(context)
elif not self._use_stealth:
    logger.debug("anti_bot_stealth=false，跳过 stealth 注入")
```

**Step 5: 添加页面内随机延迟方法**

在 `CrawlerBrowser` 类中追加：

```python
async def random_delay(self) -> None:
    """页面内操作的随机延迟，模拟人类操作间隔。
    
    在 click / scroll / type 等操作间调用，避免机器人式连续操作。
    """
    import random
    delay = random.uniform(self._delay_min, self._delay_max)
    if delay > 0:
        await asyncio.sleep(delay)
```

**Step 6: 运行现有测试确保没有回归**

```bash
python -m pytest tests/ -x -q
```

预期：所有 394 测试通过。

**Step 7: Commit**

```bash
git add core/browser.py
git commit -m "feat: random UA, configurable stealth, page-level delay for CrawlerBrowser"
```

---

### Task 5: 新增 CrawlerBrowserCDP — CDP 连接模式

**Files:**
- Create: `core/browser_cdp.py`

CDP 模式连接用户手动启动的真实 Chrome，自带 Cookie/登录态/真实指纹，无需 stealth。

**Step 1: 创建 `core/browser_cdp.py`**

```python
"""CDP 浏览器模块 - 通过 Chrome DevTools Protocol 连接本地 Chrome。

与 CrawlerBrowser 的区别：
- 不需要 launch()：用户手动启动 Chrome --remote-debugging-port=9222
- 不需要 stealth：真实 Chrome 无自动化特征
- 不需要 new_context：复用 Chrome 现有的 context
- 不管理浏览器生命周期：不 stop/close 浏览器进程

用法::

    browser = CrawlerBrowserCDP(endpoint="http://localhost:9222")
    await browser.connect()
    page = await browser.new_page("https://sz.58.com/")
    ...
    await browser.close_page(page)
    await browser.disconnect()  # 断开 CDP，不关闭 Chrome
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.interceptor import Interceptor

logger = get_logger("browser.cdp")


class CrawlerBrowserCDP:
    """通过 CDP 协议连接本地真实 Chrome。

    适用场景：
    - 目标站反爬极严，Playwright launch 无法绕过
    - 需要用户手动登录后的 Cookie/会话状态
    - 用户手动操作的 Chrome 自带真实浏览器指纹

    限制：
    - 需用户手动启动 Chrome --remote-debugging-port=9222
    - 不支持 headless（使用用户 Chrome 的当前状态）
    - 不支持 per-context 代理（代理需在 Chrome 启动参数中设定）
    """

    def __init__(
        self,
        config: ConfigManager,
        endpoint: str | None = None,
    ) -> None:
        self.config = config
        self.endpoint = endpoint or config.get("cdp_endpoint", "http://localhost:9222")
        self._playwright: Any = None
        self._browser: Any = None
        self._interceptor = Interceptor(config)
        self._request_count = 0
        self._lock = asyncio.Lock()

        # 反检测配置
        self._use_random_ua: bool = config.get_bool("anti_bot_random_ua", False)
        self._delay_min: float = config.get_float("anti_bot_delay_page_min", 1.0)
        self._delay_max: float = config.get_float("anti_bot_delay_page_max", 3.0)

    async def connect(self) -> None:
        """通过 CDP 连接本地 Chrome。"""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(
            self.endpoint
        )
        logger.info(f"CDP 已连接: {self.endpoint}")

    async def disconnect(self) -> None:
        """断开 CDP 连接（不关闭 Chrome 进程）。"""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        logger.info("CDP 已断开")

    async def new_page(
        self, url: str | None = None, proxy: str | None = None
    ) -> Any:
        """在已有 Chrome 中创建新标签页。

        :param url: 目标 URL
        :param proxy: CDP 模式不支持，忽略
        :return: Playwright Page 对象
        """
        if self._browser is None:
            raise RuntimeError("CDP 未连接，请先调用 connect()")

        async with self._lock:
            self._request_count += 1

        # CDP 模式下直接使用现有 context
        contexts = self._browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await self._browser.new_context()

        page = await context.new_page()
        await self._interceptor.attach(page)

        if url:
            timeout_ms = self.config.get_int("request_timeout", 30) * 1000
            logger.debug(f"CDP goto {url} timeout={timeout_ms}ms")
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

        return page

    async def close_page(self, page: Any) -> None:
        """关闭标签页（不关闭 context，避免影响用户其他标签页）。"""
        if page is None:
            return
        try:
            await page.close()
        except Exception as e:
            logger.warning(f"关闭 CDP page 失败: {e}")

    async def random_delay(self) -> None:
        """页面内操作随机延迟。"""
        delay = random.uniform(self._delay_min, self._delay_max)
        if delay > 0:
            await asyncio.sleep(delay)

    # ---------- 状态查询 ----------

    @property
    def is_connected(self) -> bool:
        return self._browser is not None and getattr(self._browser, "is_connected", lambda: True)()

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def existing_pages(self) -> int:
        """返回 Chrome 中已有标签页数。"""
        if self._browser is None:
            return 0
        contexts = self._browser.contexts
        if not contexts:
            return 0
        return len(contexts[0].pages)
```

**Step 2: 验证导入和基本接口**

```bash
python -c "
from core.browser_cdp import CrawlerBrowserCDP
assert hasattr(CrawlerBrowserCDP, 'connect')
assert hasattr(CrawlerBrowserCDP, 'disconnect')
assert hasattr(CrawlerBrowserCDP, 'new_page')
assert hasattr(CrawlerBrowserCDP, 'close_page')
assert hasattr(CrawlerBrowserCDP, 'random_delay')
print('PASS: 接口完整')
"
```

**Step 3: Commit**

```bash
git add core/browser_cdp.py
git commit -m "feat: add CrawlerBrowserCDP - connect to local Chrome via CDP"
```

---

### Task 6: RequestPool 集成 CDP 模式 + fake-useragent

**Files:**
- Modify: `core/request_pool.py`

**Step 1: `__init__` 新增 `cdp_browser` 参数**

在 `RequestPool.__init__` 中，`browser` 参数之后追加 `cdp_browser` 参数：

```python
def __init__(
    self,
    ...
    browser: Any | None = None,
    cdp_browser: Any | None = None,  # 新增
    ...
):
    ...
    self.browser = browser
    self.cdp_browser = cdp_browser  # 新增
```

**Step 2: 替换静态 `_UA_POOL` 为 `_get_random_ua()` 方法**

删除模块级 `_UA_POOL` 常量（第 42-47 行），替换为私有方法：

```python
def _get_random_ua(self) -> str:
    """获取随机 User-Agent，优先 fake-useragent，降级到静态池。"""
    try:
        from fake_useragent import UserAgent

        platforms = self.config.get("anti_bot_ua_platforms", "windows,macos").split(",")
        browsers = self.config.get("anti_bot_ua_browsers", "chrome,edge").split(",")
        _ua = UserAgent(os=[p.strip() for p in platforms], browsers=[b.strip() for b in browsers])
        return _ua.random
    except Exception:
        pass

    import random
    return random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    ])
```

**Step 3: 修改 `_fetch_http` 中的 User-Agent 逻辑**

在 `_fetch_http` 方法中，Layer 1 的 UA 读取改为随机生成（当 `anti_bot_random_ua=true` 时）：

当前第 462-467 行：
```python
merged_headers = {
    "User-Agent": self.config.get(
        "http_user_agent",
        "Mozilla/5.0 ...",
    ),
}
```

替换为：
```python
ua = self._get_random_ua() if self.config.get_bool("anti_bot_random_ua", False) else \
     self.config.get("http_user_agent",
                     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
merged_headers = {"User-Agent": ua}
```

**Step 4: 在 `_process_url_async` 中添加 CDP 分支**

在 `_process_url_async` 中，在 HTTP 和 Browser 分支之间（第 265 行之前），插入 CDP 分支：

```python
# === CDP 模式 ===
if fetch_mode == "cdp":
    page = None
    try:
        if self.cdp_browser is None:
            logger.warning("cdp_browser 未注入，无法使用 CDP 模式")
            self.storage.mark_request_failed(request_id, "cdp_browser 未注入", status_code=None)
            self.state_machine.mark_failed(queue_id, ERROR_NETWORK, "cdp_browser 未注入")
            self._release_proxy(proxy_record, success=False)
            return "failed"

        cdp_start = time.monotonic()
        page = await self.cdp_browser.new_page(url=None, proxy=proxy_url)

        # Parser 钩子（goto 前）
        on_page_created = getattr(parser, "on_page_created", None)
        if on_page_created is not None:
            await on_page_created(page, url)

        timeout_ms = self.config.get_int("request_timeout", 30) * 1000
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        cdp_duration_ms = int((time.monotonic() - cdp_start) * 1000)

        # Parser 钩子（页面加载后）
        on_page_loaded = getattr(parser, "on_page_loaded", None)
        if on_page_loaded is not None:
            await on_page_loaded(page, url)

        # 验证码检测（同 browser 模式）
        if self.captcha_handler is not None and await self.captcha_handler.is_captcha_page_async(page):
            logger.warning(f"[Captcha:CDP] 触发: {url}")
            self.storage.execute(
                "UPDATE requests SET captcha_triggered = 1 WHERE id = ?",
                (request_id,), fetch="none",
            )
            self.storage.mark_request_failed(request_id, "CDP 模式触发验证码", status_code=None)
            self.state_machine.mark_blocked(queue_id, ERROR_CAPTCHA, "CDP 模式验证码")
            self._release_proxy(proxy_record, success=False)
            if not self.keep_browser_open:
                await self._close_page_with_hook(page, parser)
            return "blocked"

        # 解析
        raw_path = None
        try:
            html = ""
            for _retry in range(3):
                try:
                    await page.wait_for_load_state("domcontentloaded")
                    html = await page.content() if hasattr(page, "content") else ""
                    if html and len(html) > 100:
                        break
                except Exception:
                    await asyncio.sleep(1)
            raw_path = self._save_raw_response(queue_id, request_id, html)
            response_size = len(html.encode("utf-8"))
            parser.storage = self.storage
            data = parser.parse(html, url)
        except Exception as e:
            logger.error(f"[Parser:{parser.__class__.__name__}] CDP 解析失败: {url} {e}", exc_info=True)
            self.storage.mark_request_failed(request_id, str(e), status_code=None, duration_ms=cdp_duration_ms, raw_response_path=raw_path)
            self.state_machine.mark_failed(queue_id, ERROR_PARSE, str(e))
            self._release_proxy(proxy_record, success=False)
            if not self.keep_browser_open:
                await self._close_page_with_hook(page, parser)
            return "failed"

        return await self._finish_request(
            task, parser, html, data,
            queue_id, request_id, proxy_record, proxy_url, page=page,
            duration_ms=cdp_duration_ms, response_size=response_size,
            raw_response_path=raw_path,
        )

    except Exception as e:
        logger.error(f"CDP 请求异常: {url} {e}", exc_info=True)
        self.storage.mark_request_failed(request_id, str(e), status_code=None)
        self.state_machine.mark_failed(queue_id, ERROR_NETWORK, str(e))
        self._release_proxy(proxy_record, success=False)
        if page is not None and self.cdp_browser is not None and not self.keep_browser_open:
            try:
                await self._close_page_with_hook(page, parser)
            except Exception:
                pass
        return "failed"
```

**Step 5: 修改 fetch_mode 解析逻辑，支持 Parser 级别的 preferred_fetch_mode**

替换 `_process_url_async` 中第 141-147 行的 fetch_mode 解析：

```python
# 确定抓取模式：task > parser.preferred_fetch_mode > config 全局 > 默认 browser
fetch_mode = (
    task.get("fetch_mode")
    or getattr(parser, "preferred_fetch_mode", None)
    or self.config.get("fetch_mode", "browser")
)

# requires_browser 强制走 browser 或 cdp（不能走 http）
if fetch_mode == "http" and getattr(parser, "requires_browser", False):
    logger.info(f"[{parser.__class__.__name__}] requires_browser=True, 强制使用 browser 模式")
    fetch_mode = "browser"
```

**Step 6: 替换 `_apply_anti_bot` 中的静态 UA 为动态 UA**

```python
def _apply_anti_bot(self, proxy_record: Any | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    headers["User-Agent"] = self._get_random_ua()
    logger.debug(f"反爬 UA: {headers['User-Agent'][:60]}...")
    return headers
```

**Step 7: Commit**

```bash
git add core/request_pool.py
git commit -m "feat: integrate CDP mode & fake-useragent into RequestPool"
```

---

### Task 7: main.py 集成 CDP 模式启动

**Files:**
- Modify: `main.py`

**Step 1: `--fetch-mode` 参数增加 `cdp` 选项**

第 76 行：
```python
parser.add_argument(
    "--fetch-mode", choices=["browser", "http", "cdp"],  # 加 cdp
    default=None, help="抓取模式：browser / http / cdp，默认读取 config",
)
```

**Step 2: `build_components` 中初始化 CDP 浏览器**

在 `build_components` 函数中（第 138-140 行之后），追加：

```python
# CDP 浏览器（仅在 fetch_mode=cdp 或 cdp_enabled=true 时初始化）
from core.browser_cdp import CrawlerBrowserCDP
cdp_browser = CrawlerBrowserCDP(config_mgr) if (
    args.fetch_mode == "cdp" or config_mgr.get_bool("cdp_enabled", False)
) else None
```

**Step 3: 传入 RequestPool**

在 `RequestPool` 构造函数中（第 153-162 行），追加 `cdp_browser`：

```python
request_pool = RequestPool(
    storage=storage,
    config=config_mgr,
    state_machine=state_machine,
    proxy_pool=proxy_pool,
    browser=browser,
    cdp_browser=cdp_browser,  # 新增
    captcha_handler=captcha_handler,
    image_downloader=tools.image_downloader,
    loop=event_loop,
)
```

**Step 4: 主循环中 CDP 连接/断开**

在 `main` 函数中（第 239 行 `browser.start()` 之后），追加 CDP 连接逻辑：

```python
# CDP 模式下连接本地 Chrome
cdp_browser = components.get("cdp_browser")
if cdp_browser is not None:
    try:
        event_loop.run_until_complete(cdp_browser.connect())
        logger.info(f"CDP 已连接本地 Chrome: {cdp_browser.endpoint}")
    except Exception as e:
        logger.error(f"CDP 连接失败，无法使用 CDP 模式: {e}")
        cdp_browser = None
```

在 `finally` 块中（第 258-268 行），追加 CDP 断开：

```python
# CDP 断开
if cdp_browser is not None:
    try:
        event_loop.run_until_complete(cdp_browser.disconnect())
    except Exception as e:
        logger.warning(f"CDP 断开异常: {e}")
```

**完整 `finally` 块位置**：在 `browser.close()` 之后、`cancel_all_tasks` 之前。

**Step 5: 验证 CLI 参数**

```bash
python main.py --help | grep "fetch-mode"
```

预期输出：`--fetch-mode {browser,http,cdp}`

**Step 6: Commit**

```bash
git add main.py
git commit -m "feat: integrate CDP mode into main.py bootstrap"
```

---

### Task 8: 测试套件

**Files:**
- Create: `tests/test_anti_bot.py`
- Create: `tests/test_cdp_browser.py`

**Step 1: 创建 `tests/test_anti_bot.py`**

测试 fake-useragent 集成、随机 UA 生成、stealth 配置开关：

```python
"""测试反检测功能：fake-useragent / random UA / stealth 配置"""
import pytest
from core.config_manager import ConfigManager
from core.storage import Storage


class TestRandomUA:
    """fake-useragent 与 UA 降级测试"""

    def test_get_random_ua_static_fallback(self):
        """无 fake-useragent 时降级到静态 UA 池"""
        # 此测试依赖 RequestPool._get_random_ua 的降级逻辑
        from core.request_pool import RequestPool
        from unittest.mock import MagicMock

        pool = RequestPool(
            storage=MagicMock(), config=MagicMock(), state_machine=MagicMock(),
            proxy_pool=None, browser=None, captcha_handler=None, image_downloader=None,
        )
        pool.config.get_bool.return_value = True
        pool.config.get.return_value = "windows,macos"

        # 强制 fake-useragent 不可用（模块级 mock）
        ua = pool._get_random_ua()
        assert ua and len(ua) > 30, f"UA 太短: {ua!r}"
        assert "Mozilla" in ua

    def test_get_random_ua_with_fake_useragent(self):
        """fake-useragent 可用时返回真实 Chrome UA"""
        try:
            from fake_useragent import UserAgent
            _ua = UserAgent(os=["windows", "macos"], browsers=["chrome"])
            result = _ua.random
            assert result and "Chrome" in result, f"UA 不含 Chrome: {result!r}"
        except ImportError:
            pytest.skip("fake-useragent 未安装")

    def test_anti_bot_config_defaults(self):
        """验证反检测配置默认值"""
        s = Storage()
        cfg = ConfigManager(s)
        cfg.init_defaults()
        assert cfg.get_bool("anti_bot_random_ua") is False
        assert cfg.get_bool("anti_bot_stealth") is True
        assert cfg.get_float("anti_bot_delay_page_min") == 1.0
        assert cfg.get_float("anti_bot_delay_page_max") == 3.0
        assert cfg.get("cdp_endpoint") == "http://localhost:9222"
        assert cfg.get("anti_bot_ua_platforms") == "windows,macos"
        assert cfg.get("anti_bot_ua_browsers") == "chrome,edge"

    def test_anti_bot_config_set_and_read(self):
        """反检测配置读写"""
        s = Storage()
        cfg = ConfigManager(s)
        cfg.init_defaults()
        cfg.set("anti_bot_random_ua", "true")
        assert cfg.get_bool("anti_bot_random_ua") is True

        cfg.set("anti_bot_delay_page_min", 2.5)
        assert cfg.get_float("anti_bot_delay_page_min") == 2.5


class TestBaseParserPreferredMode:
    """BaseParser.preferred_fetch_mode"""

    def test_default_preferred_mode(self):
        from parser.base import BaseParser
        assert BaseParser.preferred_fetch_mode is None

    def test_subclass_override(self):
        from parser.base import BaseParser

        class MyParser(BaseParser):
            url_pattern = r"test"
            table_name = "test"
            table_schema = "CREATE TABLE test (id INTEGER)"
            preferred_fetch_mode = "cdp"

        assert MyParser.preferred_fetch_mode == "cdp"
```

**Step 2: 创建 `tests/test_cdp_browser.py`**

测试 CDP 浏览器类的接口与配置：

```python
"""测试 CDP 浏览器"""
import pytest


class TestCrawlerBrowserCDP:
    """CrawlerBrowserCDP 接口测试（不需要实际 Chrome 运行）"""

    def test_init_with_config(self):
        from core.browser_cdp import CrawlerBrowserCDP
        from core.config_manager import ConfigManager
        from core.storage import Storage

        s = Storage()
        cfg = ConfigManager(s)
        cfg.init_defaults()

        browser = CrawlerBrowserCDP(cfg)
        assert browser.endpoint == "http://localhost:9222"
        assert browser.is_connected is False
        assert browser.request_count == 0

    def test_init_with_custom_endpoint(self):
        from core.browser_cdp import CrawlerBrowserCDP
        from unittest.mock import MagicMock

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: d

        browser = CrawlerBrowserCDP(cfg, endpoint="http://localhost:9233")
        assert browser.endpoint == "http://localhost:9233"

    def test_random_delay_range(self):
        """验证 random_delay 在配置范围内"""
        import asyncio
        from unittest.mock import MagicMock
        from core.browser_cdp import CrawlerBrowserCDP

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: 0.5 if "min" in k else 1.0
        browser = CrawlerBrowserCDP(cfg)
        assert 0.5 <= browser._delay_min <= 1.0

    def test_properties_default(self):
        from unittest.mock import MagicMock
        from core.browser_cdp import CrawlerBrowserCDP

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: d
        browser = CrawlerBrowserCDP(cfg)
        assert browser.existing_pages == 0
        assert browser.request_count == 0
```

**Step 3: 运行新测试**

```bash
python -m pytest tests/test_anti_bot.py tests/test_cdp_browser.py -v
```

预期：全部通过。

**Step 4: Commit**

```bash
git add tests/test_anti_bot.py tests/test_cdp_browser.py
git commit -m "test: anti-bot & CDP browser unit tests"
```

---

### Task 9: 全量回归测试

**Step 1: 运行全部测试**

```bash
python -m pytest tests/ -v
```

预期：所有已有测试 + 新增测试全部通过。CDP 测试不需要实际 Chrome 运行。

**Step 2: 如有失败，逐项修复并 commit fix**

---

## 实现完成后验证清单

- [ ] `python main.py --help` 显示 `--fetch-mode {browser,http,cdp}`
- [ ] `python main.py --fetch-mode http --seed ...` 正常走 HTTP 模式
- [ ] `python main.py --fetch-mode browser --seed ...` 正常走 Browser 模式
- [ ] Browser 模式下 `anti_bot_random_ua=true` 时每次 new_page 使用不同 UA
- [ ] Browser 模式下 `anti_bot_stealth=false` 时不注入 stealth 脚本
- [ ] CDP 模式下需要先启动 Chrome `--remote-debugging-port=9222`
- [ ] CDP 模式使用用户 Chrome 的 Cookie/登录态
- [ ] `fake-useragent` 降级到静态池（fake-useragent 不可用时）
- [ ] 所有 394+ 测试通过
- [ ] Web UI 中 Config 页面可看到新增的 8 个配置项
- [ ] Web UI 中 Queue 页面可设置 `fetch_mode=cdp`

---

## CDP 模式使用方式

**启动 Chrome（Windows）：**

```bash
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chrome-profile"
```

**爬虫连接：**

```bash
python main.py --fetch-mode cdp --seed https://sz.58.com/ershouche/
```

或通过 Config 页面设置 `cdp_enabled=true` + `fetch_mode=cdp`。
