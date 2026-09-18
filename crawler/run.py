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
import time
import traceback
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):  # 允许 python crawler/run.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from crawler import build, config, metrics, sources  # type: ignore
    from crawler.netclient import has_network  # type: ignore
    from crawler.store import Store  # type: ignore
else:
    from . import build, config, metrics, sources
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
    ap.add_argument("--refresh-metrics", action="store_true",
                    help="强制重新回查被引数与期刊层级（忽略缓存有效期）")
    ap.add_argument("--no-metrics", action="store_true", help="跳过指标补全")
    ap.add_argument("--max-minutes", type=float, default=None,
                    help=f"抓取时间预算（分钟），默认 {config.MAX_UPDATE_MINUTES}；0 表示不限时")
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


# ---------------------------------------------------------------- 抓取调度

def _crawl_all(topics, *, quiet: bool, max_minutes: float) -> dict:
    """抓取全部主题，返回 (文献, 错误, 是否提前收工, 被暂停的数据源)。

    两个保护机制，避免网络异常时一次更新跑上几个小时：
      1. 时间预算：到点就不再提交新主题，用已拿到的数据继续建站；
      2. 熔断：某个数据源连续失败若干次后，剩余主题不再请求它。
    """
    budget_sec = max(0.0, max_minutes) * 60
    deadline = (time.monotonic() + budget_sec) if budget_sec else None

    collected: list[dict] = []
    errors: list[dict] = []
    source_failures: Counter[str] = Counter()
    skipped: set[str] = set()
    pending = deque(topics)
    total = len(topics)
    done = 0
    stopped_early = False

    workers = max(1, min(config.MAX_TOPIC_WORKERS, total))
    pool = ThreadPoolExecutor(max_workers=workers)
    running: dict = {}
    try:
        while pending or running:
            # 提交新任务：受并发数与时间预算约束
            while pending and len(running) < workers:
                if deadline is not None and time.monotonic() >= deadline:
                    stopped_early = True
                    break
                topic = pending.popleft()
                future = pool.submit(
                    sources.fetch_topic, topic, config.SOURCES, set(skipped)
                )
                running[future] = (topic, time.monotonic())

            if not running:
                break

            wait_timeout = 5.0
            if deadline is not None:
                wait_timeout = max(0.5, min(wait_timeout, deadline - time.monotonic()))
            finished, _ = wait(
                list(running), timeout=wait_timeout, return_when=FIRST_COMPLETED
            )

            for future in finished:
                topic, submitted = running.pop(future)
                done += 1
                got, errs = future.result()
                collected.extend(got)
                errors.extend(errs)

                # 熔断：某个数据源连续失败超过阈值后，本轮不再请求它
                failed = {err.get("source") or "" for err in errs}
                for name in config.SOURCES:
                    if not config.SOURCES.get(name):
                        continue
                    if name in failed:
                        source_failures[name] += 1
                        if source_failures[name] >= config.SOURCE_FAILURE_LIMIT:
                            skipped.add(name)
                    else:
                        source_failures[name] = 0

                if not quiet:
                    spent = time.monotonic() - submitted
                    progress(done, total, f"{topic['zh']}（{spent:.0f}s）")

            if pending and deadline is not None and time.monotonic() >= deadline:
                stopped_early = True
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

    return {
        "papers": collected,
        "errors": errors,
        "stopped_early": stopped_early or bool(pending),
        "skipped_sources": sorted(skipped),
        "source_failures": dict(source_failures),
    }


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

    # 时间预算：默认走 config.MAX_UPDATE_MINUTES；首次全量抓取（--fresh）默认不限时。
    if args.max_minutes is None:
        budget_minutes = 0.0 if args.fresh else float(config.MAX_UPDATE_MINUTES)
    else:
        budget_minutes = max(0.0, float(args.max_minutes))

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
    stopped_early = False
    skipped_sources: list[str] = []
    crawl_seconds = 0.0

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

        crawl_started = time.monotonic()
        result = _crawl_all(topics, quiet=args.quiet, max_minutes=budget_minutes)
        fetched, errors = result["papers"], result["errors"]
        stopped_early = result["stopped_early"]
        skipped_sources = result["skipped_sources"]
        crawl_seconds = time.monotonic() - crawl_started

        print()

        source_counts = Counter(p.get("source") or "" for p in fetched)
        raw_count = len(fetched)
        fetched = sources.dedupe(fetched)
        say(f"  · 抓到 {raw_count} 条，跨源去重后 {len(fetched)} 条", C.DIM)
        if skipped_sources:
            say(
                "  ! 连续失败已暂停的数据源："
                + "、".join(config.SOURCE_LABELS.get(s, s) for s in skipped_sources),
                C.YELLOW,
            )
        if stopped_early:
            say(
                f"  ! 已用满 {budget_minutes:g} 分钟预算，本轮只抓了部分主题；"
                f"其余主题会在下次更新继续。",
                C.YELLOW,
            )

    new_uids = store.upsert_many(fetched) if fetched else set()

    if fetched:
        say(f"  · 其中首次收录 {len(new_uids)} 篇新文献", C.GREEN)
    else:
        say("  · 本次没有新增文献", C.DIM)

    papers = store.load_all()
    say(f"  · 本地库累计 {len(papers)} 篇，正在生成网站数据…", C.DIM)

    metrics_stats: dict = {}
    if args.no_metrics or not config.METRICS_ENABLED:
        say("  · 已跳过指标补全（被引数 / 期刊层级保持原样）", C.YELLOW)
    else:
        # 离线模式只用已有缓存；联网模式会回查新入库或超期的文献。
        allow_net = (not args.offline) or args.refresh_metrics
        # 指标补全和抓取共用同一份时间预算，避免前面用超了后面还在慢慢等。
        metrics_budget = None
        if budget_minutes and not args.offline:
            metrics_budget = max(0.0, budget_minutes * 60 - crawl_seconds)
            if metrics_budget < 10:
                allow_net = False
                say("  · 本次抓取已用满时间预算，指标补全留到下次更新", C.YELLOW)

        if allow_net:
            say("  · 正在补全被引数与期刊层级（OpenAlex）…", C.DIM)
        elif args.offline and not args.refresh_metrics:
            say("  · 离线模式：只用本地缓存的指标数据", C.DIM)
        metrics_stats = metrics.enrich_papers(
            papers,
            ROOT,
            allow_network=allow_net,
            force=args.refresh_metrics,
            progress=(None if args.quiet else progress),
            budget_sec=metrics_budget,
        )
        if not args.quiet:
            print()
        say(
            f"  · 指标覆盖：被引 {metrics_stats.get('with_citations', 0)}/{len(papers)} 篇，"
            f"期刊层级 {metrics_stats.get('with_tier', 0)}/{len(papers)} 篇",
            C.DIM,
        )
        if metrics_stats.get("timed_out"):
            say("  ! 指标补全用满时间预算，剩余文献会在下次更新继续回查", C.YELLOW)

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

    elapsed_sec = round((finished - started).total_seconds(), 1)
    meta = build.build_site(
        papers,
        root=ROOT,
        errors=errors,
        new_uids=new_uids,
        stats={
            "started": started.isoformat(timespec="seconds"),
            "finished": finished.isoformat(timespec="seconds"),
            "elapsed_sec": elapsed_sec,
            "topics": len(topics),
            "source_status": source_status,
            "metrics": metrics_stats,
            "stopped_early": stopped_early,
            "skipped_sources": skipped_sources,
            "budget_minutes": budget_minutes,
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
