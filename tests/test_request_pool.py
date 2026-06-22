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