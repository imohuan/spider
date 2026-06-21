"""state_machine 模块测试 - queue 表状态流转、原子性、换IP超限、并发安全。

测试覆盖：
- 5 个状态流转：pending→running→done / failed / blocked / skipped
- failed → running（acquire 能取 failed 状态做重试）
- blocked → pending（冷却后 reset_blocked_to_pending 重置）
- acquire 选取规则：priority 降序、created_at 升序、仅取 pending/failed
- acquire 原子性：取 + 标记 running 在同一事务，started_at 已写入
- acquire 空队列返回 None
- mark_failed 自动 retry_count+1
- increment_ip_switch 未超限返回 False，超限自动 mark_blocked + 返回 True
- increment_ip_switch 自定义 captcha_max_switch 阈值
- check_ip_switch_limit 不修改数据库
- reset_blocked_to_pending 冷却未到不重置、冷却已到重置
- 并发 acquire：多线程同时 acquire 同一队列，同一 URL 不被重复取走
- 全部用 tmp_path 隔离，不污染真实 DB
"""
import threading
import time

import pytest

from core.config_manager import ConfigManager
from core.state_machine import (
    ERROR_403,
    ERROR_IP_SWITCH_LIMIT,
    ERROR_NETWORK,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    StateMachine,
)
from core.storage import Storage


# ---------------- fixtures ----------------


@pytest.fixture
def storage(tmp_path):
    """用 tmp_path 隔离的 Storage 实例。"""
    db_path = tmp_path / "test.db"
    s = Storage(str(db_path))
    yield s
    s.close()


@pytest.fixture
def cfg(storage):
    """已初始化默认配置的 ConfigManager。"""
    c = ConfigManager(storage)
    c.init_defaults()
    return c


@pytest.fixture
def sm(storage, cfg):
    """StateMachine 实例（依赖 storage + cfg fixtures）。"""
    return StateMachine(storage, cfg)


# ---------------- 辅助 ----------------


def _enqueue(
    storage: Storage,
    url: str,
    parser_name: str = "list",
    priority: int = 0,
) -> int:
    """入队辅助，返回 queue.id。"""
    return storage.enqueue(url, parser_name=parser_name, priority=priority)


def _get_status(storage: Storage, queue_id: int) -> str:
    """读取 queue 行的 status。"""
    row = storage.execute(
        "SELECT status FROM queue WHERE id = ?",
        (queue_id,),
        fetch="one",
    )
    return row[0] if row else "<missing>"


def _get_field(storage: Storage, queue_id: int, field: str) -> object:
    """读取 queue 行的指定字段。"""
    row = storage.execute(
        f"SELECT {field} FROM queue WHERE id = ?",
        (queue_id,),
        fetch="one",
    )
    return row[0] if row else None


# ---------------- acquire 选取规则 ----------------


def test_acquire_empty_queue_returns_none(sm):
    """空队列 acquire 应返回 None。"""
    assert sm.acquire() is None


def test_acquire_pending_marks_running_and_returns_task(sm, storage):
    """acquire 应取 pending → 标记 running，返回完整任务字典。"""
    qid = _enqueue(storage, "http://example.com/a", parser_name="list", priority=5)

    task = sm.acquire()

    assert task is not None
    # 字段完整
    assert set(task.keys()) == {
        "id",
        "url",
        "url_hash",
        "parser_name",
        "retry_count",
        "ip_switch_count",
        "priority",
        "fetch_mode",
        "request_config",
    }
    assert task["id"] == qid
    assert task["url"] == "http://example.com/a"
    assert task["parser_name"] == "list"
    assert task["priority"] == 5
    assert task["retry_count"] == 0
    assert task["ip_switch_count"] == 0
    # 状态已原子变为 running
    assert _get_status(storage, qid) == STATUS_RUNNING
    # started_at 已写入
    assert _get_field(storage, qid, "started_at") is not None


