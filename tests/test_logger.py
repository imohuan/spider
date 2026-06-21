"""logger 模块测试 - 验证 setup_logging、get_logger、三级输出、DEBUG 切换、重复调用幂等。

测试覆盖：
- get_logger 返回正确名称的子 logger
- setup_logging 配置根 logger 的 level 和 handler
- run.log 写入 INFO 及以上
- error.log 只写入 ERROR 及以上
- 控制台 handler 存在且带颜色
- DEBUG 模式下 run.log/控制台 包含 DEBUG 日志
- 重复调用 setup_logging 不叠加 handler
- 文件以 utf-8 编码写入中文不乱码
"""
import logging
import logging.handlers
import os
import re
import sys

import pytest

from core import logger as logger_module
from core.logger import get_logger, setup_logging, ROOT_LOGGER_NAME
from config import LOGS_DIR


@pytest.fixture
def fresh_root_logger():
    """每个测试前清空根 logger 的 handler，保证隔离。"""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    yield root
    # 测试后也清空
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass


@pytest.fixture
def isolated_logs_dir(tmp_path, monkeypatch):
    """把 LOGS_DIR 指向临时目录，避免污染真实 data/logs。"""
    tmp_logs = tmp_path / "logs"
    tmp_logs.mkdir()
    monkeypatch.setattr(logger_module, "LOGS_DIR", str(tmp_logs))
    return str(tmp_logs)


# ---------------- get_logger ----------------

def test_get_logger_returns_child_of_crawler(fresh_root_logger):
    """get_logger('proxy') → name 为 'crawler.proxy'。"""
    lg = get_logger("proxy")
    assert lg.name == "crawler.proxy"
    assert lg.parent is fresh_root_logger


def test_get_logger_scheduler(fresh_root_logger):
    lg = get_logger("scheduler")
    assert lg.name == "crawler.scheduler"


def test_get_logger_accepts_full_name(fresh_root_logger):
    """传入 'crawler.proxy' 不应变成 'crawler.crawler.proxy'。"""
    lg = get_logger("crawler.proxy")
    assert lg.name == "crawler.proxy"


def test_get_logger_empty_returns_root(fresh_root_logger):
    lg = get_logger("")
    assert lg.name == ROOT_LOGGER_NAME


# ---------------- setup_logging ----------------

def test_setup_logging_installs_three_handlers(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    assert len(root.handlers) == 3


def test_setup_logging_sets_root_level_info(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    assert root.level == logging.INFO


def test_setup_logging_sets_root_level_debug(fresh_root_logger, isolated_logs_dir):
    setup_logging("DEBUG")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    assert root.level == logging.DEBUG


def test_setup_logging_lowercase_level(fresh_root_logger, isolated_logs_dir):
    """大小写不敏感。"""
    setup_logging("debug")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    assert root.level == logging.DEBUG


def test_setup_logging_invalid_level_defaults_to_info(fresh_root_logger, isolated_logs_dir):
    setup_logging("NOTALEVEL")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    assert root.level == logging.INFO


def test_setup_logging_idempotent(fresh_root_logger, isolated_logs_dir):
    """多次调用不应叠加 handler。"""
    setup_logging("INFO")
    setup_logging("INFO")
    setup_logging("DEBUG")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    assert len(root.handlers) == 3


def test_setup_logging_creates_logs_dir(tmp_path, monkeypatch, fresh_root_logger):
    """目录不存在时应自动创建。"""
    tmp_logs = tmp_path / "nested" / "logs"
    monkeypatch.setattr(logger_module, "LOGS_DIR", str(tmp_logs))
    setup_logging("INFO")
    assert tmp_logs.exists()


# ---------------- 三级输出 ----------------

def _read_log(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_run_log_writes_info_and_above(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    lg = get_logger("test")
    lg.info("info 消息")
    lg.warning("warn 消息")
    lg.error("error 消息")
    # flush 所有 handler
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "run.log"))
    assert "info 消息" in content
    assert "warn 消息" in content
    assert "error 消息" in content


def test_run_log_excludes_debug_in_info_mode(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    lg = get_logger("test")
    lg.debug("debug 消息")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "run.log"))
    assert "debug 消息" not in content


def test_run_log_includes_debug_in_debug_mode(fresh_root_logger, isolated_logs_dir):
    setup_logging("DEBUG")
    lg = get_logger("test")
    lg.debug("debug 消息")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "run.log"))
    assert "debug 消息" in content


def test_error_log_only_contains_error(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    lg = get_logger("test")
    lg.info("info 消息")
    lg.warning("warn 消息")
    lg.error("error 消息")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "error.log"))
    assert "error 消息" in content
    assert "info 消息" not in content
    assert "warn 消息" not in content


def test_error_log_includes_critical(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    lg = get_logger("test")
    lg.critical("critical 消息")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "error.log"))
    assert "critical 消息" in content


# ---------------- 控制台颜色 ----------------

