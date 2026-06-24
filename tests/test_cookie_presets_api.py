"""cookie_presets API 集成测试。

使用临时 SQLite 文件隔离测试数据，不会污染生产数据库。
清除夹具 scope=session 共享单个临时库，避免重复创建。
teardown 后临时文件由系统 temp 目录自动回收（Windows WAL 锁阻止同步删除）。
"""
import json
import os
import tempfile

import pytest
from web.app import create_app
from core.storage import Storage


@pytest.fixture(scope="session")
def app():
    """创建使用临时数据库的 Flask 测试 app（session 级共享）。

    monkey-patch core.storage.DB_PATH 指向临时文件，
    确保所有 Storage() 实例操作的是测试专用库。
    """
    import config
    import core.storage as st_mod

    # 保存原始路径
    orig_config = config.DB_PATH
    orig_storage = st_mod.DB_PATH

    # 创建临时数据库文件
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.db', prefix='pytest_cookie_')
    os.close(tmp_fd)

    # 改指向临时文件（config 和 core.storage 两处都要改，
    # 因为 core.storage 在模块顶层 import 了 config.DB_PATH）
    config.DB_PATH = tmp_path
    st_mod.DB_PATH = tmp_path

    # 注册退出时恢复（不尝试删除 — WAL 模式在 Windows 下锁文件，
    # 暂存到系统 temp 目录由 OS 自动回收）
    def restore():
        config.DB_PATH = orig_config
        st_mod.DB_PATH = orig_storage

    import atexit
    atexit.register(restore)

    app_obj = create_app('dev')
    app_obj.testing = True
    with app_obj.app_context():
        Storage()._init_schema()
    yield app_obj


@pytest.fixture
def client(app):
    return app.test_client()


def test_create_and_list(client):
    resp = client.post("/api/cookie-presets", json={
        "name": "Test", "domain": "example.com",
        "cookies_json": '[{"name":"t","value":"v"}]',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"]
    assert data["id"] >= 1

    resp = client.get("/api/cookie-presets")
    data = resp.get_json()
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert item["name"] == "Test"
    assert item["domain"] == "example.com"


def test_toggle_and_delete(client):
    resp = client.post("/api/cookie-presets", json={
        "name": "T", "domain": "x.com", "cookies_json": "[]",
    })
    pid = resp.get_json()["id"]

    # 关闭
    resp = client.post(f"/api/cookie-presets/{pid}/toggle")
    assert resp.get_json()["enabled"] is False

    # 开启
    resp = client.post(f"/api/cookie-presets/{pid}/toggle")
    assert resp.get_json()["enabled"] is True

    # 删除
    resp = client.delete(f"/api/cookie-presets/{pid}")
    assert resp.get_json()["ok"]


def test_enqueue_cookie_matching(client):
    """入队时自动匹配 cookie 预设。"""
    client.post("/api/cookie-presets", json={
        "name": "TestLogin", "domain": "test.example.com",
        "cookies_json": '[{"name":"session","value":"abc123"}]',
    })

    resp = client.post("/api/queue", json={
        "url": "https://test.example.com/page",
    })
    assert resp.status_code == 200

    s = Storage()
    row = s.execute(
        "SELECT request_config FROM queue WHERE url='https://test.example.com/page'",
        fetch="one",
    )
    assert row is not None
    rc = json.loads(row[0])
    assert "cookies" in rc
    assert rc["cookies"] == {"session": "abc123"}


def test_enqueue_preserves_existing_cookies(client):
    """入队时已传 cookies → 不覆盖。"""
    client.post("/api/cookie-presets", json={
        "name": "Login", "domain": "preserve.example.com",
        "cookies_json": '[{"name":"preset","value":"should-not-appear"}]',
    })
    resp = client.post("/api/queue", json={
        "url": "https://preserve.example.com/",
        "request_config": {"cookies": {"custom": "keep-me"}},
    })
    assert resp.status_code == 200
    s = Storage()
    row = s.execute(
        "SELECT request_config FROM queue WHERE url='https://preserve.example.com/'",
        fetch="one",
    )
    rc = json.loads(row[0])
    assert rc["cookies"] == {"custom": "keep-me"}


def test_create_task_raw_html(client):
    """raw 模式：传入 html 自动切换 fetch_mode='raw'，HTML 存文件，DB 只存路径。"""
    resp = client.post("/api/queue", json={
        "url": "https://58.com/ershouche/123",
        "html": "<html><body>58二手车页面</body></html>",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"]
    assert data["fetch_mode"] == "raw"

    s = Storage()
    row = s.execute(
        "SELECT fetch_mode, request_config FROM queue WHERE id = ?",
        (data["queue_id"],), fetch="one",
    )
    assert row is not None
    assert row[0] == "raw"
    rc = json.loads(row[1])
    # DB 只存路径，不存 HTML 原文
    assert "raw_html_path" in rc
    assert "html" not in rc
    # 路径指向实际文件
    path = rc["raw_html_path"].replace("\\", "/")
    assert path.startswith("data/raw_responses/raw_")
    assert path.endswith(".html")
    assert os.path.exists(os.path.join(os.path.dirname(__file__), "..", rc["raw_html_path"]))


def test_create_task_raw_html_with_parser_name(client):
    """raw 模式 + 显式 parser_name。"""
    resp = client.post("/api/queue", json={
        "url": "https://58.com/ershouche/456",
        "parser_name": "ErshoucheListParser",
        "html": "<html><body>列表页</body></html>",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"]
    assert data["fetch_mode"] == "raw"
    assert data["parser"] == "ErshoucheListParser"
