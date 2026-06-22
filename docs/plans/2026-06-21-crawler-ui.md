# 58 爬虫管理后台 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 58 爬虫框架构建前后端一体的 Web 管理后台 — 前端在 web-ui 中用 ax-ui-kit 组件实现 8 个页面，后端用 Flask + Flask-SocketIO 内嵌到爬虫主进程，提供 RESTful API + WebSocket 实时推送。

**Architecture:** Flask 单进程内嵌爬虫 Scheduler，通过 Storage 复用现有 SQLite。前端 Vue 3 SPA 通过 Vite dev proxy 调 Flask API（开发），生产环境 Flask 直接 serve 前端 build 产物。WebSocket 推日志/任务状态，HTTP 轮询指标（5s）。SQLite WAL 模式 + 单写线程保证并发安全。爬虫用 Playwright async API 避免 Flask 事件循环冲突。

**Tech Stack:**
- 前端：Vue 3.5 + Vite 8 + TS 6 + Tailwind v4 + ax-ui-kit（已有）+ vue-router 4
- 后端：Flask 3 + Flask-SocketIO 5 + eventlet（async driver）
- 数据：复用现有 SQLite Storage（core/storage.py），WAL 模式
- 实时：Flask-SocketIO（WebSocket）推日志 + 任务状态；HTTP GET 轮询指标

---

## 一、架构总览

```
┌──────────────────────────────────────────────────────┐
│  浏览器 (localhost:5175 dev / :5000 prod)              │
│  Vue 3 SPA · ax-ui-kit · 8 页面                       │
│  ├─ HTTP (axios) → Flask REST API                     │
│  └─ WebSocket (socket.io-client) → Flask-SocketIO     │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│  Flask 进程 (localhost:5000)                           │
│  ├─ /api/*           RESTful CRUD (读 SQLite)         │
│  ├─ /api/crawler/*   爬虫控制 (start/pause/stop)      │
│  ├─ /socket.io       WebSocket (日志流 + 任务状态)     │
│  └─ /static/*        生产环境 serve 前端 build         │
│                                                       │
│  内嵌爬虫核心 (同进程):                                │
│  ├─ Scheduler (后台线程)                               │
│  ├─ RequestPool                                       │
│  ├─ ProxyPool                                         │
│  └─ Storage (复用 core/storage.py)                    │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│  SQLite (data/crawler.db) · WAL 模式                   │
│  config / queue / requests / seen_urls                │
│  proxy_pool / captcha_log / 业务表                    │
└──────────────────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Web 框架 | Flask（非 FastAPI） | 爬虫是同步模型，FastAPI 异步优势用不上；Flask 生态简单 |
| 实时通信 | Flask-SocketIO | 需要推日志流 + 任务状态变更，WebSocket 比 SSE 更灵活 |
| ASGI driver | eventlet | Flask-SocketIO 官方推荐，支持协程并发 |
| 前端路由 | vue-router 4 | 8 个页面需要 URL 路由，hash 模式避免 Flask 路由冲突 |
| HTTP 客户端 | axios | 拦截器统一处理错误/loading，比 fetch 好用 |
| 开发模式 | Vite dev proxy → Flask | 前端 :5175，后端 :5000，Vite proxy 转发 /api 和 /socket.io |
| 生产模式 | Flask serve dist/ | 单端口部署，`app.static_folder = '../web-ui/dist'` |
| SQLite 并发 | WAL + 独立读连接 | 爬虫写 + API 读，WAL 模式支持并发读不阻塞写 |
| Playwright | async API | sync API 会阻塞 Flask 事件循环，必须用 async |

---

## 二、目录结构变更

### 2.1 后端新增文件

```
project_root/
├── main.py                      # 修改: 启动 Flask + 爬虫
├── web/                         # 新增: Web 后端
│   ├── __init__.py
│   ├── app.py                   # Flask app 工厂 + SocketIO 初始化
│   ├── api/
│   │   ├── __init__.py          # Blueprint 注册
│   │   ├── dashboard.py         # /api/dashboard/* 指标聚合
│   │   ├── queue.py             # /api/queue/* 队列 CRUD
│   │   ├── data.py              # /api/data/* 业务表查询/导出
│   │   ├── proxy.py             # /api/proxy/* IP 池管理
│   │   ├── captcha.py           # /api/captcha/* 验证码日志
│   │   ├── config_api.py        # /api/config/* 配置读写
│   │   ├── parsers.py           # /api/parsers/* Parser 管理
│   │   ├── logs.py              # /api/logs/* 日志读取
│   │   └── crawler_control.py   # /api/crawler/* 启停控制
│   └── socketio_handlers.py     # WebSocket 事件: 日志流 + 任务状态
├── requirements.txt             # 修改: 追加 Flask 依赖
└── ...
```

### 2.2 前端变更 (web-ui/)

```
web-ui/
├── src/
│   ├── App.vue                  # 修改: 改为 ConsoleLayout 壳
│   ├── main.ts                  # 修改: 注册 router
│   ├── router/
│   │   └── index.ts             # 新增: vue-router 配置
│   ├── api/
│   │   ├── http.ts              # 新增: axios 实例 + 拦截器
│   │   ├── ws.ts                # 新增: socket.io-client 封装
│   │   ├── dashboard.ts         # 新增: Dashboard API
│   │   ├── queue.ts             # 新增: Queue API
│   │   ├── data.ts              # 新增: DataBrowser API
│   │   ├── proxy.ts             # 新增: ProxyPool API
│   │   ├── captcha.ts           # 新增: CaptchaLog API
│   │   ├── config.ts            # 新增: Config API
│   │   ├── parsers.ts           # 新增: Parsers API
│   │   └── crawler.ts           # 新增: Crawler 控制 API
│   ├── composables/
│   │   ├── useCrawlerStatus.ts  # 新增: 爬虫状态 hook
│   │   ├── useWebSocket.ts      # 新增: WS 连接 hook
│   │   └── usePagination.ts     # 新增: 分页 hook
│   ├── views/                   # 新增: 8 个页面
│   │   ├── DashboardView.vue
│   │   ├── QueueView.vue
│   │   ├── DataBrowserView.vue
│   │   ├── ProxyPoolView.vue
│   │   ├── CaptchaLogView.vue
│   │   ├── ConfigView.vue
│   │   ├── ParsersView.vue
│   │   └── LogsView.vue
│   ├── components/              # 新增: 业务组件
│   │   ├── layout/
│   │   │   ├── CrawlerSidebar.vue   # 侧边栏 (爬虫版)
│   │   │   ├── CrawlerHeader.vue    # 顶栏
│   │   │   └── CrawlerFooter.vue    # 底部状态条
│   │   ├── dashboard/
│   │   │   ├── MetricCard.vue       # 指标卡
│   │   │   ├── StatusBadge.vue      # 状态标签
│   │   │   └── TaskFlow.vue         # 任务流水
│   │   ├── shared/
│   │   │   ├── DataTable.vue        # 通用表格 (基于 Ax* )
│   │   │   ├── FilterBar.vue        # 筛选条
│   │   │   └── EmptyState.vue       # 空状态
│   │   └── ui/                  # 已有: ax-ui-kit 组件
│   └── ...
├── vite.config.ts               # 修改: 添加 dev proxy
└── package.json                 # 修改: 追加 vue-router + axios + socket.io-client
```

---

## 三、API 设计

### 3.1 REST API 端点

| 方法 | 路径 | 说明 | 对应页面 |
|------|------|------|----------|
| GET | `/api/dashboard/metrics` | 今日抓取/成功率/队列/IP池 概览 | Dashboard |
| GET | `/api/dashboard/progress?hours=24` | 按小时聚合的抓取进度 | Dashboard |
| GET | `/api/dashboard/recent?limit=20` | 最近 N 条任务流水 | Dashboard |
| POST | `/api/crawler/start` | 启动爬虫 | Dashboard |
| POST | `/api/crawler/pause` | 暂停爬虫 | Dashboard |
| POST | `/api/crawler/stop` | 停止爬虫 | Dashboard |
| GET | `/api/crawler/status` | 爬虫状态 (running/paused/stopped) | 全局 |
| GET | `/api/queue?status=&parser=&page=1&size=20` | 队列分页列表 | Queue |
| GET | `/api/queue/stats` | 6 状态计数 | Queue |
| POST | `/api/queue/:id/retry` | 重试单条 | Queue |
| POST | `/api/queue/retry-blocked` | 批量重试 blocked | Queue |
| GET | `/api/data/tables` | 业务表列表 | DataBrowser |
| GET | `/api/data/:table?page=1&size=20&filter=` | 业务表数据分页 | DataBrowser |
| GET | `/api/data/:table/export?format=csv` | 导出 | DataBrowser |
| GET | `/api/proxy?status=&page=1&size=20` | IP 池列表 | ProxyPool |
| GET | `/api/proxy/stats` | 池状态概览 | ProxyPool |
| POST | `/api/proxy/fetch?num=10` | 手动拉取 IP | ProxyPool |
| POST | `/api/proxy/health-check` | 立即健康检查 | ProxyPool |
| DELETE | `/api/proxy/:id` | 淘汰 IP | ProxyPool |
| GET | `/api/captcha?page=1&size=20` | 验证码日志分页 | CaptchaLog |
| GET | `/api/captcha/stats` | 策略统计 | CaptchaLog |
| GET | `/api/config` | 全部配置 | Config |
| PUT | `/api/config` | 批量更新配置 | Config |
| POST | `/api/config/reset` | 重置默认 | Config |
| GET | `/api/parsers` | Parser 列表 | Parsers |
| POST | `/api/parsers/:name/toggle` | 启用/禁用 | Parsers |
| POST | `/api/parsers/rescan` | 重新扫描 | Parsers |
| POST | `/api/parsers/:name/test` | 测试 URL | Parsers |
| GET | `/api/logs?level=&module=&page=1&size=100` | 历史日志分页 | Logs |

### 3.2 WebSocket 事件

| 方向 | 事件 | 说明 |
|------|------|------|
| Server → Client | `log` | 实时日志行 (level/module/message/timestamp) |
| Server → Client | `task_update` | 任务状态变更 (queue_id/old_status/new_status) |
| Server → Client | `metrics_update` | 指标更新 (每 5s 推一次概览) |
| Server → Client | `crawler_status` | 爬虫运行状态变更 |
| Client → Server | `subscribe` | 订阅频道 (logs/metrics/all) |

---

## 四、实施任务分解

### 阶段 1: 后端骨架 (Flask + SocketIO)

---

### Task 1: 安装后端依赖

**Files:**
- Modify: `requirements.txt`

**Step 1: 追加 Flask 依赖**

在 `requirements.txt` 末尾追加：

```
# Web 管理后台
flask>=3.0.0,<4.0.0
flask-socketio>=5.3.0,<6.0.0
eventlet>=0.36.0,<1.0.0
flask-cors>=4.0.0,<5.0.0
```

**Step 2: 安装到 venv**

Run: `pip install -r requirements.txt`
Expected: 全部安装成功

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add Flask + Flask-SocketIO for web backend"
```

