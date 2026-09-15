# -*- coding: utf-8 -*-
"""本地任务管理服务：为 tasks.html 提供注册/取消/查看每日任务与推送接口。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
POWERSHELL = "powershell.exe"


def _json_response(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _read_tasks_status() -> dict:
    return _read_json(
        ROOT / "data" / "tasks.json",
        {
            "task_name": "PowerMarketRadar-Daily",
            "installed": False,
            "time": "",
            "push": False,
            "next_run": "",
            "last_result": "",
            "updated_at": "",
        },
    )


def _run(args: list[str], timeout=None) -> tuple[int, str]:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            meta = _read_json(ROOT / "data" / "meta.json", {})
            tasks = _read_tasks_status()
            _json_response(
                self,
                {
                    "task": tasks,
                    "sources": meta.get("source_status", []),
                    "updated_at": meta.get("updated_at", ""),
                    "errors": meta.get("errors", []),
                },
            )
            return
        if path == "/api/log":
            try:
                lines = int(self.query_params().get("lines", ["200"])[0])
            except Exception:
                lines = 200
            log = ROOT / "logs" / "update.log"
            text = ""
            if log.exists():
                text = "".join(log.read_text(encoding="utf-8", errors="replace").splitlines(True)[-lines:])
            _json_response(self, {"log": text})
            return
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}

        if path == "/api/install":
            time_str = str(payload.get("time") or "08:30").strip()
            push = bool(payload.get("push"))
            cmd = [PYTHON, str(ROOT / "crawler" / "schedule.py"), "install", "--time", time_str]
            if push:
                cmd.append("--push")
            code, out = _run(cmd)
            _json_response(self, {"ok": code == 0, "output": out, "task": _read_tasks_status()})
            return

        if path == "/api/remove":
            code, out = _run([PYTHON, str(ROOT / "crawler" / "schedule.py"), "remove"])
            _json_response(self, {"ok": code == 0, "output": out, "task": _read_tasks_status()})
            return

        if path == "/api/update":
            push = bool(payload.get("push"))
            if push:
                code, out = _run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "同步到GitHub.ps1")], timeout=3600)
            else:
                code, out = _run([PYTHON, str(ROOT / "crawler" / "run.py"), "--quiet"], timeout=3600)
            _json_response(self, {"ok": code == 0, "output": out})
            return

        _json_response(self, {"ok": False, "error": "not found"}, status=404)

    def query_params(self):
        from urllib.parse import parse_qs, urlparse
        return parse_qs(urlparse(self.path).query)

    def log_message(self, fmt, *args):
        sys.stderr.write("[task-server] " + fmt % args + "\n")


def main():
    parser = argparse.ArgumentParser(description="电力市场前沿追踪 - 本地任务管理服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"任务管理页面：http://{args.host}:{args.port}/tasks.html")
    print("按 Ctrl+C 退出。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
