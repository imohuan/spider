"""测试反检测功能：fake-useragent / random UA / stealth 配置"""
import pytest
from core.config_manager import ConfigManager
from core.storage import Storage


class TestRandomUA:
    """fake-useragent 与 UA 降级测试"""

    def test_get_random_ua_static_fallback(self):
        """无 fake-useragent 时降级到静态 UA 池"""
        from unittest.mock import MagicMock
        from core.request_pool import RequestPool

        pool = RequestPool(
            storage=MagicMock(), config=MagicMock(), state_machine=MagicMock(),
            proxy_pool=None, browser=None, captcha_handler=None, image_downloader=None,
        )
        pool.config.get_bool.return_value = True
        pool.config.get.return_value = "windows,macos"

        ua = pool._get_random_ua()
        assert ua and len(ua) > 30, f"UA 太短: {ua!r}"
        assert "Mozilla" in ua

    def test_get_random_ua_with_fake_useragent(self):
        """fake-useragent 可用时返回真实 Chrome UA"""
        try:
            from fake_useragent import UserAgent
            _ua = UserAgent(os=["windows", "macos"], browsers=["chrome"])
            result = _ua.random
            assert result and "Chrome" in result, f"UA 不含 Chrome: {result!r}"
        except ImportError:
            pytest.skip("fake-useragent 未安装")

    def test_get_random_ua_unique(self):
        """连续多次调用返回不同 UA（大概率不同）"""
        from unittest.mock import MagicMock
        from core.request_pool import RequestPool

        pool = RequestPool(
            storage=MagicMock(), config=MagicMock(), state_machine=MagicMock(),
            proxy_pool=None, browser=None, captcha_handler=None, image_downloader=None,
        )
        pool.config.get_bool.return_value = True
        pool.config.get.return_value = "windows,macos"

        uas = {pool._get_random_ua() for _ in range(10)}
        # 静态池 3 个，至少能出 1 种以上
        assert len(uas) >= 1


class TestAntiBotConfig:
    """反检测配置默认值与读写"""

    def test_defaults(self):
        s = Storage(":memory:")
        cfg = ConfigManager(s)
        cfg.init_defaults()
        assert cfg.get_bool("anti_bot_random_ua") is True
        assert cfg.get_bool("anti_bot_stealth") is True
        assert cfg.get_float("anti_bot_delay_page_min") == 1.0
        assert cfg.get_float("anti_bot_delay_page_max") == 3.0
        assert cfg.get("cdp_endpoint") == "http://localhost:9222"
        assert cfg.get_bool("cdp_enabled") is False
        assert cfg.get("anti_bot_ua_platforms") == "windows,macos"
        assert cfg.get("anti_bot_ua_browsers") == "chrome,edge"

    def test_set_and_read(self):
        s = Storage(":memory:")
        cfg = ConfigManager(s)
        cfg.init_defaults()
        cfg.set("anti_bot_random_ua", "true")
        assert cfg.get_bool("anti_bot_random_ua") is True

        cfg.set("anti_bot_delay_page_min", 2.5)
        assert cfg.get_float("anti_bot_delay_page_min") == 2.5

    def test_cdp_config_toggle(self):
        s = Storage(":memory:")
        cfg = ConfigManager(s)
        cfg.init_defaults()
        cfg.set("cdp_enabled", "true")
        assert cfg.get_bool("cdp_enabled") is True
        cfg.set("cdp_endpoint", "http://localhost:9233")
        assert cfg.get("cdp_endpoint") == "http://localhost:9233"


class TestBaseParserPreferredMode:
    """BaseParser.preferred_fetch_mode"""

    def test_default_preferred_mode(self):
        from parser.base import BaseParser
        assert BaseParser.preferred_fetch_mode is None

    def test_subclass_override(self):
        from parser.base import BaseParser

        class MyParser(BaseParser):
            url_pattern = r"test"
            table_name = "test"
            table_schema = "CREATE TABLE test (id INTEGER)"
            preferred_fetch_mode = "cdp"

        assert MyParser.preferred_fetch_mode == "cdp"

    def test_subclass_default_none(self):
        from parser.base import BaseParser

        class MyParser(BaseParser):
            url_pattern = r"test2"
            table_name = "test2"
            table_schema = "CREATE TABLE test2 (id INTEGER)"

        assert MyParser.preferred_fetch_mode is None
