"""storage 模块测试 - 数据库初始化、系统表建表、CRUD、url_hash 去重、业务表自动建表。

测试覆盖：
- 6 张系统表全部建出（config/queue/requests/seen_urls/proxy_pool/captcha_log）
- 索引全部建出（idx_queue_status / idx_queue_url_hash / idx_requests_queue /
  idx_requests_time / idx_proxy_status / idx_proxy_expire）
- WAL 模式启用
- enqueue 入队 + url_hash 去重（同 URL 入队两次不重复，返回相同 id）
- add_seen_url / is_url_seen（已见判断、fetch_count 自增）
- create_request / mark_request_success / mark_request_failed
- save_business_data 批量插入
- ensure_business_table 自动建表（幂等）
- get_connection 上下文管理器
- execute 通用接口
- 多线程并发写不损坏（线程安全）
- 全部用 tmp_path 隔离，不污染真实 DB
"""
import json
import os
import sqlite3
import threading

import pytest

from core import storage as storage_module
from core.storage import Storage


# ---------------- fixtures ----------------

@pytest.fixture
def storage(tmp_path):
    """用 tmp_path 隔离的 Storage 实例。"""
    db_path = tmp_path / "test.db"
    s = Storage(str(db_path))
    yield s
    s.close()


def _list_tables(storage: Storage) -> list[str]:
    """获取所有用户表名（按字母序）。"""
    rows = storage.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name",
        fetch="all",
    )
    return [r[0] for r in rows]


def _list_indexes(storage: Storage) -> list[str]:
    """获取所有索引名（按字母序）。"""
    rows = storage.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name",
        fetch="all",
    )
    return [r[0] for r in rows]


# ---------------- 建表 ----------------

def test_creates_all_system_tables(storage):
    """7 张系统表必须全部建出。"""
    tables = set(_list_tables(storage))
    expected = {"config", "queue", "requests", "seen_urls", "proxy_pool", "captcha_log", "image_queue"}
    missing = expected - tables
    assert not missing, f"缺少系统表: {missing}"
    # 不应有额外的表
    assert tables == expected, f"意外的表: {tables - expected}"


def test_creates_all_indexes(storage):
    """所有索引必须建出。"""
    indexes = set(_list_indexes(storage))
    expected = {
        "idx_queue_status",
        "idx_queue_url_hash",
        "idx_requests_queue",
        "idx_requests_time",
        "idx_proxy_status",
        "idx_proxy_expire",
        "idx_image_queue_status",
        "idx_image_queue_url_hash",
    }
    missing = expected - indexes
    assert not missing, f"缺少索引: {missing}"


def test_init_db_is_idempotent(tmp_path):
    """多次 Storage() 不应报错（IF NOT EXISTS 幂等）。"""
    db_path = tmp_path / "test.db"
    s1 = Storage(str(db_path))
    queue_count_1 = s1.execute("SELECT COUNT(*) FROM queue", fetch="one")[0]
    s1.close()
    # 再次打开同一 DB
    s2 = Storage(str(db_path))
    queue_count_2 = s2.execute("SELECT COUNT(*) FROM queue", fetch="one")[0]
    assert queue_count_1 == queue_count_2 == 0
    s2.close()


def test_creates_db_file_if_not_exists(tmp_path):
    """DB 文件不存在时应自动创建（含父目录）。"""
    db_path = tmp_path / "nested" / "deeper" / "test.db"
    assert not db_path.exists()
    s = Storage(str(db_path))
    assert db_path.exists()
    s.close()


# ---------------- WAL 模式 ----------------

def test_wal_mode_enabled(storage):
    """journal_mode 应为 wal。"""
    row = storage.execute("PRAGMA journal_mode", fetch="one")
    assert row[0].lower() == "wal"


# ---------------- queue 表 CRUD ----------------

def test_enqueue_returns_int_id(storage):
    """enqueue 应返回 int 类型的 queue id。"""
    qid = storage.enqueue("http://example.com/page1")
    assert isinstance(qid, int)
    assert qid > 0


