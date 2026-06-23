"""配置管理模块 - 加载与运行时管理全局配置项（读写 config 表）。

按设计文档 3.1 实现 ``ConfigManager``，提供类型化的配置读写接口：
- ``init_defaults``: 首次启动时初始化 25 项默认配置（INSERT OR IGNORE，幂等）
- ``get/get_int/get_bool/get_float``: 按类型读取配置，不存在或转换失败返回 default
- ``set/set_many``: 写配置，自动更新 ``updated_at``
- ``get_all``: 一次性读取全部配置，返回 ``{key: value}`` dict

设计要点：
- 所有值以 TEXT 存储，读取时按需转换（与 SQLite schema 一致）
- ``init_defaults`` 用 ``INSERT OR IGNORE``，已存在的 key 不覆盖
- ``set`` 单条 UPDATE，autocommit 立即生效
- ``set_many`` 用 ``get_connection`` 显式事务，保证原子性
- 线程安全复用 ``Storage._lock``（所有调用经 ``storage.execute`` / ``get_connection``）
"""
from __future__ import annotations

from typing import Any

from core.logger import get_logger
from core.storage import Storage

logger = get_logger("config")


# 默认配置项，首次启动时 INSERT OR IGNORE（设计文档 3.1）
# 顺序与文档表格一致，便于人工对照
_DEFAULT_CONFIGS: list[tuple[str, str, str]] = [
    # --- 代理 ---
    ("proxy_enabled", "true", "启用后所有请求优先走代理池，关闭则直连"),
    ("proxy_provider", "juliang", "代理服务商，当前支持巨量(juliang)和快代理(kuaidaili)"),
    ("proxy_api_url", "", "巨量HTTP API提取链接，格式如 http://api.juliangip.com/v1/..."),
    ("proxy_fetch_num", "3", "每次从代理API拉取的IP数量上限，建议2~5"),
    ("proxy_ttl", "60", "单个IP的有效期(秒)，到期后自动释放"),
    ("proxy_max_use", "3", "单个IP最多使用次数，达到后标记失效"),
    ("proxy_health_interval", "300", "代理池健康检查间隔(秒)，定期剔除不可用IP"),
    ("proxy_test_url", "http://httpbin.org/ip", "IP连通性检测目标URL"),
    # --- 缓存 ---
    ("cache_enabled", "true", "启用后重复请求同一URL直接走缓存，减少网络开销"),
    ("cache_html_ttl", "86400", "HTML响应缓存有效期(秒)，默认86400即1天"),
    # --- 图片 ---
    ("image_download", "true", "是否下载列表/详情页中的商品图片到本地"),
    # --- 请求 ---
    ("request_concurrency", "3", "同时处理的请求任务数，过大可能触发反爬"),
    ("request_interval_min", "1.0", "两次请求之间的最小间隔(秒)，随机延迟的下限"),
    ("request_interval_max", "3.0", "两次请求之间的最大间隔(秒)，随机延迟的上限"),
    ("request_timeout", "30", "单次HTTP请求超时时间(秒)，超时后触发重试"),
    ("retry_network", "3", "连接超时/DNS失败等网络错误的重试次数"),
    ("retry_5xx", "2", "服务器返回5xx时的重试次数"),
    ("retry_parse", "1", "HTML解析失败时的重试次数，对同一页面重抓"),
    ("queue_max_retry", "3", "单个任务在队列中的最大重试次数，超出后标记失败"),
    ("domain_rate_limit", "10", "同一域名每秒最多发送的请求数，防止被封"),
    ("ip_rate_limit", "5", "同一出口IP每分钟最多请求数，配合代理池使用"),
    # --- 并发控制 ---
    ("crawler_max_running", "3", "允许同时处于running状态的队列任务上限"),
    ("image_download_concurrency", "5", "图片下载Worker线程数，增大可加速下载"),
    ("image_download_poll_sec", "5", "图片下载队列的轮询间隔(秒)，检查是否有新任务"),
    ("image_download_batch", "10", "每次从图片队列取出的批量任务数"),
    # --- 验证码 ---
    ("captcha_enabled", "true", "启用验证码检测与处理流程"),
    ("captcha_auto_solve", "true", "启用后自动调用OCR识别验证码，关闭则标记待人工处理"),
    ("captcha_max_retry", "3", "验证码识别失败后的自动重试次数"),
    ("captcha_fallback", "manual", "验证码多次失败后的降级策略：手动处理(manual)或换IP重试(switch_ip)"),
    ("captcha_max_switch", "5", "换IP模式下单个URL最多切换IP的次数"),
    ("captcha_cooldown", "1800", "触发验证码后该IP的冷却时间(秒)，冷却期内不使用"),
    # --- 日志 ---
    ("log_level", "INFO", "日志级别，DEBUG可看到完整请求响应内容"),
    # --- HTTP 模式 ---
    ("fetch_mode", "browser", "默认抓取模式：browser(Playwright浏览器) 或 http(直连httpx)，推荐http避免反爬检测"),
    ("http_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "HTTP直连模式使用的User-Agent请求头"),
    ("http_default_headers", "{}", "HTTP模式默认附加请求头，JSON格式，如 {\"Referer\":\"https://58.com\"}"),
    ("http_follow_redirects", "true", "HTTP模式是否自动跟随301/302重定向"),
    # --- AI ---
    ("ai_base_url", "", "AI API 地址，如 https://api.openai.com/v1"),
    ("ai_api_key", "", "AI API 密钥，用于调用大模型"),
    ("ai_model", "", "AI 模型名称，如 gpt-4o / deepseek-chat"),
    ("ai_system_prompt", "", "AI 系统提示词，定义 AI 的角色和行为"),
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
    # --- 高德地图 ---
    ("amap_key", "", "高德地图 Web端(JS API) Key，用于地图展示；从 console.amap.com 获取，选择「Web端(JS API)」"),
    ("amap_security_code", "", "高德地图安全密钥(securityJsCode)，2021.12.02 后申请的 JS API Key 必填"),
    ("amap_webapi_key", "", "高德地图 Web服务 Key，用于 REST API 搜索；类型必须选「Web服务」"),
]

# 真值字符串集合（小写）—— 与假值集合互斥
_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}


