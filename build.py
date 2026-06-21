"""
build.py — 58-data 项目一键打包脚本

将整个项目（前端 Vue SPA + 后端 Flask + Playwright Chromium）打包为独立的可执行文件夹。

输出结构:
    dist/58-crawler/
    ├── 58-crawler.exe          # 主程序入口
    └── _internal/              # Python 运行时 + 所有依赖
        ├── python3.dll         # Python 解释器
        ├── *.pyd               # C 扩展（lxml, Pillow, eventlet 等的编译产物）
        ├── *.pyc               # Python 字节码
        ├── playwright/         # Playwright Python 包
        │   └── driver/package/.local-browsers/
        │       └── chromium-XXXX/  # Chromium 浏览器二进制 (~150MB)
        └── web/static/         # 前端 dist（Vue SPA）

运行时会在 EXE 同级目录自动创建 data/（DB、日志、缓存）。

关于 .pyd vs .py/.pyc:
    .pyd 是 Python 的 C 扩展模块（Windows 上等同于 .dll）。
    当你的依赖包（lxml, Pillow, eventlet 等）有 C 代码时，
    pip install 会编译成 .pyd 放入 site-packages。
    PyInstaller 打包时会自动收集这些 .pyd 到 _internal/ 目录。
    你看到的 "一堆 py 脚本" 是纯 Python 包，它们被编译为 .pyc（字节码）。
    PyInstaller --onedir 的输出就是 .exe + .pyd + .pyc 的组合。

用法:
    python build.py             # 全量构建
    python build.py --frontend  # 仅构建前端
    python build.py --backend   # 仅打包后端（需先构建前端和 venv）
    python build.py --skip-venv # 全量构建但跳过 venv 创建
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ── 路径常量 ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
FRONTEND_DIR = PROJECT_ROOT / "ax-ui-demo"
FRONTEND_DIST = FRONTEND_DIR / "dist"
STATIC_DIR = PROJECT_ROOT / "web" / "static"
VENV_DIR = PROJECT_ROOT / ".venv"
DIST_DIR = PROJECT_ROOT / "dist"
APP_NAME = "58-crawler"

IS_WIN = sys.platform == "win32"
# PyInstaller --add-data 的分隔符：Windows 用 ;  Linux/macOS 用 :
ADD_DATA_SEP = ";" if IS_WIN else ":"


# ── 工具函数 ─────────────────────────────────────────────────────

def get_venv_python() -> str:
    """返回 venv 中的 python 解释器路径。"""
    if IS_WIN:
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def get_venv_pip() -> list[str]:
    """返回 [python, -m, pip] 命令前缀，使用 venv 中的 Python。"""
    return [get_venv_python(), "-m", "pip"]


def _find_exe(name: str) -> str:
    """查找可执行文件完整路径。Windows 上 subprocess 无法自动解析 .cmd/.bat。"""
    import shutil as _shutil
    exe_path = _shutil.which(name)
    if exe_path:
        return exe_path
    # Windows: 尝试常见位置
    if IS_WIN:
        for base in [
            os.path.expandvars(r"%LOCALAPPDATA%\pnpm"),
            os.path.expandvars(r"%APPDATA%\npm"),
            r"C:\Program Files\nodejs",
        ]:
            for ext in (".exe", ".cmd", ""):
                candidate = os.path.join(base, name + ext)
                if os.path.isfile(candidate):
                    return candidate
    raise FileNotFoundError(f"找不到命令: {name}，请确认已安装")


def run(cmd: list[str], **kwargs) -> None:
    """运行命令并打印。自动查找可执行文件路径。"""
    cmd_copy = list(cmd)
    cmd_copy[0] = _find_exe(cmd_copy[0])
    print(f"  >>> {cmd_copy[0]} {' '.join(cmd_copy[1:])}")
    subprocess.run(cmd_copy, check=True, **kwargs)


# ── 构建步骤 ─────────────────────────────────────────────────────

def setup_venv() -> None:
    """创建项目本地虚拟环境，安装所有 Python 依赖 + PyInstaller。"""
    print("=" * 60)
    print("[1/5] 设置虚拟环境 (.venv/)")
    print("=" * 60)

    if not VENV_DIR.exists():
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        print(f"  venv 已创建: {VENV_DIR}")
    else:
        print(f"  venv 已存在: {VENV_DIR}")

    # 升级 pip
    run(get_venv_pip() + ["install", "--upgrade", "pip"])

    # 安装项目依赖
    req_file = PROJECT_ROOT / "requirements.txt"
    print("  安装项目依赖 (requirements.txt)...")
    run(get_venv_pip() + ["install", "-r", str(req_file)])

    # PyInstaller 不在 requirements.txt 中（它是构建工具，非运行时依赖）
    print("  安装 PyInstaller...")
    run(get_venv_pip() + ["install", "pyinstaller>=6.0"])

    print("  虚拟环境就绪")


def build_frontend() -> None:
    """构建前端 Vite 项目，输出到 web/static/。"""
    print("=" * 60)
    print("[2/5] 构建前端 (Vue + Vite)")
    print("=" * 60)

    # 清理旧输出
    if STATIC_DIR.exists():
        shutil.rmtree(STATIC_DIR)

    # 安装依赖 + 构建
    run(["pnpm", "install"], cwd=FRONTEND_DIR)
    run(["pnpm", "run", "build"], cwd=FRONTEND_DIR)

    # 复制到 Flask 静态文件目录
    shutil.copytree(FRONTEND_DIST, STATIC_DIR)

    # 列出构建产物
    asset_count = 0
    asset_size = 0
    for f in sorted(STATIC_DIR.rglob("*")):
        if f.is_file():
            asset_count += 1
            asset_size += f.stat().st_size

    print(f"  前端构建完成 -> {STATIC_DIR}")
    print(f"  文件数: {asset_count}, 总大小: {asset_size / 1024:.0f} KB")
    print(f"  index.html: {(STATIC_DIR / 'index.html').exists()}")


def install_playwright_browsers() -> None:
    """在 venv 中本地安装 Playwright Chromium。

    PLAYWRIGHT_BROWSERS_PATH=0 会使浏览器安装到 playwright 包目录下
    （site-packages/playwright/driver/package/.local-browsers/），
    而不是系统全局目录。这样 PyInstaller 打包时可以直接收集。
    """
    print("=" * 60)
    print("[3/5] 安装 Playwright Chromium (本地模式)")
    print("=" * 60)

    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    run(
        [get_venv_python(), "-m", "playwright", "install", "chromium"],
        env=env,
    )

    # 确认安装位置
    site_packages = (
        VENV_DIR / "Lib" / "site-packages"
        if IS_WIN
        else VENV_DIR / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    browsers_dir = site_packages / "playwright" / "driver" / "package" / ".local-browsers"

    if browsers_dir.exists():
        print(f"  Chromium 安装位置: {browsers_dir}")
        total = 0
        for d in sorted(browsers_dir.iterdir()):
            if d.is_dir():
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024 / 1024
                total += size
                print(f"    {d.name}  ({size:.0f} MB)")
        print(f"  浏览器总大小: {total:.0f} MB")
    else:
        print(f"  [警告] 未找到 .local-browsers，请手动检查")
        print(f"  预期位置: {browsers_dir}")


def package_backend() -> None:
    """PyInstaller 打包后端为 --onedir 可执行文件夹。

    关键配置:
    - --onedir: 文件夹模式，启动快于 --onefile，推荐（因为 Chromium 150MB 解压慢）
    - --add-data: 将前端静态文件和 Playwright 浏览器注入到 _internal/
    - --collect-all: 收集 playwright, eventlet, flask_socketio 等包的完整文件
    - --hidden-import: eventlet 的绿色线程需要显式声明
    """
    print("=" * 60)
    print("[4/5] PyInstaller 打包后端")
    print("=" * 60)

    # ── 前置检查 ──
    if not STATIC_DIR.exists() or not (STATIC_DIR / "index.html").exists():
        print("  [错误] web/static/index.html 不存在")
        print("  请先执行: python build.py --frontend")
        sys.exit(1)

    site_packages = (
        VENV_DIR / "Lib" / "site-packages"
        if IS_WIN
        else VENV_DIR / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    playwright_driver = site_packages / "playwright" / "driver"

    if not playwright_driver.exists():
        print("  [错误] Playwright driver 目录不存在")
        print(f"  预期位置: {playwright_driver}")
        print("  请先执行完整的 build.py（包含 playwright chromium 安装）")
        sys.exit(1)

    # ── 构建 PyInstaller 命令 ──
    # 注意: --add-data 格式为 source{ADD_DATA_SEP}dest
    # Windows 上 ADD_DATA_SEP = ;  Linux/Mac = :
    cmd = [
        get_venv_python(), "-m", "PyInstaller",

        # 输出配置
        "--onedir",                          # 文件夹模式（启动快）
        "--name", APP_NAME,
        "--console",                         # 保留控制台窗口（可看日志）
        "--clean",                           # 清理缓存
        "--noconfirm",                       # 覆盖已有输出

        # 模块搜索路径
        "--paths", str(PROJECT_ROOT),

        # ── 数据文件（注入到 _internal/） ──
        f"--add-data={STATIC_DIR}{ADD_DATA_SEP}web{os.sep}static",
        f"--add-data={playwright_driver}{ADD_DATA_SEP}playwright{os.sep}driver",

        # ── 收集完整包（含 .pyd / .dll / package data） ──
        "--collect-all", "playwright",
        "--collect-all", "eventlet",
        "--collect-all", "flask_socketio",
        "--collect-all", "engineio",
        "--collect-all", "socketio",
        "--collect-all", "dns",

        # ── 隐藏导入（eventlet monkey-patch 所需） ──
        "--hidden-import", "eventlet.hubs.epolls",
        "--hidden-import", "eventlet.hubs.kqueue",
        "--hidden-import", "eventlet.hubs.selects",
        "--hidden-import", "dns.rdtypes",
        "--hidden-import", "dns.rdtypes.IN",
        "--hidden-import", "dns.rdtypes.ANY",
        "--hidden-import", "engineio.async_drivers.eventlet",
        "--hidden-import", "greenlet",

        # ── 排除不需要的模块（减小编译体积） ──
        "--exclude-module", "playwright.firefox",
        "--exclude-module", "playwright.webkit",
        "--exclude-module", "pytest",
        "--exclude-module", "_pytest",
        "--exclude-module", "tkinter",

        # ── 入口 ──
        str(PROJECT_ROOT / "main.py"),
    ]

    print(f"  PyInstaller 命令: {' '.join(cmd[:10])} ...")
    run(cmd, cwd=PROJECT_ROOT)

    # ── 清理 ──
    build_temp = PROJECT_ROOT / "build"
    spec_file = PROJECT_ROOT / f"{APP_NAME}.spec"
    if build_temp.exists():
        shutil.rmtree(build_temp)
    if spec_file.exists():
        spec_file.unlink()

    print(f"  打包完成 -> {DIST_DIR / APP_NAME}")


def print_summary() -> None:
    """输出打包结果摘要和使用说明。"""
    print("=" * 60)
    print("[5/5] 打包完成！")
    print("=" * 60)
    print()

    exe_path = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    exe_path_nix = DIST_DIR / APP_NAME / APP_NAME

    if IS_WIN:
        actual_exe = exe_path
    else:
        actual_exe = exe_path_nix

    if not actual_exe.exists():
        print("  [错误] 可执行文件不存在，打包可能失败")
        print(f"  预期位置: {actual_exe}")
        return

    # 计算输出大小
    total_size = sum(
        f.stat().st_size
        for f in (DIST_DIR / APP_NAME).rglob("*")
        if f.is_file()
    ) / 1024 / 1024

    print(f"  输出目录: {DIST_DIR / APP_NAME}/")
    print(f"  可执行文件: {actual_exe.name}")
    print(f"  总大小: {total_size:.0f} MB")
    print()

    # 列出 _internal 子目录
    internal = DIST_DIR / APP_NAME / "_internal"
    if internal.exists():
        print("  内部结构 (_internal/):")
        for item in sorted(internal.iterdir()):
            if item.is_dir():
                size = sum(
                    f.stat().st_size for f in item.rglob("*") if f.is_file()
                ) / 1024 / 1024
                name = item.name
                if name == "playwright":
                    print(f"    {name}/  ({size:.0f} MB)  Playwright + Chromium 浏览器")
                elif name == "web":
                    print(f"    {name}/  ({size:.0f} MB)  前端 SPA 静态文件")
                elif not name.startswith("_"):
                    print(f"    {name}/  ({size:.0f} MB)")
    print()
    print("  启动方式:")
    if IS_WIN:
        print(f"    {DIST_DIR / APP_NAME / APP_NAME}.exe")
    else:
        print(f"    {DIST_DIR / APP_NAME / APP_NAME}")
    print("    启动后打开浏览器访问: http://127.0.0.1:5000")
    print()
    print("  注意事项:")
    print("    - 首次运行会在 EXE 同级目录自动创建 data/ (数据库、日志、缓存)")
    print("    - Chromium 浏览器已内嵌到 _internal/ 中，无需额外安装")
    print("    - 分发时只需复制整个 58-crawler/ 文件夹")


# ── 主入口 ───────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="58-data 项目打包工具 — 前端 + 后端 + Playwright → 独立可执行文件夹",
    )
    parser.add_argument(
        "--frontend", action="store_true",
        help="仅构建前端 (pnpm build → web/static/)",
    )
    parser.add_argument(
        "--backend", action="store_true",
        help="仅打包后端 PyInstaller（需先有 .venv 和 web/static/）",
    )
    parser.add_argument(
        "--skip-venv", action="store_true",
        help="跳过虚拟环境创建（假设 .venv/ 已就绪）",
    )
    parser.add_argument(
        "--skip-browsers", action="store_true",
        help="跳过 Playwright Chromium 安装（假设已安装）",
    )
    args = parser.parse_args()

    # 切换到项目根目录
    os.chdir(PROJECT_ROOT)

    # ── 单步模式 ──
    if args.frontend:
        build_frontend()
        return

    if args.backend:
        package_backend()
        return

    # ── 全量构建 ──
    if not args.skip_venv:
        setup_venv()
    else:
        print("[跳过] 虚拟环境设置 (--skip-venv)")

    build_frontend()

    if not args.skip_browsers:
        install_playwright_browsers()
    else:
        print("[跳过] Playwright Chromium 安装 (--skip-browsers)")

    package_backend()
    print_summary()


if __name__ == "__main__":
    main()