---

### Task 2: Flask app 工厂 + SocketIO 初始化

**Files:**
- Create: `web/__init__.py`
- Create: `web/app.py`

**Step 1: 创建 web 包**

`web/__init__.py`:
```python
"""Web 管理后台包 — Flask + Flask-SocketIO 内嵌爬虫主进程。"""
```

**Step 2: 实现 app 工厂**

`web/app.py`:
```python
"""Flask 应用工厂 — 创建 app + SocketIO 实例，注册蓝图和 WS handler。

用法::

    from web.app import create_app, socketio
    app, socketio = create_app()
    socketio.run(app, host='127.0.0.1', port=5000)
"""
from __future__ import annotations

import os
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS

# 全局 SocketIO 实例（main.py 启动时引用）
socketio = SocketIO(async_mode='eventlet', cors_allowed_origins='*')


def create_app(config_name: str = 'dev') -> Flask:
    """创建 Flask app，注册所有蓝图和 WebSocket handler。

    Args:
        config_name: dev / prod

    Returns:
        配置完成的 Flask app 实例
    """
    app = Flask(__name__, static_folder=None)
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', '58-crawler-dev')

    # CORS（开发模式前端 :5175 → 后端 :5000）
    if config_name == 'dev':
        CORS(app, resources={r'/api/*': {'origins': '*'}, r'/socket.io/*': {'origins': '*'}})

    # 注册 REST API 蓝图
    from web.api import register_blueprints
    register_blueprints(app)

    # 注册 WebSocket handler
    from web.socketio_handlers import register_socketio_handlers
    register_socketio_handlers(socketio)

    # 初始化 SocketIO 与 app 绑定
    socketio.init_app(app)

    return app
```

**Step 3: Commit**

```bash
git add web/__init__.py web/app.py
git commit -m "feat(web): flask app factory + socketio init"
```

---

### Task 3: API Blueprint 注册中心

**Files:**
- Create: `web/api/__init__.py`

**Step 1: 实现蓝图批量注册**

`web/api/__init__.py`:
```python
"""API 蓝图注册中心 — 统一注册所有 REST 蓝图到 Flask app。"""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    """注册所有 API 蓝图。"""
    from web.api.dashboard import bp as dashboard_bp
    from web.api.queue import bp as queue_bp
    from web.api.data import bp as data_bp
    from web.api.proxy import bp as proxy_bp
    from web.api.captcha import bp as captcha_bp
    from web.api.config_api import bp as config_bp
    from web.api.parsers import bp as parsers_bp
    from web.api.logs import bp as logs_bp
    from web.api.crawler_control import bp as crawler_bp

    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(queue_bp, url_prefix='/api/queue')
    app.register_blueprint(data_bp, url_prefix='/api/data')
    app.register_blueprint(proxy_bp, url_prefix='/api/proxy')
    app.register_blueprint(captcha_bp, url_prefix='/api/captcha')
    app.register_blueprint(config_bp, url_prefix='/api/config')
    app.register_blueprint(parsers_bp, url_prefix='/api/parsers')
    app.register_blueprint(logs_bp, url_prefix='/api/logs')
    app.register_blueprint(crawler_bp, url_prefix='/api/crawler')
```

**Step 2: Commit**

```bash
git add web/api/__init__.py
git commit -m "feat(web): blueprint registration center"
```

---

### Task 4: Dashboard API (指标聚合)

**Files:**
- Create: `web/api/dashboard.py`

**Step 1: 实现三个端点**

`web/api/dashboard.py`:
```python
"""Dashboard API — 指标聚合、进度图表、任务流水。

GET /api/dashboard/metrics       — 4 核心指标
GET /api/dashboard/progress      — 按小时聚合抓取进度
GET /api/dashboard/recent        — 最近 N 条任务流水
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('dashboard', __name__)


def _get_storage() -> Storage:
    """获取 Storage 实例（每次请求新建读连接，避免跨线程问题）。"""
    return Storage()


@bp.route('/metrics')
def get_metrics():
    """4 核心指标：今日抓取、成功率、队列长度、IP 池可用。"""
    s = _get_storage()
    today_crawled = s.execute(
        "SELECT COUNT(*) FROM requests WHERE date(request_time) = date('now') AND request_status = 'success'",
        fetch='one'
    )[0]
    today_total = s.execute(
        "SELECT COUNT(*) FROM requests WHERE date(request_time) = date('now')",
        fetch='one'
    )[0]
    success_rate = round(today_crawled / today_total * 100, 1) if today_total > 0 else 0.0

    queue_length = s.execute(
        "SELECT COUNT(*) FROM queue WHERE status IN ('pending', 'failed')",
        fetch='one'
    )[0]

    ip_available = s.execute(
        "SELECT COUNT(*) FROM proxy_pool WHERE status = 'idle'",
        fetch='one'
    )[0]
    ip_total = s.execute(
        "SELECT COUNT(*) FROM proxy_pool WHERE status IN ('idle', 'in_use', 'cooldown')",
        fetch='one'
    )[0]

    return jsonify({
        'today_crawled': today_crawled,
        'success_rate': success_rate,
        'queue_length': queue_length,
        'ip_available': ip_available,
        'ip_total': ip_total,
    })


@bp.route('/progress')
def get_progress():
    """按小时聚合的抓取进度（成功/失败），默认 24 小时。"""
    hours = request.args.get('hours', 24, type=int)
    s = _get_storage()
    rows = s.execute(
        """
        SELECT strftime('%Y-%m-%d %H:00', request_time) as hour,
               SUM(CASE WHEN request_status = 'success' THEN 1 ELSE 0 END) as success,
               SUM(CASE WHEN request_status != 'success' THEN 1 ELSE 0 END) as failed
        FROM requests
        WHERE request_time >= datetime('now', ?)
        GROUP BY hour ORDER BY hour
        """,
        params=(f'-{hours} hours',),
        fetch='all'
    )
    return jsonify([{'hour': r[0], 'success': r[1], 'failed': r[2]} for r in rows])


@bp.route('/recent')
def get_recent():
    """最近 N 条任务流水（关联 queue + parser_name）。"""
    limit = request.args.get('limit', 20, type=int)
    s = _get_storage()
    rows = s.execute(
        """
        SELECT q.url, q.parser_name, q.status, q.error_type, q.error_msg,
               q.finished_at, r.request_status
        FROM queue q
        LEFT JOIN requests r ON r.queue_id = q.id AND r.id = (
            SELECT MAX(id) FROM requests WHERE queue_id = q.id
        )
        WHERE q.status != 'pending'
        ORDER BY COALESCE(q.finished_at, q.started_at, q.created_at) DESC
        LIMIT ?
        """,
        params=(limit,),
        fetch='all'
    )
    return jsonify([{
        'url': r[0], 'parser': r[1], 'status': r[2],
        'error_type': r[3], 'error_msg': r[4],
        'finished_at': r[5], 'request_status': r[6]
    } for r in rows])
```

