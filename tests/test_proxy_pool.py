"""proxy_pool / provider / health_check 模块测试。

覆盖：
- ProxyPool.acquire / release_success / release_fail 生命周期
- IP 池低水位补充（mock provider）
- 健康检查：过期清理、冷却恢复、dead 物理删除
- 禁用模式（proxy_enabled=false）
- ProxyProvider JSON / 文本格式解析
- HealthChecker.check_one（mock httpx）
- 全部用 tmp_path 隔离
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config_manager import ConfigManager
from core.storage import Storage
from proxy.health_check import HealthChecker
from proxy.pool import (
    STATUS_COOLDOWN,
    STATUS_DEAD,
    STATUS_IDLE,
    STATUS_IN_USE,
    ProxyPool,
)
from proxy.provider import (
    JuliangProvider,
    KuaidailiProvider,
    ProxyRecord,
    make_provider,
)


# ---------------- fixtures ----------------


@pytest.fixture
def storage(tmp_path):
    db_path = tmp_path / "test.db"
    s = Storage(str(db_path))
    yield s
    s.close()


@pytest.fixture
def cfg(storage):
    c = ConfigManager(storage)
    c.init_defaults()
    return c


@pytest.fixture
def mock_provider():
    """返回固定 IP 列表的 mock provider。"""
    p = MagicMock()
    p.fetch.return_value = [
        ProxyRecord(ip="1.1.1.1", port=8080),
        ProxyRecord(ip="2.2.2.2", port=8080),
        ProxyRecord(ip="3.3.3.3", port=8080),
    ]
    return p


@pytest.fixture
def pool(storage, cfg, mock_provider):
    return ProxyPool(storage, cfg, mock_provider)


# ---------------- 辅助 ----------------


def _insert_ip(
    storage, ip, port=8080, status=STATUS_IDLE, use_count=0, max_use=3,
    fail_count=0, expire_at=None, cooldown_until=None,
):
    """直接插入一条 proxy_pool 记录，返回 id。"""
    if expire_at is None:
        expire_at = (datetime.now(timezone.utc) + timedelta(seconds=3600)).isoformat()
    with storage.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO proxy_pool (ip, port, protocol, expire_at, use_count, max_use, "
            "                        status, fail_count, cooldown_until) "
            "VALUES (?, ?, 'http', ?, ?, ?, ?, ?, ?)",
            (ip, port, expire_at, use_count, max_use, status, fail_count, cooldown_until),
        )
        return cur.lastrowid


def _get_pool_field(storage, pid, field):
    row = storage.execute(
        f"SELECT {field} FROM proxy_pool WHERE id = ?",
        (pid,),
        fetch="one",
    )
    return row[0] if row else None


# ---------------- acquire ----------------


def test_acquire_disabled_returns_none(storage, cfg):
    """proxy_enabled=false 时 acquire 返回 None。"""
    cfg.set("proxy_enabled", "false")
    p = ProxyPool(storage, cfg, None)
    assert p.acquire() is None


def test_acquire_empty_pool_no_longer_triggers_supplement(pool, mock_provider):
    """空池 acquire 不再同步触发补充（修复：避免阻塞事件循环）。"""
    rec = pool.acquire()
    mock_provider.fetch.assert_not_called()
    assert rec is None  # 池空直接返回 None


def test_warmup_triggers_supplement(pool, mock_provider):
    """warmup 冷启动同步预填充。"""
    count = pool.warmup()
    mock_provider.fetch.assert_called_once()
    assert count == 3  # 池空，需补 3 个（fetch_num=3），mock 返回 3 个
    rec = pool.acquire()
    assert rec is not None
    assert rec.ip == "1.1.1.1"


def test_warmup_skips_when_pool_sufficient(pool, storage, mock_provider):
    """池中已有足够 IP 时 warmup 跳过。"""
    # fetch_num 默认 3，插入 3 个使其达到阈值
    for i in range(3):
        _insert_ip(storage, f"10.0.0.{i}")
    count = pool.warmup()
    mock_provider.fetch.assert_not_called()
    assert count == 0


def test_warmup_disabled_returns_zero(storage, cfg):
    """proxy_enabled=false 时 warmup 返回 0。"""
    cfg.set("proxy_enabled", "false")
    p = ProxyPool(storage, cfg, None)
    assert p.warmup() == 0


def test_acquire_marks_in_use(pool, storage):
    """acquire 后 status 变为 in_use。"""
    pid = _insert_ip(storage, "10.0.0.1")
    # 让 _available_count 不触发补充
    with patch.object(pool, "_supplement", return_value=0):
        rec = pool.acquire()
    assert rec is not None
    assert rec.ip == "10.0.0.1"
    assert _get_pool_field(storage, pid, "status") == STATUS_IN_USE


def test_acquire_skips_expired(storage, cfg):
    """过期的 idle IP 不被 acquire。"""
    expired = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    _insert_ip(storage, "10.0.0.1", expire_at=expired)
    p = ProxyPool(storage, cfg, MagicMock(fetch=lambda **k: []))
    rec = p.acquire()
    assert rec is None  # 过期不被取


def test_acquire_skips_max_use_reached(storage, cfg):
    """use_count >= max_use 的 IP 不被 acquire。"""
    _insert_ip(storage, "10.0.0.1", use_count=3, max_use=3)
    p = ProxyPool(storage, cfg, MagicMock(fetch=lambda **k: []))
    rec = p.acquire()
    assert rec is None


# ---------------- release_success ----------------


def test_release_success_increments_use_count(pool, storage):
    pid = _insert_ip(storage, "10.0.0.1", use_count=0, max_use=3)
    with patch.object(pool, "_supplement", return_value=0):
        rec = pool.acquire()
    pool.release_success(rec)
    assert _get_pool_field(storage, pid, "use_count") == 1
    assert _get_pool_field(storage, pid, "status") == STATUS_IDLE


def test_release_success_reaches_max_use_marks_dead(pool, storage):
    pid = _insert_ip(storage, "10.0.0.1", use_count=2, max_use=3)
    with patch.object(pool, "_supplement", return_value=0):
        rec = pool.acquire()
    pool.release_success(rec)
    assert _get_pool_field(storage, pid, "use_count") == 3
    assert _get_pool_field(storage, pid, "status") == STATUS_DEAD


def test_release_success_rejects_non_in_use(pool, storage):
    """非 in_use 状态 release_success 应被拒绝。"""
    pid = _insert_ip(storage, "10.0.0.1", status=STATUS_IDLE, use_count=0)
    rec = ProxyRecord(id=pid, ip="10.0.0.1", port=8080, use_count=0, max_use=3)
    pool.release_success(rec)
    # use_count 不变
    assert _get_pool_field(storage, pid, "use_count") == 0


# ---------------- release_fail ----------------


def test_release_fail_first_marks_cooldown(pool, storage, cfg):
    pid = _insert_ip(storage, "10.0.0.1", use_count=0, max_use=3, fail_count=0)
    with patch.object(pool, "_supplement", return_value=0):
        rec = pool.acquire()
    pool.release_fail(rec)
    assert _get_pool_field(storage, pid, "fail_count") == 1
    assert _get_pool_field(storage, pid, "status") == STATUS_COOLDOWN
    assert _get_pool_field(storage, pid, "cooldown_until") is not None


def test_release_fail_third_marks_dead(pool, storage):
    pid = _insert_ip(storage, "10.0.0.1", use_count=0, max_use=3, fail_count=2)
    with patch.object(pool, "_supplement", return_value=0):
        rec = pool.acquire()
    pool.release_fail(rec)
    assert _get_pool_field(storage, pid, "fail_count") == 3
    assert _get_pool_field(storage, pid, "status") == STATUS_DEAD


def test_release_fail_no_cooldown_marks_dead_directly(pool, storage):
    """cooldown=False 直接 dead。"""
    pid = _insert_ip(storage, "10.0.0.1", use_count=0, max_use=3, fail_count=0)
    with patch.object(pool, "_supplement", return_value=0):
        rec = pool.acquire()
    pool.release_fail(rec, cooldown=False)
    assert _get_pool_field(storage, pid, "status") == STATUS_DEAD


# ---------------- 健康检查 ----------------


def test_health_check_expires_old_ips(pool, storage):
    expired = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    pid = _insert_ip(storage, "10.0.0.1", status=STATUS_IDLE, expire_at=expired)
    result = pool.health_check()
    assert result["expired"] >= 1
    assert _get_pool_field(storage, pid, "status") == STATUS_DEAD


def test_health_check_recovers_cooldown(pool, storage):
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    pid = _insert_ip(
        storage, "10.0.0.1", status=STATUS_COOLDOWN, fail_count=2,
        cooldown_until=past,
    )
    result = pool.health_check()
    assert result["cooldown_recovered"] == 1
    assert _get_pool_field(storage, pid, "status") == STATUS_IDLE
    assert _get_pool_field(storage, pid, "fail_count") == 0


def test_health_check_purges_dead_high_fail(pool, storage):
    _insert_ip(storage, "10.0.0.1", status=STATUS_DEAD, fail_count=5)
    _insert_ip(storage, "10.0.0.2", status=STATUS_DEAD, fail_count=2)
    result = pool.health_check()
    assert result["dead_purged"] == 1  # 只有 fail_count>=5 被删
    # fail_count=2 的 dead 保留
    row = storage.execute(
        "SELECT COUNT(*) FROM proxy_pool WHERE ip = '10.0.0.2'", fetch="one"
    )
    assert row[0] == 1


def test_health_check_disabled_returns_zero(storage, cfg):
    cfg.set("proxy_enabled", "false")
    p = ProxyPool(storage, cfg, None)
    result = p.health_check()
    assert result == {"expired": 0, "cooldown_recovered": 0, "dead_purged": 0}


# ---------------- 补充 ----------------


def test_supplement_no_provider_skips(storage, cfg):
    """无 provider 时 _supplement 返回 0。"""
    p = ProxyPool(storage, cfg, None)
    assert p._supplement() == 0


def test_supplement_provider_error_returns_zero(storage, cfg):
    """provider 抛异常时 _supplement 返回 0。"""
    bad = MagicMock()
    bad.fetch.side_effect = RuntimeError("api down")
    p = ProxyPool(storage, cfg, bad)
    assert p._supplement() == 0


def test_supplement_inserts_records(storage, cfg):
    provider = MagicMock()
    provider.fetch.return_value = [
        ProxyRecord(ip="1.1.1.1", port=8080),
        ProxyRecord(ip="2.2.2.2", port=8080),
    ]
    p = ProxyPool(storage, cfg, provider)
    count = p._supplement()
    assert count == 2
    rows = storage.execute("SELECT ip FROM proxy_pool", fetch="all")
    assert len(rows) == 2


def test_supplement_dedupes_by_ip_port(storage, cfg):
    """INSERT OR IGNORE 对同 ip:port 去重。"""
    _insert_ip(storage, "1.1.1.1", port=8080)
    provider = MagicMock()
    provider.fetch.return_value = [
        ProxyRecord(ip="1.1.1.1", port=8080),  # 重复
        ProxyRecord(ip="2.2.2.2", port=8080),
    ]
    p = ProxyPool(storage, cfg, provider)
    p._supplement()
    rows = storage.execute("SELECT ip FROM proxy_pool", fetch="all")
    assert len(rows) == 2


# ---------------- stats ----------------


def test_supplement_loop_fills_pool_when_low(storage, cfg):
    """后台补充线程在低水位时自动拉取 IP。"""
    cfg.set("proxy_supplement_interval", "1")  # 加速，避免 CI 不稳定
    provider = MagicMock()
    provider.fetch.return_value = [ProxyRecord(ip="1.1.1.1", port=8080)]
    p = ProxyPool(storage, cfg, provider)
    p._last_acquire_time = time.monotonic()  # 模拟有人在用
    p.start_supplement_loop()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if p._available_count() > 0:
                break
            time.sleep(0.1)
        assert p._available_count() > 0
        assert provider.fetch.called
    finally:
        p.stop_supplement_loop()


def test_supplement_loop_skips_when_idle(storage, cfg):
    """无人使用 IP 时补充线程不拉取（避免闲置白花钱）。"""
    cfg.set("proxy_supplement_interval", "1")
    provider = MagicMock()
    provider.fetch.return_value = [ProxyRecord(ip="1.1.1.1", port=8080)]
    p = ProxyPool(storage, cfg, provider)
    p.start_supplement_loop()
    try:
        time.sleep(1.5)  # 至少一轮
        provider.fetch.assert_not_called()
    finally:
        p.stop_supplement_loop()


def test_supplement_loop_skips_when_disabled(storage, cfg):
    """proxy_enabled=false 时补充线程不拉取。"""
    cfg.set("proxy_enabled", "false")
    cfg.set("proxy_supplement_interval", "1")  # 加速
    provider = MagicMock()
    p = ProxyPool(storage, cfg, provider)
    p.start_supplement_loop()
    try:
        time.sleep(1.5)  # > interval，线程必须已执行一轮
        provider.fetch.assert_not_called()
    finally:
        p.stop_supplement_loop()


def test_supplement_concurrent_lock(storage, cfg):
    """_supplement_lock 防止并发补充。"""
    import threading as _th
    provider = MagicMock()
    # 模拟慢速 fetch，持锁期间第二次调用应跳过
    fetch_event = _th.Event()
    def slow_fetch(**kw):
        fetch_event.set()
        time.sleep(0.5)
        return [ProxyRecord(ip="1.1.1.1", port=8080)]
    provider.fetch.side_effect = slow_fetch
    p = ProxyPool(storage, cfg, provider)
    results = []
    def call_supplement():
        results.append(p._supplement())
    t1 = _th.Thread(target=call_supplement)
    t2 = _th.Thread(target=call_supplement)
    t1.start()
    time.sleep(0.1)  # 确保 t1 先拿锁
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    # 一个返回 1（成功补充），一个返回 0（跳过）
    assert sorted(results) == [0, 1]


# ---------------- stats ----------------


def test_stats_returns_counts(pool, storage):
    _insert_ip(storage, "1.1.1.1", status=STATUS_IDLE)
    _insert_ip(storage, "2.2.2.2", status=STATUS_IN_USE)
    _insert_ip(storage, "3.3.3.3", status=STATUS_COOLDOWN)
    _insert_ip(storage, "4.4.4.4", status=STATUS_DEAD)
    stats = pool.stats()
    assert stats["idle"] == 1
    assert stats["in_use"] == 1
    assert stats["cooldown"] == 1
    assert stats["dead"] == 1
    assert stats["total"] == 4


# ---------------- Provider 解析 ----------------

# -- 巨量 text 解析 --

def test_juliang_parse_text_basic():
    """ip:port 两段（无账密）。"""
    text = "1.1.1.1:8080\n2.2.2.2:3128\n\nbadline"
    recs = JuliangProvider._parse_text(text)
    assert len(recs) == 2
    assert recs[0].ip == "1.1.1.1"
    assert recs[0].port == 8080
    assert recs[0].username is None


def test_juliang_parse_text_with_auth():
    """ip:port:username:password 四段。"""
    text = "117.69.63.102:43787:user123:pass456"
    recs = JuliangProvider._parse_text(text)
    assert len(recs) == 1
    assert recs[0].ip == "117.69.63.102"
    assert recs[0].port == 43787
    assert recs[0].username == "user123"
    assert recs[0].password == "pass456"


# -- 巨量 JSON 解析 --

def test_juliang_parse_json():
    """真实巨量 JSON 响应格式: data.proxy_list 数组。"""
    data = {
        "code": 200,
        "data": {
            "count": 2,
            "proxy_list": [
                ["117.69.63.102", 43787, "user1", "pass1"],
                ["117.69.63.103", 43788, "user2", "pass2"],
            ],
        },
    }
    recs = JuliangProvider._parse_json(data)
    assert len(recs) == 2
    assert recs[0].ip == "117.69.63.102"
    assert recs[0].port == 43787
    assert recs[0].username == "user1"
    assert recs[0].password == "pass1"
    assert recs[1].ip == "117.69.63.103"
    assert recs[1].port == 43788


def test_juliang_parse_json_no_auth():
    """数组只有两元素（无账密）。"""
    data = {
        "code": 200,
        "data": {"proxy_list": [["1.1.1.1", "8080"]]},
    }
    recs = JuliangProvider._parse_json(data)
    assert len(recs) == 1
    assert recs[0].ip == "1.1.1.1"
    assert recs[0].port == 8080
    assert recs[0].username is None
    assert recs[0].password is None


def test_juliang_parse_json_bad_code():
    """非 200 code 返回空。"""
    data = {"code": 500, "msg": "error"}
    recs = JuliangProvider._parse_json(data)
    assert recs == []


def test_juliang_parse_json_invalid_items():
    """跳过无效数组元素。"""
    data = {
        "code": 200,
        "data": {"proxy_list": [["bad", "notint"], [], ["1.1.1.1", 8080]]},
    }
    recs = JuliangProvider._parse_json(data)
    assert len(recs) == 1
    assert recs[0].ip == "1.1.1.1"


# -- 快代理 JSON 解析 --

def test_kuaidaili_parse(monkeypatch):
    """快代理 JSON 结构解析。"""
    p = KuaidailiProvider("http://example.com")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "code": 0,
        "data": {"proxy_list": [{"ip": "1.1.1.1", "port": 8080}]},
    }
    mock_resp.raise_for_status = lambda: None
    mock_client = MagicMock()
    mock_client.__enter__ = lambda self: mock_client
    mock_client.__exit__ = lambda *a: None
    mock_client.get.return_value = mock_resp
    monkeypatch.setattr("proxy.provider.httpx.Client", lambda **kw: mock_client)
    recs = p.fetch(num=1, ttl=60)
    assert len(recs) == 1
    assert recs[0].ip == "1.1.1.1"


def test_make_provider_returns_none_for_empty_url():
    assert make_provider("", "juliang") is None


def test_make_provider_juliang():
    p = make_provider("http://x", "juliang")
    assert isinstance(p, JuliangProvider)


def test_make_provider_kuaidaili():
    p = make_provider("http://x", "kuaidaili")
    assert isinstance(p, KuaidailiProvider)


def test_provider_fetch_empty_url_returns_empty():
    p = JuliangProvider("")
    assert p.fetch() == []


# ---------------- HealthChecker ----------------


def test_health_checker_check_one_ok(monkeypatch):
    """check_one 成功返回 (True, latency)。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = MagicMock()
    mock_client.__enter__ = lambda self: mock_client
    mock_client.__exit__ = lambda *a: None
    mock_client.get.return_value = mock_resp
    monkeypatch.setattr("proxy.health_check.httpx.Client", lambda **kw: mock_client)
    from core.storage import Storage
    from core.config_manager import ConfigManager
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        s = Storage(os.path.join(d, "t.db"))
        c = ConfigManager(s)
        c.init_defaults()
        checker = HealthChecker(s, c)
        ok, latency = checker.check_one("1.1.1.1", 8080)
        assert ok is True
        assert latency >= 0
        s.close()


