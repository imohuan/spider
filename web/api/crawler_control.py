"""爬虫控制 API — start / pause / stop 生命周期管理。

设计原则
--------
- start  : 幂等。若线程已在跑则只清除 paused 标志；否则（包括首次启动和 stop 之后）
           重建 browser + RequestPool + Scheduler，再启动主循环线程。
- pause  : 仅设置 _paused_event，主循环自旋等待，不销毁任何资源。
- stop   : 立即返回 stopping；后台线程异步完成 scheduler.stop() + browser 关闭 + 组件重置。
- status : 融合 scheduler 标志位 + 线程存活状态，返回真实状态。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from flask import Blueprint, jsonify, current_app
from web.app import socketio
from core.logger import get_logger

logger = get_logger("api.crawler_control")

bp = Blueprint("crawler", __name__)

# ── 注入的组件（由 dev.py / main.py 调用 init_* 设置）──────────────────
_scheduler = None          # Scheduler 实例
_components: dict[str, Any] = {}  # 完整组件字典（用于 start 时重建）

# ── 运行时状态 ────────────────────────────────────────────────────────────
_scheduler_thread: threading.Thread | None = None
_stopping = False   # 正在执行 stop 流程（用于 status 上报）


# ═══════════════════════════════════════════════════════════════════
# 注入接口（由入口文件调用）
# ═══════════════════════════════════════════════════════════════════

def init_scheduler(scheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def init_components(components: dict) -> None:
    """注入完整组件字典，供 start 重建爬虫时使用。"""
    global _components
    _components = components


# ═══════════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════════

def _run_scheduler() -> None:
    """主循环线程入口。"""
    global _stopping
    logger.info("爬虫主循环线程启动")
    try:
        _scheduler.run()
    except Exception as e:
        logger.error(f"调度器主循环异常退出: {e}", exc_info=True)
    finally:
        _stopping = False
        socketio.emit("crawler_status", {"status": "stopped"})
        logger.info("爬虫主循环线程退出")


def _rebuild_crawler() -> bool:
    """重建 browser / request_pool / scheduler，供 /start 在 stop 之后调用。

    :returns: True 表示重建成功，False 表示缺少必要组件。
    """
    global _scheduler

    db = _components.get("storage")
    config_mgr = _components.get("config")
    state_machine = _components.get("state_machine")
    registry = _components.get("registry")

    if not all([db, config_mgr, state_machine, registry]):
        logger.error("重建爬虫失败：缺少必要组件（storage/config/state_machine/registry）")
        return False

    # 1. 新建事件循环（旧循环已关闭）
    from core.bootstrap import create_event_loop
    loop = create_event_loop()
    _components["event_loop"] = loop

    # 2. 启动浏览器
    from core.browser import CrawlerBrowser
    headless = _components.get("_headless", True)
    channel = _components.get("_channel", None)
    browser = CrawlerBrowser(config_mgr, headless=headless, channel=channel)
    try:
        loop.run_until_complete(browser.start())
        logger.info("浏览器重建成功")
    except Exception as e:
        logger.error(f"浏览器重建失败（http 模式仍可用）: {e}")
        browser = None
    _components["browser"] = browser

    # 3. 重建 RequestPool
    from core.request_pool import RequestPool
    request_pool = RequestPool(
        storage=db,
        config=config_mgr,
        state_machine=state_machine,
        browser=browser,
        loop=loop,
    )
    _components["request_pool"] = request_pool

    # 4. 重建 Scheduler
    from core.scheduler import Scheduler
    scheduler = Scheduler(
        storage=db,
        config=config_mgr,
        state_machine=state_machine,
        registry=registry,
        request_pool=request_pool,
    )
    _components["scheduler"] = scheduler
    _scheduler = scheduler

    logger.info("爬虫组件重建完成")
    return True


def _do_stop() -> None:
    """后台线程：优雅停止调度器 + 关闭浏览器 + 重置状态。"""
    global _stopping

    # 1. 通知调度器退出主循环
    if _scheduler is not None:
        _scheduler.stop()

    # 2. 等待主循环线程退出（最多 10s）
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=10)
        if _scheduler_thread.is_alive():
            logger.warning("调度线程 10s 内未退出，强制继续")

    # 3. 关闭浏览器
    browser = _components.get("browser")
    loop = _components.get("event_loop")
    if browser is not None:
        try:
            browser.close_sync()
            logger.info("浏览器已关闭")
        except Exception as e:
            logger.warning(f"关闭浏览器异常: {e}")
        _components["browser"] = None

    # 4. 关闭旧事件循环
    if loop is not None and not loop.is_closed():
        try:
            from core.bootstrap import cancel_all_tasks
            cancel_all_tasks(loop, logger)
            loop.close()
        except Exception as e:
            logger.warning(f"关闭事件循环异常: {e}")
        _components["event_loop"] = None

    _stopping = False
    socketio.emit("crawler_status", {"status": "stopped"})
    logger.info("爬虫已完全停止，可重新 start")


# ═══════════════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════════════

@bp.route("/status")
def status():
    global _stopping
    if _stopping:
        return jsonify({"status": "stopping"})
    if _scheduler is None:
        return jsonify({"status": "stopped"})
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        sched_status = getattr(_scheduler, "status", "running")
        return jsonify({"status": sched_status})
    # 线程不在跑 → 真实 stopped
    return jsonify({"status": "stopped"})


@bp.route("/start", methods=["POST"])
def start():
    global _scheduler, _scheduler_thread, _stopping

    if _stopping:
        return jsonify({"error": "正在停止中，请稍后再试"}), 409

    # 线程还活着 → 只需清除 paused/shutdown 标志即可
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        if _scheduler is not None:
            _scheduler.start()
        logger.info("爬虫主循环已在运行，已恢复调度")
        socketio.emit("crawler_status", {"status": "running"})
        return jsonify({"status": "running"})

    # 线程不存在或已结束 → 需要重建组件再启动
    if _scheduler is None:
        return jsonify({"error": "Scheduler 未初始化，缺少组件"}), 500

    # 如果之前 stop 过，_scheduler 已是旧实例，尝试重建
    if _scheduler._shutdown_event.is_set():
        ok = _rebuild_crawler()
        if not ok:
            return jsonify({"error": "组件重建失败，请检查日志"}), 500

    _scheduler.start()
    _scheduler_thread = threading.Thread(target=_run_scheduler, daemon=True, name="crawler-main")
    _scheduler_thread.start()
    logger.info("爬虫主循环线程已启动")
    socketio.emit("crawler_status", {"status": "running"})
    return jsonify({"status": "running"})


@bp.route("/pause", methods=["POST"])
def pause():
    if _scheduler is None:
        return jsonify({"error": "Scheduler not initialized"}), 500
    _scheduler.pause()
    socketio.emit("crawler_status", {"status": "paused"})
    return jsonify({"status": "paused"})


@bp.route("/stop", methods=["POST"])
def stop():
    global _stopping

    if _scheduler is None:
        return jsonify({"error": "Scheduler not initialized"}), 500

    if _stopping:
        return jsonify({"status": "stopping"})

    _stopping = True
    socketio.emit("crawler_status", {"status": "stopping"})

    # 后台异步完成清理，不阻塞请求
    t = threading.Thread(target=_do_stop, daemon=True, name="crawler-stopper")
    t.start()

    return jsonify({"status": "stopping"})
