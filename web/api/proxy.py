from __future__ import annotations
from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('proxy', __name__)

@bp.route('/stats')
def stats():
    s = Storage()
    rows = s.execute("SELECT status, COUNT(*) FROM proxy_pool GROUP BY status", fetch='all')
    return jsonify({r[0]: r[1] for r in rows})

@bp.route('')
def list_proxy():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    st = request.args.get('status', '')
    where, params = "WHERE 1=1", []
    if st: where = "WHERE status = ?"; params.append(st)
    s = Storage()
    total = s.execute(f"SELECT COUNT(*) FROM proxy_pool {where}", params=params, fetch='one')[0]
    rows = s.execute(f"SELECT id,ip,port,city,username,status,use_count,max_use,fail_count,expire_at,cooldown_until FROM proxy_pool {where} ORDER BY id DESC LIMIT ? OFFSET ?", params=params+[size,(page-1)*size], fetch='all')
    return jsonify({'items':[{'id':r[0],'ip':r[1],'port':r[2],'city':r[3],'username':r[4],'status':r[5],'use':r[6],'max_use':r[7],'fail':r[8],'expire_at':r[9],'cooldown_until':r[10]} for r in rows],'total':total,'page':page,'size':size})

@bp.route('/fetch', methods=['POST'])
def fetch_proxy():
    """手动获取 1 个 IP 并写入代理池。"""
    from flask import current_app
    try:
        comps = current_app.config.get('CRAWLER_COMPONENTS', {})
        proxy_pool = comps.get('proxy_pool')
        if proxy_pool and proxy_pool.provider:
            records = proxy_pool.provider.fetch(num=1)
            if records:
                rec = records[0]
                from datetime import datetime, timedelta, timezone
                expire_at = (datetime.now(timezone.utc) + timedelta(seconds=proxy_pool.ttl_seconds)).isoformat()
                with proxy_pool.storage.get_connection() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO proxy_pool "
                        "(ip, port, protocol, city, username, password, expire_at, use_count, max_use, status, fail_count) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'idle', 0)",
                        (rec.ip, rec.port, rec.protocol or 'http', rec.city, rec.username, rec.password,
                         expire_at, proxy_pool.max_use),
                    )
                return jsonify({'ok': True, 'ip': rec.ip})
        return jsonify({'ok': False, 'error': 'provider not available'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@bp.route('/health-check', methods=['POST'])
def health_check(): return jsonify({'ok':True})

@bp.route('/<int:pid>', methods=['DELETE'])
def kill_proxy(pid: int):
    Storage().execute("UPDATE proxy_pool SET status='dead' WHERE id=?", params=(pid,))
    return jsonify({'ok':True})
