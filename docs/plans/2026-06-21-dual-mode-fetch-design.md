# 双模式抓取设计：HTTP / Browser

> 日期：2026-06-21
> 状态：已确认（待实现）

## 背景

58 同城对 Playwright/CDP 协议有深度检测，stealth、系统 Chrome、CDP 直连、persistent context 均被拦截触发验证码。但实测发现**纯 HTTP 请求不触发验证码**——58 的反爬检测的是浏览器自动化协议本身，而非 HTTP 层。

当前系统是纯浏览器模式，所有页面抓取通过 Playwright `page.goto()` 完成。需要新增 HTTP 模式，支持每任务独立配置 fetch_mode 和请求参数。

## 设计原则

1. **HTTP 模式只是换 HTML 获取通道**——解析、存储、入队、图片下载全流程不变
2. **不引入新模块**——httpx 已是项目依赖，在 RequestPool 内加私有方法即可
3. **每任务级别控制**——queue 表加 fetch_mode 列，入队时指定
4. **三层参数合并**——config 全局默认 < Parser 类属性 < task.request_config 覆盖
5. **Parser 零改动**——`_get_html()` 已兼容字符串和 Page 对象

## 整体架构

```
RequestPool._process_url_async(task, parser)
  │
  ├── 读取 task.fetch_mode（默认 "browser"）
  │
  ├── fetch_mode == "browser"  → 现有流程不变
  │     browser.new_page(url, proxy) → page.goto → captcha检测 → page.content()
  │
  └── fetch_mode == "http"     → 新增 HTTP 通道
        httpx.AsyncClient(proxy, headers, cookies) → response.text
        │
        └── 返回 HTML 字符串，后续 parser.parse(html, url) 完全复用
```

两种模式后续流程完全一致：parser.parse(html, url) → save_business_data → extract_urls → enqueue new urls → image_download → mark_done。

## 数据结构变更

### 1. queue 表——加两列

```sql
ALTER TABLE queue ADD COLUMN fetch_mode     TEXT DEFAULT 'browser';
ALTER TABLE queue ADD COLUMN request_config TEXT;
```

#### request_config JSON 结构

```json
{
  "method": "GET",
  "headers": {"Referer": "https://cd.58.com/ershouche/"},
  "cookies": {"session_id": "xxx"},
  "params": {"page": "1", "city": "cd"},
  "body": null,
  "form_data": null,
  "json_body": null,
  "timeout": 30
}
```

- `method`：GET/POST/PUT/DELETE，默认 GET
- `headers`：任务级覆盖 headers
- `cookies`：任务级 cookies
- `params`：URL query params
- body 三选一，优先级：`json_body` > `form_data` > `body`
  - `body`：raw body（字符串/bytes）
  - `form_data`：form-data 字典（application/x-www-form-urlencoded 或 multipart）
  - `json_body`：JSON body（自动 Content-Type: application/json）
- `timeout`：覆盖全局 timeout（秒）

### 2. config 表——加 4 项

```python
("fetch_mode", "browser", "默认抓取模式:browser/http"),
("http_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...", "HTTP模式默认UA"),
("http_default_headers", "{}", "HTTP模式默认headers(JSON)"),
("http_follow_redirects", "true", "HTTP模式是否跟随重定向"),
```

### 3. BaseParser——加类属性

```python
class BaseParser:
    http_method: str = "GET"
    http_headers: dict = {}          # Parser 声明的额外 headers
    http_default_params: dict = {}   # 默认 query params
    requires_browser: bool = False   # 标记必须用浏览器模式
```

Parser 级别只声明"这个解析器需要什么额外参数"，不处理 body/form_data——那些是任务级别的事。

### 4. Storage.enqueue()——扩展签名

```python
def enqueue(self, url, parser_name=None, priority=0,
            parent_id=None, fetch_mode=None, request_config=None):
```

- `fetch_mode=None` 时回退到 config 全局默认
- 新 URL 入队（extract_urls 发现的）继承父任务的 `fetch_mode`
- **不继承** `request_config`（子页面参数通常不同）

## HTTP 请求流程

### _fetch_http() 实现

