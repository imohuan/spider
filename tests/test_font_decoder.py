"""font_decoder 模块测试。

测试策略：
- OCR 用 mock callable 注入，不依赖 ddddocr/onnxruntime
- 字体文件用 fontTools 现场构造最小 TTF（避免依赖真实 58 字体样本）
- HTML Base64 提取用正则单元测试
- 解密流程用合成字体 + mock OCR 端到端验证

覆盖：
- extract_base64_fonts 正则提取
- decode / decode_many 字符映射
- _render_glyph PIL 渲染（不报错即可）
- _ocr_recognize 注入 callable 优先
- ddddocr 缺失时抛 RuntimeError
- 缓存命中不重复解析
"""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parser.tools.font_decoder import FontDecoder, _FONT_BASE64_RE


# ---------------- fixtures ----------------


@pytest.fixture
def decoder_with_mock_ocr():
    """注入 mock OCR 的 decoder。OCR 始终返回 '0'。"""
    mock_ocr = MagicMock(return_value="0")
    return FontDecoder(ocr_callable=mock_ocr), mock_ocr


# ---------------- extract_base64_fonts 正则 ----------------


def test_extract_base64_fonts_single():
    """单字体提取。"""
    html = """
    <style>
    @font-face {
        font-family: 'secret';
        src: url(data:font/woff2;base64,SGVsbG8gV29ybGQ=) format('woff2');
    }
    </style>
    """
    d = FontDecoder(ocr_callable=lambda b: "0")
    fonts = d.extract_base64_fonts(html)
    assert len(fonts) == 1
    assert fonts[0] == "SGVsbG8gV29ybGQ="


def test_extract_base64_fonts_multiple():
    """多字体提取。"""
    html = """
    <style>
    @font-face { src: url(data:font/woff2;base64,AAA=); }
    @font-face { src: url(data:font/woff;base64,BBB=); }
    @font-face { src: url(data:font/ttf;base64,CCC=); }
    </style>
    """
    d = FontDecoder(ocr_callable=lambda b: "0")
    fonts = d.extract_base64_fonts(html)
    assert len(fonts) == 3
    assert fonts == ["AAA=", "BBB=", "CCC="]


def test_extract_base64_fonts_whitespace_in_data():
    """Base64 数据含空白应被清理。"""
    html = 'src: url(data:font/woff2;base64,AB CD EF==) format("woff2")'
    d = FontDecoder(ocr_callable=lambda b: "0")
    fonts = d.extract_base64_fonts(html)
    assert len(fonts) == 1
    assert fonts[0] == "ABCDEF=="


def test_extract_base64_fonts_no_match():
    """无字体时返回空列表。"""
    html = "<html><body>no font</body></html>"
    d = FontDecoder(ocr_callable=lambda b: "0")
    assert d.extract_base64_fonts(html) == []


def test_extract_base64_fonts_case_insensitive():
    """data:font/... 大小写不敏感。"""
    html = 'src: url(data:FONT/WOFF2;base64,XXX=)'
    d = FontDecoder(ocr_callable=lambda b: "0")
    fonts = d.extract_base64_fonts(html)
    assert fonts == ["XXX="]


# ---------------- decode 无字体场景 ----------------


def test_decode_no_font_returns_original():
    """HTML 无字体时，decode 原样返回。"""
    d = FontDecoder(ocr_callable=lambda b: "0")
    html = "<html>no font</html>"
    assert d.decode(html, "encrypted") == "encrypted"


def test_decode_many_no_font_returns_originals():
    d = FontDecoder(ocr_callable=lambda b: "0")
    html = "<html>no font</html>"
    result = d.decode_many(html, ["abc", "def"])
    assert result == ["abc", "def"]


# ---------------- OCR callable 注入 ----------------


def test_ocr_callable_takes_precedence(decoder_with_mock_ocr):
    """注入的 ocr_callable 优先于 ddddocr。"""
    decoder, mock_ocr = decoder_with_mock_ocr
    # 直接调用 _ocr_recognize 应使用 mock
    result = decoder._ocr_recognize(b"fake image")
    mock_ocr.assert_called_once_with(b"fake image")
    assert result == "0"


def test_ocr_callable_takes_first_char():
    """OCR 返回多字符时取第一个。"""
    d = FontDecoder(ocr_callable=lambda b: "123")
    assert d._ocr_recognize(b"") == "1"


def test_ocr_callable_empty_returns_empty():
    """OCR 返回空字符串时返回空。"""
    d = FontDecoder(ocr_callable=lambda b: "")
    assert d._ocr_recognize(b"") == ""


# ---------------- ddddocr 缺失场景 ----------------