def test_enqueue_dedup_by_url_hash(storage):
    """同 URL 入队两次应去重，返回相同 id，queue 表只有一条记录。"""
    url = "http://example.com/dup"
    qid1 = storage.enqueue(url, parser_name="list")
    qid2 = storage.enqueue(url, parser_name="list")
    assert qid1 == qid2, "同 URL 入队两次应返回相同 id"
    count = storage.execute("SELECT COUNT(*) FROM queue WHERE url = ?", (url,), fetch="one")[0]
    assert count == 1, "queue 表不应有重复 URL"


def test_enqueue_different_urls_different_ids(storage):
    """不同 URL 入队应得不同 id。"""
    qid1 = storage.enqueue("http://example.com/a")
    qid2 = storage.enqueue("http://example.com/b")
    assert qid1 != qid2


def test_enqueue_records_parser_name_and_priority(storage):
    """enqueue 应正确记录 parser_name 与 priority。"""
    qid = storage.enqueue("http://example.com/x", parser_name="detail", priority=5)
    row = storage.execute(
        "SELECT parser_name, priority, status FROM queue WHERE id = ?",
        (qid,),
        fetch="one",
    )
    assert row["parser_name"] == "detail"
    assert row["priority"] == 5
    assert row["status"] == "pending"  # 默认值


def test_enqueue_with_parent_id(storage):
    """parent_id 应正确写入。"""
    parent = storage.enqueue("http://example.com/parent")
    child = storage.enqueue("http://example.com/child", parent_id=parent)
    row = storage.execute(
        "SELECT parent_id FROM queue WHERE id = ?", (child,), fetch="one"
    )
    assert row["parent_id"] == parent


def test_enqueue_also_adds_to_seen_urls(storage):
    """enqueue 应同步更新 seen_urls。"""
    url = "http://example.com/seen-test"
    storage.enqueue(url)
    assert storage.is_url_seen(url)


# ---------------- seen_urls 表 CRUD ----------------

def test_add_seen_url_returns_hash(storage):
    """add_seen_url 应返回 url_hash。"""
    url = "http://example.com/hash-test"
    h = storage.add_seen_url(url)
    assert isinstance(h, str)
    assert len(h) == 64  # sha256 hex 长度


def test_is_url_seen_false_for_unseen(storage):
    assert not storage.is_url_seen("http://never-seen.example.com")


def test_is_url_seen_true_after_add(storage):
    url = "http://example.com/once"
    storage.add_seen_url(url)
    assert storage.is_url_seen(url)


def test_add_seen_url_increments_fetch_count(storage):
    """重复 add 应 fetch_count + 1，且 first_seen 不变。"""
    url = "http://example.com/multi"
    h = storage.add_seen_url(url)
    storage.add_seen_url(url)
    storage.add_seen_url(url)
    row = storage.execute(
        "SELECT fetch_count, first_seen, last_seen FROM seen_urls WHERE url_hash = ?",
        (h,),
        fetch="one",
    )
    assert row["fetch_count"] == 3


def test_add_seen_url_updates_last_seen(storage):
    """重复 add 应更新 last_seen。"""
    url = "http://example.com/last-seen"
    storage.add_seen_url(url)
    first_row = storage.execute(
        "SELECT first_seen, last_seen FROM seen_urls WHERE url_hash = ?",
        (storage_module._hash_url(url),),
        fetch="one",
    )
    # 再 add 一次（last_seen 应 >= 第一次的 last_seen）
    storage.add_seen_url(url)
    second_row = storage.execute(
        "SELECT first_seen, last_seen FROM seen_urls WHERE url_hash = ?",
        (storage_module._hash_url(url),),
        fetch="one",
    )
    assert second_row["first_seen"] == first_row["first_seen"]
    assert second_row["last_seen"] >= first_row["last_seen"]


# ---------------- requests 表 CRUD ----------------

