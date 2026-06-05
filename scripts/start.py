"""一键启动脚本：构建前端 + 启动后端（单端口8000同时serve前端和API）。

Usage:
    python start.py

然后浏览器打开 http://localhost:8000
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"


def build_frontend():
    """如果dist不存在或src更新了，重新build前端。"""
    if not FRONTEND_DIST.exists():
        print("📦 首次构建前端...")
        _run_npm_build()
    else:
        # 检查src是否比dist新
        src_mtime = max(
            f.stat().st_mtime
            for f in FRONTEND_DIR.rglob("src/**/*")
            if f.is_file()
        ) if any(FRONTEND_DIR.rglob("src/**/*")) else 0
        dist_mtime = FRONTEND_DIST.stat().st_mtime
        if src_mtime > dist_mtime:
            print("📦 前端源码有更新，重新构建...")
            _run_npm_build()
        else:
            print("✅ 前端build已是最新")


def _run_npm_build():
    """执行 npm install + npm run build。"""
    if not (FRONTEND_DIR / "node_modules").exists():
        print("   npm install...")
        subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), check=True, shell=True)
    print("   npm run build...")
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND_DIR), check=True, shell=True)
    print("✅ 前端构建完成")


def start_server():
    """启动FastAPI服务器。"""
    print("\n🚀 启动 CGADS 服务器...")
    print("   前端 + API: http://localhost:8000")
    print("   API文档:    http://localhost:8000/docs")
    print("   按 Ctrl+C 停止\n")

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "backend.api:app",
         "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=str(PROJECT_ROOT),
    )


if __name__ == "__main__":
    try:
        build_frontend()
        start_server()
    except KeyboardInterrupt:
        print("\n👋 已停止")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 构建失败: {e}")
        sys.exit(1)