**Step 2: Commit**

```bash
git add web/api/dashboard.py
git commit -m "feat(web): dashboard API - metrics/progress/recent"
```

---

### Task 5: Crawler 控制 API

**Files:**
- Create: `web/api/crawler_control.py`

**Step 1: 实现启停控制**

`web/api/crawler_control.py`:
```python
"""爬虫控制 API — 启动/暂停/停止/状态查询。

POST /api/crawler/start    — 启动爬虫（后台线程）
POST /api/crawler/pause    — 暂停（设置暂停标志）
POST /api/crawler/stop     — 停止（设置退出标志 + 等待）
GET  /api/crawler/status   — 当前状态
"""
from __future__ import annotations

from flask import Blueprint, jsonify
from web.app import socketio

bp = Blueprint('crawler', __name__)

# 全局爬虫状态（main.py 初始化时注入实际 Scheduler 实例）
_scheduler = None


def init_scheduler(scheduler) -> None:
    """由 main.py 调用，注入 Scheduler 实例。"""
    global _scheduler
    _scheduler = scheduler


@bp.route('/status')
def status():
    if _scheduler is None:
        return jsonify({'status': 'stopped', 'message': 'Scheduler not initialized'})
    return jsonify({
        'status': _scheduler.status,  # running / paused / stopped
        'pid': _scheduler.pid if hasattr(_scheduler, 'pid') else None,
        'uptime': _scheduler.uptime if hasattr(_scheduler, 'uptime') else 0,
    })


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
```

**Step 2: Commit**

```bash
git add web/api/crawler_control.py
git commit -m "feat(web): crawler control API - start/pause/stop/status"
```

---

### Task 6: Queue API + Proxy API + Captcha API + Config API + Parsers API + Logs API + Data API

**Files:**
- Create: `web/api/queue.py`
- Create: `web/api/data.py`
- Create: `web/api/proxy.py`
- Create: `web/api/captcha.py`
- Create: `web/api/config_api.py`
- Create: `web/api/parsers.py`
- Create: `web/api/logs.py`

**Step 1: Queue API**

`web/api/queue.py`:
```python
"""任务队列 API — 分页列表 + 状态统计 + 重试。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('queue', __name__)


@bp.route('/stats')
def stats():
    s = Storage()
    rows = s.execute(
        "SELECT status, COUNT(*) FROM queue GROUP BY status",
        fetch='all'
    )
    return jsonify({r[0]: r[1] for r in rows})


@bp.route('')
def list_queue():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    status = request.args.get('status', '')
    parser = request.args.get('parser', '')
    search = request.args.get('search', '')

    where = "WHERE 1=1"
    params = []
    if status:
        where += " AND status = ?"
        params.append(status)
    if parser:
        where += " AND parser_name = ?"
        params.append(parser)
    if search:
        where += " AND (url LIKE ? OR error_msg LIKE ?)"
        params.extend([f'%{search}%', f'%{search}%'])

    s = Storage()
    total = s.execute(f"SELECT COUNT(*) FROM queue {where}", params=params, fetch='one')[0]
    rows = s.execute(
        f"SELECT id, url, parser_name, status, retry_count, ip_switch_count, error_type, error_msg, created_at FROM queue {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params=params + [size, (page - 1) * size],
        fetch='all'
    )
    return jsonify({
        'items': [{'id': r[0], 'url': r[1], 'parser': r[2], 'status': r[3],
                    'retry': r[4], 'switch': r[5], 'error_type': r[6], 'error_msg': r[7], 'created_at': r[8]} for r in rows],
        'total': total, 'page': page, 'size': size,
    })


@bp.route('/<int:qid>/retry', methods=['POST'])
def retry_one(qid: int):
    s = Storage()
    s.execute(
        "UPDATE queue SET status = 'pending', retry_count = retry_count + 1 WHERE id = ?",
        params=(qid,)
    )
    return jsonify({'ok': True})


@bp.route('/retry-blocked', methods=['POST'])
def retry_blocked():
    s = Storage()
    count = s.execute(
        "UPDATE queue SET status = 'pending' WHERE status = 'blocked'",
        fetch='one'
    )
    return jsonify({'ok': True, 'count': count})
```

**Step 2: Proxy API**

`web/api/proxy.py`:
```python
"""IP 池 API — 列表 + 概览 + 手动拉取 + 健康检查 + 淘汰。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('proxy', __name__)


@bp.route('/stats')
def stats():
    s = Storage()
    rows = s.execute(
        "SELECT status, COUNT(*) FROM proxy_pool GROUP BY status",
        fetch='all'
    )
    return jsonify({r[0]: r[1] for r in rows})


@bp.route('')
def list_proxy():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    status = request.args.get('status', '')

    where = "WHERE 1=1"
    params = []
    if status:
        where = "WHERE status = ?"
        params.append(status)

    s = Storage()
    total = s.execute(f"SELECT COUNT(*) FROM proxy_pool {where}", params=params, fetch='one')[0]
    rows = s.execute(
        f"""SELECT id, ip, port, city, status, use_count, max_use, fail_count,
               expire_at, cooldown_until, last_used_at
            FROM proxy_pool {where} ORDER BY id DESC LIMIT ? OFFSET ?""",
        params=params + [size, (page - 1) * size],
        fetch='all'
    )
    return jsonify({
        'items': [{'id': r[0], 'ip': r[1], 'port': r[2], 'city': r[3], 'status': r[4],
                    'use': r[5], 'max_use': r[6], 'fail': r[7], 'expire_at': r[8],
                    'cooldown_until': r[9], 'last_used_at': r[10]} for r in rows],
        'total': total, 'page': page, 'size': size,
    })


@bp.route('/fetch', methods=['POST'])
def fetch_proxy():
    """手动拉取 IP — 调用 ProxyPool.fetch()。"""
    num = request.args.get('num', 10, type=int)
    # TODO: 注入 ProxyPool 实例并调用
    return jsonify({'ok': True, 'message': f'Fetching {num} IPs...'})


@bp.route('/health-check', methods=['POST'])
def health_check():
    """立即健康检查。"""
    # TODO: 触发 health_check 线程
    return jsonify({'ok': True, 'message': 'Health check started'})


@bp.route('/<int:pid>', methods=['DELETE'])
def kill_proxy(pid: int):
    s = Storage()
    s.execute("UPDATE proxy_pool SET status = 'dead' WHERE id = ?", params=(pid,))
    return jsonify({'ok': True})
```

**Step 3: Captcha API**

