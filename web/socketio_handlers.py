"""WebSocket 事件处理 — 实时日志推送 + 任务状态。"""
from __future__ import annotations
import logging
from flask_socketio import SocketIO, emit

def register_socketio_handlers(socketio: SocketIO) -> None:
    @socketio.on('connect')
    def on_connect():
        emit('connected', {'message': 'WebSocket connected'})

    @socketio.on('subscribe')
    def on_subscribe(data):
        channel = data.get('channel', 'all')
        emit('subscribed', {'channel': channel})

    @socketio.on('disconnect')
    def on_disconnect():
        pass

class SocketIOLogHandler(logging.Handler):
    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.socketio.emit('log', {
                'level': record.levelname,
                'module': record.name,
                'message': record.getMessage(),
                'timestamp': self.format(record),
            })
        except Exception:
            pass

def push_task_update(socketio: SocketIO, queue_id: int, old_status: str, new_status: str) -> None:
    socketio.emit('task_update', {'queue_id': queue_id, 'old_status': old_status, 'new_status': new_status})

def push_metrics_update(socketio: SocketIO, metrics: dict) -> None:
    socketio.emit('metrics_update', metrics)


def push_workflow_task_update(
    socketio: SocketIO,
    task_id: int,
    workflow_name: str,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """推送工作流任务状态变更。"""
    from datetime import datetime, timezone
    payload = {
        "task_id": task_id,
        "workflow_name": workflow_name,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if result is not None:
        payload["result"] = result
    if error is not None:
        payload["error"] = error
    socketio.emit("workflow_task_update", payload)
