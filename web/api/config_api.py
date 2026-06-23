from __future__ import annotations
import json
import time
import traceback

from flask import Blueprint, jsonify, request

from core.config_manager import ConfigManager
from core.logger import get_logger
from core.storage import Storage, _validate_identifier

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
    """测试 URL — 委托 RequestPool.debug_parse() 走完整 Parser pipeline。

    Request body::

        {
            "url": "https://cd.58.com/shangpu/xxx.shtml",
            "parser": "ShengyiZRDetailParser",   // 可选, 不传则自动匹配
            "show_window": true                   // 可选, 显示浏览器窗口（调试用）
        }

    Response::

        {
            "ok": true,
            "parser": "ShengyiZRDetailParser",
            "fetch_mode": "browser",
            "duration_ms": 2345,
            "fetch_duration_ms": 2100,
            "parse_duration_ms": 45,
            "data": [{"title": "...", "price_num": "...", ...}],
            "data_count": 1,
            "raw_preview": "<html>...",
            "raw_path": "data/raw_responses/xxx.html"
        }
    """
    import asyncio
    from flask import current_app

    data = request.get_json()
    if not data or not data.get("url"):
        return jsonify({"ok": False, "error": "url is required"}), 400

    url = data["url"].strip()
    parser_name = (data.get("parser") or "").strip()
    show_window = bool(data.get("show_window", False))

    components = current_app.config.get("CRAWLER_COMPONENTS", {})
    request_pool = components.get("request_pool")
    registry = components.get("registry")

    if not request_pool:
        return jsonify({"ok": False, "error": "RequestPool 未初始化"}), 503
    if not registry:
        return jsonify({"ok": False, "error": "Registry 未初始化"}), 503

    async def _do() -> dict:
        return await request_pool.debug_parse(url, registry, parser_name, show_window)

    try:
        event_loop_obj = components.get("event_loop")
        if event_loop_obj and not event_loop_obj.is_closed():
            result = event_loop_obj.run_until_complete(_do())
        else:
            result = asyncio.run(_do())
        is_ok = result.get("ok", False)
        if is_ok:
            status = 200
        elif str(result.get("error", "")).startswith("Parse 失败"):
            status = 500
        else:
            status = 400
        return jsonify(result), status
    except Exception as e:
        logger.error(f"test-url 失败: {e}", exc_info=True)
        return jsonify({
            "ok": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }), 500


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


