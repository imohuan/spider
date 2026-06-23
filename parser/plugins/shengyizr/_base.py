"""58 同城基础 Parser —— 提供跳转守卫 + 公共钩子，不直接注册到调度器。

模块名以 ``_`` 开头，``ParserRegistry.discover()`` 自动跳过。
所有需要浏览器反跳转的 58 Parser 应继承本类的 ``SimplePageParser``。

用法::

    from parser.plugins._base import SimplePageParser

    class MyParser(SimplePageParser):
        url_pattern = r"58.com/mypage"
        table_name = "my_table"
        ...
"""
from __future__ import annotations
import asyncio as _asyncio
from parser.base import BaseParser

# ── 反跳转 JS（轮询 + 跨域 window.name 持久计数器 + 验证码自动点击）─
# __TARGET_URL__ / __MAX_REDIRECT__ 由 on_page_created() 注入时替换
_REDIRECT_GUARD_SCRIPT = """(() => {
    var TARGET = '__TARGET_URL__';
    var MAX = __MAX_REDIRECT__;
    var state = {};
    try { state = JSON.parse(window.name || '{}'); } catch(e) {}
    if (!state.remaining || state.remaining > MAX) {
        state.remaining = MAX;
        window.name = JSON.stringify(state);
    }

    window.__RG = { target: TARGET, remaining: state.remaining };
    if (state.remaining <= 0) return;

    var CAPTCHA = 'callback.58.com/antibot/verifycode';
    var captchaRetry = 0;

    function loop() {
        var current = window.location.href;
        var targetBase = TARGET.split('?')[0];
        var currentBase = current.split('?')[0];

        if (currentBase === targetBase) { setTimeout(loop, 300); return; }

        if (current.indexOf(CAPTCHA) !== -1) {
            var btn = document.getElementById('btnSubmit');
            if (btn) { captchaRetry = 0; btn.click(); }
            else if (captchaRetry++ < 20) { setTimeout(loop, 500); }
            setTimeout(loop, 1000);
            return;
        }

        try { state = JSON.parse(window.name || '{}'); } catch(e) {}
        if (state.remaining <= 0) return;
        state.remaining--;
        window.name = JSON.stringify(state);
        window.__RG.remaining = state.remaining;
        window.location.replace(TARGET);
    }

    setTimeout(loop, 3000);
})();"""


class SimplePageParser(BaseParser):
    """58 同城基础 Parser —— 跳转守卫 + 公共钩子。

    子类继承后自动获得：浏览器跳转拦截、验证码自动点击、页面滚动懒加载。
    覆盖 ``parse()`` / ``extract_urls()`` 实现具体业务逻辑。
    """

    url_pattern = r"\.58\.com"
    requires_browser = True
    table_name = "test_pages"
    table_schema = """
        CREATE TABLE test_pages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT,
            html_len    INTEGER,
            title       TEXT,
            status      TEXT,
            crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    # ---- 页面生命周期钩子 ----

    async def on_page_created(self, page, url: str) -> None:
        """goto 前注入轮询守卫。"""
        target = getattr(self, "guard_target_url", url)
        max_retry = getattr(self, "guard_max_redirect", 10)
        if max_retry <= 0:
            return
        if target and "58.com" in target:
            script = _REDIRECT_GUARD_SCRIPT.replace("__TARGET_URL__", target)
            script = script.replace("__MAX_REDIRECT__", str(max_retry))
            await page.add_init_script(script)

    async def on_page_loaded(self, page, url: str) -> None:
        """goto 后滚动加载懒渲染内容。"""
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await _asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, 0)")
            await _asyncio.sleep(0.5)
        except Exception:
            pass

    # ---- 核心解析方法 ----

    def parse(self, page, url: str) -> list[dict]:
        html = self._get_html(page)
        if not html:
            return [{"url": url, "html_len": 0, "title": "(empty HTML)", "status": "empty"}]

        hp = self.html_parser
        if hp is None:
            return [{"url": url, "html_len": len(html), "title": "(no parser)", "status": "no_tools"}]

        tree = hp.parse(html, base_url=url)
        title_nodes = hp.xpath(tree, "//title")
        if not title_nodes and hasattr(tree, "cssselect"):
            title_nodes = hp.cssselect(tree, "title")
        title = hp.text(title_nodes[0]) if title_nodes else "(no title)"

        return [{"url": url, "html_len": len(html), "title": title, "status": "ok"}]

    def _get_html(self, page) -> str:
        if isinstance(page, str):
            return page
        try:
            c = page.content()
            return c if isinstance(c, str) else ""
        except Exception:
            return ""
