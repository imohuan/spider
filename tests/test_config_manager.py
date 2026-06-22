"""config_manager 模块测试 - 默认配置初始化、类型化读写、幂等性、批量与边界。

测试覆盖：
- init_defaults: 25 项全部写入；重复调用不覆盖已修改值（幂等）
- get / get_int / get_bool / get_float: 类型化读取与默认值
- set: 写入 + updated_at 自动更新；bool/数字正确转字符串；description 可选更新
- set_many: 批量写入原子性
- get_all: 全量读取为 dict
- 类型转换边界: 非数字字符串、大小写、空白、未知 bool 值
- 不存在的 key 返回 default
- 全部用 tmp_path 隔离，不污染真实 DB
"""
import time

import pytest

from core.config_manager import ConfigManager, _DEFAULT_CONFIGS
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


# ---------------- init_defaults ----------------

def test_init_defaults_creates_all_items(cfg):
    """所有默认配置必须全部写入。"""
    all_cfg = cfg.get_all()
    expected_keys = {key for key, _, _ in _DEFAULT_CONFIGS}
    assert set(all_cfg.keys()) == expected_keys
    assert len(all_cfg) == len(_DEFAULT_CONFIGS)


def test_init_defaults_values_match_design_doc(cfg):
    """默认值与描述必须与设计文档表格一致。"""
    for key, expected_value, expected_desc in _DEFAULT_CONFIGS:
        # value 一致
        assert cfg.get(key) == expected_value, f"{key}: 期望 {expected_value!r}"
        # description 一致
        row = cfg.storage.execute(
            "SELECT description FROM config WHERE key = ?",
            (key,),
            fetch="one",
        )
        assert row[0] == expected_desc, f"{key} description: 期望 {expected_desc!r}"


def test_init_defaults_is_idempotent(cfg):
    """重复调用 init_defaults 不应覆盖已修改的值。"""
    # 修改一个值
    cfg.set("proxy_provider", "kuaidaili")
    cfg.set("proxy_fetch_num", "20")
    # 再次调用 init_defaults
    cfg.init_defaults()
    # 已修改的值必须保留
    assert cfg.get("proxy_provider") == "kuaidaili"
    assert cfg.get("proxy_fetch_num") == "20"
    # 未修改的值仍是默认值
    assert cfg.get("proxy_enabled") == "true"
    assert cfg.get_int("proxy_ttl") == 60


def test_init_defaults_on_empty_db(storage):
    """空库上首次调用 init_defaults 应写入全部默认项。"""
    c = ConfigManager(storage)
    assert c.get_all() == {}
    c.init_defaults()
    assert len(c.get_all()) == len(_DEFAULT_CONFIGS)


def test_init_defaults_does_not_touch_existing_keys(storage):
    """init_defaults 不应覆盖已存在的 key（即便 value 与默认值不同）。"""
    # 预先写入一个 key（值与默认不同）
    storage.execute(
        "INSERT INTO config (key, value, description) VALUES (?, ?, ?)",
        ("log_level", "DEBUG", "用户自定义"),
    )
    c = ConfigManager(storage)
    c.init_defaults()
    # log_level 必须保留用户的值和描述
    assert c.get("log_level") == "DEBUG"
    row = storage.execute(
        "SELECT description FROM config WHERE key = ?",
        ("log_level",),
        fetch="one",
    )
    assert row[0] == "用户自定义"


# ---------------- get ----------------

def test_get_existing_key(cfg):
    assert cfg.get("proxy_provider") == "juliang"


def test_get_missing_key_returns_default(cfg):
    assert cfg.get("nonexistent_key") is None
    assert cfg.get("nonexistent_key", "fallback") == "fallback"


def test_get_empty_string_value(storage):
    """proxy_api_url 默认值为空字符串，应能正确读取（不返回 None）。"""
    c = ConfigManager(storage)
    c.init_defaults()
    # 空字符串与 None 区分
    assert c.get("proxy_api_url") == ""
    assert c.get("proxy_api_url", "default") == ""  # 已存在，不返回 default


# ---------------- get_int ----------------

@pytest.mark.parametrize(
    "key,expected",
    [
        ("proxy_fetch_num", 3),
        ("proxy_ttl", 60),
        ("proxy_max_use", 3),
        ("proxy_health_interval", 300),
        ("cache_html_ttl", 86400),
        ("request_concurrency", 3),
        ("request_timeout", 30),
        ("retry_network", 3),
        ("retry_5xx", 2),
        ("domain_rate_limit", 10),
        ("ip_rate_limit", 5),
        ("captcha_max_retry", 3),
        ("captcha_max_switch", 5),
        ("captcha_cooldown", 1800),
    ],
)
def test_get_int_for_all_integer_defaults(cfg, key, expected):
    assert cfg.get_int(key) == expected


