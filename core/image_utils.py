"""图片工具库 — 下载 / 压缩 / 合并宫格 / 编码。

全同步实现，既可用于 workflow 同步执行，也可用于后台线程。

去重缓存结构（与 ``ImageDownloader`` 一致）::

    data/images/
        .url_{url_md5}          # URL→内容映射标记文件
        {sha256[:16]}.{ext}     # 内容文件（不同 URL 同内容只存一份）

用法::

    from core.image_utils import download_sync, compress, merge_grid, image_to_base64

    path = download_sync("https://pic.58.com/xxx.jpg")
    data = compress(path, max_size=1024, quality=75)
    combined = merge_grid([data, data2], max_cols=2)
    b64 = image_to_base64(combined)
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from config import IMAGES_DIR
from core.logger import get_logger

logger = get_logger("core.image_utils")

# ═══════════════════════════════════════════════════════════════════
# 默认参数
# ═══════════════════════════════════════════════════════════════════

DEFAULT_MAX_SIZE = 1024           # 压缩后单边最大像素
DEFAULT_QUALITY = 75              # JPEG 压缩质量 1-100
DEFAULT_MAX_COLS = 3              # 宫格最大列数
DEFAULT_CELL_SIZE = 1024          # 宫格单元格边长
DEFAULT_DOWNLOAD_TIMEOUT = 15     # 下载超时秒数


# ═══════════════════════════════════════════════════════════════════
# 下载
# ═══════════════════════════════════════════════════════════════════

def download_sync(
    url: str,
    save_dir: str | Path = IMAGES_DIR,
    timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
) -> str | None:
    """同步下载单张图片，带 URL + 内容两级去重缓存。

    :param url: 图片 URL
    :param save_dir: 保存目录
    :param timeout: 下载超时秒数
    :returns: 图片本地绝对路径，失败返回 None
    """
    if not url or not url.startswith(("http://", "https://")):
        logger.warning(f"无效图片 URL: {url}")
        return None

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    url_md5 = hashlib.md5(url.encode("utf-8")).hexdigest()
    url_marker = save_dir / f".url_{url_md5}"

    # ── 1. URL 级别缓存检查 ──
    if url_marker.exists():
        try:
            rel_path = url_marker.read_text().strip()
            cached = save_dir / rel_path
            if cached.exists() and cached.stat().st_size > 0:
                logger.debug(f"图片 URL 缓存命中: {url[:100]}")
                return str(cached)
            # 标记文件指向的文件丢失 → 清除脏标记
            url_marker.unlink(missing_ok=True)
        except Exception:
            url_marker.unlink(missing_ok=True)

    # ── 2. 下载 ──
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"图片下载失败 {url[:120]}: {e}")
        return None

    content = resp.content
    if not content:
        logger.warning(f"图片内容为空: {url[:120]}")
        return None

    content_type = resp.headers.get("content-type", "")

    # ── 3. 内容哈希 + 扩展名 ──
    ext = _ext_for(url, content_type)
    content_hash = hashlib.sha256(content).hexdigest()[:16]
    content_rel = f"{content_hash}.{ext}"
    content_abs = save_dir / content_rel

    # ── 4. 内容级别去重 ──
    if content_abs.exists() and content_abs.stat().st_size > 0:
        logger.debug(f"内容重复（不同 URL），跳过写入: {url[:100]}")
    else:
        content_abs.write_bytes(content)
        logger.debug(f"图片已缓存: {content_rel} ({len(content)} bytes) ← {url[:100]}")

    # ── 5. 写入 URL→内容 映射 ──
    url_marker.write_text(content_rel)
    return str(content_abs)


def _ext_for(url: str, content_type: str = "") -> str:
    """从 content-type 或 URL 推断文件扩展名。"""
    ct = content_type.lower()
    if "jpeg" in ct or "jpg" in ct:
        return "jpg"
    if "png" in ct:
        return "png"
    if "webp" in ct:
        return "webp"
    if "gif" in ct:
        return "gif"
    try:
        path = urlparse(url).path
        _, ext = os.path.splitext(path)
        if ext:
            return ext[1:].lower() or "jpg"
    except Exception:
        pass
    return "jpg"


# ═══════════════════════════════════════════════════════════════════
# 压缩
# ═══════════════════════════════════════════════════════════════════

def compress(
    source: str | Path | bytes | Image.Image,
    max_size: int = DEFAULT_MAX_SIZE,
    quality: int = DEFAULT_QUALITY,
) -> bytes:
    """压缩图片 — 等比缩放到 max_size 内，转 JPEG 输出。

    :param source: 图片路径 / 字节数据 / PIL Image 对象
    :param max_size: 最大边长（像素），超过等比例缩小，不放大
    :param quality: JPEG 质量 1-100
    :returns: 压缩后的 JPEG 字节数据
    """
    if isinstance(source, Image.Image):
        img = source
    elif isinstance(source, bytes):
        img = Image.open(io.BytesIO(source))
    else:
        img = Image.open(source)

    w, h = img.size
    scale = min(max_size / w, max_size / h, 1.0)
    if scale < 1.0:
        new_size = (int(w * scale), int(h * scale))
        try:
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        except AttributeError:
            img = img.resize(new_size, Image.LANCZOS)  # type: ignore[attr-defined]

    return _to_jpeg_bytes(img, quality)


def _to_jpeg_bytes(img: Image.Image, quality: int = DEFAULT_QUALITY) -> bytes:
    """将 PIL Image 转为 RGB JPEG 字节。处理 RGBA/P/LA 等模式。"""
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)  # type: ignore[arg-type]
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════
# 宫格合并
# ═══════════════════════════════════════════════════════════════════

def merge_grid(
    images: list[str | Path | bytes | Image.Image],
    max_cols: int = DEFAULT_MAX_COLS,
    cell_size: int = DEFAULT_CELL_SIZE,
    quality: int = DEFAULT_QUALITY,
) -> bytes:
    """将多张图片合并为一张宫格图（JPEG 输出）。

    自动计算行列数，每张图等比缩放后居中填入单元格。
    单张图片直接返回压缩后的 JPEG。

    :param images: 图片路径 / 字节数据 / PIL Image 对象列表
    :param max_cols: 最大列数
    :param cell_size: 单元格边长
    :param quality: 输出 JPEG 质量
    :returns: 合并后 JPEG 字节数据
    """
    imgs: list[Image.Image] = []
    meta: list[dict[str, Any]] = []  # 原始尺寸信息
    for src in images:
        try:
            if isinstance(src, Image.Image):
                img = src
            elif isinstance(src, bytes):
                img = Image.open(io.BytesIO(src))
            else:
                img = Image.open(src)
            meta.append({"original_size": img.size, "mode": img.mode})
            imgs.append(img)
        except Exception as e:
            logger.warning(f"无法打开图片用于合并: {e}")
            continue

    n = len(imgs)
    if n == 0:
        raise ValueError("没有可合并的图片")

    # 单张 → 直接压缩返回
    if n == 1:
        return compress(imgs[0], max_size=cell_size, quality=quality)

    # 计算行列数
    cols = min(n, max_cols)
    rows = (n + cols - 1) // cols

    canvas = Image.new("RGB", (cols * cell_size, rows * cell_size), (255, 255, 255))

    for idx, img in enumerate(imgs):
        r, c = divmod(idx, cols)
        x0, y0 = c * cell_size, r * cell_size

        # 等比缩放放入单元格
        w, h = img.size
        scale = min(cell_size / w, cell_size / h)
        new_w, new_h = int(w * scale), int(h * scale)
        try:
            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        except AttributeError:
            img_resized = img.resize((new_w, new_h), Image.LANCZOS)  # type: ignore[attr-defined]

        # 转 RGB
        cell_img = _ensure_rgb(img_resized)

        # 居中放入
        px = x0 + (cell_size - new_w) // 2
        py = y0 + (cell_size - new_h) // 2
        canvas.paste(cell_img, (px, py))

    logger.debug(f"宫格合并: {n} 图 → {cols}x{rows} 网格, canvas={canvas.size}")

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _ensure_rgb(img: Image.Image) -> Image.Image:
    """将任意模式图片转为 RGB。"""
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)  # type: ignore[arg-type]
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


# ═══════════════════════════════════════════════════════════════════
# 编码
# ═══════════════════════════════════════════════════════════════════

def image_to_base64(data: bytes, mime: str = "image/jpeg") -> str:
    """将图片字节数据转为 base64 data URI。

    :param data: 图片字节数据
    :param mime: MIME 类型（默认 image/jpeg）
    :returns: ``data:{mime};base64,{b64}`` 格式字符串
    """
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"