def test_acquire_priority_descending(sm, storage):
    """高 priority 应被优先取走。"""
    qid_low = _enqueue(storage, "http://example.com/low", priority=1)
    qid_high = _enqueue(storage, "http://example.com/high", priority=10)
    qid_mid = _enqueue(storage, "http://example.com/mid", priority=5)

    # 入队顺序为 low, high, mid，但应按 priority 降序取：high → mid → low
    task1 = sm.acquire()
    task2 = sm.acquire()
    task3 = sm.acquire()

    assert task1["id"] == qid_high
    assert task2["id"] == qid_mid
    assert task3["id"] == qid_low


def test_acquire_created_at_ascending_when_same_priority(sm, storage):
    """同 priority 时按 created_at 升序（先入队先出）。"""
    qid_first = _enqueue(storage, "http://example.com/first", priority=5)
    # 显式间隔 1.1 秒，确保 created_at 不同（SQLite CURRENT_TIMESTAMP 精度到秒）
    time.sleep(1.1)
    qid_second = _enqueue(storage, "http://example.com/second", priority=5)

    task1 = sm.acquire()
    task2 = sm.acquire()

    assert task1["id"] == qid_first
    assert task2["id"] == qid_second


def test_acquire_skips_running_done_blocked_skipped(sm, storage):
    """acquire 仅取 pending/failed，跳过其他状态。"""
    qid = _enqueue(storage, "http://example.com/x", priority=0)
    # 手动改成 running，模拟被其他线程取走
    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?", (STATUS_RUNNING, qid)
    )
    assert sm.acquire() is None

    # 改成 done
    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?", (STATUS_DONE, qid)
    )
    assert sm.acquire() is None

    # 改成 skipped
    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?", (STATUS_SKIPPED, qid)
    )
    assert sm.acquire() is None

    # 改成 blocked
    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?", (STATUS_BLOCKED, qid)
    )
    assert sm.acquire() is None


def test_acquire_takes_failed_for_retry(sm, storage):
    """acquire 应能取 failed 状态做重试。"""
    qid = _enqueue(storage, "http://example.com/retry", priority=0)
    # 先 acquire → mark_failed，再 acquire 应能重新取到
    task1 = sm.acquire()
    assert task1 is not None
    sm.mark_failed(qid, ERROR_NETWORK, "timeout")

    assert _get_status(storage, qid) == STATUS_FAILED

    task2 = sm.acquire()
    assert task2 is not None
    assert task2["id"] == qid
    # retry_count 应保留为 1（mark_failed 时 +1）
    assert task2["retry_count"] == 1
    # 状态变回 running
    assert _get_status(storage, qid) == STATUS_RUNNING


# ---------------- 状态流转：5 条路径 ----------------


def test_pending_to_running_to_done(sm, storage):
    """pending → running → done。"""
    qid = _enqueue(storage, "http://example.com/done")
    sm.acquire()
    assert _get_status(storage, qid) == STATUS_RUNNING

    sm.mark_done(qid)

    assert _get_status(storage, qid) == STATUS_DONE
    assert _get_field(storage, qid, "finished_at") is not None
    # mark_done 应清空错误字段
    assert _get_field(storage, qid, "error_msg") is None
    assert _get_field(storage, qid, "error_type") is None


def test_pending_to_running_to_failed(sm, storage):
    """pending → running → failed。"""
    qid = _enqueue(storage, "http://example.com/failed")
    sm.acquire()

    sm.mark_failed(qid, ERROR_NETWORK, "connection reset")

    assert _get_status(storage, qid) == STATUS_FAILED
    assert _get_field(storage, qid, "error_type") == ERROR_NETWORK
    assert _get_field(storage, qid, "error_msg") == "connection reset"
    assert _get_field(storage, qid, "finished_at") is not None
    # retry_count 应 +1
    assert _get_field(storage, qid, "retry_count") == 1


def test_pending_to_running_to_blocked(sm, storage):
    """pending → running → blocked。"""
    qid = _enqueue(storage, "http://example.com/blocked")
    sm.acquire()

    sm.mark_blocked(qid, "403", "forbidden")

    assert _get_status(storage, qid) == STATUS_BLOCKED
    assert _get_field(storage, qid, "error_type") == "403"
    assert _get_field(storage, qid, "error_msg") == "forbidden"
    assert _get_field(storage, qid, "finished_at") is not None
    # blocked 不增加 retry_count
    assert _get_field(storage, qid, "retry_count") == 0


