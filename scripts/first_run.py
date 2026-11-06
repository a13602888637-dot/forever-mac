"""One-command local setup. No OS startup hooks, secret provisioning, or data entry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.paths import default_roots, game_flavors  # noqa: E402

PROJECT_ID = hashlib.sha256(str(PROJECT).encode()).hexdigest()[:16]


def health(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
            data = json.load(response)
        return data if data.get("application") == "forever-ai-companion" and data.get("project_id") == PROJECT_ID and data.get("platform_schema") == 1 else None
    except (OSError, ValueError):
        return None


def open_page(port):
    url = f"http://127.0.0.1:{port}"
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/open", url], check=True)
    elif not webbrowser.open(url):
        raise RuntimeError(f"浏览器未能打开，请访问 {url}")


def start_desktop(mode, port, no_browser=False):
    """Detach only this project's service; report readiness before the app exits."""
    data_dir = Path(os.environ.get("FAI_DATA_DIR", PROJECT / "data")).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (data_dir / "desktop-launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for candidate in range(18761, 18771):
            state = health(candidate)
            if state and state.get("mode") == mode:
                if not no_browser:
                    open_page(candidate)
                print(f"已打开运行中的助手：http://127.0.0.1:{candidate}")
                return {"url": f"http://127.0.0.1:{candidate}", "mode": mode, "port": candidate, "reused": True}
        if port is None:
            for candidate in range(18761, 18771):
                with socket.socket() as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        probe.bind(("127.0.0.1", candidate))
                    except OSError:
                        continue
                    port = candidate
                    break
        if port is None or not 1024 <= port <= 65535:
            raise RuntimeError("没有可用的本地端口")
        log_path = data_dir / "desktop.log"
        with log_path.open("a") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "backend.cli", "serve", "--mode", mode, "--port", str(port)],
                cwd=PROJECT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError(f"本地服务启动失败，详细记录：{log_path}")
            state = health(port)
            if state and state.get("mode") == mode:
                record = {"pid": process.pid, "port": port, "mode": mode, "project_id": PROJECT_ID,
                          "started_at": int(time.time())}
                (data_dir / "desktop-runtime.json").write_text(json.dumps(record, indent=2))
                if not no_browser:
                    open_page(port)
                print(f"助手已就绪：http://127.0.0.1:{port}")
                return {"url": f"http://127.0.0.1:{port}", "mode": mode, "port": port, "reused": False}
            time.sleep(0.25)
        process.terminate()
        raise RuntimeError(f"本地服务未在预期时间内就绪，详细记录：{log_path}")


def main():
    parser = argparse.ArgumentParser(description="发现无限客户端并启动插件平台；安装由用户在平台应用计划")
    parser.add_argument("--demo", action="store_true", help="仅启动离线演示，不安装插件")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不自动打开浏览器")
    parser.add_argument("--desktop", action="store_true", help="Mac 应用使用：直接启动并复用本项目后台服务")
    parser.add_argument("--emit-launch-json", action="store_true", help="为本项目 Mac 客户端返回本地服务地址")
    args = parser.parse_args()
    os.chdir(PROJECT)
    roots = [Path(os.environ["WOW_PATH"])] if os.getenv("WOW_PATH") else default_roots()
    flavors = list(dict.fromkeys(path.resolve() for root in roots for path in game_flavors(root)))
    mode = "mock"
    if not args.demo and len(flavors) == 1:
        mode = "live"
        os.environ["WOW_PATH"] = str(flavors[0])
        print("已发现无限客户端。插件管理只扫描；请在平台预览并应用安装计划。")
    elif not args.demo:
        print("未发现唯一的无限客户端，打开离线演示。已有安装目录保持原样。")
    if args.desktop:
        launch = start_desktop(mode, args.port, args.no_browser)
        if args.emit_launch_json:
            print("FOREVERAI_LAUNCH=" + json.dumps(launch, ensure_ascii=False), flush=True)
        return
    port = args.port
    if port is None:
        for candidate in range(18761, 18771):
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(("127.0.0.1", candidate))
                except OSError:
                    continue
                port = candidate
                break
        if port is None:
            parser.error("常用本地端口均被占用，请关闭旧的本项目服务后重试。")
    from backend.cli import main as serve
    if not args.no_browser:
        def open_when_ready():
            url = f"http://127.0.0.1:{port}"
            for _ in range(40):
                try:
                    with urlopen(url + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            open_page(port)
                            return
                except OSError:
                    pass
                time.sleep(0.25)
        threading.Thread(target=open_when_ready, daemon=True).start()
    sys.argv = ["foreverai", "serve", "--mode", mode, "--port", str(port)]
    serve()


if __name__ == "__main__":
    main()