def test_health_checker_check_one_fail(monkeypatch):
    """check_one 失败返回 (False, 0)。"""
    mock_client = MagicMock()
    mock_client.__enter__ = lambda self: mock_client
    mock_client.__exit__ = lambda *a: None
    mock_client.get.side_effect = Exception("timeout")
    monkeypatch.setattr("proxy.health_check.httpx.Client", lambda **kw: mock_client)
    import tempfile, os
    from core.storage import Storage
    from core.config_manager import ConfigManager
    with tempfile.TemporaryDirectory() as d:
        s = Storage(os.path.join(d, "t.db"))
        c = ConfigManager(s)
        c.init_defaults()
        checker = HealthChecker(s, c)
        ok, latency = checker.check_one("1.1.1.1", 8080)
        assert ok is False
        assert latency == 0
        s.close()


def test_health_checker_mark_fail_increments(storage, cfg):
    """_mark_fail fail_count+1，≥3 则 dead。"""
    pid = _insert_ip(storage, "1.1.1.1", fail_count=0)
    checker = HealthChecker(storage, cfg)
    checker._mark_fail(pid)
    assert _get_pool_field(storage, pid, "fail_count") == 1
    assert _get_pool_field(storage, pid, "status") == STATUS_IDLE
    # 再失败 2 次
    checker._mark_fail(pid)
    checker._mark_fail(pid)
    assert _get_pool_field(storage, pid, "fail_count") == 3
    assert _get_pool_field(storage, pid, "status") == STATUS_DEAD