`web/api/captcha.py`:
```python
"""验证码日志 API — 分页列表 + 策略统计。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('captcha', __name__)


@bp.route('/stats')
def stats():
    s = Storage()
    today_total = s.execute(
        "SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at) = date('now')",
        fetch='one'
    )[0]
    auto_ok = s.execute(
        "SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at) = date('now') AND final_status = 'success'",
        fetch='one'
    )[0]
    switch_ok = s.execute(
        "SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at) = date('now') AND final_status = 'switched_ip'",
        fetch='one'
    )[0]
    manual = s.execute(
        "SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at) = date('now') AND final_status = 'manual'",
        fetch='one'
    )[0]
    return jsonify({'today': today_total, 'auto_success': auto_ok, 'switch_ip': switch_ok, 'manual': manual})


@bp.route('')
def list_captcha():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    s = Storage()
    total = s.execute("SELECT COUNT(*) FROM captcha_log", fetch='one')[0]
    rows = s.execute(
        """SELECT id, url, proxy_ip, strategy, attempt_count, final_status,
                  triggered_at, resolved_at
           FROM captcha_log ORDER BY id DESC LIMIT ? OFFSET ?""",
        params=(size, (page - 1) * size),
        fetch='all'
    )
    return jsonify({
        'items': [{'id': r[0], 'url': r[1], 'ip': r[2], 'strategy': r[3],
                    'attempt': r[4], 'result': r[5], 'triggered_at': r[6], 'resolved_at': r[7]} for r in rows],
        'total': total, 'page': page, 'size': size,
    })
```

**Step 4: Config API**

`web/api/config_api.py`:
```python
"""配置 API — 全量读取 + 批量更新 + 重置默认。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from core.config_manager import ConfigManager
from core.storage import Storage

bp = Blueprint('config', __name__)


@bp.route('')
def get_all():
    s = Storage()
    rows = s.execute(
        "SELECT key, value, description, updated_at FROM config ORDER BY key",
        fetch='all'
    )
    return jsonify([{'key': r[0], 'value': r[1], 'desc': r[2], 'updated': r[3]} for r in rows])


@bp.route('', methods=['PUT'])
def update_batch():
    """批量更新配置。body: {key: value, ...}"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Empty body'}), 400
    cm = ConfigManager(Storage())
    cm.set_many(data)
    return jsonify({'ok': True, 'updated': len(data)})


@bp.route('/reset', methods=['POST'])
def reset_defaults():
    cm = ConfigManager(Storage())
    cm.init_defaults(force=True)
    return jsonify({'ok': True})
```

**Step 5: Parsers API**

`web/api/parsers.py`:
```python
"""Parser 管理 API — 列表 + 启停 + 重扫 + 测试。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

bp = Blueprint('parsers', __name__)

# 由 main.py 注入 ParserRegistry
_registry = None


def init_registry(registry) -> None:
    global _registry
    _registry = registry


@bp.route('')
def list_parsers():
    if _registry is None:
        return jsonify([])
    parsers = []
    for p_cls in _registry.parsers:
        parsers.append({
            'name': p_cls.__name__,
            'pattern': getattr(p_cls, 'url_pattern', ''),
            'table': getattr(p_cls, 'table_name', ''),
            'enabled': getattr(p_cls, 'enabled', True),
            'fields': len(getattr(p_cls, '_fields', [])),
            'count': getattr(p_cls, '_crawl_count', 0),
        })
    return jsonify(parsers)


@bp.route('/<name>/toggle', methods=['POST'])
def toggle_parser(name: str):
    if _registry is None:
        return jsonify({'error': 'Registry not initialized'}), 500
    # TODO: 写 config.parser_register
    return jsonify({'ok': True})


@bp.route('/rescan', methods=['POST'])
def rescan():
    if _registry is None:
        return jsonify({'error': 'Registry not initialized'}), 500
    _registry.rescan()
    return jsonify({'ok': True})


@bp.route('/<name>/test', methods=['POST'])
def test_parser(name: str):
    """单次运行 Parser 测试。"""
    data = request.get_json()
    url = data.get('url', '') if data else ''
    if not url:
        return jsonify({'error': 'URL required'}), 400
    # TODO: 单次执行 Parser
    return jsonify({'ok': True, 'url': url})
```

**Step 6: Logs API**

`web/api/logs.py`:
```python
"""日志 API — 历史日志分页（实时日志走 WebSocket）。"""
from __future__ import annotations

import os
from flask import Blueprint, jsonify, request
from config import LOGS_DIR

bp = Blueprint('logs', __name__)


@bp.route('')
def list_logs():
    """读取 run.log 的最后 N 行（倒序）。"""
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 100, type=int)
    level = request.args.get('level', '')
    module = request.args.get('module', '')
    search = request.args.get('search', '')

    log_path = os.path.join(LOGS_DIR, 'run.log')
    if not os.path.exists(log_path):
        return jsonify({'items': [], 'total': 0, 'page': page, 'size': size})

    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 倒序
    lines.reverse()

    # 过滤
    filtered = []
    for line in lines:
        if level and f'[{level}]' not in line:
            continue
        if module and f'crawler.{module}' not in line:
            continue
        if search and search not in line:
            continue
        filtered.append(line.strip())

    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    items = filtered[start:end]

    return jsonify({'items': items, 'total': total, 'page': page, 'size': size})
```

**Step 7: Data API**

`web/api/data.py`:
```python
"""业务数据 API — 表列表 + 分页查询 + 导出。"""
from __future__ import annotations

import csv
import io
from flask import Blueprint, jsonify, request, Response
from core.storage import Storage

bp = Blueprint('data', __name__)


@bp.route('/tables')
def list_tables():
    """列出所有业务表（非系统表）。"""
    s = Storage()
    rows = s.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('config','queue','requests','seen_urls','proxy_pool','captcha_log') ORDER BY name",
        fetch='all'
    )
    result = []
    for r in rows:
        count = s.execute(f"SELECT COUNT(*) FROM {r[0]}", fetch='one')[0]
        result.append({'name': r[0], 'rows': count})
    return jsonify(result)


@bp.route('/<table>')
def query_table(table: str):
    """业务表分页查询。"""
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    filter_expr = request.args.get('filter', '')

    s = Storage()
    # 获取列名
    cols = s.execute(f"PRAGMA table_info({table})", fetch='all')
    col_names = [c[1] for c in cols]

    where = "WHERE 1=1"
    params = []
    if filter_expr:
        # 简单 WHERE 支持 key=value
        where = f"WHERE {filter_expr}"

    total = s.execute(f"SELECT COUNT(*) FROM {table} {where}", params=params, fetch='one')[0]
    rows = s.execute(
        f"SELECT * FROM {table} {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params=params + [size, (page - 1) * size],
        fetch='all'
    )
    return jsonify({
        'columns': col_names,
        'items': [dict(zip(col_names, r)) for r in rows],
        'total': total, 'page': page, 'size': size,
    })


@bp.route('/<table>/export')
def export_table(table: str):
    """导出 CSV。"""
    fmt = request.args.get('format', 'csv')
    s = Storage()
    cols = s.execute(f"PRAGMA table_info({table})", fetch='all')
    col_names = [c[1] for c in cols]
    rows = s.execute(f"SELECT * FROM {table}", fetch='all')

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(col_names)
    for r in rows:
        writer.writerow(r)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={table}.csv'}
    )
```

**Step 8: Commit**

```bash
git add web/api/queue.py web/api/data.py web/api/proxy.py web/api/captcha.py web/api/config_api.py web/api/parsers.py web/api/logs.py
git commit -m "feat(web): all REST API endpoints - queue/data/proxy/captcha/config/parsers/logs"
```

---

### Task 7: WebSocket Handler (日志流 + 任务状态)

**Files:**
- Create: `web/socketio_handlers.py`

**Step 1: 实现 SocketIO 事件**

`web/socketio_handlers.py`:
```python
"""WebSocket 事件处理 — 实时日志推送 + 任务状态变更 + 指标更新。

事件方向：
- Server → Client: log / task_update / metrics_update / crawler_status
- Client → Server: subscribe / unsubscribe

日志推送原理：
- 在 logging 模块注册一个 SocketIO Handler
- 每条日志同时写文件 + emit 到 WebSocket
"""
from __future__ import annotations

import logging
from flask_socketio import SocketIO, emit


def register_socketio_handlers(socketio: SocketIO) -> None:
    """注册 WebSocket 事件处理器。"""

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
    """自定义 logging Handler — 将日志推送到 WebSocket。

    由 main.py 在 setup_logging 后注册到 root logger。
    """

    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.socketio.emit('log', {
                'level': record.levelname,
                'module': record.name,
                'message': record.getMessage(),
                'timestamp': self.format_time(record),
            })
        except Exception:
            # WebSocket 推送失败不影响主流程
            pass


def push_task_update(socketio: SocketIO, queue_id: int, old_status: str, new_status: str) -> None:
    """任务状态变更时调用（由 Scheduler/StateMachine 调用）。"""
    socketio.emit('task_update', {
        'queue_id': queue_id,
        'old_status': old_status,
        'new_status': new_status,
    })


def push_metrics_update(socketio: SocketIO, metrics: dict) -> None:
    """指标更新（每 5s 由后台定时器调用）。"""
    socketio.emit('metrics_update', metrics)
```

