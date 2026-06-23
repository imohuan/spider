"""58 生意转让详情页解析器。

继承 ``SimplePageParser``（自动获得浏览器跳转守卫 + 滚动懒加载）。
"""
from __future__ import annotations

import re

from ._base import SimplePageParser


class ShengyiZRDetailParser(SimplePageParser):
    """58 生意转让详情页 —— 提取月租、转让费、面积、楼层、经营状态、配套设施等全字段。

    匹配 URL: ``58.com/shangpu/{infoId}x.shtml``
    """

    async def on_wait_ready(self, page, **kwargs) -> None:
        """等待详情页渲染完成（标题 + 价格元素出现）。

        超时时抛异常，由 request_pool 捕获并标记为 failed。
        """
        await page.wait_for_selector(
            "div.house-title h1",
            state="attached",
            timeout=30000,
        )

    url_pattern = r"58\.com/shangpu/\d+x\.shtml"
    table_name = "shengyizr_detail"
    table_schema = """
        CREATE TABLE shengyizr_detail (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT UNIQUE,
            info_id         TEXT,
            house_id        TEXT,
            title           TEXT,
            price_num       TEXT,
            price_unit      TEXT,
            transfer_fee    TEXT,
            payment_method  TEXT,
            area            TEXT,
            property_type   TEXT,
            property_nature TEXT,
            floor           TEXT,
            district        TEXT,
            block           TEXT,
            address         TEXT,
            remaining_lease TEXT,
            biz_status      TEXT,
            biz_type        TEXT,
            transfer_type   TEXT,
            specification   TEXT,
            customer_flow   TEXT,
            related_fee     TEXT,
            lat             REAL,
            lng             REAL,
            poster_name     TEXT,
            poster_company  TEXT,
            poster_biz_area TEXT,
            poster_type     TEXT,
            description     TEXT,
            surroundings    TEXT,
            suitable_biz    TEXT,
            service_intro   TEXT,
            facilities      TEXT,
            tags            TEXT,
            photos          TEXT,
            update_time     TEXT,
            crawled_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    # ---- 核心解析 ----

    def parse(self, page, url: str) -> list[dict]:
        html = self._get_html(page)
        if not html or self.html_parser is None:
            return []

        hp = self.html_parser
        tree = hp.parse(html, base_url=url)

        row: dict = {"url": url}

        # ── JS 变量提取（infoId / houseId / 经纬度 / 发帖人类型）──
        row["info_id"] = _js_field(html, "infoId")
        row["house_id"] = _js_field(html, "houseId")
        row["lat"] = _safe_float(_js_field(html, "lat"))
        row["lng"] = _safe_float(_js_field(html, "lng"))
        row["poster_type"] = _js_field(html, "posterInfoType")

        # ── 标题 ──
        titles = hp.xpath(tree, "//div[contains(@class,'house-title')]//h1")
        row["title"] = hp.text(titles[0]).strip() if titles else ""

        # ── 标签 ──
        tag_spans = hp.xpath(
            tree,
            "//p[contains(@class,'house-update-info')]/span[not(contains(@class,'up'))]"
        )
        tags = []
        for s in tag_spans:
            t = hp.text(s).strip()
            if t and "更新于" not in t:
                tags.append(t)
        row["tags"] = "/".join(tags)

        # ── 更新时间 ──
        up_nodes = hp.xpath(
            tree,
            "//p[contains(@class,'house-update-info')]//span[contains(@class,'up')]"
        )
        if up_nodes:
            row["update_time"] = hp.text(up_nodes[-1]).strip()

        # ── 右侧价格区 ──
        row["price_num"] = _first_text(hp, tree, "//span[contains(@class,'house_basic_title_money_num')]")
        row["price_unit"] = _first_text(hp, tree, "//span[contains(@class,'house_basic_title_money_unit')]")
        row["transfer_fee"] = _first_text(
            hp, tree, "//span[contains(@class,'house_basic_title_money_num_second')]"
        )

        # ── 面积 / 类型 / 租期（右侧三行）──
        info_ups = hp.xpath(tree, "//p[contains(@class,'house_basic_title_info')]/span[contains(@class,'up')]")
        if len(info_ups) >= 1:
            row["area"] = hp.text(info_ups[0]).strip()
        if len(info_ups) >= 2:
            row["property_type"] = hp.text(info_ups[1]).strip()
        if len(info_ups) >= 3:
            row["remaining_lease"] = hp.text(info_ups[2]).strip()

        # ── 区域 / 地址 ──
        addr_divs = hp.xpath(tree, "//div[contains(@class,'house_basic_title_info_2')]")
        if addr_divs:
            addr_p = hp.xpath(addr_divs[0], ".//p[not(contains(@class,'p_2'))]")
            if addr_p:
                raw = hp.text(addr_p[0]).strip()
                if "：" in raw:
                    raw = raw.split("：", 1)[1].strip()
                if "-" in raw:
                    parts = raw.split("-", 1)
                    row["district"] = parts[0].strip()
                    row["block"] = parts[1].strip()
                else:
                    row["district"] = raw
            addr_span = hp.xpath(addr_divs[0], ".//span[contains(@class,'address')]")
            row["address"] = hp.text(addr_span[0]).strip() if addr_span else ""

        # ── 发帖人 ──
        row["poster_name"] = _first_text(hp, tree, "//div[contains(@class,'poster-name')]//span[contains(@class,'name-text')]")
        row["poster_company"] = _first_text(hp, tree, "//div[contains(@class,'poster-company')]")
        row["poster_biz_area"] = _first_text(hp, tree, "//div[contains(@class,'main-address')]//div[contains(@class,'td')]")

        # ── 概况表（general-intro）──
        intro_items = hp.xpath(tree, "//div[contains(@class,'general-intro')]//li[contains(@class,'intro-item')]")
        for li in intro_items:
            title_el = hp.xpath(li, ".//span[contains(@class,'title')]")
            content_el = hp.xpath(li, ".//span[contains(@class,'content')]")
            if not title_el or not content_el:
                continue
            key = hp.text(title_el[0]).strip()
            # content 可能包含子元素（如询问链接），只取表层文本
            value = _stripped_content(hp, content_el[0])

            mapping = {
                "月租":     None,
                "转让费":   "transfer_fee",
                "押付":     "payment_method",
                "剩余租期": "remaining_lease",
                "建筑面积": "area",
                "商铺性质": "property_nature",
                "商铺类型": "property_type",
                "经营状态": "biz_status",
                "经营类型": "biz_type",
                "楼层":     "floor",
                "转让类型": "transfer_type",
                "规格":     "specification",
                "客流人群": "customer_flow",
                "相关费用": "related_fee",
            }
            col = mapping.get(key)
            if col and value:
                row[col] = value

        # ── 描述（房源亮点 / 周边客流 / 适合行业 / 服务介绍）──
        desc_items = hp.xpath(
            tree, "//div[contains(@class,'general-miaoshu')]//div[contains(@class,'des-item')]"
        )
        for div in desc_items:
            title_el = hp.xpath(div, ".//p[contains(@class,'title')]")
            detail_el = hp.xpath(div, ".//article[contains(@class,'detail')]")
            if not title_el or not detail_el:
                continue
            key = hp.text(title_el[0]).strip()
            value = hp.text(detail_el[0]).strip()
            if key == "房源亮点" and value:
                row["description"] = value
            elif key == "周边客流" and value:
                row["surroundings"] = value
            elif key == "适合行业" and value:
                row["suitable_biz"] = value
            elif key == "服务介绍" and value:
                row["service_intro"] = value

        # ── 配套设施 ──
        facility_lis = hp.xpath(
            tree, "//div[contains(@class,'general-peitao')]//ul[contains(@class,'peitao-icon')]/li"
        )
        facilities = []
        for li in facility_lis:
            text = hp.text(li).strip()
            if not text:
                continue
            cls_list = hp.xpath(li, "./@class") or []
            cls_str = " ".join(cls_list) if isinstance(cls_list, list) else str(cls_list)
            status = "有" if "peitao-on" in cls_str else "无"
            facilities.append(f"{text}:{status}")
        row["facilities"] = "|".join(facilities)

        # ── 图片 ──
        imgs = hp.extract_attr_list(
            tree,
            "//div[contains(@class,'general-tupian')]//ul[contains(@class,'general-pic-list')]//img",
            "src",
        )
        unique_imgs = list(dict.fromkeys(imgs)) if imgs else []
        row["photos"] = "|".join(unique_imgs) if unique_imgs else ""

        # 将图片推入下载队列
        for img_url in unique_imgs:
            self.storage.enqueue_image(img_url, max_retry=3)

        self.storage.enqueue_workflow("example", {
            "table": self.table_name,
            "url": url,
            "row": row,
        }, ref_id=getattr(self, '_queue_id', None))

        return [row]


# ── 模块级辅助函数 ──

def _js_field(html: str, field: str) -> str:
    """从 HTML 源码的 <script> 中提取 JS 变量值。

    支持三种格式::

        infoId: "87694515401693"
        lat: 30.311445
        posterInfoType = 4
    """
    # 优先匹配 JSON 风格: "field": "value"
    m = re.search(rf'["\']?{re.escape(field)}["\']?\s*:\s*"([^"]*)"', html)
    if m:
        return m.group(1)
    # 匹配数字风格: field: 123.45 或 field = 123
    m = re.search(rf'["\']?{re.escape(field)}["\']?\s*[:=]\s*([\d.]+)', html)
    if m:
        return m.group(1)
    return ""


def _first_text(hp, tree, xpath: str) -> str:
    """取第一个匹配节点的文本。"""
    nodes = hp.xpath(tree, xpath)
    return hp.text(nodes[0]).strip() if nodes else ""


def _stripped_content(hp, node) -> str:
    """取节点纯文本（跳过如"询问卖方心理预期？"链接等子元素）。"""
    text = hp.text(node)
    if not text:
        return ""
    # 去掉常见的附属文本
    text = re.sub(r"询问卖方心理预期\？?", "", text)
    return text.strip()


def _safe_float(val: str) -> float | None:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
