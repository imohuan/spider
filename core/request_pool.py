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

import httpx

from config import RAW_RESPONSE_DIR, PROJECT_ROOT
from core.config_manager import ConfigManager
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

    # ---------------- 主入口 ----------------

    def process_url(self, task: dict, parser: Any) -> str:
        """处理单个 URL，返回最终状态字符串。

        :param task: 状态机返回的任务字典 {id, url, ...}
        :param parser: 匹配的 Parser 实例
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
                    self._process_url_async(task, parser)
                )
            else:
                result = asyncio.run(self._process_url_async(task, parser))
            return result
        except RuntimeError as e:
            if "asyncio.run() cannot be called from a running event loop" in str(e):
                loop = asyncio.get_running_loop()
                return loop.run_until_complete(
                    self._process_url_async(task, parser)
                )
            raise
        except Exception as e:
            logger.error(f"process_url 异常: {url} {e}", exc_info=True)
            self.state_machine.mark_failed(queue_id, ERROR_NETWORK, str(e))
            return "failed"

    async def _process_url_async(self, task: dict, parser: Any) -> str:
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
            proxy_record = self.proxy_pool.acquire()
            if proxy_record is not None:
                proxy_url = f"http://{proxy_record.ip}:{proxy_record.port}"

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

                # 验证码检测
                captcha_triggered = False
                if self.captcha_handler is not None and await self.captcha_handler.is_captcha_page_async(page):
                    captcha_triggered = True
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
                            if hasattr(page, "content"):
                                html = await page.content()
                            else:
                                html = ""
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
                    self.storage.mark_request_failed(
                        request_id, str(e), status_code=None,
                        duration_ms=duration_ms, raw_response_path=raw_path,
                        response_headers=resp_headers,
                    )
                    self.state_machine.mark_failed(queue_id, ERROR_PARSE, str(e))
                    self._release_proxy(proxy_record, success=False)
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
                self.storage.mark_request_failed(
                    request_id, str(e), status_code=None,
                )
                self.state_machine.mark_failed(queue_id, error_type, str(e))
                self._release_proxy(proxy_record, success=False)
                return "failed"

        # === Browser 模式 ===
        page = None
        try:
            if self.browser is None:
                logger.warning("browser 未注入，跳过浏览器加载")
                self.storage.mark_request_failed(
                    request_id, "browser 未注入", status_code=None,
                )
                self.state_machine.mark_failed(queue_id, ERROR_NETWORK, "browser 未注入")
                self._release_proxy(proxy_record, success=False)
                return "failed"

            browser_start = time.monotonic()
            page = await self.browser.new_page(url=None, proxy=proxy_url)

            # Parser 页面生命周期钩子（goto 前注入 JS 脚本等）
            on_page_created = getattr(parser, "on_page_created", None)
            if on_page_created is not None:
                await on_page_created(page, url)

            timeout_ms = self.config.get_int("request_timeout", 30) * 1000
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            browser_duration_ms = int((time.monotonic() - browser_start) * 1000)

            # Parser 页面加载后钩子（滚动懒加载等）
            on_page_loaded = getattr(parser, "on_page_loaded", None)
            if on_page_loaded is not None:
                await on_page_loaded(page, url)

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
                    # 清除 captcha_triggered 标记（已解决）
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
                # 等页面稳定再读 content（守卫脚本可能在跳转中，重试最多 3 次）
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
                logger.error(f"[Parser:{parser.__class__.__name__}] 解析失败: {url} {e}", exc_info=True)
                self.storage.mark_request_failed(
                    request_id, str(e), status_code=None,
                    duration_ms=browser_duration_ms, raw_response_path=raw_path,
                )
                self.state_machine.mark_failed(queue_id, ERROR_PARSE, str(e))
                self._release_proxy(proxy_record, success=False)
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
            self.storage.mark_request_failed(
                request_id, str(e), status_code=None,
            )
            self.state_machine.mark_failed(queue_id, ERROR_NETWORK, str(e))
            self._release_proxy(proxy_record, success=False)
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
            f"[Parser:{parser.__class__.__name__}] 提取数据: {len(data)}条"
        )

        # 保存业务数据（先确保表存在，幂等）
        if data:
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
        proxy = f"http://{proxy_record.ip}:{proxy_record.port}" if proxy_record else None

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

    # ---------------- 原始 HTML 获取（无 DB 写入）----------------

    async def fetch_raw_html(self, url: str, parser: Any, fetch_mode: str = "browser", show_window: bool = False) -> dict:
        """Get raw HTML without DB writes. For test-url debugging.

        :param show_window: 如果 True，goto 后将页面弹到前台（仅 browser 模式生效）
        Returns dict: {html, duration_ms, ...}
        """
        if fetch_mode == "http":
            return await self._fetch_raw_html_http(url, parser)

        # --- Browser 模式 ---
        if self.browser is None:
            raise RuntimeError("browser 未初始化")

        browser_start = time.monotonic()
        page = await self.browser.new_page(url=None)

        # Parser 生命周期钩子（goto 前注入 JS 脚本）
        # show_window 调试模式时跳过守卫脚本，避免死循环
        on_page_created = getattr(parser, "on_page_created", None)
        if on_page_created is not None and not show_window:
            await on_page_created(page, url)

        timeout_ms = self.config.get_int("request_timeout", 30) * 1000
        if show_window:
            timeout_ms = max(timeout_ms, 60000)  # 调试模式至少 60s 超时
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

        # 调试：弹到前台方便观察
        if show_window:
            try:
                await page.bring_to_front()
                # 强制 OS 级别窗口前置（Windows 专用）
                await page.evaluate("window.focus();")
                # 闪烁标题栏提示
                await page.evaluate(
                    "document.title = '>>> 测试中 <<< ' + document.title; "
                    "setTimeout(() => { document.title = document.title.replace('>>> 测试中 <<< ', ''); }, 800);"
                )
                await asyncio.sleep(0.3)
            except Exception:
                pass  # 弹窗失败不影响抓取

        browser_duration_ms = int((time.monotonic() - browser_start) * 1000)

        # Parser 生命周期钩子（滚动懒加载等）
        on_page_loaded = getattr(parser, "on_page_loaded", None)
        if on_page_loaded is not None:
            await on_page_loaded(page, url)

        # 获取 HTML（重试最多 3 次，等页面稳定）
        html = ""
        for _retry in range(3):
            try:
                await page.wait_for_load_state("domcontentloaded")
                html = await page.content() if hasattr(page, "content") else ""
                if html and len(html) > 100:
                    break
            except Exception:
                await asyncio.sleep(1)

        # show_window 时保持窗口几秒，让用户能看到渲染结果
        if show_window:
            try:
                await asyncio.sleep(3)
            except Exception:
                pass

        await self.browser.close_page(page)

        return {"html": html, "duration_ms": browser_duration_ms}

    async def _fetch_raw_html_http(self, url: str, parser: Any) -> dict:
        """HTTP mode for fetch_raw_html — no DB writes, no proxy, no parse."""

        # 构建合并请求头（复用 _fetch_http 的头部合并逻辑）
        if self.config.get_bool("anti_bot_random_ua", False):
            ua = self._get_random_ua()
        else:
            ua = self.config.get(
                "http_user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

        merged_headers = {"User-Agent": ua}

        default_headers_str = self.config.get("http_default_headers", "{}")
        try:
            default_headers = json.loads(default_headers_str or "{}")
            merged_headers.update(default_headers)
        except json.JSONDecodeError:
            pass

        merged_headers.update(getattr(parser, "http_headers", {}))

        timeout = self.config.get_int("request_timeout", 30)

        async with httpx.AsyncClient(
            follow_redirects=self.config.get_bool("http_follow_redirects", True),
            timeout=httpx.Timeout(timeout),
        ) as client:
            start = time.monotonic()
            response = await client.request("GET", url, headers=merged_headers)
            duration_ms = int((time.monotonic() - start) * 1000)
            return {
                "html": response.text,
                "duration_ms": duration_ms,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
            }

    # ---------------- 统计 ----------------

    def stats(self) -> dict[str, int]:
        """返回当前活跃任务数。"""
        return {"active": len(self._active_tasks)}