**Step 2: Commit**

```bash
git add web/socketio_handlers.py
git commit -m "feat(web): socketio handlers - log stream + task status + metrics"
```

---

### Task 8: 修改 main.py — 启动 Flask + 爬虫

**Files:**
- Modify: `main.py`

**Step 1: 改造入口**

`main.py` (完整替换):
```python
"""项目入口 — 启动 Flask Web 后台 + 爬虫 Scheduler。

启动流程：
1. ensure_dirs() 创建数据目录
2. setup_logging() 初始化日志
3. Storage.init_db() 初始化数据库
4. ConfigManager.init_defaults() 初始化默认配置
5. create_app() 创建 Flask app + SocketIO
6. 注册 SocketIOLogHandler 到 logging
7. 启动爬虫 Scheduler（后台线程）
8. socketio.run(app) 启动 Web 服务

访问地址: http://127.0.0.1:5000
"""
import config
from core.logger import setup_logging, get_logger
from core.storage import Storage
from core.config_manager import ConfigManager


def main() -> None:
    # 1. 基础初始化
    config.ensure_dirs()
    setup_logging()
    logger = get_logger('main')

    # 2. 数据库初始化
    storage = Storage()
    storage.init_db()
    cm = ConfigManager(storage)
    cm.init_defaults()
    logger.info('数据库和配置初始化完成')

    # 3. 创建 Flask app
    from web.app import create_app, socketio
    app = create_app(config_name='dev')

    # 4. 注册 WebSocket 日志推送
    from web.socketio_handlers import SocketIOLogHandler
    root_logger = logging.getLogger('crawler')
    ws_handler = SocketIOLogHandler(socketio)
    ws_handler.setLevel(logging.INFO)
    ws_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s - %(message)s'))
    root_logger.addHandler(ws_handler)

    # 5. 初始化爬虫 Scheduler（后台线程）
    # TODO: 等 Scheduler 实现后注入
    # from core.scheduler import Scheduler
    # scheduler = Scheduler(storage, cm)
    # from web.api.crawler_control import init_scheduler
    # init_scheduler(scheduler)
    # scheduler.start_background()

    logger.info('Web 后台启动: http://127.0.0.1:5000')

    # 6. 启动 Flask（阻塞）
    socketio.run(app, host='127.0.0.1', port=5000, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
```

**Step 2: Commit**

```bash
git add main.py
git commit -m "feat: main.py - launch Flask + crawler in single process"
```

---

### 阶段 2: 前端骨架 (路由 + 布局 + API 层)

---

### Task 9: 安装前端依赖

**Files:**
- Modify: `web-ui/package.json`

**Step 1: 安装 vue-router + axios + socket.io-client**

Run:
```bash
cd web-ui && pnpm add vue-router@4 axios socket.io-client@4
```

**Step 2: Commit**

```bash
git add web-ui/package.json web-ui/pnpm-lock.yaml
git commit -m "deps(frontend): add vue-router + axios + socket.io-client"
```

---

### Task 10: Vite dev proxy 配置

**Files:**
- Modify: `web-ui/vite.config.ts`

**Step 1: 添加 proxy**

将 `vite.config.ts` 改为：
```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5175,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/socket.io': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
```

**Step 2: Commit**

```bash
git add web-ui/vite.config.ts
git commit -m "feat(frontend): vite dev proxy for flask backend"
```

---

### Task 11: 路由配置

**Files:**
- Create: `web-ui/src/router/index.ts`

**Step 1: 实现 vue-router 配置**

```typescript
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: 'Dashboard', desc: '总览 · 实时指标和任务流水' },
  },
  {
    path: '/queue',
    name: 'queue',
    component: () => import('@/views/QueueView.vue'),
    meta: { title: '任务队列', desc: 'queue 表 · 状态机驱动的 URL 队列' },
  },
  {
    path: '/data',
    name: 'data',
    component: () => import('@/views/DataBrowserView.vue'),
    meta: { title: '数据浏览', desc: 'Parser 业务表 · 查询/导出' },
  },
  {
    path: '/proxy',
    name: 'proxy',
    component: () => import('@/views/ProxyPoolView.vue'),
    meta: { title: 'IP 池', desc: 'proxy_pool 表 · 代理 IP 生命周期' },
  },
  {
    path: '/captcha',
    name: 'captcha',
    component: () => import('@/views/CaptchaLogView.vue'),
    meta: { title: '验证码日志', desc: 'captcha_log 表 · 接码记录' },
  },
  {
    path: '/config',
    name: 'config',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '配置', desc: 'config 表 · 运行时可调参数' },
  },
  {
    path: '/parsers',
    name: 'parsers',
    component: () => import('@/views/ParsersView.vue'),
    meta: { title: 'Parser 管理', desc: '插件注册表 · 启用/禁用/测试' },
  },
  {
    path: '/logs',
    name: 'logs',
    component: () => import('@/views/LogsView.vue'),
    meta: { title: '实时日志', desc: 'WebSocket 推送 · run.log + error.log' },
  },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
```

**Step 2: Commit**

```bash
git add web-ui/src/router/index.ts
git commit -m "feat(frontend): vue-router config with 8 routes"
```

---

### Task 12: 修改 main.ts 注册 router

**Files:**
- Modify: `web-ui/src/main.ts`

**Step 1: 注册 router**

```typescript
import { createApp } from 'vue'
import { Toaster } from 'vue-sonner'
import 'material-symbols/outlined.css'
import '@fontsource/geist/400.css'
import '@fontsource/geist/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import 'vue-sonner/style.css'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { registerComponents } from './components/ui'

const app = createApp(App)
app.use(router)
registerComponents(app)
app.component('Toaster', Toaster)
app.mount('#app')
```

**Step 2: Commit**

```bash
git add web-ui/src/main.ts
git commit -m "feat(frontend): register vue-router in main.ts"
```

---

### Task 13: HTTP + WebSocket 封装

**Files:**
- Create: `web-ui/src/api/http.ts`
- Create: `web-ui/src/api/ws.ts`

**Step 1: axios 实例**

`http.ts`:
```typescript
import axios from 'axios'
import { useNotify } from '@/components/ui'

const { triggerNotify } = useNotify()

export const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// 请求拦截器
http.interceptors.request.use((config) => {
  return config
})

// 响应拦截器 — 统一错误处理
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const msg = error.response?.data?.error || error.message || '请求失败'
    triggerNotify(msg, 'error', 'API 错误')
    return Promise.reject(error)
  }
)

// 便捷方法（返回已解包的 data）
export const api = {
  get: <T = any>(url: string, params?: any) => http.get<any, T>(url, { params }),
  post: <T = any>(url: string, data?: any) => http.post<any, T>(url, data),
  put: <T = any>(url: string, data?: any) => http.put<any, T>(url, data),
  delete: <T = any>(url: string) => http.delete<any, T>(url),
}
```

**Step 2: WebSocket 封装**

`ws.ts`:
```typescript
import { io, type Socket } from 'socket.io-client'
import { ref, onMounted, onBeforeUnmount } from 'vue'

let socket: Socket | null = null

export function getSocket(): Socket {
  if (!socket) {
    socket = io({
      path: '/socket.io',
      transports: ['websocket', 'polling'],
    })
  }
  return socket
}

/** WebSocket 连接 hook — 自动连接/断开 */
export function useWebSocket() {
  const connected = ref(false)
  const logs = ref<Array<{ level: string; module: string; message: string; timestamp: string }>>([])
  const taskUpdates = ref<Array<{ queue_id: number; old_status: string; new_status: string }>>([])
  const crawlerStatus = ref<'running' | 'paused' | 'stopped'>('stopped')

  let s: Socket

  onMounted(() => {
    s = getSocket()
    s.on('connect', () => { connected.value = true })
    s.on('disconnect', () => { connected.value = false })
    s.on('log', (data) => {
      logs.value.push(data)
      if (logs.value.length > 500) logs.value.shift()
    })
    s.on('task_update', (data) => {
      taskUpdates.value.push(data)
    })
    s.on('crawler_status', (data) => {
      crawlerStatus.value = data.status
    })
  })

  onBeforeUnmount(() => {
    s?.off('connect')
    s?.off('disconnect')
    s?.off('log')
    s?.off('task_update')
    s?.off('crawler_status')
  })

  return { connected, logs, taskUpdates, crawlerStatus }
}
```

