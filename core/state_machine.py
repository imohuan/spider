"""状态机模块 - 管理 queue 表状态流转与换IP计数，线程安全。

按设计文档 3.2 与 4.2 实现 ``StateMachine``：

- 状态流转::

      pending → running → done              (成功)
                        → failed            (可重试:网络/5xx/解析失败)
                        → blocked           (不重试:403/验证码,换IP+冷却)
                        → skipped           (已存在且未过期)
      failed  → running                      (重试)
      blocked → pending                      (冷却后重新入队)

- 所有状态变更在单个事务内完成（复用 :meth:`Storage.get_connection`，
  持有 ``RLock`` 直至 COMMIT/ROLLBACK），保证线程安全与原子性。
- ``acquire`` 在同一事务内 ``SELECT … + UPDATE …``，多线程同时调用
  不会取到同一行（``RLock`` 串行化 + 事务内立即修改 status）。
- ``increment_ip_switch`` 超限时自动 :meth:`mark_blocked` 并 ``log.warning``。

典型用法::

    from core.storage import Storage
    from core.config_manager import ConfigManager
    from core.state_machine import StateMachine

    storage = Storage()
    cfg = ConfigManager(storage)
    cfg.init_defaults()
    sm = StateMachine(storage, cfg)

    task = sm.acquire()                 # 取 pending/failed → 标记 running
    if task:
        try:
            ...                          # 业务处理
            sm.mark_done(task['id'])
        except NetworkError as e:
            sm.mark_failed(task['id'], 'network', str(e))
        except CaptchaError:
            exceeded = sm.increment_ip_switch(task['id'])
            if not exceeded:
                ...                      # 换 IP 重试
"""
from __future__ import annotations

from typing import Any

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.storage import Storage

logger = get_logger("state_machine")

# 状态常量（避免散落字符串硬编码）
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"

# 错误类型分类（设计文档 3.2 error_type 列）
ERROR_NETWORK = "network"
ERROR_403 = "403"
ERROR_CAPTCHA = "captcha"
ERROR_404 = "404"
ERROR_5XX = "5xx"
ERROR_PARSE = "parse"
ERROR_IP_SWITCH_LIMIT = "ip_switch_limit"


