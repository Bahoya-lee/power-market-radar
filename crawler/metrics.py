# -*- coding: utf-8 -*-
"""
指标补全层：给每篇文献补齐「被引数 / 参考文献数 / 期刊层级」。

为什么需要单独一层
------------------
OpenAlex 之外的源（Crossref、arXiv）不返回被引数，期刊层级更没有统一字段，
所以界面上大量文献的"被引 0 / 期刊层级 —"其实是缺数据，而不是真的没有引用。

这里统一按 DOI（无 DOI 时按标题）回查 OpenAlex：
    · works 接口   -> cited_by_count（被引数）、referenced_works_count（参考文献数）
    · sources 接口 -> 2yr_mean_citedness、h_index 等期刊指标
再结合 config.JOURNAL_TIERS 的人工名单定出期刊层级（T1~T5 / 预印本）。

结果缓存在 data/metrics_cache.json，日常更新只回查新文献或超期记录，
因此这个模块对整条流水线的时间开销很小。
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime
from pathlib import Path

if __package__ in (None, ""):  # 允许 python crawler/metrics.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from crawler import config  # type: ignore
    from crawler.netclient import FetchError, get_json  # type: ignore
    from crawler.sources import title_key  # type: ignore
else:
    from . import config
    from .netclient import FetchError, get_json
    from .sources import title_key


OPENALEX_WORKS = "https://api.openalex.org/works"
OPENALEX_SOURCES = "https://api.openalex.org/sources"

WORK_SELECT = (
    "doi,title,display_name,cited_by_count,referenced_works_count,"
    "publication_date,type,primary_location"
)
SOURCE_SELECT = (
    "id,display_name,issn_l,is_core,is_in_doaj,type,summary_stats,"
    "host_organization_name,works_count,cited_by_count"
)

CACHE_VERSION = 2

# 期刊层级阈值：OpenAlex 的 2yr_mean_citedness 近似影响因子
_IMPACT_TIERS = ((10.0, "T1"), (6.0, "T2"), (3.5, "T3"), (1.5, "T4"))

UNRANKED_LABEL = "未收录"

_SEARCH_UNSAFE = re.compile(r"[,|:()\[\]{}\"“”/\\]+")

# 这些名字说明抓到的只是预印本/仓储页，如果 OpenAlex 找到了正式期刊版，
# 就用正式期刊名替换显示，避免出现"arXiv 预印本 + T1 顶级期刊"这种自相矛盾的组合。
_PREPRINT_HINTS = (
    "arxiv",
    "preprint",
    "ssrn",
    "zenodo",
    "research square",
    "biorxiv",
    "medrxiv",
    "osf",
    "repec",
)


def tier_label(tier: str) -> str:
    """层级代码 -> 中文文案。"""
    if not tier:
        return UNRANKED_LABEL
    return config.TIER_LABELS.get(tier, tier)


def _venue_tier(name: str, *, src_type: str = "", impact: float | None = None,
                is_core: bool = False) -> tuple[str, str, str]:
    """定出期刊层级，返回 (层级代码, 依据, 中文说明)。

    优先级：人工名单 > 源类型（预印本/会议） > OpenAlex 期刊指标。
    """
    key = (name or "").strip().lower()
    if key:
        if key in config.JOURNAL_TIERS:
            return config.JOURNAL_TIERS[key], "curated", "人工名单"
        for known, tier in config.JOURNAL_TIERS.items():
            if known in key or key in known:
                return tier, "curated", "人工名单"

    stype = (src_type or "").strip().lower()
    if stype in {"repository", "preprint"}:
        return "PRE", "type", "预印本平台"
    if stype == "conference":
        if impact is not None and impact >= 6.0:
            return "T2", "metrics", "会议影响力"
        return "T3", "type", "会议论文集"
    if stype in {"book", "book series"}:
        return "T4", "type", "专著"

    if impact is not None:
        for floor, tier in _IMPACT_TIERS:
            if impact >= floor:
                return tier, "metrics", "OpenAlex 期刊指标"
        return "T5", "metrics", "OpenAlex 期刊指标"
    if is_core:
        return "T3", "metrics", "核心收录"
    return "", "none", ""


def _clean_query(text: str, limit: int = 120) -> str:
    """清掉会破坏 OpenAlex filter 语法的字符。"""
    return _SEARCH_UNSAFE.sub(" ", (text or "")).strip()[:limit]


def _normalize(text: str) -> str:
    return title_key(text or "")


def _titles_match(a: str, b: str) -> bool:
    """标题是否足够接近，避免检索结果张冠李戴。"""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = sorted((na, nb), key=len)
    return len(shorter) >= 24 and shorter in longer and len(shorter) / len(longer) >= 0.72


# ---------------------------------------------------------------- 缓存


def _empty_cache() -> dict:
    return {"version": CACHE_VERSION, "updated_at": "", "works": {}, "sources": {}}


def load_cache(path: Path) -> dict:
    """读取指标缓存；文件损坏或版本不符时从头开始。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_cache()
    if not isinstance(raw, dict) or raw.get("version") != CACHE_VERSION:
        return _empty_cache()
    raw.setdefault("works", {})
    raw.setdefault("sources", {})
    return raw


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cache["version"] = CACHE_VERSION
    cache["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def work_key(paper: dict) -> str:
    """一篇文献在缓存里的键：优先 DOI，其次标题。"""
    doi = (paper.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    return f"title:{_normalize(paper.get('title') or '')}"


def _is_stale(entry: dict | None, today: date, force: bool) -> bool:
    if not entry:
        return True
    if force:
        return True
    checked = str(entry.get("checked") or "")[:10]
    try:
        seen = datetime.strptime(checked, "%Y-%m-%d").date()
    except ValueError:
        return True
    return (today - seen).days >= config.METRICS_REFRESH_DAYS


# ---------------------------------------------------------------- 抓取


def _work_record(item: dict, checked: str) -> dict:
    loc = item.get("primary_location") or {}
    src = loc.get("source") or {}
    return {
        "citations": int(item.get("cited_by_count") or 0),
        "reference_count": int(item.get("referenced_works_count") or 0),
        "source_id": str(src.get("id") or "").rstrip("/").split("/")[-1],
        "source_name": (src.get("display_name") or "").strip(),
        "source_issn": (src.get("issn_l") or "").strip(),
        "source_type": (src.get("type") or "").strip(),
        "source_is_core": bool(src.get("is_core")),
        "checked": checked,
    }


def _store_work(cache: dict, key: str, record: dict) -> bool:
    """写入一条作品记录，返回是否有实质变化。"""
    old = cache["works"].get(key)
    if (
        old
        and old.get("citations") == record.get("citations")
        and old.get("reference_count") == record.get("reference_count")
        and old.get("source_id") == record.get("source_id")
    ):
        old["checked"] = record["checked"]
        return False
    cache["works"][key] = record
    return True


def _parallel_batches(batches: list, worker, *, label: str, progress=None,
                      on_save=None, deadline: float | None = None) -> list:
    """带并发和时间预算地跑一批请求，到点就不再发起新请求。

    返回所有已完成请求的结果（按完成顺序展开）。所有结果都在主线程里消费，
    这样缓存只被单线程写入，不需要加锁。
    """
    if not batches:
        return []
    workers = max(1, min(config.METRICS_WORKERS, len(batches)))
    pending = deque(batches)
    running: dict = {}
    results: list = []
    done = 0
    total = len(batches)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while pending or running:
            while pending and len(running) < workers:
                if deadline is not None and time.monotonic() >= deadline:
                    pending.clear()
                    break
                batch = pending.popleft()
                running[pool.submit(worker, batch)] = batch

            if not running:
                break

            timeout = 2.0
            if deadline is not None:
                timeout = max(0.5, min(timeout, deadline - time.monotonic()))
            finished, _ = wait(
                list(running), timeout=timeout, return_when=FIRST_COMPLETED
            )
            for future in finished:
                running.pop(future, None)
                done += 1
                if progress:
                    progress(done, total, f"{label} {done}/{total}")
                if on_save and done % 5 == 0:
                    on_save()
                results.extend(future.result() or [])
    return results


def _fetch_works_by_doi(dois: list[str], checked: str, cache: dict,
                        progress=None, on_save=None,
                        deadline: float | None = None) -> set[str]:
    """批量回查 DOI，返回查到的 DOI 集合。"""
    found: set[str] = set()
    batch_size = max(1, min(config.METRICS_BATCH, 50))
    batches = [dois[i:i + batch_size] for i in range(0, len(dois), batch_size)]

    def one(batch: list[str]) -> list[dict]:
        params = {
            "filter": "doi:" + "|".join(batch),
            "select": WORK_SELECT,
            "per-page": str(len(batch)),
            "mailto": config.MAILTO,
        }
        try:
            payload = get_json(OPENALEX_WORKS, params, retries=2, source="openalex")
        except FetchError:
            return []
        return list(payload.get("results") or [])

    for item in _parallel_batches(
        batches, one, label="回查被引", progress=progress, on_save=on_save,
        deadline=deadline,
    ):
        doi = (item.get("doi") or "").replace("https://doi.org/", "").strip().lower()
        if not doi:
            continue
        record = _work_record(item, checked)
        found.add(doi)
        _store_work(cache, f"doi:{doi}", record)

    return found


TITLE_BATCH = 12  # 一次请求里放多少条标题（URL 长度与召回率的折中）


def _fetch_works_by_title(items: list[tuple[str, str]], checked: str, cache: dict,
                          progress=None, on_save=None,
                          deadline: float | None = None) -> int:
    """按标题批量回查（用于没有 DOI 或 OpenAlex 未收录 DOI 的文献）。

    OpenAlex 的 title.search 支持用 `|` 做 OR，因此可以把十几条标题放进
    一次请求里，比逐条查询快一个数量级。返回命中的条数。
    """
    queries = [(key, _clean_query(title, 100)) for key, title in items]
    queries = [(k, q) for k, q in queries if len(q) >= 12]
    batches = [queries[i:i + TITLE_BATCH] for i in range(0, len(queries), TITLE_BATCH)]

    def one(batch: list[tuple[str, str]]) -> list[tuple]:
        params = {
            "filter": "title.search:" + "|".join(q for _k, q in batch),
            "select": WORK_SELECT,
            "per-page": str(len(batch) * 2),
            "mailto": config.MAILTO,
        }
        try:
            payload = get_json(OPENALEX_WORKS, params, retries=2, source="openalex")
        except FetchError:
            return []
        return [(batch, item) for item in payload.get("results") or []]

    hits = 0
    for batch, item in _parallel_batches(
        batches, one, label="按标题回查", progress=progress, on_save=on_save,
        deadline=deadline,
    ):
        candidate = item.get("display_name") or item.get("title") or ""
        record = _work_record(item, checked)
        # 找到最接近的那条输入标题，避免张冠李戴
        best_key = ""
        best_ratio = 0.0
        for key, query in batch:
            if not _titles_match(query, candidate):
                continue
            ratio = len(_normalize(query)) / max(1, len(_normalize(candidate)))
            if ratio > best_ratio:
                best_key, best_ratio = key, ratio
        if best_key and _store_work(cache, best_key, record):
            hits += 1
    return hits


def _source_record(item: dict, checked: str) -> dict:
    stats = item.get("summary_stats") or {}
    impact = stats.get("2yr_mean_citedness")
    name = (item.get("display_name") or "").strip()
    src_type = (item.get("type") or "").strip()
    is_core = bool(item.get("is_core"))
    tier, basis, note = _venue_tier(
        name, src_type=src_type, impact=impact, is_core=is_core
    )
    return {
        "name": name,
        "issn_l": (item.get("issn_l") or "").strip(),
        "type": src_type,
        "is_core": is_core,
        "is_oa": bool(item.get("is_in_doaj")),
        "publisher": (item.get("host_organization_name") or "").strip(),
        "works_count": int(item.get("works_count") or 0),
        "impact": round(float(impact), 3) if isinstance(impact, (int, float)) else None,
        "h_index": int(stats.get("h_index") or 0),
        "tier": tier,
        "tier_basis": basis,
        "tier_note": note,
        "checked": checked,
    }


def _fetch_sources(source_ids: list[str], checked: str, cache: dict,
                   deadline: float | None = None) -> None:
    """批量回查期刊指标（每次最多 50 个 OpenAlex Source ID）。"""
    ids = [s for s in dict.fromkeys(source_ids) if s]
    batches = [ids[i:i + 50] for i in range(0, len(ids), 50)]

    def one(batch: list[str]) -> list[dict]:
        params = {
            "filter": "ids.openalex:" + "|".join(batch),
            "select": SOURCE_SELECT,
            "per-page": str(len(batch)),
            "mailto": config.MAILTO,
        }
        try:
            payload = get_json(OPENALEX_SOURCES, params, retries=2, source="openalex")
        except FetchError:
            return []
        return list(payload.get("results") or [])

    for item in _parallel_batches(batches, one, label="回查期刊指标", deadline=deadline):
        sid = str(item.get("id") or "").rstrip("/").split("/")[-1]
        if not sid:
            continue
        cache["sources"][sid] = _source_record(item, checked)


# ---------------------------------------------------------------- 应用


def _apply_to_paper(paper: dict, work: dict, sources: dict) -> bool:
    """把缓存里的指标写到文献上，返回是否补到了有效数据。"""
    if not work:
        return False

    citations = work.get("citations")
    if isinstance(citations, int):
        paper["citations"] = max(int(paper.get("citations") or 0), citations)
    if work.get("reference_count") is not None:
        paper["reference_count"] = int(work["reference_count"])

    src = sources.get(work.get("source_id") or "")
    if src:
        paper["venue_tier"] = src.get("tier") or ""
        paper["venue_tier_label"] = tier_label(src.get("tier") or "")
        paper["venue_tier_basis"] = src.get("tier_note") or ""
        paper["venue_impact"] = src.get("impact")
        paper["venue_h_index"] = src.get("h_index")
        paper["venue_is_core"] = bool(src.get("is_core"))
        paper["venue_publisher"] = src.get("publisher") or ""
        _align_venue_name(paper, src, work)
    paper["metrics_source"] = "OpenAlex"
    paper["metrics_updated"] = work.get("checked") or ""
    return True


def _align_venue_name(paper: dict, src: dict, work: dict) -> None:
    """让"期刊名"和"期刊层级"指向同一本刊。

    预印本被期刊收录后，元数据里常留着 arXiv/SSRN 这类占位名，
    这时用 OpenAlex 找到的正式期刊名替换，并记下原始出处。
    """
    source_name = (work.get("source_name") or src.get("name") or "").strip()
    if not source_name:
        return
    current = (paper.get("venue") or "").strip()
    if current.lower() == source_name.lower():
        return
    looks_like_placeholder = (not current) or any(h in current.lower() for h in _PREPRINT_HINTS)
    if not looks_like_placeholder:
        return
    paper["venue"] = source_name
    if current:
        paper["venue_preprint_note"] = current


def apply_cache(papers: list[dict], cache: dict) -> int:
    """只用缓存给文献打指标（不联网）。"""
    hits = 0
    for paper in papers:
        work = cache["works"].get(work_key(paper))
        if work and _apply_to_paper(paper, work, cache["sources"]):
            hits += 1
    return hits


# ---------------------------------------------------------------- 主入口


def enrich_papers(
    papers: list[dict],
    root: Path,
    *,
    allow_network: bool = True,
    force: bool = False,
    progress=None,
    budget_sec: float | None = None,
) -> dict:
    """给一批文献补齐引用与期刊层级，返回本次补全统计。"""
    cache_path = root / config.METRICS_CACHE
    cache = load_cache(cache_path)
    today = date.today()
    checked = today.isoformat()
    deadline = (time.monotonic() + budget_sec) if budget_sec and budget_sec > 0 else None

    stats = {
        "enabled": bool(config.METRICS_ENABLED),
        "network": False,
        "looked_up": 0,
        "title_looked_up": 0,
        "title_hits": 0,
        "sources_fetched": 0,
        "cached": 0,
        "errors": 0,
        "timed_out": False,
        "budget_sec": budget_sec,
        "updated_at": cache.get("updated_at") or "",
    }
    if not config.METRICS_ENABLED:
        return stats

    if allow_network:
        def saver() -> None:
            """把当前缓存落盘（只在主线程调用，避免并发读写）。"""
            save_cache(cache_path, cache)

        pending_dois: list[str] = []
        pending_titles: list[tuple[str, str]] = []
        for paper in papers:
            key = work_key(paper)
            if not _is_stale(cache["works"].get(key), today, force):
                continue
            doi = (paper.get("doi") or "").strip().lower()
            if doi:
                pending_dois.append(doi)
            elif len(pending_titles) < config.METRICS_TITLE_LOOKUPS:
                pending_titles.append((key, paper.get("title") or ""))

        pending_dois = list(dict.fromkeys(pending_dois))
        stats["looked_up"] = len(pending_dois)
        if pending_dois:
            found = _fetch_works_by_doi(
                pending_dois, checked, cache, progress, on_save=saver, deadline=deadline
            )
            saver()
            # DOI 没查到的（OpenAlex 未收录），再用标题兜一次
            for paper in papers:
                if len(pending_titles) >= config.METRICS_TITLE_LOOKUPS:
                    break
                doi = (paper.get("doi") or "").strip().lower()
                if not doi or doi in found:
                    continue
                if work_key(paper) in cache["works"]:
                    continue
                pending_titles.append((work_key(paper), paper.get("title") or ""))

        if pending_titles:
            stats["title_hits"] = _fetch_works_by_title(
                pending_titles, checked, cache, progress, on_save=saver,
                deadline=deadline,
            )
        stats["title_looked_up"] = len(pending_titles)
        save_cache(cache_path, cache)

        # 给新出现的期刊补指标
        source_ids = []
        for paper in papers:
            work = cache["works"].get(work_key(paper))
            sid = (work or {}).get("source_id") or ""
            if sid and (force or sid not in cache["sources"]):
                source_ids.append(sid)
        source_ids = list(dict.fromkeys(source_ids))
        if source_ids:
            _fetch_sources(source_ids, checked, cache, deadline=deadline)
            stats["sources_fetched"] = len(source_ids)

        stats["timed_out"] = bool(deadline is not None and time.monotonic() >= deadline)
        stats["network"] = True
        save_cache(cache_path, cache)
        stats["updated_at"] = cache.get("updated_at") or ""

    stats["cached"] = apply_cache(papers, cache)
    stats["with_citations"] = sum(1 for p in papers if p.get("metrics_source"))
    stats["with_tier"] = sum(1 for p in papers if p.get("venue_tier"))
    stats["total"] = len(papers)
    return stats


# ---------------------------------------------------------------- CLI


def main(argv=None) -> int:
    """命令行预热缓存：python crawler/metrics.py [--force] [--limit N]"""
    import argparse

    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="用 OpenAlex 补全被引数与期刊层级缓存")
    ap.add_argument("--force", action="store_true", help="忽略缓存有效期，全部重新回查")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 篇（调试用）")
    ap.add_argument("--source", choices=["db", "json"], default="db",
                    help="从哪里取文献列表（默认本地库）")
    args = ap.parse_args(argv)

    if args.source == "db":
        if __package__ in (None, ""):
            from crawler.store import Store  # type: ignore
        else:
            from .store import Store

        store = Store(root / "data" / "library.db")
        try:
            papers = store.load_all()
        finally:
            store.close()
    else:
        papers = json.loads((root / "data" / "papers.json").read_text(encoding="utf-8"))

    if args.limit:
        papers = papers[: args.limit]

    print(f"  待补全文献：{len(papers)} 篇")
    stats = enrich_papers(
        papers, root, force=args.force,
        progress=lambda i, n, label: print(f"\r  {label:<28}", end="", flush=True),
    )
    print()
    print(f"  · 命中缓存/已补全：{stats['cached']} 篇")
    print(f"  · 有被引数据：{stats['with_citations']}/{stats['total']} 篇")
    print(f"  · 有期刊层级：{stats['with_tier']}/{stats['total']} 篇")
    print(f"  · 缓存更新时间：{stats['updated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
