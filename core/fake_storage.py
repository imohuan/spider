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

    def enqueue(self, url, parser_name=None, priority=0, parent_id=None,
                fetch_mode=None, request_config=None):
        return None

    def enqueue_image(self, url, request_id=None, queue_id=None, max_retry=3):
        return None

    def save_business_data(self, table_name, rows):
        return None

    def create_request(self, queue_id, url, proxy_ip, method="GET"):
        return -1

    def mark_request_success(self, request_id, extracted_data=None,
                             image_paths=None, duration_ms=None,
                             response_size=None, status_code=200,
                             raw_response_path=None, response_headers=None,
                             request_headers=None):
        pass

    def mark_request_failed(self, request_id, error_msg, status_code=None,
                            duration_ms=None, raw_response_path=None,
                            response_headers=None):
        pass

    def add_seen_url(self, url):
        return ""

    def is_url_seen(self, url):
        return False

    # --------------- 委托方法 ---------------

    def execute(self, sql, params=(), fetch="none"):
        return self._real.execute(sql, params, fetch=fetch)

    def ensure_business_table(self, table_name, table_schema):
        return self._real.ensure_business_table(table_name, table_schema)

    def get_connection(self):
        return self._real.get_connection()

    def close(self):
        pass  # 不关闭底层连接

    def init_db(self):
        pass  # no-op

    # --------------- 上下文管理器 ---------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass  # 不关闭底层连接
