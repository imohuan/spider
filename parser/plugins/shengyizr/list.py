"""58 生意转让列表页解析器。

继承 ``SimplePageParser``（自动获得浏览器跳转守卫）。
"""
from ._base import SimplePageParser

import logging

logger = logging.getLogger(__name__)


class ShengyiZRListParser(SimplePageParser):
    """58 生意转让列表页."""

    async def on_wait_ready(self, page) -> None:
        """等待列表项渲染完成（redirect guard 结束后列表元素出现）。"""
        try:
            await page.wait_for_selector(
                "div.content-side-left li h2",
                state="attached",
                timeout=30000,
            )
        except Exception:
            logger.warning(f"[{self.__class__.__name__}] on_wait_ready 超时，列表元素未出现")

    url_pattern = r"58\.com/shengyizr"
    table_name = "shengyizr_list"
    table_schema = """
        CREATE TABLE shengyizr_list (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT,
            title           TEXT,
            location        TEXT,
            address         TEXT,
            status          TEXT,
            building        TEXT,
            manager         TEXT,
            company         TEXT,
            tags            TEXT,
            price_num       TEXT,
            price_unit      TEXT,
            transfer_fee    TEXT,
            image           TEXT,
            area            TEXT,
            detail_url      TEXT,
            crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    def parse(self, page, url: str) -> list[dict]:
        html = self._get_html(page)
        if not html or self.html_parser is None:
            return []

        hp = self.html_parser
        tree = hp.parse(html, base_url=url)

        items = hp.xpath(tree, "//div[contains(@class,'content-side-left')]//li[.//h2]")
        if not items:
            return []

        rows = []
        for li in items:
            row = self._parse_item(hp, li, url)
            if row:
                rows.append(row)
                self.storage.enqueue(row['detail_url'])
                self.storage.enqueue_image(row['image'], max_retry=3)
        # 将详情页 URL 和图片 URL 入队
        # if self.storage is not None:
        #     hrefs = hp.extract_attr_list(
        #         tree,
        #         "//div[contains(@class,'content-side-left')]//li//a[contains(@href,'x.shtml')]",
        #         "href",
        #     )
        #     for href in dict.fromkeys(hrefs):
        #         self.storage.enqueue(href)
        #     imgs = hp.extract_attr_list(
        #         tree,
        #         "//div[contains(@class,'content-side-left')]//li//img[@data-src]",
        #         "data-src",
        #     )
        #     for img in dict.fromkeys(imgs):
        #         self.storage.enqueue_image(img, max_retry=3)
        return rows

    def _parse_item(self, hp, li, page_url: str) -> dict | None:
        """解析单个 li → dict。"""
        title_nodes = hp.xpath(li, ".//h2//span[@class='title_des']")
        title = hp.text(title_nodes[0]) if title_nodes else ""
        if not title:
            return None

        base_nodes = hp.xpath(li, ".//p[contains(@class,'baseinfo')]")
        withi_spans = hp.xpath(li, ".//span[@class='withi']")
        location = hp.text(withi_spans[0]) if withi_spans else ""
        address = hp.text(withi_spans[1]) if len(withi_spans) > 1 else ""

        status = ""
        for p in base_nodes:
            spans = hp.xpath(p, "./span[not(@class)]")
            if spans:
                status = hp.text(spans[0])

        building = ""
        if len(base_nodes) >= 2:
            raw = hp.text(base_nodes[1])
            if raw:
                building = raw.strip()

        mgr_node = hp.xpath(li, ".//span[@class='manager']")
        manager = hp.text(mgr_node[0]) if mgr_node else ""
        comp_node = hp.xpath(li, ".//span[@class='managercompany']")
        company = hp.text(comp_node[0]) if comp_node else ""

        tag_nodes = hp.xpath(li, ".//span[@class='tag-item']")
        tags = "/".join(hp.text(t) for t in tag_nodes)

        price_num_nodes = hp.xpath(li, ".//div[contains(@class,'price')]//span[@class='num']")
        price_num = hp.text(price_num_nodes[0]) if price_num_nodes else ""
        unit_nodes = hp.xpath(li, ".//div[contains(@class,'price')]//span[@class='unit']")
        price_unit = hp.text(unit_nodes[0]) if unit_nodes else ""
        fee_nodes = hp.xpath(li, ".//div[contains(@class,'price')]//p[@class='down']")
        transfer_fee = hp.text(fee_nodes[0]) if fee_nodes else ""

        area_nodes = hp.xpath(li, ".//div[contains(@class,'area')]//p[@class='num']//span")
        area_num = hp.text(area_nodes[0]) if area_nodes else ""

        links = hp.extract_attr_list(li, ".//a[contains(@href,'x.shtml')]", "href")
        detail_url = links[0] if links else ""

        img_nodes = hp.xpath(li, ".//div[@class='pic']//img/@data-src")
        img_url = img_nodes[0] if img_nodes else ""

        return {
            "url": page_url,
            "title": title.strip(),
            "location": location.strip(),
            "address": address.strip(),
            "status": status.strip(),
            "building": building,
            "manager": manager.strip(),
            "company": company.strip(),
            "tags": tags,
            "price_num": price_num.strip(),
            "price_unit": price_unit.strip(),
            "transfer_fee": transfer_fee.strip() if transfer_fee else "",
            "image": img_url.strip(),
            "area": area_num.strip(),
            "detail_url": detail_url,
        }
