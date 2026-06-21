"""captcha_handler 模块测试。

测试策略：
- solve_callable 用 mock 注入，不依赖 ddddocr
- is_captcha_page 用 mock page 对象
- handle 主流程覆盖：solved / manual / switch_ip / 超限转人工
- captcha_log 表写入验证（外键约束：先入队 queue 记录）
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.config_manager import ConfigManager
from core.storage import Storage
from parser.tools.captcha_handler import CaptchaHandler


@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    yield s
    s.close()


@pytest.fixture
def cfg(storage):
    c = ConfigManager(storage)
    c.init_defaults()
    return c


@pytest.fixture
def handler(cfg, storage):
    return CaptchaHandler(cfg, storage)


def _enqueue(storage, url="https://58.com/x") -> int:
    """入队一条 queue 记录，返回真实 id（captcha_log 外键依赖）。"""
    return storage.enqueue(url)


def _create_request(storage, queue_id: int, url="https://58.com/x") -> int:
    """创建 requests 记录，返回真实 id。"""
    return storage.create_request(queue_id, url, proxy_ip=None)


def make_page(url="https://58.com/list", title="", content=""):
    """构造 mock page。"""
    page = MagicMock()
    page.url = url
    page.title.return_value = title
    page.content.return_value = content
    return page


# ---------------- 配置读取 ----------------


def test_config_defaults(handler):
    assert handler.enabled is True
    assert handler.auto_solve is True
    assert handler.max_retry == 3
    assert handler.fallback == "manual"
    assert handler.max_switch == 5


def test_config_disabled(cfg, storage):
    cfg.set("captcha_enabled", "false")
    h = CaptchaHandler(cfg, storage)
    assert h.enabled is False


# ---------------- is_captcha_page ----------------


def test_is_captcha_page_url_match(handler):
    page = make_page(url="https://sec.58.com/captcha?from=list")
    assert handler.is_captcha_page(page) is True


def test_is_captcha_page_url_verify(handler):
    page = make_page(url="https://58.com/verify")
    assert handler.is_captcha_page(page) is True


def test_is_captcha_page_title_match(handler):
    page = make_page(url="https://58.com/x", title="安全验证 - 58同城")
    assert handler.is_captcha_page(page) is True


def test_is_captcha_page_text_match(handler):
    page = make_page(
        url="https://58.com/x",
        title="",
        content="<html><body>请输入验证码</body></html>",
    )
    assert handler.is_captcha_page(page) is True


def test_is_captcha_page_no_match(handler):
    page = make_page(url="https://58.com/ershouche", title="二手车", content="cars")
    assert handler.is_captcha_page(page) is False


def test_is_captcha_page_disabled(cfg, storage):
    """captcha_enabled=false 时始终返回 False。"""
    cfg.set("captcha_enabled", "false")
    h = CaptchaHandler(cfg, storage)
    page = make_page(url="https://sec.58.com/captcha")
    assert h.is_captcha_page(page) is False


# ---------------- handle: 自动接码成功 ----------------


def test_handle_auto_solve_success(cfg, storage):
    """auto_solve=true，接码成功 → 返回 'solved'。"""
    qid = _enqueue(storage)
    h = CaptchaHandler(cfg, storage, solve_callable=lambda p: True)
    page = make_page(url="https://58.com/x")
    result = h.handle(page, queue_id=qid)
    assert result == "solved"
    row = storage.execute(
        "SELECT final_status FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row[0] == "success"


def test_handle_auto_solve_fails_then_manual(cfg, storage):
    """auto_solve=true 但接码失败，fallback=manual → 返回 'manual'。"""
    qid = _enqueue(storage)
    cfg.set("captcha_max_retry", "2")
    h = CaptchaHandler(cfg, storage, solve_callable=lambda p: False)
    page = make_page(url="https://58.com/x")
    result = h.handle(page, queue_id=qid)
    assert result == "manual"
    row = storage.execute(
        "SELECT attempt_count, final_status FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row[0] == 2
    assert row[1] == "manual"


def test_handle_solve_callable_exception_treated_as_failure(cfg, storage):
    """solve_callable 抛异常应被捕获，视为失败。"""
    qid = _enqueue(storage)
    cfg.set("captcha_max_retry", "1")
    cfg.set("captcha_fallback", "manual")

    def bad_solve(p):
        raise RuntimeError("boom")

    h = CaptchaHandler(cfg, storage, solve_callable=bad_solve)
    page = make_page(url="https://58.com/x")
    result = h.handle(page, queue_id=qid)
    assert result == "manual"


# ---------------- handle: switch_ip 降级 ----------------


def test_handle_switch_ip_not_exceeded(cfg, storage):
    """fallback=switch_ip，未超限 → 返回 'switch_ip'。"""
    qid = _enqueue(storage)
    cfg.set("captcha_fallback", "switch_ip")
    cfg.set("captcha_max_switch", "5")
    h = CaptchaHandler(cfg, storage, solve_callable=lambda p: False)
    page = make_page(url="https://58.com/x")
    inc = MagicMock(return_value=False)
    result = h.handle(page, queue_id=qid, increment_ip_switch=inc)
    assert result == "switch_ip"
    inc.assert_called_once_with(qid)
    row = storage.execute(
        "SELECT final_status FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row[0] == "switched_ip"


def test_handle_switch_ip_exceeded_forces_manual(cfg, storage):
    """fallback=switch_ip 但换IP超限 → 强制转 'manual'。"""
    qid = _enqueue(storage)
    cfg.set("captcha_fallback", "switch_ip")
    cfg.set("captcha_max_switch", "5")
    h = CaptchaHandler(cfg, storage, solve_callable=lambda p: False)
    page = make_page(url="https://58.com/x")
    inc = MagicMock(return_value=True)  # 超限
    result = h.handle(page, queue_id=qid, increment_ip_switch=inc)
    assert result == "manual"
    row = storage.execute(
        "SELECT final_status FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row[0] == "manual"


def test_handle_switch_ip_no_callback_falls_back_to_manual(cfg, storage):
    """switch_ip 降级但未提供回调 → 转 manual。"""
    qid = _enqueue(storage)
    cfg.set("captcha_fallback", "switch_ip")
    h = CaptchaHandler(cfg, storage, solve_callable=lambda p: False)
    page = make_page(url="https://58.com/x")
    result = h.handle(page, queue_id=qid, increment_ip_switch=None)
    assert result == "manual"


# ---------------- handle: auto_solve=false ----------------


def test_handle_auto_solve_disabled_skips_to_fallback(cfg, storage):
    """auto_solve=false 时直接走降级，不尝试接码。"""
    qid = _enqueue(storage)
    cfg.set("captcha_auto_solve", "false")
    cfg.set("captcha_fallback", "manual")
    solve_called = [0]

    def solve(p):
        solve_called[0] += 1
        return True

    h = CaptchaHandler(cfg, storage, solve_callable=solve)
    page = make_page(url="https://58.com/x")
    result = h.handle(page, queue_id=qid)
    assert result == "manual"
    assert solve_called[0] == 0  # 没调用接码
    row = storage.execute(
        "SELECT strategy FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row[0] == "manual"


# ---------------- captcha_log 持久化 ----------------


def test_captcha_log_written_with_request_id(cfg, storage):
    """captcha_log 记录 queue_id + request_id 关联。"""
    qid = _enqueue(storage)
    rid = _create_request(storage, qid)
    h = CaptchaHandler(cfg, storage, solve_callable=lambda p: True)
    page = make_page(url="https://58.com/x")
    h.handle(page, queue_id=qid, request_id=rid)

    row = storage.execute(
        "SELECT queue_id, request_id, url, strategy, final_status "
        "FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row is not None
    assert row[0] == qid
    assert row[1] == rid
    assert row[2] == "https://58.com/x"
    assert row[3] == "auto"
    assert row[4] == "success"


def test_captcha_log_attempt_count_updated(cfg, storage):
    """接码失败时 attempt_count 累加到 max_retry。"""
    qid = _enqueue(storage)
    cfg.set("captcha_max_retry", "3")
    h = CaptchaHandler(cfg, storage, solve_callable=lambda p: False)
    page = make_page(url="https://58.com/x")
    h.handle(page, queue_id=qid)
    row = storage.execute(
        "SELECT attempt_count FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row[0] == 3


# ---------------- manual_intervention ----------------


def test_manual_intervention_logs(cfg, storage):
    """manual_intervention 应写 captcha_log。"""
    qid = _enqueue(storage)
    h = CaptchaHandler(cfg, storage)
    page = make_page(url="https://58.com/captcha")
    h.manual_intervention(page, queue_id=qid)
    row = storage.execute(
        "SELECT strategy, final_status FROM captcha_log WHERE queue_id = ?",
        (qid,), fetch="one",
    )
    assert row[0] == "manual"
    assert row[1] == "manual"


# ---------------- ddddocr 缺失 ----------------


def test_solve_without_callable_or_ddddocr_falls_to_manual(cfg, storage, monkeypatch):
    """无 callable 且 ddddocr 未安装 → 接码失败 → 降级 manual。"""
    qid = _enqueue(storage)
    h = CaptchaHandler(cfg, storage)  # 无注入
    import sys
    monkeypatch.setitem(sys.modules, "ddddocr", None)
    page = make_page(url="https://58.com/x")
    cfg.set("captcha_max_retry", "1")
    result = h.handle(page, queue_id=qid)
    assert result == "manual"
