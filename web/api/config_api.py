from __future__ import annotations
import json
import time
import traceback

from flask import Blueprint, jsonify, request

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.storage import Storage

logger = get_logger("web.api.config")
bp = Blueprint("config", __name__)


@bp.route("")
def get_all():
    s = Storage()
    rows = s.execute(
        "SELECT key,value,description,updated_at FROM config ORDER BY key",
        fetch="all",
    )
    return jsonify(
        [{"key": r[0], "value": r[1], "desc": r[2], "updated": r[3]} for r in rows]
    )


@bp.route("", methods=["PUT"])
def update_batch():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Empty body"}), 400
    ConfigManager(Storage()).set_many(data)
    return jsonify({"ok": True, "updated": len(data)})


@bp.route("/reset", methods=["POST"])
def reset_defaults():
    ConfigManager(Storage()).reset_all()
    return jsonify({"ok": True})


@bp.route("/test-url", methods=["POST"])
def test_url():
    """测试 URL — 支持 browser 模式和 http 模式。

    Request body::

        {
            "url": "https://cd.58.com/ershouche/",
            "mode": "http",             // "browser" | "http"
            "method": "GET",            // HTTP 模式生效
            "headers": {},               // 可选, dict
            "cookies": "k1=v1; k2=v2",  // 可选, 字符串
            "body_type": "json",         // "none"|"raw"|"form-data"|"json"
            "body_content": "{}"         // 可选
        }

    Response::

        {
            "ok": true,
            "status_code": 200,
            "duration_ms": 1234,
            "content_type": "text/html",
            "content_length": 56789,
            "body_preview": "<html>...",    // 前 50000 字符
            "headers": {"Server": "..."}
        }
    """
    from flask import current_app

    data = request.get_json()
    if not data or not data.get("url"):
        return jsonify({"error": "url is required"}), 400

    url = data["url"]
    mode = data.get("mode", "http")
    method = (data.get("method") or "GET").upper()
    headers = data.get("headers") or {}
    cookies = data.get("cookies") or ""
    body_type = data.get("body_type", "none")
    body_content = data.get("body_content") or ""

    logger.info(
        f"POST /api/config/test-url mode={mode} method={method} url={url[:80]}"
    )

    if mode == "browser":
        return _test_browser(url, current_app)
    else:
        return _test_http(url, method, headers, cookies, body_type, body_content)


def _test_browser(url: str, app) -> tuple:
    """用 Playwright browser 抓取 URL。"""
    components = app.config.get("CRAWLER_COMPONENTS", {})
    browser = components.get("browser")

    if not browser:
        return jsonify({"error": "Browser component not initialized"}), 503
    if not browser._browser:
        return jsonify({"error": "Browser not started yet"}), 503

    try:
        import asyncio

        async def _do():
            page = await browser._browser.new_page()
            try:
                t0 = time.perf_counter()
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                duration_ms = int((time.perf_counter() - t0) * 1000)
                status = resp.status if resp else 0
                content_type = resp.headers.get("content-type", "") if resp else ""
                body = await page.content()
                resp_headers = dict(resp.headers) if resp else {}
            finally:
                await page.close()

            return {
                "ok": True,
                "status_code": status,
                "duration_ms": duration_ms,
                "content_type": content_type,
                "content_length": len(body),
                "body_preview": body[:50000],
                "headers": {k: v for k, v in list(resp_headers.items())[:20]},
            }

        result = asyncio.run(_do())
        return jsonify(result)

    except Exception as e:
        logger.error(f"Browser test failed: {e}\n{traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e), "error_type": type(e).__name__}), 500


def _test_http(
    url: str,
    method: str,
    headers: dict,
    cookies: str,
    body_type: str,
    body_content: str,
) -> tuple:
    """用 httpx 异步客户端发出 HTTP 请求。"""
    import asyncio

    async def _do():
        import httpx

        # 构建请求配置
        req_kwargs: dict = {"headers": headers, "follow_redirects": True, "timeout": 30}

        # Cookies
        if cookies.strip():
            req_kwargs["cookies"] = _parse_cookies(cookies)

        # Body
        if body_type != "none" and method in ("POST", "PUT"):
            if body_type == "json":
                try:
                    req_kwargs["json"] = json.loads(body_content)
                except json.JSONDecodeError:
                    req_kwargs["content"] = body_content
            elif body_type == "form-data":
                parsed = {}
                for pair in body_content.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        parsed[k.strip()] = v.strip()
                req_kwargs["data"] = parsed
            else:
                req_kwargs["content"] = body_content

        async with httpx.AsyncClient() as client:
            t0 = time.perf_counter()
            resp = await client.request(method, url, **req_kwargs)
            duration_ms = int((time.perf_counter() - t0) * 1000)

        body = resp.text
        return {
            "ok": True,
            "status_code": resp.status_code,
            "duration_ms": duration_ms,
            "content_type": resp.headers.get("content-type", ""),
            "content_length": len(body),
            "body_preview": body[:50000],
            "headers": dict(resp.headers),
        }

    try:
        result = asyncio.run(_do())
        return jsonify(result)
    except Exception as e:
        logger.error(f"HTTP test failed: {e}\n{traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e), "error_type": type(e).__name__}), 500


def _parse_cookies(cookie_str: str) -> dict:
    """解析 cookie 字符串 ``k1=v1; k2=v2`` 为 dict。"""
    result = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v.strip()
    return result


@bp.route("/test-ai", methods=["POST"])
def test_ai():
    """测试 AI 服务连接 — 发送一个简单的 chat completion 请求。

    从 config 表读取 ai_base_url / ai_api_key / ai_model，发一条 "reply 'pong'"
    消息，验证配置是否正确。

    Response::

        {
            "ok": true,
            "model": "gpt-4o",
            "reply": "pong",
            "duration_ms": 1234,
            "tokens": {"prompt": 10, "completion": 2}
        }
    """
    import asyncio
    import httpx

    config_mgr = ConfigManager(Storage())
    base_url = (config_mgr.get("ai_base_url") or "").strip().rstrip("/")
    api_key = (config_mgr.get("ai_api_key") or "").strip()
    model = (config_mgr.get("ai_model") or "").strip()

    if not base_url:
        return jsonify({"ok": False, "error": "AI Base URL 未配置"}), 400
    if not api_key:
        return jsonify({"ok": False, "error": "AI API Key 未配置"}), 400
    if not model:
        return jsonify({"ok": False, "error": "AI 模型未配置"}), 400

    async def _do():
        async with httpx.AsyncClient(timeout=30) as client:
            t0 = time.perf_counter()
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": "reply only the word 'pong'"}
                    ],
                    "max_tokens": 5,
                },
            )
            duration_ms = int((time.perf_counter() - t0) * 1000)
            data = resp.json()

            if resp.status_code != 200:
                error_msg = data.get("error", {}).get("message", resp.text)
                return {"ok": False, "error": f"{resp.status_code}: {error_msg}", "duration_ms": duration_ms}

            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            usage = data.get("usage", {})
            return {
                "ok": True,
                "model": data.get("model", model),
                "reply": reply,
                "duration_ms": duration_ms,
                "tokens": {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                },
            }

    try:
        result = asyncio.run(_do())
        return jsonify(result)
    except httpx.ConnectError:
        return jsonify({"ok": False, "error": f"无法连接到 {base_url}"}), 502
    except httpx.TimeoutException:
        return jsonify({"ok": False, "error": "请求超时（30s）"}), 504
    except Exception as e:
        logger.error(f"AI test failed: {e}\n{traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e)}), 500
