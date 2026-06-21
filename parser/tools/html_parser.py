"""HTML 解析模块 - 基于 lxml 提供 XPath / CSS 选择与节点解析工具。

设计文档 4.4 提到 Parser 工具链含 ``HtmlParser(lxml)``。本模块封装常用操作：

- ``parse(html)`` → ``lxml.html.HtmlElement``
- ``xpath(elem, expr)`` → 节点列表
- ``cssselect(elem, expr)`` → 节点列表
- ``text(elem)`` → 清洗后的文本（去空白、合并换行）
- ``attr(elem, name)`` → 属性值
- ``extract_text_list(elem, expr)`` → 批量提取文本

lxml 是同步 API，与 Parser 的同步 parse() 接口对齐。
"""
from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger

logger = get_logger("parser.html_parser")

# 连续空白/换行压缩为单空格
_WS_RE = re.compile(r"\s+")


class HtmlParser:
    """lxml HTML 解析封装。"""

    def parse(self, html: str | bytes, base_url: str | None = None) -> Any:
        """解析 HTML 字符串为 lxml 元素。

        :param html: HTML 字符串或字节
        :param base_url: 基础 URL（用于相对链接解析）
        :return: ``lxml.html.HtmlElement``
        """
        from lxml import html as lxml_html
        # 直接传字符串给 lxml.html.fromstring，让它正确处理编码
        # （传字节时 lxml 可能误判编码导致中文乱码）
        if isinstance(html, bytes):
            # 尝试从 meta 或 BOM 推断，否则按 utf-8 解码
            try:
                html_str = html.decode("utf-8")
            except UnicodeDecodeError:
                html_str = html.decode("gbk", errors="ignore")
        else:
            html_str = html
        # recover=True 容错破损 HTML
        tree = lxml_html.fromstring(html_str)
        if base_url:
            try:
                tree.make_links_absolute(base_url)
            except Exception as e:
                logger.warning(f"make_links_absolute 失败: {e}")
        return tree

    def xpath(self, elem: Any, expr: str) -> list[Any]:
        """执行 XPath 表达式，返回节点列表。"""
        try:
            result = elem.xpath(expr)
            if isinstance(result, list):
                return result
            return [result]
        except Exception as e:
            logger.warning(f"xpath 失败 expr={expr!r}: {e}")
            return []

    def cssselect(self, elem: Any, expr: str) -> list[Any]:
        """执行 CSS 选择器，返回节点列表。"""
        try:
            return elem.cssselect(expr)
        except Exception as e:
            logger.warning(f"cssselect 失败 expr={expr!r}: {e}")
            return []

    def text(self, elem: Any) -> str:
        """提取元素文本，清洗空白。"""
        if elem is None:
            return ""
        if isinstance(elem, str):
            return _WS_RE.sub(" ", elem).strip()
        # 元素：取 text_content 并清洗
        try:
            raw = elem.text_content()
        except AttributeError:
            raw = str(elem)
        return _WS_RE.sub(" ", raw).strip()

    def attr(self, elem: Any, name: str) -> str:
        """提取元素属性值，不存在返回空字符串。"""
        if elem is None:
            return ""
        try:
            return elem.get(name, "") or ""
        except AttributeError:
            return ""

    def extract_text_list(
        self, elem: Any, expr: str, use_css: bool = False
    ) -> list[str]:
        """批量提取匹配节点的文本。

        :param elem: 根元素
        :param expr: XPath 或 CSS 选择器
        :param use_css: True 用 CSS，False 用 XPath
        :return: 文本列表
        """
        nodes = self.cssselect(elem, expr) if use_css else self.xpath(elem, expr)
        return [self.text(n) for n in nodes]

    def extract_attr_list(
        self, elem: Any, expr: str, attr_name: str, use_css: bool = False
    ) -> list[str]:
        """批量提取匹配节点的属性。"""
        nodes = self.cssselect(elem, expr) if use_css else self.xpath(elem, expr)
        return [self.attr(n, attr_name) for n in nodes]

    # ---------------- 便捷方法 ----------------

    def parse_and_extract(
        self, html: str | bytes, expr: str, use_css: bool = False
    ) -> list[Any]:
        """一步：解析 HTML + 提取节点。"""
        tree = self.parse(html)
        return self.cssselect(tree, expr) if use_css else self.xpath(tree, expr)

    def parse_and_extract_text(
        self, html: str | bytes, expr: str, use_css: bool = False
    ) -> list[str]:
        """一步：解析 HTML + 提取文本列表。"""
        tree = self.parse(html)
        return self.extract_text_list(tree, expr, use_css=use_css)
