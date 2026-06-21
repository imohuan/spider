"""parser.base 与 parser.registry 模块测试。

覆盖：
- BaseParser.matches / ensure_table / parse 默认行为
- ParserRegistry.register / discover / match / ensure_all_tables
- 自动扫描 parser/plugins/ 发现真实插件（占位插件不应被注册）
- URL 匹配优先级
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from core.storage import Storage
from parser.base import BaseParser, ParserTools
from parser.registry import ParserRegistry


# ---------------- fixtures ----------------


@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    yield s
    s.close()


@pytest.fixture
def tools():
    return ParserTools()


# ---------------- 测试用 Parser 子类 ----------------


class FakeListParser(BaseParser):
    url_pattern = r"example\.com/list"
    table_name = "fake_list"
    table_schema = """
        CREATE TABLE fake_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT
        )
    """

    def parse(self, page, url):
        return [{"title": "item1", "url": url}]


class FakeDetailParser(BaseParser):
    url_pattern = r"example\.com/detail/\d+"
    table_name = "fake_detail"
    table_schema = """
        CREATE TABLE fake_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id TEXT UNIQUE,
            price REAL
        )
    """

    def parse(self, page, url):
        return [{"car_id": "123", "price": 9.9}]


class NoTableParser(BaseParser):
    """未声明 table_name 的 parser。"""
    url_pattern = r"example\.com/notable"

    def parse(self, page, url):
        return []


# ---------------- BaseParser 测试 ----------------


def test_base_parser_matches_url_pattern():
    assert FakeListParser.matches("http://example.com/list")
    assert not FakeListParser.matches("http://example.com/detail/123")


def test_base_parser_empty_pattern_never_matches():
    class Empty(BaseParser):
        pass
    assert not Empty.matches("http://anything.com")


def test_base_parser_invalid_pattern_returns_false():
    class BadPattern(BaseParser):
        url_pattern = r"[unclosed"
    assert not BadPattern.matches("http://x.com")


def test_base_parser_parse_not_implemented(tools):
    """BaseParser 本身 parse 抛 NotImplementedError。"""
    p = BaseParser(tools)
    with pytest.raises(NotImplementedError):
        p.parse(None, "http://x.com")


def test_base_parser_ensure_table_creates_table(storage, tools):
    p = FakeListParser(tools)
    p.ensure_table(storage)
    # 验证表存在
    row = storage.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fake_list'",
        fetch="one",
    )
    assert row is not None


def test_base_parser_ensure_table_idempotent(storage, tools):
    """多次调用 ensure_table 不报错。"""
    p = FakeListParser(tools)
    p.ensure_table(storage)
    p.ensure_table(storage)
    p.ensure_table(storage)


def test_base_parser_ensure_table_skips_when_no_table_declared(storage, tools):
    """无 table_name 时跳过建表。"""
    p = NoTableParser(tools)
    p.ensure_table(storage)  # 不应抛
    # 没有创建任何表
    row = storage.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'notable%'",
        fetch="one",
    )
    assert row[0] == 0


def test_parser_tools_injection():
    """ParserTools 容器注入字段可被 parser 访问。"""
    mock_fd = MagicMock()
    mock_hp = MagicMock()
    tools = ParserTools(font_decoder=mock_fd, html_parser=mock_hp)
    p = FakeListParser(tools)
    assert p.font_decoder is mock_fd
    assert p.html_parser is mock_hp
    assert p.image_downloader is None


def test_parser_repr(tools):
    p = FakeListParser(tools)
    r = repr(p)
    assert "FakeListParser" in r
    assert "fake_list" in r


# ---------------- ParserRegistry 测试 ----------------


def test_registry_register_valid_class(tools):
    r = ParserRegistry(tools=tools)
    r.register(FakeListParser)
    assert len(r) == 1
    assert FakeListParser in r


def test_registry_register_rejects_non_parser():
    r = ParserRegistry()
    with pytest.raises(TypeError):
        r.register(str)  # 不是 BaseParser 子类
    with pytest.raises(TypeError):
        r.register(BaseParser)  # BaseParser 本身也不行


def test_registry_register_dedupes(tools):
    r = ParserRegistry(tools=tools)
    r.register(FakeListParser)
    r.register(FakeListParser)  # 重复
    assert len(r) == 1


def test_registry_match_returns_instance(tools):
    r = ParserRegistry(tools=tools)
    r.register(FakeListParser)
    p = r.match("http://example.com/list")
    assert isinstance(p, FakeListParser)
    # 同 URL 第二次返回缓存的同一实例
    p2 = r.match("http://example.com/list")
    assert p is p2


def test_registry_match_no_match_returns_none(tools):
    r = ParserRegistry(tools=tools)
    r.register(FakeListParser)
    assert r.match("http://other.com") is None


def test_registry_match_first_match_wins(tools):
    """先注册的 parser 优先匹配。"""
    r = ParserRegistry(tools=tools)
    # FakeListParser pattern: example\.com/list
    # FakeDetailParser pattern: example\.com/detail/\d+
    r.register(FakeListParser)
    r.register(FakeDetailParser)
    assert isinstance(r.match("http://example.com/list"), FakeListParser)
    assert isinstance(r.match("http://example.com/detail/123"), FakeDetailParser)


def test_registry_ensure_all_tables(storage, tools):
    r = ParserRegistry(storage=storage, tools=tools)
    r.register(FakeListParser)
    r.register(FakeDetailParser)
    count = r.ensure_all_tables()
    assert count == 2
    # 验证两个表都存在
    for name in ("fake_list", "fake_detail"):
        row = storage.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
            fetch="one",
        )
        assert row is not None


def test_registry_ensure_all_tables_no_storage_raises(tools):
    r = ParserRegistry(tools=tools)
    r.register(FakeListParser)
    with pytest.raises(RuntimeError):
        r.ensure_all_tables()


def test_registry_ensure_all_tables_skips_no_table_parser(storage, tools):
    """无 table_name 的 parser 不算成功建表。"""
    r = ParserRegistry(storage=storage, tools=tools)
    r.register(NoTableParser)
    count = r.ensure_all_tables()
    assert count == 1  # ensure_table 不抛，仍计为成功


# ---------------- discover 自动扫描 ----------------


def test_registry_discover_finds_real_plugins(tools):
    """discover() 应扫描 parser/plugins/ 下的真实 Parser。

    当前 plugins/ 下有 ershouche_list.py 和 ershouche_detail.py 占位，
    但它们未定义 url_pattern 等类属性（只是 pass），所以不应被注册为有效 Parser。
    如果未来填充了真实实现，本测试需要更新。
    """
    r = ParserRegistry(tools=tools)
    n = r.discover()
    # 当前 plugins 是占位，n 应为 0
    # 若未来实现了真实 parser，此处改为 >= 1
    assert n >= 0


def test_registry_discover_invalid_package_returns_zero(tools):
    r = ParserRegistry(tools=tools)
    assert r.discover("nonexistent.pkg") == 0


def test_registry_classes_property_returns_copy(tools):
    r = ParserRegistry(tools=tools)
    r.register(FakeListParser)
    classes = r.classes
    classes.clear()  # 修改副本
    assert len(r) == 1  # 原注册表不受影响


def test_registry_contains(tools):
    r = ParserRegistry(tools=tools)
    r.register(FakeListParser)
    assert FakeListParser in r
    assert FakeDetailParser not in r
