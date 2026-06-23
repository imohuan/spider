"""工作流 API — 列出/触发/查询工作流任务。"""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, request, current_app

from core.logger import get_logger

logger = get_logger("web.api.workflows")
bp = Blueprint("workflows", __name__)


def _get_registry():
    """获取 WorkflowRegistry 实例。"""
    components = current_app.config.get("CRAWLER_COMPONENTS", {})
    return components.get("workflow_registry")


def _get_scheduler():
    """获取 WorkflowScheduler 实例。"""
    components = current_app.config.get("CRAWLER_COMPONENTS", {})
    return components.get("workflow_scheduler")


def _get_storage():
    """获取 Storage 实例。"""
    components = current_app.config.get("CRAWLER_COMPONENTS", {})
    return components.get("storage")


@bp.route("")
def list_workflows():
    """列出所有已发现的 workflow。"""
    registry = _get_registry()
    if registry is None:
        return jsonify([])

    result = []
    for name in registry.names:
        result.append({
            "name": name,
            "module": f"workflows.{name}",
        })
    return jsonify(result)


@bp.route("/run", methods=["POST"])
def run_workflow():
    """触发工作流执行，返回 task_id。

    Body: {"workflow_name": "report", "params": {"city": "北京"}}
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    workflow_name = data.get("workflow_name")
    params = data.get("params", {})

    if not workflow_name:
        return jsonify({"error": "workflow_name is required"}), 400

    if not isinstance(params, dict):
        return jsonify({"error": "params must be a dict"}), 400

    registry = _get_registry()
    if registry is None:
        return jsonify({"error": "Workflow registry not initialized"}), 500
    if workflow_name not in registry:
        return jsonify({"error": f"workflow '{workflow_name}' not found"}), 400

    storage = _get_storage()
    if storage is None:
        return jsonify({"error": "Storage not initialized"}), 500

    params_json = json.dumps(params, ensure_ascii=False)
    with storage.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO workflow_queue (workflow_name, params) VALUES (?, ?)",
            (workflow_name, params_json),
        )
        task_id = cur.lastrowid

    logger.info(f"POST /api/workflows/run → {workflow_name} task_id={task_id}")
    return jsonify({"task_id": task_id})


@bp.route("/tasks")
def list_tasks():
    """列出工作流任务，支持按 status / workflow_name 过滤。"""
    storage = _get_storage()
    if storage is None:
        return jsonify([])

    status = request.args.get("status")
    workflow_name = request.args.get("workflow_name")
    limit = min(request.args.get("limit", 50, type=int), 200)

    conditions = []
    params_list = []

    if status:
        conditions.append("status = ?")
        params_list.append(status)
    if workflow_name:
        conditions.append("workflow_name = ?")
        params_list.append(workflow_name)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    sql = (
        f"SELECT id, workflow_name, params, status, result, error, "
        f"created_at, started_at, finished_at "
        f"FROM workflow_queue {where} ORDER BY created_at DESC LIMIT ?"
    )

    rows = storage.execute(sql, tuple(params_list) + (limit,), fetch="all")

    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "workflow_name": row["workflow_name"],
            "params": row["params"],
            "status": row["status"],
            "result": row["result"],
            "error": row["error"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        })

    return jsonify(result)


@bp.route("/tasks/<int:task_id>")
def get_task(task_id: int):
    """获取单个工作流任务详情（含 result JSON）。"""
    storage = _get_storage()
    if storage is None:
        return jsonify({"error": "Storage not initialized"}), 500

    row = storage.execute(
        "SELECT id, workflow_name, params, status, result, error, "
        "created_at, started_at, finished_at "
        "FROM workflow_queue WHERE id=?",
        (task_id,),
        fetch="one",
    )

    if row is None:
        return jsonify({"error": "Task not found"}), 404

    return jsonify({
        "id": row["id"],
        "workflow_name": row["workflow_name"],
        "params": row["params"],
        "status": row["status"],
        "result": row["result"],
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    })
