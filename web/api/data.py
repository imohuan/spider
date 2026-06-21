"""数据浏览 API — 查看/导出数据库中任意表的数据。"""
from __future__ import annotations

import csv
import io
import traceback

from flask import Blueprint, jsonify, request, Response

from core.logger import get_logger
from core.storage import Storage, _validate_identifier

logger = get_logger("web.api.data")
bp = Blueprint("data", __name__)


@bp.route("/tables")
def list_tables():
    """列出所有业务表及行数（排除系统表和 sqlite_* 内部表）。"""
    logger.info("GET /api/data/tables — 查询表列表")
    try:
        s = Storage()
        rows = s.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' "
            "AND name NOT IN ('config','queue','requests','seen_urls','proxy_pool','captcha_log') "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name",
            fetch="all",
        )
        result = []
        for r in rows:
            table_name = r["name"]
            count_raw = s.execute(
                f"SELECT COUNT(*) FROM [{table_name}]", fetch="one"
            )
            count = count_raw[0] if count_raw else 0
            result.append({"name": table_name, "rows": count})
        logger.info(f"GET /api/data/tables → {len(result)} 张表")
        return jsonify(result)
    except Exception:
        logger.error(
            f"GET /api/data/tables 失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<table>")
def query_table(table: str):
    """分页查询指定表的数据。"""
    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)
    logger.info(
        f"GET /api/data/{table} page={page} size={size} — 查询表数据"
    )

    try:
        # 表名校验防 SQL 注入
        _validate_identifier(table)
    except ValueError:
        logger.warning(f"GET /api/data/{table} — 非法表名")
        return jsonify({"error": f"Invalid table name: {table}"}), 400

    try:
        s = Storage()

        # 1) 获取列信息
        cols = s.execute(f"PRAGMA table_info([{table}])", fetch="all")
        if not cols:
            logger.warning(f"GET /api/data/{table} — 表不存在")
            return jsonify({"error": f"Table not found: {table}"}), 404

        col_names = [c["name"] for c in cols]
        logger.debug(f"  columns: {col_names}")

        # 2) 总行数
        total_raw = s.execute(
            f"SELECT COUNT(*) FROM [{table}]", fetch="one"
        )
        total = total_raw[0] if total_raw else 0

        # 3) 分页查询 — 自动选排序列
        #    优先用 id，没有则用第一列
        if "id" in col_names:
            order_col = "id"
        else:
            order_col = f"[{col_names[0]}]"
        sql = (
            f"SELECT * FROM [{table}] ORDER BY {order_col} DESC "
            f"LIMIT ? OFFSET ?"
        )
        logger.debug(f"  SQL: {sql}  params: ({size}, {(page - 1) * size})")
        rows = s.execute(
            sql, params=(size, (page - 1) * size), fetch="all"
        )

        result = {
            "columns": col_names,
            "items": [dict(zip(col_names, r)) for r in rows],
            "total": total,
            "page": page,
            "size": size,
        }
        logger.info(
            f"GET /api/data/{table} → {len(rows)} 行 / {total} 总行"
        )
        return jsonify(result)

    except Exception:
        logger.error(
            f"GET /api/data/{table} 查询失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<table>/export")
def export_table(table: str):
    """导出指定表为 CSV 文件。"""
    logger.info(f"GET /api/data/{table}/export — 导出 CSV")

    try:
        _validate_identifier(table)
    except ValueError:
        logger.warning(f"GET /api/data/{table}/export — 非法表名")
        return jsonify({"error": f"Invalid table name: {table}"}), 400

    try:
        s = Storage()

        cols = s.execute(f"PRAGMA table_info([{table}])", fetch="all")
        if not cols:
            logger.warning(f"GET /api/data/{table}/export — 表不存在")
            return jsonify({"error": f"Table not found: {table}"}), 404

        col_names = [c["name"] for c in cols]
        rows = s.execute(f"SELECT * FROM [{table}]", fetch="all")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(col_names)
        for r in rows:
            writer.writerow(r)

        logger.info(
            f"GET /api/data/{table}/export → {len(rows)} 行 CSV 导出"
        )
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={table}.csv"
            },
        )

    except Exception:
        logger.error(
            f"GET /api/data/{table}/export 失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500
