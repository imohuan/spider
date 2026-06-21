"""爬虫控制 API。"""
from __future__ import annotations
from flask import Blueprint, jsonify
from web.app import socketio

bp = Blueprint('crawler', __name__)
_scheduler = None

def init_scheduler(scheduler) -> None:
    global _scheduler
    _scheduler = scheduler

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
    socketio.emit('crawler_status', {'status': 'stopped'})
    return jsonify({'status': 'stopped'})
