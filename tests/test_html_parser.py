"""html_parser 模块测试 - lxml 封装的 XPath/CSS/文本提取。"""
from __future__ import annotations

import pytest

from parser.tools.html_parser import HtmlParser


@pytest.fixture
def parser():
    return HtmlParser()


@pytest.fixture
def sample_html():
    return """
    <html>
      <body>
        <ul class="car-list">
          <li class="item">
            <a href="/car/123" class="title">本田雅阁</a>
            <span class="price">5.8万</span>
          </li>
          <li class="item">
            <a href="/car/456" class="title">丰田凯美瑞</a>
            <span class="price">6.2万</span>
          </li>
        </ul>
        <div class="empty"></div>
      </body>
    </html>
    """


# ---------------- parse ----------------


def test_parse_returns_element(parser, sample_html):
    tree = parser.parse(sample_html)
    assert tree is not None
    assert tree.tag == "html"


def test_parse_bytes(parser, sample_html):
    tree = parser.parse(sample_html.encode("utf-8"))
    assert tree.tag == "html"


def test_parse_malformed_html_does_not_crash(parser):
    """破损 HTML 不应抛异常。"""
    tree = parser.parse("<html><body><div>unclosed")
    assert tree is not None


def test_parse_with_base_url(parser):
    html = '<a href="/car/123">link</a>'
    tree = parser.parse(html, base_url="https://58.com")
    links = parser.xpath(tree, "//a/@href")
    assert links == ["https://58.com/car/123"]


# ---------------- xpath ----------------


def test_xpath_returns_nodes(parser, sample_html):
    tree = parser.parse(sample_html)
    items = parser.xpath(tree, '//li[@class="item"]')
    assert len(items) == 2


def test_xpath_returns_strings(parser, sample_html):
    tree = parser.parse(sample_html)
    titles = parser.xpath(tree, '//a[@class="title"]/text()')
    assert "本田雅阁" in titles
    assert "丰田凯美瑞" in titles


def test_xpath_no_match_returns_empty(parser, sample_html):
    tree = parser.parse(sample_html)
    assert parser.xpath(tree, "//nonexistent") == []


def test_xpath_invalid_expr_returns_empty(parser, sample_html):
    tree = parser.parse(sample_html)
    assert parser.xpath(tree, "///[invalid") == []


# ---------------- cssselect ----------------


def test_cssselect_returns_nodes(parser, sample_html):
    tree = parser.parse(sample_html)
    items = parser.cssselect(tree, "li.item")
    assert len(items) == 2


def test_cssselect_no_match_returns_empty(parser, sample_html):
    tree = parser.parse(sample_html)
    assert parser.cssselect(tree, "div.nonexistent") == []


# ---------------- text / attr ----------------


def test_text_extracts_and_cleans(parser, sample_html):
    tree = parser.parse(sample_html)
    item = parser.xpath(tree, '//li[@class="item"]')[0]
    text = parser.text(item)
    # 多空白应被压缩为单空格
    assert "  " not in text
    assert "本田雅阁" in text


def test_text_none_returns_empty(parser):
    assert parser.text(None) == ""


def test_text_string_input(parser):
    assert parser.text("  hello   world  ") == "hello world"


def test_attr_extracts_value(parser, sample_html):
    tree = parser.parse(sample_html)
    link = parser.xpath(tree, "//a")[0]
    assert parser.attr(link, "href") == "/car/123"


def test_attr_missing_returns_empty(parser, sample_html):
    tree = parser.parse(sample_html)
    link = parser.xpath(tree, "//a")[0]
    assert parser.attr(link, "nonexistent") == ""


def test_attr_none_returns_empty(parser):
    assert parser.attr(None, "href") == ""


# ---------------- 批量提取 ----------------


def test_extract_text_list_xpath(parser, sample_html):
    tree = parser.parse(sample_html)
    titles = parser.extract_text_list(tree, '//a[@class="title"]')
    assert titles == ["本田雅阁", "丰田凯美瑞"]


def test_extract_text_list_css(parser, sample_html):
    tree = parser.parse(sample_html)
    prices = parser.extract_text_list(tree, "span.price", use_css=True)
    assert prices == ["5.8万", "6.2万"]


def test_extract_attr_list_xpath(parser, sample_html):
    tree = parser.parse(sample_html)
    hrefs = parser.extract_attr_list(tree, '//a[@class="title"]', "href")
    assert hrefs == ["/car/123", "/car/456"]


def test_extract_attr_list_css(parser, sample_html):
    tree = parser.parse(sample_html)
    hrefs = parser.extract_attr_list(tree, "a.title", "href", use_css=True)
    assert hrefs == ["/car/123", "/car/456"]


# ---------------- 便捷方法 ----------------


def test_parse_and_extract(parser, sample_html):
    items = parser.parse_and_extract(sample_html, '//li[@class="item"]')
    assert len(items) == 2


def test_parse_and_extract_text(parser, sample_html):
    titles = parser.parse_and_extract_text(sample_html, '//a[@class="title"]')
    assert titles == ["本田雅阁", "丰田凯美瑞"]


def test_parse_and_extract_text_css(parser, sample_html):
    prices = parser.parse_and_extract_text(
        sample_html, "span.price", use_css=True
    )
    assert prices == ["5.8万", "6.2万"]


# ---------------- 中文支持 ----------------


def test_chinese_text_extraction(parser):
    html = '<div class="content">中文测试 内容</div>'
    tree = parser.parse(html)
    assert parser.text(parser.xpath(tree, "//div")[0]) == "中文测试 内容"
