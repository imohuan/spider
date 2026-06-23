"""image_utils 测试脚本 — 使用 ``data/images/`` 真实图片验证下载/压缩/合并。

运行方式::

    python tests/test_image_utils.py           # 完整测试
    python tests/test_image_utils.py --quick   # 仅随机 2 张
    python tests/test_image_utils.py --info    # 仅打印图片信息（不合并）

测试输出保存至 ``data/images/_test_output/`` 目录。
"""
from __future__ import annotations

import io
import os
import random
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PIL import Image

from config import IMAGES_DIR
from core.image_utils import (
    DEFAULT_MAX_SIZE,
    DEFAULT_QUALITY,
    DEFAULT_MAX_COLS,
    download_sync,   # noqa: F401 — 下载功能，本地测试用
    compress,
    merge_grid,
    image_to_base64,
)

_SEP = "─" * 72
_THIN = "─" * 48
_OUTPUT_DIR = Path(IMAGES_DIR) / "_test_output"


def banner(title: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")


def section(title: str) -> None:
    print(f"\n{_SEP}")
    print(f"  {title}")
    print(f"{_THIN}")


def main() -> None:
    args = set(sys.argv[1:])
    quick = "--quick" in args
    info_only = "--info" in args

    # ── 0. 扫描 data/images/ 找出真实图片 ──
    img_dir = Path(IMAGES_DIR)
    all_images = sorted(
        p for p in img_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")
        and not p.name.startswith(".")       # 排除 .url_* 标记文件
    )

    if len(all_images) < 2:
        print(f"[FAIL] data/images/ 中图片不足（需要至少 2 张，实际 {len(all_images)}）")
        print("   至少放 2 张 .jpg/.png/.webp 图片到 data/images/ 再运行测试")
        sys.exit(1)

    # 随机选 N 张（无放回）
    n = min(len(all_images), 2 if quick else 4)
    selected = random.sample(all_images, n)
    print(f"[dir] 从 {len(all_images)} 张图片中随机选择了 {n} 张")
    for p in selected:
        stat = p.stat()
        print(f"   - {p.name}  ({stat.st_size:,} bytes)")

    if info_only:
        _print_info(selected)
        return

    # ── 1. 压缩测试 ──
    banner(f"压缩测试 — max_size={DEFAULT_MAX_SIZE}, quality={DEFAULT_QUALITY}")
    compressed_list: list[bytes] = []
    total_before = 0
    total_after = 0
    for i, path in enumerate(selected, 1):
        section(f"图片 {i}/{n}: {path.name}")
        stat_before = path.stat().st_size
        img = Image.open(path)
        w, h = img.size
        mode = img.mode

        data = compress(path, max_size=DEFAULT_MAX_SIZE, quality=DEFAULT_QUALITY)
        stat_after = len(data)
        ratio = (1 - stat_after / stat_before) * 100 if stat_before > 0 else 0

        # 重新打开压缩后的图片查看尺寸
        compressed_img = Image.open(io.BytesIO(data))
        cw, ch = compressed_img.size

        print(f"  原始:  {w}x{h}  {mode}  {stat_before:,} bytes")
        print(f"  压缩后: {cw}x{ch}  JPEG  {stat_after:,} bytes")
        print(f"  压缩率: {ratio:.1f}%  {'[OK]' if ratio > 0 else '[WARN] 无损（原图已足够小）'}")

        compressed_list.append(data)
        total_before += stat_before
        total_after += stat_after

    print(f"\n{_THIN}")
    print(f"  合计压缩率: {(1 - total_after / total_before) * 100:.1f}%")
    print(f"  ({total_before:,} → {total_after:,} bytes)")

    # ── 2. base64 编码 ──
    banner("base64 编码")
    for i, data in enumerate(compressed_list, 1):
        b64 = image_to_base64(data)
        print(f"  图片 {i}: 字节 {len(data):,} → base64 {len(b64):,} 字符")
    print(f"  [OK] base64 编码正常")

    # ── 3. 宫格合并测试 ──
    banner(f"宫格合并测试 — max_cols={DEFAULT_MAX_COLS}")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    merged = merge_grid(compressed_list, max_cols=DEFAULT_MAX_COLS)
    merged_img = Image.open(io.BytesIO(merged))
    cols = min(n, DEFAULT_MAX_COLS)
    rows = (n + cols - 1) // cols

    print(f"  输入: {n} 张图片")
    print(f"  网格: {cols}x{rows}")
    print(f"  输出: {merged_img.size[0]}x{merged_img.size[1]}, {len(merged):,} bytes")

    # 保存宫格图
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_path = _OUTPUT_DIR / f"merged_grid_{n}x{cols}_{ts}.jpg"
    merged_path.write_bytes(merged)
    print(f"  [SAVE] 保存: {merged_path}")

    # ── 4. 单图保存（用于对比） ──
    section("保存压缩后的单图")
    for i, data in enumerate(compressed_list, 1):
        out = _OUTPUT_DIR / f"compressed_{i:02d}_{ts}.jpg"
        out.write_bytes(data)
        print(f"  [SAVE] {out}  ({len(data):,} bytes)")

    # ── 5. 不同参数对比 ──
    banner("参数对比 — 不同 quality")
    _compare_quality(selected[0], _OUTPUT_DIR, ts)

    # ── 6. 摘要 ──
    banner("测试摘要")
    print(f"  [OK] 压缩: {n} 张, 平均压缩率 {(1 - total_after / total_before) * 100:.1f}%")
    print(f"  [OK] 合并: {n} 张 → {cols}x{rows} 宫格, {len(merged):,} bytes")
    print(f"  [OK] base64: {n} 张编码正常")
    print(f"  [SAVE] 输出目录: {_OUTPUT_DIR}")
    print(f"  [SAVE] 输出文件数: {n + 1} (压缩单图 + 宫格图)")
    print(f"\n{'=' * 72}")
    print("  全部测试完成 [OK]")
    print(f"{'=' * 72}\n")


def _print_info(paths: list[Path]) -> None:
    """仅打印图片详细信息，不做任何处理。"""
    banner("图片信息")
    for i, p in enumerate(paths, 1):
        section(f"图片 {i}: {p.name}")
        stat = p.stat()
        img = Image.open(p)
        print(f"  路径:     {p}")
        print(f"  尺寸:     {img.size[0]}x{img.size[1]}")
        print(f"  模式:     {img.mode}")
        print(f"  格式:     {img.format}")
        print(f"  文件大小: {stat.st_size:,} bytes")
        # 估算像素数
        mp = (img.size[0] * img.size[1]) / 1_000_000
        print(f"  像素数:   {mp:.2f} MP")


def _compare_quality(path: Path, out_dir: Path, ts: str) -> None:
    """对同一张图用不同 quality 参数压缩，对比效果。"""
    qualities = [30, 50, 75, 95]
    results: list[tuple[int, int]] = []

    print(f"  原图: {path.name}")
    for q in qualities:
        data = compress(path, quality=q, max_size=DEFAULT_MAX_SIZE)
        results.append((q, len(data)))

    # 列对比
    max_bytes = max(r[1] for r in results)
    for q, size in results:
        bar = "#" * int(size / max_bytes * 30)
        print(f"  quality={q:>2}: {size:>8,} bytes  {bar}")

    # 保存对比图
    for q in qualities:
        data = compress(path, quality=q, max_size=DEFAULT_MAX_SIZE)
        out = out_dir / f"quality_{q:02d}_{ts}.jpg"
        out.write_bytes(data)


if __name__ == "__main__":
    main()
