# 58同城爬虫框架 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建一个可扩展的58同城数据采集框架,支持IP池、请求池、资源拦截缓存、字体反爬破解、验证码处理、插件化Parser、SQLite持久化。

**Architecture:** 6层架构(调度/请求池/浏览器拦截/解析/持久化/配置),Parser插件化,所有可变参数进config表运行时可调,日志分info/debug两级,请求状态机驱动断点续爬。

**Tech Stack:** Python 3.13 + Playwright(浏览器渲染+资源拦截) + fontTools + PIL + ddddocr(字体解密+滑块过码) + lxml(HTML解析) + SQLite(持久化) + logging(日志) + httpx(图片下载)

---

## 一、整体架构(6层)

```
┌─────────────────────────────────────────────┐
│  6. 配置层 (Config)                           │
│     SQLite config表,运行时可调                │
│     - IP池参数 / 反爬参数 / Parser注册表       │
│     - 全局开关 / 缓存策略 / 验证码策略         │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  1. 调度层 (Scheduler)                        │
│     - 从queue表取pending/failed的URL          │
│     - 按URL匹配Parser插件                     │
│     - 速率控制(全局/单域名/单IP)              │
│     - 优雅退出(SIGINT)                       │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  2. 请求池层 (RequestPool)                    │
│     - 向IP池申请IP                            │
│     - 反爬处理(随机UA/延迟/Referer/Cookie)    │
│     - 错误分类重试(超时/403/5xx)              │
│     - 记录换IP次数到requests表                │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  3. 浏览器层 (Playwright + 拦截器)            │
│     - route()拦截JS/CSS/静态font → 本地缓存  │
│     - 动态加密字体(内嵌Base64)放行不缓存      │
│     - CaptchaHandler 检测+处理验证码          │
│     - 等待渲染完成                            │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  4. 解析层 (Parser插件)                       │
│     - 工具链注入:                             │
│       FontDecoder(fontTools+PIL+ddddocr)     │
│       HtmlParser(lxml)                       │
│       ImageDownloader(httpx)                 │
│       CaptchaHandler(ddddocr+Playwright)     │
│     - parse(page,url) → (data,new_urls,imgs) │
│     - 业务表由Parser声明,自动建表             │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  5. 持久层 (Storage)                          │
│     - requests表(请求记录+换IP次数)           │
│     - 业务表(Parser定义)                     │
│     - seen_urls表(URL去重)                   │
│     - proxy_pool表(IP池状态)                 │
│     - captcha_log表(验证码记录)              │
│     - config表(配置)                         │
│     - 文件: images/ cache/ logs/             │
└─────────────────────────────────────────────┘
```

---

## 二、目录结构

```
project_root/
├── main.py                      # 入口,启动调度器
├── config.py                    # 全局常量、路径定义
├── core/
│   ├── __init__.py
│   ├── scheduler.py             # 调度层
│   ├── request_pool.py          # 请求池层
│   ├── browser.py               # 浏览器层(Playwright封装)
│   ├── interceptor.py           # 资源拦截+缓存
│   ├── storage.py               # 持久层(SQLite封装)
│   ├── config_manager.py        # 配置层(读写config表)
│   ├── logger.py                # 日志库封装(info/debug两级)
│   └── state_machine.py         # 请求状态机
├── proxy/
│   ├── __init__.py
│   ├── pool.py                  # IP池管理
│   ├── provider.py              # 代理服务商API(巨量HTTP)
│   └── health_check.py          # IP健康检查
├── parser/
│   ├── __init__.py
│   ├── base.py                  # Parser基类+工具链注入
│   ├── registry.py              # Parser注册表
│   ├── tools/
│   │   ├── font_decoder.py      # 字体解密器(fontTools+ddddocr)
│   │   ├── html_parser.py       # HTML解析(lxml)
│   │   ├── image_downloader.py  # 图片下载(httpx)
│   │   └── captcha_handler.py   # 验证码处理(ddddocr)
│   └── plugins/                 # 具体Parser插件
│       ├── __init__.py
│       ├── ershouche_list.py    # 58二手车列表页
│       └── ershouche_detail.py  # 58二手车详情页
├── data/
│   ├── crawler.db               # SQLite数据库
│   ├── images/                  # 业务图片
│   ├── cache/                   # 静态资源缓存(JS/CSS/font)
│   │   ├── js/
│   │   ├── css/
│   │   └── font/
│   ├── logs/
│   │   ├── run.log              # INFO级日志
│   │   └── error.log            # ERROR级日志
│   └── html_snapshot/           # 解析失败的HTML快照
└── tests/
    ├── __init__.py
    ├── test_storage.py
    ├── test_proxy_pool.py
    ├── test_state_machine.py
    ├── test_interceptor.py
    └── test_font_decoder.py
```

