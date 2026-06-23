# Workflow System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 热插拔工作流系统 — `workflows/` 目录下的 Python 脚本自动发现、前端/代码触发异步执行、结果存 JSON。

**Architecture:** 4 个新文件 + 3 个修改文件。WorkflowRegistry 扫描 `workflows/` 目录找 `execute` 函数；WorkflowScheduler 后台线程轮询 `workflow_queue` 表执行；Flask 蓝图 `/api/workflows` 暴露 4 个 API；WebSocket 推送 `workflow_task_update`。

**Tech Stack:** Python 3.13 + SQLite + Flask + Flask-SocketIO + pytest

**Design doc:** `docs/plans/2026-06-23-workflow-system-design.md`

---

### Task 0: 创建新表 migration

**Files:**
- Modify: `core/storage.py` — 在 `_SYSTEM_SCHEMA` 添加 `workflow_queue` 建表 SQL
- Create: `tests/test_workflow_system.py` — 所有测试

**Step 1: 在 `_SYSTEM_SCHEMA` 末尾添加建表 SQL**

在 `core/storage.py` 的 `_SYSTEM_SCHEMA` 字符串末尾（`cookie_presets` 表之后）添加：

```sql
CREATE TABLE IF NOT EXISTS workflow_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_name   TEXT NOT NULL,
    params          TEXT,
    status          TEXT DEFAULT 'pending',
    result          TEXT,
    error           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_queue(status);
CREATE INDEX IF NOT EXISTS idx_workflow_name ON workflow_queue(workflow_name);
```

**Step 2: 写测试 — 建表幂等 + CRUD**

```python
# tests/test_workflow_system.py
import json
import tempfile
import os
from core.storage import Storage


class TestWorkflowQueueTable:
    def test_table_created_on_init(self):
        """Storage 初始化时自动建 workflow_queue 表。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            s = Storage(db.name)
            rows = s.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_queue'",
                fetch='all',
            )
            assert len(rows) == 1
            assert rows[0][0] == 'workflow_queue'
            s.close()
        finally:
            os.unlink(db.name)

    def test_table_is_idempotent(self):
        """重复初始化不报错。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            s = Storage(db.name)
            s.init_db()  # 第二次建表
            rows = s.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_queue'",
                fetch='all',
            )
            assert len(rows) == 1
            s.close()
        finally:
            os.unlink(db.name)
```

**Step 3: 跑测试验证**
```bash
python -m pytest tests/test_workflow_system.py::TestWorkflowQueueTable -v
```
预期: 2 passed

**Step 4: Commit**
```bash
git add core/storage.py tests/test_workflow_system.py
git commit -m "feat: add workflow_queue table to SQLite schema"
```

---

### Task 1: WorkflowRegistry — 自动发现

**Files:**
- Create: `core/workflow_registry.py`
- Test: `tests/test_workflow_system.py` (追加)

**Step 1: 写测试 — discover 扫描目录**

在 `tests/test_workflow_system.py` 追加：

```python
import tempfile
from pathlib import Path
from core.workflow_registry import WorkflowRegistry


class TestWorkflowRegistry:
    def test_discover_finds_execute_function(self):
        """扫描 workflows/ 找到有 execute 函数的模块。"""
        d = tempfile.mkdtemp()
        try:
            # 建一个合法的 workflow 文件
            (Path(d) / "hello.py").write_text(
                "async def execute(params):\n    return {'msg': 'ok'}\n"
            )
            # 建一个无 execute 函数的前缀
            (Path(d) / "_utils.py").write_text("def helper(): pass\n")
            # 建一个无 execute 的普通文件
            (Path(d) / "not_a_workflow.py").write_text("x = 1\n")

            registry = WorkflowRegistry()
            registry.discover(directory=d)

            assert "hello" in registry.names
            assert "not_a_workflow" not in registry.names
            assert "_utils" not in registry.names
            assert len(registry) == 1
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_discover_ignores_underscore_prefixed(self):
        """跳过 _ 开头的文件和目录。"""
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "_internal.py").write_text(
                "async def execute(params):\n    return {}\n"
            )
            registry = WorkflowRegistry()
            registry.discover(directory=d)
            assert "_internal" not in registry.names
            assert len(registry) == 0
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_list_workflows(self):
        """列出所有已发现的 workflow 名称。"""
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "a.py").write_text("async def execute(p): return {}\n")
            (Path(d) / "b.py").write_text("async def execute(p): return {}\n")
            registry = WorkflowRegistry()
            registry.discover(directory=d)
            names = registry.names
            assert sorted(names) == ["a", "b"]
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
```