def test_get_int_missing_key_returns_default(cfg):
    assert cfg.get_int("nonexistent") == 0
    assert cfg.get_int("nonexistent", 99) == 99


def test_get_int_non_numeric_returns_default(cfg):
    """非数字字符串应返回 default，不抛异常。"""
    cfg.set("log_level", "INFO")  # 字符串值
    assert cfg.get_int("log_level", -1) == -1


def test_get_int_negative_and_zero(storage):
    """负数与 0 应正确解析。"""
    c = ConfigManager(storage)
    c.set("neg_val", "-42")
    c.set("zero_val", "0")
    assert c.get_int("neg_val") == -42
    assert c.get_int("zero_val") == 0


def test_get_int_float_string_returns_default(cfg):
    """'1.5' 不能直接 int()，应返回 default（保持严格类型）。"""
    cfg.set("float_str", "1.5")
    assert cfg.get_int("float_str", -1) == -1


# ---------------- get_bool ----------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("YES", True),
        ("Yes", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("NO", False),
    ],
)
def test_get_bool_recognizes_canonical_values(storage, value, expected):
    """get_bool 应识别所有约定的真/假值表示，大小写不敏感。"""
    c = ConfigManager(storage)
    c.set("flag", value)
    assert c.get_bool("flag") is expected


def test_get_bool_unknown_value_returns_default(storage):
    """未知字符串应返回 default。"""
    c = ConfigManager(storage)
    c.set("flag", "maybe")
    assert c.get_bool("flag") is False  # default=False
    assert c.get_bool("flag", True) is True  # 显式指定 default=True


def test_get_bool_missing_key_returns_default(cfg):
    assert cfg.get_bool("nonexistent") is False
    assert cfg.get_bool("nonexistent", True) is True


def test_get_bool_with_whitespace(storage):
    """带空白的值应 strip 后再识别。"""
    c = ConfigManager(storage)
    c.set("flag", "  true  ")
    assert c.get_bool("flag") is True


@pytest.mark.parametrize("key", [
    "proxy_enabled",
    "cache_enabled",
    "image_download",
    "captcha_enabled",
    "captcha_auto_solve",
])
def test_get_bool_for_all_bool_defaults(cfg, key):
    """所有默认 bool 配置项默认值都应为 True。"""
    assert cfg.get_bool(key) is True


# ---------------- get_float ----------------

@pytest.mark.parametrize(
    "key,expected",
    [
        ("request_interval_min", 1.0),
        ("request_interval_max", 3.0),
    ],
)
def test_get_float_for_float_defaults(cfg, key, expected):
    assert cfg.get_float(key) == expected


def test_get_float_missing_key_returns_default(cfg):
    assert cfg.get_float("nonexistent") == 0.0
    assert cfg.get_float("nonexistent", 2.5) == 2.5


def test_get_float_non_numeric_returns_default(cfg):
    cfg.set("log_level", "INFO")
    assert cfg.get_float("log_level", -1.5) == -1.5


def test_get_float_integer_string(storage):
    """整数串应能转为 float。"""
    c = ConfigManager(storage)
    c.set("int_str", "42")
    assert c.get_float("int_str") == 42.0


def test_get_float_negative_and_zero(storage):
    c = ConfigManager(storage)
    c.set("neg", "-3.14")
    c.set("zero", "0.0")
    assert c.get_float("neg") == -3.14
    assert c.get_float("zero") == 0.0


# ---------------- set ----------------

def test_set_updates_value(cfg):
    cfg.set("proxy_provider", "kuaidaili")
    assert cfg.get("proxy_provider") == "kuaidaili"


def test_set_updates_updated_at(storage):
    """set 必须更新 updated_at。"""
    c = ConfigManager(storage)
    c.init_defaults()
    # 记录原始 updated_at
    row1 = storage.execute(
        "SELECT updated_at FROM config WHERE key = ?", ("proxy_enabled",), fetch="one",
    )
    original_ts = row1[0]
    # 等待至少 1 秒，确保 CURRENT_TIMESTAMP 不同（SQLite 精度为秒）
    time.sleep(1.1)
    c.set("proxy_enabled", "false")
    row2 = storage.execute(
        "SELECT updated_at FROM config WHERE key = ?", ("proxy_enabled",), fetch="one",
    )
    new_ts = row2[0]
    assert new_ts != original_ts, f"updated_at 未更新: {original_ts} == {new_ts}"


def test_set_with_description_updates_description(cfg):
    """set 传 description 应一并更新。"""
    cfg.set("proxy_provider", "kuaidaili", description="新描述")
    row = cfg.storage.execute(
        "SELECT description FROM config WHERE key = ?",
        ("proxy_provider",),
        fetch="one",
    )
    assert row[0] == "新描述"


