"""字体解码模块 - 基于 fontTools + PIL + ddddocr 解析 58 动态字体反爬。

按设计文档 4.6 工作流：

1. 从页面 HTML 提取内嵌的 Base64 字体编码（正则）
2. Base64 解码 → 保存临时 .ttf
3. fontTools 解析 cmap → 获取 Unicode→字形映射
4. 对每个加密 Unicode:
   - PIL 生成 120x120 白底黑字图片（文字居中）
   - ddddocr 识别 → 真实数字/字符
   - 构建 {加密字符: 真实字符} 映射表
5. 用映射表解密加密字段

ddddocr 是重依赖（onnxruntime + 模型文件）。本模块：
- ddddocr **延迟 import**，仅在首次 OCR 时加载
- 支持注入自定义 ``ocr_callable``（测试用 mock，生产用真实 ddddocr）
- ddddocr 缺失时抛 ``RuntimeError``，提示安装

可配置（不同频道加密字段不同）::

    decoder = FontDecoder(
        font_css_selector="style",
        encrypted_selector=".fontSecret",
    )
"""
from __future__ import annotations

import base64
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from core.logger import get_logger

logger = get_logger("parser.font_decoder")

# 从 HTML <style> 块提取 Base64 字体的正则
# 匹配 src: url(data:font/woff2;base64,XXXX) 或 @font-face 内的 base64 数据
_FONT_BASE64_RE = re.compile(
    r"src:\s*url\(\s*data:font/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=\s]+)\s*\)",
    re.IGNORECASE,
)

# 默认 OCR 图片尺寸
_OCR_IMAGE_SIZE = 120


