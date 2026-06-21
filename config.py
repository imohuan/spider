"""全局配置模块 - 定义项目路径常量。

路径推导策略：

- **开发模式**：基于 ``__file__`` 推导，项目可在任意位置克隆运行
- **PyInstaller frozen 模式**：
  - ``PROJECT_ROOT`` = EXE 所在目录（用于可写数据：DB、日志、缓存）
  - ``STATIC_DIR`` = ``_MEIPASS/web/static/``（前端打包文件，只读）
  - ``_MEIPASS`` 中的 Playwright 浏览器由 ``--add-data`` 注入

目录创建请通过 :func:`ensure_dirs` 显式触发，由入口（main.py）在启动时调用，
避免 import 时的副作用污染测试环境。
"""
import os
import sys


def _is_frozen() -> bool:
    """检测是否运行在 PyInstaller 打包环境中。"""
    return getattr(sys, 'frozen', False)


if _is_frozen():
    # --onedir 模式：EXE 在 dist/58-crawler/58-crawler.exe
    # 可写数据放在 EXE 同级目录
    PROJECT_ROOT = os.path.dirname(sys.executable)
    # 静态文件（前端 dist）在 _MEIPASS（_internal/）中
    STATIC_DIR = os.path.join(sys._MEIPASS, 'web', 'static')  # type: ignore[attr-defined]
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(PROJECT_ROOT, 'web', 'static')

# 数据根目录
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# 各数据子目录
IMAGES_DIR = os.path.join(DATA_DIR, "images")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
RAW_RESPONSE_DIR = os.path.join(DATA_DIR, "raw_responses")

# 缓存子目录
CACHE_JS_DIR = os.path.join(CACHE_DIR, "js")
CACHE_CSS_DIR = os.path.join(CACHE_DIR, "css")
CACHE_FONT_DIR = os.path.join(CACHE_DIR, "font")

# SQLite 数据库路径
DB_PATH = os.path.join(DATA_DIR, "crawler.db")


def ensure_dirs() -> None:
    """创建所有数据目录（幂等）。由入口在启动时调用。"""
    for _dir in (
        DATA_DIR,
        IMAGES_DIR,
        CACHE_DIR,
        CACHE_JS_DIR,
        CACHE_CSS_DIR,
        CACHE_FONT_DIR,
        LOGS_DIR,
        RAW_RESPONSE_DIR,
    ):
        os.makedirs(_dir, exist_ok=True)
