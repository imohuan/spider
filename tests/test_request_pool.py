"""Tests for core/request_pool.py — _finish_request empty data handling and raw mode."""

import asyncio
import os
import tempfile
from unittest.mock import MagicMock


class TestFinishRequestEmptyData:
    """parser 返回 [] / None 时 _finish_request 应标记失败。"""

    def _make_pool(self):
        """用 __new__ 获取真实 RequestPool 实例，只 mock 依赖。"""
        from core.request_pool import RequestPool
        pool = RequestPool.__new__(RequestPool)
        pool.storage = MagicMock()
        pool.state_machine = MagicMock()
        pool.keep_browser_open = False
        pool.browser = None
        return pool

    def _call(self, pool, data):
        return asyncio.run(
            pool._finish_request(
                task={"url": "http://test.com"},
                parser=MagicMock(),
                html="<html></html>",
                data=data,
                queue_id=1,
                request_id=100,
                proxy_record=None,
                proxy_url=None,
            )
        )

    def test_empty_list_marks_failed(self):
        """data=[] → 'failed', mark_failed + 不保存数据。"""
        pool = self._make_pool()
        result = self._call(pool, [])
        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()
        args = pool.state_machine.mark_failed.call_args
        assert args[0][1] == "parse"
        assert "解析结果为空" in args[0][2]

        pool.storage.save_business_data.assert_not_called()
        pool.storage.mark_request_failed.assert_called_once()

    def test_none_data_marks_failed(self):
        """data=None → 同样 'failed'。"""
        pool = self._make_pool()
        result = self._call(pool, None)
        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()

    def test_valid_data_marks_done(self):
        """data 非空 → 'success', mark_done + save_business_data。"""
        pool = self._make_pool()
        result = self._call(pool, [{"title": "有效数据"}])
        assert result == "success"
        pool.state_machine.mark_done.assert_called_once()
        pool.storage.save_business_data.assert_called_once()


class TestProcessRaw:
    """Raw 模式：跳过抓取，从文件读取 HTML 直接解析。"""

    def _make_pool(self):
        from core.request_pool import RequestPool
        pool = RequestPool.__new__(RequestPool)
        pool.storage = MagicMock()
        pool.storage.create_request.return_value = 1
        pool.state_machine = MagicMock()
        pool.config = MagicMock()
        pool.config.get.return_value = "browser"
        pool.keep_browser_open = False
        pool.browser = None
        pool.proxy_pool = None
        pool.captcha_handler = None
        pool.image_downloader = None
        return pool

    def _write_html_file(self, html: str) -> str:
        """将 HTML 写入 data/raw_responses/，返回相对路径（如 PROJECT_ROOT）。"""
        import config
        os.makedirs(config.RAW_RESPONSE_DIR, exist_ok=True)
        fd, filepath = tempfile.mkstemp(suffix=".html", dir=config.RAW_RESPONSE_DIR, prefix="raw_test_")
        os.close(fd)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return os.path.relpath(filepath, config.PROJECT_ROOT)

    def _make_task(self, raw_html_path: str, url: str = "https://58.com/test"):
        import json
        return {
            "id": 1,
            "url": url,
            "fetch_mode": "raw",
            "request_config": json.dumps({"raw_html_path": raw_html_path}),
        }

    def _make_parser(self, data: list[dict] | None = None):
        parser = MagicMock()
        parser.parse.return_value = data if data is not None else [{"title": "ok"}]
        parser.table_name = "test_table"
        parser.ensure_table = MagicMock()
        return parser

    def test_raw_parses_and_returns_success(self):
        """正常 HTML → parser.parse 被调用 → 返回 success。"""
        pool = self._make_pool()
        parser = self._make_parser([{"title": "ok"}])
        html_content = "<html><body>hello</body></html>"
        path = self._write_html_file(html_content)
        task = self._make_task(path)

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "success"
        parser.parse.assert_called_once_with(html_content, task["url"])
        pool.storage.save_business_data.assert_called_once()
        pool.state_machine.mark_done.assert_called_once()

    def test_raw_empty_html_file_marks_failed(self):
        """空 HTML 文件 → 直接 mark_failed。"""
        pool = self._make_pool()
        parser = self._make_parser()
        path = self._write_html_file("")
        task = self._make_task(path)

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()
        parser.parse.assert_not_called()

    def test_raw_missing_path_marks_failed(self):
        """raw_html_path 为空 → mark_failed。"""
        pool = self._make_pool()
        parser = self._make_parser()
        task = self._make_task("")

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()

    def test_raw_file_not_found_marks_failed(self):
        """文件不存在 → mark_failed。"""
        pool = self._make_pool()
        parser = self._make_parser()
        task = self._make_task("data/raw_responses/nonexistent.html")

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()

    def test_raw_parse_exception_marks_failed(self):
        """parse 抛异常 → mark_failed。"""
        pool = self._make_pool()
        parser = self._make_parser()
        parser.parse.side_effect = ValueError("解析崩溃")
        path = self._write_html_file("<html><body>bad</body></html>")
        task = self._make_task(path)

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()

    def test_raw_passes_raw_html_path_to_finish(self):
        """_finish_request 收到 raw_html_path 作为 raw_response_path。"""
        pool = self._make_pool()
        parser = self._make_parser([{"title": "ok"}])
        html_content = "<html><head></head><body><div>58同城数据</div></body></html>"
        path = self._write_html_file(html_content)
        task = self._make_task(path)

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "success"
        call_args = pool.storage.mark_request_success.call_args
        raw_path = call_args[1].get("raw_response_path", "")
        assert raw_path == path  # 路径传给 _finish_request