def test_pending_to_running_to_skipped(sm, storage):
    """pending → running → skipped。"""
    qid = _enqueue(storage, "http://example.com/skipped")
    sm.acquire()

    sm.mark_skipped(qid)

    assert _get_status(storage, qid) == STATUS_SKIPPED
    assert _get_field(storage, qid, "finished_at") is not None


def test_failed_to_running_retry_loop(sm, storage, cfg):
    """failed → running → failed → running 多次重试，retry_count 持续累加。

    retry_count 达到 queue_max_retry 后不再被 acquire 取走。
    """
    qid = _enqueue(storage, "http://example.com/loop")
    for i in range(1, 4):
        task = sm.acquire()
        assert task is not None
        assert _get_status(storage, qid) == STATUS_RUNNING
        sm.mark_failed(qid, ERROR_NETWORK, f"attempt {i}")
        assert _get_field(storage, qid, "retry_count") == i

    # retry_count=3，已达 queue_max_retry=3，不再被 acquire 取走
    assert _get_status(storage, qid) == STATUS_FAILED
    assert _get_field(storage, qid, "retry_count") == 3
    task = sm.acquire()
    assert task is None, "retry_count >= queue_max_retry 的任务不应被取走"

    # 重置 queue_max_retry 为更高值，应能再次取到
    cfg.set("queue_max_retry", "5")
    task = sm.acquire()
    assert task is not None
    assert task["retry_count"] == 3


def test_blocked_to_pending_after_cooldown(sm, storage, cfg):
    """blocked → pending 冷却后重置。"""
    # 缩短冷却时间便于测试
    cfg.set("captcha_cooldown", "2")
    qid = _enqueue(storage, "http://example.com/cooldown")
    sm.acquire()
    sm.mark_blocked(qid, "403", "forbidden")
    assert _get_status(storage, qid) == STATUS_BLOCKED

    # 冷却未到，不应重置
    count = sm.reset_blocked_to_pending()
    assert count == 0
    assert _get_status(storage, qid) == STATUS_BLOCKED

    # 等待冷却结束
    time.sleep(2.1)
    count = sm.reset_blocked_to_pending()
    assert count == 1
    assert _get_status(storage, qid) == STATUS_PENDING
    # 重置后清空错误字段
    assert _get_field(storage, qid, "started_at") is None
    assert _get_field(storage, qid, "finished_at") is None
    assert _get_field(storage, qid, "error_msg") is None
    assert _get_field(storage, qid, "error_type") is None


def test_reset_blocked_to_pending_skips_unfinished(sm, storage, cfg):
    """finished_at 为 NULL 的 blocked URL 不应被重置（避免误操作）。"""
    cfg.set("captcha_cooldown", "0")
    qid = _enqueue(storage, "http://example.com/null")
    # 直接 UPDATE 成 blocked 但 finished_at=NULL（异常状态）
    storage.execute(
        "UPDATE queue SET status = ?, finished_at = NULL WHERE id = ?",
        (STATUS_BLOCKED, qid),
    )
    count = sm.reset_blocked_to_pending()
    assert count == 0
    assert _get_status(storage, qid) == STATUS_BLOCKED


def test_reset_blocked_to_pending_zero_cooldown(sm, storage, cfg):
    """cooldown=0 时，刚 blocked 的 URL 立刻可被重置。"""
    cfg.set("captcha_cooldown", "0")
    qid = _enqueue(storage, "http://example.com/zero")
    sm.acquire()
    sm.mark_blocked(qid, "403", "forbidden")

    count = sm.reset_blocked_to_pending()
    assert count == 1
    assert _get_status(storage, qid) == STATUS_PENDING


