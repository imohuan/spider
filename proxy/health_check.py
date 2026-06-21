"""代理健康检查模块 - 定期扫描 proxy_pool，清理失效/过期 IP。

设计文档 4.3 健康检查逻辑封装为 ``HealthChecker`` 类，独立于 ``ProxyPool``
（``ProxyPool.health_check`` 方法做 DB 清理，``HealthChecker`` 做主动探测）。

主动探测：从池中取 idle IP，用 httpx 通过代理请求测试 URL，
- 成功 → 保持 idle，记录延迟
- 失败 → fail_count+1，连续失败≥3 → dead

测试 URL 默认 ``https://httpbin.org/ip``，可配置。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.storage import Storage
from proxy.pool import STATUS_DEAD, STATUS_IDLE

logger = get_logger("proxy.health_check")

DEFAULT_TEST_URL = "https://httpbin.org/ip"
DEFAULT_TIMEOUT = 10


class HealthChecker:
    """主动探测代理 IP 可用性。

    典型用法::

        checker = HealthChecker(storage, config)
        result = checker.check_all(max_check=50)
    """

    def __init__(
        self,
        storage: Storage,
        config: ConfigManager,
        test_url: str = DEFAULT_TEST_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.storage = storage
        self.config = config
        self.test_url = test_url
        self.timeout = timeout

    def check_one(self, proxy_ip: str, proxy_port: int, protocol: str = "http") -> tuple[bool, int]:
        """探测单个代理可用性。

        :return: (是否可用, 延迟毫秒)。不可用时延迟为 0。
        """
        proxy_url = f"{protocol}://{proxy_ip}:{proxy_port}"
        start = time.monotonic()
        try:
            with httpx.Client(proxy=proxy_url, timeout=self.timeout) as client:
                resp = client.get(self.test_url)
                ok = resp.status_code == 200
        except Exception:
            return False, 0
        latency_ms = int((time.monotonic() - start) * 1000)
        return ok, latency_ms

    def check_all(self, max_check: int = 50) -> dict[str, int]:
        """扫描池中所有 idle IP，探测可用性。

        :param max_check: 单次最多检查多少个（避免阻塞过久）
        :return: {"ok": N, "fail": N, "total": N}
        """
        rows = self.storage.execute(
            "SELECT id, ip, port, protocol FROM proxy_pool "
            "WHERE status = ? LIMIT ?",
            (STATUS_IDLE, max_check),
            fetch="all",
        )
        result = {"ok": 0, "fail": 0, "total": 0}
        if not rows:
            return result
        result["total"] = len(rows)
        for row in rows:
            pid, ip, port, protocol = row[0], row[1], row[2], row[3]
            ok, latency = self.check_one(ip, port, protocol or "http")
            if ok:
                result["ok"] += 1
                logger.debug(f"IP {ip}:{port} OK, latency={latency}ms")
            else:
                result["fail"] += 1
                self._mark_fail(pid)
                logger.debug(f"IP {ip}:{port} 探测失败，fail_count+1")
        logger.info(
            f"health_check 完成: ok={result['ok']} fail={result['fail']} "
            f"total={result['total']}"
        )
        return result

    def _mark_fail(self, proxy_id: int) -> None:
        """单个 IP 探测失败：fail_count+1，连续≥3 则 dead。"""
        with self.storage.get_connection() as conn:
            row = conn.execute(
                "SELECT fail_count FROM proxy_pool WHERE id = ?",
                (proxy_id,),
            ).fetchone()
            if row is None:
                return
            new_fail = row[0] + 1
            new_status = STATUS_DEAD if new_fail >= 3 else STATUS_IDLE
            conn.execute(
                "UPDATE proxy_pool SET fail_count = ?, status = ? WHERE id = ?",
                (new_fail, new_status, proxy_id),
            )
