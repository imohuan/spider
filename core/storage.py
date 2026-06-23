"""存储模块 - SQLite 持久层封装。

按设计文档第三章实现 6 张系统表（config / queue / requests / seen_urls /
proxy_pool / captcha_log）的建表与 CRUD，提供线程安全的统一 execute 接口，
供 config_manager / state_machine / proxy_pool 等模块复用。

设计要点：
- 单连接 + ``threading.Lock`` 串行化所有写操作（``check_same_thread=False``）
- WAL 模式提升并发读能力
- ``get_connection()`` 上下文管理器获取独占访问权
- url_hash 算法：``hashlib.sha256(url.encode('utf-8')).hexdigest()``
- 业务表由 Parser 声明 schema，通过 ``ensure_business_table`` 自动建表
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH
from core.logger import get_logger

logger = get_logger("storage")

# SQL 标识符白名单（表名/列名）：字母/下划线开头，后接字母数字下划线
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str) -> str:
    """校验 SQL 标识符（表名/列名），不合格抛 ValueError。

    防止通过 f-string 拼接表名/列名时引入 SQL 注入。
    """
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name

# 6 张系统表的建表 SQL（IF NOT EXISTS，幂等）
_SYSTEM_SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    description TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    url_hash        TEXT UNIQUE NOT NULL,
    parser_name     TEXT,
    status          TEXT DEFAULT 'pending',
    retry_count     INTEGER DEFAULT 0,
    ip_switch_count INTEGER DEFAULT 0,
    priority        INTEGER DEFAULT 0,
    parent_id       INTEGER,
    fetch_mode      TEXT DEFAULT 'browser',
    request_config  TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    error_msg       TEXT,
    error_type      TEXT,
    FOREIGN KEY (parent_id) REFERENCES queue(id)
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_url_hash ON queue(url_hash);

CREATE TABLE IF NOT EXISTS requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id        INTEGER NOT NULL,
    url             TEXT NOT NULL,
    proxy_ip        TEXT,
    method          TEXT DEFAULT 'GET',
    status_code     INTEGER,
    request_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_ms     INTEGER,
    response_size   INTEGER,
    extracted_data  TEXT,
    image_paths     TEXT,
    request_status  TEXT,
    ip_switch_count INTEGER DEFAULT 0,
    captcha_triggered INTEGER DEFAULT 0,
    error_msg       TEXT,
    raw_response_path TEXT,
    response_headers TEXT,
    request_headers TEXT,
    finish_time     TIMESTAMP,
    FOREIGN KEY (queue_id) REFERENCES queue(id)
);
CREATE INDEX IF NOT EXISTS idx_requests_queue ON requests(queue_id);
CREATE INDEX IF NOT EXISTS idx_requests_time ON requests(request_time);

CREATE TABLE IF NOT EXISTS seen_urls (
    url_hash    TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fetch_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS proxy_pool (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ip              TEXT NOT NULL,
    port            INTEGER NOT NULL,
    protocol        TEXT DEFAULT 'http',
    city            TEXT,
    username        TEXT,
    password        TEXT,
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expire_at       TIMESTAMP NOT NULL,
    use_count       INTEGER DEFAULT 0,
    max_use         INTEGER DEFAULT 3,
    status          TEXT DEFAULT 'idle',
    fail_count      INTEGER DEFAULT 0,
    last_used_at    TIMESTAMP,
    cooldown_until  TIMESTAMP,
    UNIQUE(ip, port)
);
CREATE INDEX IF NOT EXISTS idx_proxy_status ON proxy_pool(status);
CREATE INDEX IF NOT EXISTS idx_proxy_expire ON proxy_pool(expire_at);

CREATE TABLE IF NOT EXISTS captcha_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      INTEGER,
    queue_id        INTEGER,
    url             TEXT NOT NULL,
    proxy_ip        TEXT,
    strategy        TEXT,
    attempt_count   INTEGER DEFAULT 0,
    final_status    TEXT,
    triggered_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES requests(id),
    FOREIGN KEY (queue_id) REFERENCES queue(id)
);

CREATE TABLE IF NOT EXISTS image_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    url_hash        TEXT NOT NULL,
    request_id      INTEGER,
    queue_id        INTEGER,
    status          TEXT DEFAULT 'pending',
    retry_count     INTEGER DEFAULT 0,
    max_retry       INTEGER DEFAULT 3,
    local_path      TEXT,
    error_msg       TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES requests(id),
    FOREIGN KEY (queue_id) REFERENCES queue(id)
);
CREATE INDEX IF NOT EXISTS idx_image_queue_status ON image_queue(status);
CREATE INDEX IF NOT EXISTS idx_image_queue_url_hash ON image_queue(url_hash);

CREATE TABLE IF NOT EXISTS templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name      TEXT NOT NULL,
    template_html   TEXT NOT NULL,
    template_name   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_templates_table ON templates(table_name);

CREATE TABLE IF NOT EXISTS cookie_presets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    domain        TEXT NOT NULL,
    cookies_json  TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cookie_presets_domain ON cookie_presets(domain);

CREATE TABLE IF NOT EXISTS workflow_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_name   TEXT NOT NULL,
    params          TEXT,
    status          TEXT DEFAULT 'pending',
    result          TEXT,
    error           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_queue(status);
CREATE INDEX IF NOT EXISTS idx_workflow_name ON workflow_queue(workflow_name);
"""