def test_reset_blocked_to_pending_does_not_touch_other_statuses(sm, storage, cfg):
    """reset 不应影响 pending/running/done/failed/skipped 状态的行。"""
    cfg.set("captcha_cooldown", "0")
    qid_pending = _enqueue(storage, "http://example.com/p")
    qid_running = _enqueue(storage, "http://example.com/r")
    qid_done = _enqueue(storage, "http://example.com/d")
    qid_failed = _enqueue(storage, "http://example.com/f")
    qid_skipped = _enqueue(storage, "http://example.com/s")
    qid_blocked = _enqueue(storage, "http://example.com/b")

    storage.execute(
        "UPDATE queue SET status = 'running', started_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (qid_running,),
    )
    storage.execute(
        "UPDATE queue SET status = 'done', finished_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (qid_done,),
    )
    storage.execute(
        "UPDATE queue SET status = 'failed', finished_at = CURRENT_TIMESTAMP, "
        "retry_count = 1 WHERE id = ?",
        (qid_failed,),
    )
    storage.execute(
        "UPDATE queue SET status = 'skipped', finished_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (qid_skipped,),
    )
    storage.execute(
        "UPDATE queue SET status = 'blocked', finished_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (qid_blocked,),
    )

    count = sm.reset_blocked_to_pending()
    assert count == 1
    # 其他状态保持不变
    assert _get_status(storage, qid_pending) == STATUS_PENDING
    assert _get_status(storage, qid_running) == STATUS_RUNNING
    assert _get_status(storage, qid_done) == STATUS_DONE
    # failed 应保持 failed（含 retry_count）
    assert _get_status(storage, qid_failed) == STATUS_FAILED
    assert _get_field(storage, qid_failed, "retry_count") == 1
    assert _get_status(storage, qid_skipped) == STATUS_SKIPPED
    assert _get_status(storage, qid_blocked) == STATUS_PENDING


# ---------------- increment_ip_switch ----------------


def test_increment_ip_switch_under_limit_returns_false(sm, storage):
    """未超限时 increment_ip_switch 返回 False，count 累加。"""
    qid = _enqueue(storage, "http://example.com/ip")
    # 默认 captcha_max_switch=5
    for i in range(1, 5):
        exceeded = sm.increment_ip_switch(qid)
        assert exceeded is False
        assert _get_field(storage, qid, "ip_switch_count") == i
        # 未超限时不应自动 blocked
        assert _get_status(storage, qid) == STATUS_PENDING


def test_increment_ip_switch_exceed_auto_blocked(sm, storage, cfg):
    """达到上限时 increment_ip_switch 自动 mark_blocked 并返回 True。"""
    qid = _enqueue(storage, "http://example.com/exceed")
    # 默认上限 5：调用 5 次后超限
    for _ in range(4):
        assert sm.increment_ip_switch(qid) is False

    # 第 5 次：count 变 5，5 >= 5 触发超限
    exceeded = sm.increment_ip_switch(qid)
    assert exceeded is True
    assert _get_field(storage, qid, "ip_switch_count") == 5
    # 自动 blocked
    assert _get_status(storage, qid) == STATUS_BLOCKED
    assert _get_field(storage, qid, "error_type") == ERROR_IP_SWITCH_LIMIT
    assert _get_field(storage, qid, "error_msg") == "换IP次数超限(5/5)"
    assert _get_field(storage, qid, "finished_at") is not None


def test_increment_ip_switch_custom_threshold(sm, storage, cfg):
    """修改 captcha_max_switch 配置后应按新阈值判定。"""
    cfg.set("captcha_max_switch", "3")
    qid = _enqueue(storage, "http://example.com/custom")
    # 1, 2 未超限
    assert sm.increment_ip_switch(qid) is False
    assert sm.increment_ip_switch(qid) is False
    # 第 3 次：3 >= 3 超限
    assert sm.increment_ip_switch(qid) is True
    assert _get_status(storage, qid) == STATUS_BLOCKED
    assert _get_field(storage, qid, "error_msg") == "换IP次数超限(3/3)"


def test_increment_ip_switch_nonexistent_id(sm):
    """不存在的 queue_id 应安全返回 False（不抛异常）。"""
    # 调用不应抛异常
    result = sm.increment_ip_switch(99999)
    assert result is False


# ---------------- check_ip_switch_limit ----------------


