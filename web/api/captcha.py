from __future__ import annotations
from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('captcha', __name__)

@bp.route('/stats')
def stats():
    s = Storage()
    today = s.execute("SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at)=date('now')", fetch='one')[0]
    auto = s.execute("SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at)=date('now') AND final_status='success'", fetch='one')[0]
    switch = s.execute("SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at)=date('now') AND final_status='switched_ip'", fetch='one')[0]
    manual = s.execute("SELECT COUNT(*) FROM captcha_log WHERE date(triggered_at)=date('now') AND final_status='manual'", fetch='one')[0]
    return jsonify({'today':today,'auto_success':auto,'switch_ip':switch,'manual':manual})

@bp.route('')
def list_captcha():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    s = Storage()
    total = s.execute("SELECT COUNT(*) FROM captcha_log", fetch='one')[0]
    rows = s.execute("SELECT id,url,proxy_ip,strategy,attempt_count,final_status,triggered_at,resolved_at FROM captcha_log ORDER BY id DESC LIMIT ? OFFSET ?", params=(size,(page-1)*size), fetch='all')
    return jsonify({'items':[{'id':r[0],'url':r[1],'ip':r[2],'strategy':r[3],'attempt':r[4],'result':r[5],'triggered_at':r[6],'resolved_at':r[7]} for r in rows],'total':total,'page':page,'size':size})
