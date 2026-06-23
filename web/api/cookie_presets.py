"""Cookie 预设管理 API。"""
from __future__ import annotations
import json
from flask import Blueprint, jsonify, request
from core.storage import Storage

bp = Blueprint('cookie_presets', __name__)


@bp.route('', methods=['GET'])
def list_presets():
    s = Storage()
    rows = s.list_cookie_presets()
    items = [
        {
            'id': r[0],
            'name': r[1],
            'domain': r[2],
            'cookies_json': r[3],
            'enabled': bool(r[4]),
            'created_at': r[5],
            'updated_at': r[6],
        }
        for r in rows
    ]
    return jsonify({'items': items})


@bp.route('', methods=['POST'])
def create_or_update_preset():
    data = request.get_json(silent=True) or {}
    name = (data.get('name', '') or '').strip()
    domain = (data.get('domain', '') or '').strip()
    cookies_json = (data.get('cookies_json', '') or '').strip()

    if not name or not domain:
        return jsonify({'ok': False, 'error': 'name and domain are required'}), 400

    # 校验 cookies_json 是合法 JSON
    if cookies_json:
        try:
            json.loads(cookies_json)
        except json.JSONDecodeError:
            return jsonify({'ok': False, 'error': 'cookies_json is not valid JSON'}), 400

    preset_id = data.get('id') or None
    try:
        s = Storage()
        new_id = s.upsert_cookie_preset(name=name, domain=domain, cookies_json=cookies_json, preset_id=preset_id)
        return jsonify({'ok': True, 'id': new_id})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@bp.route('/<int:pid>', methods=['DELETE'])
def delete_preset(pid: int):
    s = Storage()
    ok = s.delete_cookie_preset(pid)
    if ok:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'not found'}), 404


@bp.route('/<int:pid>/toggle', methods=['POST'])
def toggle_preset(pid: int):
    """切换 enabled 状态。"""
    row = Storage().get_cookie_preset(pid)
    if row is None:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    new_enabled = 0 if row[4] else 1
    Storage().execute(
        "UPDATE cookie_presets SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (new_enabled, pid), fetch="none",
    )
    return jsonify({'ok': True, 'enabled': bool(new_enabled)})


@bp.route('/<int:pid>', methods=['GET'])
def get_preset(pid: int):
    row = Storage().get_cookie_preset(pid)
    if row is None:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    return jsonify({
        'id': row[0], 'name': row[1], 'domain': row[2],
        'cookies_json': row[3], 'enabled': bool(row[4]),
        'created_at': row[5], 'updated_at': row[6],
    })
