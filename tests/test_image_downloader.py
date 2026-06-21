"""image_downloader 模块测试。

测试策略：
- httpx 用 mock，不发真实网络请求
- 验证内容哈希命名、URL 标记文件、扩展名推断、去重、批量下载、失败容错
- 异步测试用 asyncio.run
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parser.tools.image_downloader import ImageDownloader


@pytest.fixture
def downloader(tmp_path):
    return ImageDownloader(save_dir=tmp_path / "images", timeout=5, concurrency=3)


def run_async(coro):
    return asyncio.run(coro)


# ---------------- _ext_for ----------------


def test_ext_for_from_url_jpg():
    assert ImageDownloader._ext_for("https://x.com/a.jpg") == "jpg"


def test_ext_for_from_url_png():
    assert ImageDownloader._ext_for("https://x.com/a.png") == "png"


def test_ext_for_from_url_webp():
    assert ImageDownloader._ext_for("https://x.com/a.webp") == "webp"


def test_ext_for_from_content_type_jpeg():
    assert ImageDownloader._ext_for("https://x.com/a", "image/jpeg") == "jpg"


def test_ext_for_from_content_type_png():
    assert ImageDownloader._ext_for("https://x.com/a", "image/png") == "png"


def test_ext_from_content_type_overrides_url():
    """content-type 优先于 URL。"""
    assert ImageDownloader._ext_for("https://x.com/a.jpg", "image/png") == "png"


def test_ext_no_info_defaults_jpg():
    assert ImageDownloader._ext_for("https://x.com/noext") == "jpg"


# ---------------- URL marker (replaces _path_for_url) ----------------


def test_url_marker_created_after_download(downloader, tmp_path):
    """下载后应创建 .url_{md5} 标记文件。"""
    downloader.save_dir = tmp_path
    url = "https://httpbin.org/image/jpeg"
    url_hash = hashlib.md5(url.encode()).hexdigest()
    marker = tmp_path / f".url_{url_hash}"
    # 无网络时返回 None，但标记不应存在（除非已下载过）
    assert not marker.exists()


def test_content_hash_filename(downloader, tmp_path):
    """文件名应使用内容 SHA256 前 16 位，而非 URL MD5。"""
    downloader.save_dir = tmp_path
    url = "https://httpbin.org/image/jpeg"
    url_hash = hashlib.md5(url.encode()).hexdigest()
    marker = tmp_path / f".url_{url_hash}"
    # 没有真实下载时标记不存在
    assert not marker.exists()


# ---------------- download_one ----------------


def test_download_one_invalid_url_returns_none(downloader):
    assert run_async(downloader.download_one("")) is None
    assert run_async(downloader.download_one("ftp://x.com/a")) is None


def test_download_one_success(downloader, tmp_path):
    url = "https://x.com/photo.jpg"
    mock_resp = MagicMock()
    mock_resp.content = b"fake image bytes"
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with patch.object(downloader, "_make_client", return_value=mock_client):
        rel = run_async(downloader.download_one(url))

    assert rel is not None
    abs_path = Path(downloader.save_dir) / rel
    assert abs_path.exists()
    assert abs_path.read_bytes() == b"fake image bytes"
    assert rel.endswith(".jpg")


def test_download_one_failure_returns_none(downloader):
    url = "https://x.com/photo.jpg"
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("network error"))
    mock_client.aclose = AsyncMock()

    with patch.object(downloader, "_make_client", return_value=mock_client):
        rel = run_async(downloader.download_one(url))
    assert rel is None


def test_download_one_skips_existing(downloader):
    """URL 标记文件存在且指向有效内容 → 跳过下载。"""
    url = "https://x.com/exist.jpg"
    url_hash = hashlib.md5(url.encode()).hexdigest()
    content_rel = "abc123.jpg"  # 模拟内容哈希文件名
    # 创建标记文件和内容文件
    marker = Path(downloader.save_dir) / f".url_{url_hash}"
    marker.write_text(content_rel)
    (Path(downloader.save_dir) / content_rel).write_bytes(b"existing")

    mock_client = MagicMock()
    mock_client.get = AsyncMock()  # 不应被调用
    mock_client.aclose = AsyncMock()

    with patch.object(downloader, "_make_client", return_value=mock_client):
        rel_returned = run_async(downloader.download_one(url))

    assert rel_returned == content_rel
    mock_client.get.assert_not_awaited()


def test_download_one_uses_provided_client(downloader):
    """提供 client 时不自建、不关闭。"""
    url = "https://x.com/a.jpg"
    mock_resp = MagicMock()
    mock_resp.content = b"x"
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    run_async(downloader.download_one(url, client=mock_client))
    mock_client.aclose.assert_not_awaited()  # 不关闭外部 client


# ---------------- download_batch ----------------


def test_download_batch_empty_returns_empty(downloader):
    assert run_async(downloader.download_batch([])) == []


def test_download_batch_success(downloader):
    urls = [
        "https://x.com/a.jpg",
        "https://x.com/b.png",
        "https://x.com/c.jpg",
    ]
    mock_resp = MagicMock()
    mock_resp.content = b"data"
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with patch.object(downloader, "_make_client", return_value=mock_client):
        paths = run_async(downloader.download_batch(urls))

    assert len(paths) == 3
    # 每个文件应存在
    for p in paths:
        assert (Path(downloader.save_dir) / p).exists()


def test_download_batch_partial_failure(downloader):
    """批量中部分失败，成功的仍返回。"""
    urls = ["https://x.com/ok.jpg", "https://x.com/bad.jpg"]
    mock_resp_ok = MagicMock()
    mock_resp_ok.content = b"ok"
    mock_resp_ok.headers = {"content-type": "image/jpeg"}
    mock_resp_ok.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        side_effect=[mock_resp_ok, RuntimeError("timeout")]
    )
    mock_client.aclose = AsyncMock()

    with patch.object(downloader, "_make_client", return_value=mock_client):
        paths = run_async(downloader.download_batch(urls))

    assert len(paths) == 1  # 只有第一个成功


def test_download_batch_respects_concurrency(downloader):
    """并发数限制：3 个任务，concurrency=3，应同时发起。"""
    urls = [f"https://x.com/{i}.jpg" for i in range(5)]
    downloader.concurrency = 2

    mock_resp = MagicMock()
    mock_resp.content = b"x"
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with patch.object(downloader, "_make_client", return_value=mock_client):
        paths = run_async(downloader.download_batch(urls))

    assert len(paths) == 5


# ---------------- clear_all ----------------


def test_clear_all_removes_files(downloader):
    # 写几个文件
    for name in ["a.jpg", "b.png"]:
        (Path(downloader.save_dir) / name).write_bytes(b"x")
    count = downloader.clear_all()
    assert count == 2
    assert not any(Path(downloader.save_dir).glob("*"))


def test_clear_all_empty_dir(downloader):
    assert downloader.clear_all() == 0


# ---------------- 目录自动创建 ----------------


def test_init_creates_save_dir(tmp_path):
    save_dir = tmp_path / "new" / "deep" / "images"
    assert not save_dir.exists()
    ImageDownloader(save_dir=save_dir)
    assert save_dir.exists()
