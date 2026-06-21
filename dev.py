"""开发模式启动脚本 — 同时启动前端 Vite dev server 和 Flask 后端。

用法::

    python dev.py                  # 同时启动前后端
    python dev.py --no-proxy       # 禁用代理
    python dev.py --log-level DEBUG

前端: Vite HMR 热更新，默认 http://localhost:5175
后端: Flask + SocketIO，默认 http://127.0.0.1:5000
Vite 已配置 proxy 将 /api 和 /socket.io 转发到后端，所以直接访问 :5175 即可。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
import time

# ── 参数 ──────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="58 爬虫 - 开发模式")
parser.add_argument("--no-proxy", action="store_true", help="禁用代理池")
parser.add_argument("--no-captcha", action="store_true", help="不加载验证码模块")
parser.add_argument("--log-level", default="INFO", help="日志级别 (DEBUG|INFO)")
parser.add_argument("--web-host", default="127.0.0.1", help="Web 后台监听地址")
parser.add_argument("--web-port", type=int, default=5000, help="Web 后台端口")
parser.add_argument("--fe-host", default="localhost", help="前端 dev server 地址")
parser.add_argument("--fe-port", type=int, default=5175, help="前端 dev server 端口")
args = parser.parse_args()

# ── 环境变量 ──────────────────────────────────────────────
os.environ["NO_PROXY"] = "1" if args.no_proxy else ""
os.environ["NO_CAPTCHA"] = "1" if args.no_captcha else ""

# ── 初始化 ────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, args.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dev")

# ── 端口清理（先杀旧进程再启动）───────────────────────────

def _kill_port(port: int, label: str = "") -> bool:
    """终止占用指定端口的进程。Windows 用 netstat + taskkill，Linux/Mac 用 lsof/fuser。

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

    logger.info(f"端口 {port}{' (' + label + ')' if label else ''} 被 PID {pid} 占用, 正在终止...")
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=10)
    else:
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.3)
    return True


_kill_port(args.web_port, "Flask 后端")
_kill_port(args.fe_port, "Vite 前端")

# 确保目录
import config
config.ensure_dirs()

# 初始化日志
from core.logger import setup_logging
setup_logging(args.log_level)

# 初始化 DB（创建/迁移表，预置 Parser 表）
from core.storage import Storage
db = Storage(config.DB_PATH)

# 初始化配置
from core.config_manager import ConfigManager
config_mgr = ConfigManager(db)
config_mgr.init_defaults()  # 首次启动写入 35 项默认配置（幂等）

# ── 启动后端 ──────────────────────────────────────────────
from web.app import create_app, socketio

app = create_app()  # 开发模式：不提供静态文件，CORS 放行跨域

# 注入爬虫核心组件给 API 蓝图复用
# 开发模式下初始化最小爬虫组件集, 让 API 有可用数据返回
from parser.registry import ParserRegistry
from parser.base import ParserTools
from parser.tools.html_parser import HtmlParser
from parser.tools.font_decoder import FontDecoder
from parser.tools.image_downloader import ImageDownloader

tools = ParserTools(
    html_parser=HtmlParser(),
    font_decoder=FontDecoder(),
    image_downloader=ImageDownloader(),
)
registry = ParserRegistry(storage=db, tools=tools)
try:
    registry.discover()
except Exception:
    pass  # parser/plugins 可能不存在, 不影响启动

# 确保所有 parser 业务表已创建（幂等）
try:
    created = registry.ensure_all_tables()
    if created > 0:
        logger.info(f"已创建 {created} 个业务表")
except Exception as e:
    logger.warning(f"创建业务表失败: {e}")

# 初始化最小爬虫核心，供 API 使用
from core.state_machine import StateMachine
from core.request_pool import RequestPool
from core.browser import CrawlerBrowser
from core.scheduler import Scheduler

state_machine = StateMachine(db, config_mgr)

# 创建专用 event loop + browser 供 RequestPool 使用
_event_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_event_loop)

browser = CrawlerBrowser(config_mgr, headless=True)
try:
    _event_loop.run_until_complete(browser.start())
    logger.info("浏览器已启动 (headless=True)")
except Exception as e:
    logger.error(f"浏览器启动失败（后端 API 仍可用，但 browser 模式不可用）: {e}")
    browser = None

request_pool = RequestPool(
    storage=db,
    config=config_mgr,
    state_machine=state_machine,
    browser=browser,
    loop=_event_loop,
)
scheduler = Scheduler(
    storage=db,
    config=config_mgr,
    state_machine=state_machine,
    registry=registry,
    request_pool=request_pool,
)

app.config["CRAWLER_COMPONENTS"] = {
    "storage": db,
    "config": config_mgr,
    "registry": registry,
    "scheduler": scheduler,
}

# 注入 Scheduler 引用给爬虫控制 API
from web.api.crawler_control import init_scheduler
init_scheduler(scheduler)

# 开发模式：默认暂停状态，等用户从 UI 点击"启动"
scheduler.pause()

def _run_scheduler() -> None:
    """后台运行爬虫调度器主循环。"""
    logger.info("爬虫调度器后台线程启动")
    scheduler.run()

scheduler_thread = threading.Thread(target=_run_scheduler, daemon=True)
scheduler_thread.start()


def _run_flask() -> None:
    logger.info(f"Flask 后端启动: http://{args.web_host}:{args.web_port}")
    socketio.run(app, host=args.web_host, port=args.web_port,
                 debug=False, use_reloader=False, allow_unsafe_werkzeug=True)


flask_thread = threading.Thread(target=_run_flask, daemon=True)
flask_thread.start()
time.sleep(0.5)  # 等 Flask 就绪

# ── 启动前端 ──────────────────────────────────────────────
pnpm = "pnpm.cmd" if sys.platform == "win32" else "pnpm"
fe_dir = os.path.join(os.path.dirname(__file__), "ax-ui-demo")
logger.info(f"Vite 前端启动: http://{args.fe_host}:{args.fe_port}")
fe_proc = subprocess.Popen(
    [pnpm, "dev", "--host", args.fe_host, "--port", str(args.fe_port)],
    cwd=fe_dir,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
)

# ── 等待 + 优雅退出 ──────────────────────────────────────
_shutting_down = False


def _shutdown(sig=None, frame=None) -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    logger.info("正在关闭...")
    scheduler.stop()
    try:
        fe_proc.terminate()
        fe_proc.wait(timeout=5)
    except Exception:
        fe_proc.kill()
    # 清理 browser + event loop
    if browser is not None:
        try:
            _event_loop.run_until_complete(browser.close())
            logger.info("浏览器已关闭")
        except Exception as e:
            logger.warning(f"浏览器关闭异常: {e}")
    logger.info("前后端已关闭。")


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

print(f"""
╔══════════════════════════════════════════════╗
║          58 爬虫 - 开发模式                    ║
║                                              ║
║  前端: http://{args.fe_host}:{args.fe_port:<25}║
║  后端: http://{args.web_host}:{args.web_port:<25}║
║                                              ║
║  访问前端地址即可，已配置代理转发到后端。         ║
║  Ctrl+C 退出。                                 ║
╚══════════════════════════════════════════════╝
""")

try:
    for line in fe_proc.stdout:
        print(f"[vite] {line.rstrip()}")
except KeyboardInterrupt:
    pass
finally:
    _shutdown()