**Step 2: 跑测试验证失败**
```bash
python -m pytest tests/test_workflow_system.py::TestWorkflowRegistry -v
```
预期: FAIL (ImportError: core.workflow_registry 不存在)

**Step 3: 实现 WorkflowRegistry**

```python
# core/workflow_registry.py
"""工作流注册表 — 自动发现 workflows/ 目录下的 execute 函数。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

from core.logger import get_logger

logger = get_logger("workflow.registry")

# workflow execute 函数的签名
ExecuteFunc = Callable[[dict], Any]  # async def execute(params) -> dict


class WorkflowRegistry:
    """工作流注册表。

    扫描指定目录，加载每个 .py 文件中的 ``execute`` 函数。

    用法::

        registry = WorkflowRegistry()
        registry.discover()  # 扫描 workflows/ 目录
        func = registry.get("report")  # 获取 execute 函数
    """

    def __init__(self) -> None:
        self._modules: dict[str, ExecuteFunc] = {}

    # ── 注册 ──

    def register(self, name: str, func: ExecuteFunc) -> None:
        """手动注册一个 workflow 函数。"""
        self._modules[name] = func
        logger.debug(f"注册 workflow: {name}")

    # ── 发现 ──

    def discover(self, directory: str = "workflows") -> int:
        """扫描目录，加载所有包含 ``execute`` 函数的 .py 文件。

        :param directory: 要扫描的目录路径（默认 "workflows"）
        :return: 发现的 workflow 数
        """
        pkg_path = Path(directory)
        if not pkg_path.exists() or not pkg_path.is_dir():
            logger.warning(f"workflows 目录不存在: {pkg_path}")
            return 0

        count_before = len(self._modules)

        for py_file in sorted(pkg_path.glob("*.py")):
            mod_name = py_file.stem  # 不含 .py 的文件名

            # 跳过 _ 前缀和特殊文件
            if mod_name.startswith("_"):
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"workflows.{mod_name}", str(py_file)
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                if hasattr(mod, "execute") and callable(mod.execute):
                    self._modules[mod_name] = mod.execute
                    logger.info(f"发现 workflow: {mod_name}")
                else:
                    logger.debug(f"跳过 {mod_name}: 无 callable execute")
            except Exception as e:
                logger.error(f"加载 workflow {mod_name} 失败: {e}", exc_info=True)

        added = len(self._modules) - count_before
        logger.info(f"扫描 {directory} 完成，发现 {added} 个 workflow")
        return added

    def rescan(self, directory: str = "workflows") -> int:
        """重新扫描（先清空再 discover）。"""
        self._modules.clear()
        return self.discover(directory)

    # ── 查询 ──

    def get(self, name: str) -> ExecuteFunc | None:
        """获取指定 workflow 的 execute 函数。"""
        return self._modules.get(name)

    @property
    def names(self) -> list[str]:
        """所有已注册的 workflow 名称列表。"""
        return sorted(self._modules.keys())

    def __len__(self) -> int:
        return len(self._modules)

    def __contains__(self, name: str) -> bool:
        return name in self._modules


# 便捷函数 — Parser 中直接调用
_registry: WorkflowRegistry | None = None


def get_registry() -> WorkflowRegistry:
    """获取全局 WorkflowRegistry 实例（懒初始化）。"""
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
        _registry.discover()
    return _registry


def enqueue_workflow(workflow_name: str, params: dict) -> int:
    """将工作流任务入队，返回 task_id。

    供 Parser 代码调用::

        from core.workflow_registry import enqueue_workflow
        task_id = enqueue_workflow("report", {"city": "北京"})

    :param workflow_name: workflow 名称（对应文件名，不含 .py）
    :param params: 传递给 execute 的参数
    :return: workflow_queue.id
    """
    import json
    from core.storage import Storage

    storage = Storage()
    with storage.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO workflow_queue (workflow_name, params) VALUES (?, ?)",
            (workflow_name, json.dumps(params, ensure_ascii=False)),
        )
        task_id = cur.lastrowid
    logger.info(f"工作流入队: {workflow_name} → task_id={task_id} params={params}")
    return task_id
```