def test_check_ip_switch_limit_does_not_modify(sm, storage, cfg):
    """check_ip_switch_limit 不修改数据库。"""
    qid = _enqueue(storage, "http://example.com/check")
    cfg.set("captcha_max_switch", "3")

    # 初始未超限
    assert sm.check_ip_switch_limit(qid) is False
    assert _get_field(storage, qid, "ip_switch_count") == 0

    # 手动加到 2，仍未超限
    storage.execute(
        "UPDATE queue SET ip_switch_count = 2 WHERE id = ?", (qid,)
    )
    assert sm.check_ip_switch_limit(qid) is False

    # 加到 3，超限
    storage.execute(
        "UPDATE queue SET ip_switch_count = 3 WHERE id = ?", (qid,)
    )
    assert sm.check_ip_switch_limit(qid) is True

    # count 仍是 3，未被修改
    assert _get_field(storage, qid, "ip_switch_count") == 3


def test_check_ip_switch_limit_custom_max(sm, storage):
    """显式传入 max_switch 覆盖配置值。"""
    qid = _enqueue(storage, "http://example.com/param")
    storage.execute(
        "UPDATE queue SET ip_switch_count = 2 WHERE id = ?", (qid,)
    )
    # 默认 captcha_max_switch=5，未超限
    assert sm.check_ip_switch_limit(qid) is False
    # 自定义 max_switch=2，2 >= 2 超限
    assert sm.check_ip_switch_limit(qid, max_switch=2) is True
    # 自定义 max_switch=10，未超限
    assert sm.check_ip_switch_limit(qid, max_switch=10) is False


def test_check_ip_switch_limit_nonexistent_id(sm):
    """不存在的 queue_id 应返回 False。"""
    assert sm.check_ip_switch_limit(99999) is False


# ---------------- acquire 原子性 ----------------


def test_acquire_atomic_started_at_set(sm, storage):
    """acquire 在同一事务内更新 status 与 started_at，无中间状态。"""
    qid = _enqueue(storage, "http://example.com/atomic")
    task = sm.acquire()
    assert task is not None
    # 立即查询，两个字段都应已写入（事务已 COMMIT）
    row = storage.execute(
        "SELECT status, started_at FROM queue WHERE id = ?",
        (qid,),
        fetch="one",
    )
    assert row[0] == STATUS_RUNNING
    assert row[1] is not None


def test_acquire_clears_error_fields_from_failed(sm, storage):
    """acquire 取走 failed 行后，error_msg/error_type 应被清空。"""
    qid = _enqueue(storage, "http://example.com/clear")
    sm.acquire()
    sm.mark_failed(qid, ERROR_NETWORK, "first failure")
    # 验证错误字段已写入
    assert _get_field(storage, qid, "error_msg") == "first failure"
    assert _get_field(storage, qid, "error_type") == ERROR_NETWORK

    # 重新 acquire，应清空错误字段
    sm.acquire()
    assert _get_status(storage, qid) == STATUS_RUNNING
    assert _get_field(storage, qid, "error_msg") is None
    assert _get_field(storage, qid, "error_type") is None
    assert _get_field(storage, qid, "finished_at") is None


# ---------------- 并发 acquire ----------------


def test_concurrent_acquire_no_duplicate(sm, storage):
    """多线程并发 acquire 同一队列，同一 URL 不被重复取走。

    构造 20 个 pending URL，启动 20 个线程同时 acquire，
    每个线程最多取 1 次。最终应取到 20 个不同的 id（无重复、无遗漏）。
    """
    sm.config.set("crawler_max_running", "100")  # 放开并发限额
    n = 20
    qids = [
        _enqueue(storage, f"http://example.com/c{i}", priority=i)
        for i in range(n)
    ]
    acquired: list[int] = []
    acquired_lock = threading.Lock()
    errors: list[Exception] = []

    def worker():
        try:
            task = sm.acquire()
            if task is not None:
                with acquired_lock:
                    acquired.append(task["id"])
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"线程出错: {errors}"
    # 应取到 n 个不同的 id（每个线程取一个，因 priority 不同各取各的）
    assert len(acquired) == n
    assert len(set(acquired)) == n, f"出现重复 acquire: {acquired}"
    # 所有 URL 应该处于 running 状态
    running_count = storage.execute(
        "SELECT COUNT(*) FROM queue WHERE status = ?",
        (STATUS_RUNNING,),
        fetch="one",
    )[0]
    assert running_count == n


