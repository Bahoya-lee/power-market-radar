# -*- coding: utf-8 -*-
"""
分析层：自动打标签、计算热点分、生成趋势序列、挖掘上升关键词。

设计思路
--------
热点 = 近 30 天产出量 × 增长动能 × 影响力。
只用绝对数量会被沉淀多年的老方向淹没，所以引入 momentum（近 30 天速度
对比此前 90 天速度）来捕捉"正在变热"的方向。
另外用 n-gram 频率对比自动发现词库之外的新兴术语，避免只能看到预设主题。
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import config


# ---------------------------------------------------------------- 打标签

def _haystack(paper: dict) -> str:
    return f"{paper.get('title','')} {paper.get('abstract','')}".lower()


def tag_paper(paper: dict) -> list[str]:
    """按关键词把文献归入一个或多个主题。"""
    text = _haystack(paper)
    title = (paper.get("title") or "").lower()
    found: list[tuple[float, str]] = []

    for topic in config.TOPICS:
        hits = 0.0
        for kw in topic["keywords"]:
            k = kw.lower()
            if k in text:
                # 出现在标题里说明主题更核心，权重加倍
                hits += 2.0 if k in title else 1.0
        if hits > 0:
            found.append((hits, topic["id"]))

    if not found:
        # 没有命中任何关键词时，保留数据源检索时的主题归属
        return list(paper.get("topics") or [])

    found.sort(reverse=True)
    return [tid for _, tid in found[:3]]


# 期刊层级 -> 热度里的"平台分"
_TIER_SCORE = {
    "T1": 1.00,
    "T2": 0.82,
    "T3": 0.62,
    "T4": 0.44,
    "T5": 0.30,
    "PRE": 0.34,
    "": 0.15,
}


def enrich(papers: list[dict]) -> list[dict]:
    """补全主题标签、引用速度、期刊层级与热度分等派生字段。"""
    today = date.today()
    for p in papers:
        p["topics"] = tag_paper(p)
        p["topic_primary"] = p["topics"][0] if p["topics"] else p.get("topic_primary", "")

        citations = p.get("citations") or 0
        year = p.get("year") or today.year
        age = max(1, today.year - year + 1)
        p["cite_per_year"] = round(citations / age, 2)

        p["recency_days"] = _days_since(p.get("date") or f"{year}-01-01")

        tier = str(p.get("venue_tier") or "").upper()
        p["venue_tier"] = tier
        p["venue_tier_label"] = config.TIER_LABELS.get(tier, "") if tier else ""
        p["reference_count"] = int(p.get("reference_count") or 0)
        p["is_top_venue"] = bool(
            tier in {"T1", "T2"} or (p.get("journal_weight") or 0) >= 0.85
        )

    _assign_heat(papers)
    return papers


def _assign_heat(papers: list[dict]) -> None:
    """给每篇文献算一个 0-100 的"热度"综合分。

    热度 = 引用速度(32%) + 被引总量(22%) + 新近程度(30%) + 期刊层级(16%)。
    四项先各自归一化，避免被绝对数值大的老文献垄断榜单。
    """
    if not papers:
        return
    velocity = [math.log1p(max(0.0, p.get("cite_per_year") or 0)) for p in papers]
    cited = [math.log1p(max(0, p.get("citations") or 0)) for p in papers]
    recency = [
        math.exp(-min(max(int(p.get("recency_days") or 9999), 0), 3650) / 180.0)
        for p in papers
    ]
    venue = [_TIER_SCORE.get(p.get("venue_tier") or "", _TIER_SCORE[""]) for p in papers]

    v_n, c_n = _norm(velocity), _norm(cited)
    for i, p in enumerate(papers):
        score = 0.32 * v_n[i] + 0.22 * c_n[i] + 0.30 * recency[i] + 0.16 * venue[i]
        p["heat"] = round(score * 100, 1)


def _days_since(iso: str) -> int:
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 9999
    return (date.today() - d).days


# ---------------------------------------------------------------- 趋势序列

def _month_keys(months: int = 12) -> list[str]:
    """返回最近 N 个月的 YYYY-MM 键（升序）。"""
    today = date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(keys))


def topic_trends(papers: list[dict], months: int = 12) -> dict:
    """每个主题近 N 个月的月度产出量，用于画趋势线。"""
    keys = _month_keys(months)
    index = {k: i for i, k in enumerate(keys)}
    series: dict[str, list[int]] = {t["id"]: [0] * months for t in config.TOPICS}

    for p in papers:
        month = (p.get("date") or "")[:7]
        if month not in index:
            continue
        for tid in p.get("topics") or []:
            if tid in series:
                series[tid][index[month]] += 1

    return {"months": keys, "series": series}


# ---------------------------------------------------------------- 热点计算

def _norm(values: list[float]) -> list[float]:
    """把一组数值线性归一到 0..1；全相等时统一给 0.5。"""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def hotspots(papers: list[dict], trends: dict) -> list[dict]:
    """计算每个主题的热度、动能与影响力，输出排序后的榜单。"""
    today = date.today()
    d30 = (today - timedelta(days=30)).isoformat()
    d90 = (today - timedelta(days=90)).isoformat()
    d180 = (today - timedelta(days=180)).isoformat()

    stats = []
    for topic in config.TOPICS:
        tid = topic["id"]
        mine = [p for p in papers if tid in (p.get("topics") or [])]

        recent30 = sum(1 for p in mine if (p.get("date") or "") >= d30)
        prev90 = sum(1 for p in mine if d90 <= (p.get("date") or "") < d30)
        recent180 = sum(1 for p in mine if (p.get("date") or "") >= d180)

        # 引用影响力：取该主题被引最高的 20 篇的引用年均值
        cpy = sorted((p.get("cite_per_year") or 0) for p in mine)[-20:]
        impact = sum(cpy) / len(cpy) if cpy else 0.0

        top_venue_ratio = (
            sum(1 for p in mine if p.get("is_top_venue")) / len(mine) if mine else 0.0
        )

        # 动能：近 30 天月均产出 ÷ 此前 90 天月均产出（加平滑项避免除零）
        momentum = (recent30 / 1.0 + 0.5) / (prev90 / 3.0 + 0.5)

        stats.append(
            {
                "id": tid,
                "zh": topic["zh"],
                "color": topic["color"],
                "total": len(mine),
                "recent30": recent30,
                "recent180": recent180,
                "impact": round(impact, 2),
                "top_venue_ratio": round(top_venue_ratio, 3),
                "momentum": round(momentum, 2),
                "trend": trends["series"].get(tid, []),
            }
        )

    if not stats:
        return []

    volume_n = _norm([math.log1p(s["recent180"]) for s in stats])
    momentum_n = _norm([math.log1p(s["momentum"]) for s in stats])
    impact_n = _norm([math.log1p(s["impact"]) for s in stats])
    venue_n = _norm([s["top_venue_ratio"] for s in stats])

    for i, s in enumerate(stats):
        score = (
            0.38 * volume_n[i]
            + 0.30 * momentum_n[i]
            + 0.20 * impact_n[i]
            + 0.12 * venue_n[i]
        )
        s["score"] = round(score * 100, 1)
        s["level"] = "升温" if s["momentum"] >= 1.15 else ("降温" if s["momentum"] <= 0.85 else "平稳")

    stats.sort(key=lambda s: s["score"], reverse=True)
    return stats


# ---------------------------------------------------------------- 上升关键词

_TOKEN_RE = re.compile(r"[a-z][a-z\-]{2,}")


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in config.STOPWORDS]


def _ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def rising_terms(papers: list[dict], top_n: int = 40, window_days: int = 180) -> list[dict]:
    """对比"近 N 天"与"此前 N 天"的词频，找出正在冒头的新术语。

    只看标题（标题最能概括主题，且噪声远低于摘要）。
    """
    today = date.today()
    cur_from = (today - timedelta(days=window_days)).isoformat()
    prev_from = (today - timedelta(days=window_days * 2)).isoformat()

    cur: Counter = Counter()
    prev: Counter = Counter()
    docs_cur = 0
    docs_prev = 0

    for p in papers:
        d = p.get("date") or ""
        if d >= cur_from:
            bucket, count_doc = cur, True
        elif prev_from <= d < cur_from:
            bucket, count_doc = prev, True
        else:
            continue

        if count_doc:
            if bucket is cur:
                docs_cur += 1
            else:
                docs_prev += 1

        tokens = _tokenize(p.get("title") or "")
        for n in (1, 2, 3):
            bucket.update(set(_ngrams(tokens, n)))

    docs_cur = max(1, docs_cur)
    docs_prev = max(1, docs_prev)

    scored = []
    for term, c in cur.items():
        if c < 3:
            continue
        if len(term.split()) == 1 and len(term) < 5:
            continue
        p_count = prev.get(term, 0)
        rate_cur = c / docs_cur
        rate_prev = p_count / docs_prev
        growth = (rate_cur + 1e-4) / (rate_prev + 1e-4)
        # 只保留有明显增长的词，避免输出常青词
        if growth < 1.25:
            continue
        scored.append(
            {
                "term": term,
                "count": c,
                "prev_count": p_count,
                "growth": round(growth, 2),
                "weight": round(rate_cur * math.log1p(growth) * 100, 3),
                "is_new": p_count == 0,
            }
        )

    scored.sort(key=lambda x: x["weight"], reverse=True)

    # 去掉被更长短语包含的短词，让列表更可读
    picked: list[dict] = []
    for item in scored:
        if any(item["term"] in p["term"] and item["term"] != p["term"] for p in picked):
            continue
        picked.append(item)
        if len(picked) >= top_n:
            break
    return picked


# ---------------------------------------------------------------- 汇总

def summarize(papers: list[dict], new_uids: set[str]) -> dict:
    today = date.today()
    d30 = (today - timedelta(days=30)).isoformat()
    venues = Counter(p.get("venue") or "未标注来源" for p in papers if p.get("venue"))
    sources = Counter(p.get("source_name") or p.get("source") or "未知" for p in papers)

    return {
        "total": len(papers),
        "recent30": sum(1 for p in papers if (p.get("date") or "") >= d30),
        "new_today": len(new_uids),
        "oa": sum(1 for p in papers if p.get("is_oa")),
        "top_venues": [{"name": n, "count": c} for n, c in venues.most_common(12)],
        "sources": [{"name": n, "count": c} for n, c in sources.most_common()],
    }