**Step 4: 跑测试验证通过**
```bash
python -m pytest tests/test_workflow_system.py::TestWorkflowRegistry -v
```
预期: 3 passed

**Step 5: Commit**
```bash
git add core/workflow_registry.py tests/test_workflow_system.py
git commit -m "feat: add WorkflowRegistry auto-discovery"
```

---

### Task 2: WorkflowScheduler — 后台调度执行

**Files:**
- Create: `core/workflow_scheduler.py`
- Test: `tests/test_workflow_system.py` (追加)

**Step 1: 写测试**

在 `tests/test_workflow_system.py` 追加：

```python
import asyncio
import json
import tempfile
from pathlib import Path
from core.workflow_scheduler import WorkflowScheduler
from core.workflow_registry import WorkflowRegistry


class TestWorkflowScheduler:
    @staticmethod
    async def _dummy_execute(params):
        return {"received": params, "ok": True}

    @staticmethod
    async def _failing_execute(params):
        raise RuntimeError("forced failure")

    def test_execute_one_task_success(self):
        """调度器执行一个 pending 任务 → done。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            from core.storage import Storage
            s = Storage(db.name)
            # 手动入库
            s.execute(
                "INSERT INTO workflow_queue (workflow_name, params, status) VALUES (?, ?, 'pending')",
                ("dummy", json.dumps({"x": 1})),
            )

            registry = WorkflowRegistry()
            registry.register("dummy", self._dummy_execute)

            scheduler = WorkflowScheduler(storage=s, registry=registry, poll_interval=0.05)
            scheduler._execute_one_task()

            row = s.execute(
                "SELECT status, result, error FROM workflow_queue WHERE id=1",
                fetch="one",
            )
            assert row["status"] == "done"
            result = json.loads(row["result"])
            assert result["received"] == {"x": 1}
            assert result["ok"] is True
            assert row["error"] is None

            s.close()
        finally:
            import os
            os.unlink(db.name)

    def test_execute_one_task_failure(self):
        """任务抛出异常 → failed + error 记录。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            from core.storage import Storage
            s = Storage(db.name)
            s.execute(
                "INSERT INTO workflow_queue (workflow_name, params, status) VALUES (?, ?, 'pending')",
                ("failing", json.dumps({})),
            )

            registry = WorkflowRegistry()
            registry.register("failing", self._failing_execute)

            scheduler = WorkflowScheduler(storage=s, registry=registry, poll_interval=0.05)
            scheduler._execute_one_task()

            row = s.execute(
                "SELECT status, result, error FROM workflow_queue WHERE id=1",
                fetch="one",
            )
            assert row["status"] == "failed"
            assert "forced failure" in (row["error"] or "")
            assert row["result"] is None

            s.close()
        finally:
            import os
            os.unlink(db.name)

    def test_skip_unknown_workflow(self):
        """workflow_name 不在 registry → 标记 failed。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            from core.storage import Storage
            s = Storage(db.name)
            s.execute(
                "INSERT INTO workflow_queue (workflow_name, params, status) VALUES (?, ?, 'pending')",
                ("nonexistent", json.dumps({})),
            )

            registry = WorkflowRegistry()
            scheduler = WorkflowScheduler(storage=s, registry=registry, poll_interval=0.05)
            scheduler._execute_one_task()

            row = s.execute(
                "SELECT status, error FROM workflow_queue WHERE id=1",
                fetch="one",
            )
            assert row["status"] == "failed"
            assert "not found" in (row["error"] or "").lower()

            s.close()
        finally:
            import os
            os.unlink(db.name)

    def test_start_and_stop(self):
        """启动/停止调度线程。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            from core.storage import Storage
            s = Storage(db.name)

            registry = WorkflowRegistry()
            registry.register("dummy", self._dummy_execute)

            scheduler = WorkflowScheduler(storage=s, registry=registry, poll_interval=0.05)
            scheduler.start()
            assert scheduler.is_running

            # 入队一个任务，等它被执行
            s.execute(
                "INSERT INTO workflow_queue (workflow_name, params) VALUES (?, ?)",
                ("dummy", json.dumps({"test": "auto"})),
            )

            import time
            for _ in range(50):  # 最多等 5 秒
                row = s.execute(
                    "SELECT status FROM workflow_queue WHERE id=1", fetch="one"
                )
                if row and row["status"] in ("done", "failed"):
                    break
                time.sleep(0.1)

            scheduler.stop()
            assert not scheduler.is_running

            s.close()
        finally:
            import os
            os.unlink(db.name)
```

