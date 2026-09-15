# -*- coding: utf-8 -*-
"""
一站式入口：抓取 -> 去重 -> 入库 -> 分析 -> 建站。

用法示例：
    python crawler/run.py                 # 全量更新
    python crawler/run.py --topics spot_market,ai
    python crawler/run.py --offline       # 跳过抓取，只用本地库重建网站
    python crawler/run.py --open          # 更新完自动打开浏览器
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):  # 允许 python crawler/run.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from crawler import build, config, sources  # type: ignore
    from crawler.netclient import has_network  # type: ignore
    from crawler.store import Store  # type: ignore
else:
    from . import build, config, sources
    from .netclient import has_network
    from .store import Store

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- 输出美化

class C:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"


def _enable_ansi() -> None:
    """在 Windows 控制台打开 ANSI 颜色。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def say(msg: str = "", color: str = "") -> None:
    print(f"{color}{msg}{C.RESET}" if color else msg, flush=True)


def banner() -> None:
    say()
    say("  [电力市场研究前沿追踪] 数据更新", C.BOLD + C.CYAN)
    say("  " + "-" * 46, C.DIM)


def progress(done: int, total: int, label: str) -> None:
    width = 26
    filled = int(width * done / max(1, total))
    bar = "#" * filled + "." * (width - filled)
    pct = int(100 * done / max(1, total))
    print(f"\r  [{bar}] {pct:3d}%  {label[:34]:<34}", end="", flush=True)


# ---------------------------------------------------------------- 参数

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="电力市场研究前沿追踪 - 每日自动更新脚本")
    ap.add_argument("--topics", help="只抓取指定主题，逗号分隔（如 spot_market,ai）")
    ap.add_argument("--offline", action="store_true", help="跳过抓取，仅用本地库重建网站")
    ap.add_argument("--open", dest="open_browser", action="store_true", help="完成后打开网站")
    ap.add_argument("--quiet", action="store_true", help="精简输出（适合定时任务）")
    ap.add_argument("--fresh", action="store_true", help="清空本地库后重新抓取")
    ap.add_argument("--list-topics", action="store_true", help="列出所有主题后退出")
    return ap.parse_args(argv)


def select_topics(spec):
    if not spec:
        return list(config.TOPICS)
    wanted = {s.strip() for s in spec.split(",") if s.strip()}
    by_id = {t["id"]: t for t in config.TOPICS}
    picked = [by_id[w] for w in wanted if w in by_id]
    unknown = wanted - set(by_id)
    if unknown:
        say(f"  ! 未知主题已忽略：{', '.join(sorted(unknown))}", C.YELLOW)
    if not picked:
        say("  ! 没有匹配到任何主题，改为抓取全部主题", C.YELLOW)
        return list(config.TOPICS)
    return picked


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    _enable_ansi()
    args = parse_args(argv)

    if args.list_topics:
        say()
        for t in config.TOPICS:
            say(f"  {t['id']:<20} {t['zh']}")
        say()
        return 0

    started = datetime.now()
    banner()

    db_path = ROOT / "data" / "library.db"
    if args.fresh and db_path.exists():
        db_path.unlink()
        say("  · 已清空本地文献库（--fresh）", C.YELLOW)

    store = Store(db_path)
    say(f"  · 本地库现有文献：{store.count()} 篇", C.DIM)

    topics = select_topics(args.topics)
    fetched: list[dict] = []
    errors: list[dict] = []
    source_counts: Counter[str] = Counter()

    if args.offline:
        say("  · 已跳过抓取（--offline），直接用本地库重建网站", C.YELLOW)
    else:
        if not has_network():
            say("  x 检测不到网络连接。", C.RED)
            say("    请确认网络或代理可用后重试；也可以用 --offline 仅重建网站。", C.DIM)
            store.close()
            return 2

        active_sources = sum(1 for v in config.SOURCES.values() if v)
        say(f"  · 网络正常，开始抓取 {len(topics)} 个主题 x {active_sources} 个数据源", C.DIM)
        say()

        source_failures: Counter[str] = Counter()
        workers = min(config.MAX_TOPIC_WORKERS, len(topics))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(sources.fetch_topic, topic, config.SOURCES, set()): topic
                for topic in topics
            }
            done = 0
            for future in as_completed(futures):
                topic = futures[future]
                done += 1
                got, errs = future.result()
                fetched.extend(got)
                errors.extend(errs)
                for err in errs:
                    name = err.get("source") or ""
                    source_failures[name] += 1
                progress(done, len(topics), topic["zh"])

        print()

        source_counts = Counter(p.get("source") or "" for p in fetched)
        raw_count = len(fetched)
        fetched = sources.dedupe(fetched)
        say(f"  · 抓到 {raw_count} 条，跨源去重后 {len(fetched)} 条", C.DIM)

    new_uids = store.upsert_many(fetched) if fetched else set()

    if fetched:
        say(f"  · 其中首次收录 {len(new_uids)} 篇新文献", C.GREEN)
    else:
        say("  · 本次没有新增文献", C.DIM)

    papers = store.load_all()
    say(f"  · 本地库累计 {len(papers)} 篇，正在生成网站数据…", C.DIM)

    finished = datetime.now()
    source_errors = Counter(e.get("source") or "" for e in errors)
    source_status = []
    for source_id, enabled in config.SOURCES.items():
        if not enabled:
            status = "disabled"
        elif source_errors.get(source_id):
            status = "failed"
        elif source_counts.get(source_id):
            status = "ok"
        else:
            status = "empty"
        source_status.append(
            {
                "id": source_id,
                "name": config.SOURCE_LABELS.get(source_id, source_id),
                "enabled": bool(enabled),
                "status": status,
                "fetched": source_counts.get(source_id, 0),
                "errors": source_errors.get(source_id, 0),
            }
        )

    store.log_run(
        started.isoformat(timespec="seconds"),
        finished.isoformat(timespec="seconds"),
        len(fetched),
        len(new_uids),
        errors,
    )
    store.close()

    meta = build.build_site(
        papers,
        root=ROOT,
        errors=errors,
        new_uids=new_uids,
        stats={
            "started": started.isoformat(timespec="seconds"),
            "finished": finished.isoformat(timespec="seconds"),
            "elapsed_sec": round((finished - started).total_seconds(), 1),
            "topics": len(topics),
            "source_status": source_status,
        },
    )

    say()
    say(f"  √ 更新完成：共 {meta['total']} 篇文献，近 30 天 {meta['recent30']} 篇，"
        f"今日新增 {meta['new_today']} 篇", C.GREEN + C.BOLD)
    say(f"    网站入口：{ROOT / 'index.html'}", C.DIM)

    if errors:
        say(f"  ! {len(errors)} 个数据源请求失败（已跳过，不影响其余结果）", C.YELLOW)
        if not args.quiet:
            for e in errors[:5]:
                say(f"      - {e['source']} / {e['topic']}：{e['error'][:90]}", C.DIM)

    say()

    if args.open_browser:
        import webbrowser

        webbrowser.open((ROOT / "index.html").as_uri())

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n  已中断。", C.YELLOW)
        raise SystemExit(130)
    except Exception:
        say("\n  更新过程中出现未预期的错误：", C.RED)
        traceback.print_exc()
        raise SystemExit(1)
