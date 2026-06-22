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