---

## 三、数据库表设计

### 3.1 config表(配置层)

```sql
CREATE TABLE config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    description TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**默认配置项:**

| key | 默认value | description |
|---|---|---|
| proxy_enabled | true | 是否启用代理 |
| proxy_provider | juliang | 代理服务商:juliang/kuaidaili |
| proxy_api_url | (空) | 巨量HTTP API提取URL |
| proxy_fetch_num | 10 | 每次拉取IP数量 |
| proxy_ttl | 60 | IP有效期秒数 |
| proxy_max_use | 3 | 单IP最多使用次数 |
| proxy_health_interval | 300 | 健康检查间隔秒 |
| cache_enabled | true | 是否启用静态资源缓存 |
| cache_html_ttl | 86400 | HTML缓存有效期秒 |
| image_download | true | 是否下载业务图片 |
| request_concurrency | 3 | 全局并发数 |
| request_interval_min | 1.0 | 请求最小间隔秒 |
| request_interval_max | 3.0 | 请求最大间隔秒 |
| request_timeout | 30 | 请求超时秒 |
| retry_network | 3 | 网络错误重试次数 |
| retry_5xx | 2 | 5xx错误重试次数 |
| domain_rate_limit | 10 | 单域名每秒最大请求数 |
| ip_rate_limit | 5 | 单IP每分钟最大请求数 |
| captcha_enabled | true | 是否处理验证码 |
| captcha_auto_solve | true | 是否自动接码 |
| captcha_max_retry | 3 | 自动接码重试次数 |
| captcha_fallback | manual | 降级策略:manual/switch_ip |
| captcha_max_switch | 5 | 换IP模式单URL最多换IP次数 |
| captcha_cooldown | 1800 | 触发验证码后IP冷却秒 |
| log_level | INFO | 日志级别:INFO/DEBUG |

### 3.2 queue表(请求队列+状态机)

```sql
CREATE TABLE queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    url_hash        TEXT UNIQUE NOT NULL,      -- URL+参数哈希,去重用
    parser_name     TEXT,                      -- 匹配的Parser名
    status          TEXT DEFAULT 'pending',    -- pending/running/done/failed/blocked/skipped
    retry_count     INTEGER DEFAULT 0,         -- 通用重试次数
    ip_switch_count INTEGER DEFAULT 0,         -- 换IP次数(验证码触发)
    priority        INTEGER DEFAULT 0,         -- 优先级,数字大优先
    parent_id       INTEGER,                   -- 来源URL的queue.id
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    error_msg       TEXT,
    error_type      TEXT,                      -- network/403/captcha/404/5xx/parse
    FOREIGN KEY (parent_id) REFERENCES queue(id)
);
CREATE INDEX idx_queue_status ON queue(status);
CREATE INDEX idx_queue_url_hash ON queue(url_hash);
```

**状态机流转:**
```
pending → running → done              (成功)
                  → failed            (可重试:网络/5xx/解析失败)
                  → blocked           (不重试:403/验证码,换IP+冷却)
                  → skipped           (已存在且未过期)
