"""生意转让 AI 评估数据 API — 关联 shengyizr_detail + workflow_queue。"""
from __future__ import annotations

import json
import traceback

from flask import Blueprint, jsonify, request

from core.logger import get_logger
from core.storage import Storage

logger = get_logger("web.api.shengyi")
bp = Blueprint("shengyi", __name__)

# ── AI 评级常量 ──
AI_LEVELS = ["潜力极高", "值得关注", "一般", "不推荐"]


def _parse_ai_result(result_json: str | None) -> dict | None:
    """从 workflow_queue.result JSON 提取 AI 评估字段。"""
    if not result_json:
        return None
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return None
    inner = data.get("result") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        return None
    return {
        "score": inner.get("score"),
        "level": inner.get("level"),
        "summary": inner.get("summary"),
        "details": inner.get("details"),
        "advice": inner.get("advice"),
    }


def _parse_nearby_pois(result_json: str | None) -> list:
    """从 workflow_queue.result JSON 提取 nearby_pois 字段。"""
    if not result_json:
        return []
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    return data.get("nearby_pois") or []


def _build_where(params: dict) -> tuple[str, list]:
    """构建 WHERE 子句和参数列表。"""
    conditions: list[str] = []
    args: list = []

    # 搜索（标题/地址/描述）
    search = params.get("search", "").strip()
    if search:
        conditions.append(
            "(d.title LIKE ? OR d.address LIKE ? OR d.description LIKE ?)"
        )
        like = f"%{search}%"
        args.extend([like, like, like])

    # 区域
    district = params.get("district", "").strip()
    if district:
        conditions.append("d.district = ?")
        args.append(district)

    # 经营状态
    biz_status = params.get("biz_status", "").strip()
    if biz_status:
        conditions.append("d.biz_status = ?")
        args.append(biz_status)

    # 经营类型
    biz_type = params.get("biz_type", "").strip()
    if biz_type:
        conditions.append("d.biz_type = ?")
        args.append(biz_type)

    # AI 评级（逗号分隔多选）
    level_raw = params.get("level", "").strip()
    if level_raw:
        levels = [l.strip() for l in level_raw.split(",") if l.strip()]
        if levels:
            placeholders = ",".join(["?"] * len(levels))
            conditions.append(
                f"json_extract(w.result, '$.result.level') IN ({placeholders})"
            )
            args.extend(levels)

    # 评分范围
    score_min = params.get("score_min", type=float)
    score_max = params.get("score_max", type=float)
    if score_min is not None:
        conditions.append(
            "CAST(json_extract(w.result, '$.result.score') AS REAL) >= ?"
        )
        args.append(score_min)
    if score_max is not None:
        conditions.append(
            "CAST(json_extract(w.result, '$.result.score') AS REAL) <= ?"
        )
        args.append(score_max)

    # workflow 状态
    wf_status = params.get("status", "").strip()
    if wf_status:
        conditions.append("w.status = ?")
        args.append(wf_status)

    # 自定义标签筛选（多标签 OR 逻辑: 满足任一标签即匹配）
    tag_raw = params.get("tag", "").strip()
    if tag_raw:
        tags = [t.strip() for t in tag_raw.split(",") if t.strip()]
        if tags:
            placeholders = ",".join(["?"] * len(tags))
            conditions.append(
                f"d.info_id IN (SELECT info_id FROM shengyi_tags WHERE tag IN ({placeholders}))"
            )
            args.extend(tags)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    return where, args


