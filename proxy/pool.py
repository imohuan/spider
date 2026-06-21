"""代理池模块 - 管理代理 IP 生命周期：拉取 → 分配 → 回收 → 健康检查 → 淘汰。

按设计文档 4.3 实现 ``ProxyPool``：

- **生命周期**::

      [补充] 池中可用 IP < 阈值 → 调 provider 拉新 IP → 入池
      [分配] RequestPool 申请 → 取 idle/未过期/use_count<max_use 的 IP → 标记 in_use
      [回收-成功] use_count+1, 未超限→idle, 超限→dead
      [回收-失败] fail_count+1, fail_count>=3→dead, 否则→cooldown(cooldown_until=now+冷却)
      [健康检查] 每 health_interval 秒扫描 → 清理过期/dead IP

- 持久化到 ``proxy_pool`` 表（设计文档 3.5）
- 配置项从 ``ConfigManager`` 读取：proxy_enabled / proxy_fetch_num / proxy_ttl /
  proxy_max_use / proxy_health_interval / captcha_cooldown
- 线程安全：所有写操作经 ``Storage.get_connection`` 事务
- 支持禁用模式（``proxy_enabled=false``）：``acquire`` 返回 ``None``，请求层直连
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.storage import Storage
from proxy.provider import ProxyProvider, ProxyRecord

logger = get_logger("proxy.pool")

# proxy_pool.status 取值
STATUS_IDLE = "idle"
STATUS_IN_USE = "in_use"
STATUS_COOLDOWN = "cooldown"
STATUS_DEAD = "dead"


class ProxyPool:
    """代理 IP 池，管理拉取/分配/回收/淘汰。

    典型用法::

        pool = ProxyPool(storage, config, provider)
        ip = pool.acquire()              # 申请一个可用 IP
        try:
            response = fetch(url, proxy=ip)
            pool.release_success(ip)     # 成功回收
        except NetworkError:
            pool.release_fail(ip)        # 失败回收（带冷却）

    ``proxy_enabled=false`` 时为禁用模式，``acquire`` 返回 ``None``。
    """

    def __init__(
        self,
        storage: Storage,
        config: ConfigManager,
        provider: ProxyProvider | None = None,
    ) -> None:
        self.storage = storage
        self.config = config
        self.provider = provider
        self._lock = threading.Lock()  # 保护 _supplement 后台线程启动标记
        self._supplement_thread: threading.Thread | None = None
        self._supplement_stop = threading.Event()

    # ---------------- 配置读取 ----------------

    @property
    def enabled(self) -> bool:
        return self.config.get_bool("proxy_enabled", default=False)

    @property
    def fetch_num(self) -> int:
        return self.config.get_int("proxy_fetch_num", default=10)

    @property
    def ttl_seconds(self) -> int:
        return self.config.get_int("proxy_ttl", default=60)

    @property
    def max_use(self) -> int:
        return self.config.get_int("proxy_max_use", default=3)

    @property
    def health_interval(self) -> int:
        return self.config.get_int("proxy_health_interval", default=300)

    @property
    def cooldown_seconds(self) -> int:
        """IP 失败后冷却秒数，复用 captcha_cooldown。"""
        return self.config.get_int("captcha_cooldown", default=1800)

    # ---------------- 分配 ----------------

    def acquire(self) -> ProxyRecord | None:
        """申请一个可用 IP，标记为 ``in_use``。

        选取规则：
        - status = idle
        - 未过期（expire_at > now）
        - use_count < max_use

        :return: ``ProxyRecord`` 或 ``None``（池空 / 禁用 / 无可用）
        """
        if not self.enabled:
            logger.debug("proxy_enabled=false，acquire 返回 None（直连模式）")
            return None
        # 触发一次低水位补充（同步，简单实现）
        if self._available_count() < self.fetch_num:
            self._supplement()
        now_iso = _now_iso()
        with self.storage.get_connection() as conn:
            row = conn.execute(
                "SELECT id, ip, port, protocol, city, expire_at, use_count, max_use "
                "FROM proxy_pool "
                "WHERE status = ? AND expire_at > ? AND use_count < max_use "
                "ORDER BY last_used_at NULLS FIRST, fetched_at ASC "
                "LIMIT 1",
                (STATUS_IDLE, now_iso),
            ).fetchone()
            if row is None:
                logger.warning("代理池无可用 IP")
                return None
            conn.execute(
                "UPDATE proxy_pool SET status = ?, last_used_at = ? WHERE id = ?",
                (STATUS_IN_USE, now_iso, row["id"]),
            )
            rec = ProxyRecord(
                id=row["id"],
                ip=row["ip"],
                port=row["port"],
                protocol=row["protocol"],
                city=row["city"],
                expire_at=row["expire_at"],
                use_count=row["use_count"],
                max_use=row["max_use"],
            )
        logger.debug(f"acquire IP: {rec.ip}:{rec.port} (use_count={rec.use_count})")
        return rec

    # ---------------- 回收 ----------------

    def release_success(self, record: ProxyRecord) -> None:
        """成功回收：use_count+1，超限则 dead，否则 idle。"""
        if not self.enabled:
            return
        new_count = record.use_count + 1
        new_status = STATUS_DEAD if new_count >= record.max_use else STATUS_IDLE
        with self.storage.get_connection() as conn:
            cur = conn.execute(
                "UPDATE proxy_pool SET use_count = ?, status = ?, last_used_at = ? "
                "WHERE id = ? AND status = ?",
                (new_count, new_status, _now_iso(),
                 record.id, STATUS_IN_USE),
            )
            if cur.rowcount == 0:
                logger.warning(
                    f"release_success: IP {record.ip} 当前非 in_use，跳过"
                )
                return
        logger.debug(
            f"release_success IP={record.ip} use_count={new_count} → {new_status}"
        )

    def release_fail(self, record: ProxyRecord, cooldown: bool = True) -> None:
        """失败回收：fail_count+1，连续失败>=3 则 dead，否则 cooldown。

        :param cooldown: True 走冷却（默认），False 直接 dead（严重错误）
        """
        if not self.enabled:
            return
        now = datetime.now(timezone.utc)
        cooldown_until = (now + timedelta(seconds=self.cooldown_seconds)).isoformat() \
            if cooldown else None
        with self.storage.get_connection() as conn:
            row = conn.execute(
                "SELECT fail_count FROM proxy_pool WHERE id = ? AND status = ?",
                (record.id, STATUS_IN_USE),
            ).fetchone()
            if row is None:
                logger.warning(
                    f"release_fail: IP {record.ip} 当前非 in_use，跳过"
                )
                return
            new_fail = row["fail_count"] + 1
            if not cooldown or new_fail >= 3:
                new_status = STATUS_DEAD
                conn.execute(
                    "UPDATE proxy_pool SET fail_count = ?, status = ?, "
                    "                last_used_at = ?, cooldown_until = NULL "
                    "WHERE id = ?",
                    (new_fail, new_status, _now_iso(), record.id),
                )
            else:
                new_status = STATUS_COOLDOWN
                conn.execute(
                    "UPDATE proxy_pool SET fail_count = ?, status = ?, "
                    "                last_used_at = ?, cooldown_until = ? "
                    "WHERE id = ?",
                    (new_fail, new_status, _now_iso(), cooldown_until, record.id),
                )
        logger.debug(
            f"release_fail IP={record.ip} fail_count={new_fail} → {new_status}"
        )

    # ---------------- 补充 ----------------

    def _available_count(self) -> int:
        """当前可用（idle + 未过期）IP 数。"""
        now_iso = _now_iso()
        row = self.storage.execute(
            "SELECT COUNT(*) FROM proxy_pool "
            "WHERE status = ? AND expire_at > ?",
            (STATUS_IDLE, now_iso),
            fetch="one",
        )
        return row[0] if row else 0

    def _supplement(self) -> int:
        """调用 provider 拉取新 IP 入池。

        :return: 实际入库的 IP 数
        """
        if self.provider is None:
            logger.debug("无 provider 配置，跳过补充")
            return 0
        try:
            records = self.provider.fetch(num=self.fetch_num, ttl=self.ttl_seconds)
        except Exception as e:
            logger.error(f"provider.fetch 失败: {e}", exc_info=True)
            return 0
        if not records:
            logger.warning("provider 返回空 IP 列表")
            return 0
        inserted = 0
        expire_at = (datetime.now(timezone.utc)
                     + timedelta(seconds=self.ttl_seconds)).isoformat()
        with self.storage.get_connection() as conn:
            for rec in records:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO proxy_pool "
                        "(ip, port, protocol, city, expire_at, use_count, max_use, "
                        " status, fail_count) "
                        "VALUES (?, ?, ?, ?, ?, 0, ?, ?, 0)",
                        (rec.ip, rec.port, rec.protocol or "http",
                         rec.city, expire_at, self.max_use, STATUS_IDLE),
                    )
                    inserted += 1
                except Exception as e:
                    logger.warning(f"插入 IP {rec.ip}:{rec.port} 失败: {e}")
        logger.info(f"补充 {inserted} 个新 IP 入池")
        return inserted

    # ---------------- 健康检查 ----------------

    def health_check(self) -> dict[str, int]:
        """健康检查：清理过期 IP、重置冷却到期 IP、统计 dead 数。

        :return: {"expired": N, "cooldown_recovered": N, "dead_purged": N}
        """
        if not self.enabled:
            return {"expired": 0, "cooldown_recovered": 0, "dead_purged": 0}
        now_iso = _now_iso()
        result = {"expired": 0, "cooldown_recovered": 0, "dead_purged": 0}
        with self.storage.get_connection() as conn:
            # 1. 过期 IP 标记为 dead（不论原状态）
            cur = conn.execute(
                "UPDATE proxy_pool SET status = ? "
                "WHERE status IN (?, ?, ?) AND expire_at <= ?",
                (STATUS_DEAD, STATUS_IDLE, STATUS_IN_USE, STATUS_COOLDOWN, now_iso),
            )
            result["expired"] = cur.rowcount
            # 2. 冷却到期 IP 重置为 idle
            cur = conn.execute(
                "UPDATE proxy_pool SET status = ?, cooldown_until = NULL, "
                "                fail_count = 0 "
                "WHERE status = ? AND cooldown_until IS NOT NULL "
                "  AND cooldown_until <= ?",
                (STATUS_IDLE, STATUS_COOLDOWN, now_iso),
            )
            result["cooldown_recovered"] = cur.rowcount
            # 3. 物理删除长期 dead 的 IP（fail_count>=5）
            cur = conn.execute(
                "DELETE FROM proxy_pool WHERE status = ? AND fail_count >= 5",
                (STATUS_DEAD,),
            )
            result["dead_purged"] = cur.rowcount
        logger.info(
            f"health_check: expired={result['expired']} "
            f"recovered={result['cooldown_recovered']} "
            f"purged={result['dead_purged']}"
        )
        return result

    def start_health_check_loop(self) -> None:
        """启动后台健康检查线程（每 health_interval 秒一次）。"""
        with self._lock:
            if self._supplement_thread is not None:
                logger.warning("健康检查线程已启动")
                return
        interval = self.health_interval

        def _loop():
            while not self._supplement_stop.wait(interval):
                try:
                    self.health_check()
                except Exception as e:
                    logger.error(f"健康检查异常: {e}", exc_info=True)

        t = threading.Thread(target=_loop, daemon=True, name="proxy-health")
        with self._lock:
            self._supplement_thread = t
        t.start()
        logger.info(f"健康检查线程已启动，间隔 {interval}s")

    def stop_health_check_loop(self) -> None:
        """停止后台健康检查线程。"""
        self._supplement_stop.set()
        with self._lock:
            t = self._supplement_thread
            self._supplement_thread = None
        if t is not None:
            t.join(timeout=5)
            logger.info("健康检查线程已停止")

    # ---------------- 统计 ----------------

    def stats(self) -> dict[str, int]:
        """返回池统计: {idle, in_use, cooldown, dead, total}。"""
        rows = self.storage.execute(
            "SELECT status, COUNT(*) FROM proxy_pool GROUP BY status",
            (),
            fetch="all",
        )
        result = {"idle": 0, "in_use": 0, "cooldown": 0, "dead": 0, "total": 0}
        for row in rows or []:
            status = row[0]
            count = row[1]
            if status in result:
                result[status] = count
            result["total"] += count
        return result


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串（与 SQLite CURRENT_TIMESTAMP 对齐用）。"""
    return datetime.now(timezone.utc).isoformat()
