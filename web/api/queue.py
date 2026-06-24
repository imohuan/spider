from __future__ import annotations
import json as _json
import os
from datetime import datetime
from flask import Blueprint, current_app, jsonify, request
from config import RAW_RESPONSE_DIR, PROJECT_ROOT
from core.storage import Storage

bp = Blueprint('queue', __name__)


def _convert_edit_this_cookie(raw: list) -> dict:
    """将 EditThisCookie JSON 转换为 httpx cookies 格式 {name: value}。"""
    return {item["name"]: item["value"] for item in raw if "name" in item and "value" in item}


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


def _save_raw_html(html: str) -> str:
    """将 raw 模式的 HTML 保存到 data/raw_responses/，返回相对路径。

    文件名格式：raw_{timestamp}_{hash}.html
    """
    os.makedirs(RAW_RESPONSE_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # 取 HTML 前 2000 字符的 hash 做文件名后缀（防撞名）
    tag = format(abs(hash(html[:2000] if len(html) > 2000 else html)), 'x')[:8]
    filename = f"raw_{ts}_{tag}.html"
    filepath = os.path.join(RAW_RESPONSE_DIR, filename)

    # 截断过大的 HTML（>5MB）
    max_size = 5 * 1024 * 1024
    content = html
    if len(content) > max_size:
        half = max_size // 2
        content = content[:half] + "\n\n<!-- ... HTML 过大，已截断 ... -->\n\n" + content[-half:]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return os.path.relpath(filepath, PROJECT_ROOT)


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
        fetch_mode:   string (可选) — "browser" / "http" / "raw"，默认 "browser"
        request_config: dict (可选) — 任务级请求参数（method/headers/cookies 等）
        html:         string (可选) — 直接传入 HTML 文本，跳过抓取。
                      传入后 fetch_mode 自动设为 "raw"，HTML 存文件，
                      DB 只记 request_config.raw_html_path 路径。
    返回:
        {ok: true, queue_id: int}
    """
    data = request.get_json(silent=True) or {}
    url = (data.get('url', '') or '').strip()
    html_text = (data.get('html', '') or '').strip()
    
    if not url:
        return jsonify({'ok': False, 'error': 'url is required'}), 400
    
    parser_name = data.get('parser_name') or None
    fetch_mode = data.get('fetch_mode') or 'browser'
    request_config = data.get('request_config') or None
    
    # raw 模式：传入 html 则自动切换，跳过抓取
    # HTML 立即保存到 data/raw_responses/，DB 只存文件路径
    raw_mode = False
    if html_text:
        fetch_mode = 'raw'
        raw_mode = True
        request_config = request_config or {}
        raw_html_path = _save_raw_html(html_text)
        request_config['raw_html_path'] = raw_html_path
    
    # Cookie 预设自动匹配（非 raw 模式，不覆盖前端显式传入的 cookies）
    if not raw_mode and (not request_config or 'cookies' not in request_config):
        s = Storage()
        matched = s.match_cookie_preset(url)
        if matched is not None:
            try:
                preset_cookies = _json.loads(matched[3])  # cookies_json 列
                if isinstance(preset_cookies, list) and len(preset_cookies) > 0:
                    request_config = request_config or {}
                    request_config['cookies'] = _convert_edit_this_cookie(preset_cookies)
            except (_json.JSONDecodeError, Exception):
                pass  # 格式异常静默忽略，不影响入队
    
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
        'fetch_mode': fetch_mode,
    })

@bp.route('/retry-blocked', methods=['POST'])
def retry_blocked():
    Storage().execute("UPDATE queue SET status='pending' WHERE status='blocked'")
    return jsonify({'ok':True})
