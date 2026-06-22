"""测试用伪存储 - 包装真实 Storage，让写入方法为空操作。

用于 test-url 等调试端点：Parser 内部调用 storage.enqueue() 等写入方法时
不做实际操作，但 execute() / ensure_business_table() 等读方法正常委托。
"""
from core.storage import Storage


class FakeStorage:
    """包装真实 Storage 对象的代理类。

    - 写入方法（enqueue / save_business_data / create_request 等）均为空操作
    - 读方法（execute / ensure_business_table / get_connection 等）委托给真实 Storage
    - 上下文管理器兼容（__exit__ 不关闭底层连接）
    """

    def __init__(self, real_storage: Storage) -> None:
        self._real = real_storage

    # --------------- no-op 写入方法 ---------------

    def enqueue(
        self,
        url: str,
        parser_name: str | None = None,
        priority: int = 0,
        parent_id: int | None = None,
        fetch_mode: str | None = None,
        request_config: str | dict | None = None,
    ) -> int:
        return -1

    def enqueue_image(
        self, url: str, request_id: int | None = None,
        queue_id: int | None = None, max_retry: int = 3,
    ) -> int | None:
        return None

    def save_business_data(self, table_name: str, rows: list[dict]) -> None:
        return None

    def create_request(
        self,
        queue_id: int,
        url: str,
        proxy_ip: str | None,
        method: str = "GET",
    ) -> int:
        return -1

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
        pass

    def mark_request_failed(
        self,
        request_id: int,
        error_msg: str,
        status_code: int | None = None,
        duration_ms: int | None = None,
        raw_response_path: str | None = None,
        response_headers: dict | None = None,
    ) -> None:
        pass

    def add_seen_url(self, url: str) -> str:
        return ""

    def is_url_seen(self, url: str) -> bool:
        return False

    # --------------- 委托方法 ---------------

    def execute(self, sql: str, params=(), fetch: str = "none"):
        return self._real.execute(sql, params, fetch=fetch)

    def ensure_business_table(self, table_name: str, table_schema: str) -> None:
        return self._real.ensure_business_table(table_name, table_schema)

    def get_connection(self):
        return self._real.get_connection()

    def close(self) -> None:
        pass  # 不关闭底层连接

    def init_db(self) -> None:
        pass  # no-op

    # --------------- 上下文管理器 ---------------

    def __enter__(self) -> "FakeStorage":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass  # 不关闭底层连接
