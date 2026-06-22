"""Parser 注册表 API — 查看、重新扫描。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app

from core.logger import get_logger

logger = get_logger("web.api.parsers")
bp = Blueprint("parsers", __name__)


def _get_registry():
    """从 app.config 获取 Parser 注册表。

    组件字典由 main.py 在 --serve 启动时注入 app.config['CRAWLER_COMPONENTS']。
    增加防御性诊断: 当 registry 为 None 时, 打印 config 中实际存在的 key,
    帮助定位 WebSocket 错误后 config 丢失的根因.
    """
    components = current_app.config.get("CRAWLER_COMPONENTS", {})
    registry = components.get("registry", None)

    if registry is None and components:
        # 有组件字典但缺少 registry key — 可能是 dev.py 模式(未初始化 registry)
        available_keys = list(components.keys())
        logger.warning(
            f"CRAWLER_COMPONENTS 存在但缺少 'registry' key. "
            f"当前可用 key: {available_keys}. "
            f"app 实例 id={id(current_app)}. "
            f"提示: dev.py 启动时不初始化 registry, 需使用 main.py --serve."
        )
    elif registry is None and not components:
        # CRAWLER_COMPONENTS 完全不存在 — 可能是 app context 指向了错误的 app 实例
        logger.error(
            f"CRAWLER_COMPONENTS 完全缺失! "
            f"app 实例 id={id(current_app)}, "
            f"config keys: {list(current_app.config.keys())[:10]}"
        )

    return registry


@bp.route("")
def list_parsers():
    registry = _get_registry()
    if registry is None:
        logger.warning("GET /api/parsers — registry 未初始化")
        return jsonify([])
    result = []
    for cls in registry.classes if hasattr(registry, "classes") else []:
        result.append({
            "name": cls.__name__,
            "pattern": getattr(cls, "url_pattern", ""),
            "table": getattr(cls, "table_name", ""),
            "fields": len(getattr(cls, "_fields", [])),
            "count": getattr(cls, "_crawl_count", 0),
        })
    logger.info(f"GET /api/parsers → {len(result)} 个 Parser")
    return jsonify(result)


@bp.route("/rescan", methods=["POST"])
def rescan():
    registry = _get_registry()
    if registry is None:
        return jsonify({"error": "Registry not initialized"}), 500
    registry.rescan()
    return jsonify({"ok": True})


@bp.route("/<name>/test", methods=["POST"])
def test_parser(name: str):
    data = request.get_json()
    logger.info(f"POST /api/parsers/{name}/test url={data.get('url', '') if data else ''}")
    return jsonify({"ok": True, "name": name, "url": data.get("url", "") if data else ""})