@bp.route("/ai-vision", methods=["POST"])
def ai_vision():
    """AI 视觉识别 — 提交 messages（多图片），强制 tool calling 输出结构化结果。

    ``messages`` 中的 ``image_id`` 项会自动转为 base64：

    - ``{"type": "image_id", "image_id": "abc123"}`` → 读取 ``data/images/abc123.jpg``

    请求示例::

        {
            "messages": [
                {"role": "system", "content": "你是商品分析助手"},
                {"role": "user", "content": [
                    {"type": "text", "text": "描述这张图"},
                    {"type": "image_id", "image_id": "abc123"},
                    {"type": "text", "text": "和这张"},
                    {"type": "image_id", "image_id": "def456"}
                ]}
            ],
            "output_mode": {
                "tool_name": "extract_product",
                "tool_description": "提取商品信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "商品标题"},
                        "price": {"type": "number", "description": "价格(元)"}
                    },
                    "required": ["title", "price"]
                }
            }
        }

    返回::

        {
            "ok": true,
            "result": {"title": "iPhone 15", "price": 6999},
            "attempts": 1,
            "duration_ms": 2345,
            "usage": {"prompt_tokens": 1200, "completion_tokens": 45}
        }
    """
    import asyncio
    import base64
    import httpx
    import os

    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "Empty body"}), 400

    raw_messages = data.get("messages")
    output_mode = data.get("output_mode")

    if not raw_messages or not isinstance(raw_messages, list) or len(raw_messages) == 0:
        return jsonify({"ok": False, "error": "messages (非空数组) is required"}), 400
    if not output_mode or not isinstance(output_mode, dict):
        return jsonify({"ok": False, "error": "output_mode (dict) is required"}), 400

    tool_name = (output_mode.get("tool_name") or "").strip()
    tool_description = (output_mode.get("tool_description") or "").strip()
    parameters = output_mode.get("parameters")
    if not tool_name:
        return jsonify({"ok": False, "error": "output_mode.tool_name is required"}), 400
    if not parameters or not isinstance(parameters, dict):
        return jsonify({"ok": False, "error": "output_mode.parameters is required"}), 400

    # 读取配置
    config_mgr = ConfigManager(Storage())
    base_url = (config_mgr.get("ai_base_url") or "").strip().rstrip("/")
    api_key = (config_mgr.get("ai_api_key") or "").strip()
    model = (config_mgr.get("ai_model") or "").strip()
    db_system_prompt = config_mgr.get("ai_system_prompt") or ""

    if not base_url:
        return jsonify({"ok": False, "error": "AI Base URL 未配置"}), 400
    if not api_key:
        return jsonify({"ok": False, "error": "AI API Key 未配置"}), 400
    if not model:
        return jsonify({"ok": False, "error": "AI 模型未配置"}), 400

    # 图片根目录
    images_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "images"
    )

    def _resolve_content(content):
        """递归转换消息 content，把 image_id 转为 image_url base64。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            resolved = []
            for item in content:
                if not isinstance(item, dict):
                    resolved.append(item)
                    continue
                item_type = item.get("type", "")
                if item_type == "image_id":
                    img_id = (item.get("image_id") or "").strip()
                    if not img_id:
                        resolved.append(item)
                        continue
                    # 尝试 jpg → png → webp → gif
                    for ext in (".jpg", ".png", ".webp", ".gif"):
                        img_path = os.path.join(images_root, f"{img_id}{ext}")
                        if os.path.exists(img_path):
                            break
                    else:
                        raise FileNotFoundError(f"图片不存在: data/images/{img_id}.*")
                    mime_map = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
                    mime = mime_map.get(os.path.splitext(img_path)[1].lower(), "image/jpeg")
                    try:
                        with open(img_path, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode("utf-8")
                    except Exception as e:
                        raise RuntimeError(f"图片读取失败 {img_path}: {e}")
                    resolved.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    })
                else:
                    resolved.append(item)
            return resolved
        return content

    # 转换 messages
    converted = []
    for msg in raw_messages:
        role = msg.get("role", "user")
        content = _resolve_content(msg.get("content", ""))
        converted.append({"role": role, "content": content})

    # system prompt 处理：如果 DB 有 preset，插入到第一条 system 之前；追加工具调用指令
    tool_instruction = f"\n\n你必须调用 {tool_name} 工具来输出结果，不得输出其他内容。"
    final_messages = []
    system_added = False
    for msg in converted:
        if msg["role"] == "system":
            sys_content = msg["content"]
            if db_system_prompt and not system_added:
                sys_content = db_system_prompt + "\n\n" + (sys_content if sys_content else "")
                system_added = True
            # 最后一条 system 消息追加工具指令
            final_messages.append({"role": "system", "content": sys_content + tool_instruction})
        else:
            final_messages.append(msg)

    # 如果没有 system 消息，在开头插入
    has_system = any(m["role"] == "system" for m in final_messages)
    if not has_system:
        preset = db_system_prompt or "你是一个专业的图片分析助手。"
        final_messages.insert(0, {"role": "system", "content": preset + tool_instruction})

    # tool 定义
    tool_def = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_description or f"输出分析结果",
            "parameters": parameters,
        },
    }

    max_retries = 3

    async def _do_request(attempt: int) -> dict:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": final_messages,
                    "tools": [tool_def],
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": tool_name},
                    },
                    "max_tokens": 4096,
                },
            )
        duration_ms = int((time.perf_counter() - t0) * 1000)

        if resp.status_code != 200:
            resp_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = resp_data.get("error", {}).get("message", resp.text[:200])
            return {"ok": False, "error": f"{resp.status_code}: {error_msg}", "duration_ms": duration_ms, "attempt": attempt}

        resp_data = resp.json()
        usage = resp_data.get("usage", {})
        choice = (resp_data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            logger.warning(f"AI vision attempt {attempt}: no tool_calls in response, content={str(msg.get('content',''))[:200]}")
            return {
                "ok": False,
                "error": "模型未调用工具（未返回 tool_calls），将重试",
                "raw_content": msg.get("content", "")[:500],
                "duration_ms": duration_ms,
                "attempt": attempt,
            }

        for tc in tool_calls:
            func = tc.get("function") or {}
            if func.get("name") == tool_name:
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError as e:
                    logger.warning(f"AI vision attempt {attempt}: JSON parse failed: {e}, raw={func.get('arguments','')[:200]}")
                    return {
                        "ok": False,
                        "error": f"工具调用参数 JSON 解析失败: {e}",
                        "raw_args": func.get("arguments", "")[:500],
                        "duration_ms": duration_ms,
                        "attempt": attempt,
                    }
                return {
                    "ok": True,
                    "result": args,
                    "attempts": attempt,
                    "duration_ms": duration_ms,
                    "usage": {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                }

        logger.warning(f"AI vision attempt {attempt}: tool {tool_name} not found in tool_calls")
        return {
            "ok": False,
            "error": f"模型调用了其他工具，非 {tool_name}",
            "duration_ms": duration_ms,
            "attempt": attempt,
        }

    async def _run_with_retry():
        last_error = None
        for attempt in range(1, max_retries + 1):
            logger.info(f"AI vision attempt {attempt}/{max_retries}")
            try:
                result = await _do_request(attempt)
            except httpx.ConnectError:
                result = {"ok": False, "error": f"无法连接到 {base_url}", "attempt": attempt}
            except httpx.TimeoutException:
                result = {"ok": False, "error": "请求超时（120s）", "attempt": attempt}
            except FileNotFoundError as e:
                return jsonify({"ok": False, "error": str(e)}), 404
            except RuntimeError as e:
                return jsonify({"ok": False, "error": str(e)}), 500
            except Exception as e:
                logger.error(f"AI vision attempt {attempt} exception: {e}\n{traceback.format_exc()}")
                result = {"ok": False, "error": str(e), "attempt": attempt}

            if result["ok"]:
                return result
            last_error = result
            if attempt < max_retries:
                await asyncio.sleep(1)

        return {
            "ok": False,
            "error": f"重试 {max_retries} 次后仍然失败: {last_error.get('error', '未知错误') if last_error else '未知错误'}",
            "attempts": max_retries,
            "last_error": last_error,
        }

    try:
        result = asyncio.run(_run_with_retry())
        return result if isinstance(result, tuple) else jsonify(result)
    except Exception as e:
        logger.error(f"AI vision failed: {e}\n{traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/generate-template", methods=["POST"])
def generate_template():
    """AI 生成 HTML 预览模板 — 根据表字段和用户描述生成含 {{字段}} 占位符的 HTML。

    Request::

        {
            "table": "ershouche_list",
            "prompt": "生成商品卡片列表"
        }

    Response::

        {
            "ok": true,
            "template": "<div class=\"card\">\n  <img src=\"{{image}}\">\n  <h3>{{title}}</h3>\n</div>",
            "duration_ms": 2345,
            "usage": {"prompt_tokens": 500, "completion_tokens": 200}
        }
    """
    import asyncio
    import httpx

    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "Empty body"}), 400

    table = (data.get("table") or "").strip()
    prompt = (data.get("prompt") or "").strip()

    if not table:
        return jsonify({"ok": False, "error": "table is required"}), 400
    if not prompt:
        return jsonify({"ok": False, "error": "prompt is required"}), 400

    try:
        _validate_identifier(table)
    except ValueError:
        return jsonify({"ok": False, "error": f"Invalid table name: {table}"}), 400

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

    s = Storage()
    cols = s.execute(f"PRAGMA table_info([{table}])", fetch="all")
    if not cols:
        return jsonify({"ok": False, "error": f"Table not found: {table}"}), 404

    col_names = [c["name"] for c in cols]

    order_col = "id" if "id" in col_names else f"[{col_names[0]}]"
    first_rows = s.execute(
        f"SELECT * FROM [{table}] ORDER BY {order_col} ASC LIMIT 1",
        fetch="all",
    )
    last_rows = s.execute(
        f"SELECT * FROM [{table}] ORDER BY {order_col} DESC LIMIT 1",
        fetch="all",
    )

    first_row = dict(zip(col_names, first_rows[0])) if first_rows else {}
    last_row = dict(zip(col_names, last_rows[0])) if last_rows else {}

    system_prompt = """你是一个专业的 HTML 模板生成助手。根据用户提供的数据库字段名、示例数据和 UI 描述，生成可直接渲染的 HTML 卡片模板。