**Step 2: 跑测试验证失败**
```bash
python -m pytest tests/test_workflow_system.py::TestWorkflowScheduler -v
```
预期: FAIL (ImportError)

**Step 3: 实现 WorkflowScheduler**

```python
# core/workflow_scheduler.py
"""工作流调度器 — 后台线程轮询 workflow_queue 执行任务。"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
from datetime import datetime, timezone

from core.logger import get_logger
from core.storage import Storage
from core.workflow_registry import WorkflowRegistry

logger = get_logger("workflow.scheduler")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowScheduler:
    """工作流调度器。

    后台线程轮询 ``workflow_queue`` 表，取 pending 任务执行。

    用法::

        scheduler = WorkflowScheduler(storage, registry)
        scheduler.start()
        # ...
        scheduler.stop()
    """

    def __init__(
        self,
        storage: Storage,
        registry: WorkflowRegistry,
        poll_interval: float = 1.0,
    ) -> None:
        self.storage = storage
        self.registry = registry
        self.poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── 生命周期 ──

    def start(self) -> None:
        """启动后台调度线程。"""
        if self._thread is not None:
            logger.warning("调度器已启动，忽略重复 start")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="workflow-scheduler",
        )
        self._thread.start()
        logger.info("工作流调度器已启动")

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台调度线程。"""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        self._thread = None
        logger.info("工作流调度器已停止")

    # ── 主循环 ──

    def _run_loop(self) -> None:
        """后台线程主循环 — 轮询 + 执行。"""
        while not self._stop_event.is_set():
            try:
                self._execute_one_task()
            except Exception as e:
                logger.error(f"调度循环异常: {e}", exc_info=True)
            # 等 poll_interval 或被 stop
            self._stop_event.wait(self.poll_interval)

    # ── 单任务执行 ──

    def _execute_one_task(self) -> None:
        """从队列取一个 pending 任务并执行。无待处理任务时直接返回。"""
        with self.storage.get_connection() as conn:
            row = conn.execute(
                "SELECT id, workflow_name, params FROM workflow_queue "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()

            if row is None:
                return

            task_id = row[0]
            workflow_name = row[1]
            params_raw = row[2]

            # 标记为 running
            now = _now_iso()
            conn.execute(
                "UPDATE workflow_queue SET status='running', started_at=? WHERE id=?",
                (now, task_id),
            )

        # 解析参数
        try:
            params = json.loads(params_raw) if params_raw else {}
        except json.JSONDecodeError:
            params = {}

        # 获取 execute 函数
        func = self.registry.get(workflow_name)
        if func is None:
            self._mark_failed(task_id, f"workflow '{workflow_name}' not found in registry")
            return

        # 执行
        try:
            if asyncio.iscoroutinefunction(func):
                # 在新的事件循环中运行（与爬虫主循环隔离）
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(func(params))
                finally:
                    loop.close()
            else:
                result = func(params)

            self._mark_done(task_id, result)
            logger.info(f"工作流 {workflow_name} (task_id={task_id}) 完成")

        except Exception as e:
            error_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self._mark_failed(task_id, error_detail)
            logger.error(
                f"工作流 {workflow_name} (task_id={task_id}) 失败: {error_detail[:200]}"
            )

    def _mark_done(self, task_id: int, result: dict) -> None:
        """标记任务完成。"""
        now = _now_iso()
        result_json = json.dumps(result, ensure_ascii=False)
        with self.storage.get_connection() as conn:
            conn.execute(
                "UPDATE workflow_queue SET status='done', result=?, finished_at=? WHERE id=?",
                (result_json, now, task_id),
            )

    def _mark_failed(self, task_id: int, error: str) -> None:
        """标记任务失败。"""
        now = _now_iso()
        with self.storage.get_connection() as conn:
            conn.execute(
                "UPDATE workflow_queue SET status='failed', error=?, finished_at=? WHERE id=?",
                (error, now, task_id),
            )
```

