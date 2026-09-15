# -*- coding: utf-8 -*-
"""
在 Windows 任务计划程序中注册/取消"每日自动更新"。

用法：
    python crawler/schedule.py install --time 08:30
    python crawler/schedule.py status
    python crawler/schedule.py remove
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "PowerMarketRadar-Daily"
LOG_DIR = ROOT / "logs"
TASK_CONFIG = ROOT / "data" / "task_config.json"
TASK_STATUS = ROOT / "data" / "tasks.json"


def _python_exe() -> str:
    """返回用于后台运行的 Python 解释器路径（优先 pythonw，避免弹黑框）。"""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else exe)


def _run(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 1, "找不到 schtasks 命令（仅支持 Windows）"


def _read_task_config() -> dict:
    try:
        return json.loads(TASK_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_task_config(time_str: str, push: bool) -> None:
    TASK_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    TASK_CONFIG.write_text(
        json.dumps({"time": time_str, "push": bool(push)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_task_status(status: dict) -> None:
    TASK_STATUS.parent.mkdir(parents=True, exist_ok=True)
    TASK_STATUS.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _query_status() -> dict:
    code, out = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"])
    installed = code == 0
    cfg = _read_task_config()
    status = {
        "task_name": TASK_NAME,
        "installed": installed,
        "time": cfg.get("time", ""),
        "push": bool(cfg.get("push", False)),
        "next_run": "",
        "last_result": "",
        "log_file": str(LOG_DIR / "update.log"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not installed:
        return status

    def field(label_cn: str, label_en: str) -> str:
        m = re.search(rf"(?:{label_cn}|{label_en}):\s*(.+)$", out, flags=re.MULTILINE)
        return m.group(1).strip() if m else ""

    status["next_run"] = field("下次运行时间", "Next Run Time")
    status["last_result"] = field("上次结果", "Last Result")
    status["last_run"] = field("上次运行时间", "Last Run Time")
    return status


def write_status_file() -> int:
    status = _query_status()
    _write_task_status(status)
    return 0 if status["installed"] else 1


def install(time_str: str, push: bool = False) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_py = ROOT / "crawler" / "run.py"
    py = _python_exe()

    # 任务计划程序无法直接输出到文件，所以套一层 bat 记录日志。
    if push:
        wrapper = ROOT / "_daily_update_push.bat"
        command = (
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{ROOT / "同步到GitHub.ps1"}" '
            f'>> "{LOG_DIR / "update.log"}" 2>&1'
        )
    else:
        wrapper = ROOT / "_daily_update.bat"
        command = f'"{py}" "{run_py}" --quiet >> "{LOG_DIR / "update.log"}" 2>&1'
    wrapper.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f'cd /d "{ROOT}"\r\n'
        f"{command}\r\n",
        encoding="utf-8",
    )

    code, out = _run([
        "schtasks", "/Create",
        "/SC", "DAILY",
        "/TN", TASK_NAME,
        "/TR", f'"{wrapper}"',
        "/ST", time_str,
        "/F",
    ])

    if code != 0:
        print("  注册失败：")
        print("  " + out.strip()[:500])
        print("  · 可尝试以管理员身份运行本脚本，或手动在「任务计划程序」中创建。")
        return 1

    _write_task_config(time_str, push)
    print(f"  √ 已注册每日自动更新任务：{TASK_NAME}")
    print(f"    执行时间：每天 {time_str}")
    print(f"    执行动作：{'抓取并推送 GitHub' if push else '仅抓取并刷新本地网站'}")
    print(f"    运行日志：{LOG_DIR / 'update.log'}")
    print("    提示：任务只在电脑开机且已登录时运行；错过的时间点不会自动补跑。")
    write_status_file()
    return 0


def remove() -> int:
    code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code != 0:
        print("  未找到该任务，或删除失败：")
        print("  " + out.strip()[:400])
        return 1
    try:
        TASK_CONFIG.unlink(missing_ok=True)
    except Exception:
        pass
    print(f"  √ 已取消每日自动更新任务：{TASK_NAME}")
    write_status_file()
    return 0


def status() -> int:
    status = _query_status()
    if not status["installed"]:
        print("  当前没有注册每日自动更新任务。")
    else:
        print(f"  任务名称：{status['task_name']}")
        print(f"  执行时间：{status['time'] or '未知'}")
        print(f"  执行动作：{'抓取并推送 GitHub' if status['push'] else '仅抓取并刷新本地网站'}")
        if status.get("next_run"):
            print(f"  下次运行：{status['next_run']}")
        if status.get("last_result"):
            print(f"  上次结果：{status['last_result']}")
    write_status_file()
    return 0 if status["installed"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="电力市场前沿追踪 —— 每日任务管理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("install", help="注册每日自动更新")
    p_ins.add_argument("--time", default="08:30", help="每天执行时间，24 小时制，如 08:30")
    p_ins.add_argument("--push", action="store_true", help="每日更新后推送到 GitHub")

    sub.add_parser("remove", help="取消每日自动更新")
    sub.add_parser("status", help="查看任务状态")

    args = ap.parse_args(argv)
    if sys.platform != "win32" and args.cmd != "status":
        print("  该功能依赖 Windows 任务计划程序。")
        return 1

    if args.cmd == "install":
        return install(args.time, push=args.push)
    if args.cmd == "remove":
        return remove()
    return status()


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