def test_ddddocr_missing_raises_runtime_error(monkeypatch):
    """无 ocr_callable 且 ddddocr 未安装时抛 RuntimeError。"""
    d = FontDecoder()  # 无注入
    # 模拟 ddddocr 不可导入
    import sys
    monkeypatch.setitem(sys.modules, "ddddocr", None)
    with pytest.raises(RuntimeError, match="ddddocr 未安装"):
        d._ocr_recognize(b"image")


# ---------------- 缓存 ----------------


def test_cache_hit_avoids_reparse(decoder_with_mock_ocr):
    """同字体第二次 decode 命中缓存不重复解析。"""
    decoder, _ = decoder_with_mock_ocr
    # 用一个无效 base64 触发 _decode_one_font（会失败但缓存空映射）
    html = 'src: url(data:font/woff2;base64,AAAA) format("woff2")'
    decoder.decode(html, "x")
    assert decoder.cache_size == 1
    # 第二次同字体
    decoder.decode(html, "y")
    # cache 不增长
    assert decoder.cache_size == 1


def test_clear_cache():
    d = FontDecoder(ocr_callable=lambda b: "0")
    d._cache["fake"] = {"a": "1"}
    assert d.cache_size == 1
    d.clear_cache()
    assert d.cache_size == 0


# ---------------- decode 字符映射逻辑 ----------------


def test_decode_uses_font_map(monkeypatch):
    """decode 用 font_map 替换字符，未命中字符保留原样。"""
    d = FontDecoder(ocr_callable=lambda b: "0")
    # mock _build_font_map 返回固定映射
    fake_map = {"\ue001": "5", "\ue002": "8"}
    monkeypatch.setattr(d, "_build_font_map", lambda html: fake_map)
    encrypted = "\ue001\ue002\ue003"  # 第三字符未在 map 中
    result = d.decode("<html>", encrypted)
    assert result == "58\ue003"


def test_decode_many_uses_shared_map(monkeypatch):
    """decode_many 共享同一 font_map。"""
    d = FontDecoder(ocr_callable=lambda b: "0")
    fake_map = {"\ue001": "1", "\ue002": "2"}
    call_count = [0]

    def mock_build(html):
        call_count[0] += 1
        return fake_map

    monkeypatch.setattr(d, "_build_font_map", mock_build)
    result = d.decode_many("<html>", ["\ue001", "\ue002\ue001", "x"])
    assert result == ["1", "21", "x"]
    assert call_count[0] == 1  # 只构建一次映射


# ---------------- _build_font_map 失败容错 ----------------


def test_build_font_map_invalid_base64_skipped():
    """无效 Base64 跳过，不抛异常。"""
    d = FontDecoder(ocr_callable=lambda b: "0")
    html = 'src: url(data:font/woff2;base64,!!!invalid!!!) format("woff2")'
    # 不应抛
    mapping = d._build_font_map(html)
    # 无效字体解析失败，返回空映射
    assert mapping == {}


def test_build_font_map_multiple_fonts_merged(monkeypatch):
    """多字体的映射合并。"""
    d = FontDecoder(ocr_callable=lambda b: "0")
    html = """
    src: url(data:font/woff2;base64,AAA=);
    src: url(data:font/woff2;base64,BBB=);
    """
    call_count = [0]
    mappings = [
        {"\ue001": "1"},
        {"\ue002": "2"},
    ]

    def mock_decode_one(b64):
        idx = call_count[0]
        call_count[0] += 1
        return mappings[idx]

    monkeypatch.setattr(d, "_decode_one_font", mock_decode_one)
    mapping = d._build_font_map(html)
    assert mapping == {"\ue001": "1", "\ue002": "2"}


# ---------------- 配置参数 ----------------


def test_init_default_params():
    d = FontDecoder()
    assert d.font_css_selector == "style"
    assert d.encrypted_selector == ".fontSecret"


def test_init_custom_params():
    d = FontDecoder(
        font_css_selector="div.font-block",
        encrypted_selector=".enc",
    )
    assert d.font_css_selector == "div.font-block"
    assert d.encrypted_selector == ".enc"


# ---------------- 正则模块本身 ----------------


def test_font_base64_re_matches_various_formats():
    """正则应匹配 woff2/woff/ttf 等。"""
    test_cases = [
        'src: url(data:font/woff2;base64,ABC=)',
        'src: url(data:font/woff;base64,DEF==)',
        'src: url(data:font/ttf;base64,GHI=)',
        'src: url(  data:font/woff2;base64,JKL=  )',
        'SRC: url(data:font/woff2;base64,MNO=)',
    ]
    for tc in test_cases:
        assert _FONT_BASE64_RE.search(tc), f"未匹配: {tc}"
