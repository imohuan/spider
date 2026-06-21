"""Flask 应用工厂 — 创建 app + SocketIO 实例。

用法::

    # 开发模式（前后端分离，不提供静态文件）
    from web.app import create_app, socketio
    app = create_app()

    # 生产模式（打包为 EXE，提供前端静态文件）
    app = create_app(static_folder='/path/to/web/static')

    socketio.run(app, host='127.0.0.1', port=5000)
"""
from __future__ import annotations

import logging
import os
import time
import traceback
from pathlib import Path
from flask import Flask, send_from_directory, request, g, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS

from core.logger import get_logger

logger = get_logger("web")

socketio = SocketIO(async_mode='threading', cors_allowed_origins='*')


# ── Monkey-patch SimpleWebSocketWSGI 解决 werkzeug AssertionError ──
# 背景: werkzeug 3.x 的 WSGIRequestHandler.execute() 在 WSGI app 返回后,
# 如果 start_response 从未被调用, 会 assert crash: "write() before start_response".
# SimpleWebSocketWSGI 直接操作裸 socket 完成 WebSocket 握手, 不调用 start_response.
# 修复: 在 WebSocket 服务器创建前 preemptively 调用 start_response('101 ...'),
# 满足 werkzeug 的 WSGI 契约. 后续 write(b"") 尝试写 HTTP 头到已关闭的 socket 会
# 被 werkzeug 的 except Exception: pass 静默吞掉.
def _patch_simple_websocket_wsgi():
    """Monkey-patch SimpleWebSocketWSGI.__call__ to satisfy werkzeug.

    背景: werkzeug 3.x 的 execute() 在 WSGI app 返回后, 若 start_response 从未被调用,
    会触发 ``AssertionError: write() before start_response``。
    SimpleWebSocketWSGI 绕过了 WSGI 层直接在 raw socket 上完成 WebSocket 握手,
    因此 start_response 永远不会被调用 —— 导致每次 WebSocket 连接断开时
    werkzeug 必定 crash。
    """
    try:
        import simple_websocket  # noqa: F401
        from engineio.async_drivers._websocket_wsgi import SimpleWebSocketWSGI
    except ImportError:
        return  # simple-websocket 未安装, 不需要 patch

    _original_call = SimpleWebSocketWSGI.__call__

    def _patched_call(self, environ, start_response):
        # 在 WebSocket 握手 (simple_websocket.Server.__init__) 之前
        # preemptively 调用 start_response, 让 werkzeug 知道响应已开始.
        # 101 Switching Protocols 是 WebSocket 升级的标准 HTTP 状态码.
        if 'werkzeug.socket' in environ:
            try:
                start_response('101 Switching Protocols', [])
            except Exception:
                pass  # 如果某些路径已经调用过 start_response

        self.ws = simple_websocket.Server(
            environ, **getattr(self, 'server_args', {}))
        ret = self.app(self)
        if self.ws and self.ws.mode == 'gunicorn':
            raise StopIteration()
        return ret

    SimpleWebSocketWSGI.__call__ = _patched_call
    logger.info("SimpleWebSocketWSGI.__call__ patched for werkzeug compatibility")


_patch_simple_websocket_wsgi()

# 项目根目录（web/ 的上一级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(config_name: str = 'dev', static_folder: str | None = None) -> Flask:
    """创建 Flask 应用。

    :param config_name: 配置名 ('dev' | 'prod')
    :param static_folder: 前端静态文件目录路径。
        - ``None``: 不提供静态文件（开发模式，前端 Vite dev server 独立运行）
        - 传入路径: 提供前端 SPA（打包模式，EXE 内嵌前端）
          支持相对路径（基于项目根目录解析）和绝对路径。
    """
    # 相对路径基于项目根目录解析，避免 Flask root_path 导致的双层拼接
    if static_folder and not os.path.isabs(static_folder):
        static_folder = str(_PROJECT_ROOT / static_folder)

    app = Flask(
        __name__,
        static_folder=static_folder,
        static_url_path='' if static_folder else None,
    )
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', '58-crawler-dev')

    if config_name == 'dev':
        CORS(app, resources={r'/api/*': {'origins': '*'}, r'/socket.io/*': {'origins': '*'}})

    # 提供前端 SPA（hash 路由，只需返回 index.html）
    if static_folder:
        @app.route('/')
        def serve_index():
            return send_from_directory(static_folder, 'index.html')

        @app.route('/<path:path>')
        def serve_static(path: str):
            """兜底静态文件（JS/CSS/图片等）。"""
            from flask import abort
            try:
                return send_from_directory(static_folder, path)
            except Exception:
                # SPA fallback: 未知路径返回 index.html
                # 前端使用 Hash History，通常不会触发此分支
                return send_from_directory(static_folder, 'index.html')

    # 注册蓝图（后续 Task 补充实际蓝图，这里留 import 占位）
    from web.api import register_blueprints
    register_blueprints(app)

    # 注册 WebSocket handler
    from web.socketio_handlers import register_socketio_handlers, SocketIOLogHandler
    register_socketio_handlers(socketio)

    # 将 WebSocket 日志 handler 挂到爬虫根 logger，实时推送日志到前端
    ws_handler = SocketIOLogHandler(socketio)
    ws_handler.setLevel(logging.DEBUG)
    ws_handler.setFormatter(logging.Formatter("%(asctime)s", "%Y-%m-%d %H:%M:%S"))
    logging.getLogger("crawler").addHandler(ws_handler)

    # ---------------- 全局日志 & 错误处理 ----------------

    @app.before_request
    def _log_request_start():
        """记录每个请求的开始时间。"""
        g._request_start = time.perf_counter()

    @app.after_request
    def _log_request_end(response):
        """记录每个请求的完成情况（方法、路径、状态码、耗时）。"""
        elapsed = time.perf_counter() - g.pop("_request_start", 0)
        method = request.method
        path = request.path
        status = response.status_code
        content_length = response.content_length or 0

        if status >= 500:
            logger.error(
                f"{method} {path} → {status} {elapsed:.0f}ms {content_length}B"
            )
        elif status >= 400:
            logger.warning(
                f"{method} {path} → {status} {elapsed:.0f}ms {content_length}B"
            )
        else:
            logger.info(
                f"{method} {path} → {status} {elapsed:.0f}ms {content_length}B"
            )
        return response

    @app.errorhandler(500)
    def _handle_500(error):
        """全局 500 错误 — 打印完整堆栈到日志。"""
        logger.error(
            f"Unhandled 500 on {request.method} {request.path}:\n"
            f"{traceback.format_exc()}"
        )
        return jsonify({
            "error": "Internal server error",
            "detail": str(error),
        }), 500

    @app.errorhandler(Exception)
    def _handle_unhandled(error):
        """兜底 — 捕获所有未注册 errorhandler 的异常。"""
        logger.error(
            f"Unhandled exception on {request.method} {request.path}: "
            f"{type(error).__name__}: {error}\n"
            f"{traceback.format_exc()}"
        )
        status_code = getattr(error, "code", 500)
        return jsonify({
            "error": str(error),
            "type": type(error).__name__,
        }), status_code

    socketio.init_app(app)
    return app