def test_concurrent_acquire_single_url_only_one_wins(sm, storage):
    """多线程并发 acquire 单一 URL，只有一个线程能取到。

    构造 1 个 pending URL，启动 10 个线程同时 acquire，
    应只有 1 个线程取到 task，其余返回 None。
    """
    qid = _enqueue(storage, "http://example.com/single", priority=0)
    acquired: list[int] = []
    acquired_lock = threading.Lock()
    errors: list[Exception] = []

    def worker():
        try:
            task = sm.acquire()
            if task is not None:
                with acquired_lock:
                    acquired.append(task["id"])
        except Exception as e:
            errors.append(e)

    n = 10
    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"线程出错: {errors}"
    # 只有 1 个线程取到
    assert len(acquired) == 1
    assert acquired[0] == qid
    # URL 处于 running
    assert _get_status(storage, qid) == STATUS_RUNNING


def test_concurrent_acquire_many_urls_high_contention(sm, storage):
    """高并发场景：5 个 URL + 20 个线程，每个 URL 最多被取 1 次。

    比单 URL 测试更接近真实场景（多 worker 争抢少量任务）。
    """
    sm.config.set("crawler_max_running", "100")  # 放开并发限额
    n_urls = 5
    n_threads = 20
    qids = [
        _enqueue(storage, f"http://example.com/h{i}", priority=i)
        for i in range(n_urls)
    ]
    acquired: list[int] = []
    acquired_lock = threading.Lock()
    errors: list[Exception] = []

    def worker():
        try:
            task = sm.acquire()
            if task is not None:
                with acquired_lock:
                    acquired.append(task["id"])
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"线程出错: {errors}"
    # 应取到 5 个不同的 id（不多不少）
    assert len(acquired) == n_urls
    assert len(set(acquired)) == n_urls, f"出现重复: {acquired}"
    assert set(acquired) == set(qids)


# ---------------- 端到端：完整生命周期 ----------------


def test_end_to_end_lifecycle_success(sm, storage):
    """端到端：pending → running → done，acquire 后队列空。"""
    qid = _enqueue(storage, "http://example.com/e2e", priority=0)

    task = sm.acquire()
    assert task is not None
    sm.mark_done(task["id"])

    # 队列已无 pending/failed
    assert sm.acquire() is None
    assert _get_status(storage, qid) == STATUS_DONE


def test_end_to_end_lifecycle_blocked_then_retry(sm, storage, cfg):
    """端到端：pending → running → blocked → pending → running → done。"""
    cfg.set("captcha_cooldown", "0")
    qid = _enqueue(storage, "http://example.com/blocked-then-retry")

    # 第一次 acquire → blocked
    task1 = sm.acquire()
    assert task1 is not None
    sm.mark_blocked(qid, "403", "forbidden")
    assert _get_status(storage, qid) == STATUS_BLOCKED

    # 此时 acquire 不应取到 blocked
    assert sm.acquire() is None

    # 冷却重置
    sm.reset_blocked_to_pending()
    assert _get_status(storage, qid) == STATUS_PENDING

    # 第二次 acquire → done
    task2 = sm.acquire()
    assert task2 is not None
    sm.mark_done(qid)
    assert _get_status(storage, qid) == STATUS_DONE


def test_end_to_end_ip_switch_exceed_blocked(sm, storage, cfg):
    """端到端：连续触发验证码 → 多次换IP → 超限自动 blocked。"""
    cfg.set("captcha_max_switch", "3")
    qid = _enqueue(storage, "http://example.com/captcha-loop")

    # 模拟 3 次验证码触发：每次都 increment_ip_switch
    exceeded1 = sm.increment_ip_switch(qid)
    assert exceeded1 is False
    assert _get_status(storage, qid) == STATUS_PENDING

    exceeded2 = sm.increment_ip_switch(qid)
    assert exceeded2 is False
    assert _get_status(storage, qid) == STATUS_PENDING

    # 第 3 次超限 → 自动 blocked
    exceeded3 = sm.increment_ip_switch(qid)
    assert exceeded3 is True
    assert _get_status(storage, qid) == STATUS_BLOCKED
    assert _get_field(storage, qid, "ip_switch_count") == 3
    assert _get_field(storage, qid, "error_type") == ERROR_IP_SWITCH_LIMIT


