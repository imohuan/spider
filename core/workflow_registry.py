"""工作流注册表 — 自动发现 workflows/ 目录下的 execute 函数。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

from core.logger import get_logger

logger = get_logger("workflow.registry")

# workflow execute 函数签名: async def execute(params: dict) -> dict
ExecuteFunc = Callable[[dict], Any]


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
            mod_name = py_file.stem

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


# ── 便捷函数：Parser 中直接调用 ──

_registry: WorkflowRegistry | None = None


def get_registry() -> WorkflowRegistry:
    """获取全局 WorkflowRegistry 实例（懒初始化）。"""
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
        _registry.discover()
    return _registry


def enqueue_workflow(workflow_name: str, params: dict | None = None, ref_id: str | None = None) -> int:
    """将工作流任务入队，返回 task_id。

    供非 Parser 代码调用::

        from core.workflow_registry import enqueue_workflow
        task_id = enqueue_workflow("report", {"city": "北京"}, ref_id=123)

    Parser 中请直接使用 self.storage.enqueue_workflow(...)

    :param workflow_name: workflow 名称
    :param params: 传递给 execute 的参数
    :param ref_id: 关联的业务 ID
    :return: workflow_queue.id
    """
    from core.storage import Storage

    with Storage() as storage:
        return storage.enqueue_workflow(workflow_name, params, ref_id=ref_id)
