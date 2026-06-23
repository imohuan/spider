# 工作流系统设计

## 概述

热插拔自定义脚本任务系统。在 `workflows/` 目录放 Python 文件，每个文件暴露 `execute(params) -> dict`，系统自动发现、加载；前端/Parser 传参数触发异步执行，结果存 JSON。

与爬虫完全独立，但可访问数据库和爬虫组件。

## 架构

```
workflows/                 ← 你写的 Python 文件
  ├─ report.py             → async def execute(params) -> dict
  └─ cleanup.py

core/
  ├─ workflow_registry.py  ← 自动发现/加载 workflow 文件
  └─ workflow_scheduler.py ← 后台线程轮询执行队列任务

web/api/
  └─ workflows.py          ← Flask 蓝图

数据库 (同 SQLite)：
  └─ workflow_queue 表     ← 独立于 queue 表
```

## workflow 文件规范

每个 `.py` 文件必须暴露一个 async 函数：

```python
# workflows/example.py
async def execute(params: dict) -> dict:
    """params: 前端/Parser 传入的参数字典。
    return: 会被存为 JSON 到 result 字段。
    抛出异常 = 任务标记 failed。
    """
    city = params.get("city", "北京")
    # 可 import core.storage 查数据库
    return {"status": "ok", "city": city, "count": 42}
```

## workflow_queue 表

| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增 |
| workflow_name | TEXT | 对应文件名（不含 .py） |
| params | TEXT (JSON) | 自由参数，由调用方传入 |
| status | TEXT | pending / running / done / failed |
| result | TEXT (JSON) | execute 返回值 |
| error | TEXT | 异常信息 |
| created_at | TEXT | ISO 时间 |
| started_at | TEXT | |
| finished_at | TEXT | |

状态机：pending → running → done/failed

## API

4 个路由，挂 `/api/workflows`：

```
GET    /api/workflows              → 列出所有已发现的 workflow
POST   /api/workflows/run           → 触发执行，body: {workflow_name, params}
GET    /api/workflows/tasks         → 任务列表，支持 ?status= & ?workflow_name=
GET    /api/workflows/tasks/<id>    → 单个任务详情（含 result）
```

## Parser 调用方式

```python
from core.workflow_registry import enqueue_workflow
enqueue_workflow("report", {
    "city": city,
    "ref_id": task_id,
    "ref_table": "shengyizr_list"
})
```

## WebSocket 事件

- `workflow_task_update` — 任务状态变更时推送（含 id, status, result）
