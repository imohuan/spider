"""项目引导模块 — 提供跨入口复用的初始化、清理、工具函数。

解决 test_parser_direct.py / main.py / dev.py 三处重复代码。
放在 core/ 而非 config.py 是因为 core.logger 已依赖 config，放 config.py 会循环导入。
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any

import config
from core.logger import setup_logging, get_logger


# ═══════════════════════════════════════════════════════════════
# 环境初始化
# ═══════════════════════════════════════════════════════════════

def init_environment(log_level: str = "INFO", logger_name: str = "main") -> logging.Logger:
    """确保目录 + 初始化日志，返回 logger。

    三个入口文件都重复的 3 行代码：
        config.ensure_dirs()
        setup_logging(log_level)
        logger = get_logger("...")

    :param log_level: 日志级别，默认 INFO
    :param logger_name: logger 名称，默认 "main"
    """
    config.ensure_dirs()
    setup_logging(log_level)
    return get_logger(logger_name)


# ═══════════════════════════════════════════════════════════════
# 异步事件循环
# ═══════════════════════════════════════════════════════════════

def create_event_loop() -> asyncio.AbstractEventLoop:
    """创建并设置为当前线程的持久事件循环。

    Playwright 要求对象绑定同一循环，必须全程用一个 loop，不能用 asyncio.run()。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def cancel_all_tasks(loop: asyncio.AbstractEventLoop, logger: logging.Logger | None = None) -> None:
    """取消事件循环中所有待处理任务，静默清理。

    Ctrl+C 后 Playwright 连接可能已断开，导致残留的 Connection.run() 协程。
    不清理则 ``loop.close()`` 打印 "Task was destroyed but it is pending!"。
    """
    pending = asyncio.all_tasks(loop)
    if not pending:
        return
    if logger:
        logger.debug(f"取消 {len(pending)} 个待处理异步任务")
    for t in pending:
        t.cancel()
    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))


# ═══════════════════════════════════════════════════════════════
# 浏览器生命周期
# ═══════════════════════════════════════════════════════════════

def start_browser(config_mgr, headless: bool = True, loop: asyncio.AbstractEventLoop | None = None):
    """创建并启动 CrawlerBrowser，返回 browser 实例。

    :param config_mgr: ConfigManager 实例
    :param headless: 是否无头模式
    :param loop: 事件循环，不传则自动创建
    :returns: (browser, loop) 元组
    """
    from core.browser import CrawlerBrowser

    if loop is None:
        loop = create_event_loop()

    browser = CrawlerBrowser(config_mgr, headless=headless)
    loop.run_until_complete(browser.start())
    return browser, loop


def shutdown_browser(
    browser,
    loop: asyncio.AbstractEventLoop,
    logger: logging.Logger | None = None,
) -> None:
    """安全关闭浏览器并清理事件循环。

    吞掉所有异常 — 浏览器连接可能在 Ctrl+C 时已断开。
    """
    if browser is not None:
        try:
            loop.run_until_complete(browser.close())
        except Exception as e:
            if logger:
                logger.warning(f"浏览器关闭异常（可忽略）: {e}")

    # 先取消残留任务再关闭循环，避免 "Task was destroyed but it is pending!"
    cancel_all_tasks(loop, logger)
    loop.close()


# ═══════════════════════════════════════════════════════════════
# Web 管理后台
# ═══════════════════════════════════════════════════════════════

def start_web_server_in_thread(
    app,
    host: str = "127.0.0.1",
    port: int = 5000,
    logger: logging.Logger | None = None,
) -> threading.Thread:
    """在 daemon 线程中启动 Flask-SocketIO 服务器。

    :returns: 已启动的 Thread 实例
    """
    from web.app import socketio as sio

    def _run():
        if logger:
            logger.info(f"Web 管理后台启动: http://{host}:{port}")
        sio.run(app, host=host, port=port,
                debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ═══════════════════════════════════════════════════════════════
# 端口清理（开发模式）
# ═══════════════════════════════════════════════════════════════

def kill_port(port: int, label: str = "", logger: logging.Logger | None = None) -> bool:
    """终止占用指定端口的进程。

    Windows 用 netstat + taskkill，Linux/Mac 用 lsof/fuser。

    :returns: True 表示找到并杀掉了进程，False 表示端口空闲
    """
    pid = None
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = int(parts[-1])
                    break
        except Exception:
            pass
    else:
        for cmd in [["lsof", "-ti", f":{port}"], ["fuser", f"{port}/tcp"]]:
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=5)
                if result.stdout.strip():
                    pid = int(result.stdout.strip().split()[0])
                    break
            except Exception:
                continue

    if pid is None:
        return False

    msg = f"端口 {port}{' (' + label + ')' if label else ''} 被 PID {pid} 占用, 正在终止..."
    if logger:
        logger.info(msg)
    else:
        print(msg)

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=10)
    else:
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.3)
    return True


# ═══════════════════════════════════════════════════════════════
# 自动打开浏览器
# ═══════════════════════════════════════════════════════════════

def open_service_ui(
    host: str = "127.0.0.1",
    port: int = 5000,
    scheme: str = "http",
    path: str = "",
    logger: logging.Logger | None = None,
) -> None:
    """用系统默认浏览器打开服务地址。

    用于 main.py --serve 和 dev.py 启动后自动打开管理后台。

    :param host: 监听地址，默认 127.0.0.1
    :param port: 端口号
    :param scheme: 协议，默认 http
    :param path: URL 路径，默认空
    :param logger: 打印日志用
    """
    url = f"{scheme}://{host}:{port}{path}"
    if logger:
        logger.info(f"正在打开浏览器: {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        if logger:
            logger.warning(f"自动打开浏览器失败: {e}")
        else:
            print(f"[warn] 自动打开浏览器失败: {e}")
