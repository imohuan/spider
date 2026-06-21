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


# 25 项默认配置（设计文档 3.1）
# 顺序与文档表格一致，便于人工对照
_DEFAULT_CONFIGS: list[tuple[str, str, str]] = [
    # --- 代理 ---
    ("proxy_enabled", "true", "是否启用代理"),
    ("proxy_provider", "juliang", "代理服务商:juliang/kuaidaili"),
    ("proxy_api_url", "", "巨量HTTP API提取URL"),
    ("proxy_fetch_num", "10", "每次拉取IP数量"),
    ("proxy_ttl", "60", "IP有效期秒数"),
    ("proxy_max_use", "3", "单IP最多使用次数"),
    ("proxy_health_interval", "300", "健康检查间隔秒"),
    # --- 缓存 ---
    ("cache_enabled", "true", "是否启用静态资源缓存"),
    ("cache_html_ttl", "86400", "HTML缓存有效期秒"),
    # --- 图片 ---
    ("image_download", "true", "是否下载业务图片"),
    # --- 请求 ---
    ("request_concurrency", "3", "全局并发数"),
    ("request_interval_min", "1.0", "请求最小间隔秒"),
    ("request_interval_max", "3.0", "请求最大间隔秒"),
    ("request_timeout", "30", "请求超时秒"),
    ("retry_network", "3", "网络错误重试次数"),
    ("retry_5xx", "2", "5xx错误重试次数"),
    ("retry_parse", "1", "解析失败重试次数"),
    ("queue_max_retry", "3", "队列任务最大重试次数"),
    ("domain_rate_limit", "10", "单域名每秒最大请求数"),
    ("ip_rate_limit", "5", "单IP每分钟最大请求数"),
    # --- 并发控制 ---
    ("crawler_max_running", "3", "URL队列最大并发 running 数"),
    ("image_download_concurrency", "5", "图片下载并发数"),
    ("image_download_poll_sec", "5", "图片队列轮询间隔秒"),
    ("image_download_batch", "10", "图片队列每批拉取数"),
    # --- 验证码 ---
    ("captcha_enabled", "true", "是否处理验证码"),
    ("captcha_auto_solve", "true", "是否自动接码"),
    ("captcha_max_retry", "3", "自动接码重试次数"),
    ("captcha_fallback", "manual", "降级策略:manual/switch_ip"),
    ("captcha_max_switch", "5", "换IP模式单URL最多换IP次数"),
    ("captcha_cooldown", "1800", "触发验证码后IP冷却秒"),
    # --- 日志 ---
    ("log_level", "INFO", "日志级别:INFO/DEBUG"),
    # --- HTTP 模式 ---
    ("fetch_mode", "browser", "默认抓取模式:browser/http"),
    ("http_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "HTTP模式默认UA"),
    ("http_default_headers", "{}", "HTTP模式默认headers(JSON)"),
    ("http_follow_redirects", "true", "HTTP模式是否跟随重定向"),
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
