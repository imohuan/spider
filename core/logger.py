"""日志模块 - 提供统一的日志记录能力（文件 + 控制台，按级别与轮转）。

按设计文档 4.1 规范：
- ``data/logs/run.log``: INFO 级，记录关键流程
- ``data/logs/error.log``: ERROR 级，仅错误
- 控制台: INFO 级，带 ANSI 颜色，实时进度
- DEBUG 模式（``log_level='DEBUG'``）: 额外输出请求详情、拦截资源、解析过程

每个业务模块通过 :func:`get_logger` 获取子 logger::

    from core.logger import get_logger
    logger = get_logger('scheduler')   # → logging.getLogger('crawler.scheduler')

入口（main.py）启动时调用一次 :func:`setup_logging` 完成初始化。
"""
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

from config import LOGS_DIR

# 匹配 ANSI 转义序列，用于文件日志去色
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# 根 logger 名称（所有子 logger 共享前缀）
ROOT_LOGGER_NAME = "crawler"

# 日志格式：2026-06-21 10:30:00 [INFO] crawler.scheduler - 消息内容
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 文件 handler 轮转参数
_RUN_LOG_FILENAME = "run.log"
_ERROR_LOG_FILENAME = "error.log"
_RUN_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_RUN_LOG_BACKUP_COUNT = 5
_ERROR_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_ERROR_LOG_BACKUP_COUNT = 3

# ANSI 颜色码（Windows 10+ / Python 3.13 原生支持 VT 序列）
_RESET = "\033[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[90m",      # 灰色
    logging.INFO: "\033[32m",       # 绿色
    logging.WARNING: "\033[33m",    # 黄色
    logging.ERROR: "\033[31m",      # 红色
    logging.CRITICAL: "\033[1;31m", # 加粗红
}


class _PlainFormatter(logging.Formatter):
    """文件日志 formatter：去除消息中的 ANSI 转义序列。

    Werkzeug 等第三方库可能输出带终端颜色码的日志消息（如 ``esc[33m``），
    在纯文本文件中显示为乱码，这里统一剥离。
    """

    def format(self, record: logging.LogRecord) -> str:
        return _ANSI_ESCAPE_RE.sub("", super().format(record))


class _ColorFormatter(logging.Formatter):
    """控制台 formatter：消息按级别着色（时间/级别/logger 名保持默认色）。

    仅对 ``%(message)s`` 部分包裹 ANSI 颜色码，避免整行染色影响可读性。
    """

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        if not color:
            return super().format(record)
        original_msg, original_args = record.msg, record.args
        try:
            message = record.getMessage()
            record.msg = f"{color}{message}{_RESET}"
            record.args = None  # 已格式化，避免再次 % 插值
            return super().format(record)
        finally:
            record.msg, record.args = original_msg, original_args


def _ensure_logs_dir() -> None:
    """确保日志目录存在（不依赖 config.ensure_dirs，便于测试隔离）。"""
    os.makedirs(LOGS_DIR, exist_ok=True)


def _build_file_handler(
    filename: str,
    level: int,
    max_bytes: int,
    backup_count: int,
) -> RotatingFileHandler:
    """创建一个 UTF-8 编码的轮转文件 handler。"""
    path = os.path.join(LOGS_DIR, filename)
    handler = RotatingFileHandler(
        filename=path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,  # 延迟创建文件，避免目录不存在时崩溃
    )
    handler.setLevel(level)
    handler.setFormatter(_PlainFormatter(_LOG_FORMAT, _DATE_FORMAT))
    return handler


def _build_console_handler(level: int) -> logging.StreamHandler:
    """创建带颜色的控制台 handler。"""
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(_ColorFormatter(_LOG_FORMAT, _DATE_FORMAT))
    return handler


def setup_logging(log_level: str = "INFO") -> None:
    """初始化日志系统。由 main.py 启动时调用一次。

    - ``log_level``: ``'INFO'`` 或 ``'DEBUG'``（大小写不敏感）
    - 配置根 logger ``crawler`` 的 handlers 和 level
    - ``run.log``: INFO 级，文件按 10MB 滚动保留 5 份
    - ``error.log``: ERROR 级，按 5MB 滚动保留 3 份
    - 控制台: INFO 级带颜色（DEBUG 模式下显示 DEBUG）

    多次调用幂等：会先清空已有的 handler，避免重复输出。
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    _ensure_logs_dir()

    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(level)  # 根级别决定能否收到 DEBUG 日志

    # 清空旧 handler，避免重复调用时叠加输出
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    # run.log: INFO 级（DEBUG 模式下也包含 DEBUG，由根 level 控制）
    run_level = logging.DEBUG if level == logging.DEBUG else logging.INFO
    root.addHandler(_build_file_handler(
        _RUN_LOG_FILENAME, run_level, _RUN_LOG_MAX_BYTES, _RUN_LOG_BACKUP_COUNT,
    ))
    # error.log: 仅 ERROR 及以上
    root.addHandler(_build_file_handler(
        _ERROR_LOG_FILENAME, logging.ERROR, _ERROR_LOG_MAX_BYTES, _ERROR_LOG_BACKUP_COUNT,
    ))
    # 控制台：与 run.log 同级，带颜色
    root.addHandler(_build_console_handler(run_level))

    # 避免日志向上传播到 root logger（否则可能被默认 handler 重复打印）
    root.propagate = False

    # 桥接 werkzeug（Flask 开发服务器）日志到 crawler 体系
    # 否则 Flask 的启动 banner、原生 access log 等全部丢失
    _werkzeug = logging.getLogger("werkzeug")
    _werkzeug.handlers.clear()
    _werkzeug.setLevel(level)
    for h in root.handlers:
        _werkzeug.addHandler(h)
    _werkzeug.propagate = False


def get_logger(module_name: str) -> logging.Logger:
    """获取子 logger。

    :param module_name: 模块名，如 ``'proxy'`` / ``'scheduler'``。
                        也可以传完整名 ``'crawler.proxy'``，会原样使用。
    :return: ``logging.getLogger('crawler.' + module_name)``
    """
    if not module_name:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if module_name.startswith(ROOT_LOGGER_NAME + "."):
        full_name = module_name
    else:
        full_name = f"{ROOT_LOGGER_NAME}.{module_name}"
    logger = logging.getLogger(full_name)
    # 子 logger 放行所有级别（DEBUG），实际过滤由根 logger 的 handler level 决定
    logger.setLevel(logging.DEBUG)
    return logger