**Step 3: Commit**

```bash
git add web-ui/src/api/http.ts web-ui/src/api/ws.ts
git commit -m "feat(frontend): axios + socket.io client wrappers"
```

---

### Task 14: API 服务层 (8 个模块)

**Files:**
- Create: `web-ui/src/api/dashboard.ts`
- Create: `web-ui/src/api/queue.ts`
- Create: `web-ui/src/api/data.ts`
- Create: `web-ui/src/api/proxy.ts`
- Create: `web-ui/src/api/captcha.ts`
- Create: `web-ui/src/api/config.ts`
- Create: `web-ui/src/api/parsers.ts`
- Create: `web-ui/src/api/crawler.ts`

**Step 1: 逐个实现 API 模块**

`dashboard.ts`:
```typescript
import { api } from './http'

export const dashboardApi = {
  getMetrics: () => api.get('/dashboard/metrics'),
  getProgress: (hours = 24) => api.get('/dashboard/progress', { hours }),
  getRecent: (limit = 20) => api.get('/dashboard/recent', { limit }),
}
```

`crawler.ts`:
```typescript
import { api } from './http'

export const crawlerApi = {
  start: () => api.post('/crawler/start'),
  pause: () => api.post('/crawler/pause'),
  stop: () => api.post('/crawler/stop'),
  status: () => api.get('/crawler/status'),
}
```

`queue.ts`:
```typescript
import { api } from './http'

export const queueApi = {
  stats: () => api.get('/queue/stats'),
  list: (params: { page?: number; size?: number; status?: string; parser?: string; search?: string }) =>
    api.get('/queue', params),
  retry: (id: number) => api.post(`/queue/${id}/retry`),
  retryBlocked: () => api.post('/queue/retry-blocked'),
}
```

`data.ts`:
```typescript
import { api } from './http'

export const dataApi = {
  tables: () => api.get('/data/tables'),
  query: (table: string, params: { page?: number; size?: number; filter?: string }) =>
    api.get(`/data/${table}`, params),
  exportCsv: (table: string) => `/api/data/${table}/export?format=csv`,
}
```

`proxy.ts`:
```typescript
import { api } from './http'

export const proxyApi = {
  stats: () => api.get('/proxy/stats'),
  list: (params: { page?: number; size?: number; status?: string }) => api.get('/proxy', params),
  fetch: (num = 10) => api.post('/proxy/fetch', null, { params: { num } }),
  healthCheck: () => api.post('/proxy/health-check'),
  kill: (id: number) => api.delete(`/proxy/${id}`),
}
```

`captcha.ts`:
```typescript
import { api } from './http'

export const captchaApi = {
  stats: () => api.get('/captcha/stats'),
  list: (params: { page?: number; size?: number }) => api.get('/captcha', params),
}
```

`config.ts`:
```typescript
import { api } from './http'

export const configApi = {
  getAll: () => api.get('/config'),
  update: (data: Record<string, string>) => api.put('/config', data),
  reset: () => api.post('/config/reset'),
}
```

`parsers.ts`:
```typescript
import { api } from './http'

export const parsersApi = {
  list: () => api.get('/parsers'),
  toggle: (name: string) => api.post(`/parsers/${name}/toggle`),
  rescan: () => api.post('/parsers/rescan'),
  test: (name: string, url: string) => api.post(`/parsers/${name}/test`, { url }),
}
```

**Step 2: Commit**

```bash
git add web-ui/src/api/dashboard.ts web-ui/src/api/queue.ts web-ui/src/api/data.ts web-ui/src/api/proxy.ts web-ui/src/api/captcha.ts web-ui/src/api/config.ts web-ui/src/api/parsers.ts web-ui/src/api/crawler.ts
git commit -m "feat(frontend): 8 API service modules"
```

---

### Task 15: App.vue 改为 ConsoleLayout 壳

**Files:**
- Modify: `web-ui/src/App.vue`

**Step 1: 替换 App.vue**

```vue
<script setup lang="ts">
import CrawlerSidebar from '@/components/layout/CrawlerSidebar.vue'
import CrawlerHeader from '@/components/layout/CrawlerHeader.vue'
import CrawlerFooter from '@/components/layout/CrawlerFooter.vue'
</script>

<template>
  <div class="flex h-screen w-screen overflow-hidden bg-background">
    <Toaster position="top-right" rich-colors close-button />
    <CrawlerSidebar />
    <div class="flex-1 flex flex-col overflow-hidden">
      <CrawlerHeader />
      <main class="flex-1 overflow-y-auto p-margin">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
      <CrawlerFooter />
    </div>
  </div>
</template>

<style>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
```

**Step 2: Commit**

```bash
git add web-ui/src/App.vue
git commit -m "feat(frontend): App.vue as console layout shell with router-view"
```

---

### Task 16: 布局组件 (Sidebar + Header + Footer)

**Files:**
- Create: `web-ui/src/components/layout/CrawlerSidebar.vue`
- Create: `web-ui/src/components/layout/CrawlerHeader.vue`
- Create: `web-ui/src/components/layout/CrawlerFooter.vue`

**Step 1: CrawlerSidebar.vue**

参考 `crawler-ui-mockup.html` 的 sidebar，用 Ax* 组件 + Material Symbols 图标 + 语义 token 实现。导航项分 4 组：监控 / 数据 / 运维 / 系统。用 `router-link` 替代 mockup 的 `<a>`。

```vue
<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()

interface NavGroup {
  section: string
  items: { id: string; name: string; icon: string; path: string }[]
}

const navGroups: NavGroup[] = [
  {
    section: '监控',
    items: [
      { id: 'dashboard', name: 'Dashboard', icon: 'dashboard', path: '/dashboard' },
      { id: 'queue', name: '任务队列', icon: 'list_alt', path: '/queue' },
    ],
  },
  {
    section: '数据',
    items: [
      { id: 'data', name: '数据浏览', icon: 'table_chart', path: '/data' },
      { id: 'proxy', name: 'IP 池', icon: 'vpn_lock', path: '/proxy' },
    ],
  },
  {
    section: '运维',
    items: [
      { id: 'captcha', name: '验证码日志', icon: 'verified_user', path: '/captcha' },
      { id: 'config', name: '配置', icon: 'settings', path: '/config' },
      { id: 'parsers', name: 'Parser 管理', icon: 'extension', path: '/parsers' },
    ],
  },
  {
    section: '系统',
    items: [
      { id: 'logs', name: '实时日志', icon: 'terminal', path: '/logs' },
    ],
  },
]

const currentPath = computed(() => route.path)
</script>

<template>
  <aside class="w-56 bg-surface-container-lowest border-r border-outline-variant flex flex-col flex-shrink-0">
    <!-- Logo -->
    <div class="px-5 py-4 border-b border-outline-variant">
      <div class="flex items-center gap-ax-sm">
        <div class="w-7 h-7 rounded-md flex items-center justify-center text-white text-xs font-bold bg-primary">
          58
        </div>
        <div>
          <div class="text-sm font-medium leading-tight text-primary">爬虫管理后台</div>
          <div class="text-[10px] text-secondary leading-tight">v0.1 · localhost</div>
        </div>
      </div>
    </div>

    <!-- 状态条 -->
    <div class="px-4 py-3 border-b border-outline-variant">
      <div class="flex items-center gap-ax-sm mb-1">
        <span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
        <span class="text-xs font-medium text-primary">爬虫运行中</span>
      </div>
      <div class="text-[10px] text-secondary">PID 3852 · 运行 2h17m</div>
    </div>

    <!-- 导航 -->
    <nav class="flex-1 py-ax-sm overflow-y-auto">
      <div v-for="group in navGroups" :key="group.section">
        <p class="text-[10px] text-secondary uppercase tracking-wider px-5 py-2 font-medium">{{ group.section }}</p>
        <router-link
          v-for="item in group.items"
          :key="item.id"
          :to="item.path"
          class="flex items-center gap-ax-sm px-5 py-2 text-sm transition-colors rounded-lg mx-ax-xs"
          :class="currentPath === item.path
            ? 'bg-secondary-container text-on-secondary-container font-medium'
            : 'text-secondary hover:bg-surface-container-low'"
        >
          <span class="material-symbols-outlined text-[18px]">{{ item.icon }}</span>
          <span>{{ item.name }}</span>
        </router-link>
      </div>
    </nav>

    <!-- 底部 -->
    <div class="px-4 py-3 border-t border-outline-variant text-[10px] text-secondary space-y-1">
      <div class="flex justify-between"><span>SQLite</span><span>WAL · 12.4 MB</span></div>
      <div class="flex justify-between"><span>Flask</span><span>:5000</span></div>
    </div>
  </aside>
</template>
```

