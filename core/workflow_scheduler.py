"""工作流调度器 — 后台线程轮询 workflow_queue 执行任务。"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Callable

from core.logger import get_logger

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
        storage,
        registry,
        poll_interval: float = 1.0,
    ) -> None:
        self.storage = storage
        self.registry = registry
        self.poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_update: Callable | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_on_update(self, callback: Callable) -> None:
        """设置任务状态变更回调，用于 WebSocket 推送。

        callback 签名: (task_id, workflow_name, status, result, error) -> None
        """
        self._on_update = callback

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
            self._stop_event.wait(self.poll_interval)

    # ── 单任务执行 ──

    def _execute_one_task(self) -> None:
        """从队列取一个 pending 任务并执行。无待处理任务时直接返回。"""
        with self.storage.get_connection() as conn:
            row = conn.execute(
                "SELECT id, workflow_name, ref_id, params FROM workflow_queue "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()

            if row is None:
                return

            task_id = row[0]
            workflow_name = row[1]
            ref_id = row[2]
            params_raw = row[3]

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
            self._mark_failed(task_id, workflow_name, f"workflow '{workflow_name}' not found in registry")
            return

        # 执行 — 传入 params + storage + ref_id
        try:
            if asyncio.iscoroutinefunction(func):
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(func(params, storage=self.storage, ref_id=ref_id))
                finally:
                    loop.close()
            else:
                result = func(params, storage=self.storage, ref_id=ref_id)

            self._mark_done(task_id, workflow_name, result)
            logger.info(f"工作流 {workflow_name} (task_id={task_id}) 完成")

        except Exception as e:
            error_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self._mark_failed(task_id, workflow_name, error_detail)
            logger.error(
                f"工作流 {workflow_name} (task_id={task_id}) 失败: {error_detail[:200]}"
            )

    def _mark_done(self, task_id: int, workflow_name: str, result: dict) -> None:
        """标记任务完成。"""
        now = _now_iso()
        result_json = json.dumps(result, ensure_ascii=False)
        with self.storage.get_connection() as conn:
            conn.execute(
                "UPDATE workflow_queue SET status='done', result=?, finished_at=? WHERE id=?",
                (result_json, now, task_id),
            )
        if self._on_update:
            try:
                self._on_update(task_id, workflow_name, "done", result, None)
            except Exception:
                logger.debug(f"WebSocket push 失败 (done) task_id={task_id}", exc_info=True)

    def _mark_failed(self, task_id: int, workflow_name: str, error: str) -> None:
        """标记任务失败。"""
        now = _now_iso()
        with self.storage.get_connection() as conn:
            conn.execute(
                "UPDATE workflow_queue SET status='failed', error=?, finished_at=? WHERE id=?",
                (error, now, task_id),
            )
        if self._on_update:
            try:
                self._on_update(task_id, workflow_name, "failed", None, error)
            except Exception:
                logger.debug(f"WebSocket push 失败 (failed) task_id={task_id}", exc_info=True)