**Step 4: 跑测试验证通过**
```bash
python -m pytest tests/test_workflow_system.py::TestWorkflowScheduler -v
```
预期: 4 passed

**Step 5: Commit**
```bash
git add core/workflow_scheduler.py tests/test_workflow_system.py
git commit -m "feat: add WorkflowScheduler background executor"
```

---

### Task 3: Flask API 蓝图 — `/api/workflows`

**Files:**
- Create: `web/api/workflows.py`
- Modify: `web/api/__init__.py` — 注册蓝图
- Test: `tests/test_workflow_system.py` (追加)

**Step 1: 写 API 测试**

```python
import pytest
from flask import Flask
from web.app import create_app


@pytest.fixture
def app_with_workflows():
    """创建带 workflow API 的测试 Flask app。"""
    app = create_app()
    app.config['TESTING'] = True
    # 注入 mock 组件
    from core.workflow_registry import WorkflowRegistry
    registry = WorkflowRegistry()

    async def mock_execute(params):
        return {"received": params, "status": "ok"}
    registry.register("test_wf", mock_execute)

    from core.storage import Storage
    storage = Storage()

    from core.workflow_scheduler import WorkflowScheduler
    scheduler = WorkflowScheduler(storage=storage, registry=registry, poll_interval=0.05)

    app.config['CRAWLER_COMPONENTS'] = {
        "workflow_registry": registry,
        "workflow_scheduler": scheduler,
    }
    return app


class TestWorkflowAPI:
    def test_list_workflows(self, app_with_workflows):
        """GET /api/workflows 返回已发现的 workflow 列表。"""
        with app_with_workflows.test_client() as client:
            resp = client.get("/api/workflows")
            assert resp.status_code == 200
            data = resp.get_json()
            assert isinstance(data, list)
            assert any(w["name"] == "test_wf" for w in data)

    def test_run_workflow_creates_task(self, app_with_workflows):
        """POST /api/workflows/run 创建 pending 任务并返回 task_id。"""
        with app_with_workflows.test_client() as client:
            resp = client.post(
                "/api/workflows/run",
                json={"workflow_name": "test_wf", "params": {"x": 42}},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert "task_id" in data
            assert data["task_id"] > 0

    def test_run_unknown_workflow(self, app_with_workflows):
        """POST /api/workflows/run 对未知 workflow 返回 400。"""
        with app_with_workflows.test_client() as client:
            resp = client.post(
                "/api/workflows/run",
                json={"workflow_name": "no_such_wf", "params": {}},
            )
            assert resp.status_code == 400

    def test_list_tasks(self, app_with_workflows):
        """GET /api/workflows/tasks 返回任务列表。"""
        with app_with_workflows.test_client() as client:
            # 先创建几个任务
            client.post("/api/workflows/run", json={"workflow_name": "test_wf", "params": {}})
            client.post("/api/workflows/run", json={"workflow_name": "test_wf", "params": {}})
            resp = client.get("/api/workflows/tasks")
            assert resp.status_code == 200
            data = resp.get_json()
            assert len(data) >= 2

    def test_list_tasks_with_status_filter(self, app_with_workflows):
        """GET /api/workflows/tasks?status=pending 过滤。"""
        with app_with_workflows.test_client() as client:
            client.post("/api/workflows/run", json={"workflow_name": "test_wf", "params": {}})
            resp = client.get("/api/workflows/tasks?status=pending")
            data = resp.get_json()
            assert all(t["status"] == "pending" for t in data)

    def test_get_single_task(self, app_with_workflows):
        """GET /api/workflows/tasks/<id> 返回单个任务详情。"""
        with app_with_workflows.test_client() as client:
            run_resp = client.post(
                "/api/workflows/run",
                json={"workflow_name": "test_wf", "params": {"k": "v"}},
            )
            task_id = run_resp.get_json()["task_id"]

            resp = client.get(f"/api/workflows/tasks/{task_id}")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["id"] == task_id
            assert data["workflow_name"] == "test_wf"
            assert json.loads(data["params"]) == {"k": "v"}
```

