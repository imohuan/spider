"""cookie_presets API 集成测试。"""
import json
import pytest
from web.app import create_app
from core.storage import Storage


@pytest.fixture
def app():
    app = create_app('dev')
    app.testing = True
    with app.app_context():
        Storage()._init_schema()
    return app


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
