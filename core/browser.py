"""浏览器模块 - 封装 Playwright 浏览器实例、上下文与页面生命周期管理。

按设计文档 4.4 与第六章技术决策：

- **为什么 Playwright**：``route()`` 是唯一能干净实现资源拦截/修改/缓存的方案
- **Async API**：爬虫主进程与 Flask 同进程时避免事件循环冲突（见设计文档第九章风险）
- **代理**：每个 context 可绑定独立代理 IP
- **生命周期**：单 Browser 实例长驻，按需创建 Context/Page，定期重启避免内存泄漏
  （设计文档第十章风险：每 100 个 URL 重启一次浏览器进程）

典型用法（异步）::

    browser = CrawlerBrowser(headless=True)
    await browser.start()
    try:
        page = await browser.new_page(url, proxy="http://1.2.3.4:8080")
        await page.wait_for_load_state("networkidle")
        html = await page.content()
    finally:
        await browser.close()

资源拦截由 :class:`Interceptor` 注入到每个 Page。
"""
from __future__ import annotations

import asyncio
from typing import Any

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.interceptor import Interceptor

logger = get_logger("browser")

# 每 N 个 URL 重启一次浏览器进程，避免内存泄漏
RESTART_INTERVAL = 100


class CrawlerBrowser:
    """Playwright 异步浏览器封装。

    单 ``Browser`` 实例长驻，每个抓取任务创建独立 ``BrowserContext`` + ``Page``
    （隔离 cookie/localStorage），结束后关闭 context 释放资源。

    反检测策略：
    1. **使用系统 Chrome**（``channel="chrome"``）替代 Playwright 自带 Chromium
       —— Playwright Chromium 含自动化标记，WAF 可识别；系统 Chrome 无此特征。
    2. **Stealth 脚本注入**：隐藏 navigator.webdriver、伪造 chrome.runtime 等
    3. **Chrome 启动参数**：--disable-blink-features=AutomationControlled
    4. **伪装 UA**：headless 时替换掉 "HeadlessChrome" 标识
    """

    # Chrome 反检测启动参数
    _STEALTH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
    ]
    _HEADFUL_ARGS = [
        "--start-maximized",
    ]

    def __init__(
        self,
        config: ConfigManager,
        headless: bool = True,
        browser_type: str = "chromium",
        channel: str | None = "chrome",  # 默认用系统 Chrome 而非 Playwright Chromium
    ) -> None:
        self.config = config
        self.headless = headless
        self.browser_type = browser_type
        self.channel = channel  # None = Playwright 自带 Chromium, "chrome" = 系统 Chrome
        self._playwright: Any = None
        self._browser: Any = None
        self._stealth: Any = None  # playwright_stealth.Stealth 实例
        self._request_count = 0
        self._interceptor = Interceptor(config)
        self._lock = asyncio.Lock()

        # 反检测配置（缓存，避免每次 new_page 都读 config）
        self._use_random_ua: bool = self.config.get_bool("anti_bot_random_ua", False)
        self._use_stealth: bool = self.config.get_bool("anti_bot_stealth", True)
        self._delay_min: float = self.config.get_float("anti_bot_delay_page_min", 1.0)
        self._delay_max: float = self.config.get_float("anti_bot_delay_page_max", 3.0)

    async def start(self) -> None:
        """启动 Playwright 与浏览器实例（含 stealth 反检测 + 系统 Chrome）。"""
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import Stealth
            self._stealth = Stealth(chrome_runtime=True)
        except ImportError:
            logger.warning("playwright-stealth 未安装，跳过反检测注入")
            self._stealth = None
        self._playwright = await async_playwright().start()
        engine = getattr(self._playwright, self.browser_type)

        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": self._STEALTH_ARGS + (self._HEADFUL_ARGS if not self.headless else []),
        }
        if self.channel:
            launch_kwargs["channel"] = self.channel

        self._browser = await engine.launch(**launch_kwargs)
        browser_name = self.channel or "Playwright Chromium"
        logger.info(
            f"浏览器已启动: {browser_name} headless={self.headless} stealth=on"
        )

    async def close(self) -> None:
        """关闭浏览器与 Playwright。"""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        logger.info("浏览器已关闭")

    async def restart(self) -> None:
        """重启浏览器进程（每 RESTART_INTERVAL 个 URL 调用一次）。"""
        logger.info("重启浏览器进程（内存回收）")
        await self.close()
        await self.start()

    async def new_page(self, url: str | None = None, proxy: str | None = None) -> Any:
        """创建新 Page，可选绑定代理，可选立即跳转到 url。

        :param url: 目标 URL，``None`` 则返回空白页
        :param proxy: 代理 URL（``http://ip:port``），``None`` 直连
        :return: Playwright Page 对象
        """
        if self._browser is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        # 每 RESTART_INTERVAL 个 URL 重启一次
        async with self._lock:
            self._request_count += 1
            if self._request_count > RESTART_INTERVAL:
                await self.restart()
                self._request_count = 1

        context_kwargs: dict[str, Any] = {}
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}
            logger.debug(f"创建 context，proxy={proxy}")

        # headless 时必须伪装 UA（默认 UA 含 "HeadlessChrome" 直接暴露）
        if self.headless:
            context_kwargs["user_agent"] = self._get_random_ua()
            # headless 模式下 window 尺寸为 0，需显式设置
            context_kwargs["viewport"] = {"width": 1366, "height": 768}

        if self._use_random_ua:
            context_kwargs["user_agent"] = self._get_random_ua()

        context = await self._browser.new_context(**context_kwargs)
        # 注入 stealth 反检测脚本
        if self._use_stealth and self._stealth is not None:
            await self._stealth.apply_stealth_async(context)
        elif not self._use_stealth:
            logger.debug("anti_bot_stealth=false，跳过 stealth 注入")

        page = await context.new_page()
        # 注入资源拦截器
        await self._interceptor.attach(page)

        if url:
            timeout_ms = self.config.get_int("request_timeout", default=30) * 1000
            logger.debug(f"goto {url} timeout={timeout_ms}ms")
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        return page

    def _get_random_ua(self) -> str:
        """获取随机 User-Agent，优先 fake-useragent，降级到静态池。"""
        try:
            from fake_useragent import UserAgent

            platforms_str = self.config.get("anti_bot_ua_platforms", "windows,macos")
            browsers_str = self.config.get("anti_bot_ua_browsers", "chrome,edge")
            _ua = UserAgent(
                os=[p.strip() for p in platforms_str.split(",")],
                browsers=[b.strip() for b in browsers_str.split(",")],
            )
            ua_str = _ua.random
            if ua_str:
                logger.debug(f"随机 UA: {ua_str[:80]}...")
                return ua_str
        except Exception as e:
            logger.debug(f"fake-useragent 不可用，降级静态 UA 池: {e}")

        # 降级：静态 UA 池
        import random as _random
        return _random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        ])

    async def random_delay(self) -> None:
        """页面内操作的随机延迟，模拟人类操作间隔。"""
        import random as _random
        delay = _random.uniform(self._delay_min, self._delay_max)
        if delay > 0:
            await asyncio.sleep(delay)

    async def show_page(self, page: Any) -> None:
        """尝试将页面弹到前台。
        
        headless 模式下窗口不存在，捕获异常静默忽略。
        """
        try:
            await page.bring_to_front()
            await page.evaluate("window.focus()")
        except Exception:
            pass  # headless 模式无窗口，忽略

    async def close_page(self, page: Any) -> None:
        """关闭 page 及其 context。"""
        if page is None:
            return
        context = page.context
        try:
            await page.close()
        except Exception as e:
            logger.warning(f"关闭 page 失败: {e}")
        try:
            await context.close()
        except Exception as e:
            logger.warning(f"关闭 context 失败: {e}")

    @property
    def request_count(self) -> int:
        return self._request_count
