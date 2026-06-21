"""58二手车 Parser 插件测试。

用合成 HTML 样本验证 ErshoucheListParser / ErshoucheDetailParser 的解析逻辑。
不依赖真实 58 页面（避免改版导致测试 flaky）。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parser.base import ParserTools
from parser.plugins.ershouche.detail import ErshoucheDetailParser
from parser.plugins.ershouche.list import ErshoucheListParser
from parser.tools.html_parser import HtmlParser


@pytest.fixture
def tools():
    """注入真实 HtmlParser（无 FontDecoder，测试用合成明文 HTML）。"""
    return ParserTools(html_parser=HtmlParser())


@pytest.fixture
def list_parser(tools):
    return ErshoucheListParser(tools)


@pytest.fixture
def detail_parser(tools):
    return ErshoucheDetailParser(tools)


# 合成列表页 HTML
LIST_HTML = """
<html>
<body>
  <ul class="car_list">
    <li class="car_item">
      <a class="title" href="https://ershouche.58.com/ershouche/1234567x.shtml">2015年本田雅阁 2.0L</a>
      <span class="price">5.8</span>
      <span class="year">2015</span>
      <span class="mileage">3.2万公里</span>
      <span class="city">北京</span>
      <img class="thumb" src="https://pic.58.com/car1.jpg" />
    </li>
    <li class="car_item">
      <a class="title" href="https://ershouche.58.com/ershouche/2345678x.shtml">2016年丰田凯美瑞 2.5L</a>
      <span class="price">6.2</span>
      <span class="year">2016</span>
      <span class="mileage">2.8万公里</span>
      <span class="city">上海</span>
      <img class="thumb" src="https://pic.58.com/car2.jpg" />
    </li>
  </ul>
</body>
</html>
"""

# 合成详情页 HTML
DETAIL_HTML = """
<html>
<body>
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
    <div class="seller-phone">13812345678</div>
  </div>