# ---------------- 非法状态转换防护（I1 修复） ----------------


def test_mark_done_rejects_non_running_state(sm, storage):
    """mark_done 仅允许从 running 转入，对 done/blocked/skipped 状态不改。"""
    qid = _enqueue(storage, "http://example.com/x")
    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?",
        (STATUS_DONE, qid),
        fetch="none",
    )
    sm.mark_done(qid)  # 应被拒绝
    assert _get_status(storage, qid) == STATUS_DONE
    fin1 = _get_field(storage, qid, "finished_at")
    sm.mark_done(qid)
    fin2 = _get_field(storage, qid, "finished_at")
    assert fin1 == fin2


def test_mark_failed_rejects_non_running_state(sm, storage):
    """mark_failed 仅允许从 running 转入，对终态不改也不增 retry_count。"""
    qid = _enqueue(storage, "http://example.com/x")
    storage.execute(
        "UPDATE queue SET status = ?, retry_count = 0 WHERE id = ?",
        (STATUS_DONE, qid),
        fetch="none",
    )
    sm.mark_failed(qid, ERROR_NETWORK, "should be rejected")
    assert _get_status(storage, qid) == STATUS_DONE
    assert _get_field(storage, qid, "retry_count") == 0


def test_mark_blocked_rejects_non_running_state(sm, storage):
    """mark_blocked 仅允许从 running 转入。"""
    qid = _enqueue(storage, "http://example.com/x")
    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?",
        (STATUS_SKIPPED, qid),
        fetch="none",
    )
    sm.mark_blocked(qid, ERROR_403, "should be rejected")
    assert _get_status(storage, qid) == STATUS_SKIPPED


def test_mark_skipped_rejects_non_running_state(sm, storage):
    """mark_skipped 仅允许从 running 转入。"""
    qid = _enqueue(storage, "http://example.com/x")
    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?",
        (STATUS_DONE, qid),
        fetch="none",
    )
    sm.mark_skipped(qid)
    assert _get_status(storage, qid) == STATUS_DONE


def test_mark_transitions_work_from_running(sm, storage):
    """acquire 进入 running 后，所有 mark_* 转换都应成功（正向回归）。"""
    qid = _enqueue(storage, "http://example.com/x")
    sm.acquire()  # → running
    sm.mark_done(qid)
    assert _get_status(storage, qid) == STATUS_DONE

    storage.execute(
        "UPDATE queue SET status = ? WHERE id = ?",
        (STATUS_PENDING, qid),
        fetch="none",
    )
    sm.acquire()
    sm.mark_failed(qid, ERROR_NETWORK, "net err")
    assert _get_status(storage, qid) == STATUS_FAILED
    assert _get_field(storage, qid, "retry_count") == 1


# ---------------- increment_ip_switch 原子性（C1 修复） ----------------


def test_increment_ip_switch_atomic_count_and_status(sm, storage, cfg):
    """C1 回归：超限时 count 与 blocked 状态在同一事务内写入，
    不存在 count 已 +1 但 status 未改的中间态。"""
    cfg.set("captcha_max_switch", "1")
    qid = _enqueue(storage, "http://example.com/atomic")
    exceeded = sm.increment_ip_switch(qid)
    assert exceeded is True
    assert _get_field(storage, qid, "ip_switch_count") == 1
    assert _get_status(storage, qid) == STATUS_BLOCKED
    assert _get_field(storage, qid, "error_type") == ERROR_IP_SWITCH_LIMIT


def test_increment_ip_switch_concurrent_no_split_state(sm, storage, cfg):
    """C1 回归：多线程并发对同一 queue_id 调用 increment_ip_switch，
    不会出现 count 与 status 不一致。"""
    cfg.set("captcha_max_switch", "10")
    qid = _enqueue(storage, "http://example.com/concurrent")

    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        r = sm.increment_ip_switch(qid)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert _get_field(storage, qid, "ip_switch_count") == 8
    assert _get_status(storage, qid) == STATUS_PENDING
