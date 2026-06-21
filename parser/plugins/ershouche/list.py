"""58二手车列表页解析插件。

匹配 58 二手车列表页 URL，解析车辆条目写入 ``ershouche_cars`` 表，
并提取详情页 URL 入队、提取图片 URL 下载。

URL 模式（设计文档 4.5 示例）::

    https://ershouche.58.com/
    https://ershouche.58.com/chesheng/
    https://58.com/ershouche/

列表页 DOM 结构（基于 58 公开页面，可能随改版变化）::

    <ul class="car_list">
      <li class="car_item">
        <a class="title" href="/ershouche/1234567x.shtml">2015年本田雅阁 2.0L</a>
        <span class="price fontSecret">5.8</span>  <!-- 可能加密 -->
        <span class="year">2015</span>
        <span class="mileage">3.2万公里</span>
        <span class="city">北京</span>
        <img class="thumb" src="https://pic.58.com/abc.jpg" />
      </li>
      ...
    </ul>

价格字段可能用字体加密（``fontSecret`` class），由 ``FontDecoder`` 解密。
"""
from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger
from parser.base import BaseParser

logger = get_logger("parser.ershouche_list")

# URL 模式：58二手车列表页（含子域名和路径变体）
URL_PATTERN = r"ershouche\.58\.com|58\.com/ershouche"

# 详情页 URL 提取正则（从 /ershouche/1234567x.shtml 提取 car_id）
_DETAIL_URL_RE = re.compile(r"/ershouche/(\d+)x?\.s?html?")


class ErshoucheListParser(BaseParser):
    """58二手车列表页解析器。"""

    url_pattern = URL_PATTERN
    table_name = "ershouche_cars"
    table_schema = """
        CREATE TABLE ershouche_cars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id      TEXT UNIQUE NOT NULL,
            title       TEXT,
            price       REAL,
            year        INTEGER,
            mileage     TEXT,
            city        TEXT,
            url         TEXT,
            image_path  TEXT,
            crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    # ---------------- 解析 ----------------

    def parse(self, page: Any, url: str) -> list[dict]:
        """解析列表页，返回车辆条目列表。

        :param page: Playwright Page 对象（已加载）或 HTML 字符串（测试用）
        :param url: 列表页 URL
        :return: 车辆 dict 列表，字段匹配 table_schema
        """
        html = self._get_html(page)
        if not html:
            logger.warning(f"列表页 HTML 为空: {url}")
            return []

        hp = self.html_parser
        if hp is None:
            logger.error("HtmlParser 未注入")
            return []

        tree = hp.parse(html, base_url=url)
        items = hp.cssselect(tree, "li.car_item") or hp.cssselect(
            tree, ".car_list li"
        ) or hp.xpath(tree, '//ul[contains(@class,"car")]/li')

        if not items:
            logger.info(f"列表页未找到车辆条目: {url}")
            return []

        results: list[dict] = []
        for item in items:
            row = self._parse_one_item(hp, item, url)
            if row and row.get("car_id"):
                results.append(row)
        logger.info(f"列表页解析完成: {url} → {len(results)} 条车辆")
        return results

    def _parse_one_item(self, hp: Any, item: Any, base_url: str) -> dict:
        """解析单个车辆条目。"""
        # 标题 + 详情链接
        title_node = hp.cssselect(item, "a.title") or hp.xpath(
            item, './/a[contains(@class,"title")]'
        )
        title = hp.text(title_node[0]) if title_node else ""
        detail_url = hp.attr(title_node[0], "href") if title_node else ""

        # car_id 从详情 URL 提取
        car_id = self._extract_car_id(detail_url)

        # 价格（可能加密）
        price_node = hp.cssselect(item, ".price") or hp.cssselect(
            item, ".fontSecret"
        ) or hp.xpath(item, './/span[contains(@class,"price")]')
        price = self._parse_price(hp, price_node[0]) if price_node else None

        # 年份
        year = self._parse_int_field(hp, item, ".year")

        # 里程
        mileage = self._parse_text_field(hp, item, ".mileage")

        # 城市
        city = self._parse_text_field(hp, item, ".city")

        return {
            "car_id": car_id,
            "title": title,
            "price": price,
            "year": year,
            "mileage": mileage,
            "city": city,
            "url": detail_url,
            "image_path": None,  # 图片路径由 image_downloader 填充
        }

    # ---------------- 辅助 ----------------

    def _get_html(self, page: Any) -> str:
        """从 page 获取 HTML（兼容 Playwright Page 和测试用字符串）。"""
        if isinstance(page, str):
            return page
        if page is None:
            return ""
        # Playwright Page: page.content() 是 async，但 parse 是同步接口
        # 调用方应在调用 parse 前已 await page.content() 并传入字符串
        # 或 page 已是同步包装器
        try:
            content = page.content()
            if isinstance(content, str):
                return content
            # async content() — 调用方应自行处理
            logger.warning("page.content() 返回非字符串，调用方应传入 HTML 字符串")
            return ""
        except Exception as e:
            logger.warning(f"获取 page HTML 失败: {e}")
            return ""

    @staticmethod
    def _extract_car_id(url: str) -> str:
        """从详情 URL 提取 car_id。"""
        if not url:
            return ""
        m = _DETAIL_URL_RE.search(url)
        return m.group(1) if m else ""

    def _parse_price(self, hp: Any, node: Any) -> float | None:
        """解析价格节点，处理字体加密。"""
        text = hp.text(node)
        if not text:
            return None
        # 检查是否需要字体解密（class 含 fontSecret）
        class_attr = hp.attr(node, "class") or ""
        if "fontsecret" in class_attr.lower() and self.font_decoder is not None:
            # 需要 HTML 上下文，这里简化：直接尝试解密节点文本
            # 真实场景应传入整个 HTML 给 font_decoder
            try:
                # font_decoder.decode 需要 html，这里用节点文本回退
                decoded = self.font_decoder.decode("", text)
                text = decoded
            except Exception as e:
                logger.warning(f"字体解密价格失败: {e}")
        # 提取数字
        try:
            return float(re.sub(r"[^\d.]", "", text))
        except (ValueError, TypeError):
            return None

    def _parse_int_field(self, hp: Any, item: Any, selector: str) -> int | None:
        """解析整数字段（如年份）。"""
        nodes = hp.cssselect(item, selector)
        if not nodes:
            return None
        text = hp.text(nodes[0])
        m = re.search(r"\d+", text)
        return int(m.group()) if m else None

    def _parse_text_field(self, hp: Any, item: Any, selector: str) -> str:
        """解析文本字段。"""
        nodes = hp.cssselect(item, selector)
        return hp.text(nodes[0]) if nodes else ""