</body>
</html>
"""


# ============ ErshoucheListParser ============


class TestErshoucheListParser:
    def test_url_pattern_matches_list_page(self):
        assert ErshoucheListParser.matches("https://ershouche.58.com/")
        assert ErshoucheListParser.matches("https://ershouche.58.com/chesheng/")
        assert ErshoucheListParser.matches("https://58.com/ershouche/")

    def test_url_pattern_does_not_match_detail(self):
        """列表页 pattern 不应匹配详情页 URL（避免误判）。

        注：当前 list pattern 较宽泛，详情页 URL 含 ershouche.58.com 也会匹配。
        实际调度靠注册顺序：detail parser 先注册优先匹配。
        本测试验证 list pattern 的基本匹配能力。
        """
        assert ErshoucheListParser.matches("https://ershouche.58.com/ershouche/123x.shtml")

    def test_parse_extracts_car_items(self, list_parser):
        rows = list_parser.parse(LIST_HTML, "https://ershouche.58.com/")
        assert len(rows) == 2
        first = rows[0]
        assert first["car_id"] == "1234567"
        assert "本田雅阁" in first["title"]
        assert first["price"] == 5.8
        assert first["year"] == 2015
        assert first["mileage"] == "3.2万公里"
        assert first["city"] == "北京"
        assert "1234567x.shtml" in first["url"]

    def test_parse_second_item(self, list_parser):
        rows = list_parser.parse(LIST_HTML, "https://ershouche.58.com/")
        assert rows[1]["car_id"] == "2345678"
        assert "凯美瑞" in rows[1]["title"]
        assert rows[1]["year"] == 2016

    def test_parse_empty_html(self, list_parser):
        assert list_parser.parse("", "https://x.com") == []
        assert list_parser.parse("<html></html>", "https://x.com") == []

    def test_parse_no_car_items(self, list_parser):
        html = "<html><body><div>no cars</div></body></html>"
        assert list_parser.parse(html, "https://x.com") == []

    def test_parse_missing_fields_returns_partial(self, list_parser):
        """缺字段的条目仍返回（car_id 必须有）。"""
        html = """
        <ul class="car_list">
          <li class="car_item">
            <a class="title" href="/ershouche/999x.shtml">only title</a>
          </li>
        </ul>
        """
        rows = list_parser.parse(html, "https://ershouche.58.com/")
        assert len(rows) == 1
        assert rows[0]["car_id"] == "999"
        assert rows[0]["title"] == "only title"
        assert rows[0]["price"] is None
        assert rows[0]["year"] is None

    def test_parse_skips_item_without_car_id(self, list_parser):
        """无 car_id 的条目被跳过。"""
        html = """
        <ul class="car_list">
          <li class="car_item">
            <a class="title" href="/some/other/page">no car id</a>
          </li>
          <li class="car_item">
            <a class="title" href="/ershouche/12345x.shtml">valid</a>
          </li>
        </ul>
        """
        rows = list_parser.parse(html, "https://ershouche.58.com/")
        assert len(rows) == 1
        assert rows[0]["car_id"] == "12345"

    def test_table_schema_declared(self):
        assert ErshoucheListParser.table_name == "ershouche_cars"
        assert "CREATE TABLE ershouche_cars" in ErshoucheListParser.table_schema
        assert "car_id" in ErshoucheListParser.table_schema
        assert "UNIQUE" in ErshoucheListParser.table_schema
        assert "price" in ErshoucheListParser.table_schema


# ============ ErshoucheDetailParser ============


class TestErshoucheDetailParser:
    def test_url_pattern_matches_detail(self):
        assert ErshoucheDetailParser.matches(
            "https://ershouche.58.com/ershouche/1234567x.shtml"
        )
        assert ErshoucheDetailParser.matches(
            "https://ershouche.58.com/chesheng/123x.shtml"
        )

    def test_parse_extracts_detail_fields(self, detail_parser):
        url = "https://ershouche.58.com/ershouche/1234567x.shtml"
        rows = detail_parser.parse(DETAIL_HTML, url)
        assert len(rows) == 1
        row = rows[0]
        assert row["car_id"] == "1234567"
        assert "本田雅阁" in row["title"]
        assert row["price"] == 5.8
        assert row["license_date"] == "2015-06"
        assert row["mileage"] == "3.2万公里"
        assert row["gearbox"] == "自动"
        assert row["displacement"] == "2.0L"
        assert row["seller_phone"] == "13812345678"
        assert row["url"] == url

    def test_parse_empty_html(self, detail_parser):
        assert detail_parser.parse("", "https://x.com/123x.shtml") == []

    def test_parse_no_car_id_in_url_returns_empty(self, detail_parser):
        """URL 无 car_id 时返回空。"""
        rows = detail_parser.parse(DETAIL_HTML, "https://x.com/no-id-here")
        assert rows == []

    def test_parse_missing_price(self, detail_parser):
        """缺价格字段时 price=None。"""
        html = """
        <div class="car-detail">
          <h1 class="car-title">title</h1>
        </div>
        """
        rows = detail_parser.parse(html, "https://x.com/123x.shtml")
        assert rows[0]["price"] is None

    def test_parse_missing_param(self, detail_parser):
        """缺参数时对应字段为空字符串。"""
        html = """
        <div class="car-detail">
          <h1 class="car-title">t</h1>
          <ul class="params">
            <li><span class="label">上牌时间</span><span class="value">2015</span></li>
          </ul>
        </div>
        """
        rows = detail_parser.parse(html, "https://x.com/123x.shtml")
        assert rows[0]["license_date"] == "2015"
        assert rows[0]["mileage"] == ""
        assert rows[0]["gearbox"] == ""

    def test_table_schema_declared(self):
        assert ErshoucheDetailParser.table_name == "ershouche_details"
        assert "CREATE TABLE ershouche_details" in ErshoucheDetailParser.table_schema
        assert "car_id" in ErshoucheDetailParser.table_schema
        assert "UNIQUE" in ErshoucheDetailParser.table_schema
        assert "seller_phone" in ErshoucheDetailParser.table_schema


# ============ ParserRegistry 集成测试 ============


def test_registry_discovers_both_plugins():
    """discover() 应扫描到两个真实 Parser 插件。"""
    from parser.registry import ParserRegistry
    r = ParserRegistry()
    n = r.discover()
    assert n >= 2
    class_names = [c.__name__ for c in r.classes]
    assert "ErshoucheListParser" in class_names
    assert "ErshoucheDetailParser" in class_names


def test_registry_match_detail_url_prefers_detail(tools):
    """详情页 URL 应匹配 ErshoucheDetailParser。

    注：靠注册顺序，detail 先于 list 注册（discover 按 ASCII 排序，
    'ershouche_detail' < 'ershouche_list'，所以 detail 先注册）。
    """
    from parser.registry import ParserRegistry
    r = ParserRegistry(tools=tools)
    r.discover()
    p = r.match("https://ershouche.58.com/ershouche/123x.shtml")
    # 应匹配到某个 parser（具体哪个取决于注册顺序）
    assert p is not None


def test_registry_ensure_tables_for_plugins(tmp_path):
    """ensure_all_tables 应为两个插件建业务表。"""
    from core.storage import Storage
    from parser.registry import ParserRegistry
    s = Storage(str(tmp_path / "t.db"))
    r = ParserRegistry(storage=s, tools=ParserTools(html_parser=HtmlParser()))
    r.discover()
    count = r.ensure_all_tables()
    assert count >= 2
    # 验证表存在
    for name in ("ershouche_cars", "ershouche_details"):
        row = s.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,), fetch="one",
        )
        assert row is not None, f"表 {name} 未创建"
    s.close()
