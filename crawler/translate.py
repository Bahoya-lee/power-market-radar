# -*- coding: utf-8 -*-
"""
建站预翻译：在生成 data.js 前，把英文标题、摘要、期刊名尽量翻译成中文。

策略：
1. 期刊名优先用本地词典，稳定且不需要联网；
2. 标题/摘要调用免费翻译接口，并缓存在 data/translations.json；
3. 翻译失败时保留原文，不影响主流程。

可通过环境变量关闭外部翻译：
    PMR_TRANSLATE_ENABLED=0
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import netclient


VENUE_ZH = {
    "applied energy": "应用能源",
    "the energy journal": "能源期刊",
    "ieee transactions on power systems": "IEEE 电力系统汇刊",
    "energy policy": "能源政策",
    "nature energy": "自然·能源",
    "ieee transactions on smart grid": "IEEE 智能电网汇刊",
    "ieee transactions on energy markets, policy and regulation": "IEEE 能源市场、政策与监管汇刊",
    "ieee transactions on power delivery": "IEEE 电力输送汇刊",
    "ieee transactions on sustainable energy": "IEEE 可持续能源汇刊",
    "ieee transactions on industrial informatics": "IEEE 工业信息学汇刊",
    "energy": "能源",
    "renewable and sustainable energy reviews": "可再生与可持续能源评论",
    "joule": "焦耳",
    "energy economics": "能源经济学",
    "electric power systems research": "电力系统研究",
    "international journal of electrical power & energy systems": "国际电力与能源系统期刊",
    "energy conversion and economics": "能源转化与经济",
    "journal of modern power systems and clean energy": "现代电力系统与清洁能源期刊",
    "csee journal of power and energy systems": "中国电机工程学会电力与能源系统期刊",
    "iet generation, transmission & distribution": "IET 发电、输电与配电",
    "iet renewable power generation": "IET 可再生能源发电",
    "protection and control of modern power systems": "现代电力系统保护与控制",
    "energy strategy reviews": "能源战略评论",
    "utilities policy": "公用事业政策",
    "the electricity journal": "电力期刊",
    "energy reports": "能源报告",
    "sustainable energy, grids and networks": "可持续能源、电网与网络",
    "journal of energy storage": "储能期刊",
    "energy conversion and management": "能源转化与管理",
    "advances in applied energy": "应用能源进展",
}

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
CHUNK_CHARS = 4200
MAX_ABSTRACT_CHARS = 900


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _cache_path(root: Path) -> Path:
    return root / "data" / "translations.json"


def _load_cache(root: Path) -> dict[str, str]:
    path = _cache_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(root: Path, cache: dict[str, str]) -> None:
    try:
        _cache_path(root).write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _clean_translation(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_google_response(raw: str) -> str:
    data = json.loads(raw)
    parts: list[str] = []
    for segment in data[0] or []:
        if segment and segment[0]:
            parts.append(str(segment[0]))
    return "".join(parts)


def _translate_chunk(texts: list[str]) -> list[str]:
    """翻译一小批文本；失败返回空列表。"""
    payload = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": "zh-CN",
            "dt": "t",
            "q": "\n".join(texts),
        }
    ).encode("utf-8")

    opener = netclient._urllib_opener()
    req = urllib.request.Request(
        TRANSLATE_URL,
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    with opener.open(req, timeout=18) as fp:
        raw = fp.read().decode("utf-8", errors="replace")

    translated = _clean_translation(_parse_google_response(raw))
    parts = translated.split("\n")
    if len(parts) == len(texts):
        return [_clean_translation(p) for p in parts]
    return []


def _chunks(texts: list[str]) -> list[list[str]]:
    out: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for text in texts:
        n = len(text) + 1
        if cur and size + n > CHUNK_CHARS:
            out.append(cur)
            cur = []
            size = 0
        cur.append(text)
        size += n
    if cur:
        out.append(cur)
    return out


def _translate_many(texts: list[str], cache: dict[str, str]) -> bool:
    missing = [t for t in dict.fromkeys(texts) if t and not _has_cjk(t) and t not in cache]
    if not missing:
        return True

    for chunk in _chunks(missing):
        try:
            results = _translate_chunk(chunk)
        except Exception:
            return False
        if len(results) != len(chunk):
            return False
        for original, translated in zip(chunk, results):
            if translated:
                cache[original] = translated
    return True


def apply_pre_translations(papers: list[dict], root: Path) -> dict:
    """给 papers 补充 title_zh / abstract_zh / venue_zh。"""
    cache = _load_cache(root)
    enabled = (os.environ.get("PMR_TRANSLATE_ENABLED") or "1").strip().lower() not in {
        "0", "false", "no", "off",
    }

    if enabled:
        titles = [p.get("title") or "" for p in papers]
        abstracts = [
            (p.get("abstract") or "")[:MAX_ABSTRACT_CHARS]
            for p in papers
            if p.get("abstract")
        ]
        if _translate_many(titles, cache):
            _translate_many(abstracts, cache)

    for p in papers:
        venue = (p.get("venue") or "").strip()
        venue_lower = venue.lower()
        if venue_lower in VENUE_ZH:
            p["venue_zh"] = VENUE_ZH[venue_lower]
        elif venue_lower.startswith("arxiv"):
            p["venue_zh"] = "arXiv 预印本"
        else:
            p["venue_zh"] = ""

        title = p.get("title") or ""
        abstract = p.get("abstract") or ""
        p["title_zh"] = title if _has_cjk(title) else cache.get(title, "")
        p["abstract_zh"] = abstract if _has_cjk(abstract) else cache.get(
            abstract[:MAX_ABSTRACT_CHARS], ""
        )

    _save_cache(root, cache)
    return {"translated_cache": len(cache), "enabled": enabled}
