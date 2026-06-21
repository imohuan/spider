"""interceptor 模块测试 - 资源拦截策略与缓存命中验证。

策略覆盖（设计文档 4.4）：
- data: URI（动态加密字体）→ 放行不缓存
- JS/CSS/font 外部 URL → 查缓存命中 fulfill，未命中 fetch+缓存
- image/xhr/fetch → 放行
- 缓存文件命名用 MD5(url)
- cache_enabled=false 时不挂载 route

测试方式：用 mock Route/Request 对象模拟 Playwright 调用，
不依赖真实浏览器二进制（CI 友好）。
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest

from config import CACHE_CSS_DIR, CACHE_FONT_DIR, CACHE_JS_DIR
from core.config_manager import ConfigManager
from core.interceptor import Interceptor
from core.storage import Storage


# ---------------- fixtures ----------------


@pytest.fixture
def storage(tmp_path):
    db_path = tmp_path / "test.db"
    s = Storage(str(db_path))
    yield s
    s.close()


@pytest.fixture
def cfg(storage, tmp_path, monkeypatch):
    """ConfigManager，缓存目录重定向到 tmp_path 隔离。"""
    c = ConfigManager(storage)
    c.init_defaults()
    # 重定向缓存目录
    js_dir = tmp_path / "cache" / "js"
    css_dir = tmp_path / "cache" / "css"
    font_dir = tmp_path / "cache" / "font"
    js_dir.mkdir(parents=True, exist_ok=True)
    css_dir.mkdir(parents=True, exist_ok=True)
    font_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("core.interceptor.CACHE_JS_DIR", str(js_dir))
    monkeypatch.setattr("core.interceptor.CACHE_CSS_DIR", str(css_dir))
    monkeypatch.setattr("core.interceptor.CACHE_FONT_DIR", str(font_dir))
    return c


@pytest.fixture
def interceptor(cfg):
    # 重新创建以使用 monkeypatch 后的目录
    return Interceptor(cfg)


# ---------------- 辅助：mock Route/Request ----------------


def make_route_request(url: str, resource_type: str):
    """构造 mock Route 和 Request 对象。"""
    request = MagicMock()
    request.url = url
    request.resource_type = resource_type
    route = MagicMock()
    route.continue_ = AsyncMock()
    route.fulfill = AsyncMock()
    route.fetch = AsyncMock()
    return route, request


def run_async(coro):
    """同步运行异步协程。"""
    return asyncio.run(coro)


# ---------------- data: URI 放行 ----------------


def test_data_uri_passthrough(interceptor):
    """data: URI（动态加密字体）应放行不缓存。"""
    route, request = make_route_request(
        "data:font/woff2;base64,d09GMgABAAAAAA...", "font"
    )
    run_async(interceptor._handle_route(route, request))
    route.continue_.assert_awaited_once()
    route.fulfill.assert_not_awaited()
    route.fetch.assert_not_awaited()


# ---------------- 静态资源缓存未命中 ----------------


def test_js_cache_miss_fetches_and_caches(interceptor, monkeypatch):
    """JS 资源未命中缓存：fetch + 写缓存 + fulfill。"""
    url = "https://example.com/static/app.js"
    route, request = make_route_request(url, "script")

    mock_response = MagicMock()
    mock_response.body = AsyncMock(return_value=b"console.log(1);")
    route.fetch.return_value = mock_response

    # 确保缓存目录为空（隔离）
    cache_path = interceptor._cache_path(url, "script")
    if cache_path.exists():
        cache_path.unlink()

    run_async(interceptor._handle_route(route, request))

    route.fetch.assert_awaited_once()
    route.fulfill.assert_awaited_once()
    assert cache_path.exists()
    assert cache_path.read_bytes() == b"console.log(1);"


def test_css_cache_miss_fetches_and_caches(interceptor):
    """CSS 资源未命中缓存：fetch + 写缓存。"""
    url = "https://example.com/style.css"
    route, request = make_route_request(url, "stylesheet")
    mock_response = MagicMock()
    mock_response.body = AsyncMock(return_value=b"body{color:red}")
    route.fetch.return_value = mock_response

    cache_path = interceptor._cache_path(url, "stylesheet")
    if cache_path.exists():
        cache_path.unlink()

    run_async(interceptor._handle_route(route, request))
    route.fetch.assert_awaited_once()
    assert cache_path.exists()


def test_font_cache_miss_fetches_and_caches(interceptor):
    """字体资源未命中缓存：fetch + 写缓存，扩展名按 URL 推断。"""
    url = "https://example.com/fonts/icon.woff2"
    route, request = make_route_request(url, "font")
    mock_response = MagicMock()
    mock_response.body = AsyncMock(return_value=b"\x00\x01fontdata")
    route.fetch.return_value = mock_response

    cache_path = interceptor._cache_path(url, "font")
    if cache_path.exists():
        cache_path.unlink()

    run_async(interceptor._handle_route(route, request))
    route.fetch.assert_awaited_once()
    assert cache_path.exists()
    # 扩展名应为 woff2（从 URL 推断）
    assert cache_path.suffix == ".woff2"


# ---------------- 缓存命中 ----------------


def test_js_cache_hit_fulfills_without_fetch(interceptor):
    """JS 资源命中缓存：fulfill 本地文件，不调用 fetch。"""
    url = "https://example.com/static/cached.js"
    cache_path = interceptor._cache_path(url, "script")
    cache_path.write_bytes(b"cached content")

    route, request = make_route_request(url, "script")
    run_async(interceptor._handle_route(route, request))

    route.fulfill.assert_awaited_once()
    route.fetch.assert_not_awaited()
    route.continue_.assert_not_awaited()
    # 检查 fulfill 的 body 参数
    _, kwargs = route.fulfill.call_args
    assert kwargs.get("body") == b"cached content"


# ---------------- 非缓存资源放行 ----------------


def test_image_passthrough(interceptor):
    """image 资源放行。"""
    route, request = make_route_request(
        "https://example.com/photo.jpg", "image"
    )
    run_async(interceptor._handle_route(route, request))
    route.continue_.assert_awaited_once()
    route.fulfill.assert_not_awaited()


def test_xhr_passthrough(interceptor):
    """XHR 资源放行（可能含数据）。"""
    route, request = make_route_request(
        "https://example.com/api/list", "xhr"
    )
    run_async(interceptor._handle_route(route, request))
    route.continue_.assert_awaited_once()


def test_fetch_passthrough(interceptor):
    """Fetch 资源放行。"""
    route, request = make_route_request(
        "https://example.com/api/data", "fetch"
    )
    run_async(interceptor._handle_route(route, request))
    route.continue_.assert_awaited_once()


# ---------------- fetch 失败回退 ----------------


def test_fetch_failure_falls_back_to_continue(interceptor):
    """fetch 抛异常时应回退到 continue_。"""
    url = "https://example.com/broken.js"
    route, request = make_route_request(url, "script")
    route.fetch.side_effect = RuntimeError("network error")

    cache_path = interceptor._cache_path(url, "script")
    if cache_path.exists():
        cache_path.unlink()

    run_async(interceptor._handle_route(route, request))
    route.fetch.assert_awaited_once()
    route.continue_.assert_awaited_once()


# ---------------- 缓存路径计算 ----------------


def test_cache_path_uses_md5_hash(interceptor):
    """缓存文件名用 URL 的 MD5 哈希。"""
    url = "https://example.com/static/app.js"
    path = interceptor._cache_path(url, "script")
    expected_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    assert path.name.startswith(expected_hash)


def test_cache_path_ext_from_url(interceptor):
    """扩展名优先从 URL 路径推断。"""
    path = interceptor._cache_path(
        "https://example.com/font.woff2", "font"
    )
    assert path.suffix == ".woff2"

    path = interceptor._cache_path(
        "https://example.com/font.ttf", "font"
    )
    assert path.suffix == ".ttf"


def test_cache_path_default_ext_when_no_url_ext(interceptor):
    """URL 无扩展名时用 resource_type 默认扩展名。"""
    path = interceptor._cache_path(
        "https://example.com/noext", "script"
    )
    assert path.suffix == ".js"

    path = interceptor._cache_path(
        "https://example.com/noext", "stylesheet"
    )
    assert path.suffix == ".css"


def test_cache_path_in_correct_dir(interceptor):
    """不同 resource_type 进不同目录。"""
    js_path = interceptor._cache_path("https://x.com/a.js", "script")
    css_path = interceptor._cache_path("https://x.com/a.css", "stylesheet")
    font_path = interceptor._cache_path("https://x.com/a.woff", "font")
    assert "js" in str(js_path).replace("\\", "/")
    assert "css" in str(css_path).replace("\\", "/")
    assert "font" in str(font_path).replace("\\", "/")


# ---------------- attach / detach ----------------


def test_attach_enabled_calls_route(interceptor):
    """cache_enabled=true 时 attach 调用 page.route。"""
    page = MagicMock()
    page.route = AsyncMock()
    run_async(interceptor.attach(page))
    page.route.assert_awaited_once_with("**/*", interceptor._handle_route)


def test_attach_disabled_skips_route(storage, tmp_path, monkeypatch):
    """cache_enabled=false 时不挂载 route。"""
    s = Storage(str(tmp_path / "t.db"))
    c = ConfigManager(s)
    c.init_defaults()
    c.set("cache_enabled", "false")
    js_dir = tmp_path / "cache" / "js"
    js_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("core.interceptor.CACHE_JS_DIR", str(js_dir))
    monkeypatch.setattr("core.interceptor.CACHE_CSS_DIR", str(tmp_path / "cache" / "css"))
    monkeypatch.setattr("core.interceptor.CACHE_FONT_DIR", str(tmp_path / "cache" / "font"))
    it = Interceptor(c)
    page = MagicMock()
    page.route = AsyncMock()
    run_async(it.attach(page))
    page.route.assert_not_awaited()
    s.close()


def test_detach_calls_unroute(interceptor):
    """detach 调用 page.unroute。"""
    page = MagicMock()
    page.unroute = AsyncMock()
    run_async(interceptor.detach(page))
    page.unroute.assert_awaited_once()


def test_detach_swallows_exception(interceptor):
    """detach 时 unroute 抛异常应被吞掉（幂等）。"""
    page = MagicMock()
    page.unroute = AsyncMock(side_effect=RuntimeError("already unrouted"))
    # 不应抛
    run_async(interceptor.detach(page))


# ---------------- cache_stats / clear_cache ----------------


def test_cache_stats_counts_files(interceptor):
    """cache_stats 返回各目录文件数。"""
    # 写几个文件到 js 目录
    js_path = interceptor._cache_path("https://x.com/1.js", "script")
    js_path.write_bytes(b"")
    js_path2 = interceptor._cache_path("https://x.com/2.js", "script")
    js_path2.write_bytes(b"")
    stats = interceptor.cache_stats()
    assert stats["script"] >= 2


def test_clear_cache_all(interceptor):
    """clear_cache(None) 清空所有目录。"""
    for url in ["https://x.com/a.js", "https://x.com/b.js"]:
        interceptor._cache_path(url, "script").write_bytes(b"")
    for url in ["https://x.com/a.css"]:
        interceptor._cache_path(url, "stylesheet").write_bytes(b"")
    count = interceptor.clear_cache()
    assert count >= 3
    stats = interceptor.cache_stats()
    assert stats["script"] == 0
    assert stats["stylesheet"] == 0


def test_clear_cache_by_type(interceptor):
    """clear_cache('script') 只清 JS。"""
    js_path = interceptor._cache_path("https://x.com/a.js", "script")
    js_path.write_bytes(b"")
    css_path = interceptor._cache_path("https://x.com/a.css", "stylesheet")
    css_path.write_bytes(b"")
    count = interceptor.clear_cache("script")
    assert count == 1
    assert not js_path.exists()
    assert css_path.exists()  # CSS 保留