@bp.route("/list")
def list_items():
    """分页查询 shengyizr_detail + 58-ai-check 关联结果。

    Query params:
        page=1       size=20
        search=关键词   (标题/地址/描述模糊匹配)
        district=朝阳
        biz_status=经营中
        biz_type=餐饮美食
        level=潜力极高,值得关注  (逗号分隔多选)
        score_min=5   score_max=10
        status=done   (workflow 状态)
        tag=靠谱,急转    (自定义标签筛选, 逗号分隔, OR 逻辑)
        sort_by=score  (排序字段: score / id; 默认 id)
        sort_order=asc (asc / desc; 默认 desc)
    """
    page = request.args.get("page", 1, type=int)
    size = min(request.args.get("size", 20, type=int), 100)
    sort_by = request.args.get("sort_by", "id").strip()
    sort_order = request.args.get("sort_order", "desc").strip()

    # 排序白名单校验
    ALLOWED_SORT = {"id", "score"}
    if sort_by not in ALLOWED_SORT:
        sort_by = "id"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    # 构造 ORDER BY
    if sort_by == "score":
        order_clause = (
            f"CAST(json_extract(w.result, '$.result.score') AS REAL) {sort_order}, "
            "d.id DESC"
        )
    else:
        order_clause = f"d.id {sort_order.upper()}"

    logger.info(f"GET /api/shengyi/list page={page} size={size}")

    try:
        s = Storage()

        # ── WHERE 子句 ──
        where, where_args = _build_where(request.args)

        # ── 总数 ──
        count_sql = f"""
            SELECT COUNT(*)
            FROM shengyizr_detail d
            LEFT JOIN workflow_queue w
                ON d.info_id = w.ref_id AND w.workflow_name = '58-ai-check'
            {where}
        """
        total_raw = s.execute(count_sql, tuple(where_args), fetch="one")
        total = total_raw[0] if total_raw else 0

        # ── 分页数据 ──
        # 选中 shengyizr_detail 全字段 + workflow 关键字段
        data_sql = f"""
            SELECT
                d.*,
                w.id        AS ai_task_id,
                w.status    AS ai_status,
                w.result    AS ai_result,
                w.error     AS ai_error,
                w.created_at    AS ai_created_at,
                w.started_at    AS ai_started_at,
                w.finished_at   AS ai_finished_at
            FROM shengyizr_detail d
            LEFT JOIN workflow_queue w
                ON d.info_id = w.ref_id AND w.workflow_name = '58-ai-check'
            {where}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
        """
        offset = (page - 1) * size
        rows = s.execute(
            data_sql, tuple(where_args) + (size, offset), fetch="all"
        )

        # ── 组装响应 ──
        items = []
        info_ids = []
        for r in rows:
            item = dict(r)
            # 解析 AI 结果
            ai_result_raw = item.pop("ai_result", None)
            ai = _parse_ai_result(ai_result_raw)
            if ai:
                item["ai"] = ai
            nearby = _parse_nearby_pois(ai_result_raw)
            if nearby:
                item["nearby_pois"] = nearby
            items.append(item)
            info_ids.append(item["info_id"])

        # ── 批量加载自定义标签 ──
        if info_ids:
            placeholders = ",".join(["?"] * len(info_ids))
            tag_rows = s.execute(
                f"SELECT info_id, tag FROM shengyi_tags WHERE info_id IN ({placeholders}) ORDER BY id",
                tuple(info_ids),
                fetch="all",
            )
            tag_map: dict[str, list[str]] = {}
            for tr in tag_rows:
                tag_map.setdefault(tr["info_id"], []).append(tr["tag"])
            for item in items:
                custom_tags = tag_map.get(item["info_id"], [])
                if custom_tags:
                    item["custom_tags"] = custom_tags

        logger.info(
            f"GET /api/shengyi/list → {len(items)} 行 / {total} 总行"
        )

        return jsonify({
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        })

    except Exception:
        logger.error(
            f"GET /api/shengyi/list 失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/filters")
def get_filters():
    """获取筛选器可选值（区域/经营状态/经营类型）。"""
    logger.info("GET /api/shengyi/filters")
    try:
        s = Storage()

        def _distinct(col: str) -> list[str]:
            rows = s.execute(
                f"SELECT DISTINCT [{col}] FROM shengyizr_detail "
                f"WHERE [{col}] IS NOT NULL AND [{col}] != '' "
                f"ORDER BY [{col}]",
                fetch="all",
            )
            return [r[col] for r in rows]

        return jsonify({
            "districts": _distinct("district"),
            "biz_statuses": _distinct("biz_status"),
            "biz_types": _distinct("biz_type"),
            "levels": AI_LEVELS,
        })
    except Exception:
        logger.error(
            f"GET /api/shengyi/filters 失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/detail/<info_id>")
def get_detail(info_id: str):
    """获取单条生意详情 + AI 评估。"""
    logger.info(f"GET /api/shengyi/detail/{info_id}")
    try:
        s = Storage()

        sql = """
            SELECT
                d.*,
                w.id        AS ai_task_id,
                w.status    AS ai_status,
                w.result    AS ai_result,
                w.error     AS ai_error,
                w.created_at    AS ai_created_at,
                w.started_at    AS ai_started_at,
                w.finished_at   AS ai_finished_at
            FROM shengyizr_detail d
            LEFT JOIN workflow_queue w
                ON d.info_id = w.ref_id AND w.workflow_name = '58-ai-check'
            WHERE d.info_id = ?
        """
        row = s.execute(sql, (info_id,), fetch="one")

        if row is None:
            return jsonify({"error": "Not found"}), 404

        item = dict(row)
        ai_result_raw = item.pop("ai_result", None)
        ai = _parse_ai_result(ai_result_raw)
        if ai:
            item["ai"] = ai
        nearby = _parse_nearby_pois(ai_result_raw)
        if nearby:
            item["nearby_pois"] = nearby

        # 加载自定义标签
        tag_rows = s.execute(
            "SELECT tag FROM shengyi_tags WHERE info_id = ? ORDER BY id",
            (info_id,), fetch="all",
        )
        custom_tags = [tr["tag"] for tr in tag_rows]
        if custom_tags:
            item["custom_tags"] = custom_tags

        return jsonify(item)

    except Exception:
        logger.error(
            f"GET /api/shengyi/detail/{info_id} 失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/refetch/<info_id>", methods=["POST"])