class FontDecoder:
    """58 动态字体反爬解码器。

    :param font_css_selector: HTML 中字体 CSS 的选择器（保留参数，本期用正则）
    :param encrypted_selector: 加密文本的 CSS 选择器（Parser 层用）
    :param ocr_callable: 自定义 OCR 函数，签名 ``(image_bytes) -> str``。
        ``None`` 时用 ddddocr（延迟加载）。
    """

    def __init__(
        self,
        font_css_selector: str = "style",
        encrypted_selector: str = ".fontSecret",
        ocr_callable: Callable[[bytes], str] | None = None,
    ) -> None:
        self.font_css_selector = font_css_selector
        self.encrypted_selector = encrypted_selector
        self._ocr_callable = ocr_callable
        self._ocr: Any = None
        # 字体映射缓存：{base64_font_data: {encrypted_char: real_char}}
        self._cache: dict[str, dict[str, str]] = {}

    # ---------------- 公开接口 ----------------

    def decode(self, html: str, encrypted_text: str) -> str:
        """解密文本。

        :param html: 页面 HTML（含内嵌 Base64 字体）
        :param encrypted_text: 加密的文本（如 ".fontSecret" 元素内容）
        :return: 解密后的真实文本
        """
        font_map = self._build_font_map(html)
        if not font_map:
            logger.debug("未提取到字体映射，原样返回")
            return encrypted_text
        return "".join(font_map.get(c, c) for c in encrypted_text)

    def decode_many(
        self, html: str, encrypted_texts: list[str]
    ) -> list[str]:
        """批量解密（共享同一字体映射，避免重复解析）。"""
        font_map = self._build_font_map(html)
        if not font_map:
            return list(encrypted_texts)
        return [
            "".join(font_map.get(c, c) for c in text)
            for text in encrypted_texts
        ]

    def extract_base64_fonts(self, html: str) -> list[str]:
        """从 HTML 提取所有 Base64 字体数据。

        :return: Base64 字符串列表（未解码）
        """
        matches = _FONT_BASE64_RE.findall(html)
        # 清理空白字符
        return [re.sub(r"\s+", "", m) for m in matches]

    # ---------------- 字体映射构建 ----------------

    def _build_font_map(self, html: str) -> dict[str, str]:
        """构建 {加密字符: 真实字符} 映射表。

        多个字体时合并（后解析的覆盖先解析的，符合 58 多字体策略）。
        """
        fonts = self.extract_base64_fonts(html)
        if not fonts:
            return {}
        result: dict[str, str] = {}
        for b64 in fonts:
            if b64 in self._cache:
                result.update(self._cache[b64])
                continue
            try:
                mapping = self._decode_one_font(b64)
                self._cache[b64] = mapping
                result.update(mapping)
            except Exception as e:
                logger.warning(f"解析字体失败: {e}")
                self._cache[b64] = {}
        return result

    def _decode_one_font(self, base64_data: str) -> dict[str, str]:
        """解析单个 Base64 字体，返回 {加密字符: 真实字符}。

        步骤：
        1. Base64 解码 → 临时 .ttf
        2. fontTools 解析 cmap
        3. 对每个 cmap 条目（除标准 ASCII），PIL 渲染 → OCR → 真实字符
        """
        font_bytes = base64.b64decode(base64_data)
        # 写临时文件（fontTools 需要文件路径）
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            f.write(font_bytes)
            tmp_path = Path(f.name)
        try:
            mapping = self._parse_font_file(tmp_path)
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return mapping

    def _parse_font_file(self, font_path: Path) -> dict[str, str]:
        """用 fontTools 解析字体文件，对每个字形 OCR 识别。"""
        from fontTools.ttLib import TTFont

        font = TTFont(str(font_path))
        cmap = font.getBestCmap()
        if not cmap:
            logger.warning("字体无 cmap 表")
            return {}

        mapping: dict[str, str] = {}
        for codepoint, glyph_name in cmap.items():
            # 跳过标准 ASCII（32-127），只处理加密字符
            if 32 <= codepoint <= 127:
                continue
            # 跳过 PUA 区常见的高频空字形
            if not glyph_name or glyph_name == ".notdef":
                continue
            try:
                encrypted_char = chr(codepoint)
                image_bytes = self._render_glyph(font, codepoint)
                real_char = self._ocr_recognize(image_bytes)
                if real_char:
                    mapping[encrypted_char] = real_char
            except Exception as e:
                logger.debug(f"字形 OCR 失败 codepoint={codepoint}: {e}")
        font.close()
        return mapping

    def _render_glyph(self, font: Any, codepoint: int) -> bytes:
        """用 PIL 渲染单个字形为 PNG 图片字节。

        :param font: fontTools TTFont 对象
        :param codepoint: Unicode 码点
        :return: PNG 图片字节
        """
        from PIL import Image, ImageDraw, ImageFont

        char = chr(codepoint)
        # 用 fontTools 导出字体到临时文件供 PIL 加载
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            tmp_font_path = Path(f.name)
        try:
            font.saveXML(str(tmp_font_path) + ".ttx")
            # 直接用原字体文件加载（更可靠）
            # 注：实际生产中 font 已是文件加载的，这里简化用内存
            # 用 PIL 默认字体回退（无法加载真实字形时）
            try:
                pil_font = ImageFont.truetype(
                    getattr(font, "reader", "").fileName
                    if hasattr(font, "reader") and hasattr(font.reader, "fileName")
                    else str(tmp_font_path),
                    size=_OCR_IMAGE_SIZE - 20,
                )
            except Exception:
                pil_font = ImageFont.load_default()

            img = Image.new("L", (_OCR_IMAGE_SIZE, _OCR_IMAGE_SIZE), 255)
            draw = ImageDraw.Draw(img)
            # 居中绘制
            try:
                bbox = draw.textbbox((0, 0), char, font=pil_font)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                x = (_OCR_IMAGE_SIZE - w) // 2 - bbox[0]
                y = (_OCR_IMAGE_SIZE - h) // 2 - bbox[1]
            except Exception:
                x, y = 10, 10
            draw.text((x, y), char, fill=0, font=pil_font)

            from io import BytesIO
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        finally:
            try:
                tmp_font_path.unlink(missing_ok=True)
                (Path(str(tmp_font_path) + ".ttx")).unlink(missing_ok=True)
            except Exception:
                pass

    def _ocr_recognize(self, image_bytes: bytes) -> str:
        """OCR 识别图片中的字符。

        优先用注入的 ocr_callable，否则用 ddddocr（延迟加载）。
        多字符结果取第一个。
        """
        result = self._call_ocr(image_bytes)
        if isinstance(result, str) and result:
            return result[0]
        return ""

    def _call_ocr(self, image_bytes: bytes) -> str:
        """实际调用 OCR（注入 callable 或 ddddocr），返回原始结果。"""
        if self._ocr_callable is not None:
            return self._ocr_callable(image_bytes)
        # 延迟加载 ddddocr
        if self._ocr is None:
            try:
                import ddddocr
                self._ocr = ddddocr.DdddOcr(show_ad=False)
            except ImportError as e:
                raise RuntimeError(
                    "ddddocr 未安装，请 pip install ddddocr "
                    "或注入自定义 ocr_callable"
                ) from e
            except Exception as e:
                raise RuntimeError(f"ddddocr 初始化失败: {e}") from e
        try:
            return self._ocr.classification(image_bytes)
        except Exception as e:
            logger.warning(f"OCR 识别失败: {e}")
            return ""

    # ---------------- 缓存管理 ----------------

    def clear_cache(self) -> None:
        """清空字体映射缓存。"""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)