class StateMachine:
    """queue 表状态机：管理 URL 抓取生命周期，线程安全。

    所有方法均通过 :meth:`Storage.get_connection` 或 :meth:`Storage.execute`
    访问 DB，复用 ``Storage._lock``（``RLock``）保证线程安全。
    """

    def __init__(self, storage: Storage, config: ConfigManager) -> None:
        self.storage = storage
        self.config = config

    # ---------------- 取任务 ----------------

    def acquire(self) -> dict[str, Any] | None:
        """取一个 ``pending`` 或 ``failed`` 状态的 URL，原子标记为 ``running``。

        选取规则（设计文档 4.2）：
        - 按 ``priority`` 降序（数字大优先）
        - 同优先级按 ``created_at`` 升序（先入队先出）
        - 仅取 ``pending`` 或 ``failed`` 两种状态
        - ``failed`` 任务 ``retry_count >= queue_max_retry`` 时不再取
        - 若 running 任务数已达 ``crawler_max_running``，返回 None

        原子性保证：``SELECT + UPDATE`` 在同一事务内执行
        （:meth:`Storage.get_connection` 持锁直至 COMMIT），
        多线程同时调用不会取到同一行。

        :return: 任务字典 ``{id, url, url_hash, parser_name, retry_count,
                  ip_switch_count, priority, fetch_mode, request_config}``，队列空或达上限返回 ``None``
        """
        max_retry = self.config.get_int("queue_max_retry", default=3)
        max_running = self.config.get_int("crawler_max_running", default=3)
        with self.storage.get_connection() as conn:
            # 检查并发上限
            running_count = conn.execute(
                "SELECT COUNT(*) FROM queue WHERE status = ?",
                (STATUS_RUNNING,),
            ).fetchone()[0]
            if running_count >= max_running:
                logger.debug(
                    f"acquire 达并发上限 running={running_count}/{max_running}"
                )
                return None

            row = conn.execute(
                "SELECT id, url, url_hash, parser_name, retry_count, "
                "       ip_switch_count, priority, fetch_mode, request_config "
                "FROM queue "
                "WHERE status IN (?, ?) "
                "  AND (status != ? OR retry_count < ?) "
                "ORDER BY priority DESC, created_at ASC "
                "LIMIT 1",
                (STATUS_PENDING, STATUS_FAILED, STATUS_FAILED, max_retry),
            ).fetchone()
            if row is None:
                return None
            queue_id = row["id"]
            # 同事务内立即标记为 running，记录 started_at
            conn.execute(
                "UPDATE queue SET status = ?, started_at = CURRENT_TIMESTAMP, "
                "                finished_at = NULL, error_msg = NULL, error_type = NULL "
                "WHERE id = ?",
                (STATUS_RUNNING, queue_id),
            )
            logger.debug(f"acquire queue_id={queue_id} → running")
            return {
                "id": row["id"],
                "url": row["url"],
                "url_hash": row["url_hash"],
                "parser_name": row["parser_name"],
                "retry_count": row["retry_count"],
                "ip_switch_count": row["ip_switch_count"],
                "priority": row["priority"],
                "fetch_mode": row["fetch_mode"],
                "request_config": row["request_config"],
            }

    # ---------------- 状态变更 ----------------

    def mark_done(self, queue_id: int) -> None:
        """标记 ``done``，记录 ``finished_at``。

        仅允许从 ``running`` 转入 ``done``。非法状态转换记 warning，不改状态。
        """
        with self.storage.get_connection() as conn:
            cur = conn.execute(
                "UPDATE queue SET status = ?, finished_at = CURRENT_TIMESTAMP, "
                "                error_msg = NULL, error_type = NULL "
                "WHERE id = ? AND status = ?",
                (STATUS_DONE, queue_id, STATUS_RUNNING),
            )
            if cur.rowcount == 0:
                logger.warning(
                    f"mark_done: queue_id={queue_id} 非法状态转换（当前非 running）"
                )
                return
        logger.info(f"mark_done queue_id={queue_id}")

    def mark_failed(self, queue_id: int, error_type: str, error_msg: str) -> None:
        """标记 ``failed``，记录错误信息与 ``finished_at``，``retry_count`` +1。

        仅允许从 ``running`` 转入 ``failed``。``failed`` 状态可被 :meth:`acquire`
        再次取走以重试。非法状态转换记 warning，不改状态。
        """
        with self.storage.get_connection() as conn:
            cur = conn.execute(
                "UPDATE queue SET status = ?, retry_count = retry_count + 1, "
                "                finished_at = CURRENT_TIMESTAMP, "
                "                error_msg = ?, error_type = ? "
                "WHERE id = ? AND status = ?",
                (STATUS_FAILED, error_msg, error_type, queue_id, STATUS_RUNNING),
            )
            if cur.rowcount == 0:
                logger.warning(
                    f"mark_failed: queue_id={queue_id} 非法状态转换（当前非 running）"
                )
                return
        logger.warning(
            f"mark_failed queue_id={queue_id} type={error_type} msg={error_msg}"
        )

    def mark_blocked(self, queue_id: int, error_type: str, error_msg: str) -> None:
        """标记 ``blocked``，记录错误信息与 ``finished_at``。

        仅允许从 ``running`` 转入 ``blocked``。``blocked`` 状态不重试，等待冷却后由
        :meth:`reset_blocked_to_pending` 重新入队。非法状态转换记 warning，不改状态。
        """
        with self.storage.get_connection() as conn:
            cur = conn.execute(
                "UPDATE queue SET status = ?, finished_at = CURRENT_TIMESTAMP, "
                "                error_msg = ?, error_type = ? "
                "WHERE id = ? AND status = ?",
                (STATUS_BLOCKED, error_msg, error_type, queue_id, STATUS_RUNNING),
            )
            if cur.rowcount == 0:
                logger.warning(
                    f"mark_blocked: queue_id={queue_id} 非法状态转换（当前非 running）"
                )
                return
        logger.warning(
            f"mark_blocked queue_id={queue_id} type={error_type} msg={error_msg}"
        )

    def mark_skipped(self, queue_id: int) -> None:
        """标记 ``skipped``（已存在且未过期），记录 ``finished_at``。

        仅允许从 ``running`` 转入 ``skipped``。非法状态转换记 warning，不改状态。
        """
        with self.storage.get_connection() as conn:
            cur = conn.execute(
                "UPDATE queue SET status = ?, finished_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = ?",
                (STATUS_SKIPPED, queue_id, STATUS_RUNNING),
            )
            if cur.rowcount == 0:
                logger.warning(
                    f"mark_skipped: queue_id={queue_id} 非法状态转换（当前非 running）"
                )
                return
        logger.info(f"mark_skipped queue_id={queue_id}")

    # ---------------- 换IP计数 ----------------

    def increment_ip_switch(self, queue_id: int) -> bool:
        """换IP次数 +1，超限则自动标记 ``blocked`` 并 ``log.warning``。

        设计文档 4.2 伪代码::

            new_count = UPDATE queue SET ip_switch_count = ip_switch_count + 1
            max_switch = config.get('captcha_max_switch', 5)
            if new_count >= max_switch:
                mark_blocked(queue_id, 'ip_switch_limit', f'换IP次数超限(...)')
                log.warning(...)
                return True  # 超限
            return False  # 未超限

        **原子性**：count+1、读 url/count、判断超限、超限则 UPDATE status=blocked
        全部在同一事务内完成，避免分段事务的原子性窗口（防止并发下 count 已写
        但 status 未改的不一致）。

        :return: ``True`` 表示已超限（并已自动 blocked），``False`` 表示未超限
        """
        max_switch = self.config.get_int("captcha_max_switch", 5)
        with self.storage.get_connection() as conn:
            # count + 1
            cur = conn.execute(
                "UPDATE queue SET ip_switch_count = ip_switch_count + 1 WHERE id = ?",
                (queue_id,),
            )
            if cur.rowcount == 0:
                logger.warning(
                    f"increment_ip_switch: queue_id={queue_id} 不存在"
                )
                return False
            # 同事务读 url 和新 count（用于日志与超限判断）
            row = conn.execute(
                "SELECT url, ip_switch_count FROM queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if row is None:
                return False
            url = row["url"]
            new_count = row["ip_switch_count"]
            # 同事务判断超限并标记 blocked。
            # 注意：此处 UPDATE 不限 status —— 换IP超限是强制行为，无论当前
            # 处于何种状态都应立即 blocked（防止 count 已累加但状态未变的窗口）。
            # 外部 mark_* 方法的状态校验是防止调度逻辑误用，与强制超限无关。
            exceeded = new_count >= max_switch
            if exceeded:
                conn.execute(
                    "UPDATE queue SET status = ?, finished_at = CURRENT_TIMESTAMP, "
                    "                error_msg = ?, error_type = ? "
                    "WHERE id = ?",
                    (STATUS_BLOCKED,
                     f"换IP次数超限({new_count}/{max_switch})",
                     ERROR_IP_SWITCH_LIMIT,
                     queue_id),
                )
        # 事务外打日志
        if exceeded:
            logger.warning(
                f"URL换IP次数超限({new_count}/{max_switch}),标记blocked: {url}"
            )
        else:
            logger.debug(
                f"increment_ip_switch queue_id={queue_id} → {new_count}/{max_switch}"
            )
        return exceeded

    def check_ip_switch_limit(
        self, queue_id: int, max_switch: int | None = None
    ) -> bool:
        """检查换IP次数是否超限（不修改数据库）。

        :param max_switch: 自定义上限。``None`` 时从 ``captcha_max_switch`` 读取。
        :return: ``True`` 表示已超限（``ip_switch_count >= max_switch``）
        """
        if max_switch is None:
            max_switch = self.config.get_int("captcha_max_switch", 5)
        row = self.storage.execute(
            "SELECT ip_switch_count FROM queue WHERE id = ?",
            (queue_id,),
            fetch="one",
        )
        if row is None:
            return False
        return row[0] >= max_switch

    # ---------------- 冷却重置 ----------------

    def reset_blocked_to_pending(self) -> int:
        """将冷却结束的 ``blocked`` URL 重置为 ``pending``。

        冷却时间从 ``config.captcha_cooldown``（默认 1800 秒）读取：
        ``finished_at + cooldown <= now`` 的 ``blocked`` URL 会被重置为 ``pending``，
        并清空 ``started_at`` / ``finished_at`` / ``error_msg`` / ``error_type``。

        :return: 重置的行数
        """
        cooldown = self.config.get_int("captcha_cooldown", 1800)
        # strftime('%s', …) 返回 Unix 时间戳字符串，CAST 为 INTEGER 后比较
        # 条件：now - finished_at >= cooldown
        with self.storage.get_connection() as conn:
            cur = conn.execute(
                "UPDATE queue "
                "SET status = ?, started_at = NULL, finished_at = NULL, "
                "    error_msg = NULL, error_type = NULL "
                "WHERE status = ? "
                "  AND finished_at IS NOT NULL "
                "  AND CAST(strftime('%s', 'now') AS INTEGER) "
                "      - CAST(strftime('%s', finished_at) AS INTEGER) >= ?",
                (STATUS_PENDING, STATUS_BLOCKED, cooldown),
            )
            count = cur.rowcount
        if count > 0:
            logger.info(f"reset_blocked_to_pending: 重置 {count} 条 blocked URL")
        return count