**Step 2: 跑测试验证失败**
```bash
python -m pytest tests/test_workflow_system.py::TestWorkflowAPI -v
```
预期: FAIL (404 — /api/workflows 路由不存在)

**Step 3: 实现蓝图**

```python
# web/api/workflows.py
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
    data = request.get_json(silent=True) or {}
    workflow_name = data.get("workflow_name")
    params = data.get("params", {})

    if not workflow_name:
        return jsonify({"error": "workflow_name is required"}), 400

    registry = _get_registry()
    if registry and workflow_name not in registry:
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
    limit = request.args.get("limit", 50, type=int)

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
```

**Step 4: 在 `web/api/__init__.py` 注册蓝图**

在 `register_blueprints` 函数中添加：

```python
from web.api.workflows import bp as workflows_bp
app.register_blueprint(workflows_bp, url_prefix='/api/workflows')
```

放在其他蓝图注册之后。

**Step 5: 跑测试验证通过**
```bash
python -m pytest tests/test_workflow_system.py::TestWorkflowAPI -v
```
预期: 6 passed

**Step 6: Commit**
```bash
git add web/api/workflows.py web/api/__init__.py tests/test_workflow_system.py
git commit -m "feat: add /api/workflows blueprint with 4 endpoints"
```

---

### Task 4: WebSocket 事件 + main.py 装配

**Files:**
- Modify: `web/socketio_handlers.py` — 添加 `push_workflow_task_update`
- Modify: `main.py` — 装配 WorkflowRegistry + WorkflowScheduler

**Step 1: 添加 WebSocket 推送函数**

在 `web/socketio_handlers.py` 末尾追加：

```python
def push_workflow_task_update(
    socketio: SocketIO,
    task_id: int,
    workflow_name: str,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """推送工作流任务状态变更。"""
    from datetime import datetime, timezone
    payload = {
        "task_id": task_id,
        "workflow_name": workflow_name,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if result is not None:
        payload["result"] = result
    if error is not None:
        payload["error"] = error
    socketio.emit("workflow_task_update", payload)
```

**Step 2: 修改 WorkflowScheduler 使其支持 WebSocket 推送**

给 `_execute_one_task` 添加可选的 `on_update` 回调参数：

在 `WorkflowScheduler.__init__` 添加：
```python
self._on_update: Callable | None = None
```

添加 setter：
```python
def set_on_update(self, callback: Callable) -> None:
    """设置任务状态变更回调，用于 WebSocket 推送。
    
    callback 签名: (task_id: int, workflow_name: str, status: str, result: dict | None, error: str | None) -> None
    """
    self._on_update = callback
```

在 `_mark_done` 和 `_mark_failed` 中调用回调。

**Step 3: 在 `main.py` 装配组件**

在 `build_components` 函数末尾（return 前）添加：

