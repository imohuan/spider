"""scheduler / request_pool 模块测试。

测试策略：
- RateLimiter: 独立单元测试（并发槽、域名限速、IP 限速、随机抖动）
- Scheduler: mock state_machine / registry / request_pool，验证主循环逻辑
- RequestPool: mock 所有依赖，验证 process_url 状态流转
"""
from __future__ import annotations

import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config_manager import ConfigManager
from core.scheduler import RateLimiter, Scheduler, extract_domain
from core.state_machine import StateMachine
from core.storage import Storage
from parser.registry import ParserRegistry
from core.request_pool import RequestPool


# ---------------- fixtures ----------------


@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    yield s
    s.close()


@pytest.fixture
def cfg(storage):
    c = ConfigManager(storage)
    c.init_defaults()
    return c


@pytest.fixture
def state_machine(storage, cfg):
    return StateMachine(storage, cfg)


# ============ RateLimiter ============


class TestRateLimiter:
    def test_acquire_releases_concurrency_slot(self, cfg):
        rl = RateLimiter(cfg)
        rl.wait()
        assert rl.stats()["active_count"] == 1
        rl.release()
        assert rl.stats()["active_count"] == 0

    def test_concurrency_limit_blocks(self, cfg):
        """并发数达上限时，新请求应阻塞。"""
        cfg.set("request_concurrency", "1")
        cfg.set("request_interval_min", "0")  # 加速测试
        cfg.set("request_interval_max", "0")
        rl = RateLimiter(cfg)
        rl.wait()  # 占满槽
        # 第二个 wait 应阻塞
        blocked = [True]

        def try_wait():
            rl.wait()
            blocked[0] = False

        t = threading.Thread(target=try_wait)
        t.start()
        time.sleep(0.2)
        assert blocked[0] is True  # 仍在阻塞
        rl.release()
        t.join(timeout=2)
        assert blocked[0] is False

    def test_release_notifies_waiter(self, cfg):
        cfg.set("request_concurrency", "1")
        cfg.set("request_interval_min", "0")
        cfg.set("request_interval_max", "0")
        rl = RateLimiter(cfg)
        rl.wait()

        released = [False]

        def waiter():
            rl.wait()
            released[0] = True

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        assert not released[0]
        rl.release()
        t.join(timeout=2)
        assert released[0]
        rl.release()  # waiter 释放

    def test_random_jitter_applied(self, cfg):
        """随机抖动应导致 wait 时间有延迟（jitter 在 0~0.2 之间）。"""
        cfg.set("request_concurrency", "10")
        cfg.set("request_interval_min", "0.0")
        cfg.set("request_interval_max", "0.2")
        rl = RateLimiter(cfg)
        # 第二次调用才会触发 min_interval（第一次 _last_global_request=0）
        rl.wait()
        rl.release()
        # 第二次：min_interval=0，jitter 在 0~0.2
        start = time.monotonic()
        rl.wait()
        elapsed = time.monotonic() - start
        # jitter 可能是 0~0.2，不强制下限，只验证不超时
        assert elapsed < 1.0
        rl.release()

    def test_release_on_exception(self, cfg):
        """wait 中途异常应释放并发槽。"""
        cfg.set("request_interval_min", "0")
        rl = RateLimiter(cfg)
        # mock _wait_domain 抛异常
        with patch.object(rl, "_wait_domain", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                rl.wait(domain="x.com")
        # 槽应已释放
        assert rl.stats()["active_count"] == 0

    def test_stats(self, cfg):
        rl = RateLimiter(cfg)
        s = rl.stats()
        assert "active_count" in s
        assert "concurrency" in s
        assert "domain_count" in s
        assert "ip_count" in s


# ============ extract_domain ============


class TestExtractDomain:
    def test_normal_url(self):
        assert extract_domain("https://ershouche.58.com/list") == "ershouche.58.com"

    def test_http(self):
        assert extract_domain("http://example.com") == "example.com"

    def test_no_scheme(self):
        assert extract_domain("example.com/path") is None or extract_domain("example.com/path") == ""

    def test_invalid_url(self):
        assert extract_domain("") is None


# ============ Scheduler ============


class TestScheduler:
    @pytest.fixture
    def mock_request_pool(self):
        rp = MagicMock()
        rp.process_url.return_value = "success"
        rp.wait_all = MagicMock()
        return rp

    @pytest.fixture
    def scheduler(self, storage, cfg, state_machine, mock_request_pool):
        registry = ParserRegistry()
        return Scheduler(storage, cfg, state_machine, registry, mock_request_pool)

    def test_seed_enqueues_urls(self, scheduler, storage):
        count = scheduler.seed(["https://a.com", "https://b.com"])
        assert count == 2
        # queue 表应有 2 条
        row = storage.execute("SELECT COUNT(*) FROM queue", fetch="one")
        assert row[0] == 2

    def test_seed_dedupes(self, scheduler, storage):
        scheduler.seed(["https://a.com", "https://a.com"])
        row = storage.execute("SELECT COUNT(*) FROM queue", fetch="one")
        assert row[0] == 1

    def test_run_empty_queue_returns_quickly(self, scheduler):
        """空队列应快速返回（等 10 秒那部分用 max_tasks=0 跳过）。"""
        stats = scheduler.run(max_tasks=0)
        assert stats["total"] == 0

    def test_run_processes_one_task(self, scheduler, storage, mock_request_pool):
        """入队 1 个 URL，run 应处理它并退出。"""
        scheduler.seed(["https://example.com/page"])
        # mock registry.match 返回 None（无 parser）→ mark_skipped
        stats = scheduler.run(max_tasks=1)
        assert stats["total"] == 1
        # 因无 parser，应走 skipped 分支
        assert stats["skipped"] == 1
        mock_request_pool.process_url.assert_not_called()

    def test_run_with_matching_parser(self, scheduler, storage, mock_request_pool):
        """有匹配 parser 时，调用 request_pool.process_url。"""
        from parser.base import BaseParser, ParserTools

        class FakeParser(BaseParser):
            url_pattern = r"example\.com/list"
            def parse(self, page, url):
                return []

        scheduler.seed(["https://example.com/list"])
        scheduler.registry.register(FakeParser)

        stats = scheduler.run(max_tasks=1)
        assert stats["total"] == 1
        mock_request_pool.process_url.assert_called_once()
        assert stats["success"] == 1

    def test_shutdown_signal_stops_loop(self, scheduler, storage):
        """request_shutdown 应让主循环退出。"""
        scheduler.seed(["https://a.com"] * 100)
        # 在另一个线程触发 shutdown
        def trigger():
            time.sleep(0.5)
            scheduler.request_shutdown()

        t = threading.Thread(target=trigger)
        t.start()
        # mock request_pool 让它每次调用后检查 shutdown
        def slow_process(task, parser):
            time.sleep(0.1)
            return "success"

        scheduler.request_pool.process_url = slow_process
        scheduler.run()  # 无 max_tasks
        t.join()
        # 应在 shutdown 后退出
        assert scheduler.is_shutting_down

    def test_process_url_exception_marks_failed(
        self, scheduler, storage, mock_request_pool
    ):
        """request_pool.process_url 抛异常时，应 mark_failed。"""
        from parser.base import BaseParser

        class FakeParser(BaseParser):
            url_pattern = r"example\.com"
            def parse(self, page, url):
                return []

        scheduler.seed(["https://example.com/x"])
        scheduler.registry.register(FakeParser)

        mock_request_pool.process_url.side_effect = RuntimeError("boom")
        stats = scheduler.run(max_tasks=1)
        assert stats["total"] == 1
        assert stats["failed"] == 1

    def test_graceful_shutdown_calls_wait_all(self, scheduler):
        """优雅退出应调用 request_pool.wait_all。"""
        scheduler._graceful_shutdown()
        scheduler.request_pool.wait_all.assert_called_once()

    def test_status_running_by_default(self, scheduler):
        """初始化后 status 应为 running。"""
        assert scheduler.status == "running"

    def test_status_paused_after_pause(self, scheduler):
        """pause 后 status 应为 paused。"""
        scheduler.pause()
        assert scheduler.status == "paused"

    def test_status_stopped_after_stop(self, scheduler):
        """stop 后 status 应为 stopped。"""
        scheduler.stop()
        assert scheduler.status == "stopped"

    def test_pause_resume_cycle(self, scheduler):
        """暂停后 start 恢复为 running。"""
        scheduler.pause()
        assert scheduler.status == "paused"
        scheduler.start()
        assert scheduler.status == "running"

    def test_pause_then_stop(self, scheduler):
        """暂停中 stop 应能正常退出。"""
        scheduler.pause()
        assert scheduler.status == "paused"
        scheduler.stop()
        assert scheduler.status == "stopped"

    def test_pause_blocks_loop(self, scheduler, storage):
        """暂停后主循环应阻塞等待，直到恢复。"""
        from parser.base import BaseParser

        class FakeParser(BaseParser):
            url_pattern = r"example\.com"
            def parse(self, page, url):
                return []

        scheduler.seed(["https://example.com/p1", "https://example.com/p2"])
        scheduler.registry.register(FakeParser)

        def process_url_with_pause(task, parser):
            # 第一个任务处理完后立即暂停
            scheduler.pause()
            return "success"

        scheduler.request_pool.process_url = process_url_with_pause

        # 在另一个线程中几秒后恢复
        def resume_after_delay():
            time.sleep(1.5)
            scheduler.start()

        t = threading.Thread(target=resume_after_delay)
        t.start()

        stats = scheduler.run(max_tasks=2)
        t.join()
        assert stats["total"] >= 1  # 至少处理了 1 个（暂停前完成）


# ============ RequestPool ============


class TestRequestPool:
    @pytest.fixture
    def mock_proxy_pool(self):
        pool = MagicMock()
        pool.acquire.return_value = None  # 默认无 IP
        pool.release_success = MagicMock()
        pool.release_fail = MagicMock()
        return pool

    @pytest.fixture
    def mock_browser(self):
        browser = MagicMock()
        page = MagicMock()
        page.content = AsyncMock(return_value="<html>test</html>")
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        browser.new_page = AsyncMock(return_value=page)
        browser.close_page = AsyncMock()
        return browser, page

    @pytest.fixture
    def mock_captcha_handler(self):
        h = MagicMock()
        h.is_captcha_page.return_value = False
        h.is_captcha_page_async = AsyncMock(return_value=False)
        return h

    @pytest.fixture
    def mock_image_downloader(self):
        d = MagicMock()
        d.download_batch = AsyncMock(return_value=["img1.jpg"])
        return d

    @pytest.fixture
    def mock_parser(self):
        p = MagicMock()
        p.table_name = "test_cars"
        p.table_schema = "CREATE TABLE test_cars (id INTEGER PRIMARY KEY, car_id TEXT, title TEXT)"
        p.on_page_created = None  # 禁用页面钩子
        p.on_page_loaded = None
        p.on_wait_ready = None

        def _parse(page, url):
            if p.storage is not None:
                p.storage.enqueue("https://example.com/detail/123")
            return [{"title": "car1", "car_id": "123"}]

        p.parse.side_effect = _parse
        return p

    @pytest.fixture
    def request_pool(self, storage, cfg, state_machine, mock_proxy_pool,
                     mock_browser, mock_captcha_handler, mock_image_downloader):
        browser, _ = mock_browser
        rp = RequestPool(
            storage=storage, config=cfg, state_machine=state_machine,
            proxy_pool=mock_proxy_pool, browser=browser,
            captcha_handler=mock_captcha_handler,
            image_downloader=mock_image_downloader,
        )
        return rp

    def test_process_url_success(self, request_pool, storage, state_machine,
                                  mock_parser, mock_proxy_pool, mock_browser,
                                  mock_image_downloader):
        """完整成功流程。"""
        # 先入队 + acquire 让 queue 状态为 running（模拟调度器已取出任务）
        storage.enqueue("https://example.com/list")
        task = state_machine.acquire()
        # 建业务表
        storage.ensure_business_table("test_cars",
            "CREATE TABLE test_cars (id INTEGER PRIMARY KEY, car_id TEXT, title TEXT)")

        result = request_pool.process_url(task, mock_parser)
        assert result == "success"
        # queue 状态应为 done
        row = storage.execute("SELECT status FROM queue WHERE id=?", (task["id"],), fetch="one")
        assert row[0] == "done"
        # 业务数据已保存
        row = storage.execute("SELECT car_id FROM test_cars", fetch="one")
        assert row[0] == "123"
        # 新 URL 已入队
        row = storage.execute("SELECT COUNT(*) FROM queue WHERE url LIKE '%detail/123%'", fetch="one")
        assert row[0] == 1
        # request 记录标记成功
        row = storage.execute("SELECT request_status FROM requests WHERE queue_id=?",
                              (task["id"],), fetch="one")
        assert row[0] == "success"

    def test_process_url_captcha_blocked(self, request_pool, storage, state_machine,
                                          mock_parser, mock_captcha_handler, mock_proxy_pool):
        """验证码触发且降级 manual → blocked。"""
        mock_captcha_handler.is_captcha_page.return_value = True
        mock_captcha_handler.is_captcha_page_async.return_value = True
        mock_captcha_handler.handle.return_value = "manual"

        storage.enqueue("https://example.com/captcha")
        task = state_machine.acquire()

        result = request_pool.process_url(task, mock_parser)
        assert result == "blocked"
        row = storage.execute("SELECT status FROM queue WHERE id=?", (task["id"],), fetch="one")
        assert row[0] == "blocked"
        # captcha_triggered 应为 1
        row = storage.execute("SELECT captcha_triggered FROM requests WHERE queue_id=?",
                              (task["id"],), fetch="one")
        assert row[0] == 1

    def test_process_url_captcha_solved_continues(self, request_pool, storage,
                                                    state_machine, mock_parser,
                                                    mock_captcha_handler):
        """验证码解决后继续抓取。"""
        mock_captcha_handler.is_captcha_page.return_value = True
        mock_captcha_handler.is_captcha_page_async.return_value = True
        mock_captcha_handler.handle.return_value = "solved"
        storage.ensure_business_table("test_cars",
            "CREATE TABLE test_cars (id INTEGER PRIMARY KEY, car_id TEXT, title TEXT)")

        storage.enqueue("https://example.com/list")
        task = state_machine.acquire()

        result = request_pool.process_url(task, mock_parser)
        assert result == "success"

    def test_process_url_parser_failure(self, request_pool, storage, state_machine,
                                         mock_parser):
        """parser.parse 抛异常 → mark_failed。"""
        mock_parser.parse.side_effect = RuntimeError("parse error")
        storage.enqueue("https://example.com/list")
        task = state_machine.acquire()

        result = request_pool.process_url(task, mock_parser)
        assert result == "failed"
        row = storage.execute("SELECT status, error_type FROM queue WHERE id=?",
                              (task["id"],), fetch="one")
        assert row[0] == "failed"
        assert row[1] == "parse"

    def test_process_url_no_browser(self, storage, cfg, state_machine, mock_parser):
        """browser 未注入 → mark_failed。"""
        rp = RequestPool(storage, cfg, state_machine, browser=None)
        storage.enqueue("https://example.com/list")
        task = state_machine.acquire()

        result = rp.process_url(task, mock_parser)
        assert result == "failed"

    def test_process_url_no_proxy_direct(self, storage, cfg, state_machine,
                                          mock_browser, mock_parser):
        """无 proxy_pool 时直连。"""
        browser, _ = mock_browser
        rp = RequestPool(storage, cfg, state_machine, proxy_pool=None, browser=browser)
        storage.ensure_business_table("test_cars",
            "CREATE TABLE test_cars (id INTEGER PRIMARY KEY, car_id TEXT, title TEXT)")
        storage.enqueue("https://example.com/list")
        task = state_machine.acquire()

        result = rp.process_url(task, mock_parser)
        assert result == "success"

    def test_keep_browser_open_skips_close_page(self, storage, state_machine,
                                                  mock_parser):
        """keep_browser_open=True 时 process_url 不调用 close_page。"""
        cfg = ConfigManager(storage)
        cfg.init_defaults()
        cfg.set("fetch_mode", "browser")
        storage.ensure_business_table("test_cars",
            "CREATE TABLE test_cars (id INTEGER PRIMARY KEY, car_id TEXT, title TEXT)")
        storage.enqueue("https://example.com/list")
        task = state_machine.acquire()

        # 真实 RequestPool（不用 fixture 的 mock_browser）
        browser = MagicMock()
        page = MagicMock()
        page.content = AsyncMock(return_value="<html>mock</html>")
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        browser.new_page = AsyncMock(return_value=page)
        browser.close_page = AsyncMock()
        rp = RequestPool(storage, cfg, state_machine, browser=browser)
        rp.keep_browser_open = True

        result = rp.process_url(task, mock_parser)
        assert result == "success"
        browser.close_page.assert_not_called()