failed → running                      (重试)
blocked → pending                     (冷却后重新入队)
```

### 3.3 requests表(请求记录)

```sql
CREATE TABLE requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id        INTEGER NOT NULL,           -- 关联queue表
    url             TEXT NOT NULL,
    proxy_ip        TEXT,                       -- 使用的代理IP
    method          TEXT DEFAULT 'GET',
    status_code     INTEGER,                    -- HTTP状态码
    request_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_ms     INTEGER,                    -- 耗时毫秒
    response_size   INTEGER,                    -- 响应大小字节
    extracted_data  TEXT,                       -- 提取的数据JSON
    image_paths     TEXT,                       -- 下载的图片相对路径JSON数组
    request_status  TEXT,                       -- success/failed/blocked/captcha
    ip_switch_count INTEGER DEFAULT 0,          -- 本次请求换IP次数
    captcha_triggered INTEGER DEFAULT 0,        -- 是否触发验证码:0/1
    error_msg       TEXT,
    FOREIGN KEY (queue_id) REFERENCES queue(id)
);
CREATE INDEX idx_requests_queue ON requests(queue_id);
CREATE INDEX idx_requests_time ON requests(request_time);
```

### 3.4 seen_urls表(URL去重)

```sql
CREATE TABLE seen_urls (
    url_hash    TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fetch_count INTEGER DEFAULT 1
);
```

### 3.5 proxy_pool表(IP池)

```sql
CREATE TABLE proxy_pool (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ip              TEXT NOT NULL,
    port            INTEGER NOT NULL,
    protocol        TEXT DEFAULT 'http',
    city            TEXT,                       -- IP归属城市
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expire_at       TIMESTAMP NOT NULL,         -- IP过期时间
    use_count       INTEGER DEFAULT 0,          -- 已使用次数
    max_use         INTEGER DEFAULT 3,          -- 最大使用次数
    status          TEXT DEFAULT 'idle',        -- idle/in_use/cooldown/dead
    fail_count      INTEGER DEFAULT 0,          -- 连续失败次数
    last_used_at    TIMESTAMP,
    cooldown_until  TIMESTAMP,                  -- 冷却结束时间
    UNIQUE(ip, port)
);
CREATE INDEX idx_proxy_status ON proxy_pool(status);
CREATE INDEX idx_proxy_expire ON proxy_pool(expire_at);
```

### 3.6 captcha_log表(验证码记录)

```sql
CREATE TABLE captcha_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      INTEGER,                    -- 关联requests表
    queue_id        INTEGER,                    -- 关联queue表
    url             TEXT NOT NULL,
    proxy_ip        TEXT,
    strategy        TEXT,                       -- auto/manual/switch_ip
    attempt_count   INTEGER DEFAULT 0,          -- 自动接码尝试次数
    final_status    TEXT,                       -- success/manual/switched_ip/failed
    triggered_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES requests(id),
    FOREIGN KEY (queue_id) REFERENCES queue(id)
);
```

### 3.7 业务表(由Parser声明,自动建表)

Parser通过类属性声明表结构,启动时自动建表。示例:

```python
# parser/plugins/ershouche_list.py
class ErshoucheListParser(BaseParser):
    url_pattern = r'58\.com/ershouche/?$'
    table_name = 'ershouche_cars'
    table_schema = '''
        CREATE TABLE ershouche_cars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id      TEXT UNIQUE NOT NULL,    -- 58车辆ID,数据去重主键
            title       TEXT,
            price       REAL,                    -- 解密后真实价格
            year        INTEGER,
            mileage     TEXT,
            city        TEXT,
            url         TEXT,
            image_path  TEXT,                    -- 图片相对路径
            crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''
```

---

## 四、核心模块设计

### 4.1 日志库(logger.py)

**需求:** info/debug两级,日志详细,分文件输出。

**设计:**
- `run.log`:INFO级,记录关键流程(开始/结束/URL处理/换IP/验证码触发)
- `error.log`:ERROR级,仅错误
- 控制台:INFO级,带颜色,实时进度
- DEBUG模式(配置`log_level=DEBUG`):额外输出请求详情、拦截资源、解析过程

**日志规范:**
- 每个模块用独立logger:`logger = logging.getLogger('crawler.proxy')`
- 关键节点必打日志:
  - 调度器取URL: `[Scheduler] 取到URL: {url}, parser: {name}`
  - 请求池发请求: `[RequestPool] 请求 {url}, IP: {ip}, 第{N}次`
  - 换IP: `[RequestPool] 换IP: {old_ip} → {new_ip}, 累计换IP: {count}`
  - 拦截资源: `[Interceptor] 拦截: {resource_type} {url} → {action}`
  - 验证码触发: `[Captcha] 触发: {url}, IP: {ip}, 策略: {strategy}`
  - 解析完成: `[Parser:{name}] 提取数据: {count}条, 新URL: {count}个`

### 4.2 状态机(state_machine.py)

**职责:** 管理queue表状态流转,线程安全。

**关键方法:**
- `acquire()`:取pending/failed的URL,标记为running
- `mark_done(queue_id)`:成功完成
- `mark_failed(queue_id, error_type, error_msg)`:失败,可重试
- `mark_blocked(queue_id, error_type, error_msg)`:阻塞,换IP冷却
- `mark_skipped(queue_id)`:跳过
- `increment_ip_switch(queue_id)`:换IP次数+1,返回当前次数
- `check_ip_switch_limit(queue_id, max_switch)`:检查是否超限

**换IP次数超限处理:**
```python
def increment_ip_switch(queue_id):
    """换IP次数+1,超限则标记blocked"""
    new_count = UPDATE queue SET ip_switch_count = ip_switch_count + 1 WHERE id = ?
    max_switch = config.get('captcha_max_switch', 5)
    if new_count >= max_switch:
        mark_blocked(queue_id, 'ip_switch_limit', f'换IP次数超限({new_count}/{max_switch})')
        log.warning(f'URL换IP次数超限({new_count}/{max_switch}),标记blocked: {url}')
        return True  # 超限
    return False  # 未超限
```

### 4.3 IP池(proxy/pool.py)

**职责:** 管理代理IP生命周期:拉取→分配→回收→健康检查→淘汰。

**核心流程:**

```
[补充线程] 池中可用IP < 阈值 → 调provider拉新IP → 入池
[分配] RequestPool申请 → 取idle状态、未过期、use_count<max_use的IP → 标记in_use
[回收-成功] use_count+1, 未超限→idle, 超限→dead
[回收-失败] fail_count+1, fail_count>=3→dead, 否则→cooldown(cooldown_until=now+冷却时间)
[健康检查] 每5分钟扫描 → 清理过期IP、dead IP
```

**IP池与RequestPool的交互:**
```python
# RequestPool 发请求
ip = proxy_pool.acquire()  # 申请IP
try:
    response = browser.get(url, proxy=ip)
    proxy_pool.release_success(ip)  # 成功回收
except NetworkError:
    proxy_pool.release_fail(ip)     # 失败回收
```

### 4.4 浏览器层+拦截器(browser.py + interceptor.py)

**资源拦截策略:**

| 资源类型 | 来源 | 处理 | 缓存 |
|---|---|---|---|
| JS | 外部URL | 拦截→查本地缓存→命中用本地/未命中下载+缓存 | ✅ cache/js/ |
| CSS | 外部URL | 同上 | ✅ cache/css/ |
| font(静态) | 外部URL(.woff/.ttf) | 同上 | ✅ cache/font/ |
| font(动态加密) | 内嵌Base64 | **不拦截,放行** | ❌ 不缓存 |
| 图片(页面内) | 外部URL | 放行(由Parser决定哪些下载) | ❌ |
| XHR/Fetch | - | 放行(可能含数据) | ❌ |

**拦截器判断逻辑:**
```python
async def handle_route(route, request):
    url = request.url
    resource_type = request.resource_type
    
    # 动态加密字体:Base64内嵌,URL以data:开头,不拦截
    if url.startswith('data:'):
        await route.continue_()
        return
    
    # 静态资源:JS/CSS/字体,查缓存
    if resource_type in ['script', 'stylesheet', 'font']:
        cache_path = get_cache_path(url, resource_type)
        if cache_path.exists():
            logger.debug(f'[Interceptor] 缓存命中: {resource_type} {url}')
            await route.fulfill(body=cache_path.read_bytes())
        else:
            logger.debug(f'[Interceptor] 下载并缓存: {resource_type} {url}')
            response = await route.fetch()
            cache_path.write_bytes(response.body)
            await route.fulfill(response=response)
        return
    
    # 其他资源放行
    await route.continue_()
```

**缓存文件命名:** 用URL的MD5哈希,避免特殊字符:
```
cache/js/a1b2c3d4e5f6.js
cache/css/f7e8d9c0b1a2.css
cache/font/1a2b3c4d5e6f.woff
```

### 4.5 Parser插件机制(parser/base.py + registry.py)

**Parser基类:**
```python
class BaseParser:
    url_pattern: str           # 正则,匹配URL
    table_name: str            # 业务表名
    table_schema: str          # 建表SQL
    
    def __init__(self, tools):
        self.font_decoder = tools.font_decoder
        self.html_parser = tools.html_parser
        self.image_downloader = tools.image_downloader
    
    def parse(self, page, url) -> dict:
        """子类实现:提取数据,返回dict"""
        raise NotImplementedError
    
    def extract_urls(self, page, url) -> list:
        """子类实现:提取新URL,返回list"""
        return []
    
    def extract_images(self, page, url) -> list:
        """子类实现:返回要下载的图片URL list"""
        return []
```

**Parser注册表(从config表加载):**
```python
class ParserRegistry:
    def __init__(self, db):
        # 扫描parser/plugins/目录,自动发现所有Parser类
        # 也可从config表的parser_register配置加载
        self.parsers = []
        for cls in discover_parsers():
            self.parsers.append(cls)
    
    def match(self, url) -> BaseParser:
        """根据URL匹配Parser"""
        for parser_cls in self.parsers:
            if re.search(parser_cls.url_pattern, url):
                return parser_cls(self.tools)
        return None  # 无匹配,跳过
```

### 4.6 字体解密器(parser/tools/font_decoder.py)

**工作流:**
```
1. 从页面HTML提取内嵌的Base64字体编码(正则)
2. Base64解码 → 保存临时.ttf
3. fontTools解析cmap → 获取Unicode→字形映射
4. 对每个加密Unicode:
   - PIL生成120x120白底黑字图片(文字居中)
   - ddddocr识别 → 真实数字/字符
   - 构建 {加密字符: 真实字符} 映射表
5. 用映射表解密加密字段
```

**可配置(不同频道加密字段不同):**
```python
class FontDecoder:
    def __init__(self, font_css_selector='style', encrypted_selector='.fontSecret'):
        self.font_css_selector = font_css_selector
        self.encrypted_selector = encrypted_selector
        self.ocr = ddddocr.DdddOcr(show_ad=False)
    
    def decode(self, html, encrypted_text) -> str:
        """解密文本"""
        font_map = self._build_font_map(html)
        return ''.join([font_map.get(c, c) for c in encrypted_text])
```

### 4.7 验证码处理器(parser/tools/captcha_handler.py)

**决策流(两个独立开关):**
```
检测到验证码页
  ↓
读 captcha_auto_solve 配置
  ├─ false → 跳过自动接码,直接走降级
  └─ true  → 自动接码,重试 captcha_max_retry 次
              ├─ 成功 → 继续
              └─ 失败 → 走降级
  ↓
读 captcha_fallback 配置
  ├─ "manual"    → 暂停,弹浏览器等人工
  └─ "switch_ip" → increment_ip_switch()
                     ├─ 未超限 → 换IP重试
                     └─ 超限 → 强制转人工
```

**关键:换IP次数记录在queue表的ip_switch_count列,requests表也记录。**

### 4.8 调度层(core/scheduler.py)

**主循环:**
```python
class Scheduler:
    def run(self):
        logger.info('爬虫启动')
        while True:
            # 优雅退出检查
            if self.shutdown_event.is_set():
                self._graceful_shutdown()
                break
            
            # 速率控制
            self.rate_limiter.wait()
            
            # 取URL
            task = self.state_machine.acquire()
            if not task:
                logger.info('队列空,等待10秒')
                time.sleep(10)
                continue
            
            # 匹配Parser
            parser = self.registry.match(task.url)
            if not parser:
                self.state_machine.mark_skipped(task.id)
                continue
            
            # 交给请求池处理
            self.request_pool.submit(task, parser)
    
    def _graceful_shutdown(self):
        """优雅退出:等当前请求完成,状态写回DB"""
        logger.info('收到退出信号,等待当前请求完成...')
        self.request_pool.wait_all()
        logger.info('所有请求完成,退出')
```

### 4.9 请求池层(core/request_pool.py)

**单URL处理流程:**
```python
def process_url(self, task, parser):
    url = task.url
    logger.info(f'开始处理: {url}')
    
    retry_count = 0
    max_retry = config.get('retry_network', 3)
    
    while retry_count <= max_retry:
        # 申请IP
        proxy_ip = self.proxy_pool.acquire()
        if not proxy_ip:
            logger.warning('IP池空,等待30秒')
            time.sleep(30)
            continue
        
        # 反爬处理
        self.anti_bot.apply(proxy_ip)  # 随机UA/延迟/Referer
        
        # 记录请求开始
        request_record = self.storage.create_request(task.id, url, proxy_ip)
        
        try:
            # 浏览器加载
            page = self.browser.get(url, proxy=proxy_ip)
            
            # 检测验证码
            if self.captcha_handler.is_captcha_page(page):
                logger.warning(f'触发验证码: {url}, IP: {proxy_ip}')
                request_record.captcha_triggered = 1
                
                handled = self.captcha_handler.handle(page, task, request_record)
                if not handled:
                    # 验证码未通过,走降级
                    if config.get('captcha_fallback') == 'switch_ip':
                        # 换IP次数+1(在queue表和requests表都记)
                        exceeded = self.state_machine.increment_ip_switch(task.id)
                        request_record.ip_switch_count += 1
                        if exceeded:
                            # 超限,强制转人工
                            self.captcha_handler.manual_intervention(page, task)
                        else:
                            self.proxy_pool.release_fail(proxy_ip, cooldown=True)
                            continue  # 换IP重试
                    else:
                        self.captcha_handler.manual_intervention(page, task)
            
            # 解析
            data = parser.parse(page, url)
            new_urls = parser.extract_urls(page, url)
            image_urls = parser.extract_images(page, url)
            
            # 下载图片
            image_paths = self.image_downloader.download_batch(image_urls)
            
            # 保存数据
            self.storage.save_business_data(parser.table_name, data)
            self.storage.add_new_urls(new_urls, parent_id=task.id)
            self.storage.mark_request_success(request_record, data, image_paths)
            self.state_machine.mark_done(task.id)
            
            logger.info(f'完成: {url}, 数据: {len(data)}条, 新URL: {len(new_urls)}个')
            self.proxy_pool.release_success(proxy_ip)
            return
            
        except NetworkError as e:
            logger.warning(f'网络错误: {url}, 重试{retry_count}/{max_retry}')
            self.proxy_pool.release_fail(proxy_ip)
            retry_count += 1
        except AntiBotError as e:
            logger.warning(f'反爬拦截: {url}, IP冷却')
            self.proxy_pool.release_fail(proxy_ip, cooldown=True)
            self.state_machine.mark_blocked(task.id, '403', str(e))
            return
        except ParseError as e:
            logger.error(f'解析失败: {url}, {e}')
            self.storage.save_html_snapshot(page, task.id)  # 存快照供排查
            self.state_machine.mark_failed(task.id, 'parse', str(e))
            return
```

---

## 五、实施任务分解

### 阶段1:基础设施(1-2天)

| 任务 | 文件 | 说明 |
|---|---|---|
| 1.1 项目骨架 | 全目录 | 建目录结构、requirements.txt、main.py入口 |
| 1.2 日志库 | core/logger.py | info/debug两级,分文件,控制台带颜色 |
| 1.3 配置管理 | core/config_manager.py | 读写config表,首次启动初始化默认配置 |
| 1.4 持久层 | core/storage.py | SQLite连接池、建表、CRUD封装 |
| 1.5 状态机 | core/state_machine.py | queue表状态流转、换IP计数 |
| 1.6 数据库初始化 | core/storage.py | 建所有系统表(config/queue/requests/seen_urls/proxy_pool/captcha_log) |

### 阶段2:IP池(1天)

| 任务 | 文件 | 说明 |
|---|---|---|
| 2.1 代理服务商对接 | proxy/provider.py | 巨量HTTP API,拉取IP |
| 2.2 IP池管理 | proxy/pool.py | 拉取/分配/回收/淘汰,线程安全 |
| 2.3 健康检查 | proxy/health_check.py | 定期清理过期/死亡IP |
| 2.4 测试 | tests/test_proxy_pool.py | 模拟IP生命周期 |

### 阶段3:浏览器+拦截(1-2天)

| 任务 | 文件 | 说明 |
|---|---|---|
| 3.1 Playwright封装 | core/browser.py | 启动浏览器、设置代理、加载页面 |
| 3.2 资源拦截器 | core/interceptor.py | route()拦截JS/CSS/静态font,缓存到本地 |
| 3.3 动态字体识别 | core/interceptor.py | 判断data:字体,不缓存放行 |
| 3.4 缓存管理 | core/interceptor.py | 文件哈希命名,查缓存,写缓存 |
| 3.5 测试 | tests/test_interceptor.py | 拦截+缓存命中验证 |

### 阶段4:解析层(2天)

| 任务 | 文件 | 说明 |
|---|---|---|
| 4.1 Parser基类 | parser/base.py | 定义接口、工具链注入、表声明 |
| 4.2 Parser注册表 | parser/registry.py | 扫描plugins目录、URL匹配 |
| 4.3 字体解密器 | parser/tools/font_decoder.py | fontTools+PIL+ddddocr |
| 4.4 HTML解析器 | parser/tools/html_parser.py | lxml封装 |
| 4.5 图片下载器 | parser/tools/image_downloader.py | httpx异步下载 |
| 4.6 验证码处理器 | parser/tools/captcha_handler.py | 检测+自动接码+降级 |
| 4.7 第一个Parser插件 | parser/plugins/ershouche_list.py | 58二手车列表页(完整实现) |
| 4.8 测试 | tests/test_font_decoder.py | 字体解密验证 |

### 阶段5:调度+请求池(1-2天)

| 任务 | 文件 | 说明 |
|---|---|---|
| 5.1 速率控制 | core/scheduler.py | 全局/单域名/单IP限速+随机抖动 |
| 5.2 请求池 | core/request_pool.py | 反爬处理、错误分类重试、换IP计数 |
| 5.3 调度器 | core/scheduler.py | 主循环、优雅退出 |
| 5.4 集成测试 | tests/ | 端到端跑通 |

### 阶段6:完善(1天)

| 任务 | 文件 | 说明 |
|---|---|---|
| 6.1 控制台进度 | core/scheduler.py | 实时显示已抓/总数/成功率/当前IP |
| 6.2 HTML快照 | core/storage.py | 解析失败时存HTML供排查 |
| 6.3 文档 | README.md | 使用说明、配置说明、Parser开发指南 |

---

## 六、关键技术决策

### 6.1 为什么用Playwright不用DrissionPage?

| 维度 | Playwright | DrissionPage |
|---|---|---|
| 资源拦截 | ✅ route()原生支持,可拦截/修改/缓存 | ❌ 基于CDP监听,修改能力弱 |
| 反检测 | 需装playwright-stealth | 较好 |
| 异步 | ✅ 原生async | ❌ 同步为主 |
| 生态 | ✅ 成熟 | 国产小众 |

**结论:** 资源拦截是核心需求,Playwright的route()是唯一能干净实现的方案。

### 6.2 为什么用SQLite不用Redis?

- 数据量:<100万条,SQLite轻松胜任
- 去重:SQLite的UNIQUE索引+INSERT OR IGNORE足够
- 断点续爬:SQLite天然持久化,无需额外配置
- 部署:零依赖,单文件
- Redis只在大规模分布式场景才有必要

### 6.3 为什么用巨量HTTP按IP计费?

- 58场景:页面流量小(100-200KB),但IP必须频繁换
- 按IP计费:100元≈2万个IP≈4万条数据,成本极低
- 按流量计费:同样数据量要60元,贵2倍+

---

## 七、配置示例

### 7.1 最小配置(只抓公开数据)

```sql
UPDATE config SET value='true' WHERE key='proxy_enabled';
UPDATE config SET value='juliang' WHERE key='proxy_provider';
UPDATE config SET value='https://dps.juliangip.com/...' WHERE key='proxy_api_url';
UPDATE config SET value='false' WHERE key='captcha_auto_solve';
UPDATE config SET value='switch_ip' WHERE key='captcha_fallback';
UPDATE config SET value='3' WHERE key='captcha_max_switch';
```

### 7.2 需要登录态数据(配合账号池,本框架不实现账号池)

```sql
UPDATE config SET value='true' WHERE key='captcha_auto_solve';
UPDATE config SET value='manual' WHERE key='captcha_fallback';
UPDATE config SET value='5' WHERE key='captcha_max_switch';
```

---

## 八、开发规范

### 8.1 日志规范

```python
import logging
logger = logging.getLogger('crawler.module_name')

# 关键流程用info
logger.info(f'开始处理: {url}')

# 详细过程用debug(配置log_level=DEBUG时才输出)
logger.debug(f'拦截资源: {resource_type} {url}')

# 警告(可恢复)
logger.warning(f'IP失效,换IP: {old_ip} → {new_ip}')

# 错误(记录但不崩溃)
logger.error(f'解析失败: {url}, {e}', exc_info=True)
```

### 8.2 错误处理规范

```python
class CrawlerError(Exception): pass
class NetworkError(CrawlerError): pass
class AntiBotError(CrawlerError): pass
class CaptchaError(CrawlerError): pass
class ParseError(CrawlerError): pass
```

所有异常继承自定义基类,请求池层统一捕获分类处理。

### 8.3 线程安全

- SQLite:用`check_same_thread=False`+连接池,或单线程写
- IP池:用`threading.Lock`保护
- queue表:用事务保证状态流转原子性

---

## 九、后续扩展方向(本期不实现)

1. **账号池:** 支持登录态数据(联系电话),需账号管理+Cookie维护+账号-IP绑定
2. **分布式:** 多机部署,改用Redis队列+共享IP池
3. **监控面板:** Flask Web UI,实时查看进度、手动操作
4. **自动扩Parser:** URL访问后自动学习页面结构,半自动生成Parser
5. **数据导出:** 支持导出CSV/Excel/JSON

---

## 十、风险与对策

| 风险 | 对策 |
|---|---|
| 58改版反爬策略 | Parser插件化,改Parser不改框架 |
| ddddocr识别不准 | 图片预处理(放大/二值化)+多次识别投票 |
| IP池耗尽 | 健康检查+自动补充+低水位告警 |
| Playwright内存泄漏 | 定期重启浏览器进程(每100个URL) |
| SQLite写锁竞争 | WAL模式+单写线程 |

---

**计划完成。下一步选择执行方式:**

1. **Subagent驱动(本会话)** - 我逐任务派发subagent实现,任务间review
2. **独立会话** - 新开会话用executing-plans批量执行

选哪种?
