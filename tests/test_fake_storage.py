"""FakeStorage 测试 - 验证写入方法为空操作，读方法正常委托。"""
import sqlite3

import pytest

from core.fake_storage import FakeStorage
from core.storage import Storage


# ---------------- fixtures ----------------

@pytest.fixture
def storage(tmp_path):
    """用 tmp_path 隔离的底层 Storage。"""
    db_path = tmp_path / "test.db"
    s = Storage(str(db_path))
    yield s
    s.close()


@pytest.fixture
def fake(storage):
    """包装 storage 的 FakeStorage 实例。"""
    return FakeStorage(storage)


# ---------------- no-op 写入方法 ----------------

def test_enqueue_returns_none(fake, storage):
    assert fake.enqueue("http://example.com/test") is None
    # 验证未写入底层 DB
    count = storage.execute("SELECT COUNT(*) FROM queue", fetch="one")[0]
    assert count == 0


def test_enqueue_image_returns_none(fake):
    assert fake.enqueue_image("http://example.com/img.jpg") is None


def test_save_business_data_returns_none(fake):
    assert fake.save_business_data("t", [{"a": 1}]) is None


def test_create_request_returns_minus_one(fake):
    assert fake.create_request(1, "http://x", proxy_ip=None) == -1


def test_mark_request_success_is_noop(fake):
    assert fake.mark_request_success(1) is None


def test_mark_request_failed_is_noop(fake):
    assert fake.mark_request_failed(1, error_msg="err") is None


def test_add_seen_url_returns_empty_string(fake):
    assert fake.add_seen_url("http://example.com/x") == ""


def test_is_url_seen_always_false(fake):
    assert fake.is_url_seen("http://example.com/x") is False
    assert fake.is_url_seen("http://never-seen-before.com") is False


# ---------------- 委托方法 ----------------

def test_execute_delegates(fake, storage):
    storage.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER)")
    storage.execute("INSERT INTO t VALUES (1)")
    row = fake.execute("SELECT id FROM t", fetch="one")
    assert row[0] == 1


def test_ensure_business_table_delegates(fake, storage):
    fake.ensure_business_table("t_fake_test", "CREATE TABLE t_fake_test (id INTEGER PRIMARY KEY, v TEXT)")
    row = storage.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='t_fake_test'",
        fetch="one",
    )
    assert row is not None


def test_get_connection_delegates(fake):
    with fake.get_connection() as conn:
        assert isinstance(conn, sqlite3.Connection)


def test_cursor_raises_attribute_error(fake):
    with pytest.raises(AttributeError):
        fake.cursor()


# ---------------- 生命周期 ----------------

def test_close_is_noop(fake, storage):
    fake.close()
    # 底层连接应仍可用
    row = storage.execute("SELECT 1", fetch="one")
    assert row[0] == 1


def test_init_db_is_noop(fake):
    fake.init_db()  # 不应抛异常


def test_context_manager(fake, storage):
    with fake as f:
        assert f is fake
    # __exit__ 后底层连接仍可用
    row = storage.execute("SELECT 1", fetch="one")
    assert row[0] == 1


def test_context_manager_enter_exit(fake):
    """__enter__ 返回自身，__exit__ 不抛异常。"""
    assert fake.__enter__() is fake
    assert fake.__exit__(None, None, None) is None
