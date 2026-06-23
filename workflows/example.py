"""示例 workflow。

调用方式:
    # Parser 中:
    self.storage.enqueue_workflow("example", {"row": row}, ref_id=task_id)

    # 前端 API:
    POST /api/workflows/run {"workflow_name": "example", "params": {...}, "ref_id": 123}
"""
from core.logger import get_logger

logger = get_logger("workflow.example")


async def execute(params: dict, storage=None, ref_id=None) -> dict:
    """工作流入口函数。

    :param params: 调用方传入的参数字典（含 row 数据等）
    :param storage: Storage 实例，可直接查/写数据库
    :param ref_id: 关联的业务 ID（如 queue.id）
    :return: 字典结果，存为 JSON 到 workflow_queue.result
    """
    logger.info(f"example workflow: ref_id={ref_id} params keys={sorted(params.keys())}")

    row = params.get("row", {})

    # 可访问数据库
    if storage:
        total = storage.execute(
            "SELECT COUNT(*) AS cnt FROM queue", fetch="one"
        )
        logger.info(f"当前队列任务数: {total['cnt']}")

    # 可访问网络
    # import httpx
    # async with httpx.AsyncClient() as c:
    #     resp = await c.get("https://api.example.com/data")

    return {
        "status": "ok",
        "ref_id": ref_id,
        "row_keys": sorted(row.keys()) if row else [],
    }
