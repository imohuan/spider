"""Dashboard API。"""
from __future__ import annotations
from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('dashboard', __name__)

@bp.route('/metrics')
def get_metrics():
    s = Storage()
    today_crawled = s.execute(
        "SELECT COUNT(*) FROM requests WHERE date(request_time) = date('now') AND request_status = 'success'",
        fetch='one')[0]
    today_total = s.execute(
        "SELECT COUNT(*) FROM requests WHERE date(request_time) = date('now')",
        fetch='one')[0]
    success_rate = round(today_crawled / today_total * 100, 1) if today_total > 0 else 0.0
    queue_length = s.execute(
        "SELECT COUNT(*) FROM queue WHERE status IN ('pending', 'failed')",
        fetch='one')[0]
    ip_available = s.execute(
        "SELECT COUNT(*) FROM proxy_pool WHERE status = 'idle'",
        fetch='one')[0]
    ip_total = s.execute(
        "SELECT COUNT(*) FROM proxy_pool WHERE status IN ('idle', 'in_use', 'cooldown')",
        fetch='one')[0]
    return jsonify({'today_crawled': today_crawled, 'success_rate': success_rate, 'queue_length': queue_length, 'ip_available': ip_available, 'ip_total': ip_total})

@bp.route('/progress')
def get_progress():
    hours = request.args.get('hours', 24, type=int)
    s = Storage()
    rows = s.execute(
        "SELECT strftime('%%Y-%%m-%%d %%H:00', request_time), SUM(CASE WHEN request_status='success' THEN 1 ELSE 0 END), SUM(CASE WHEN request_status!='success' THEN 1 ELSE 0 END) FROM requests WHERE request_time >= datetime('now', ?) GROUP BY strftime('%%Y-%%m-%%d %%H:00', request_time) ORDER BY 1",
        params=(f'-{hours} hours',), fetch='all')
    return jsonify([{'hour': r[0], 'success': r[1], 'failed': r[2]} for r in rows])

@bp.route('/recent')
def get_recent():
    limit = request.args.get('limit', 20, type=int)
    s = Storage()
    rows = s.execute(
        "SELECT q.url, q.parser_name, q.status, q.error_type, q.error_msg, q.finished_at, r.request_status FROM queue q LEFT JOIN requests r ON r.queue_id=q.id AND r.id=(SELECT MAX(id) FROM requests WHERE queue_id=q.id) WHERE q.status!='pending' ORDER BY COALESCE(q.finished_at,q.started_at,q.created_at) DESC LIMIT ?",
        params=(limit,), fetch='all')
    return jsonify([{'url':r[0],'parser':r[1],'status':r[2],'error_type':r[3],'error_msg':r[4],'finished_at':r[5],'request_status':r[6]} for r in rows])