def test_set_without_description_keeps_original(cfg):
    """set 不传 description 时，原 description 应保留。"""
    original_desc = cfg.storage.execute(
        "SELECT description FROM config WHERE key = ?",
        ("proxy_provider",),
        fetch="one",
    )[0]
    cfg.set("proxy_provider", "kuaidaili")
    desc = cfg.storage.execute(
        "SELECT description FROM config WHERE key = ?",
        ("proxy_provider",),
        fetch="one",
    )[0]
    assert desc == original_desc


def test_set_bool_value_converts_to_lowercase_string(storage):
    """set(True) 应存为 'true'，与 get_bool 解析规则一致。"""
    c = ConfigManager(storage)
    c.set("flag", True)
    # 直接读原始字符串值
    row = storage.execute(
        "SELECT value FROM config WHERE key = ?", ("flag",), fetch="one",
    )
    assert row[0] == "true"
    # get_bool 能正确读回
    assert c.get_bool("flag") is True

    c.set("flag", False)
    row = storage.execute(
        "SELECT value FROM config WHERE key = ?", ("flag",), fetch="one",
    )
    assert row[0] == "false"
    assert c.get_bool("flag") is False


def test_set_int_value_converts_to_string(storage):
    """set(42) 应存为 '42'。"""
    c = ConfigManager(storage)
    c.set("num", 42)
    assert c.get("num") == "42"
    assert c.get_int("num") == 42


def test_set_float_value_converts_to_string(storage):
    """set(1.5) 应存为 '1.5'。"""
    c = ConfigManager(storage)
    c.set("num", 1.5)
    assert c.get("num") == "1.5"
    assert c.get_float("num") == 1.5


def test_set_new_key(cfg):
    """set 一个新 key 应能创建记录。"""
    cfg.set("custom_key", "custom_value", description="自定义")
    assert cfg.get("custom_key") == "custom_value"
    assert cfg.get_int("custom_key", -1) == -1  # 不是 int


# ---------------- set_many ----------------

def test_set_many_updates_multiple_keys(cfg):
    cfg.set_many({
        "proxy_provider": "kuaidaili",
        "proxy_fetch_num": 20,
        "proxy_enabled": False,
    })
    assert cfg.get("proxy_provider") == "kuaidaili"
    assert cfg.get_int("proxy_fetch_num") == 20
    assert cfg.get("proxy_enabled") == "false"
    assert cfg.get_bool("proxy_enabled") is False


def test_set_many_empty_dict_is_noop(cfg):
    """空 dict 应是 no-op，不抛异常。"""
    before = cfg.get_all()
    cfg.set_many({})
    after = cfg.get_all()
    assert before == after


def test_set_many_atomic_on_error(storage):
    """set_many 应在单事务内执行（全成功或全回滚）。

    通过让第二个 item 的 value 在 str() 转换时抛异常，验证已写入的第一个 key 被回滚。
    """
    c = ConfigManager(storage)
    c.init_defaults()
    original_provider = c.get("proxy_provider")

    class Exploding:
        """str() 调用时抛异常，模拟 set_many 中途失败。"""

        def __str__(self):
            raise RuntimeError("boom")

    bad_items = {
        "proxy_provider": "kuaidaili",  # 这个会先成功执行（在事务内）
        "bad_key": Exploding(),          # 这个会在 str(value) 时抛异常
    }
    with pytest.raises(RuntimeError, match="boom"):
        c.set_many(bad_items)

    # 事务回滚：proxy_provider 应保持原值
    assert c.get("proxy_provider") == original_provider
    # bad_key 也不应存在
    assert c.get("bad_key") is None


# ---------------- get_all ----------------

def test_get_all_returns_dict(cfg):
    all_cfg = cfg.get_all()
    assert isinstance(all_cfg, dict)
    assert len(all_cfg) == len(_DEFAULT_CONFIGS)


def test_get_all_values_are_strings(cfg):
    """所有 value 应为 str 类型（与 schema TEXT 一致）。"""
    for key, value in cfg.get_all().items():
        assert isinstance(value, str), f"{key} 的 value 不是 str: {type(value)}"


def test_get_all_on_empty_db(storage):
    """空库上 get_all 应返回空 dict，不抛异常。"""
    c = ConfigManager(storage)
    assert c.get_all() == {}


# ---------------- 线程安全 ----------------

def test_concurrent_set_is_thread_safe(storage):
    """多线程并发 set 不应损坏数据库（复用 Storage 的锁）。"""
    import threading

    c = ConfigManager(storage)
    c.init_defaults()

    errors: list[Exception] = []

    def worker(tid: int) -> None:
        try:
            for i in range(20):
                c.set(f"thread_{tid}_key_{i}", str(i))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"并发写出现异常: {errors}"
    # 每个线程写 20 个 key，共 100 个
    thread_keys = [k for k in c.get_all() if k.startswith("thread_")]
    assert len(thread_keys) == 100