def test_create_request_returns_id(storage):
    """create_request 应返回 int 类型的 request id。"""
    qid = storage.enqueue("http://example.com/r1")
    rid = storage.create_request(qid, "http://example.com/r1", proxy_ip="1.2.3.4")
    assert isinstance(rid, int)
    assert rid > 0


def test_create_request_defaults(storage):
    """create_request 应正确写入默认 method=GET。"""
    qid = storage.enqueue("http://example.com/r2")
    rid = storage.create_request(qid, "http://example.com/r2", proxy_ip=None)
    row = storage.execute(
        "SELECT queue_id, url, proxy_ip, method, request_status FROM requests WHERE id = ?",
        (rid,),
        fetch="one",
    )
    assert row["queue_id"] == qid
    assert row["url"] == "http://example.com/r2"
    assert row["proxy_ip"] is None
    assert row["method"] == "GET"
    assert row["request_status"] is None  # 未设置


def test_mark_request_success_with_dict(storage):
    """mark_request_success 应将 dict 序列化为 JSON。"""
    qid = storage.enqueue("http://example.com/s1")
    rid = storage.create_request(qid, "http://example.com/s1", "1.1.1.1")
    data = {"title": "测试", "price": 9.9}
    imgs = ["/data/images/1.jpg", "/data/images/2.jpg"]
    storage.mark_request_success(
        rid,
        extracted_data=data,
        image_paths=imgs,
        duration_ms=123,
        response_size=4096,
        status_code=200,
    )
    row = storage.execute(
        "SELECT status_code, duration_ms, response_size, extracted_data, "
        "image_paths, request_status FROM requests WHERE id = ?",
        (rid,),
        fetch="one",
    )
    assert row["status_code"] == 200
    assert row["duration_ms"] == 123
    assert row["response_size"] == 4096
    assert row["request_status"] == "success"
    assert json.loads(row["extracted_data"]) == data
    assert json.loads(row["image_paths"]) == imgs


def test_mark_request_success_with_string(storage):
    """extracted_data 传 str 时应原样写入。"""
    qid = storage.enqueue("http://example.com/s2")
    rid = storage.create_request(qid, "http://example.com/s2", "1.1.1.1")
    storage.mark_request_success(rid, extracted_data='{"raw": 1}', image_paths="[]")
    row = storage.execute(
        "SELECT extracted_data, image_paths FROM requests WHERE id = ?",
        (rid,),
        fetch="one",
    )
    assert row["extracted_data"] == '{"raw": 1}'
    assert row["image_paths"] == "[]"


def test_mark_request_failed(storage):
    """mark_request_failed 应写入 error_msg 与状态。"""
    qid = storage.enqueue("http://example.com/f1")
    rid = storage.create_request(qid, "http://example.com/f1", "2.2.2.2")
    storage.mark_request_failed(rid, error_msg="timeout", status_code=504)
    row = storage.execute(
        "SELECT status_code, error_msg, request_status FROM requests WHERE id = ?",
        (rid,),
        fetch="one",
    )
    assert row["status_code"] == 504
    assert row["error_msg"] == "timeout"
    assert row["request_status"] == "failed"


def test_mark_request_failed_no_status_code(storage):
    """status_code 可为 None。"""
    qid = storage.enqueue("http://example.com/f2")
    rid = storage.create_request(qid, "http://example.com/f2", "3.3.3.3")
    storage.mark_request_failed(rid, error_msg="network error")
    row = storage.execute(
        "SELECT status_code, error_msg, request_status FROM requests WHERE id = ?",
        (rid,),
        fetch="one",
    )
    assert row["status_code"] is None
    assert row["error_msg"] == "network error"
    assert row["request_status"] == "failed"


# ---------------- 业务表自动建表 ----------------