def test_console_handler_has_color_formatter(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    console_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(console_handlers) == 1
    assert isinstance(console_handlers[0].formatter, logger_module._ColorFormatter)


def test_console_emits_colored_message(fresh_root_logger, isolated_logs_dir, capsys):
    setup_logging("INFO")
    # 重新绑定 stdout，确保 capsys 能可靠捕获
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
            h.stream = sys.stdout
    lg = get_logger("test")
    lg.info("你好世界")
    captured = capsys.readouterr()
    # 控制台应有 ANSI 颜色码（绿色 INFO）
    assert "\033[32m" in captured.out
    assert "你好世界" in captured.out
    assert "\033[0m" in captured.out


def test_console_error_uses_red(fresh_root_logger, isolated_logs_dir, capsys):
    setup_logging("INFO")
    # 重新绑定 stdout，确保 capsys 能可靠捕获
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
            h.stream = sys.stdout
    lg = get_logger("test")
    lg.error("错误消息")
    captured = capsys.readouterr()
    assert "\033[31m" in captured.out
    assert "错误消息" in captured.out


def test_console_warning_uses_yellow(fresh_root_logger, isolated_logs_dir, capsys):
    setup_logging("INFO")
    # 重新绑定 stdout，确保 capsys 能可靠捕获
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
            h.stream = sys.stdout
    lg = get_logger("test")
    lg.warning("警告消息")
    captured = capsys.readouterr()
    assert "\033[33m" in captured.out


def test_console_debug_visible_in_debug_mode(fresh_root_logger, isolated_logs_dir, capsys):
    setup_logging("DEBUG")
    # 重新绑定 stdout，确保 capsys 能可靠捕获
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
            h.stream = sys.stdout
    lg = get_logger("test")
    lg.debug("调试消息")
    captured = capsys.readouterr()
    assert "调试消息" in captured.out
    assert "\033[90m" in captured.out  # 灰色


def test_console_debug_hidden_in_info_mode(fresh_root_logger, isolated_logs_dir, capsys):
    setup_logging("INFO")
    # 重新绑定 stdout，确保 capsys 能可靠捕获
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
            h.stream = sys.stdout
    lg = get_logger("test")
    lg.debug("调试消息")
    captured = capsys.readouterr()
    assert "调试消息" not in captured.out


# ---------------- 文件编码 ----------------

def test_file_log_utf8_chinese(fresh_root_logger, isolated_logs_dir):
    """中文写入文件不应乱码。"""
    setup_logging("INFO")
    lg = get_logger("test")
    msg = "中文测试：换IP 1.2.3.4 → 5.6.7.8, 验证码触发"
    lg.info(msg)
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "run.log"))
    assert msg in content


# ---------------- 日志格式 ----------------

def test_log_format_contains_required_fields(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    lg = get_logger("scheduler")
    lg.info("取到URL: http://example.com")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "run.log"))
    line = [l for l in content.splitlines() if "取到URL" in l][0]
    # 应包含 [INFO]、crawler.scheduler、消息
    assert "[INFO]" in line
    assert "crawler.scheduler" in line
    assert "取到URL: http://example.com" in line
    # 时间格式：2026-06-21 10:30:00
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line), f"时间格式错误: {line}"


# ---------------- 关键节点日志规范 ----------------

def test_scheduler_log_format(fresh_root_logger, isolated_logs_dir):
    """调度器取URL 节点日志示例。"""
    setup_logging("INFO")
    lg = get_logger("scheduler")
    url = "http://sh.58.com/zufang/123"
    parser_name = "list"
    lg.info(f"[Scheduler] 取到URL: {url}, parser: {parser_name}")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "run.log"))
    assert "[Scheduler] 取到URL: http://sh.58.com/zufang/123, parser: list" in content


def test_request_pool_ip_switch_log(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    lg = get_logger("request_pool")
    lg.warning("[RequestPool] 换IP: 1.2.3.4 → 5.6.7.8, 累计换IP: 3")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    content = _read_log(os.path.join(isolated_logs_dir, "run.log"))
    assert "[RequestPool] 换IP: 1.2.3.4 → 5.6.7.8, 累计换IP: 3" in content


# ---------------- RotatingFileHandler 配置 ----------------

def test_file_handlers_use_rotating(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    from logging.handlers import RotatingFileHandler
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 2  # run.log + error.log

    run_handler = next(h for h in file_handlers if h.baseFilename.endswith("run.log"))
    err_handler = next(h for h in file_handlers if h.baseFilename.endswith("error.log"))
    assert run_handler.maxBytes == 10 * 1024 * 1024
    assert run_handler.backupCount == 5
    assert err_handler.maxBytes == 5 * 1024 * 1024
    assert err_handler.backupCount == 3


def test_file_handlers_utf8_encoding(fresh_root_logger, isolated_logs_dir):
    setup_logging("INFO")
    root = logging.getLogger(ROOT_LOGGER_NAME)
    from logging.handlers import RotatingFileHandler
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 2
    # handler.encoding 在构造时就设置好（delay=True 时 stream 延迟打开）
    for h in file_handlers:
        assert (h.encoding or "").lower() == "utf-8"
    # 写入中文验证实际编码正确（写不出来或乱码会在其他测试中暴露）
    lg = get_logger("test")
    lg.info("编码验证：中文")
    for h in file_handlers:
        h.flush()
