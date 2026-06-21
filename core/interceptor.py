"""拦截器模块 - ``route()`` 拦截 JS/CSS/静态字体并缓存到本地。

按设计文档 4.4 资源拦截策略：

| 资源类型       | 来源       | 处理                            | 缓存          |
|---------------|-----------|---------------------------------|--------------|
| JS            | 外部 URL  | 拦截→查缓存→命中用本地/未命中下载+缓存 | cache/js/    |
| CSS           | 外部 URL  | 同上                            | cache/css/   |
| font(静态)    | 外部 URL  | 同上                            | cache/font/  |
| font(动态加密) | 内嵌 Base64 | **不拦截，放行**              | 不缓存       |
| 图片(页面内)  | 外部 URL  | 放行（由 Parser 决定哪些下载）   | 不缓存       |
| XHR/Fetch     | -         | 放行（可能含数据）              | 不缓存       |

缓存文件命名用 URL 的 MD5 哈希，避免特殊字符::

    cache/js/a1b2c3d4e5f6.js
    cache/css/f7e8d9c0b1a2.css
    cache/font/1a2b3c4d5e6f.woff
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.config_manager import ConfigManager
from core.logger import get_logger
from config import CACHE_JS_DIR, CACHE_CSS_DIR, CACHE_FONT_DIR

logger = get_logger("interceptor")

# resource_type → 缓存目录映射
_RESOURCE_CACHE_MAP: dict[str, Path] = {
    "script": Path(CACHE_JS_DIR),
    "stylesheet": Path(CACHE_CSS_DIR),
    "font": Path(CACHE_FONT_DIR),
}

# 资源类型 → 文件扩展名（缓存文件命名用）
_RESOURCE_EXT: dict[str, str] = {
    "script": "js",
    "stylesheet": "css",
    "font": "woff",
}


class Interceptor:
    """Playwright 资源拦截器，按 resource_type 缓存静态资源。

    用法（由 ``CrawlerBrowser`` 自动注入到每个 Page）::

        interceptor = Interceptor(config)
        await interceptor.attach(page)
    """

    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        # 确保缓存目录存在
        for d in _RESOURCE_CACHE_MAP.values():
            d.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.config.get_bool("cache_enabled", default=True)

    async def attach(self, page: Any) -> None:
        """将拦截 handler 绑定到 page 的所有路由。"""
        if not self.enabled:
            logger.debug("cache_enabled=false，跳过资源拦截")
            return
        await page.route("**/*", self._handle_route)

    async def detach(self, page: Any) -> None:
        """解除 page 上的路由绑定。"""
        try:
            await page.unroute("**/*", self._handle_route)
        except Exception:
            pass

    async def _handle_route(self, route: Any, request: Any) -> None:
        """路由处理主逻辑。"""
        url = request.url
        resource_type = request.resource_type

        # 1. 动态加密字体（data: URI）放行，不缓存
        if url.startswith("data:"):
            logger.debug(f"[Interceptor] 放行 data: URI")
            await route.continue_()
            return

        # 2. 静态资源（JS/CSS/font）查缓存或下载缓存
        if resource_type in _RESOURCE_CACHE_MAP:
            await self._handle_cacheable(route, url, resource_type)
            return

        # 3. 其他资源（image/xhr/fetch/media）放行
        await route.continue_()

    async def _handle_cacheable(
        self, route: Any, url: str, resource_type: str
    ) -> None:
        """处理可缓存的静态资源：查缓存命中则 fulfill，未命中则 fetch + 缓存。"""
        cache_path = self._cache_path(url, resource_type)
        if cache_path.exists():
            logger.debug(f"[Interceptor] 缓存命中: {resource_type} {url}")
            try:
                body = cache_path.read_bytes()
                await route.fulfill(body=body)
                return
            except Exception as e:
                logger.warning(
                    f"[Interceptor] 读取缓存失败，回退到 fetch: {url} {e}"
                )

        # 未命中：fetch 并缓存
        try:
            logger.debug(f"[Interceptor] 下载并缓存: {resource_type} {url}")
            response = await route.fetch()
            body = await response.body()
            cache_path.write_bytes(body)
            await route.fulfill(response=response)
        except Exception as e:
            logger.warning(f"[Interceptor] fetch 失败，放行: {url} {e}")
            try:
                await route.continue_()
            except Exception:
                pass

    def _cache_path(self, url: str, resource_type: str) -> Path:
        """根据 URL 计算缓存文件路径。

        用 URL 的 MD5 哈希做文件名，扩展名按 resource_type 推断。
        """
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        # 尝试从 URL 路径提取真实扩展名（.woff/.ttf/.woff2 等）
        ext = _RESOURCE_EXT.get(resource_type, "bin")
        try:
            path_part = urlparse(url).path
            _, real_ext = os.path.splitext(path_part)
            if real_ext and real_ext.startswith("."):
                ext = real_ext[1:].lower()
        except Exception:
            pass
        cache_dir = _RESOURCE_CACHE_MAP[resource_type]
        return cache_dir / f"{url_hash}.{ext}"

    def cache_stats(self) -> dict[str, int]:
        """返回各缓存目录的文件数。"""
        result: dict[str, int] = {}
        for name, d in _RESOURCE_CACHE_MAP.items():
            try:
                result[name] = len(list(d.glob("*")))
            except Exception:
                result[name] = 0
        return result

    def clear_cache(self, resource_type: str | None = None) -> int:
        """清空缓存。

        :param resource_type: 指定类型，``None`` 清空全部
        :return: 删除的文件数
        """
        count = 0
        dirs = (
            [_RESOURCE_CACHE_MAP[resource_type]]
            if resource_type
            else list(_RESOURCE_CACHE_MAP.values())
        )
        for d in dirs:
            if not d.exists():
                continue
            for f in d.glob("*"):
                if f.is_file():
                    try:
                        f.unlink()
                        count += 1
                    except Exception as e:
                        logger.warning(f"删除缓存失败 {f}: {e}")
        logger.info(f"清空缓存: {count} 个文件（type={resource_type or 'all'}）")
        return count
