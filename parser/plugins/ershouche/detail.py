"""58二手车详情页解析插件。

匹配详情页 URL（``/ershouche/{car_id}x.shtml``），解析车辆详细字段写入
``ershouche_details`` 表。

URL 模式::

    https://ershouche.58.com/ershouche/1234567x.shtml
    https://ershouche.58.com/chesheng/1234567x.shtml

详情页字段（基于 58 公开页面结构）::

    <div class="car-detail">
      <h1 class="car-title">2015年本田雅阁 2.0L 自动豪华版</h1>
      <div class="price">5.8万</div>
      <ul class="params">
        <li><span class="label">上牌时间</span><span class="value">2015-06</span></li>
        <li><span class="label">表显里程</span><span class="value">3.2万公里</span></li>
        <li><span class="label">变速箱</span><span class="value">自动</span></li>
        <li><span class="label">排量</span><span class="value">2.0L</span></li>
      </ul>
      <div class="car-images">
        <img src="https://pic.58.com/1.jpg" />
        <img src="https://pic.58.com/2.jpg" />
      </div>
      <div class="seller-phone fontSecret">13812345678</div>  <!-- 加密 -->
    </div>
"""
from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger
from parser.base import BaseParser

logger = get_logger("parser.ershouche_detail")

# 详情页 URL 模式
URL_PATTERN = r"ershouche\.58\.com/.*\d+x?\.s?html|58\.com/ershouche/\d+"


class ErshoucheDetailParser(BaseParser):
    """58二手车详情页解析器。"""

    url_pattern = URL_PATTERN
    table_name = "ershouche_details"
    table_schema = """
        CREATE TABLE ershouche_details (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id          TEXT UNIQUE NOT NULL,
            title           TEXT,
            price           REAL,
            license_date    TEXT,
            mileage         TEXT,
            gearbox         TEXT,
            displacement    TEXT,
            seller_phone    TEXT,
            url             TEXT,
            image_paths     TEXT,
            crawled_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    def parse(self, page: Any, url: str) -> list[dict]:
        """解析详情页，返回单条车辆详情 dict。"""
        html = self._get_html(page)
        if not html:
            logger.warning(f"详情页 HTML 为空: {url}")
            return []

        hp = self.html_parser
        if hp is None:
            logger.error("HtmlParser 未注入")
            return []

        tree = hp.parse(html, base_url=url)
        car_id = self._extract_car_id(url)
        if not car_id:
            logger.warning(f"无法从 URL 提取 car_id: {url}")
            return []

        row = {
            "car_id": car_id,
            "title": self._text(hp, tree, "h1.car-title"),
            "price": self._parse_price(hp, tree),
            "license_date": self._param_value(hp, tree, "上牌时间"),
            "mileage": self._param_value(hp, tree, "表显里程"),
            "gearbox": self._param_value(hp, tree, "变速箱"),
            "displacement": self._param_value(hp, tree, "排量"),
            "seller_phone": self._parse_phone(hp, tree),
            "url": url,
            "image_paths": None,
        }
        logger.info(f"详情页解析完成: {url} car_id={car_id}")
        return [row]

    # ---------------- 辅助 ----------------

    def _get_html(self, page: Any) -> str:
        """从 page 获取 HTML（兼容字符串和 Page 对象）。"""
        if isinstance(page, str):
            return page
        if page is None:
            return ""
        try:
            content = page.content()
            return content if isinstance(content, str) else ""
        except Exception as e:
            logger.warning(f"获取 page HTML 失败: {e}")
            return ""

    @staticmethod
    def _extract_car_id(url: str) -> str:
        """从详情 URL 提取 car_id。"""
        m = re.search(r"/(\d+)x?\.s?html?", url)
        return m.group(1) if m else ""

    def _text(self, hp: Any, tree: Any, selector: str) -> str:
        """CSS 选择器取文本。"""
        nodes = hp.cssselect(tree, selector)
        return hp.text(nodes[0]) if nodes else ""

    def _parse_price(self, hp: Any, tree: Any) -> float | None:
        """解析价格。"""
        text = self._text(hp, tree, ".price") or self._text(hp, tree, ".car-price")
        if not text:
            return None
        try:
            return float(re.sub(r"[^\d.]", "", text))
        except (ValueError, TypeError):
            return None

    def _param_value(self, hp: Any, tree: Any, label: str) -> str:
        """从参数列表提取指定 label 的值。

        DOM: <li><span class="label">上牌时间</span><span class="value">2015-06</span></li>
        """
        # 找到 label 节点，取相邻的 value
        expr = f'//li[span[@class="label" and contains(text(),"{label}")]]/span[@class="value"]'
        nodes = hp.xpath(tree, expr)
        if nodes:
            return hp.text(nodes[0])
        # 兼容：li/span 顺序结构
        expr2 = f'//li[contains(.//span[1],"{label}")]/span[2]'
        nodes2 = hp.xpath(tree, expr2)
        return hp.text(nodes2[0]) if nodes2 else ""

    def _parse_phone(self, hp: Any, tree: Any) -> str:
        """解析卖家电话（可能加密）。"""
        node = hp.cssselect(tree, ".seller-phone") or hp.cssselect(
            tree, ".fontSecret"
        )
        if not node:
            return ""
        text = hp.text(node[0])
        if not text:
            return ""
        # 字体解密
        class_attr = hp.attr(node[0], "class") or ""
        if "fontsecret" in class_attr.lower() and self.font_decoder is not None:
            try:
                text = self.font_decoder.decode("", text)
            except Exception as e:
                logger.warning(f"字体解密电话失败: {e}")
        # 提取电话号码
        m = re.search(r"\d{11}|\d{3}[\-\s]?\d{8}", text)
        return m.group() if m else text
