# 58同城爬虫框架

可扩展的 58 同城数据采集框架，支持 IP 池、请求池、资源拦截缓存、字体反爬破解、验证码处理、插件化 Parser、SQLite 持久化。

## 技术栈

- Python 3.13 + Playwright（浏览器渲染 + 资源拦截）
- fontTools + PIL + ddddocr（字体解密 + 滑块过码）
- lxml（HTML 解析）
- httpx（异步图片下载 + 代理 API）
- SQLite（持久化，WAL 模式）

## 架构（6 层）

```
配置层 (Config)        SQLite config 表，运行时可调
   ↓
调度层 (Scheduler)     取 URL → 匹配 Parser → 速率控制 → 优雅退出
   ↓
请求池 (RequestPool)   申请 IP → 反爬 → browser.get → 验证码 → 解析 → 存数据
   ↓
浏览器 (Browser)       Playwright + route() 资源拦截 + 缓存
   ↓
解析层 (Parser)        插件化，工具链注入（FontDecoder/HtmlParser/...）
   ↓
持久层 (Storage)       SQLite 封装，6 张系统表 + 业务表自动建
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置代理（可选）

编辑 `data/crawler.db` 的 config 表，或用 SQL：

```sql
UPDATE config SET value='true' WHERE key='proxy_enabled';
UPDATE config SET value='juliang' WHERE key='proxy_provider';
UPDATE config SET value='https://dps.juliangip.com/...' WHERE key='proxy_api_url';
UPDATE config SET value='switch_ip' WHERE key='captcha_fallback';
```

不配置代理则直连抓取。

### 3. 启动爬虫

```bash
# 从已有队列继续
python main.py

# 指定种子 URL
python main.py --seed https://ershouche.58.com/

# 限量抓取
python main.py --seed-url https://ershouche.58.com/ --max-tasks 100

# 调试模式（显示浏览器 + DEBUG 日志）
python main.py --show-browser --log-level DEBUG

# 禁用代理直连
python main.py --no-proxy
```

## 目录结构

```
58-data/
├── main.py                  # 入口
├── config.py                # 路径常量
├── core/
│   ├── scheduler.py         # 调度层 + RateLimiter
│   ├── request_pool.py      # 请求池
│   ├── browser.py           # Playwright 封装
│   ├── interceptor.py       # 资源拦截 + 缓存
│   ├── storage.py           # SQLite 持久层
│   ├── config_manager.py    # 配置管理
│   ├── state_machine.py     # queue 状态机
│   └── logger.py            # 日志库
├── proxy/
│   ├── pool.py              # IP 池
│   ├── provider.py          # 代理服务商 API
│   └── health_check.py      # IP 健康检查
├── parser/
│   ├── base.py              # Parser 基类
│   ├── registry.py          # 注册表
│   ├── tools/
│   │   ├── font_decoder.py  # 字体解密
│   │   ├── html_parser.py   # lxml 封装
│   │   ├── image_downloader.py
│   │   └── captcha_handler.py
│   └── plugins/
│       ├── ershouche_list.py
│       └── ershouche_detail.py
├── data/                    # 运行时数据（DB/图片/缓存/日志）
├── web/                     # Flask + SocketIO 管理后台
│   ├── app.py               # 应用工厂
│   ├── socketio_handlers.py # WebSocket 实时推送
│   └── api/                 # 9 个蓝图 29 个路由
│       ├── dashboard.py     # 指标/进度/最近任务
│       ├── queue.py         # 队列查看/重试
│       ├── data.py          # 业务数据浏览/导出
│       ├── proxy.py         # IP 池管理
│       ├── captcha.py       # 验证码日志
│       ├── config_api.py    # 配置读写
│       ├── parsers.py       # Parser 管理
│       ├── logs.py          # 日志查询
│       └── crawler_control.py # 启停/暂停
├── build.py                 # PyInstaller 打包脚本（EXE）
├── examples/                # 示例运行脚本
└── tests/                   # 测试（394 用例）
```

## 配置项（25 项）

| key | 默认值 | 说明 |
|---|---|---|
| proxy_enabled | true | 是否启用代理 |
| proxy_provider | juliang | 代理服务商 |
| proxy_api_url | (空) | API 提取 URL |
| proxy_fetch_num | 10 | 每次拉取 IP 数 |
| proxy_ttl | 60 | IP 有效期秒 |
| proxy_max_use | 3 | 单 IP 最大使用次数 |
| cache_enabled | true | 静态资源缓存 |
| request_concurrency | 3 | 全局并发数 |
| request_interval_min | 1.0 | 请求最小间隔秒 |
| request_interval_max | 3.0 | 请求最大间隔秒 |
| request_timeout | 30 | 请求超时秒 |
| retry_network | 3 | 网络错误重试次数 |
| captcha_enabled | true | 是否处理验证码 |
| captcha_auto_solve | true | 自动接码 |
| captcha_max_retry | 3 | 接码重试次数 |
| captcha_fallback | manual | 降级策略：manual/switch_ip |
| captcha_max_switch | 5 | 换 IP 上限 |
| log_level | INFO | 日志级别 |

完整配置见 `core/config_manager.py` 的 `_DEFAULT_CONFIGS`。

## 开发 Parser 插件

1. 在 `parser/plugins/` 下新建 `.py` 文件
2. 继承 `BaseParser`，声明 `url_pattern` / `table_name` / `table_schema`
3. 实现 `parse(page, url)` / `extract_urls` / `extract_images`

```python
from parser.base import BaseParser

