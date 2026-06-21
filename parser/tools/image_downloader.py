"""图片下载模块 - 基于 httpx 异步下载图片资源到本地。

按设计文档 4.4：图片下载由 Parser 声明（``extract_images``），由 image_downloader
批量执行，下载结果路径写入 requests.image_paths。

特性：
- **异步**：``asyncio.gather`` 并发下载，提高吞吐
- **限流**：信号量控制并发数（避免压垮源站）
- **去重**：URL 哈希做文件名，同 URL 不重复下载
- **失败容错**：单个下载失败不影响整批，返回成功路径列表
- **超时**：从 config.request_timeout 读取
- **代理**：支持传入代理（与 RequestPool 共用 IP）

文件命名：``images/{url_md5}.{ext}``
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from config import IMAGES_DIR
from core.logger import get_logger

logger = get_logger("parser.image_downloader")

# 默认并发下载数
_DEFAULT_CONCURRENCY = 5
# 默认超时秒
_DEFAULT_TIMEOUT = 30


class ImageDownloader:
    """异步图片下载器。

    用法::

        downloader = ImageDownloader(IMAGES_DIR, timeout=30, concurrency=5)
        paths = await downloader.download_batch(
            ["https://x.com/a.jpg", "https://x.com/b.jpg"],
            proxy="http://1.2.3.4:8080",
        )
    """

    def __init__(
        self,
        save_dir: str | Path = IMAGES_DIR,
        timeout: int = _DEFAULT_TIMEOUT,
        concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.concurrency = max(1, concurrency)

    async def download_one(
        self,
        url: str,
        proxy: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        """下载单个图片，返回相对 save_dir 的路径。失败返回 None。

        :param url: 图片 URL
        :param proxy: 代理 URL（``http://ip:port``）
        :param client: 复用的 httpx.AsyncClient（批量下载时传入避免重复建连）
        :return: 相对路径（如 ``abc123.jpg``）或 None
        """
        if not url or not url.startswith(("http://", "https://")):
            logger.warning(f"无效图片 URL: {url}")
            return None

        rel_path = self._path_for_url(url)
        abs_path = self.save_dir / rel_path
        # 已下载则跳过
        if abs_path.exists() and abs_path.stat().st_size > 0:
            logger.debug(f"图片已存在，跳过: {url}")
            return rel_path

        own_client = client is None
        if own_client:
            client = self._make_client(proxy)
        try:
            try:
                resp = await client.get(url, timeout=self.timeout)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"下载失败 {url}: {e}")
                return None
            content_type = resp.headers.get("content-type", "")
            ext = self._ext_for(url, content_type)
            # 重新计算路径（ext 可能因 content-type 调整）
            rel_path = self._path_for_url(url, ext)
            abs_path = self.save_dir / rel_path
            abs_path.write_bytes(resp.content)
            logger.debug(f"下载完成: {url} → {rel_path} ({len(resp.content)} bytes)")
            return rel_path
        finally:
            if own_client and client is not None:
                await client.aclose()

    async def download_batch(
        self,
        urls: list[str],
        proxy: str | None = None,
    ) -> list[str]:
        """批量下载，返回成功下载的相对路径列表（保持顺序）。

        用信号量限制并发，单个失败不影响整批。
        """
        if not urls:
            return []
        sem = asyncio.Semaphore(self.concurrency)
        client = self._make_client(proxy)
        results: list[str | None] = [None] * len(urls)

        async def _task(idx: int, url: str) -> None:
            async with sem:
                results[idx] = await self.download_one(url, proxy=proxy, client=client)

        try:
            await asyncio.gather(
                *[_task(i, u) for i, u in enumerate(urls)],
                return_exceptions=False,
            )
        finally:
            await client.aclose()
        # 过滤 None，但保持顺序
        return [r for r in results if r]

    def _make_client(self, proxy: str | None) -> httpx.AsyncClient:
        """创建 httpx 异步客户端。"""
        kwargs: dict[str, Any] = {"follow_redirects": True}
        if proxy:
            kwargs["proxy"] = proxy
        return httpx.AsyncClient(**kwargs)

    def _path_for_url(self, url: str, ext: str | None = None) -> str:
        """根据 URL 计算保存路径（相对 save_dir）。"""
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        if ext is None:
            ext = self._ext_for(url)
        return f"{url_hash}.{ext}"

    @staticmethod
    def _ext_for(url: str, content_type: str = "") -> str:
        """从 URL 或 content-type 推断图片扩展名。"""
        # 优先 content-type
        ct = content_type.lower()
        if "jpeg" in ct or "jpg" in ct:
            return "jpg"
        if "png" in ct:
            return "png"
        if "webp" in ct:
            return "webp"
        if "gif" in ct:
            return "gif"
        # 其次 URL 路径
        try:
            path = urlparse(url).path
            _, ext = os.path.splitext(path)
            if ext:
                return ext[1:].lower() or "jpg"
        except Exception:
            pass
        return "jpg"

    def clear_all(self) -> int:
        """清空保存目录。返回删除的文件数。"""
        count = 0
        for f in self.save_dir.glob("*"):
            if f.is_file():
                try:
                    f.unlink()
                    count += 1
                except Exception as e:
                    logger.warning(f"删除失败 {f}: {e}")
        return count
