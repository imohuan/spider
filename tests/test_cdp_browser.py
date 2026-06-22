"""测试 CDP 浏览器"""
import pytest


class TestCrawlerBrowserCDPInit:
    """CrawlerBrowserCDP 初始化测试（不需要实际 Chrome 运行）"""

    def test_init_with_config(self):
        from core.browser_cdp import CrawlerBrowserCDP
        from core.config_manager import ConfigManager
        from core.storage import Storage

        s = Storage(":memory:")
        cfg = ConfigManager(s)
        cfg.init_defaults()

        browser = CrawlerBrowserCDP(cfg)
        assert browser.endpoint == "http://localhost:9222"
        assert browser.is_connected is False
        assert browser.request_count == 0
        assert browser.existing_pages == 0

    def test_init_with_custom_endpoint(self):
        from unittest.mock import MagicMock
        from core.browser_cdp import CrawlerBrowserCDP

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: d

        browser = CrawlerBrowserCDP(cfg, endpoint="http://localhost:9233")
        assert browser.endpoint == "http://localhost:9233"

    def test_random_delay_config(self):
        """验证 random_delay 使用配置范围"""
        from unittest.mock import MagicMock
        from core.browser_cdp import CrawlerBrowserCDP

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: 0.5 if "min" in k else 1.0
        browser = CrawlerBrowserCDP(cfg)
        assert 0.5 <= browser._delay_min <= 1.0

    def test_properties_default(self):
        from unittest.mock import MagicMock
        from core.browser_cdp import CrawlerBrowserCDP

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: d
        browser = CrawlerBrowserCDP(cfg)
        assert browser.existing_pages == 0
        assert browser.request_count == 0


class TestCrawlerBrowserCDPDisconnected:
    """未连接时的行为"""

    def test_new_page_without_connect_raises(self):
        from unittest.mock import MagicMock
        from core.browser_cdp import CrawlerBrowserCDP
        import pytest

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: d
        browser = CrawlerBrowserCDP(cfg)

        import asyncio
        with pytest.raises(RuntimeError, match="CDP 未连接"):
            asyncio.run(browser.new_page())

    def test_close_page_none_safe(self):
        from unittest.mock import MagicMock
        from core.browser_cdp import CrawlerBrowserCDP
        import asyncio

        cfg = MagicMock()
        cfg.get.return_value = "http://localhost:9222"
        cfg.get_bool.return_value = False
        cfg.get_float.side_effect = lambda k, d: d
        browser = CrawlerBrowserCDP(cfg)
        # close_page(None) 应该安全返回不抛异常
        asyncio.run(browser.close_page(None))
