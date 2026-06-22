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
def fetch_proxy(): return jsonify({'ok':True})

@bp.route('/health-check', methods=['POST'])
def health_check(): return jsonify({'ok':True})

@bp.route('/<int:pid>', methods=['DELETE'])
def kill_proxy(pid: int):
    Storage().execute("UPDATE proxy_pool SET status='dead' WHERE id=?", params=(pid,))
    return jsonify({'ok':True})