def _hash_url(url: str) -> str:
    """计算 URL 的 sha256 哈希（utf-8 编码）。"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class Storage:
    """SQLite 持久层封装。

    单连接 + ``threading.Lock`` 串行化所有访问，配合 ``check_same_thread=False``
    支持多线程调用。WAL 模式提升读并发。

    典型用法::

        from core.storage import Storage
        s = Storage()                    # 默认使用 config.DB_PATH
        qid = s.enqueue("http://example.com", parser_name="list")
        rid = s.create_request(qid, "http://example.com", proxy_ip="1.2.3.4")
        s.mark_request_success(rid, extracted_data={"k": "v"}, image_paths=[])

    也可作为上下文管理器使用，自动关闭连接::

        with Storage() as s:
            s.enqueue(url)
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or DB_PATH
        # 确保父目录存在（避免首次启动崩溃）
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._lock = threading.RLock()
        # check_same_thread=False 允许跨线程访问，由 self._lock 保证安全
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            # row_factory 让 fetchone/fetchall 返回 sqlite3.Row（支持按列名访问）
            isolation_level=None,  # autocommit，事务由我们显式 BEGIN/COMMIT 控制
        )
        self._conn.row_factory = sqlite3.Row

        # 启用 WAL：写不阻塞读，崩溃恢复更可靠
        with self._lock:
            mode = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()
            # foreign_keys 开启外键约束
            self._conn.execute("PRAGMA foreign_keys=ON")
        logger.debug(f"SQLite journal_mode={mode[0] if mode else 'unknown'}")

        self.init_db()

    # ---------------- 初始化 ----------------

    def init_db(self) -> None:
        """建所有系统表（IF NOT EXISTS，幂等）并执行自动迁移。在 __init__ 中自动调用。"""
        with self._lock:
            self._conn.executescript(_SYSTEM_SCHEMA)
        self._migrate()
        logger.debug("系统表已就绪（config/queue/requests/seen_urls/proxy_pool/captcha_log）")

    def _migrate(self) -> None:
        """自动添加缺失列（幂等）。"""
        # requests 表迁移
        columns_to_add = [
            ("raw_response_path", "TEXT"),
            ("response_headers", "TEXT"),
            ("request_headers", "TEXT"),
            ("finish_time", "TIMESTAMP"),
        ]
        with self._lock:
            existing = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(requests)").fetchall()
            }
            for col_name, col_type in columns_to_add:
                if col_name not in existing:
                    sql = f"ALTER TABLE requests ADD COLUMN {_validate_identifier(col_name)} {col_type}"
                    self._conn.execute(sql)
                    logger.info(f"自动迁移: requests 表添加列 {col_name} {col_type}")
            self._conn.commit()
        
        # proxy_pool 表迁移
        proxy_columns = [
            ("username", "TEXT"),
            ("password", "TEXT"),
        ]
        with self._lock:
            existing = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(proxy_pool)").fetchall()
            }
            for col_name, col_type in proxy_columns:
                if col_name not in existing:
                    sql = f"ALTER TABLE proxy_pool ADD COLUMN {_validate_identifier(col_name)} {col_type}"
                    self._conn.execute(sql)
                    logger.info(f"自动迁移: proxy_pool 表添加列 {col_name} {col_type}")
            self._conn.commit()

    # ---------------- 上下文管理 ----------------

    @contextmanager
    def get_connection(self) -> "sqlite3.Connection":
        """获取数据库连接的上下文管理器（独占访问）。

        持有 ``self._lock`` 直至退出，保证调用方在 with 块内的多步操作原子性。
        进入时显式 ``BEGIN`` 开启事务（因连接为 autocommit 模式），
        正常退出 ``COMMIT``，异常退出 ``ROLLBACK``。

        注意：复杂多步写操作建议使用此接口；单条 SQL 请用 :meth:`execute`。
        """
        self._lock.acquire()
        try:
            self._conn.execute("BEGIN")
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._lock.release()

    # ---------------- 通用执行接口 ----------------

    def execute(self, sql: str, params=(), fetch: str = "none"):
        """通用 SQL 执行接口（线程安全）。

        :param sql: SQL 语句（支持占位符 ``?``）
        :param params: 参数（tuple 或 list），默认空
        :param fetch: ``'one'`` 返回单行（sqlite3.Row 或 None）；
                      ``'all'`` 返回多行 list；
                      ``'none'`` 不返回结果（写操作）
        :return: 根据 fetch 返回结果，或 None

        注意：本方法不主动 commit。autocommit 模式下，DML 语句会立即生效；
        若需事务原子性，请使用 :meth:`get_connection` 显式管理事务边界。
        """
        with self._lock:
            cur = self._conn.execute(sql, params)
            result: object = None
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            return result

    # ---------------- queue 表 CRUD ----------------

    def enqueue(
        self,
        url: str,
        parser_name: str | None = None,
        priority: int = 0,
        parent_id: int | None = None,
        fetch_mode: str | None = None,
        request_config: str | dict | None = None,
    ) -> int:
        """URL 入队。

        - 计算 url_hash（sha256），按 UNIQUE 约束去重
        - 已存在则不重复插入（保留原 status/retry_count 等）
        - 同时更新 seen_urls.last_seen 与 fetch_count
        - 整个操作在单个事务内完成（queue 与 seen_urls 原子写入，
          崩溃时要么都生效要么都回滚）

        :param fetch_mode: 抓取模式 ``"browser"`` / ``"http"``。
            ``None`` 时用列默认值 ``"browser"``。
        :param request_config: 任务级请求参数，dict 会被 JSON 序列化。
            ``None`` 不写入（子页面通常不继承父任务参数）。
        :return: queue.id（新插入的或已存在的）
        """
        url_hash = _hash_url(url)
        # request_config dict → JSON 字符串
        if isinstance(request_config, dict):
            request_config = json.dumps(request_config, ensure_ascii=False)
        # fetch_mode None → 显式设为 'browser'（SQLite DEFAULT 不作用于显式 NULL）
        if fetch_mode is None:
            fetch_mode = "browser"
        with self.get_connection() as conn:
            # queue 插入
            conn.execute(
                "INSERT OR IGNORE INTO queue "
                "(url, url_hash, parser_name, priority, parent_id, fetch_mode, request_config) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (url, url_hash, parser_name, priority, parent_id,
                 fetch_mode, request_config),
            )
            row = conn.execute(
                "SELECT id FROM queue WHERE url_hash = ?", (url_hash,)
            ).fetchone()
            queue_id = row[0]
            # seen_urls 更新（同事务，保证原子性）
            conn.execute(
                "INSERT INTO seen_urls (url_hash, url, first_seen, last_seen, fetch_count) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1) "
                "ON CONFLICT(url_hash) DO UPDATE SET "
                "last_seen = CURRENT_TIMESTAMP, "
                "fetch_count = fetch_count + 1",
                (url_hash, url),
            )
        logger.debug(f"enqueue url={url} → queue_id={queue_id}")
        return queue_id

    # ---------------- seen_urls 表 CRUD ----------------

    def add_seen_url(self, url: str) -> str:
        """记录 URL 已见过。已存在则更新 last_seen 并 fetch_count+1。

        :return: url_hash
        """
        url_hash = _hash_url(url)
        with self._lock:
            self._conn.execute(
                "INSERT INTO seen_urls (url_hash, url, first_seen, last_seen, fetch_count) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1) "
                "ON CONFLICT(url_hash) DO UPDATE SET "
                "last_seen = CURRENT_TIMESTAMP, "
                "fetch_count = fetch_count + 1",
                (url_hash, url),
            )
            self._conn.commit()
        return url_hash

    def is_url_seen(self, url: str) -> bool:
        """判断 URL 是否已见过。"""
        url_hash = _hash_url(url)
        row = self.execute(
            "SELECT 1 FROM seen_urls WHERE url_hash = ?",
            (url_hash,),
            fetch="one",
        )
        return row is not None

    # ---------------- requests 表 CRUD ----------------

    def create_request(
        self,
        queue_id: int,
        url: str,
        proxy_ip: str | None,
        method: str = "GET",
    ) -> int:
        """创建一条 request 记录，返回其 id。"""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO requests (queue_id, url, proxy_ip, method) "
                "VALUES (?, ?, ?, ?)",
                (queue_id, url, proxy_ip, method),
            )
            self._conn.commit()
            request_id = cur.lastrowid
        logger.debug(
            f"create_request queue_id={queue_id} url={url} → request_id={request_id}"
        )
        return request_id

    def mark_request_success(
        self,
        request_id: int,
        extracted_data=None,
        image_paths=None,
        duration_ms: int | None = None,
        response_size: int | None = None,
        status_code: int = 200,
        raw_response_path: str | None = None,
        response_headers: dict | None = None,
        request_headers: dict | None = None,
    ) -> None:
        """标记 request 为 success，写入提取数据与图片路径。

        - ``extracted_data`` 支持 dict/list（自动 JSON 序列化）或 str
        - ``image_paths`` 支持 list/tuple（自动 JSON 序列化）或 str
        - ``raw_response_path`` 原始响应文件的相对路径
        - ``response_headers`` 响应头 dict
        - ``request_headers`` 实际发送的请求头 dict
        """
        if extracted_data is not None and isinstance(extracted_data, (dict, list)):
            extracted_data = json.dumps(extracted_data, ensure_ascii=False)
        if image_paths is not None and isinstance(image_paths, (list, tuple)):
            image_paths = json.dumps(list(image_paths), ensure_ascii=False)
        resp_headers_json = json.dumps(response_headers, ensure_ascii=False) if response_headers else None
        req_headers_json = json.dumps(request_headers, ensure_ascii=False) if request_headers else None
        with self._lock:
            self._conn.execute(
                "UPDATE requests SET "
                "status_code = ?, duration_ms = ?, response_size = ?, "
                "extracted_data = ?, image_paths = ?, request_status = 'success', "
                "raw_response_path = ?, response_headers = ?, request_headers = ?, "
                "finish_time = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (
                    status_code,
                    duration_ms,
                    response_size,
                    extracted_data,
                    image_paths,
                    raw_response_path,
                    resp_headers_json,
                    req_headers_json,
                    request_id,
                ),
            )
            self._conn.commit()

    def mark_request_failed(
        self,
        request_id: int,
        error_msg: str,
        status_code: int | None = None,
        duration_ms: int | None = None,
        raw_response_path: str | None = None,
        response_headers: dict | None = None,
    ) -> None:
        """标记 request 为 failed，写入错误信息与可选上下文。

        - ``raw_response_path`` 失败响应的原始内容文件路径
        - ``response_headers`` 若服务器有返回响应头则传入
        """
        resp_headers_json = json.dumps(response_headers, ensure_ascii=False) if response_headers else None
        with self._lock:
            self._conn.execute(
                "UPDATE requests SET "
                "status_code = ?, error_msg = ?, request_status = 'failed', "
                "duration_ms = ?, raw_response_path = ?, response_headers = ?, "
                "finish_time = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (status_code, error_msg, duration_ms, raw_response_path,
                 resp_headers_json, request_id),
            )
            self._conn.commit()

    # ---------------- 业务表 ----------------

    def ensure_business_table(self, table_name: str, table_schema: str) -> None:
        """Parser 声明的业务表自动建表（幂等）。

        :param table_name: 表名（用于存在性检查）
        :param table_schema: 完整的 ``CREATE TABLE`` 语句
        :raises ValueError: table_name 不是合法标识符，或 table_schema 不是
                            单条 ``CREATE TABLE`` 语句
        """
        table_name = _validate_identifier(table_name)
        # 校验 schema 是单条 CREATE TABLE 语句
        stripped = table_schema.strip()
        if not re.match(r"^CREATE\s+TABLE", stripped, re.IGNORECASE):
            raise ValueError("table_schema must start with CREATE TABLE")
        # 防多语句注入: CREATE TABLE 体内一般不含分号，
        # 除结尾分号外不应有其他分号
        if ";" in stripped[:-1]:
            raise ValueError("table_schema must be a single CREATE TABLE statement")
        with self._lock:
            cur = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            if cur.fetchone() is None:
                self._conn.execute(table_schema)
                self._conn.commit()
                logger.info(f"业务表已创建: {table_name}")

    def save_business_data(self, table_name: str, rows: list[dict]) -> None:
        """批量插入或替换业务数据（upsert 语义）。

        使用 INSERT OR REPLACE，当唯一键/主键冲突时自动替换旧行，
        避免重试任务时因重复数据报 UNIQUE constraint failed。

        :param table_name: 目标表名（必须已通过 ensure_business_table 创建）
        :param rows: dict 列表，每个 dict 的 key 为列名，value 为值。
                     所有 row 应有相同的列集合（以第一个 row 为准）。
        :raises ValueError: table_name 或列名不是合法 SQL 标识符
        """
        if not rows:
            return
        table_name = _validate_identifier(table_name)
        columns = list(rows[0].keys())
        for c in columns:
            _validate_identifier(c)
        col_str = ",".join(columns)
        placeholders = ",".join("?" * len(columns))
        sql = f"INSERT OR REPLACE INTO {table_name} ({col_str}) VALUES ({placeholders})"
        params_list = [tuple(row.get(c) for c in columns) for row in rows]
        with self._lock:
            self._conn.executemany(sql, params_list)
            self._conn.commit()
        logger.debug(f"save_business_data {table_name}: 写入 {len(rows)} 行")

    # ---------------- 图片下载队列 ----------------

    def enqueue_image(
        self, url: str, request_id: int | None = None,
        queue_id: int | None = None, max_retry: int = 3,
    ) -> int | None:
        """将图片 URL 加入下载队列。已下载/待下载的同 URL 不重复入队。

        :return: 插入的 row id，URL 已存在返回 None
        """
        url_hash = _hash_url(url)
        with self._lock:
            # 同 URL 已 pending 或已 done → 跳过
            existing = self._conn.execute(
                "SELECT id, status, local_path FROM image_queue "
                "WHERE url_hash=? AND status IN ('pending', 'done')",
                (url_hash,),
            ).fetchone()
            if existing:
                return None
            cur = self._conn.execute(
                "INSERT INTO image_queue (url, url_hash, request_id, queue_id, max_retry) "
                "VALUES (?,?,?,?,?)",
                (url, url_hash, request_id, queue_id, max_retry),
            )
            self._conn.commit()
            return cur.lastrowid

    def acquire_pending_images(self, limit: int = 10) -> list[dict]:
        """获取待下载的图片（按创建时间升序）。

        :return: 字典列表，含 id/url/retry_count/max_retry
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, url, retry_count, max_retry FROM image_queue "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                self._conn.executemany(
                    "UPDATE image_queue SET status='downloading' WHERE id=?",
                    [(i,) for i in ids],
                )
                self._conn.commit()
            return [
                {"id": r[0], "url": r[1], "retry_count": r[2], "max_retry": r[3]}
                for r in rows
            ]

    def mark_image_done(self, image_id: int, local_path: str) -> None:
        """标记图片下载成功。"""
        with self._lock:
            self._conn.execute(
                "UPDATE image_queue SET status='done', local_path=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (local_path, image_id),
            )
            self._conn.commit()

    def mark_image_failed(self, image_id: int, error_msg: str) -> str:
        """标记图片下载失败。retry_count < max_retry 则重回 pending, 否则 failed。

        :return: 新状态 'pending' 或 'failed'
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT retry_count, max_retry FROM image_queue WHERE id=?",
                (image_id,),
            ).fetchone()
            if not row:
                return "failed"
            retry, max_r = row
            retry += 1
            new_status = "pending" if retry < max_r else "failed"
            self._conn.execute(
                "UPDATE image_queue SET status=?, retry_count=?, error_msg=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_status, retry, error_msg, image_id),
            )
            self._conn.commit()
            return new_status

    def image_queue_stats(self) -> dict[str, int]:
        """返回图片队列状态计数。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM image_queue GROUP BY status"
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    # ---------------- 工作流队列 ----------------

    def enqueue_workflow(self, workflow_name: str, params: dict | None = None) -> int:
        """将工作流任务入队，返回 task_id。

        供 Parser 代码调用::

            self.storage.enqueue_workflow("report", {"city": city, "ref_id": task_id})

        :param workflow_name: workflow 名称（对应文件名，不含 .py）
        :param params: 传递给 execute 的参数 dict
        :return: workflow_queue.id
        """
        if params is not None and not isinstance(params, dict):
            raise TypeError(f"params must be a dict, got {type(params).__name__}")
        params_json = json.dumps(params or {}, ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO workflow_queue (workflow_name, params) VALUES (?, ?)",
                (workflow_name, params_json),
            )
            self._conn.commit()
            task_id = cur.lastrowid
        logger.info(f"工作流入队: {workflow_name} → task_id={task_id}")
        return task_id

    def _init_schema(self) -> None:
        """(Re-)apply system schema (idempotent). Used by tests."""
        self.init_db()

    # ── Cookie 预设 ──

    def upsert_cookie_preset(
        self, name: str, domain: str, cookies_json: str, preset_id: int | None = None
    ) -> int:
        """创建或更新 Cookie 预设。preset_id 为 None 时 INSERT，否则 UPDATE。

        :return: 预设 id
        """
        with self.get_connection() as conn:
            if preset_id is not None:
                conn.execute(
                    "UPDATE cookie_presets SET name=?, domain=?, cookies_json=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (name, domain, cookies_json, preset_id),
                )
                return preset_id
            else:
                cursor = conn.execute(
                    "INSERT INTO cookie_presets (name, domain, cookies_json) VALUES (?, ?, ?)",
                    (name, domain, cookies_json),
                )
                return cursor.lastrowid

    def get_cookie_preset(self, preset_id: int) -> tuple | None:
        """按 id 查询单条预设。"""
        return self.execute(
            "SELECT id, name, domain, cookies_json, enabled, created_at, updated_at "
            "FROM cookie_presets WHERE id=?",
            (preset_id,), fetch="one",
        )

    def list_cookie_presets(self) -> list[tuple]:
        """列出全部预设（含禁用的），按 updated_at 倒序。"""
        return self.execute(
            "SELECT id, name, domain, cookies_json, enabled, created_at, updated_at "
            "FROM cookie_presets ORDER BY updated_at DESC",
            fetch="all",
        )

    def delete_cookie_preset(self, preset_id: int) -> bool:
        """删除预设，返回是否删到了行。"""
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM cookie_presets WHERE id=?", (preset_id,))
            return cur.rowcount > 0

    def match_cookie_preset(self, url: str) -> tuple | None:
        """按 URL 域名匹配启用的 Cookie 预设。

        从 url 提取域名 → 查 cookie_presets WHERE domain=? AND enabled=1。
        返回完整行 tuple(id, name, domain, cookies_json, enabled, created_at, updated_at) 或 None。
        """
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        if not domain:
            return None
        return self.execute(
            "SELECT id, name, domain, cookies_json, enabled, created_at, updated_at "
            "FROM cookie_presets WHERE domain=? AND enabled=1 LIMIT 1",
            (domain,), fetch="one",
        )

    # ---------------- 生命周期 ----------------

    def close(self) -> None:
        """关闭数据库连接。"""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
