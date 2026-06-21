"""调度层模块 - 任务调度、限速、主循环与优雅退出。

按设计文档 4.8：

- ``RateLimiter``: 全局/单域名/单IP 三级限速 + 随机抖动
- ``Scheduler``: 主循环（取 URL → 匹配 Parser → 委托 RequestPool）
- 优雅退出（SIGINT）：等当前请求完成，状态写回 DB

主循环是同步的，但请求池内的浏览器操作是异步的（Playwright async）。
``Scheduler`` 用 ``asyncio.run`` 在同步循环中跑异步请求池。
"""
from __future__ import annotations

import asyncio
import random
import signal
import threading
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.state_machine import StateMachine
from core.storage import Storage
from parser.registry import ParserRegistry

logger = get_logger("scheduler")


class RateLimiter:
    """三级速率控制：全局并发 / 单域名每秒 / 单IP每分钟 + 随机抖动。

    线程安全（``threading.Lock`` 保护计数器）。
    """

    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self._lock = threading.Lock()
        # 全局并发计数
        self._active_count = 0
        self._concurrency_cv = threading.Condition(self._lock)
        # 单域名：{domain: [timestamp_list]} 滑动窗口
        self._domain_requests: dict[str, list[float]] = defaultdict(list)
        # 单 IP：{ip: [timestamp_list]} 滑动窗口（1 分钟）
        self._ip_requests: dict[str, list[float]] = defaultdict(list)
        # 上次全局请求时间（用于最小间隔）
        self._last_global_request = 0.0

    @property
    def concurrency(self) -> int:
        return self.config.get_int("request_concurrency", default=3)

    @property
    def domain_rate_limit(self) -> int:
        """单域名每秒最大请求数。"""
        return self.config.get_int("domain_rate_limit", default=10)

    @property
    def ip_rate_limit(self) -> int:
        """单 IP 每分钟最大请求数。"""
        return self.config.get_int("ip_rate_limit", default=5)

    @property
    def interval_min(self) -> float:
        return self.config.get_float("request_interval_min", default=1.0)

    @property
    def interval_max(self) -> float:
        return self.config.get_float("request_interval_max", default=3.0)

    def wait(self, domain: str | None = None, ip: str | None = None) -> None:
        """阻塞直到满足速率限制。

        :param domain: 目标域名（None 跳过域名限制）
        :param ip: 使用的代理 IP（None 跳过 IP 限制）
        """
        # 1. 全局并发槽
        with self._concurrency_cv:
            while self._active_count >= self.concurrency:
                self._concurrency_cv.wait()
            self._active_count += 1

        try:
            # 2. 全局最小间隔 + 随机抖动
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_global_request
                min_interval = self.interval_min
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
                # 随机抖动
                jitter = random.uniform(0, max(0, self.interval_max - self.interval_min))
                if jitter > 0:
                    time.sleep(jitter)
                self._last_global_request = time.monotonic()

            # 3. 单域名速率
            if domain:
                self._wait_domain(domain)

            # 4. 单 IP 速率
            if ip:
                self._wait_ip(ip)
        except Exception:
            # 异常时释放并发槽
            self.release()
            raise

    def release(self) -> None:
        """释放一个全局并发槽。"""
        with self._concurrency_cv:
            self._active_count = max(0, self._active_count - 1)
            self._concurrency_cv.notify()

    def _wait_domain(self, domain: str) -> None:
        """单域名每秒限制（滑动窗口）。"""
        limit = self.domain_rate_limit
        with self._lock:
            now = time.time()
            # 清理 1 秒前的记录
            self._domain_requests[domain] = [
                t for t in self._domain_requests[domain] if now - t < 1.0
            ]
            if len(self._domain_requests[domain]) >= limit:
                # 等到最早记录过期
                wait_time = 1.0 - (now - self._domain_requests[domain][0])
                if wait_time > 0:
                    self._lock.release()
                    try:
                        time.sleep(wait_time)
                    finally:
                        self._lock.acquire()
                    # 重新清理
                    now = time.time()
                    self._domain_requests[domain] = [
                        t for t in self._domain_requests[domain] if now - t < 1.0
                    ]
            self._domain_requests[domain].append(time.time())

    def _wait_ip(self, ip: str) -> None:
        """单 IP 每分钟限制（滑动窗口）。"""
        limit = self.ip_rate_limit
        with self._lock:
            now = time.time()
            self._ip_requests[ip] = [
                t for t in self._ip_requests[ip] if now - t < 60.0
            ]
            if len(self._ip_requests[ip]) >= limit:
                wait_time = 60.0 - (now - self._ip_requests[ip][0])
                if wait_time > 0:
                    self._lock.release()
                    try:
                        time.sleep(wait_time)
                    finally:
                        self._lock.acquire()
                    now = time.time()
                    self._ip_requests[ip] = [
                        t for t in self._ip_requests[ip] if now - t < 60.0
                    ]
            self._ip_requests[ip].append(time.time())

    def stats(self) -> dict[str, Any]:
        """返回当前限速状态。"""
        with self._lock:
            return {
                "active_count": self._active_count,
                "concurrency": self.concurrency,
                "domain_count": len(self._domain_requests),
                "ip_count": len(self._ip_requests),
            }


