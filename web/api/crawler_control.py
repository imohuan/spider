"""爬虫控制 API。"""
from __future__ import annotations
from flask import Blueprint, jsonify
from web.app import socketio
from core.logger import get_logger

logger = get_logger("api.crawler_control")

bp = Blueprint('crawler', __name__)
_scheduler = None
_browser = None
_cdp_browser = None

def init_scheduler(scheduler) -> None:
    global _scheduler
    _scheduler = scheduler

def init_browser(browser, cdp_browser=None) -> None:
    """注入浏览器实例，供 stop 端点清理用。"""
    global _browser, _cdp_browser
    _browser = browser
    _cdp_browser = cdp_browser

@bp.route('/status')
def status():
    if _scheduler is None:
        return jsonify({'status': 'stopped'})
    return jsonify({'status': getattr(_scheduler, 'status', 'stopped')})

@bp.route('/start', methods=['POST'])
def start():
    if _scheduler is None:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    _scheduler.start()
    socketio.emit('crawler_status', {'status': 'running'})
    return jsonify({'status': 'running'})

@bp.route('/pause', methods=['POST'])
def pause():
    if _scheduler is None:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    _scheduler.pause()
    socketio.emit('crawler_status', {'status': 'paused'})
    return jsonify({'status': 'paused'})

@bp.route('/stop', methods=['POST'])
def stop():
    if _scheduler is None:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    _scheduler.stop()

    # 立即关闭所有浏览器和 CDP 实例（线程安全）
    if _browser is not None:
        try:
            _browser.close_sync()
            logger.info("浏览器已通过 /api/crawler/stop 关闭")
        except Exception as e:
            logger.warning(f"/api/crawler/stop 关闭浏览器异常: {e}")
    if _cdp_browser is not None:
        try:
            _cdp_browser.disconnect_sync()
            logger.info("CDP 已通过 /api/crawler/stop 断开")
        except Exception as e:
            logger.warning(f"/api/crawler/stop 断开 CDP 异常: {e}")

    socketio.emit('crawler_status', {'status': 'stopped'})
    return jsonify({'status': 'stopped'})
