"""直接通过 request_pool.process_url() 测试 Parser。

绕过调度器主循环，手动组装组件后直接调用 process_url，方便快速迭代 Parser 逻辑。

HTML 输出位置：
    data/raw_responses/{queue_id}_{request_id}_{timestamp}.html

用法::

    python scripts/test_parser_direct.py                      # 用内置 SimpleParser 测试
    python scripts/test_parser_direct.py --url https://xxx    # 自定义 URL
    python scripts/test_parser_direct.py --fetch-mode browser # 浏览器模式
    python scripts/test_parser_direct.py --show-browser       # 浏览器可见 + 页面不关闭 + 进程挂起
    python scripts/test_parser_direct.py --fetch-mode browser # 浏览器模式
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import os
import sys

# 确保项目根在 sys.path 第一位
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from config import ensure_dirs, DATA_DIR, RAW_RESPONSE_DIR
from core.logger import setup_logging, get_logger
from core.storage import Storage
from core.config_manager import ConfigManager
from core.state_machine import StateMachine
from core.request_pool import RequestPool
from core.browser import CrawlerBrowser
from parser.tools.html_parser import HtmlParser
from parser.base import BaseParser, ParserTools
from parser.plugins.shengyizr._base import SimplePageParser
from parser.plugins.shengyizr.list import ShengyiZRListParser


# ── 组件装配 ─────────────────────────────────────────────────────
def build_components(db_path: str):
    logger = get_logger("test")
    logger.info(f"DB: {db_path}")

    storage = Storage(db_path=db_path)
    config_mgr = ConfigManager(storage)
    config_mgr.init_defaults()

    config_mgr.set("fetch_mode", "http")
    config_mgr.set("proxy_enabled", "false")
    config_mgr.set("cache_enabled", "false")

    state_machine = StateMachine(storage, config_mgr)
    tools = ParserTools(html_parser=HtmlParser())

    request_pool = RequestPool(
        storage=storage,
        config=config_mgr,
        state_machine=state_machine,
        proxy_pool=None,
        browser=None,
        captcha_handler=None,
        image_downloader=None,
    )

    return storage, config_mgr, state_machine, request_pool, tools, logger


# ── 主流程 ───────────────────────────────────────────────────────
def main():
    parser_args = _parse_args()

    ensure_dirs()
    setup_logging("DEBUG")

    # 独立 DB，不干扰主爬虫数据库（PID 后缀确保每次运行独立，避免文件锁）
    db_path = os.path.join(DATA_DIR, f"test_parser_{os.getpid()}.db")
    storage, config_mgr, state_machine, request_pool, tools, logger = build_components(db_path)

    if parser_args.fetch_mode:
        config_mgr.set("fetch_mode", parser_args.fetch_mode)
    if parser_args.timeout:
        config_mgr.set("request_timeout", str(parser_args.timeout))

    parser = ShengyiZRListParser(tools)
    parser.ensure_table(storage)

    url = parser_args.url or "https://jianyangshi.58.com/shengyizr/pn2/?gposLastIndex=38&maxInserted=0&skuInserted=0&FGTID=168468672233573454678298957&PGTID=0d306b32-0006-6b82-2830-24ce1a641899&ClickID=44"
    fetch_mode = config_mgr.get("fetch_mode", "browser")
    parser.guard_target_url = url  # 守卫目标：固定为原始种子 URL，不随任务 URL 变化
    parser.guard_max_redirect = 10  # 最大回跳次数，防止无限刷新

    # --- Browser 模式额外初始化 ---
    if fetch_mode == "browser":
        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)
        headless = not parser_args.show_browser
        from core.browser import CrawlerBrowser
        browser = CrawlerBrowser(config_mgr, headless=headless)
        event_loop.run_until_complete(browser.start())
        request_pool.browser = browser
        request_pool._loop = event_loop
        if parser_args.show_browser:
            request_pool.keep_browser_open = True
        logger.info(f"浏览器已启动 (headless={headless}, keep_open={parser_args.show_browser})")
    else:
        event_loop = None
        browser = None

    # 入队 + acquire
    queue_id = storage.enqueue(url, parser_name="ShengyiZRListParser", fetch_mode=fetch_mode)
    logger.info(f"已入队: queue_id={queue_id}")

    task = state_machine.acquire()
    if task is None:
        logger.error("无法获取任务（可能状态异常）")
        return 1

    logger.info(f"开始测试: fetch_mode={fetch_mode} url={url}")
    logger.info("-" * 60)

    try:
        result = request_pool.process_url(task, parser)

        logger.info("-" * 60)
        logger.info(f"处理结果: {result}")

        # 展示结果
        _print_results(storage, url, logger, parser.table_name)

        # ---- 浏览器保持打开 ----
        if parser_args.show_browser:
            logger.info("浏览器保持打开 (--show-browser)，按 Ctrl+C 退出")
            print("\n浏览器窗口保持打开，按 Ctrl+C 退出...")
            try:
                while True:
                    import time
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("收到退出信号")
    finally:
        if browser is not None and event_loop is not None:
            try:
                event_loop.run_until_complete(browser.close())
            except Exception:
                pass
        storage.close()

        if not parser_args.keep_db:
            _cleanup_temp_db(db_path)

    return 0


def _print_results(storage: Storage, url: str, logger, table_name: str = "test_pages"):
    """打印测试结果。"""
    rows = storage.execute(f"SELECT * FROM {table_name} ORDER BY id DESC", fetch="all")
    print(f"\n=== Parser 输出 ({table_name} 表) ===")
    if not rows:
        print("  (无数据)")
        return

    if table_name == "shengyizr_list":
        for r in rows[:5]:  # 只打印前5条摘要
            print(f"  [{r['title'][:30]}] {r['price_num']}{r['price_unit']} | {r['area']}m2 | {r['location']} | {r['detail_url'][:50]}")
        print(f"  ... 共 {len(rows)} 条")
    else:
        for r in rows:
            print(f"  url:       {r['url']}")
            print(f"  html_len:  {r['html_len']}")
            print(f"  title:     {r['title']}")
            print(f"  status:    {r['status']}")

    reqs = storage.execute(
        "SELECT id, status_code, duration_ms, response_size, request_status, error_msg "
        "FROM requests ORDER BY id DESC LIMIT 3",
        fetch="all",
    )
    print("\n=== 请求记录 (requests 表) ===")
    if not reqs:
        print("  (无数据)")
    for r in reqs:
        print(f"  id={r['id']} status={r['status_code']} {r['duration_ms']}ms "
              f"size={r['response_size']} {r['request_status']} err={r['error_msg']}")

    q = storage.execute("SELECT id, url, status, retry_count, error_msg FROM queue", fetch="all")
    print("\n=== 队列状态 (queue 表) ===")
    if not q:
        print("  (无数据)")
    for t in q:
        print(f"  id={t['id']} {t['status']} retry={t['retry_count']} {t['url']}")

    # HTML 输出位置
    print("\n=== 文件输出 ===")
    print(f"  目录:  {RAW_RESPONSE_DIR}/")
    if os.path.isdir(RAW_RESPONSE_DIR):
        files = sorted(glob.glob(os.path.join(RAW_RESPONSE_DIR, "*.html")), key=os.path.getmtime, reverse=True)
        for f in files[:5]:
            size = os.path.getsize(f)
            print(f"    {os.path.basename(f)}  ({size:,} bytes)")


def _cleanup_temp_db(db_path: str):
    for p in [db_path] + [db_path + s for s in ("-wal", "-shm")]:
        try:
            os.remove(p)
        except OSError:
            pass


def _parse_args():
    ap = argparse.ArgumentParser(description="直接测试 request_pool.process_url()")
    ap.add_argument("--url", help="目标 URL，默认 https://jianyangshi.58.com/")
    ap.add_argument("--fetch-mode", choices=["browser", "http"], default="http",
                    help="抓取模式，默认 http（无需浏览器）")
    ap.add_argument("--timeout", type=int, default=30, help="请求超时秒，默认 30")
    ap.add_argument("--keep-db", action="store_true", help="保留临时数据库文件不删除")
    ap.add_argument("--show-browser", action="store_true",
                    help="浏览器可见模式 + 页面保持打开不关闭（调试用）")
    return ap.parse_args()


if __name__ == "__main__":
    sys.exit(main())
