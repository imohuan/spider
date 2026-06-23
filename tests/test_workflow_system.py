"""工作流系统测试 — workflow_queue 表 / WorkflowRegistry / WorkflowScheduler / API。"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from flask import Flask
from web.app import create_app


# ──────────────────────────────────────────────────────────
# Task 0: workflow_queue 建表
# ──────────────────────────────────────────────────────────

class TestWorkflowQueueTable:
    def test_table_created_on_init(self):
        """Storage 初始化时自动建 workflow_queue 表。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            from core.storage import Storage
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
            from core.storage import Storage
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

    def test_enqueue_workflow_returns_task_id(self):
        """storage.enqueue_workflow() 插入 pending 任务并返回 id。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            from core.storage import Storage
            s = Storage(db.name)
            task_id = s.enqueue_workflow("report", {"city": "北京"})
            assert task_id > 0

            row = s.execute(
                "SELECT workflow_name, params, status FROM workflow_queue WHERE id=?",
                (task_id,), fetch="one",
            )
            assert row["workflow_name"] == "report"
            assert json.loads(row["params"]) == {"city": "北京"}
            assert row["status"] == "pending"
            s.close()
        finally:
            os.unlink(db.name)

    def test_enqueue_workflow_empty_params(self):
        """enqueue_workflow 空 params 不报错。"""
        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            from core.storage import Storage
            s = Storage(db.name)
            task_id = s.enqueue_workflow("cleanup")
            assert task_id > 0

            row = s.execute(
                "SELECT params FROM workflow_queue WHERE id=?",
                (task_id,), fetch="one",
            )
            assert json.loads(row["params"]) == {}
            s.close()
        finally:
            os.unlink(db.name)


# ──────────────────────────────────────────────────────────
# Task 1: WorkflowRegistry 自动发现
# ──────────────────────────────────────────────────────────

class TestWorkflowRegistry:
    def test_discover_finds_execute_function(self):
        """扫描 workflows/ 找到有 execute 函数的模块。"""
        from core.workflow_registry import WorkflowRegistry
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "hello.py").write_text(
                "async def execute(params):\n    return {'msg': 'ok'}\n"
            )
            (Path(d) / "_utils.py").write_text("def helper(): pass\n")
            (Path(d) / "not_a_workflow.py").write_text("x = 1\n")

            registry = WorkflowRegistry()
            registry.discover(directory=d)

            assert "hello" in registry.names
            assert "not_a_workflow" not in registry.names
            assert "_utils" not in registry.names
            assert len(registry) == 1
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_discover_ignores_underscore_prefixed(self):
        """跳过 _ 开头的文件和目录。"""
        from core.workflow_registry import WorkflowRegistry
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
            shutil.rmtree(d, ignore_errors=True)

    def test_list_workflows(self):
        """列出所有已发现的 workflow 名称。"""
        from core.workflow_registry import WorkflowRegistry
        d = tempfile.mkdtemp()
        try:
            (Path(d) / "a.py").write_text("async def execute(p): return {}\n")
            (Path(d) / "b.py").write_text("async def execute(p): return {}\n")
            registry = WorkflowRegistry()
            registry.discover(directory=d)
            names = registry.names
            assert sorted(names) == ["a", "b"]
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ──────────────────────────────────────────────────────────
# Task 2: WorkflowScheduler 后台调度
# ──────────────────────────────────────────────────────────

class TestWorkflowScheduler:
    @staticmethod
    async def _dummy_execute(params):
        return {"received": params, "ok": True}

    @staticmethod
    async def _failing_execute(params):
        raise RuntimeError("forced failure")

    def test_execute_one_task_success(self):
        """调度器执行一个 pending 任务 → done。"""
        from core.storage import Storage
        from core.workflow_registry import WorkflowRegistry
        from core.workflow_scheduler import WorkflowScheduler

        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            s = Storage(db.name)
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
            os.unlink(db.name)

    def test_execute_one_task_failure(self):
        """任务抛出异常 → failed + error 记录。"""
        from core.storage import Storage
        from core.workflow_registry import WorkflowRegistry
        from core.workflow_scheduler import WorkflowScheduler

        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
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
            os.unlink(db.name)

    def test_skip_unknown_workflow(self):
        """workflow_name 不在 registry → 标记 failed。"""
        from core.storage import Storage
        from core.workflow_registry import WorkflowRegistry
        from core.workflow_scheduler import WorkflowScheduler

        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
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
            os.unlink(db.name)

    def test_start_and_stop(self):
        """启动/停止调度线程。"""
        from core.storage import Storage
        from core.workflow_registry import WorkflowRegistry
        from core.workflow_scheduler import WorkflowScheduler

        db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db.close()
        try:
            s = Storage(db.name)

            registry = WorkflowRegistry()
            registry.register("dummy", self._dummy_execute)

            scheduler = WorkflowScheduler(storage=s, registry=registry, poll_interval=0.05)
            scheduler.start()
            assert scheduler.is_running

            s.execute(
                "INSERT INTO workflow_queue (workflow_name, params) VALUES (?, ?)",
                ("dummy", json.dumps({"test": "auto"})),
            )

            for _ in range(50):
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
            os.unlink(db.name)


# ──────────────────────────────────────────────────────────
# Task 3: Flask API
# ──────────────────────────────────────────────────────────

@pytest.fixture
def app_with_workflows():
    """创建带 workflow API 的测试 Flask app。"""
    app = create_app()
    app.config['TESTING'] = True

    from core.workflow_registry import WorkflowRegistry
    registry = WorkflowRegistry()

    async def mock_execute(params):
        return {"received": params, "status": "ok"}
    registry.register("test_wf", mock_execute)

    from core.storage import Storage
    storage = Storage()

    from core.workflow_scheduler import WorkflowScheduler
    scheduler = WorkflowScheduler(storage=storage, registry=registry, poll_interval=0.05)
    scheduler.start()

    app.config['CRAWLER_COMPONENTS'] = {
        "workflow_registry": registry,
        "workflow_scheduler": scheduler,
        "storage": storage,
    }

    yield app

    scheduler.stop()
    storage.close()


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