def test_ensure_business_table_creates_table(storage):
    """首次调用应建表。"""
    schema = """
        CREATE TABLE ershouche_cars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id      TEXT UNIQUE NOT NULL,
            title       TEXT,
            price       REAL,
            crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    storage.ensure_business_table("ershouche_cars", schema)
    tables = set(_list_tables(storage))
    assert "ershouche_cars" in tables


def test_ensure_business_table_idempotent(storage):
    """重复调用不应报错，不应重建。"""
    schema = """
        CREATE TABLE ershouche_cars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id      TEXT UNIQUE NOT NULL,
            title       TEXT
        )
    """
    storage.ensure_business_table("ershouche_cars", schema)
    # 再调用一次不应抛异常
    storage.ensure_business_table("ershouche_cars", schema)
    # 表仍应存在
    tables = set(_list_tables(storage))
    assert "ershouche_cars" in tables


def test_ensure_business_table_multiple(storage):
    """多个业务表可同时存在。"""
    storage.ensure_business_table(
        "t_a",
        "CREATE TABLE t_a (id INTEGER PRIMARY KEY, v TEXT)",
    )
    storage.ensure_business_table(
        "t_b",
        "CREATE TABLE t_b (id INTEGER PRIMARY KEY, v TEXT)",
    )
    tables = set(_list_tables(storage))
    assert "t_a" in tables
    assert "t_b" in tables


# ---------------- save_business_data ----------------

def test_save_business_data_batch_insert(storage):
    """批量插入多行应全部成功。"""
    storage.ensure_business_table(
        "t_batch",
        "CREATE TABLE t_batch (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, val INTEGER)",
    )
    rows = [
        {"name": "a", "val": 1},
        {"name": "b", "val": 2},
        {"name": "c", "val": 3},
    ]
    storage.save_business_data("t_batch", rows)
    result = storage.execute("SELECT name, val FROM t_batch ORDER BY val", fetch="all")
    assert [(r[0], r[1]) for r in result] == [("a", 1), ("b", 2), ("c", 3)]


def test_save_business_data_empty_rows(storage):
    """空 rows 列表不应报错。"""
    storage.ensure_business_table(
        "t_empty",
        "CREATE TABLE t_empty (id INTEGER PRIMARY KEY, v TEXT)",
    )
    storage.save_business_data("t_empty", [])
    count = storage.execute("SELECT COUNT(*) FROM t_empty", fetch="one")[0]
    assert count == 0


# ── 图片下载队列 ──────────────────────────────────────────────

def test_enqueue_image_returns_id(storage):
    id1 = storage.enqueue_image("https://x.com/a.jpg")
    assert id1 is not None
    id2 = storage.enqueue_image("https://x.com/b.jpg")
    assert id2 > id1


def test_enqueue_image_dedupes_by_url(storage):
    storage.enqueue_image("https://x.com/a.jpg")
    assert storage.enqueue_image("https://x.com/a.jpg") is None


def test_acquire_pending_images(storage):
    storage.enqueue_image("https://x.com/a.jpg")
    storage.enqueue_image("https://x.com/b.jpg")
    items = storage.acquire_pending_images(10)
    assert len(items) == 2
    assert items[0]["url"] == "https://x.com/a.jpg"
    assert items[0]["retry_count"] == 0


def test_mark_image_done_then_status_is_done(storage):
    sid = storage.enqueue_image("https://x.com/a.jpg")
    storage.acquire_pending_images(10)
    storage.mark_image_done(sid, "abc123.jpg")
    row = storage.execute(
        "SELECT status, local_path FROM image_queue WHERE id=?", (sid,), fetch="one"
    )
    assert row[0] == "done"
    assert row[1] == "abc123.jpg"


def test_mark_image_failed_retries_then_fails(storage):
    sid = storage.enqueue_image("https://x.com/a.jpg", max_retry=2)
    storage.acquire_pending_images(10)
    # 第一次失败 → 重回 pending
    assert storage.mark_image_failed(sid, "timeout") == "pending"
    row = storage.execute("SELECT status, retry_count FROM image_queue WHERE id=?", (sid,), fetch="one")
    assert row[0] == "pending"
    assert row[1] == 1
    # acquire 再次拉取
    items = storage.acquire_pending_images(10)
    assert len(items) == 1
    # 第二次失败 → failed (retry >= max_retry)
    assert storage.mark_image_failed(sid, "timeout again") == "failed"
    row = storage.execute("SELECT status, retry_count FROM image_queue WHERE id=?", (sid,), fetch="one")
    assert row[0] == "failed"
    assert row[1] == 2


def test_image_queue_stats(storage):
    storage.enqueue_image("https://x.com/a.jpg")
    storage.enqueue_image("https://x.com/b.jpg")
    items = storage.acquire_pending_images(1)
    storage.mark_image_done(items[0]["id"], "a.jpg")
    stats = storage.image_queue_stats()
    assert stats.get("done", 0) == 1
    assert stats.get("pending", 0) == 1  # b.jpg 未被 acquire 或 acquire 后被 reset
    # Note: acquire 会将已拉取的行标记为 downloading，但只有一个被 acquire
    # 另一个仍在 pending；若 acquire 内部事务提交后调用 stats, downloading 也应为 0
    # 因 b.jpg 未被 acquire，状态仍为 pending

def test_save_business_data_single_row(storage):
    """单行插入也应工作。"""
    storage.ensure_business_table(
        "t_single",
        "CREATE TABLE t_single (id INTEGER PRIMARY KEY AUTOINCREMENT, k TEXT, v TEXT)",
    )
    storage.save_business_data("t_single", [{"k": "key1", "v": "value1"}])
    row = storage.execute(
        "SELECT k, v FROM t_single WHERE k = ?", ("key1",), fetch="one"
    )
    assert row["v"] == "value1"


def test_save_business_data_chinese_values(storage):
    """中文值应正确写入与读取。"""
    storage.ensure_business_table(
        "t_cn",
        "CREATE TABLE t_cn (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)",
    )
    storage.save_business_data("t_cn", [{"title": "中文标题"}, {"title": "另一标题"}])
    rows = storage.execute("SELECT title FROM t_cn ORDER BY id", fetch="all")
    assert [r[0] for r in rows] == ["中文标题", "另一标题"]


# ---------------- get_connection 上下文管理器 ----------------

def test_get_connection_yields_sqlite_connection(storage):
    """get_connection 应 yield sqlite3.Connection。"""
    import sqlite3
    with storage.get_connection() as conn:
        assert isinstance(conn, sqlite3.Connection)


def test_get_connection_commit_on_exit(storage):
    """with 块内的写操作应自动 commit。"""
    with storage.get_connection() as conn:
        conn.execute(
            "INSERT INTO config (key, value, description) VALUES (?, ?, ?)",
            ("test_key", "test_value", "from get_connection"),
        )
    row = storage.execute(
        "SELECT value FROM config WHERE key = ?", ("test_key",), fetch="one"
    )
    assert row["value"] == "test_value"


def test_get_connection_rollback_on_exception(storage):
    """with 块抛异常时应 rollback。"""
    try:
        with storage.get_connection() as conn:
            conn.execute(
                "INSERT INTO config (key, value) VALUES (?, ?)",
                ("will_rollback", "v"),
            )
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    row = storage.execute(
        "SELECT 1 FROM config WHERE key = ?", ("will_rollback",), fetch="one"
    )
    assert row is None


# ---------------- execute 通用接口 ----------------

def test_execute_fetch_none(storage):
    """fetch='none' 应返回 None。"""
    result = storage.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)",
        ("k_none", "v_none"),
        fetch="none",
    )
    assert result is None


def test_execute_fetch_one(storage):
    """fetch='one' 应返回单行。"""
    storage.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)",
        ("k_one", "v_one"),
    )
    row = storage.execute(
        "SELECT value FROM config WHERE key = ?", ("k_one",), fetch="one"
    )
    assert row["value"] == "v_one"


def test_execute_fetch_all(storage):
    """fetch='all' 应返回 list。"""
    storage.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)", ("k1", "v1")
    )
    storage.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)", ("k2", "v2")
    )
    rows = storage.execute(
        "SELECT key FROM config ORDER BY key", fetch="all"
    )
    keys = [r["key"] for r in rows]
    assert keys == ["k1", "k2"]


def test_execute_fetch_one_returns_none_when_no_match(storage):
    """无匹配时应返回 None。"""
    row = storage.execute(
        "SELECT 1 FROM config WHERE key = ?", ("nonexistent",), fetch="one"
    )
    assert row is None


def test_execute_default_fetch_is_none(storage):
    """默认 fetch 应为 'none'。"""
    result = storage.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)", ("default", "v")
    )
    assert result is None


# ---------------- 线程安全 ----------------

def test_concurrent_enqueue_no_duplicates(tmp_path):
    """多线程并发 enqueue 同一 URL，queue 表不应有重复。"""
    db_path = tmp_path / "thread_test.db"
    storage = Storage(str(db_path))
    url = "http://example.com/concurrent"
    results: list[int] = []
    results_lock = threading.Lock()
    errors: list[Exception] = []

    def worker():
        try:
            qid = storage.enqueue(url)
            with results_lock:
                results.append(qid)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"线程出错: {errors}"
    # 所有线程应返回同一个 queue_id
    assert len(set(results)) == 1, f"并发 enqueue 应返回同一 id，实际: {results}"
    # queue 表应有且只有一条
    count = storage.execute(
        "SELECT COUNT(*) FROM queue WHERE url = ?", (url,), fetch="one"
    )[0]
    assert count == 1
    storage.close()


def test_concurrent_enqueue_different_urls(tmp_path):
    """多线程并发 enqueue 不同 URL，应全部成功。"""
    db_path = tmp_path / "thread_test2.db"
    storage = Storage(str(db_path))
    results: list[int] = []
    results_lock = threading.Lock()
    errors: list[Exception] = []

    def worker(url: str):
        try:
            qid = storage.enqueue(url)
            with results_lock:
                results.append(qid)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=(f"http://example.com/u{i}",))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"线程出错: {errors}"
    # 应有 20 个不同的 id
    assert len(set(results)) == 20
    count = storage.execute("SELECT COUNT(*) FROM queue", fetch="one")[0]
    assert count == 20
    storage.close()


# ---------------- 上下文管理协议 ----------------

def test_storage_context_manager_closes_connection(tmp_path):
    """with Storage() 退出后连接应关闭。"""
    db_path = tmp_path / "ctx.db"
    with Storage(str(db_path)) as s:
        s.enqueue("http://example.com/ctx")
    # 退出后再次使用应抛异常（连接已关闭）
    with pytest.raises(Exception):
        s.execute("SELECT 1", fetch="one")


# ---------------- 表结构完整性 ----------------

def test_queue_table_columns(storage):
    """queue 表应包含设计文档中所有列。"""
    cols = storage.execute("PRAGMA table_info(queue)", fetch="all")
    names = {c[1] for c in cols}
    expected = {
        "id",
        "url",
        "url_hash",
        "parser_name",
        "status",
        "retry_count",
        "ip_switch_count",
        "priority",
        "parent_id",
        "created_at",
        "started_at",
        "finished_at",
        "error_msg",
        "error_type",
    }
    assert expected.issubset(names), f"queue 表缺少列: {expected - names}"


def test_proxy_pool_table_columns(storage):
    """proxy_pool 表应包含设计文档中所有列。"""
    cols = storage.execute("PRAGMA table_info(proxy_pool)", fetch="all")
    names = {c[1] for c in cols}
    expected = {
        "id",
        "ip",
        "port",
        "protocol",
        "city",
        "fetched_at",
        "expire_at",
        "use_count",
        "max_use",
        "status",
        "fail_count",
        "last_used_at",
        "cooldown_until",
    }
    assert expected.issubset(names), f"proxy_pool 表缺少列: {expected - names}"


def test_seen_urls_primary_key_is_url_hash(storage):
    """seen_urls 的主键应为 url_hash。"""
    cols = storage.execute("PRAGMA table_info(seen_urls)", fetch="all")
    pk_cols = [c[1] for c in cols if c[5]]  # c[5] is pk flag
    assert pk_cols == ["url_hash"]


def test_queue_url_hash_is_unique(storage):
    """queue.url_hash 应有 UNIQUE 约束。"""
    # 尝试直接插入两条相同 url_hash 应失败
    storage.execute(
        "INSERT INTO queue (url, url_hash) VALUES (?, ?)",
        ("http://a", "HASH_A"),
    )
    with pytest.raises(Exception):
        storage.execute(
            "INSERT INTO queue (url, url_hash) VALUES (?, ?)",
            ("http://b", "HASH_A"),  # 相同 hash
        )


# ---------------- 不污染真实 DB ----------------

def test_does_not_touch_real_db(tmp_path):
    """测试运行不应创建真实 data/crawler.db（确保隔离）。"""
    # 这个测试本身不操作真实 DB，但通过断言强化隔离意识
    from config import DB_PATH
    # 注意：这里不删除真实 DB（其他测试可能已创建），
    # 只验证我们的 fixture 用的是 tmp_path 下的 db
    storage = Storage(str(tmp_path / "isolated.db"))
    storage.enqueue("http://example.com/isolated")
    storage.close()
    # 真实 DB_PATH 不应被本次测试影响（不验证其存在性，仅验证 tmp_path 下有 DB）
    assert (tmp_path / "isolated.db").exists()
    # 真实 DB 不应包含我们的测试 URL
    if os.path.exists(DB_PATH):
        # 用一个新连接读真实 DB（不通过 fixture）
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                "SELECT 1 FROM queue WHERE url = ?", ("http://example.com/isolated",)
            ).fetchone()
            assert row is None, "测试不应污染真实 DB"
        finally:
            conn.close()


# ---------------- C1: get_connection 内调用 execute 不死锁 ----------------

def test_get_connection_call_execute_no_deadlock(storage):
    """在 get_connection 事务块内调用 execute 不应死锁（暴露 C1）。

    使用 threading.Lock（不可重入）时，同线程再次 acquire 会永久阻塞；
    RLock 允许同线程多次 acquire。用独立线程 + 超时确保失败时不会挂死测试套件。
    """
    result = {"done": False, "error": None}

    def call():
        try:
            with storage.get_connection() as conn:
                conn.execute(
                    "INSERT INTO config (key, value) VALUES (?, ?)",
                    ("in_txn", "v1"),
                )
                # 同线程在持锁期间调用 execute（依赖 RLock 可重入）
                storage.execute(
                    "INSERT INTO config (key, value) VALUES (?, ?)",
                    ("via_execute", "v2"),
                )
            result["done"] = True
        except BaseException as e:
            result["error"] = e

    t = threading.Thread(target=call)
    t.start()
    t.join(timeout=5.0)

    assert not t.is_alive(), "execute 在 get_connection 内死锁（5s 内未完成）"
    assert result["error"] is None, f"意外异常: {result['error']!r}"
    assert result["done"]
    # 两笔写入都应可见（事务已 commit）
    rows = storage.execute(
        "SELECT key FROM config WHERE key IN (?, ?) ORDER BY key",
        ("in_txn", "via_execute"),
        fetch="all",
    )
    keys = [r[0] for r in rows]
    assert keys == ["in_txn", "via_execute"]


# ---------------- I1: enqueue 原子性 ----------------

def test_enqueue_atomic_with_seen_urls(tmp_path):
    """enqueue 中 seen_urls 写入失败时应整体回滚（queue 也不写入）。

    通过 SQLite 触发器在 seen_urls INSERT 时模拟失败，验证 get_connection
    事务回滚能撤销之前已写入的 queue 行（修复前 enqueue 拆两段，queue 已 commit）。
    """
    db_path = tmp_path / "atomic.db"
    storage = Storage(str(db_path))
    target_url = "http://example.com/atomic-test"

    # 在 seen_urls 表上建一个 BEFORE INSERT 触发器，遇到目标 URL 时 ABORT
    # （URL 为固定字符串且不含单引号，直接内联到 DDL 是安全的）
    storage.execute(
        "CREATE TRIGGER fail_on_target_url "
        "BEFORE INSERT ON seen_urls "
        "WHEN NEW.url = 'http://example.com/atomic-test' "
        "BEGIN "
        "    SELECT RAISE(ABORT, 'simulated crash during seen_urls write'); "
        "END"
    )

    # enqueue 应抛 sqlite3.Error（触发器 RAISE(ABORT) 在 Python 中映射为
    # IntegrityError，它是 sqlite3.Error 的子类）
    with pytest.raises(sqlite3.Error):
        storage.enqueue(target_url)

    # 验证 queue 也没写入（事务回滚）
    queue_count = storage.execute(
        "SELECT COUNT(*) FROM queue WHERE url = ?",
        (target_url,),
        fetch="one",
    )[0]
    assert queue_count == 0, "enqueue 应原子：seen_urls 失败时 queue 不应写入"

    # seen_urls 也不应有记录
    seen_count = storage.execute(
        "SELECT COUNT(*) FROM seen_urls WHERE url = ?",
        (target_url,),
        fetch="one",
    )[0]
    assert seen_count == 0

    # 其他正常 URL 仍可 enqueue（验证 trigger 只针对目标 URL，DB 仍可用）
    other_qid = storage.enqueue("http://example.com/other")
    assert other_qid > 0
    storage.close()


# ---------------- I2: save_business_data 标识符校验 ----------------

def test_save_business_data_rejects_invalid_identifier(storage):
    """非法表名/列名应抛 ValueError，不执行任何 SQL。"""
    # 非法表名（包含分号）
    with pytest.raises(ValueError):
        storage.save_business_data(
            "foo; DROP TABLE queue; --",
            [{"a": 1}],
        )

    # 合法表名但非法列名
    storage.ensure_business_table(
        "t_valid",
        "CREATE TABLE t_valid (id INTEGER PRIMARY KEY, v TEXT)",
    )
    with pytest.raises(ValueError):
        storage.save_business_data(
            "t_valid",
            [{"id": 1, "v; DROP TABLE queue; --": "evil"}],
        )

    # 数字开头的非法列名
    with pytest.raises(ValueError):
        storage.save_business_data("t_valid", [{"1bad": "x"}])

    # 验证 queue 表依然存在（未被执行任何破坏性 SQL）
    tables = set(_list_tables(storage))
    assert "queue" in tables
    # t_valid 应仍然存在且为空（非法列名调用未写入任何数据）
    assert "t_valid" in tables
    count = storage.execute("SELECT COUNT(*) FROM t_valid", fetch="one")[0]
    assert count == 0


# ---------------- I3: ensure_business_table 多语句防护 ----------------

def test_ensure_business_table_rejects_multi_statement(storage):
    """多语句 schema 应抛 ValueError。"""
    # 多语句注入：CREATE TABLE ...; DROP TABLE queue; --
    with pytest.raises(ValueError):
        storage.ensure_business_table(
            "t_inject",
            "CREATE TABLE t_inject (id INTEGER); DROP TABLE queue; --",
        )

    # 非 CREATE TABLE 开头
    with pytest.raises(ValueError):
        storage.ensure_business_table(
            "t_drop",
            "DROP TABLE queue",
        )

    # 非法表名（包含分号）
    with pytest.raises(ValueError):
        storage.ensure_business_table(
            "t; DROP TABLE queue; --",
            "CREATE TABLE t (id INTEGER)",
        )

    # queue 表依然存在（未被执行任何破坏性 SQL）
    tables = set(_list_tables(storage))
    assert "queue" in tables
    # t_inject / t_drop 不应被创建
    assert "t_inject" not in tables
    assert "t_drop" not in tables
