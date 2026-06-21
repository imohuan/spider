from __future__ import annotations
import os
from flask import Blueprint, jsonify, request
from config import LOGS_DIR

bp = Blueprint('logs', __name__)

@bp.route('')
def list_logs():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 100, type=int)
    level = request.args.get('level', '')
    module = request.args.get('module', '')
    search = request.args.get('search', '')
    log_path = os.path.join(LOGS_DIR, 'run.log')
    if not os.path.exists(log_path): return jsonify({'items':[],'total':0,'page':page,'size':size})
    with open(log_path, 'r', encoding='utf-8') as f: lines = f.readlines()
    lines.reverse()
    filtered = [l.strip() for l in lines if (not level or f'[{level}]' in l) and (not module or f'crawler.{module}' in l or module in l) and (not search or search in l)]
    if size == -1:
        return jsonify({'items':filtered,'total':len(filtered),'page':1,'size':len(filtered)})
    start = (page-1)*size
    return jsonify({'items':filtered[start:start+size],'total':len(filtered),'page':page,'size':size})
