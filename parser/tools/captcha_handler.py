"""验证码处理模块 - 检测验证码页面、自动接码、降级策略。

按设计文档 4.7 决策流（两个独立开关）::

    检测到验证码页
      ↓
    读 captcha_auto_solve 配置
      ├─ false → 跳过自动接码，直接走降级
      └─ true  → 自动接码，重试 captcha_max_retry 次
                  ├─ 成功 → 继续
                  └─ 失败 → 走降级
      ↓
    读 captcha_fallback 配置
      ├─ "manual"    → 暂停，弹浏览器等人工
      └─ "switch_ip" → increment_ip_switch()
                         ├─ 未超限 → 换IP重试
                         └─ 超限 → 强制转人工

关键：换IP次数记录在 queue 表 ip_switch_count 列，由 state_machine 维护。
本模块只负责"检测+尝试接码+决定降级动作"，不直接操作 IP。

ddddocr 延迟加载（与 font_decoder 同策略）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.storage import Storage

logger = get_logger("parser.captcha")

# 验证码页面识别关键词（URL / 标题 / 页面文本）
_CAPTCHA_URL_PATTERNS = [
    "captcha",
    "verify",
    "checkcode",
    "validate",
    "sec.58.com",
]
_CAPTCHA_TITLE_PATTERNS = ["验证", "安全验证", "人机验证", "captcha"]
_CAPTCHA_TEXT_PATTERNS = ["请输入验证码", "拖动滑块", "完成验证", "安全验证"]


class CaptchaHandler:
    """验证码处理器。

    依赖：
    - ``ConfigManager``: 读取 captcha_enabled / captcha_auto_solve /
      captcha_max_retry / captcha_fallback / captcha_max_switch
    - ``Storage``: 写 captcha_log 表
    - ``state_machine.increment_ip_switch``: 通过回调注入（避免循环依赖）

    :param solve_callable: 自定义接码函数 ``(page) -> bool``。
        ``None`` 时用 ddddocr + Playwright 滑块（延迟加载）。
    :param manual_pause_callback: 人工介入时调用的暂停回调 ``(page, queue_id) -> bool``。
        ``None``（默认）时仅记日志不实际暂停；
        传入 ``lambda page, qid: input("按 Enter 继续...") or True`` 可实际阻塞等待。
        返回 True 表示用户已通过验证码，handle() 返回 "solved" 继续抓取；
        返回 False 表示用户放弃，handle() 返回 "manual" 标记 blocked。
        用于集成测试/非无头调试场景。
    """

    def __init__(
        self,
        config: ConfigManager,
        storage: Storage,
        solve_callable: Callable[[Any], bool] | None = None,
        manual_pause_callback: Callable[[Any, int], bool] | None = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self._solve_callable = solve_callable
        self._manual_pause_callback = manual_pause_callback
        self._solver: Any = None

    # ---------------- 配置 ----------------

    @property
    def enabled(self) -> bool:
        return self.config.get_bool("captcha_enabled", default=True)

    @property
    def auto_solve(self) -> bool:
        return self.config.get_bool("captcha_auto_solve", default=True)

    @property
    def max_retry(self) -> int:
        return self.config.get_int("captcha_max_retry", default=3)

    @property
    def fallback(self) -> str:
        return self.config.get("captcha_fallback", default="manual")

    @property
    def max_switch(self) -> int:
        return self.config.get_int("captcha_max_switch", default=5)

    # ---------------- 检测 ----------------

    def is_captcha_page(self, page: Any) -> bool:
        """检测当前 page 是否为验证码页面（同步）。

        检测顺序（任一命中即判定为验证码页）：
        1. URL 含验证码关键词
        2. 页面 title 含验证码关键词
        3. 页面 body 文本含验证码关键词

        对 Playwright async page，调用方应先用 ``await page.title()`` /
        ``await page.content()`` 获取字符串再传入；或用辅助方法
        ``is_captcha_page_async``。
        """
        if not self.enabled:
            return False
        try:
            url = page.url if hasattr(page, "url") else str(page)
        except Exception:
            url = ""
        if self._url_looks_like_captcha(url):
            logger.info(f"检测到验证码页（URL 匹配）: {url}")
            return True
        try:
            title = page.title() if hasattr(page, "title") else ""
        except Exception:
            title = ""
        if self._text_matches(title, _CAPTCHA_TITLE_PATTERNS):
            logger.info(f"检测到验证码页（title 匹配）: {title}")
            return True
        try:
            content = page.content() if hasattr(page, "content") else ""
        except Exception:
            content = ""
        if isinstance(content, str) and self._text_matches(content, _CAPTCHA_TEXT_PATTERNS):
            logger.info("检测到验证码页（body 文本匹配）")
            return True
        return False

    async def is_captcha_page_async(self, page: Any) -> bool:
        """async 版本：对 Playwright async page 自动 await title/content。"""
        if not self.enabled:
            return False
        url = ""
        try:
            url = page.url if hasattr(page, "url") else str(page)
        except Exception:
            pass
        if self._url_looks_like_captcha(url):
            logger.info(f"检测到验证码页（URL 匹配）: {url}")
            return True
        # await title
        try:
            raw = page.title() if hasattr(page, "title") else ""
            title = await raw if asyncio.iscoroutine(raw) else raw
        except Exception:
            title = ""
        if self._text_matches(title, _CAPTCHA_TITLE_PATTERNS):
            logger.info(f"检测到验证码页（title 匹配）: {title}")
            return True
        # await content
        try:
            raw = page.content() if hasattr(page, "content") else ""
            content = await raw if asyncio.iscoroutine(raw) else raw
        except Exception:
            content = ""
        if isinstance(content, str) and self._text_matches(content, _CAPTCHA_TEXT_PATTERNS):
            logger.info("检测到验证码页（body 文本匹配）")
            return True
        return False

    @staticmethod
    def _url_looks_like_captcha(url: str) -> bool:
        url_lower = url.lower()
        return any(p in url_lower for p in _CAPTCHA_URL_PATTERNS)

    @staticmethod
    def _text_matches(text: str, patterns: list[str]) -> bool:
        if not text:
            return False
        text_lower = text.lower()
        return any(p.lower() in text_lower for p in patterns)

    # ---------------- 处理主流程 ----------------

    def handle(
        self,
        page: Any,
        queue_id: int,
        request_id: int | None = None,
        increment_ip_switch: Callable[[int], bool] | None = None,
    ) -> str:
        """处理验证码页面，返回最终状态。

        返回值：
        - ``"solved"``: 自动接码成功，可继续抓取
        - ``"manual"``: 转人工介入
        - ``"switch_ip"``: 触发换 IP（调用方应换 IP 重试）
        - ``"failed"``: 接码失败且降级不可用

        :param page: Playwright Page 对象
        :param queue_id: 关联的 queue.id
        :param request_id: 关联的 requests.id
        :param increment_ip_switch: 换IP计数回调 ``(queue_id) -> bool``，
            返回 True 表示超限。switch_ip 降级时调用。
        """
        url = ""
        try:
            url = page.url if hasattr(page, "url") else ""
        except Exception:
            pass

        # 记录 captcha_log
        captcha_log_id = self._log_captcha(
            queue_id=queue_id,
            request_id=request_id,
            url=url,
            strategy="auto" if self.auto_solve else self.fallback,
        )

        # 阶段1：自动接码
        if self.auto_solve:
            solved = self._try_auto_solve(page, queue_id, captcha_log_id)
            if solved:
                self._update_captcha_log(captcha_log_id, "success")
                return "solved"
            logger.warning(f"自动接码失败 queue_id={queue_id}")

        # 阶段2：降级
        final_status = self._apply_fallback(
            queue_id, increment_ip_switch, captcha_log_id
        )

        # manual 降级时触发人工介入暂停（若注入了 pause_callback）
        if final_status == "manual":
            solved = self.manual_intervention(page, queue_id)
            if solved:
                return "solved"

        return final_status

    # ---------------- 自动接码 ----------------

    def _try_auto_solve(
        self, page: Any, queue_id: int, captcha_log_id: int
    ) -> bool:
        """尝试自动接码，最多 max_retry 次。任一成功即返回 True。"""
        for attempt in range(1, self.max_retry + 1):
            logger.info(
                f"自动接码尝试 {attempt}/{self.max_retry} queue_id={queue_id}"
            )
            self._update_captcha_log(
                captcha_log_id, attempt_count=attempt
            )
            try:
                ok = self._solve(page)
            except Exception as e:
                logger.warning(f"接码异常 attempt={attempt}: {e}")
                ok = False
            if ok:
                logger.info(f"接码成功 attempt={attempt} queue_id={queue_id}")
                return True
        return False

    def _solve(self, page: Any) -> bool:
        """执行一次接码。优先注入的 callable，否则用 ddddocr。"""
        if self._solve_callable is not None:
            return bool(self._solve_callable(page))
        # 延迟加载 ddddocr + Playwright 滑块逻辑
        return self._solve_with_ddddocr(page)

    def _solve_with_ddddocr(self, page: Any) -> bool:
        """用 ddddocr + Playwright 处理滑块验证码。

        本期为占位实现（返回 False）。真实实现需要：
        1. 截图找滑块元素
        2. ddddocr 识别缺口位置
        3. Playwright 模拟拖动
        """
        if self._solver is None:
            try:
                import ddddocr  # noqa: F401
                self._solver = True  # 标记已尝试加载
            except ImportError:
                raise RuntimeError(
                    "ddddocr 未安装，无法自动接码。请注入 solve_callable 或安装 ddddocr"
                )
        logger.warning("ddddocr 滑块接码未实现，返回 False")
        return False

    # ---------------- 降级 ----------------

    def _apply_fallback(
        self,
        queue_id: int,
        increment_ip_switch: Callable[[int], bool] | None,
        captcha_log_id: int,
    ) -> str:
        """应用降级策略。"""
        strategy = self.fallback
        logger.info(f"应用降级策略: {strategy} queue_id={queue_id}")

        if strategy == "switch_ip":
            if increment_ip_switch is None:
                logger.error(
                    "switch_ip 降级但未提供 increment_ip_switch 回调，转人工"
                )
                self._update_captcha_log(captcha_log_id, "manual")
                return "manual"
            exceeded = increment_ip_switch(queue_id)
            if exceeded:
                logger.warning(
                    f"换IP次数超限，强制转人工 queue_id={queue_id}"
                )
                self._update_captcha_log(captcha_log_id, "manual")
                return "manual"
            self._update_captcha_log(captcha_log_id, "switched_ip")
            return "switch_ip"

        # 默认 manual
        self._update_captcha_log(captcha_log_id, "manual")
        return "manual"

    # ---------------- 人工介入 ----------------

    def manual_intervention(self, page: Any, queue_id: int) -> bool:
        """提示人工介入（暂停等待），返回用户是否解决了验证码。

        若 ``manual_pause_callback`` 已注入，则调用它实际阻塞等待并返回结果；
        否则仅记日志返回 False（生产模式不阻塞主循环）。
        """
        logger.warning(
            f"【人工介入】queue_id={queue_id} 请在浏览器手动完成验证码"
        )
        if self._manual_pause_callback is not None:
            try:
                return bool(self._manual_pause_callback(page, queue_id))
            except Exception as e:
                logger.error(f"manual_pause_callback 异常: {e}")
                return False
        self._log_captcha(
            queue_id=queue_id,
            request_id=None,
            url=getattr(page, "url", ""),
            strategy="manual",
            final_status="manual",
        )
        return False

    # ---------------- captcha_log 持久化 ----------------

    def _log_captcha(
        self,
        queue_id: int,
        request_id: int | None,
        url: str,
        strategy: str = "",
        final_status: str = "",
        attempt_count: int = 0,
    ) -> int:
        """写 captcha_log 表，返回 id。"""
        with self.storage.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO captcha_log "
                "(queue_id, request_id, url, strategy, attempt_count, final_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (queue_id, request_id, url, strategy, attempt_count, final_status),
            )
            return cur.lastrowid

    def _update_captcha_log(
        self,
        captcha_log_id: int,
        final_status: str | None = None,
        attempt_count: int | None = None,
    ) -> None:
        """更新 captcha_log 记录。"""
        sets: list[str] = ["resolved_at = CURRENT_TIMESTAMP"]
        params: list[Any] = []
        if final_status is not None:
            sets.append("final_status = ?")
            params.append(final_status)
        if attempt_count is not None:
            sets.append("attempt_count = ?")
            params.append(attempt_count)
        params.append(captcha_log_id)
        with self.storage.get_connection() as conn:
            conn.execute(
                f"UPDATE captcha_log SET {', '.join(sets)} WHERE id = ?",
                params,
            )
