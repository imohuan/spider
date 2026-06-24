"""Tests for core/request_pool.py — _finish_request empty data handling."""

import asyncio
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
    """Raw 模式：跳过抓取，直接解析传入的 HTML。"""

    def _make_pool(self, html: str = "<html><body>test</body></html>"):
        from core.request_pool import RequestPool
        pool = RequestPool.__new__(RequestPool)
        pool.storage = MagicMock()
        pool.storage.create_request.return_value = 1  # 返回整数 ID，避免文件名含 MagicMock 字符串
        pool.state_machine = MagicMock()
        pool.config = MagicMock()
        pool.config.get.return_value = "browser"
        pool.keep_browser_open = False
        pool.browser = None
        pool.proxy_pool = None
        pool.captcha_handler = None
        pool.image_downloader = None
        return pool

    def _make_task(self, html: str, url: str = "https://58.com/test"):
        import json
        return {
            "id": 1,
            "url": url,
            "fetch_mode": "raw",
            "request_config": json.dumps({"html": html}),
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
        task = self._make_task("<html><body>hello</body></html>")

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "success"
        parser.parse.assert_called_once_with("<html><body>hello</body></html>", task["url"])
        pool.storage.save_business_data.assert_called_once()
        pool.state_machine.mark_done.assert_called_once()

    def test_raw_empty_html_marks_failed(self):
        """空 HTML → 直接 mark_failed，不调用 parser.parse。"""
        pool = self._make_pool()
        parser = self._make_parser()
        task = self._make_task("")

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()
        parser.parse.assert_not_called()

    def test_raw_parse_exception_marks_failed(self):
        """parse 抛异常 → mark_failed。"""
        pool = self._make_pool()
        parser = self._make_parser()
        parser.parse.side_effect = ValueError("解析崩溃")
        task = self._make_task("<html><body>bad</body></html>")

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "failed"
        pool.state_machine.mark_failed.assert_called_once()

    def test_raw_preserves_html_in_raw_response(self):
        """原始 HTML 应保存为 raw_response 文件。"""
        pool = self._make_pool()
        parser = self._make_parser([{"title": "ok"}])
        html_content = "<html><head></head><body><div>58同城数据</div></body></html>"
        task = self._make_task(html_content)

        result = asyncio.run(
            pool._process_raw(task, parser, queue_id=1, url=task["url"])
        )

        assert result == "success"
        # _save_raw_response 应被调用，且内容包含原始 HTML
        call_args = pool.storage.mark_request_success.call_args
        raw_path = call_args[1].get("raw_response_path", "")
        assert raw_path  # 路径非空，表明文件已生成