```python
async def _fetch_http(self, task, parser, proxy_record) -> str:
    """HTTP 模式获取 HTML。返回 response.text。"""

    # === 三层参数合并 ===
    # Layer 1: config 全局默认
    merged_headers = {
        "User-Agent": self.config.get("http_user_agent", DEFAULT_UA),
    }
    default_headers = json.loads(self.config.get("http_default_headers", "{}"))
    merged_headers.update(default_headers)

    # Layer 2: Parser 级补充
    merged_headers.update(getattr(parser, "http_headers", {}))
    merged_params = dict(getattr(parser, "http_default_params", {}))
    method = getattr(parser, "http_method", "GET")

    # Layer 3: 任务级覆盖
    rc = json.loads(task.get("request_config") or "{}")
    method = rc.get("method", method)
    merged_headers.update(rc.get("headers", {}))
    merged_params.update(rc.get("params", {}))
    cookies = rc.get("cookies", {})
    timeout = rc.get("timeout", self.config.get_int("request_timeout", 30))

    # 代理
    proxy_url = f"http://{proxy_record.ip}:{proxy_record.port}" if proxy_record else None

    # 发请求
    async with httpx.AsyncClient(
        proxy=proxy_url,
        follow_redirects=self.config.get_bool("http_follow_redirects", True),
        timeout=timeout,
    ) as client:
        request_kwargs = {
            "headers": merged_headers,
            "params": merged_params,
            "cookies": cookies,
        }

        # body 处理（三选一，优先级 json > form_data > body）
        if rc.get("json_body") is not None:
            request_kwargs["json"] = rc["json_body"]
        elif rc.get("form_data") is not None:
            request_kwargs["data"] = rc["form_data"]
        elif rc.get("body") is not None:
            request_kwargs["content"] = rc["body"]

        response = await client.request(method, task["url"], **request_kwargs)
        response.raise_for_status()
        return response.text
```

### 三层合并优先级

```
config 全局默认  →  Parser 类属性  →  task.request_config
     ↑                  ↑                    ↑
  所有任务共享      某类页面共享          单个任务独有
```

### HTTP 模式下的验证码检测

HTTP 响应可能也返回验证码页面。检测方式改为检查 response.text 中是否包含验证码特征字符串（如 `antibot/verifycode`、`callback.58.com/antibot`）。

触发验证码后走现有 captcha 处理流程，但 HTTP 模式下自动接码意义不大（没有浏览器渲染），建议直接走 `switch_ip` 或 `blocked` 策略。

## 不改变的东西

| 组件 | 说明 |
|---|---|
| RateLimiter | 按域名/IP 限速，两种模式通用 |
| StateMachine | 状态流转不变 |
| proxy_pool | 获取/释放逻辑不变 |
| interceptor | 仅浏览器模式使用，HTTP 模式不涉及 |
| font_decoder | 两种模式都用（字体加密在 HTML 中） |
| image_downloader | 独立于抓取模式 |
| scheduler | 主循环不变，只通过 request_pool 间接感知 |
| web 后台 | API 不变，前端可选加 fetch_mode 切换 |

## 错误处理映射

| httpx 异常 | 映射到 error_type | 状态机动作 |
|---|---|---|
| `ConnectError` / `TimeoutException` | `network` | failed → 重试 |
| `HTTPStatusError(4xx)` | `403` | blocked → 冷却 |
| `HTTPStatusError(5xx)` | `5xx` | failed → 重试 |
| 响应包含验证码特征 | `captcha` | blocked → 冷却/换IP |
| 其他异常 | `parse` | failed → 重试 |

## Parser 适配

现有 `_get_html()` 已兼容字符串和 Page 对象，Parser 代码零改动。

如果未来有 Parser 只支持浏览器模式（需要 JS 渲染），在类上声明：

```python
class SomeParser(BaseParser):
    requires_browser = True
```

`RequestPool` 检查到 `requires_browser=True` 时，即使 task.fetch_mode="http" 也强制走浏览器分支。

## 降级策略（可选，后续迭代）

HTTP 模式请求失败后，可自动降级到浏览器模式重试：

```python
if task.fetch_mode == "http":
    try:
        html = await self._fetch_http(task, parser, proxy)
    except Exception:
        html = await self._fetch_browser(task, proxy)
```

**先不做**，YAGNI。后续如果 HTTP 模式成功率不理想再加。

## 完整改动清单

| 文件 | 改动 | 工作量 |
|---|---|---|
| `core/storage.py` | queue 表加 2 列 + `enqueue()` 扩展 + 迁移 | 小 |
| `core/config_manager.py` | 加 4 项默认配置 | 极小 |
| `core/request_pool.py` | 新增 `_fetch_http()` + `_process_url_async` 分支 | 中 |
| `parser/base.py` | 加 4 个类属性 | 极小 |
| `core/state_machine.py` | `acquire()` 返回值加 `fetch_mode` / `request_config` | 小 |
| `main.py` | `enqueue` 调用传 `fetch_mode` | 极小 |
| `parser/plugins/*` | 可选：声明 `http_headers` 等 | 按需 |
| `tests/` | 新增 HTTP 模式测试用例 | 中 |

**不动的**：scheduler、rate_limiter、proxy_pool、interceptor、font_decoder、image_downloader、web 后台。
