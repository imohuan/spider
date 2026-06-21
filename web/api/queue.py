from __future__ import annotations
from flask import Blueprint, current_app, jsonify, request
from core.storage import Storage

bp = Blueprint('queue', __name__)


def _resolve_parser_name(url: str, parser_name: str | None) -> str | None:
    """如果 parser_name 为空，尝试从 registry 匹配 URL。
    
    返回匹配到的 parser 类名；无法匹配则返回原值。
    """
    if parser_name:
        return parser_name
    try:
        components = current_app.config.get("CRAWLER_COMPONENTS", {})
        registry = components.get("registry", None)
        if registry:
            matched = registry.match(url)
            if matched:
                return matched.__class__.__name__
    except Exception:
        pass
    return parser_name


@bp.route('/stats')
def stats():
    s = Storage()
    rows = s.execute("SELECT status, COUNT(*) FROM queue GROUP BY status", fetch='all')
    return jsonify({r[0]: r[1] for r in rows})


@bp.route('')
def list_queue():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    st = request.args.get('status', '')
    parser = request.args.get('parser', '')
    search = request.args.get('search', '')
    where, params = "WHERE 1=1", []
    if st: where += " AND status = ?"; params.append(st)
    if parser: where += " AND parser_name = ?"; params.append(parser)
    if search: where += " AND (url LIKE ? OR error_msg LIKE ?)"; params.extend([f'%{search}%', f'%{search}%'])
    s = Storage()
    total = s.execute(f"SELECT COUNT(*) FROM queue {where}", params=params, fetch='one')[0]
    rows = s.execute(
        f"SELECT id,url,parser_name,status,retry_count,ip_switch_count,error_type,error_msg,created_at "
        f"FROM queue {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params=params+[size, (page-1)*size], fetch='all',
    )
    items = []
    for r in rows:
        parser_name = _resolve_parser_name(r[1], r[2])
        items.append({
            'id': r[0], 'url': r[1], 'parser': parser_name,
            'status': r[3], 'retry': r[4], 'switch': r[5],
            'error_type': r[6], 'error_msg': r[7], 'created_at': r[8],
        })
    return jsonify({'items': items, 'total': total, 'page': page, 'size': size})

@bp.route('/<int:qid>/retry', methods=['POST'])
def retry_one(qid: int):
    Storage().execute("UPDATE queue SET status='pending',retry_count=retry_count+1 WHERE id=?", params=(qid,))
    return jsonify({'ok':True})

@bp.route('', methods=['POST'])
def create_task():
    """创建新任务（URL 入队）。
    
    请求体 JSON:
        url:          string (必填) — 目标 URL
        parser_name:  string (可选) — Parser 名称，None 时自动匹配
        fetch_mode:   string (可选) — "browser" / "http"，默认 "browser"
        request_config: dict (可选) — 任务级请求参数（method/headers/cookies 等）
    返回:
        {ok: true, queue_id: int}
    """
    import json as _json
    data = request.get_json(silent=True) or {}
    url = (data.get('url', '') or '').strip()
    if not url:
        return jsonify({'ok': False, 'error': 'url is required'}), 400
    
    parser_name = data.get('parser_name') or None
    fetch_mode = data.get('fetch_mode') or 'browser'
    request_config = data.get('request_config') or None
    
    # 如果未指定 parser_name，尝试自动匹配
    resolved_parser = _resolve_parser_name(url, parser_name)
    
    s = Storage()
    queue_id = s.enqueue(
        url,
        parser_name=resolved_parser,
        fetch_mode=fetch_mode,
        request_config=request_config,
    )
    return jsonify({
        'ok': True,
        'queue_id': queue_id,
        'parser': resolved_parser or 'auto-detect',
    })

@bp.route('/retry-blocked', methods=['POST'])
def retry_blocked():
    Storage().execute("UPDATE queue SET status='pending' WHERE status='blocked'")
    return jsonify({'ok':True})
