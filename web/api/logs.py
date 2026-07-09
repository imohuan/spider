from __future__ import annotations
import os
import re
from flask import Blueprint, jsonify, request
from config import LOGS_DIR

bp = Blueprint('logs', __name__)

# 日志行正则：匹配 "2026-07-09 10:30:00 [INFO] crawler.xxx - message"
_LOG_LINE_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.+?)\s+-\s+(.*)$'
)


@bp.route('')
def list_logs():
    """分页获取日志，最新日志在前（倒序）。

    Query params:
        page (int): 页码，1 开始，默认 1
        size (int): 每页条数，默认 5000
        level (str): 按日志级别过滤
        module (str): 按模块名过滤
        search (str): 关键词搜索
    """
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 5000, type=int)
    level = request.args.get('level', '')
    module = request.args.get('module', '')
    search = request.args.get('search', '')

    log_path = os.path.join(LOGS_DIR, 'run.log')
    if not os.path.exists(log_path):
        return jsonify({'items': [], 'total': 0, 'page': page, 'size': size, 'has_more': False})

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = [l.rstrip('\n\r') for l in f]

    # 倒序：最新日志在前
    lines.reverse()

    # 先取当前页，再做过滤（避免全量扫描大文件）
    start = (page - 1) * size
    chunk = lines[start:start + size]

    # 过滤
    filtered = [
        l for l in chunk
        if (not level or f'[{level}]' in l)
        and (not module or f'crawler.{module}' in l or module in l)
        and (not search or search.lower() in l.lower())
    ]

    has_more = (start + size) < len(lines)

    return jsonify({
        'items': filtered,
        'total': len(lines),  # 总行数（未过滤），用于判断是否还有更多
        'page': page,
        'size': size,
        'has_more': has_more,
    })