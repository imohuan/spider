"""图片代理/缓存 API — 本地 hash 缓存 + 按需下载。"""
from __future__ import annotations

import hashlib
import os

import httpx
from flask import Blueprint, jsonify, request, send_file

from core.logger import get_logger

logger = get_logger("web.api.images")
bp = Blueprint("images", __name__)


@bp.route("/proxy")
def proxy_image():
    """图片代理 — Hash URL 查本地缓存，命中直接返回，未命中下载后返回。

    Query: ``?url=<encoded_image_url>``

    缓存路径: ``data/images/<sha256(url)>.<ext>``
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()

    images_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "images",
    )

    # 1. 查本地缓存
    for ext in (".jpg", ".png", ".webp", ".gif"):
        path = os.path.join(images_dir, f"{url_hash}{ext}")
        if os.path.exists(path):
            mime = {
                ".jpg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif",
            }
            return send_file(path, mimetype=mime.get(ext, "image/jpeg"))

    # 2. 下载
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"图片下载失败 {resp.status_code}: {url[:120]}")
            return jsonify({"error": f"Download failed: {resp.status_code}"}), 502

        content_type = resp.headers.get("content-type", "").lower()
        ext_map = {
            "image/jpeg": ".jpg", "image/png": ".png",
            "image/webp": ".webp", "image/gif": ".gif",
        }
        ext = ".jpg"
        for mime, e in ext_map.items():
            if mime in content_type:
                ext = e
                break

        os.makedirs(images_dir, exist_ok=True)
        path = os.path.join(images_dir, f"{url_hash}{ext}")
        with open(path, "wb") as f:
            f.write(resp.content)

        mime = {
            ".jpg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".gif": "image/gif",
        }
        logger.info(f"图片已缓存: {url_hash}{ext} ({len(resp.content)} bytes)")
        return send_file(path, mimetype=mime.get(ext, "image/jpeg"))

    except httpx.ConnectError:
        logger.warning(f"图片连接失败: {url[:120]}")
        return jsonify({"error": "无法连接到图片服务器"}), 502
    except httpx.TimeoutException:
        logger.warning(f"图片下载超时: {url[:120]}")
        return jsonify({"error": "图片下载超时（15s）"}), 504
    except Exception as e:
        logger.error(f"图片代理异常: {e}")
        return jsonify({"error": str(e)}), 500
