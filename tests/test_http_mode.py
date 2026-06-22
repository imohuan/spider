""":HTTP 模式测试 — 三层参数合并 + 文本验证码检测 + 双模式流程。

覆盖设计文档 docs/plans/2026-06-21-dual-mode-fetch-design.md 的关键逻辑。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config_manager import ConfigManager
from core.request_pool import RequestPool
from core.state_machine import ERROR_403, ERROR_5XX, ERROR_NETWORK, StateMachine
from core.storage import Storage
from parser.base import BaseParser, ParserTools


class MockParser(BaseParser):
    url_pattern = r"mock"
    table_name = "mock_data"
    table_schema = "CREATE TABLE mock_data (id INTEGER PRIMARY KEY)"
    http_method = "GET"
    http_headers = {"Referer": "https://mock.58.com/"}
    http_default_params = {"city": "cd"}


class BrowserOnlyParser(BaseParser):
    url_pattern = r"mock_browser"
    table_name = "mock_browser"
    table_schema = "CREATE TABLE mock_browser (id INTEGER PRIMARY KEY)"
    requires_browser = True


# ---------------- 三层参数合并 ----------------

def test_fetch_http_three_layer_merge():
    """三层合并：config < Parser < task.request_config。"""
    storage = Storage(":memory:")
    config = ConfigManager(storage)
    config.init_defaults()
    config.set("http_user_agent", "ConfigUA/1.0")
    config.set("http_default_headers", '{"X-Default": "from-config"}')
    config.set("anti_bot_random_ua", "false")

    state_machine = StateMachine(storage, config)
    rp = RequestPool(storage, config, state_machine)

    parser = MockParser(ParserTools())
    task = {
        "id": 1,
        "url": "https://mock.58.com/list",
        "fetch_mode": "http",
        "request_config": '{"method":"POST","headers":{"X-Task":"from-task"},"params":{"page":"1"},"json_body":{"key":"val"}}',
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.text = "<html>ok</html>"
        mock_resp.content = b"<html>ok</html>"
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_req = MagicMock()
        mock_req.headers = {"user-agent": "ConfigUA/1.0"}
        mock_resp.request = mock_req
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)

        import asyncio
        asyncio.run(rp._fetch_http(task, parser, None))

        call_kwargs = mock_client.return_value.__aenter__.return_value.request.call_args
        assert call_kwargs is not None
        args, kwargs = call_kwargs

        # method 来自 task
        assert args[0] == "POST"

        # headers 三层合并
        headers = kwargs["headers"]
        assert headers["User-Agent"] == "ConfigUA/1.0"
        assert headers["X-Default"] == "from-config"
        assert headers["Referer"] == "https://mock.58.com/"
        assert headers["X-Task"] == "from-task"

        # params 合并
        assert kwargs["params"] == {"city": "cd", "page": "1"}

        # json body
        assert kwargs["json"] == {"key": "val"}


def test_fetch_http_defaults():
    """未配置时使用默认值。"""
    storage = Storage(":memory:")
    config = ConfigManager(storage)
    config.init_defaults()
    rp = RequestPool(storage, config, StateMachine(storage, config))

    parser = MockParser(ParserTools())
    task = {
        "id": 1,
        "url": "https://mock.58.com/list",
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.text = "<html>ok</html>"
        mock_resp.content = b"<html>ok</html>"
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_req = MagicMock()
        mock_req.headers = {"user-agent": "ConfigUA/1.0"}
        mock_resp.request = mock_req
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)

        import asyncio
        asyncio.run(rp._fetch_http(task, parser, None))

        call_kwargs = mock_client.return_value.__aenter__.return_value.request.call_args
        args, kwargs = call_kwargs

        # 默认 GET
        assert args[0] == "GET"
        # 默认 UA（config 中的 http_user_agent）
        assert "User-Agent" in kwargs["headers"]


def test_fetch_http_form_data_body():
    """form_data / body / json_body 三选一。"""
    storage = Storage(":memory:")
    config = ConfigManager(storage)
    config.init_defaults()
    rp = RequestPool(storage, config, StateMachine(storage, config))

    parser = MockParser(ParserTools())

    # form_data
    task = {
        "id": 1, "url": "https://mock.58.com/list",
        "request_config": '{"method":"POST","form_data":{"a":"b"}}',
    }
    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.text = "<html>ok</html>"
        mock_resp.content = b"<html>ok</html>"
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_req = MagicMock()
        mock_req.headers = {}
        mock_resp.request = mock_req
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)
        import asyncio
        asyncio.run(rp._fetch_http(task, parser, None))
        kwargs = mock_client.return_value.__aenter__.return_value.request.call_args[1]
        assert kwargs["data"] == {"a": "b"}
        assert "json" not in kwargs

    # json_body 优先于 form_data
    task2 = {
        "id": 1, "url": "https://mock.58.com/list",
        "request_config": '{"method":"POST","form_data":{"a":"b"},"json_body":{"c":"d"}}',
    }
    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.text = "<html>ok</html>"
        mock_resp.content = b"<html>ok</html>"
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_req = MagicMock()
        mock_req.headers = {}
        mock_resp.request = mock_req
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(return_value=mock_resp)
        import asyncio
        asyncio.run(rp._fetch_http(task2, parser, None))
        kwargs = mock_client.return_value.__aenter__.return_value.request.call_args[1]
        assert kwargs["json"] == {"c": "d"}
        assert "data" not in kwargs


# ---------------- 验证码检测 ----------------

def test_detect_captcha_in_text_positive():
    """文本验证码特征检测 - 正例。"""
    html = '<html><body>callback.58.com/antibot 安全验证</body></html>'
    assert RequestPool._detect_captcha_in_text(html, "https://cd.58.com/ershouche/") is True


def test_detect_captcha_in_text_negative():
    """文本验证码特征检测 - 负例（正常页面）。"""
    html = '<html><body>58同城二手车</body></html>'
    assert RequestPool._detect_captcha_in_text(html, "https://cd.58.com/ershouche/") is False


def test_detect_captcha_sec_58_dot_com():
    """sec.58.com 应被检测为验证码。"""
    html = '<html><body>Please visit sec.58.com to verify</body></html>'
    assert RequestPool._detect_captcha_in_text(html, "https://cd.58.com/") is True


# ---------------- enqueue / acquire 新字段 ----------------

def test_enqueue_with_fetch_mode():
    """enqueue 应存储 fetch_mode 和 request_config。"""
    storage = Storage(":memory:")
    qid = storage.enqueue(
        "https://mock.58.com/list",
        fetch_mode="http",
        request_config={"method": "POST", "headers": {"X-A": "b"}},
    )
    assert isinstance(qid, int)
    # 验证写入
    row = storage.execute(
        "SELECT fetch_mode, request_config FROM queue WHERE id = ?",
        (qid,), fetch="one",
    )
    assert row is not None
    assert row["fetch_mode"] == "http"
    assert "POST" in row["request_config"]


def test_acquire_returns_fetch_mode():
    """acquire 应返回 fetch_mode 和 request_config。"""
    storage = Storage(":memory:")
    config = ConfigManager(storage)
    config.init_defaults()
    sm = StateMachine(storage, config)

    storage.enqueue("https://mock.58.com/list", fetch_mode="http",
                    request_config={"method": "GET"})
    task = sm.acquire()
    assert task is not None
    assert task["fetch_mode"] == "http"
    assert task["request_config"] == '{"method": "GET"}'


def test_enqueue_default_fetch_mode():
    """不传 fetch_mode 时默认值生效。"""
    storage = Storage(":memory:")
    qid = storage.enqueue("https://mock.58.com/list")
    row = storage.execute(
        "SELECT fetch_mode FROM queue WHERE id = ?", (qid,), fetch="one",
    )
    assert row is not None
    assert row["fetch_mode"] == "browser"  # 列默认值


# ---------------- requires_browser ----------------

def test_requires_browser_parsed_as_browser():
    """requires_browser=True 的 Parser 应强制走浏览器模式。"""
    parser = BrowserOnlyParser()
    assert parser.requires_browser is True
    assert getattr(parser, "requires_browser", False) is True


def test_normal_parser_does_not_require_browser():
    """普通 Parser 不应标记 requires_browser。"""
    parser = MockParser(ParserTools())
    assert parser.requires_browser is False


# ---------------- HTTP 异常映射 ----------------

def test_http_status_error_403():
    """HTTP 403 → blocked。"""
    storage = Storage(":memory:")
    config = ConfigManager(storage)
    config.init_defaults()
    sm = StateMachine(storage, config)
    rp = RequestPool(storage, config, sm)

    qid = storage.enqueue("https://mock.58.com/403", fetch_mode="http")
    task = sm.acquire()

    with patch("httpx.AsyncClient") as mock_client:
        from httpx import HTTPStatusError, Request, Response
        mock_resp = Response(403, request=Request("GET", "https://mock.58.com/403"))
        err = HTTPStatusError("Forbidden", request=Request("GET", "https://mock.58.com/403"), response=mock_resp)
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(side_effect=err)

        import asyncio
        result = asyncio.run(rp._process_url_async(task, MockParser(ParserTools())))

    assert result == "blocked"
    row = storage.execute("SELECT status, error_type FROM queue WHERE id = ?", (qid,), fetch="one")
    assert row["status"] == "blocked"
    assert row["error_type"] == ERROR_403


def test_http_network_error():
    """HTTP 网络错误 → failed（可重试）。"""
    storage = Storage(":memory:")
    config = ConfigManager(storage)
    config.init_defaults()
    sm = StateMachine(storage, config)
    rp = RequestPool(storage, config, sm)

    qid = storage.enqueue("https://mock.58.com/timeout", fetch_mode="http")
    task = sm.acquire()

    with patch("httpx.AsyncClient") as mock_client:
        import httpx
        mock_client.return_value.__aenter__.return_value.request = AsyncMock(
            side_effect=httpx.ConnectError("timeout")
        )

        import asyncio
        result = asyncio.run(rp._process_url_async(task, MockParser(ParserTools())))

    assert result == "failed"
    row = storage.execute("SELECT status, error_type FROM queue WHERE id = ?", (qid,), fetch="one")
    assert row["status"] == "failed"
    assert row["error_type"] == ERROR_NETWORK