class MyParser(BaseParser):
    url_pattern = r"example\.com/list"
    table_name = "my_data"
    table_schema = """
        CREATE TABLE my_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT
        )
    """

    def parse(self, page, url):
        # page 可以是 HTML 字符串或 Playwright Page
        html = page if isinstance(page, str) else page.content()
        tree = self.html_parser.parse(html)
        items = self.html_parser.cssselect(tree, ".item")
        return [{"title": self.html_parser.text(i), "url": url} for i in items]
```

启动时 `ParserRegistry.discover()` 自动扫描注册，`ensure_all_tables()` 自动建表。

## 状态机流转

```
pending → running → done              (成功)
                  → failed            (可重试)
                  → blocked           (换 IP + 冷却)
                  → skipped           (无匹配 Parser)
failed  → running                      (重试)
blocked → pending                     (冷却后重置)
```

换 IP 次数记录在 `queue.ip_switch_count`，超限（`captcha_max_switch`）自动 blocked。

## 测试

```bash
# 全套件
pytest

# 单模块
pytest tests/test_storage.py -v

# 带覆盖率
pytest --cov=core --cov=parser --cov=proxy
```

当前 394 个测试覆盖所有核心模块。

## Web 管理后台

Flask + Flask-SocketIO 实现，9 个蓝图 29 个 API 路由，支持实时日志推送和任务状态更新。

### 启动 Web 后台

```bash
python -c "from web.app import create_app, socketio; app=create_app(); socketio.run(app, host='127.0.0.1', port=5000)"
```

### API 概览

| 蓝图 | 前缀 | 功能 |
|---|---|---|
| dashboard | /api/dashboard | 指标、进度、最近任务 |
| queue | /api/queue | 队列统计、查看、重试 |
| data | /api/data | 业务表浏览、导出 CSV |
| proxy | /api/proxy | IP 池查看、拉取、健康检查、删除 |
| captcha | /api/captcha | 验证码日志统计 |
| config | /api/config | 配置读写、重置 |
| parsers | /api/parsers | Parser 列表、开关、重扫、测试 |
| logs | /api/logs | 日志查询 |
| crawler | /api/crawler | 启动/暂停/停止 |

WebSocket 事件：`log`（日志推送）、`task_update`（状态变更）、`metrics_update`（指标更新）。

## 打包为 EXE

```bash
python build.py             # 全量构建（前端 + 后端 + Chromium）
python build.py --frontend  # 仅构建前端
```

输出 `dist/58-crawler/`，包含 `58-crawler.exe` + `_internal/`（Python 运行时 + 依赖 + Chromium）。

## 风险与对策

| 风险 | 对策 |
|---|---|
| 58 改版反爬 | Parser 插件化，改 Parser 不改框架 |
| ddddocr 识别不准 | 支持注入自定义 ocr_callable |
| IP 池耗尽 | 健康检查 + 自动补充 + 低水位告警 |
| Playwright 内存泄漏 | 每 100 个 URL 重启浏览器 |
| SQLite 写锁竞争 | WAL 模式 + RLock 串行化 |