class ConfigManager:
    """配置管理器：读写 ``config`` 表，提供类型化访问。

    典型用法::

        from core.storage import Storage
        from core.config_manager import ConfigManager

        storage = Storage()
        cfg = ConfigManager(storage)
        cfg.init_defaults()                       # 首次启动初始化（幂等）

        if cfg.get_bool("proxy_enabled"):
            provider = cfg.get("proxy_provider")
            fetch_num = cfg.get_int("proxy_fetch_num", 10)

        cfg.set("proxy_provider", "kuaidaili")    # 运行时修改
    """

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def _normalize_value(self, value: Any) -> str:
        """将任意值转为配置存储字符串。bool 显式转 'true'/'false'。"""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    # ---------------- 初始化 ----------------

    def init_defaults(self) -> None:
        """初始化所有默认配置（幂等）。

        使用 ``INSERT OR IGNORE``：已存在的 key 不覆盖，便于：
        - 首次启动：写入全部 25 项默认值
        - 后续启动：保留用户已修改的值
        - 重复调用：无副作用
        """
        # 单事务批量插入，避免 25 次独立 commit
        with self.storage.get_connection() as conn:
            for key, value, description in _DEFAULT_CONFIGS:
                conn.execute(
                    "INSERT OR IGNORE INTO config (key, value, description) "
                    "VALUES (?, ?, ?)",
                    (key, value, description),
                )
        logger.debug(f"init_defaults 完成，共 {len(_DEFAULT_CONFIGS)} 项")

    def reset_all(self) -> None:
        """强制重置所有配置为默认值（覆盖已有值），用于 UI 重置按钮。"""
        with self.storage.get_connection() as conn:
            conn.execute("DELETE FROM config")
            for key, value, description in _DEFAULT_CONFIGS:
                conn.execute(
                    "INSERT INTO config (key, value, description) VALUES (?, ?, ?)",
                    (key, value, description),
                )
        logger.info(f"reset_all 完成，共 {len(_DEFAULT_CONFIGS)} 项")

    # ---------------- 读 ----------------

    def get(self, key: str, default: str | None = None) -> str | None:
        """读取字符串配置。不存在返回 ``default``。"""
        row = self.storage.execute(
            "SELECT value FROM config WHERE key = ?",
            (key,),
            fetch="one",
        )
        if row is None:
            return default
        return row[0]

    def get_int(self, key: str, default: int = 0) -> int:
        """读取 int 配置。不存在或无法解析返回 ``default``。"""
        value = self.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(f"get_int({key!r}): 值 {value!r} 无法转为 int，返回 default={default}")
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """读取 bool 配置。

        解析规则（大小写不敏感）：
        - ``'true'`` / ``'1'`` / ``'yes'`` → ``True``
        - ``'false'`` / ``'0'`` / ``'no'`` → ``False``
        - 其他或不存在 → ``default``
        """
        value = self.get(key)
        if value is None:
            return default
        lowered = value.strip().lower()
        if lowered in _TRUE_VALUES:
            return True
        if lowered in _FALSE_VALUES:
            return False
        logger.warning(f"get_bool({key!r}): 值 {value!r} 无法识别为 bool，返回 default={default}")
        return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """读取 float 配置。不存在或无法解析返回 ``default``。"""
        value = self.get(key)
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"get_float({key!r}): 值 {value!r} 无法转为 float，返回 default={default}")
            return default

    def get_all(self) -> dict[str, str]:
        """读取全部配置，返回 ``{key: value}`` dict。"""
        rows = self.storage.execute(
            "SELECT key, value FROM config",
            fetch="all",
        )
        return {row[0]: row[1] for row in rows} if rows else {}

    # ---------------- 写 ----------------

    def set(self, key: str, value: Any, description: str | None = None) -> None:
        """写入配置，自动更新 ``updated_at = CURRENT_TIMESTAMP``。

        - ``value`` 会被 ``str()`` 转为字符串存储（bool 转为 ``'true'``/``'false'``，
          避免直接 ``str(True) == 'True'`` 与 ``get_bool`` 解析规则不一致）
        - ``description`` 非 None 时一并更新；为 None 时保留原 description
        - 使用 UPSERT（``INSERT ... ON CONFLICT DO UPDATE``）兼容新增/更新
        """
        # bool 必须显式转小写字符串，否则 str(True)='True' 不在 _TRUE_VALUES 中
        value = self._normalize_value(value)

        if description is None:
            self.storage.execute(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                (key, value),
            )
        else:
            self.storage.execute(
                "INSERT INTO config (key, value, description, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, description = excluded.description, "
                "updated_at = CURRENT_TIMESTAMP",
                (key, value, description),
            )
        logger.debug(f"配置变更: {key} = {value}")

    def set_many(self, items: dict[str, Any]) -> None:
        """批量写入配置。

        :param items: ``{key: value}`` dict，value 规则同 :meth:`set`。
                      不支持批量更新 description（如需请单独调用 :meth:`set`）。
        在单个事务内执行，保证原子性（全成功或全回滚）。
        """
        if not items:
            return
        with self.storage.get_connection() as conn:
            for key, value in items.items():
                value = self._normalize_value(value)
                conn.execute(
                    "INSERT INTO config (key, value, updated_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                    (key, value),
                )
        logger.debug(f"批量更新 {len(items)} 项配置")