规则：
1. 使用 {{字段名}} 作为数据占位符，字段名严格匹配用户提供的列名
2. 禁止使用任何模板引擎语法：禁止 {{#if}} / {{#each}} / {{#unless}} / {{else}} / {{/if}} / {{/each}} 等条件或循环语句，禁止使用 {{>partial}} 等引用语法
3. {{字段名}} 仅用于单个字段值的直接输出，不要嵌套、不要修饰、不要条件判断
4. 只输出纯净的 HTML 片段（可含内联 style），不要输出 markdown 代码块标记（```html 等）
5. 不要包含 <!DOCTYPE>、<html>、<head>、<body> 标签
6. 不生成 <script> 标签
7. 图片标签加 onerror="this.style.display='none'" 防止破图
8. 每个卡片最外层 div 不要设置 width（由外层 CSS Grid 控制），不设固定高度
9. 设计为响应式卡片：图片顶部、内容底部，视觉干净整洁
10. 直接输出 HTML 源码，不要任何解释性文字、不要前后缀"""

    user_parts = [
        f"数据表: {table}",
        f"可用字段: {', '.join(col_names)}",
    ]

    if first_row:
        user_parts.append("\n第一条数据示例:")
        for k, v in first_row.items():
            user_parts.append(f"  {k}: {str(v)[:200]}")

    if last_row:
        user_parts.append("\n最后一条数据示例:")
        for k, v in last_row.items():
            user_parts.append(f"  {k}: {str(v)[:200]}")

    user_parts.append(f"\n用户需求描述: {prompt}")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]

    async def _do():
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 4096,
                    "temperature": 0.7,
                },
            )
        duration_ms = int((time.perf_counter() - t0) * 1000)

        if resp.status_code != 200:
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {}
            error_msg = resp_data.get("error", {}).get("message", resp.text[:200])
            return {"ok": False, "error": f"{resp.status_code}: {error_msg}", "duration_ms": duration_ms}

        resp_data = resp.json()
        content = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")

        template = content.strip()
        if template.startswith("```html"):
            template = template[7:]
        elif template.startswith("```"):
            template = template[3:]
        if template.endswith("```"):
            template = template[:-3]
        template = template.strip()

        usage = resp_data.get("usage", {})
        return {
            "ok": True,
            "template": template,
            "duration_ms": duration_ms,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
        }

    try:
        result = asyncio.run(_do())
        # Auto-save to templates table on success
        if result.get("ok") and result.get("template"):
            s2 = Storage()
            s2.execute(
                "INSERT INTO templates (table_name, template_html, template_name) VALUES (?, ?, ?)",
                (table, result["template"], f"{table} - {prompt[:30]}"),
            )
            logger.info(f"模板已缓存: table={table}")
        return jsonify(result)
    except httpx.ConnectError:
        return jsonify({"ok": False, "error": f"无法连接到 {base_url}"}), 502
    except httpx.TimeoutException:
        return jsonify({"ok": False, "error": "请求超时（120s）"}), 504
    except Exception as e:
        logger.error(f"generate-template failed: {e}\n{traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/templates", methods=["GET"])
def list_templates():
    """列出指定表的所有模板。"""
    table = request.args.get("table", "").strip()
    if not table:
        return jsonify({"ok": False, "error": "table is required"}), 400
    try:
        _validate_identifier(table)
    except ValueError:
        return jsonify({"ok": False, "error": f"Invalid table name: {table}"}), 400

    s = Storage()
    rows = s.execute(
        "SELECT id, table_name, template_html, template_name, created_at, updated_at "
        "FROM templates WHERE table_name = ? ORDER BY updated_at DESC",
        (table,),
        fetch="all",
    )
    return jsonify({
        "ok": True,
        "templates": [
            {
                "id": r["id"],
                "table_name": r["table_name"],
                "template_html": r["template_html"],
                "template_name": r["template_name"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ],
    })


@bp.route("/templates", methods=["POST"])
def save_template():
    """创建或更新模板。
    
    Request::
        { "table_name": "xxx", "template_html": "...", "template_name": "...", "id": 1 }
    
    - 不传 id → 新建
    - 传 id → 更新已有模板
    """
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "Empty body"}), 400

    table_name = (data.get("table_name") or "").strip()
    template_html = (data.get("template_html") or "").strip()
    template_name = (data.get("template_name") or "").strip()
    template_id = data.get("id")

    if not table_name or not template_html:
        return jsonify({"ok": False, "error": "table_name and template_html are required"}), 400
    try:
        _validate_identifier(table_name)
    except ValueError:
        return jsonify({"ok": False, "error": f"Invalid table name: {table_name}"}), 400

    s = Storage()
    if template_id:
        s.execute(
            "UPDATE templates SET template_html = ?, template_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (template_html, template_name, int(template_id)),
        )
        return jsonify({"ok": True, "id": int(template_id)})
    else:
        cur = s.execute(
            "INSERT INTO templates (table_name, template_html, template_name) VALUES (?, ?, ?)",
            (table_name, template_html, template_name),
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@bp.route("/templates/<int:template_id>", methods=["DELETE"])
def delete_template(template_id):
    """删除模板。"""
    s = Storage()
    s.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    return jsonify({"ok": True})