class Scheduler:
    """爬虫调度器，主循环驱动整个抓取流程。

    依赖注入：
    - ``storage``: 持久层
    - ``config``: 配置管理
    - ``state_machine``: 状态机
    - ``registry``: Parser 注册表
    - ``request_pool``: 请求池（处理单 URL）

    典型用法::

        scheduler = Scheduler(storage, config, state_machine, registry, request_pool)
        scheduler.run()  # 阻塞主循环
    """

    def __init__(
        self,
        storage: Storage,
        config: ConfigManager,
        state_machine: StateMachine,
        registry: ParserRegistry,
        request_pool: Any,  # RequestPool，避免循环 import
    ) -> None:
        self.storage = storage
        self.config = config
        self.state_machine = state_machine
        self.registry = registry
        self.request_pool = request_pool
        self.rate_limiter = RateLimiter(config)
        self._shutdown_event = threading.Event()
        self._paused_event = threading.Event()  # set = 暂停
        self._signal_installed = False

    # ---------------- 优雅退出 ----------------

    def _install_signal_handler(self) -> None:
        """安装 SIGINT/SIGTERM 信号处理器。"""
        if self._signal_installed:
            return
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            self._signal_installed = True
            logger.info("信号处理器已安装（SIGINT/SIGTERM 触发优雅退出）")
        except (ValueError, OSError) as e:
            # 非主线程无法安装信号处理器
            logger.warning(f"无法安装信号处理器（可能非主线程）: {e}")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        logger.info(f"收到信号 {signum}，触发优雅退出")
        self._shutdown_event.set()

    def request_shutdown(self) -> None:
        """请求优雅退出（线程安全）。"""
        self._shutdown_event.set()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    @property
    def status(self) -> str:
        """调度器状态：running / paused / shutting_down / stopped"""
        if self._shutdown_event.is_set():
            return "stopped"
        if self._paused_event.is_set():
            return "paused"
        return "running"

    def start(self) -> None:
        """启动/恢复调度器（取消暂停）。"""
        logger.info("调度器启动/恢复")
        self._paused_event.clear()
        self._shutdown_event.clear()

    def pause(self) -> None:
        """暂停调度器。"""
        logger.info("调度器暂停")
        self._paused_event.set()

    def stop(self) -> None:
        """停止调度器（优雅退出）。"""
        logger.info("调度器停止请求")
        self._paused_event.clear()  # 解除暂停，让循环能进入退出逻辑
        self.request_shutdown()

    # ---------------- 主循环 ----------------

    def run(self, max_tasks: int | None = None) -> dict[str, int]:
        """启动主循环。

        :param max_tasks: 最多处理多少个任务后退出（测试/限量抓取用）。
            ``None`` 表示一直跑到队列空或收到退出信号。
        :return: 统计 {total, success, failed, blocked, skipped}
        """
        self._install_signal_handler()
        logger.info("爬虫启动")
        stats = {
            "total": 0, "success": 0, "failed": 0,
            "blocked": 0, "skipped": 0,
        }

        while not self._shutdown_event.is_set():
            # 暂停检查：阻塞直到恢复或退出
            if self._paused_event.is_set():
                logger.info("调度器已暂停，等待恢复...")
                # 每 1 秒检查一次退出信号
                while self._paused_event.is_set() and not self._shutdown_event.is_set():
                    time.sleep(1)
                if self._shutdown_event.is_set():
                    break
                logger.info("调度器恢复运行")
            # max_tasks 达成立即退出（放在循环开头，避免空队列 continue 跳过）
            if max_tasks is not None and stats["total"] >= max_tasks:
                break

            # 取任务
            task = self.state_machine.acquire()
            if task is None:
                # 队列空，尝试重置冷却到期的 blocked
                reset_count = self.state_machine.reset_blocked_to_pending()
                if reset_count > 0:
                    logger.info(f"重置 {reset_count} 条 blocked URL 重新入队")
                    continue
                # 空队列 + max_tasks=0 应立即退出
                if max_tasks is not None:
                    break
                logger.info("队列空，等待 10 秒")
                # 分段 sleep 以便快速响应退出信号
                for _ in range(10):
                    if self._shutdown_event.is_set():
                        break
                    time.sleep(1)
                continue

            stats["total"] += 1
            queue_id = task["id"]
            url = task["url"]
            parser_name = task.get("parser_name") or ""

            # 匹配 Parser
            parser = self.registry.match(url)
            if parser is None:
                logger.warning(f"无匹配 Parser，跳过: {url}")
                # 确保 queue 是 running 状态才能 mark_skipped
                self.state_machine.mark_skipped(queue_id)
                stats["skipped"] += 1
                if max_tasks and stats["total"] >= max_tasks:
                    break
                continue

            # parser_name 为空时，回写匹配到的 parser 名到 DB
            if not parser_name:
                parser_name = parser.__class__.__name__
                try:
                    self.storage.execute(
                        "UPDATE queue SET parser_name = ? WHERE id = ?",
                        (parser_name, queue_id),
                    )
                except Exception as e:
                    logger.warning(f"回写 parser_name 失败 queue_id={queue_id}: {e}")

            logger.info(
                f"[Scheduler] 取到URL: {url}, parser: {parser.__class__.__name__}"
            )

            # 委托请求池处理
            try:
                result = self.request_pool.process_url(task, parser)
                stats[result] = stats.get(result, 0) + 1
            except Exception as e:
                logger.error(f"process_url 异常: {url} {e}", exc_info=True)
                # 异常时标记 failed
                try:
                    self.state_machine.mark_failed(queue_id, "network", str(e))
                except Exception:
                    pass
                stats["failed"] += 1

            if max_tasks and stats["total"] >= max_tasks:
                logger.info(f"达到 max_tasks={max_tasks}，退出")
                break

        self._graceful_shutdown()
        logger.info(f"爬虫退出，统计: {stats}")
        return stats

    def _graceful_shutdown(self) -> None:
        """优雅退出：等当前请求完成。"""
        logger.info("收到退出信号，等待当前请求完成...")
        # RequestPool 应实现 wait_all()
        if hasattr(self.request_pool, "wait_all"):
            self.request_pool.wait_all()
        logger.info("所有请求完成，退出")

    # ---------------- 入队辅助 ----------------

    def seed(self, urls: list[str], parser_name: str | None = None,
             priority: int = 0, fetch_mode: str | None = None,
             request_config: dict | None = None) -> int:
        """种子 URL 入队。

        :param fetch_mode: 抓取模式 ``"browser"`` / ``"http"``，None 用 config 默认
        :param request_config: 任务级请求参数
        :return: 实际入队数量（去重后）
        """
        count = 0
        for url in urls:
            try:
                # parser_name 未指定时，自动从 registry 匹配
                name = parser_name
                if not name:
                    matched = self.registry.match(url)
                    if matched:
                        name = matched.__class__.__name__
                self.storage.enqueue(
                    url, parser_name=name, priority=priority,
                    fetch_mode=fetch_mode, request_config=request_config,
                )
                count += 1
            except Exception as e:
                logger.warning(f"入队失败 {url}: {e}")
        logger.info(f"种子入队 {count}/{len(urls)} 个 URL")
        return count


def extract_domain(url: str) -> str | None:
    """从 URL 提取域名。"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or None
    except Exception:
        return None