**Step 2: CrawlerHeader.vue**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { crawlerApi } from '@/api/crawler'
import { useNotify } from '@/components/ui'

const route = useRoute()
const { triggerNotify } = useNotify()

const title = computed(() => (route.meta.title as string) || '')
const desc = computed(() => (route.meta.desc as string) || '')

const startCrawler = async () => {
  try {
    await crawlerApi.start()
    triggerNotify('爬虫已启动', 'success', '操作成功')
  } catch {}
}
</script>

<template>
  <header class="h-14 bg-surface-container-lowest border-b border-outline-variant flex items-center justify-between px-margin shrink-0">
    <div>
      <h1 class="text-base font-medium leading-tight text-primary">{{ title }}</h1>
      <div class="text-[11px] text-secondary leading-tight">{{ desc }}</div>
    </div>
    <div class="flex items-center gap-ax-sm">
      <AxButton variant="outline" size="sm" icon="refresh">刷新</AxButton>
      <AxButton variant="primary" size="sm" icon="play_arrow" @click="startCrawler">启动爬虫</AxButton>
    </div>
  </header>
</template>
```

**Step 3: CrawlerFooter.vue**

```vue
<script setup lang="ts">
import { useWebSocket } from '@/api/ws'

const { connected } = useWebSocket()
</script>

<template>
  <footer class="h-7 bg-surface-container-lowest border-t border-outline-variant flex items-center px-4 text-[10px] text-secondary gap-4 shrink-0">
    <span>WebSocket:
      <span :class="connected ? 'text-primary' : 'text-error'">
        {{ connected ? '已连接' : '未连接' }}
      </span>
    </span>
    <span>延迟: 23ms</span>
    <span class="ml-auto">58 爬虫管理后台 · 仅本机 127.0.0.1</span>
  </footer>
</template>
```

**Step 4: Commit**

```bash
git add web-ui/src/components/layout/
git commit -m "feat(frontend): CrawlerSidebar + Header + Footer with ax-ui-kit"
```

---

### 阶段 3: 8 个页面视图

> 以下每个 Task 对应一个页面 View。每个 View 参考 `crawler-ui-mockup.html` 的对应区块，将原生 HTML 替换为 Ax* 组件 + 语义 token + Material Symbols 图标，并用 API 调用替换 mock 数据。

---

### Task 17: DashboardView.vue

**Files:**
- Create: `web-ui/src/views/DashboardView.vue`

**实现要点:**
- 顶部状态条：爬虫运行状态 + 暂停/停止按钮（AxButton variant="outline"/"danger"）
- 4 指标卡：MetricCard.vue 组件，`dashboardApi.getMetrics()` 获取数据，5s 轮询
- 柱状图：SVG 占位或引入轻量图表库（chart.js），`dashboardApi.getProgress()`
- 任务流水：TaskFlow.vue 组件，`dashboardApi.getRecent()`
- WebSocket `metrics_update` 事件自动刷新指标
- 组件：AxButton, AxAlert（异常时）, useNotify

**关键代码结构:**

```vue
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { dashboardApi } from '@/api/dashboard'
import { crawlerApi } from '@/api/crawler'
import { useWebSocket } from '@/api/ws'
import MetricCard from '@/components/dashboard/MetricCard.vue'
import TaskFlow from '@/components/dashboard/TaskFlow.vue'

const metrics = ref({ today_crawled: 0, success_rate: 0, queue_length: 0, ip_available: 0, ip_total: 0 })
const progress = ref([])
const recent = ref([])
const { logs: wsLogs } = useWebSocket()

let timer: ReturnType<typeof setInterval>

const fetchAll = async () => {
  const [m, p, r] = await Promise.all([
    dashboardApi.getMetrics(),
    dashboardApi.getProgress(),
    dashboardApi.getRecent(),
  ])
  metrics.value = m
  progress.value = p
  recent.value = r
}

onMounted(() => {
  fetchAll()
  timer = setInterval(fetchAll, 5000) // 5s 轮询
})