```python
# ── 工作流系统 ──
from core.workflow_registry import WorkflowRegistry
from core.workflow_scheduler import WorkflowScheduler

workflow_registry = WorkflowRegistry()
workflow_registry.discover()

workflow_scheduler = WorkflowScheduler(
    storage=storage,
    registry=workflow_registry,
)
```

在返回的字典中添加：
```python
"workflow_registry": workflow_registry,
"workflow_scheduler": workflow_scheduler,
```

在 `--serve` 分支（`if args.serve:` 块内）添加：
```python
# 启动工作流调度器并挂 WebSocket 推送
from web.socketio_handlers import push_workflow_task_update
from web.app import socketio

workflow_scheduler.set_on_update(
    lambda task_id, name, status, result, error: push_workflow_task_update(
        socketio, task_id, name, status, result, error
    )
)
workflow_scheduler.start()
```

**Step 4: 跑全部测试**
```bash
python -m pytest tests/test_workflow_system.py -v
```
预期: 全部 11 个测试通过

**Step 5: Commit**
```bash
git add web/socketio_handlers.py main.py tests/test_workflow_system.py
git commit -m "feat: wire workflow system into main.py + WebSocket"
```

---

### Task 5: 初始化示例 workflow + 创建目录

**Files:**
- Create: `workflows/__init__.py`
- Create: `workflows/_example.py` (不会被扫描，作为模板参考)

**Step 1: 创建目录和文件**

创建 `workflows/` 目录。

```python
# workflows/__init__.py
"""工作流模块 — 每个 .py 文件定义一个 async def execute(params) -> dict 函数。"""
```

```python
# workflows/_example.py
"""示例 workflow — 文件名以 _ 开头不会被自动扫描。

复制此文件并改名（去掉 _ 前缀）即可创建新 workflow。
例如: cp _example.py report.py
"""
from core.logger import get_logger

logger = get_logger("workflow.example")


async def execute(params: dict) -> dict:
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
```

**Step 2: Commit**
```bash
git add workflows/__init__.py workflows/_example.py
git commit -m "feat: add workflows directory with example template"
```

---

### Task 6: 最终验收

**Step 1: 跑全部测试**
```bash
python -m pytest tests/test_workflow_system.py -v
```
预期: 全部 11 个测试通过

**Step 2: 运行已有测试确保无回归**
```bash
python -m pytest tests/ -v --ignore=tests/test_workflow_system.py
```
预期: 无新增失败

**Step 3: Commit**
```bash
git commit -m "feat: complete workflow system implementation"
```

---

## 文件清单

| 操作 | 文件 | 说明 |
|---|---|---|
| Create | `workflows/__init__.py` | 包标记 |
| Create | `workflows/_example.py` | 模板（不会被扫描） |
| Create | `core/workflow_registry.py` | 自动发现 + enqueue_workflow |
| Create | `core/workflow_scheduler.py` | 后台线程轮询执行 |
| Create | `web/api/workflows.py` | Flask 蓝图 |
| Create | `tests/test_workflow_system.py` | 全部测试 |
| Modify | `core/storage.py` | 添加 workflow_queue 建表 SQL |
| Modify | `web/api/__init__.py` | 注册 workflow 蓝图 |
| Modify | `web/socketio_handlers.py` | 添加 push_workflow_task_update |
| Modify | `main.py` | 装配 WorkflowRegistry + Scheduler |

## API 汇总

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/workflows` | 列出已发现 workflow |
| POST | `/api/workflows/run` | 触发执行 `{workflow_name, params}` |
| GET | `/api/workflows/tasks` | 任务列表 `?status=&workflow_name=` |
| GET | `/api/workflows/tasks/<id>` | 任务详情 |

## WebSocket 事件

| 事件名 | 说明 |
|---|---|
| `workflow_task_update` | 任务状态变更时推送 `{task_id, workflow_name, status, result?, error?, timestamp}` |

## Parser 调用方式

```python
from core.workflow_registry import enqueue_workflow
task_id = enqueue_workflow("report", {
    "city": city,
    "ref_id": task_id,
    "ref_table": "shengyizr_list",
})
```