# ---------------- 异步拉取 ----------------

@pytest.mark.asyncio
async def test_juliang_fetch_async_json():
    """异步拉取 JSON 格式，返回含账密的 IP。"""
    import json as _json
    mock_resp = MagicMock()
    mock_resp.text = _json.dumps({
        "code": 200,
        "data": {"proxy_list": [["1.1.1.1", 8080, "u", "p"]]},
    })
    mock_resp.raise_for_status = lambda: None
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    p = JuliangProvider("http://test")
    import httpx as _httpx
    with patch.object(_httpx, "AsyncClient", return_value=mock_client):
        recs = await p.fetch_async(num=1)
    assert len(recs) == 1
    assert recs[0].ip == "1.1.1.1"
    assert recs[0].port == 8080
    assert recs[0].username == "u"
    assert recs[0].password == "p"


@pytest.mark.asyncio
async def test_fetch_async_empty_url_returns_empty():
    """api_url 为空时返回空列表。"""
    p = JuliangProvider("")
    recs = await p.fetch_async(num=1)
    assert recs == []


@pytest.mark.asyncio
async def test_fetch_async_text_format():
    """异步拉取 text 格式返回 IP。"""
    mock_resp = MagicMock()
    mock_resp.text = "117.69.63.102:43787:user:pass\n118.69.63.103:43788"
    mock_resp.raise_for_status = lambda: None
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    p = JuliangProvider("http://test")
    import httpx as _httpx
    with patch.object(_httpx, "AsyncClient", return_value=mock_client):
        recs = await p.fetch_async(num=2)
    assert len(recs) == 2