def refetch_url(info_id: str):
    """重新获取 — 将对应 URL 的队列任务重置为 pending（已存在则重试，不存在则入队）。"""
    logger.info(f"POST /api/shengyi/refetch/{info_id}")
    try:
        s = Storage()
        row = s.execute(
            "SELECT url FROM shengyizr_detail WHERE info_id = ?",
            (info_id,), fetch="one",
        )
        if not row:
            return jsonify({"error": "Not found"}), 404

        url = row["url"]
        # 先查已有队列任务
        existing = s.execute(
            "SELECT id FROM queue WHERE url = ?",
            (url,), fetch="one",
        )
        if existing:
            s.execute(
                "UPDATE queue SET status='pending', retry_count=retry_count+1, error_msg=NULL, error_type=NULL WHERE id=?",
                (existing["id"],),
            )
            logger.info(f"refetch {info_id} → reset queue #{existing['id']} to pending")
            return jsonify({"ok": True, "queue_id": existing["id"], "action": "retry"})

        queue_id = s.enqueue(url, parser_name="ShengyiZRDetailParser")
        logger.info(f"refetch {info_id} → new queue #{queue_id}")
        return jsonify({"ok": True, "queue_id": queue_id, "action": "enqueue"})
    except Exception:
        logger.error(
            f"POST /api/shengyi/refetch/{info_id} 失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500


# ── 自定义标签管理 ──

@bp.route("/tags")
def list_tags():
    """获取所有自定义标签（去重）。"""
    logger.info("GET /api/shengyi/tags")
    try:
        s = Storage()
        rows = s.execute(
            "SELECT DISTINCT tag FROM shengyi_tags ORDER BY tag",
            fetch="all",
        )
        return jsonify([r["tag"] for r in rows])
    except Exception:
        logger.error(f"GET /api/shengyi/tags 失败:\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<info_id>/tags", methods=["GET"])
def get_item_tags(info_id: str):
    """获取指定 item 的自定义标签。"""
    logger.info(f"GET /api/shengyi/{info_id}/tags")
    try:
        s = Storage()
        rows = s.execute(
            "SELECT tag FROM shengyi_tags WHERE info_id = ? ORDER BY id",
            (info_id,), fetch="all",
        )
        return jsonify([r["tag"] for r in rows])
    except Exception:
        logger.error(f"GET /api/shengyi/{info_id}/tags 失败:\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<info_id>/tags", methods=["POST"])
def add_item_tag(info_id: str):
    """添加标签。 body: {"tag": "标签名"}"""
    logger.info(f"POST /api/shengyi/{info_id}/tags")
    try:
        body = request.get_json(silent=True) or {}
        tag = (body.get("tag") or "").strip()
        if not tag:
            return jsonify({"error": "tag is required"}), 400
        if len(tag) > 30:
            return jsonify({"error": "tag too long (max 30)"}), 400

        s = Storage()
        try:
            s.execute(
                "INSERT INTO shengyi_tags (info_id, tag) VALUES (?, ?)",
                (info_id, tag),
            )
        except Exception:
            # 重复标签，忽略
            pass

        logger.info(f"tag added: {info_id} ← {tag}")
        return jsonify({"ok": True, "tag": tag})
    except Exception:
        logger.error(f"POST /api/shengyi/{info_id}/tags 失败:\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<info_id>/tags", methods=["DELETE"])
def remove_item_tag(info_id: str):
    """删除标签。 body: {"tag": "标签名"}  或 query ?tag=标签名"""
    logger.info(f"DELETE /api/shengyi/{info_id}/tags")
    try:
        tag = ""
        if request.is_json:
            body = request.get_json(silent=True) or {}
            tag = (body.get("tag") or "").strip()
        if not tag:
            tag = (request.args.get("tag") or "").strip()
        if not tag:
            return jsonify({"error": "tag is required"}), 400

        s = Storage()
        s.execute(
            "DELETE FROM shengyi_tags WHERE info_id = ? AND tag = ?",
            (info_id, tag),
        )
        logger.info(f"tag removed: {info_id} × {tag}")
        return jsonify({"ok": True, "tag": tag})
    except Exception:
        logger.error(
            f"DELETE /api/shengyi/{info_id}/tags 失败:\n{traceback.format_exc()}"
        )
        return jsonify({"error": "Internal server error"}), 500
