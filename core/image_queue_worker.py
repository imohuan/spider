"""图片下载队列 Worker — 后台异步消费 image_queue 表。

用法::

    worker = ImageQueueWorker(storage, downloader, poll_sec=5, batch_size=10)
    task = asyncio.create_task(worker.run())
    # ... 爬虫运行期间持久消费 ...
    worker.stop()
    await task
"""
from __future__ import annotations

import asyncio
from core.logger import get_logger

logger = get_logger("image_queue")


class ImageQueueWorker:
    """后台图片下载队列消费者。

    循环从 ``image_queue`` 表中拉取 pending 图片，通过 ImageDownloader 下载，
    成功标记 done，失败按 max_retry 重试（retry < max → 重回 pending）。

    并发控制：``config`` 中的 ``image_download_poll_sec`` / ``image_download_batch``
    决定轮询间隔和批量拉取数，``download_one()`` 内部走 ImageDownloader 的信号量限流。
    """

    def __init__(
        self,
        storage,
        downloader,
        config,
    ) -> None:
        self.storage = storage
        self.downloader = downloader
        self.config = config
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def poll_sec(self) -> float:
        return self.config.get_float("image_download_poll_sec", default=5.0)

    @property
    def batch_size(self) -> int:
        return self.config.get_int("image_download_batch", default=10)

    async def run(self) -> None:
        """启动消费循环（阻塞，用 asyncio.create_task 包装）。"""
        self._running = True
        logger.info(
            "图片队列 Worker 启动 poll=%.1fs batch=%d", self.poll_sec, self.batch_size
        )
        while self._running:
            try:
                await self._poll()
            except Exception as e:
                logger.error(f"图片队列轮询异常: {e}", exc_info=True)
            await asyncio.sleep(self.poll_sec)

    async def _poll(self) -> None:
        """一轮消费：拉取 pending → 下载 → 标记。"""
        items = self.storage.acquire_pending_images(self.batch_size)
        if not items:
            return
        logger.debug(f"处理 {len(items)} 张待下载图片")
        tasks = [self._download_one(it) for it in items]
        await asyncio.gather(*tasks)

    async def _download_one(self, item: dict) -> None:
        try:
            path = await self.downloader.download_one(item["url"])
            if path:
                self.storage.mark_image_done(item["id"], path)
            else:
                new_status = self.storage.mark_image_failed(
                    item["id"], "download_one 返回 None"
                )
                logger.debug(
                    f"图片下载失败 id={item['id']} status={new_status} "
                    f"retry={item['retry_count'] + 1}/{item['max_retry']}"
                )
        except Exception as e:
            new_status = self.storage.mark_image_failed(item["id"], str(e))
            logger.debug(
                f"图片下载异常 id={item['id']} status={new_status}: {e}"
            )

    def stop(self) -> None:
        """停止消费循环。"""
        self._running = False
        logger.info("图片队列 Worker 已停止")
