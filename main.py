"""58同城爬虫框架入口。

启动流程：
1. 初始化目录 / 日志 / DB / 配置
2. 装配所有组件（storage → config → state_machine → proxy_pool → browser →
   captcha_handler → image_downloader → parser_registry → request_pool → scheduler）
3. 注册 Parser 插件 + 建业务表
4. 种子 URL 入队（--seed 参数或从已有 queue 继续）
5. 启动调度器主循环
6. 可选：--serve 启动 Web 管理后台（Flask + SocketIO）

用法::

    python main.py                          # 从已有 queue 继续抓取
    python main.py --seed https://ershouche.58.com/
    python main.py --seed-url https://ershouche.58.com/ --max-tasks 100
    python main.py --no-proxy               # 禁用代理直连
    python main.py --log-level DEBUG        # 调试模式
    python main.py --serve                  # 启动 Web 管理后台
    python main.py --serve --fetch-mode http --seed https://cd.58.com/ershouche/  # HTTP 模式 + Web UI
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from core.storage import Storage
from core.config_manager import ConfigManager
from core.state_machine import StateMachine
from core.scheduler import Scheduler
from core.request_pool import RequestPool
from core.bootstrap import (
    init_environment,
    create_event_loop,
    cancel_all_tasks,
    start_web_server_in_thread,
    open_service_ui,
    start_image_worker,
    stop_image_worker,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="58同城爬虫框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--seed", "--seed-url", dest="seed_urls", nargs="*", default=[],
        help="种子 URL 列表（可多个），不传则从已有 queue 继续",
    )
    parser.add_argument(
        "--max-tasks", type=int, default=None,
        help="最多处理多少个任务后退出（默认一直跑到队列空）",
    )
    parser.add_argument(
        "--no-proxy", action="store_true",
        help="禁用代理，直连抓取（覆盖 config.proxy_enabled）",
    )
    parser.add_argument(
        "--log-level", choices=["INFO", "DEBUG", "WARNING", "ERROR"],
        default=None, help="日志级别（覆盖 config.log_level）",
    )
    parser.add_argument(
        "--headless", action="store_true", default=True,
        help="浏览器无头模式（默认开启）",
    )
    parser.add_argument(
        "--show-browser", action="store_true",
        help="显示浏览器窗口（调试用，覆盖 --headless）",
    )
    parser.add_argument(
        "--fetch-mode", choices=["browser", "http", "cdp"],
        default=None, help="抓取模式：browser（浏览器）/ http（直连），默认读取 config",
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="启动 Web 管理后台（Flask + SocketIO，默认 127.0.0.1:5000）",
    )
    parser.add_argument(
        "--web-host", default="127.0.0.1", help="Web 后台绑定地址（默认 127.0.0.1）",
    )
    parser.add_argument(
        "--web-port", type=int, default=5000, help="Web 后台端口（默认 5000）",
    )
    return parser.parse_args(argv)



def build_components(args: argparse.Namespace, event_loop=None) -> dict[str, Any]:
    """装配所有组件，返回组件字典。

    按依赖顺序初始化：storage → config → state_machine → tools →
    proxy_pool → browser → captcha → image_downloader → registry →
    request_pool → scheduler。
    """
    storage = Storage()
    config_mgr = ConfigManager(storage)
    config_mgr.init_defaults()

    # 命令行覆盖配置
    if args.no_proxy:
        config_mgr.set("proxy_enabled", "false")
    if args.log_level:
        config_mgr.set("log_level", args.log_level)
    if args.fetch_mode:
        config_mgr.set("fetch_mode", args.fetch_mode)

    state_machine = StateMachine(storage, config_mgr)

    # Parser 工具链
    from parser.base import ParserTools
    from parser.tools.html_parser import HtmlParser
    from parser.tools.font_decoder import FontDecoder
    from parser.tools.image_downloader import ImageDownloader
    from parser.tools.captcha_handler import CaptchaHandler

    tools = ParserTools(
        html_parser=HtmlParser(),
        font_decoder=FontDecoder(),
        image_downloader=ImageDownloader(),
        captcha_handler=None,  # 下面单独建
    )

    # 代理池
    from proxy.pool import ProxyPool
    from proxy.provider import make_provider

    provider = make_provider(
        config_api_url=config_mgr.get("proxy_api_url", default=""),
        provider_name=config_mgr.get("proxy_provider", default="juliang"),
    )
    proxy_pool = ProxyPool(storage, config_mgr, provider)

    # 浏览器
    from core.browser import CrawlerBrowser
    browser = CrawlerBrowser(config_mgr, headless=not args.show_browser)

    # CDP 浏览器（仅在 fetch_mode=cdp 或 cdp_enabled=true 时初始化）
    cdp_browser = None
    if args.fetch_mode == "cdp" or config_mgr.get_bool("cdp_enabled", False):
        from core.browser_cdp import CrawlerBrowserCDP
        cdp_browser = CrawlerBrowserCDP(config_mgr)

    # 验证码处理器
    captcha_handler = CaptchaHandler(config_mgr, storage)
    tools.captcha_handler = captcha_handler

    # Parser 注册表
    from parser.registry import ParserRegistry
    registry = ParserRegistry(storage=storage, tools=tools)
    registry.discover()
    registry.ensure_all_tables()

    # ── 工作流系统 ──
    from core.workflow_registry import WorkflowRegistry
    from core.workflow_scheduler import WorkflowScheduler

    workflow_registry = WorkflowRegistry()
    workflow_registry.discover()

    workflow_scheduler = WorkflowScheduler(
        storage=storage,
        registry=workflow_registry,
    )

    # 请求池
    request_pool = RequestPool(
        storage=storage,
        config=config_mgr,
        state_machine=state_machine,
        proxy_pool=proxy_pool,
        browser=browser,
        cdp_browser=cdp_browser,
        captcha_handler=captcha_handler,
        image_downloader=tools.image_downloader,
        loop=event_loop,
    )

    # 调度器
    scheduler = Scheduler(
        storage=storage,
        config=config_mgr,
        state_machine=state_machine,
        registry=registry,
        request_pool=request_pool,
    )

    return {
        "storage": storage,
        "config": config_mgr,
        "state_machine": state_machine,
        "proxy_pool": proxy_pool,
        "browser": browser,
        "cdp_browser": cdp_browser,
        "captcha_handler": captcha_handler,
        "image_downloader": tools.image_downloader,
        "registry": registry,
        "request_pool": request_pool,
        "scheduler": scheduler,
        "workflow_registry": workflow_registry,
        "workflow_scheduler": workflow_scheduler,
    }


def main(argv: list[str] | None = None) -> int:
    """主入口。"""
    args = parse_args(argv)

    # 初始化目录 + 日志
    log_level = args.log_level or "INFO"
    logger = init_environment(log_level)
    logger.info("=" * 60)
    logger.info("58同城爬虫框架启动")
    logger.info("=" * 60)

    # 创建持久事件循环（Playwright 对象绑循环，必须全程同一循环）
    event_loop = create_event_loop()

    # 装配组件（传入 event_loop 给 RequestPool）
    components = build_components(args, event_loop=event_loop)
    scheduler = components["scheduler"]
    proxy_pool = components["proxy_pool"]
    browser = components["browser"]
    registry = components["registry"]
    config_mgr = components["config"]

    logger.info(f"已注册 Parser: {len(registry)} 个")
    for cls in registry.classes:
        logger.info(f"  - {cls.__name__} (pattern={cls.url_pattern!r})")

    # 种子入队
    if args.seed_urls:
        count = scheduler.seed(args.seed_urls, fetch_mode=args.fetch_mode)
        logger.info(f"种子入队: {count}/{len(args.seed_urls)}")

    # Web 管理后台（后台线程启动，不阻塞爬虫主循环）
    if args.serve:
        from web.app import create_app

        web_app = create_app(static_folder='web/static')
        web_app.config['CRAWLER_COMPONENTS'] = components
        from web.api.crawler_control import init_scheduler
        init_scheduler(scheduler)

        # 启动工作流调度器并挂 WebSocket 推送
        from web.socketio_handlers import push_workflow_task_update
        from web.app import socketio as ws_socketio

        workflow_scheduler.set_on_update(
            lambda tid, name, status, result, error: push_workflow_task_update(
                ws_socketio, tid, name, status, result, error
            )
        )
        workflow_scheduler.start()

        server_thread = start_web_server_in_thread(
            web_app, host=args.web_host, port=args.web_port, logger=logger,
        )
        open_service_ui(host=args.web_host, port=args.web_port, logger=logger)
    else:
        server_thread = None

    # 启动健康检查线程（代理启用时）
    if config_mgr.get_bool("proxy_enabled", default=False):
        proxy_pool.start_health_check_loop()

    # 启动浏览器（用持久化事件循环，避免 asyncio.run 创建新循环导致 Playwright 对象失效）
    try:
        event_loop.run_until_complete(browser.start())

        # CDP 模式下连接本地 Chrome
        cdp_browser = components.get("cdp_browser")
        if cdp_browser is not None:
            try:
                event_loop.run_until_complete(cdp_browser.connect())
                logger.info(f"CDP 已连接本地 Chrome: {cdp_browser.endpoint}")
            except Exception as e:
                logger.error(f"CDP 连接失败: {e}")
                cdp_browser = None

        # 图片下载队列 Worker（独立线程 + 专用事件循环，http/browser 模式都能消费）
        img_downloader = components["image_downloader"]
        img_storage = components["storage"]
        img_worker, img_loop, img_thread = start_image_worker(
            storage=img_storage, downloader=img_downloader, config=config_mgr, logger=logger,
        )

        try:
            # 主循环
            stats = scheduler.run(max_tasks=args.max_tasks)
            logger.info(f"抓取完成，统计: {stats}")
            return 0
        except KeyboardInterrupt:
            logger.info("收到 Ctrl+C，触发优雅退出")
            scheduler.request_shutdown()
            return 0
        finally:
            # 停止图片 Worker
            stop_image_worker(img_worker, img_loop, img_thread, logger)
            proxy_pool.stop_health_check_loop()
            # 关闭浏览器 — 连接可能已断开（Ctrl+C 时常见），吞掉错误不炸
            try:
                event_loop.run_until_complete(browser.close())
            except Exception as e:
                logger.warning(f"浏览器关闭异常（可忽略）: {e}")
            # CDP 断开
            cdp_browser = components.get("cdp_browser")
            if cdp_browser is not None:
                try:
                    event_loop.run_until_complete(cdp_browser.disconnect())
                except Exception as e:
                    logger.warning(f"CDP 断开异常: {e}")
            # 取消所有待处理异步任务，避免 "Task was destroyed but it is pending!"
            cancel_all_tasks(event_loop, logger)
    finally:
        event_loop.close()
        logger.info("爬虫已退出")


if __name__ == "__main__":
    sys.exit(main())