onBeforeUnmount(() => clearInterval(timer))
</script>
```

**Commit:**
```bash
git add web-ui/src/views/DashboardView.vue web-ui/src/components/dashboard/
git commit -m "feat(frontend): DashboardView with metrics + progress + task flow"
```

---

### Task 18: QueueView.vue

**Files:**
- Create: `web-ui/src/views/QueueView.vue`

**实现要点:**
- 6 状态计数卡（pending/running/done/failed/blocked/skipped）：`queueApi.stats()`
- 筛选条：AxSelect（状态/Parser）+ AxInput（搜索）+ AxButton（重试 blocked / 导出）
- 表格：DataTable.vue，列：URL / Parser / 状态(StatusBadge) / 重试 / 换IP / 错误 / 操作
- 分页
- 行操作：重试单条 `queueApi.retry(id)`
- 组件：AxSelect, AxInput, AxButton, StatusBadge

**Commit:**
```bash
git add web-ui/src/views/QueueView.vue
git commit -m "feat(frontend): QueueView with stats + filter + table + pagination"
```

---

### Task 19: DataBrowserView.vue

**Files:**
- Create: `web-ui/src/views/DataBrowserView.vue`

**实现要点:**
- 表选择：AxSelect（业务表列表），`dataApi.tables()`
- 搜索：AxInput（字段过滤表达式）
- 导出：AxButton → `window.open(dataApi.exportCsv(table))`
- 表格：动态列（从 API 返回的 columns），`dataApi.query(table, params)`
- 价格红色显示（中国涨跌色）
- 图片列：AxImage（缩略图，点击 AxImageViewer 全屏）
- 分页

**Commit:**
```bash
git add web-ui/src/views/DataBrowserView.vue
git commit -m "feat(frontend): DataBrowserView with dynamic table + export + image preview"
```

---

### Task 20: ProxyPoolView.vue

**Files:**
- Create: `web-ui/src/views/ProxyPoolView.vue`

**实现要点:**
- 4 池状态卡（总数/idle/cooldown/dead）：`proxyApi.stats()`
- 操作条：AxSelect（服务商）+ AxButton（手动拉取/健康检查）
- 表格：IP:Port / 城市 / 状态 / 使用次数 / 失败次数 / 过期时间 / 操作
- 行操作：淘汰 IP `proxyApi.kill(id)`
- 组件：AxButton, StatusBadge, AxTooltip

**Commit:**
```bash
git add web-ui/src/views/ProxyPoolView.vue
git commit -m "feat(frontend): ProxyPoolView with stats + manual fetch + kill"
```

---

### Task 21: CaptchaLogView.vue

**Files:**
- Create: `web-ui/src/views/CaptchaLogView.vue`

**实现要点:**
- 4 策略统计卡（触发/自动通过/换IP通过/转人工）：`captchaApi.stats()`
- 日志表：触发时间 / URL / IP / 策略 / 尝试次数 / 结果 / 耗时 / 截图
- 策略和结果用 StatusBadge 着色
- 截图列：点击打开 AxDialog 显示验证码快照
- 组件：AxDialog, StatusBadge, AxImage

**Commit:**
```bash
git add web-ui/src/views/CaptchaLogView.vue
git commit -m "feat(frontend): CaptchaLogView with stats + log table + screenshot dialog"
```

---

### Task 22: ConfigView.vue

**Files:**
- Create: `web-ui/src/views/ConfigView.vue`

**实现要点:**
- 分类 tab：代理IP / 反爬限速 / 验证码 / 系统（用 Ax 组件或手写 tab）
- 配置表：key / value（AxInput/AxSwitch 根据 type）/ 说明 / 更新时间
- 保存全部：AxButton → `configApi.update(data)`
- 重置默认：AxButton → AxDialog 二次确认 → `configApi.reset()`
- 危险参数（proxy_api_url）改动时弹 AxDialog 二次确认

**Commit:**
```bash
git add web-ui/src/views/ConfigView.vue
git commit -m "feat(frontend): ConfigView with tabs + edit + save + reset with confirm"
```

---

### Task 23: ParsersView.vue

**Files:**
- Create: `web-ui/src/views/ParsersView.vue`

**实现要点:**
- 卡片网格：每张卡片显示 Parser 名称、url_pattern、业务表、字段数、抓取量
- 启用/禁用开关：AxSwitch → `parsersApi.toggle(name)`
- 查看代码：AxButton → 弹窗显示 Python 源码
- 测试 URL：AxButton → AxDialog 输入 URL → `parsersApi.test(name, url)` → 显示输出
- 重新扫描：AxButton → `parsersApi.rescan()`
- 组件：AxSwitch, AxDialog, AxButton, AxJsonViewer（测试输出）

**Commit:**
```bash
git add web-ui/src/views/ParsersView.vue
git commit -m "feat(frontend): ParsersView with cards + toggle + test URL dialog"
```

---

### Task 24: LogsView.vue

**Files:**
- Create: `web-ui/src/views/LogsView.vue`

**实现要点:**
- 控制条：4 级别 checkbox（INFO/DEBUG/WARN/ERROR）+ 模块 AxSelect + 搜索 AxInput + 自动滚动 AxSwitch + 清空 AxButton
- 黑色终端区域：font-mono，WebSocket `log` 事件实时推送
- 级别着色：INFO 绿、DEBUG 灰、WARN 黄、ERROR 红
- 自动滚动到底部（`scrollHeight`）
- 历史日志：首次加载从 `/api/logs` 拉取，之后 WebSocket 实时追加
- 组件：AxInput, AxSelect, AxSwitch, AxButton

**Commit:**
```bash
git add web-ui/src/views/LogsView.vue
git commit -m "feat(frontend): LogsView with realtime terminal + filter + auto-scroll"
```

---

### 阶段 4: 共享组件 + 收尾

---

### Task 25: 共享组件

**Files:**
- Create: `web-ui/src/components/shared/StatusBadge.vue`
- Create: `web-ui/src/components/shared/FilterBar.vue`
- Create: `web-ui/src/components/shared/EmptyState.vue`
- Create: `web-ui/src/components/dashboard/MetricCard.vue`
- Create: `web-ui/src/components/dashboard/TaskFlow.vue`

**实现要点:**

`StatusBadge.vue` — 通用状态标签，props: status + colorMap:
```vue
<script setup lang="ts">
const props = defineProps<{ status: string }>()
const colorMap: Record<string, string> = {
  pending: 'bg-surface-container text-secondary border border-outline-variant',
  running: 'bg-info-container text-on-info-container',
  done: 'bg-secondary-container text-primary',
  failed: 'bg-warning-container text-on-warning-container',
  blocked: 'bg-error-container text-on-error-container',
  skipped: 'bg-surface-container text-secondary border border-outline-variant',
  idle: 'bg-secondary-container text-primary',
  in_use: 'bg-info-container text-on-info-container',
  cooldown: 'bg-warning-container text-on-warning-container',
  dead: 'bg-error-container text-on-error-container',
  success: 'bg-secondary-container text-primary',
  switched_ip: 'bg-secondary-container text-primary',
  manual: 'bg-warning-container text-on-warning-container',
}
</script>
<template>
  <span class="pill" :class="colorMap[status] || 'bg-surface-container text-secondary'">{{ status }}</span>
</template>
```

`MetricCard.vue` — 指标卡:
```vue
<script setup lang="ts">
defineProps<{ label: string; value: string | number; trend?: string; trendColor?: string }>()
</script>
<template>
  <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
    <div class="text-xs text-secondary mb-1">{{ label }}</div>
    <div class="text-2xl font-medium text-primary">{{ value }}</div>
    <div v-if="trend" class="text-[11px] mt-1" :style="trendColor ? `color: ${trendColor}` : ''">{{ trend }}</div>
  </div>
</template>
```

**Commit:**
```bash
git add web-ui/src/components/shared/ web-ui/src/components/dashboard/
git commit -m "feat(frontend): shared components - StatusBadge + MetricCard + TaskFlow + FilterBar + EmptyState"
```

---

### Task 26: 端到端验证

**Step 1: 启动后端**

Run: `python main.py`
Expected: Flask 启动在 :5000，无报错

**Step 2: 启动前端**

Run: `cd web-ui && pnpm dev`
Expected: Vite 启动在 :5175，proxy 生效

**Step 3: 逐页验证**

- [ ] Dashboard: 指标卡有数据（或 0），柱状图渲染
- [ ] Queue: 6 状态卡有计数，表格分页正常
- [ ] Data: 表列表加载，切表查询正常
- [ ] Proxy: 概览卡有数据，表格正常
- [ ] Captcha: 统计卡有数据，日志表正常
- [ ] Config: 配置项加载，编辑后保存成功
- [ ] Parsers: Parser 列表显示
- [ ] Logs: WebSocket 连接，实时日志推送

**Step 4: Commit**

```bash
git add -A
git commit -m "test: e2e verification - all 8 pages functional"
```

---

## 五、实施顺序与依赖

```
阶段1 后端 (Task 1-8)          阶段2 前端骨架 (Task 9-16)        阶段3 页面 (Task 17-24)    阶段4 收尾
┌──────────────────┐          ┌──────────────────┐             ┌────────────────┐       ┌─────────┐
│ T1  装依赖        │          │ T9  装依赖        │             │ T17 Dashboard  │       │ T25 共享 │
│ T2  Flask 工厂    │          │ T10 Vite proxy   │             │ T18 Queue      │       │ T26 E2E  │
│ T3  Blueprint    │          │ T11 Router       │             │ T19 Data       │       └─────────┘
│ T4  Dashboard API│          │ T12 main.ts      │             │ T20 Proxy      │
│ T5  Crawler API  │          │ T13 HTTP+WS 封装  │             │ T21 Captcha    │
│ T6  其余 7 API   │          │ T14 API 服务层    │             │ T22 Config     │
│ T7  SocketIO     │          │ T15 App.vue      │             │ T23 Parsers    │
│ T8  main.py      │          │ T16 布局组件      │             │ T24 Logs       │
└──────────────────┘          └──────────────────┘             └────────────────┘
   后端可独立测试                   前端骨架可跑空页面              逐页对接 API
```

**关键依赖:**
- Task 4-6 依赖 Task 1-3（Flask 骨架）
- Task 8 依赖 Task 7（SocketIO handler）
- Task 11-16 依赖 Task 9-10（依赖 + proxy）
- Task 17-24 依赖 Task 14-16（API 层 + 布局）
- Task 17-24 之间无依赖，可并行
- Task 26 依赖全部完成

---

## 六、风险与对策

| 风险 | 对策 |
|------|------|
| Playwright sync API 阻塞 Flask 事件循环 | 爬虫用 async Playwright，Scheduler 在独立线程运行 |
| SQLite 读写竞争（爬虫写 + API 读） | WAL 模式 + 每次请求新建读连接，不共享写连接 |
| eventlet monkey-patch 与 Playwright 冲突 | 如果冲突，改用 gevent 或 threading 模式 |
| 前端 dev proxy WebSocket 不通 | vite.config.ts 中 `ws: true` 配置 |
| 生产环境单端口部署 | Flask `static_folder` 指向 dist/，`send_from_directory` serve index.html |
| 配置页面修改危险参数 | AxDialog 二次确认 + 后端校验 |

---

**计划完成。下一步选择执行方式:**

**1. Subagent-Driven（本会话）** — 我逐任务派发 subagent 实现，任务间 review

**2. Parallel Session（独立会话）** — 新开会话用 executing-plans 批量执行

选哪种？
