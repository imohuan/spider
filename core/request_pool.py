"""请求池层模块 - 单 URL 处理全流程。

按设计文档 4.9：申请 IP → 反爬处理 → browser.get → 验证码检测 →
parser.parse → 下载图片 → 保存数据 → 更新状态。

关键协调：
- 与 ``ProxyPool`` 协作申请/回收 IP
- 与 ``StateMachine`` 协作换 IP 计数（通过 captcha_handler）
- 与 ``CaptchaHandler`` 协作检测+接码+降级
- 错误分类重试：network/5xx/403/captcha/parse

browser 是异步的，``process_url`` 用 ``asyncio.run`` 桥接同步调用。
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from config import RAW_RESPONSE_DIR, PROJECT_ROOT


from core.config_manager import ConfigManager
from core.fake_storage import FakeStorage
from core.logger import get_logger
from core.state_machine import (
    ERROR_403,
    ERROR_5XX,
    ERROR_CAPTCHA,
    ERROR_NETWORK,
    ERROR_PARSE,
    StateMachine,
)
from core.storage import Storage

logger = get_logger("request_pool")


class RequestPool:
    """请求池，处理单个 URL 的完整抓取流程。

    依赖注入：
    - ``storage`` / ``config`` / ``state_machine``
    - ``proxy_pool``: ProxyPool 实例（可为 None，禁用代理模式）
    - ``browser``: CrawlerBrowser 实例（异步）
    - ``captcha_handler``: CaptchaHandler 实例
    - ``image_downloader``: ImageDownloader 实例
    """

    def __init__(
        self,
        storage: Storage,
        config: ConfigManager,
        state_machine: StateMachine,
        proxy_pool: Any | None = None,
        browser: Any | None = None,
        cdp_browser: Any | None = None,
        captcha_handler: Any | None = None,
        image_downloader: Any | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.storage = storage
        self.config = config
        self.state_machine = state_machine
        self.proxy_pool = proxy_pool
        self.browser = browser
        self.cdp_browser = cdp_browser
        self.captcha_handler = captcha_handler
        self.image_downloader = image_downloader
        self._loop = loop  # 持久事件循环（production 模式传入，避免 Playwright 对象跨循环失效）
        self._active_tasks: set[asyncio.Task] = set()
        self.keep_browser_open: bool = False  # 调试用：True 则 process_url 完成后不关闭 page/browser
        self._last_page: Any = None       # keep_browser_open 时捕获的 page
        self._last_parser: Any = None     # 对应的 parser（用于 on_before_page_close 钩子）
        self._debug_sessions: dict[str, dict] = {}  # session_id → {page, parser, browser, expiry, url, timer}

    async def _close_page_with_hook(self, page: Any, parser: Any) -> None:
        """关闭 page 前调用 Parser 生命周期钩子。"""
        if hasattr(parser, "on_before_page_close"):
            try:
                await parser.on_before_page_close(page)
            except Exception as exc:
                logger.warning(
                    f"[{parser.__class__.__name__}] on_before_page_close 异常，继续关闭: {exc}"
                )
        await self.browser.close_page(page)

    # ---------------- 内部辅助方法 ----------------

    def _fail_task(
        self,
        request_id: int,
        queue_id: int,
        error_type: str,
        error_msg: str,
        proxy_record: Any | None,
        *,
        status_code: int | None = None,
        duration_ms: int | None = None,
        raw_response_path: str | None = None,
        response_headers: dict | None = None,
    ) -> None:
        """标记请求和任务失败 + 释放代理（不含页面关闭）。"""
        self.storage.mark_request_failed(
            request_id, error_msg, status_code=status_code,
            duration_ms=duration_ms, raw_response_path=raw_response_path,
            response_headers=response_headers,
        )
        self.state_machine.mark_failed(queue_id, error_type, error_msg)
        self._release_proxy(proxy_record, success=False)

    async def _browser_page_lifecycle(
        self, browser: Any, url: str, parser: Any, proxy_url: str | None,
        cookies: list[dict] | None = None,
        extra_timeout_ms: int = 0,
    ) -> tuple[Any, int]:
        """创建页面 → Cookie 注入 → goto → 生命周期钩子 → 返回 (page, duration_ms)。

        :param extra_timeout_ms: 额外超时（毫秒），最终超时 = max(config, extra_timeout_ms)
        """
        start = time.monotonic()
        page = await browser.new_page(url=None, proxy=proxy_url)

        # Cookie 注入（在 goto 之前）
        if cookies:
            try:
                await page.context.add_cookies(cookies)
            except Exception as e:
                logger.warning(f"Cookie 注入失败: {e}")

        on_page_created = getattr(parser, "on_page_created", None)
        if on_page_created is not None:
            await on_page_created(page, url)

        timeout_ms = self.config.get_int("request_timeout", 30) * 1000
        if extra_timeout_ms > timeout_ms:
            timeout_ms = extra_timeout_ms
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        duration_ms = int((time.monotonic() - start) * 1000)

        on_page_loaded = getattr(parser, "on_page_loaded", None)
        if on_page_loaded is not None:
            await on_page_loaded(page, url)

        on_wait_ready = getattr(parser, "on_wait_ready", None)
        if on_wait_ready is not None:
            await on_wait_ready(page)

        return page, duration_ms

    async def _extract_and_parse_html(
        self, page: Any, parser: Any, url: str, queue_id: int, request_id: int,
    ) -> tuple[str, list[dict], int, str | None]:
        """提取 HTML（最多重试 3 次）→ 保存原始响应 → parse → 返回结果。"""
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
        return html, data, response_size, raw_path

    # ---------------- 主入口 ----------------

    def process_url(self, task: dict, parser: Any, show_window: bool = False) -> str:
        """处理单个 URL，返回最终状态字符串。

        :param task: 状态机返回的任务字典 {id, url, ...}
        :param parser: 匹配的 Parser 实例
        :param show_window: 调试模式 — browser 模式下将页面弹到前台
        :return: "success" / "failed" / "blocked" / "skipped"
        """
        queue_id = task["id"]
        url = task["url"]
        logger.info(f"[RequestPool] 请求 {url}")

        # 事件循环桥接：
        # - self._loop（production）：用持久循环，保证 Playwright 对象在同循环内可用
        # - 否则：asyncio.run() 创建临时循环（测试兼容，AsyncMock 不绑定循环）
        try:
            if self._loop is not None and not self._loop.is_closed():
                result = self._loop.run_until_complete(
                    self._process_url_async(task, parser, show_window=show_window)
                )
            else:
                result = asyncio.run(self._process_url_async(task, parser, show_window=show_window))
            return result
        except RuntimeError as e:
            if "asyncio.run() cannot be called from a running event loop" in str(e):
                loop = asyncio.get_running_loop()
                return loop.run_until_complete(
                    self._process_url_async(task, parser, show_window=show_window)
                )
            raise
        except Exception as e:
            logger.error(f"process_url 异常: {url} {e}", exc_info=True)
            self.state_machine.mark_failed(queue_id, ERROR_NETWORK, str(e))
            return "failed"

    async def _process_url_async(self, task: dict, parser: Any, show_window: bool = False) -> str:
        """异步处理单个 URL 的完整流程。

        根据 task.fetch_mode 分支：
        - ``"http"`` → httpx 直接请求，返回 HTML 字符串
        - ``"browser"`` → Playwright 浏览器加载，返回 Page 对象
        两种模式后续流程（parse/save/enqueue）完全一致。
        """
        queue_id = task["id"]
        url = task["url"]

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

        # 1. 申请代理 IP
        proxy_record = None
        proxy_url = None
        if self.proxy_pool is not None:
            proxy_record = await self.proxy_pool.acquire_async()
            if proxy_record is not None:
                proxy_url = self._build_proxy_url(proxy_record)

        # 2. 记录请求开始
        method = "GET"
        rc_str = task.get("request_config")
        if rc_str:
            try:
                rc = json.loads(rc_str) if isinstance(rc_str, str) else rc_str
                method = rc.get("method", "GET")
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        request_id = self.storage.create_request(
            queue_id=queue_id,
            url=url,
            proxy_ip=proxy_record.ip if proxy_record else None,
            method=method,
        )

        # === CDP 模式 ===
        if fetch_mode == "cdp":
            page = None
            try:
                if self.cdp_browser is None:
                    logger.warning("cdp_browser 未注入，无法使用 CDP 模式")
                    self._fail_task(request_id, queue_id, ERROR_NETWORK, "cdp_browser 未注入", proxy_record)
                    return "failed"

                playwright_cookies = self._extract_cookies_from_task(task)
                page, cdp_duration_ms = await self._browser_page_lifecycle(
                    self.cdp_browser, url, parser, proxy_url, cookies=playwright_cookies,
                )

                # 验证码检测
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
                    html, data, response_size, raw_path = await self._extract_and_parse_html(
                        page, parser, url, queue_id, request_id,
                    )
                except Exception as e:
                    logger.error(f"[Parser:{parser.__class__.__name__}] CDP 解析失败: {url} {e}", exc_info=True)
                    self._fail_task(request_id, queue_id, ERROR_PARSE, str(e), proxy_record,
                                   duration_ms=cdp_duration_ms, raw_response_path=raw_path)
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
                self._fail_task(request_id, queue_id, ERROR_NETWORK, str(e), proxy_record)
                if page is not None and self.cdp_browser is not None and not self.keep_browser_open:
                    try:
                        await self._close_page_with_hook(page, parser)
                    except Exception:
                        pass
                return "failed"

        # === HTTP 模式 ===
        if fetch_mode == "http":
            try:
                http_result = await self._fetch_http(task, parser, proxy_record)
                html = http_result["html"]
                duration_ms = http_result["duration_ms"]
                response_size = http_result["response_size"]
                resp_headers = http_result["response_headers"]
                req_headers = http_result["request_headers"]

                # 保存原始响应
                raw_path = self._save_raw_response(queue_id, request_id, html)

                # HTTP 模式验证码检测（文本特征匹配）
                if self.captcha_handler is not None and self._detect_captcha_in_text(html, url):
                    logger.warning(f"[Captcha:HTTP] 触发: {url}")
                    self.storage.execute(
                        "UPDATE requests SET captcha_triggered = 1 WHERE id = ?",
                        (request_id,), fetch="none",
                    )
                    self.storage.mark_request_failed(
                        request_id, "HTTP响应含验证码", status_code=None,
                        duration_ms=duration_ms, raw_response_path=raw_path,
                        response_headers=resp_headers,
                    )
                    self.state_machine.mark_blocked(queue_id, ERROR_CAPTCHA, "HTTP响应含验证码")
                    self._release_proxy(proxy_record, success=False)
                    return "blocked"

                # 解析（Parser 已兼容 HTML 字符串）
                try:
                    parser.storage = self.storage
                    data = parser.parse(html, url)
                except Exception as e:
                    logger.error(f"[Parser:{parser.__class__.__name__}] 解析失败: {url} {e}", exc_info=True)
                    self._fail_task(request_id, queue_id, ERROR_PARSE, str(e), proxy_record,
                                   duration_ms=duration_ms, raw_response_path=raw_path,
                                   response_headers=resp_headers)
                    return "failed"

                return await self._finish_request(
                    task, parser, html, data,
                    queue_id, request_id, proxy_record, proxy_url,
                    duration_ms=duration_ms, response_size=response_size,
                    raw_response_path=raw_path,
                    response_headers=resp_headers, request_headers=req_headers,
                )

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                logger.error(f"[HTTP:{status}] {url}")
                # 尝试保存失败响应
                raw_path = None
                resp_headers = None
                try:
                    raw_path = self._save_raw_response(queue_id, request_id, e.response.text)
                    resp_headers = dict(e.response.headers)
                except Exception:
                    pass
                self.storage.mark_request_failed(
                    request_id, str(e), status_code=status,
                    duration_ms=None, raw_response_path=raw_path,
                    response_headers=resp_headers,
                )
                if 400 <= status < 500:
                    self.state_machine.mark_blocked(queue_id, ERROR_403, str(e))
                    self._release_proxy(proxy_record, success=False)
                    return "blocked"
                else:
                    self.state_machine.mark_failed(queue_id, ERROR_5XX, str(e))
                    self._release_proxy(proxy_record, success=False)
                    return "failed"

            except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
                error_type_name = type(e).__name__
                error_type = ERROR_NETWORK
                if isinstance(e, httpx.TimeoutException):
                    error_type_name = "Timeout"
                elif isinstance(e, httpx.ConnectError):
                    error_type_name = "ConnectError"
                logger.error(f"[HTTP:{error_type_name}] {url}: {e}")
                self._fail_task(request_id, queue_id, error_type, str(e), proxy_record)
                return "failed"

        # === Browser 模式 ===
        page = None
        try:
            if self.browser is None:
                logger.warning("browser 未注入，跳过浏览器加载")
                self._fail_task(request_id, queue_id, ERROR_NETWORK, "browser 未注入", proxy_record)
                return "failed"

            playwright_cookies = self._extract_cookies_from_task(task)
            page, browser_duration_ms = await self._browser_page_lifecycle(
                self.browser, url, parser, proxy_url, cookies=playwright_cookies,
            )
            self._last_page = page
            self._last_parser = parser

            # show_window 调试增强（仅 browser 模式）
            if show_window:
                try:
                    await page.bring_to_front()
                    await page.evaluate("window.focus();")
                    await page.evaluate(
                        "document.title = '>>> 测试中 <<< ' + document.title; "
                        "setTimeout(() => { document.title = document.title.replace('>>> 测试中 <<< ', ''); }, 800);"
                    )
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

            # 验证码检测
            if self.captcha_handler is not None and await self.captcha_handler.is_captcha_page_async(page):
                logger.warning(f"[Captcha] 触发: {url}, IP: {proxy_record.ip if proxy_record else 'direct'}")

                # 保存触发验证码的页面内容
                try:
                    captcha_html = await page.content()
                    raw_path = self._save_raw_response(queue_id, request_id, captcha_html)
                except Exception:
                    raw_path = None

                self.storage.execute(
                    "UPDATE requests SET captcha_triggered = 1 WHERE id = ?",
                    (request_id,), fetch="none",
                )
                captcha_result = self.captcha_handler.handle(
                    page=page,
                    queue_id=queue_id,
                    request_id=request_id,
                    increment_ip_switch=self.state_machine.increment_ip_switch,
                )
                if captcha_result == "solved":
                    logger.info(f"验证码已解决，继续抓取: {url}")
                    self.storage.execute(
                        "UPDATE requests SET captcha_triggered = 0 WHERE id = ?",
                        (request_id,), fetch="none",
                    )
                elif captcha_result == "switch_ip":
                    self.storage.mark_request_failed(
                        request_id, "验证码触发换IP", status_code=None,
                        duration_ms=browser_duration_ms, raw_response_path=raw_path,
                    )
                    self._release_proxy(proxy_record, success=False)
                    if not self.keep_browser_open:
                        await self.browser.close_page(page)
                    return await self._retry_with_new_ip(task, parser)
                else:
                    self.storage.mark_request_failed(
                        request_id, "验证码需人工处理", status_code=None,
                        duration_ms=browser_duration_ms, raw_response_path=raw_path,
                    )
                    self.state_machine.mark_blocked(queue_id, ERROR_CAPTCHA, "验证码需人工")
                    self._release_proxy(proxy_record, success=False)
                    if not self.keep_browser_open:
                        await self._close_page_with_hook(page, parser)
                    return "blocked"

            # 解析
            raw_path = None
            try:
                html, data, response_size, raw_path = await self._extract_and_parse_html(
                    page, parser, url, queue_id, request_id,
                )
            except Exception as e:
                logger.error(f"[Parser:{parser.__class__.__name__}] 解析失败: {url} {e}", exc_info=True)
                self._fail_task(request_id, queue_id, ERROR_PARSE, str(e), proxy_record,
                               duration_ms=browser_duration_ms, raw_response_path=raw_path)
                if not self.keep_browser_open:
                    await self._close_page_with_hook(page, parser)
                return "failed"

            return await self._finish_request(
                task, parser, html, data,
                queue_id, request_id, proxy_record, proxy_url, page=page,
                duration_ms=browser_duration_ms, response_size=response_size,
                raw_response_path=raw_path,
            )

        except Exception as e:
            logger.error(f"请求处理异常: {url} {e}", exc_info=True)
            self._fail_task(request_id, queue_id, ERROR_NETWORK, str(e), proxy_record)
            if page is not None and self.browser is not None and not self.keep_browser_open:
                try:
                    await self._close_page_with_hook(page, parser)
                except Exception:
                    pass
            return "failed"

    # ---------------- 共享后处理（双模式复用） ----------------

    async def _finish_request(
        self,
        task: dict,
        parser: Any,
        html: str,
        data: list[dict],
        queue_id: int,
        request_id: int,
        proxy_record: Any | None,
        proxy_url: str | None,
        page: Any = None,
        duration_ms: int | None = None,
        response_size: int | None = None,
        raw_response_path: str | None = None,
        response_headers: dict | None = None,
        request_headers: dict | None = None,
    ) -> str:
        """解析后的共享流程：保存数据 / 更新状态。

        URL 入队和图片下载已由 parser.parse() 自行完成。
        """
        logger.info(
            f"[Parser:{parser.__class__.__name__}] 提取数据: {len(data) if data else 0}条"
        )

        # 校验：解析结果为空（[] / None）→ 标记失败
        if not data:
            logger.warning(
                f"[Parser:{parser.__class__.__name__}] 解析结果为空, "
                f"标记失败 (url={task.get('url')})"
            )
            self.storage.mark_request_failed(
                request_id=request_id,
                error_msg="解析结果为空（页面无数据或结构变更）",
            )
            self.state_machine.mark_failed(queue_id, ERROR_PARSE, "解析结果为空")
            self._release_proxy(proxy_record, success=False)
            if page is not None and self.browser is not None and not self.keep_browser_open:
                await self._close_page_with_hook(page, parser)
            return "failed"

        # 保存业务数据（先确保表存在，幂等）
        parser.ensure_table(self.storage)
        self.storage.save_business_data(parser.table_name, data)

        # 更新状态
        self.storage.mark_request_success(
            request_id=request_id,
            extracted_data=data[0] if data else None,
            duration_ms=duration_ms,
            response_size=response_size,
            status_code=200,
            raw_response_path=raw_response_path,
            response_headers=response_headers,
            request_headers=request_headers,
        )
        self.state_machine.mark_done(queue_id)
        self._release_proxy(proxy_record, success=True)

        # Browser 模式关闭 page（调试模式 keep_browser_open 时跳过）
        if page is not None and self.browser is not None and not self.keep_browser_open:
            await self._close_page_with_hook(page, parser)

        return "success"

    # ---------------- HTTP 请求 ----------------

    async def _fetch_http(
        self, task: dict, parser: Any, proxy_record: Any | None
    ) -> dict:
        """HTTP 模式获取 HTML，返回包含元数据的字典。

        :return: dict with keys:
            ``html``: 响应文本,
            ``duration_ms``: 请求耗时(ms),
            ``response_size``: 响应体字节数,
            ``status_code``: HTTP 状态码,
            ``response_headers``: 响应头 dict,
            ``request_headers``: 实际发送的请求头 dict
        """
        url = task["url"]

        # === Layer 1: config 全局默认 ===
        if self.config.get_bool("anti_bot_random_ua", False):
            ua = self._get_random_ua()
        else:
            ua = self.config.get(
                "http_user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
        merged_headers = {
            "User-Agent": ua,
        }
        default_headers_str = self.config.get("http_default_headers", "{}")
        try:
            default_headers = json.loads(default_headers_str or "{}")
            merged_headers.update(default_headers)
        except json.JSONDecodeError:
            logger.warning(f"http_default_headers 解析失败，使用空字典: {default_headers_str!r}")

        # === Layer 2: Parser 级补充 ===
        merged_headers.update(getattr(parser, "http_headers", {}))
        merged_params = dict(getattr(parser, "http_default_params", {}))
        method = getattr(parser, "http_method", "GET")

        # === Layer 3: 任务级覆盖 ===
        rc_str = task.get("request_config") or "{}"
        try:
            rc = json.loads(rc_str)
        except (json.JSONDecodeError, TypeError):
            rc = {}

        method = rc.get("method", method)
        merged_headers.update(rc.get("headers", {}))
        merged_params.update(rc.get("params", {}))
        cookies = rc.get("cookies", {})
        timeout = rc.get("timeout", self.config.get_int("request_timeout", 30))

        # 代理
        proxy = self._build_proxy_url(proxy_record) if proxy_record else None

        # 发请求（计时）
        async with httpx.AsyncClient(
            proxy=proxy,
            follow_redirects=self.config.get_bool("http_follow_redirects", True),
            timeout=httpx.Timeout(timeout),
        ) as client:
            request_kwargs: dict[str, Any] = {
                "headers": merged_headers,
                "params": merged_params,
                "cookies": cookies,
            }

            # body 三选一（优先级 json > form_data > body）
            if rc.get("json_body") is not None:
                request_kwargs["json"] = rc["json_body"]
            elif rc.get("form_data") is not None:
                request_kwargs["data"] = rc["form_data"]
            elif rc.get("body") is not None:
                request_kwargs["content"] = rc["body"]

            start = time.monotonic()
            response = await client.request(method, url, **request_kwargs)
            duration_ms = int((time.monotonic() - start) * 1000)
            response.raise_for_status()

            return {
                "html": response.text,
                "duration_ms": duration_ms,
                "response_size": len(response.content),
                "status_code": response.status_code,
                "response_headers": dict(response.headers),
                "request_headers": dict(response.request.headers) if response.request else merged_headers,
            }

    # ---------------- HTTP 验证码检测 ----------------

    @staticmethod
    def _detect_captcha_in_text(html: str, url: str) -> bool:
        """HTTP 模式验证码检测：检查 HTML 文本是否包含验证码特征。"""
        text = html.lower()
        captcha_markers = [
            "antibot/verifycode",
            "callback.58.com/antibot",
            "sec.58.com",
            "验证码",
            "安全验证",
            "人机验证",
            "请输入验证码",
            "拖动滑块",
        ]
        for marker in captcha_markers:
            if marker.lower() in text:
                logger.info(f"HTTP 响应检测到验证码特征: {marker!r} url={url}")
                return True
        return False

    # ---------------- 换 IP 重试 ----------------

    async def _retry_with_new_ip(self, task: dict, parser: Any) -> str:
        """换 IP 后重试（验证码触发 switch_ip 降级时）。

        本期简化：直接标记 blocked 让调度器重新入队。
        真实实现应在这里申请新 IP 并重新走 _process_url_async。
        """
        queue_id = task["id"]
        logger.info(f"换 IP 重试（简化为 blocked 等待重置）: queue_id={queue_id}")
        # 已在 captcha_handler 中 increment_ip_switch，这里不再重复
        # 让状态保持 running 由调度器处理 — 但实际 increment_ip_switch 未超限时
        # 应该重新入队。这里简化：标记 failed 让 acquire 重新取到。
        self.state_machine.mark_failed(queue_id, ERROR_CAPTCHA, "换 IP 等待重试")
        return "failed"

    # ---------------- 反爬 ----------------

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
                return ua_str
        except Exception:
            pass

        import random
        return random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
        ])

    def _apply_anti_bot(self, proxy_record: Any | None) -> dict[str, str]:
        """应用反爬处理：随机 UA / Referer / Cookie。

        :return: 额外 headers 字典
        """
        headers: dict[str, str] = {}
        # 随机 UA
        ua = self._get_random_ua()
        headers["User-Agent"] = ua
        # 随机延迟已在 RateLimiter 处理
        logger.debug(f"反爬 UA: {ua[:40]}...")
        return headers

    # ---------------- 代理回收 ----------------

    def _release_proxy(self, proxy_record: Any | None, success: bool) -> None:
        """回收代理 IP。"""
        if proxy_record is None or self.proxy_pool is None:
            return
        try:
            if success:
                self.proxy_pool.release_success(proxy_record)
            else:
                self.proxy_pool.release_fail(proxy_record)
        except Exception as e:
            logger.warning(f"回收代理失败: {e}")

    # ---------------- 原始响应保存 ----------------

    @staticmethod
    def _save_raw_response(queue_id: int, request_id: int, content: str) -> str:
        """保存原始响应文本到 raw_responses，返回相对于 PROJECT_ROOT 的路径。

        :param queue_id: 队列 ID
        :param request_id: 请求 ID
        :param content: 响应文本内容（HTML/JSON/纯文本）
        :return: 相对路径，如 ``data/raw_responses/1_3_20260621_162500.html``
        """
        os.makedirs(RAW_RESPONSE_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{queue_id}_{request_id}_{ts}.html"
        filepath = os.path.join(RAW_RESPONSE_DIR, filename)
        # 截断过大的响应（>5MB 截断为头尾各 2.5MB，防止磁盘爆炸）
        max_size = 5 * 1024 * 1024
        if len(content) > max_size:
            half = max_size // 2
            content = content[:half] + "\n\n<!-- ... 响应过大，已截断 ... -->\n\n" + content[-half:]
            logger.warning(f"原始响应过大({len(content)/1024/1024:.1f}MB)，已截断至 5MB: {filepath}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug(f"原始响应已保存: {filepath}")
        return os.path.relpath(filepath, PROJECT_ROOT)

    # ---------------- 等待所有任务 ----------------

    def wait_all(self, timeout: float = 60.0) -> None:
        """等待所有活跃任务完成（优雅退出用）。"""
        if not self._active_tasks:
            return
        logger.info(f"等待 {len(self._active_tasks)} 个活跃任务完成...")
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        # 简化：sleep 等待
        deadline = time.monotonic() + timeout
        while self._active_tasks and time.monotonic() < deadline:
            time.sleep(0.5)

    # ---------------- 代理 URL ----------------

    @staticmethod
    def _build_proxy_url(proxy_record: Any) -> str:
        """根据 ProxyRecord 构建代理 URL，带账密认证。

        有账密: ``http://user:pass@ip:port``
        无账密: ``http://ip:port``
        """
        auth = ""
        if getattr(proxy_record, "username", None) and getattr(proxy_record, "password", None):
            auth = f"{proxy_record.username}:{proxy_record.password}@"
        return f"http://{auth}{proxy_record.ip}:{proxy_record.port}"

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

    # ---------------- debug_parse 调试入口 ----------------

    async def debug_parse(
        self, url: str, registry: Any, parser_name: str = "",
        show_window: bool = False, keep_open_seconds: int = 0,
    ) -> dict:
        """get-url 完整流程：创建 debug RequestPool → process_url → 读取捕获结果。

        与 :meth:`process_url` 走 **完全相同** 的代码路径（``_process_url_async``），
        区别仅在于注入 ``DebugStorage``（捕获数据不写 DB）+ ``NoOpStateMachine`` + 无代理/验证码/图片下载。

        :param keep_open_seconds: > 0 时抓取完成后保持浏览器页面打开（默认 1 小时），
            返回 debug_session_id 供前端调用 close_debug_page 手动关闭。
        :returns: {ok, parser, fetch_mode, duration_ms, data, data_count, raw_preview, raw_path, ...}
        """
        import time as _time
        import uuid as _uuid

        t0 = _time.perf_counter()

        # ── 1. 匹配 Parser ──
        if parser_name:
            matched_cls = None
            for cls in registry.classes:
                if cls.__name__ == parser_name:
                    matched_cls = cls
                    break
            if not matched_cls:
                return {"ok": False, "error": f"Parser '{parser_name}' 不存在"}

            parser = registry.match(url)
            if parser is None or parser.__class__.__name__ != parser_name:
                instance = matched_cls(registry.tools)
                if not instance.matches(url):
                    return {"ok": False, "error": f"URL 不匹配 Parser '{parser_name}'"}
                parser = instance
        else:
            parser = registry.match(url)
            if not parser:
                return {"ok": False, "error": "未找到匹配该 URL 的 Parser"}

        # ── 2. Cookie 预设匹配（与 queue.py 入队逻辑一致）──
        request_config: dict = {}
        try:
            matched_preset = self.storage.match_cookie_preset(url)
            if matched_preset is not None:
                preset_cookies = json.loads(matched_preset[3])  # cookies_json 列
                if isinstance(preset_cookies, list) and len(preset_cookies) > 0:
                    request_config["cookies"] = {
                        item["name"]: item["value"]
                        for item in preset_cookies
                        if "name" in item and "value" in item
                    }
        except Exception:
            pass

        # ── 3. 构建 task dict ──
        fetch_mode = (
            getattr(parser, "preferred_fetch_mode", None)
            or self.config.get("fetch_mode", "browser")
        )
        if getattr(parser, "requires_browser", False):
            fetch_mode = "browser"

        task = {
            "id": 0,
            "url": url,
            "fetch_mode": fetch_mode,
            "request_config": json.dumps(request_config) if request_config else None,
        }

        logger.info(
            f"[debug_parse] parser={parser.__class__.__name__} "
            f"fetch_mode={fetch_mode} show_window={show_window} "
            f"keep_open={keep_open_seconds}s "
            f"cookies={'yes' if request_config.get('cookies') else 'no'} "
            f"url={url[:80]}"
        )

        # ── 4. 创建 debug RequestPool（共享 browser/config/loop，隔离 storage/state）──
        debug_storage = _DebugStorage(self.storage)
        debug_pool = RequestPool(
            storage=debug_storage,
            config=self.config,
            state_machine=_NoOpStateMachine(),
            proxy_pool=None,       # 无代理
            browser=self.browser,  # 共享浏览器
            captcha_handler=None,  # 无验证码检测
            image_downloader=None, # 无图片下载
            loop=self._loop,       # 共享事件循环
        )
        if keep_open_seconds > 0:
            debug_pool.keep_browser_open = True

        # ── 5. 直接调用 _process_url_async（debug_parse 本身已在事件循环中）──
        status = await debug_pool._process_url_async(task, parser, show_window=show_window)
        total_duration_ms = int((_time.perf_counter() - t0) * 1000)

        # ── 6. 处理 keep_open（仅 browser 模式 + 成功拿到 page 时）──
        debug_session_id = ""
        debug_expires_at = 0
        if keep_open_seconds > 0 and debug_pool._last_page is not None and self.browser is not None:
            import threading
            session_id = _uuid.uuid4().hex[:8]
            expiry = _time.time() + keep_open_seconds
            self._debug_sessions[session_id] = {
                "page": debug_pool._last_page,
                "parser": debug_pool._last_parser,
                "browser": self.browser,
                "expiry": expiry,
                "url": url,
                "parser_name": parser.__class__.__name__,
            }
            # 自动过期关闭
            timer = threading.Timer(
                keep_open_seconds,
                lambda: self._auto_close_debug_page(session_id),
            )
            timer.daemon = True
            timer.start()
            self._debug_sessions[session_id]["timer"] = timer

            debug_session_id = session_id
            debug_expires_at = int(expiry)
            logger.info(f"[debug_parse] 浏览器保持打开 session={session_id} expires_at={debug_expires_at}")

        # ── 7. 从 DebugStorage 读取捕获结果 ──
        raw_path = debug_storage.captured_raw_path or ""
        raw_preview = ""
        if raw_path:
            try:
                abs_path = os.path.join(PROJECT_ROOT, raw_path)
                with open(abs_path, "r", encoding="utf-8") as f:
                    raw_preview = f.read()[:5000]
            except Exception:
                pass

        result: dict = {
            "ok": status == "success",
            "parser": parser.__class__.__name__,
            "fetch_mode": fetch_mode,
            "duration_ms": total_duration_ms,
            "fetch_duration_ms": debug_storage.captured_duration_ms or 0,
            "raw_preview": raw_preview,
            "raw_path": raw_path,
        }
        if debug_session_id:
            result["debug_session_id"] = debug_session_id
            result["debug_expires_at"] = debug_expires_at

        if status == "success":
            result["data"] = debug_storage.captured_data
            result["data_count"] = len(debug_storage.captured_data)
        else:
            result["error"] = debug_storage.captured_error or f"抓取状态: {status}"

        return result

    def _auto_close_debug_page(self, session_id: str) -> None:
        """Timer 回调 — 自动关闭过期 debug 页面。"""
        session = self._debug_sessions.pop(session_id, None)
        if session is None:
            return
        page = session.get("page")
        browser = session.get("browser")
        if page is not None and browser is not None:
            loop = self._loop
            if loop and not loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    browser.close_page(page), loop
                )
        logger.info(f"[debug_parse] 自动关闭过期 session={session_id}")

    async def close_debug_page(self, session_id: str) -> dict:
        """手动关闭 debug 页面（调用 on_before_page_close 钩子 + close_page）。"""
        session = self._debug_sessions.pop(session_id, None)
        if session is None:
            return {"ok": False, "error": f"session '{session_id}' 不存在或已过期"}

        # 取消自动关闭 timer
        timer = session.get("timer")
        if timer is not None:
            timer.cancel()

        page = session.get("page")
        parser = session.get("parser")
        browser = session.get("browser")

        if page is not None and browser is not None:
            # 调用 _close_page_with_hook（含 on_before_page_close 钩子）
            await self._close_page_with_hook(page, parser)

        logger.info(f"[debug_parse] 手动关闭 session={session_id}")
        return {"ok": True, "session_id": session_id}

    def list_debug_pages(self) -> list[dict]:
        """列出当前活跃的 debug 会话（供前端轮询）。"""
        import time as _time
        now = _time.time()
        result = []
        for sid, session in self._debug_sessions.items():
            result.append({
                "session_id": sid,
                "url": session.get("url", ""),
                "parser": session.get("parser_name", ""),
                "expires_at": int(session.get("expiry", 0)),
                "remaining_seconds": max(0, int(session.get("expiry", 0) - now)),
            })
        return result

    # ---------------- 统计 ----------------

    def stats(self) -> dict[str, int]:
        """返回当前活跃任务数。"""
        return {"active": len(self._active_tasks)}


# ==================== debug_parse 辅助类 ====================


class _DebugStorage(FakeStorage):
    """FakeStorage 子类 — 捕获 save_business_data / mark_request_* 的数据供 debug_parse 读取。"""

    def __init__(self, real_storage: Storage) -> None:
        super().__init__(real_storage)
        self.captured_data: list[dict] = []
        self.captured_raw_path: str = ""
        self.captured_duration_ms: int | None = None
        self.captured_error: str = ""

    def save_business_data(self, table_name: str, rows: list[dict]) -> None:
        self.captured_data = rows

    def create_request(self, queue_id: int, url: str, proxy_ip: str | None, method: str = "GET") -> int:
        return 0  # 给一个固定 ID，让 _save_raw_response 文件名正常

    def mark_request_success(
        self, request_id: int, extracted_data=None, image_paths=None,
        duration_ms: int | None = None, response_size: int | None = None,
        status_code: int = 200, raw_response_path: str | None = None,
        response_headers: dict | None = None, request_headers: dict | None = None,
    ) -> None:
        self.captured_duration_ms = duration_ms
        if raw_response_path:
            self.captured_raw_path = raw_response_path

    def mark_request_failed(
        self, request_id: int, error_msg: str, status_code: int | None = None,
        duration_ms: int | None = None, raw_response_path: str | None = None,
        response_headers: dict | None = None,
    ) -> None:
        self.captured_error = error_msg
        if raw_response_path:
            self.captured_raw_path = raw_response_path


class _NoOpStateMachine:
    """空状态机 — 所有方法空操作，供 debug_parse 使用。

    需覆盖 _process_url_async 调用的全部 state_machine 方法：
    mark_done / mark_failed / mark_blocked / mark_skipped / increment_ip_switch
    """

    def mark_done(self, queue_id: int) -> None: pass
    def mark_failed(self, queue_id: int, error_type: str, error_msg: str) -> None: pass
    def mark_blocked(self, queue_id: int, error_type: str, error_msg: str) -> None: pass
    def mark_skipped(self, queue_id: int) -> None: pass
    def increment_ip_switch(self, queue_id: int) -> bool: return False
