"""解析器注册表模块 - 自动发现与查找 URL 对应的 Parser。

按设计文档 4.5：

- 扫描 ``parser/plugins/`` 目录自动发现所有 ``BaseParser`` 子类
- 也可从 config 表的 ``parser_register`` 加载（本期不实现，留扩展）
- ``match(url)`` 按 url_pattern 匹配，返回首个命中的 Parser 实例
- 无匹配返回 ``None``（调度层据此 mark_skipped）

注册顺序保证：列表页 parser 优先于详情页 parser（按 ``priority`` 排序，
``priority`` 大的优先匹配；默认 0）。这避免详情页 URL 被列表页 pattern 误匹配。
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from core.logger import get_logger
from core.storage import Storage
from parser.base import BaseParser, ParserTools

logger = get_logger("parser.registry")


class ParserRegistry:
    """Parser 注册表。

    用法::

        registry = ParserRegistry(storage, tools)
        registry.discover()  # 自动扫描 parser/plugins/
        parser = registry.match("https://58.com/ershouche/123")
    """

    def __init__(
        self,
        storage: Storage | None = None,
        tools: ParserTools | None = None,
    ) -> None:
        self.storage = storage
        self.tools = tools or ParserTools()
        self._classes: list[type[BaseParser]] = []
        self._instances: dict[str, BaseParser] = {}

    # ---------------- 注册 ----------------

    def register(self, cls: type[BaseParser]) -> None:
        """注册一个 Parser 类。

        :raises TypeError: cls 不是 BaseParser 子类
        """
        if not (inspect.isclass(cls) and issubclass(cls, BaseParser)
                and cls is not BaseParser):
            raise TypeError(f"{cls!r} 不是 BaseParser 子类")
        if cls in self._classes:
            return
        self._classes.append(cls)
        logger.debug(f"注册 Parser: {cls.__name__} pattern={cls.url_pattern!r}")

    def discover(self, package: str = "parser.plugins") -> int:
        """递归扫描包目录下的所有 BaseParser 子类。

        :param package: 要扫描的包路径，默认 ``parser.plugins``
        :return: 发现并注册的 Parser 数
        """
        count_before = len(self._classes)
        try:
            pkg = importlib.import_module(package)
        except ImportError as e:
            logger.warning(f"无法导入包 {package}: {e}")
            return 0
        pkg_path = getattr(pkg, "__path__", None)
        if not pkg_path:
            logger.warning(f"{package} 不是包（无 __path__）")
            return 0
        for _, mod_name, is_pkg in pkgutil.iter_modules(pkg_path):
            if mod_name.startswith("_"):
                continue
            if is_pkg:
                # 递归扫描子包（如 shengyizr/list.py、ershouche/detail.py）
                self.discover(f"{package}.{mod_name}")
            else:
                full_name = f"{package}.{mod_name}"
                try:
                    mod = importlib.import_module(full_name)
                except Exception as e:
                    logger.error(f"导入 {full_name} 失败: {e}", exc_info=True)
                    continue
                for _, obj in inspect.getmembers(mod, inspect.isclass):
                    if (issubclass(obj, BaseParser) and obj is not BaseParser
                            and obj.__module__ == full_name):
                        try:
                            self.register(obj)
                        except TypeError as e:
                            logger.warning(f"跳过 {obj}: {e}")
        added = len(self._classes) - count_before
        if package == "parser.plugins":  # 只顶层打印汇总
            logger.info(f"扫描 {package} 完成，新增 {added} 个 Parser")
        return added

    def rescan(self, package: str = "parser.plugins") -> int:
        """重新扫描 Parser 插件（先清空再 discover）。"""
        self._classes.clear()
        self._instances.clear()
        return self.discover(package)

    # ---------------- 匹配 ----------------

    def match(self, url: str) -> BaseParser | None:
        """按 URL 匹配 Parser，返回实例（缓存）。无匹配返回 None。"""
        for cls in self._classes:
            if cls.matches(url):
                # 实例缓存（按类名）
                if cls.__name__ not in self._instances:
                    self._instances[cls.__name__] = cls(self.tools)
                return self._instances[cls.__name__]
        return None

    # ---------------- 表管理 ----------------

    def ensure_all_tables(self) -> int:
        """为所有已注册 Parser 创建业务表。

        :return: 成功建表的 Parser 数
        :raises RuntimeError: 未设置 storage
        """
        if self.storage is None:
            raise RuntimeError("未设置 storage，无法建表")
        count = 0
        for cls in self._classes:
            # 实例化以调用 ensure_table
            inst = self._instances.get(cls.__name__) or cls(self.tools)
            self._instances[cls.__name__] = inst
            try:
                inst.ensure_table(self.storage)
                count += 1
            except Exception as e:
                logger.error(
                    f"为 {cls.__name__} 建表失败: {e}", exc_info=True
                )
        return count

    # ---------------- 查询 ----------------

    @property
    def classes(self) -> list[type[BaseParser]]:
        """已注册的 Parser 类列表（只读视图）。"""
        return list(self._classes)

    def __len__(self) -> int:
        return len(self._classes)

    def __contains__(self, cls: type[BaseParser]) -> bool:
        return cls in self._classes
