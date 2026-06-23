"""示例 workflow — 文件名以 _ 开头不会被自动扫描。

复制此文件并改名（去掉 _ 前缀）即可创建新 workflow:
    cp workflows/_example.py workflows/report.py

调用方式:
    # Parser 中:
    self.storage.enqueue_workflow("report", {"city": city, "ref_id": task_id})

    # 非 Parser 代码:
    from core.workflow_registry import enqueue_workflow
    enqueue_workflow("report", {"city": "北京"})
"""
from core.logger import get_logger

logger = get_logger("workflow.58-ai-check")


async def execute(params: dict, storage=None, ref_id=None) -> dict:
    """工作流入口函数。

    :param params: 调用方传入的参数字典（前端表单 / Parser 代码）
    :return: 字典结果，会存为 JSON 到 workflow_queue.result
    """
    logger.info(f"example workflow starting, params={params}")

    # 可访问数据库
    # from core.storage import Storage
    # s = Storage()
    # rows = s.execute("SELECT COUNT(*) FROM queue", fetch="one")

    # 可访问网络
    # import httpx
    # async with httpx.AsyncClient() as c:
    #     resp = await c.get("https://api.example.com/data")

    return {
        "status": "ok",
        "received_params": params,
        "message": "Hello from workflow!",
    }
