"""解析器基类模块 - 定义解析器的统一接口与工具链注入。

``parse(page, url) -> list[dict]`` 是唯一必须实现的方法。子类通过
``self.storage.enqueue()`` 入队新 URL，通过 ``self.image_downloader`` 下载图片，
不再需要独立的 ``extract_urls`` / ``extract_images`` 钩子。

工具链（FontDecoder / HtmlParser / ImageDownloader / CaptchaHandler + Storage）
通过 ``ParserTools`` + ``request_pool`` 注入，避免子类重复初始化。

子类示例::

    class ShengyiZRListParser(SimplePageParser):
        url_pattern = r"58\\.com/shengyizr"
        table_name = "shengyizr_list"
        table_schema = "CREATE TABLE shengyizr_list (...)"

        def parse(self, page, url) -> list[dict]:
            ...
            self.storage.enqueue(detail_url)
            self.storage.enqueue_image(img_url)
            ...
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.logger import get_logger

if TYPE_CHECKING:
    from core.storage import Storage
    from parser.tools.captcha_handler import CaptchaHandler
    from parser.tools.font_decoder import FontDecoder
    from parser.tools.html_parser import HtmlParser
    from parser.tools.image_downloader import ImageDownloader

logger = get_logger("parser.base")


@dataclass
class ParserTools:
    """解析器工具链容器，由调度层注入到每个 Parser 实例。"""
    font_decoder: "FontDecoder | None" = None
    html_parser: "HtmlParser | None" = None
    image_downloader: "ImageDownloader | None" = None
    captcha_handler: "CaptchaHandler | None" = None


class BaseParser:
    """解析器基类。

    子类必须声明：
    - ``url_pattern``: 正则字符串，匹配 URL
    - ``table_name``: 业务表名
    - ``table_schema``: 建表 SQL（CREATE TABLE ...）

    子类应实现：
    - ``parse(page, url) -> list[dict]``: 提取数据，通过 ``self.storage.enqueue()`` 入队新 URL
    """

    # 子类必须覆盖
    url_pattern: str = ""
    table_name: str = ""
    table_schema: str = ""

    # HTTP 模式参数（子类可选覆盖）
    http_method: str = "GET"
    http_headers: dict = {}          # Parser 声明的额外 headers
    http_default_params: dict = {}   # 默认 query params
    requires_browser: bool = False   # 标记必须用浏览器模式

    def __init__(self, tools: ParserTools | None = None) -> None:
        self.tools = tools or ParserTools()
        # 快捷访问（向后兼容旧代码直接 self.font_decoder）
        self.font_decoder = self.tools.font_decoder
        self.html_parser = self.tools.html_parser
        self.image_downloader = self.tools.image_downloader
        self.captcha_handler = self.tools.captcha_handler
        self.storage: "Storage | None" = None  # 由 request_pool 注入

    # ---------------- 页面生命周期钩子 ----------------

    async def on_page_created(self, page, url: str) -> None:
        """页面创建后、``goto`` 前的钩子，子类可覆盖注入 JS 脚本。

        在浏览器模式 ``new_page`` 返回 Page 对象后、``goto(url)`` 之前调用。
        适用于注入 ``add_init_script``（如劫持 window.location 阻止 58 跳转）。
        """
        pass

    async def on_before_page_close(self, page) -> None:
        """页面关闭前钩子，子类可覆盖做异步收尾。

        在浏览器模式 ``close_page(page)`` 之前调用，此时 Page 仍可用。
        适用于：截图、提取最终 state、等待异步渲染完成等。
        未覆盖则直接关闭，无额外开销。
        """
        pass

    # ---------------- 表管理 ----------------

    def ensure_table(self, storage: "Storage") -> None:
        """在 storage 中创建业务表（幂等）。由调度层启动时调用。"""
        if not self.table_name or not self.table_schema:
            logger.warning(
                f"{self.__class__.__name__} 未声明 table_name/table_schema，跳过建表"
            )
            return
        storage.ensure_business_table(self.table_name, self.table_schema)
        logger.debug(f"业务表已就绪: {self.table_name}")

    # ---------------- URL 匹配 ----------------

    @classmethod
    def matches(cls, url: str) -> bool:
        """URL 是否匹配本 parser 的 url_pattern。"""
        if not cls.url_pattern:
            return False
        try:
            return re.search(cls.url_pattern, url) is not None
        except re.error as e:
            logger.error(f"{cls.__name__} url_pattern 编译失败: {e}")
            return False

    # ---------------- 子类实现接口 ----------------

    def parse(self, page: Any, url: str) -> list[dict]:
        """提取数据与图片。子类必须实现。

        :param page: Playwright Page 对象或 HTML 字符串（已加载完成）
        :param url: 当前页 URL
        :return: 数据行列表，每行一个 dict（键名匹配 table_schema 列名）

        新 URL 入队通过 ``self.storage.enqueue()`` 完成（由 request_pool 注入）。
        图片下载通过 ``self.image_downloader.download_batch()`` 完成。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 parse()"
        )

    # ---------------- 辅助 ----------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} pattern={self.url_pattern!r} table={self.table_name!r}>"
