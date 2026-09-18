# -*- coding: utf-8 -*-
"""
各学术数据源的适配器，统一输出同一套字段。

统一字段：
    uid, title, abstract, authors[], venue, year, date, url, pdf_url, doi,
    citations, source, source_name, type, is_oa, topics[], journal_weight
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from . import config
from .netclient import FetchError, get_json, get_text


# ---------------------------------------------------------------- 工具函数

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(value) -> str:
    """去掉 HTML 标签与多余空白，并还原实体字符。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value)
    text = str(value)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\u00ad", "")
    return _WS_RE.sub(" ", text).strip()


def make_uid(*parts: str) -> str:
    """生成稳定 ID：同一篇文献每次抓取都得到同样的 uid，用于去重与增量更新。"""
    basis = "|".join(p.strip().lower() for p in parts if p)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def title_key(title: str) -> str:
    """标题归一化，用于跨源去重。"""
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (title or "").lower())
    return _WS_RE.sub(" ", t).strip()[:120]


def _to_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value) -> str:
    """把各种日期表示统一成 YYYY-MM-DD。"""
    if not value:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    text = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    m = re.match(r"(\d{4})-(\d{2})", text)
    if m:
        return f"{m.group(0)}-01"
    m = re.match(r"(\d{4})", text)
    if m:
        return f"{m.group(0)}-01-01"
    return ""


def _journal_weight(venue: str) -> float:
    v = (venue or "").lower().strip()
    if not v:
        return 0.0
    if v in config.TOP_JOURNALS:
        return config.TOP_JOURNALS[v]
    for name, weight in config.TOP_JOURNALS.items():
        if name in v or v in name:
            return weight
    return 0.0


def _reconstruct_abstract(inverted) -> str:
    """OpenAlex 的摘要以倒排索引形式给出，这里还原成正常文本。"""
    if not inverted:
        return ""
    positions = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((int(i), word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _split_authors_openalex(authorships) -> list[str]:
    names = []
    for a in authorships or []:
        name = clean_text((a.get("author") or {}).get("display_name"))
        if name:
            names.append(name)
    return names


# ---------------------------------------------------------------- OpenAlex

OPENALEX_BASE = "https://api.openalex.org/works"


def _openalex_params(queries, *, from_date, sort, per_page, type_filter="article|review") -> dict:
    or_group = "|".join(f'"{q}"' for q in queries)
    filters = [
        f"title_and_abstract.search:{or_group}",
        f"from_publication_date:{from_date}",
        f"type:{type_filter}",
    ]
    return {
        "filter": ",".join(filters),
        "sort": sort,
        "per-page": str(per_page),
        "select": (
            "id,doi,title,display_name,publication_date,publication_year,"
            "authorships,primary_location,type,cited_by_count,open_access,"
            "abstract_inverted_index,language,is_retracted"
        ),
        "mailto": config.MAILTO,
    }


def _openalex_to_paper(item: dict, topic_id: str):
    title = clean_text(item.get("display_name") or item.get("title"))
    if not title:
        return None

    doi = (item.get("doi") or "").replace("https://doi.org/", "").strip()

    loc = item.get("primary_location") or {}
    src = loc.get("source") or {}
    venue = clean_text(src.get("display_name"))

    pdf_url = clean_text((item.get("open_access") or {}).get("oa_url"))
    if not pdf_url:
        pdf_url = clean_text(loc.get("pdf_url"))

    landing = clean_text(loc.get("landing_page_url"))
    url = f"https://doi.org/{doi}" if doi else (landing or clean_text(item.get("id")))

    abstract = clean_text(_reconstruct_abstract(item.get("abstract_inverted_index")))
    abstract = re.sub(r"^\s*abstract[:\s]+", "", abstract, flags=re.IGNORECASE)

    oa_id = clean_text(item.get("id")).rstrip("/").split("/")[-1]
    return {
        "uid": make_uid(f"oa:{oa_id}"),
        "title": title,
        "abstract": abstract,
        "authors": _split_authors_openalex(item.get("authorships")),
        "venue": venue,
        "year": _to_int(item.get("publication_year")),
        "date": _parse_date(item.get("publication_date")),
        "url": url,
        "pdf_url": pdf_url,
        "doi": doi,
        "citations": _to_int(item.get("cited_by_count")),
        "source": "openalex",
        "source_name": "OpenAlex",
        "type": clean_text(item.get("type")) or "article",
        "is_oa": bool((item.get("open_access") or {}).get("is_oa")),
        "topics": [topic_id],
        "journal_weight": _journal_weight(venue),
        "language": clean_text(item.get("language")),
    }


def fetch_openalex(topic: dict) -> list[dict]:
    """抓取一个主题：最新文献 + 近若干年高被引文献。"""
    out: list[dict] = []
    today = date.today()

    jobs = [
        {
            "from_date": (today - timedelta(days=config.RECENT_DAYS)).isoformat(),
            "sort": "publication_date:desc",
            "per_page": config.PER_TOPIC_RECENT,
        },
        {
            "from_date": date(today.year - config.CLASSIC_YEARS, 1, 1).isoformat(),
            "sort": "cited_by_count:desc",
            "per_page": config.PER_TOPIC_CLASSIC,
        },
        {
            "from_date": (today - timedelta(days=config.RECENT_DAYS)).isoformat(),
            "sort": "publication_date:desc",
            "per_page": config.PER_TOPIC_PREPRINTS,
            "type_filter": "preprint",
        },
    ]

    for job in jobs:
        params = _openalex_params(topic["queries"], **job)
        payload = get_json(OPENALEX_BASE, params, source="openalex")
        for item in payload.get("results", []):
            paper = _openalex_to_paper(item, topic["id"])
            if paper:
                out.append(paper)
    return out


# ---------------------------------------------------------------- arXiv

ARXIV_BASE = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _arxiv_query(topic: dict) -> str:
    """构造 arXiv 检索式：主题短语 OR 组合，并限定在相关分类内。"""
    phrases = [f'abs:"{q}"' for q in topic["queries"]]
    cats = " OR ".join(f"cat:{c}" for c in config.ARXIV_CATEGORIES)
    return f"({' OR '.join(phrases)}) AND ({cats})"


def fetch_arxiv(topic: dict, max_results: int = 30) -> list[dict]:
    params = {
        "search_query": _arxiv_query(topic),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": "0",
        "max_results": str(max_results),
    }
    try:
        text = get_text(
            ARXIV_BASE,
            params,
            accept="application/atom+xml",
            source="arxiv",
        )
    except FetchError:
        # arXiv 在部分网络环境下直连会被重置。这里改用 OpenAlex 的预印本记录，
        # 再按 landing_page_url 过滤出 arXiv 条目，保证 arXiv 源仍能贡献前沿文献。
        try:
            return _fetch_arxiv_via_openalex(topic, max_results)
        except FetchError:
            # OpenAlex 也暂时限流时，不让整个更新流程报错；OpenAlex 主源仍会抓取预印本。
            return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FetchError("arXiv 返回的 XML 无法解析") from exc

    out: list[dict] = []
    for entry in root.findall(f"{ATOM}entry"):
        title = clean_text(entry.findtext(f"{ATOM}title"))
        if not title:
            continue

        authors = [
            clean_text(a.findtext(f"{ATOM}name")) for a in entry.findall(f"{ATOM}author")
        ]
        authors = [a for a in authors if a]

        abstract = clean_text(entry.findtext(f"{ATOM}summary"))
        published = _parse_date(entry.findtext(f"{ATOM}published"))

        link_pdf = ""
        link_abs = ""
        for link in entry.findall(f"{ATOM}link"):
            href = link.get("href") or ""
            if link.get("title") == "pdf" or href.endswith(".pdf"):
                link_pdf = href
            elif link.get("rel") == "alternate":
                link_abs = href

        doi = clean_text(entry.findtext(f"{ARXIV_NS}doi"))
        arxiv_id = clean_text(entry.findtext(f"{ATOM}id"))
        primary = entry.find(f"{ARXIV_NS}primary_category")
        category = primary.get("term") if primary is not None else ""

        out.append(
            {
                "uid": make_uid(f"arxiv:{arxiv_id}"),
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "venue": f"arXiv preprint ({category})" if category else "arXiv preprint",
                "year": _to_int(published[:4]),
                "date": published,
                "url": link_abs or arxiv_id,
                "pdf_url": link_pdf,
                "doi": doi,
                "citations": 0,
                "source": "arxiv",
                "source_name": "arXiv",
                "type": "preprint",
                "is_oa": True,
                "topics": [topic["id"]],
                "journal_weight": 0.0,
                "language": "en",
            }
        )
    return out


def _fetch_arxiv_via_openalex(topic: dict, max_results: int = 30) -> list[dict]:
    """arXiv 直连失败时的兜底：用 OpenAlex 预印本结果筛选 arXiv 链接。"""
    today = date.today()
    params = _openalex_params(
        topic["queries"],
        from_date=(today - timedelta(days=config.RECENT_DAYS)).isoformat(),
        sort="publication_date:desc",
        per_page=max(30, max_results * 2),
        type_filter="preprint",
    )
    payload = get_json(OPENALEX_BASE, params, source="openalex")
    out: list[dict] = []
    for item in payload.get("results", []):
        paper = _openalex_to_paper(item, topic["id"])
        if not paper:
            continue
        loc = item.get("primary_location") or {}
        landing = clean_text(loc.get("landing_page_url"))
        pdf = clean_text(loc.get("pdf_url"))
        if "arxiv.org" not in (landing + " " + pdf).lower():
            continue
        arxiv_id = landing.rstrip("/").split("/")[-1] if landing else ""
        paper.update(
            {
                "uid": make_uid(f"arxiv:{arxiv_id or paper['uid']}"),
                "source": "arxiv",
                "source_name": "arXiv",
                "type": "preprint",
                "is_oa": True,
                "venue": "arXiv preprint",
                "url": landing or paper["url"],
                "pdf_url": pdf or paper["pdf_url"],
                "doi": paper.get("doi") or "",
            }
        )
        out.append(paper)
    return out


# ---------------------------------------------------------------- Crossref

CROSSREF_BASE = "https://api.crossref.org/works"


def fetch_crossref(topic: dict, rows: int = 25) -> list[dict]:
    today = date.today()
    out: list[dict] = []
    queries = topic["queries"][:2] or [topic["zh"]]
    for query in queries:
        params = {
            # Crossref 的 bibliographic 查询不支持布尔 OR，逐个短语查询后再合并。
            "query.bibliographic": query,
            "filter": (
                f"from-pub-date:{(today - timedelta(days=config.RECENT_DAYS)).isoformat()},"
                f"until-pub-date:{today.isoformat()},"
                "type:journal-article"
            ),
            "sort": "published",
            "order": "desc",
            "rows": str(rows),
            "select": (
                "DOI,title,abstract,author,container-title,issued,published,"
                "is-referenced-by-count,type,URL,link,subject"
            ),
            "mailto": config.MAILTO,
        }
        payload = get_json(CROSSREF_BASE, params, source="crossref")
        items = (payload.get("message") or {}).get("items") or []

        for item in items:
            titles = item.get("title") or []
            title = clean_text(titles[0] if titles else "")
            if not title:
                continue

            containers = item.get("container-title") or []
            venue = clean_text(containers[0] if containers else "")

            authors = []
            for a in item.get("author") or []:
                name = " ".join(
                    p for p in [clean_text(a.get("given")), clean_text(a.get("family"))] if p
                )
                if name:
                    authors.append(name)

            issued = item.get("issued") or item.get("published") or {}
            parts = (issued.get("date-parts") or [[None]])[0]
            iso = ""
            year = 0
            if parts and parts[0]:
                year = int(parts[0])
                # Crossref 偶尔包含未来很多年的错误元数据，直接丢弃。
                if year > today.year + 1 or year < 1800:
                    continue
                month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
                day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
                iso = f"{year:04d}-{month:02d}-{day:02d}"
                if iso > today.isoformat():
                    continue

            doi = clean_text(item.get("DOI"))
            pdf_url = ""
            for lk in item.get("link") or []:
                if "pdf" in (lk.get("content-type") or ""):
                    pdf_url = clean_text(lk.get("URL"))
                    break

            out.append(
                {
                    "uid": make_uid(f"crossref:{doi or title}"),
                    "title": title,
                    "abstract": clean_text(item.get("abstract")),
                    "authors": authors,
                    "venue": venue,
                    "year": year,
                    "date": iso,
                    "url": f"https://doi.org/{doi}" if doi else clean_text(item.get("URL")),
                    "pdf_url": pdf_url,
                    "doi": doi,
                    "citations": _to_int(item.get("is-referenced-by-count")),
                    "source": "crossref",
                    "source_name": "Crossref",
                    "type": clean_text(item.get("type")) or "journal-article",
                    "is_oa": False,
                    "topics": [topic["id"]],
                    "journal_weight": _journal_weight(venue),
                    "language": clean_text(item.get("language")),
                }
            )
    return out


# ---------------------------------------------------------------- Semantic Scholar

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"


def fetch_semanticscholar(topic: dict, limit: int = 25) -> list[dict]:
    """可选数据源。无 Key 时限流严格，因此默认关闭。"""
    params = {
        "query": " ".join(topic["queries"][:2]),
        "limit": str(limit),
        "fields": (
            "title,abstract,year,publicationDate,authors,venue,externalIds,"
            "citationCount,openAccessPdf,url,publicationTypes"
        ),
        "year": f"{date.today().year - 2}-{date.today().year}",
    }
    if os.environ.get("S2_API_KEY"):
        params["x-api-key"] = os.environ["S2_API_KEY"]

    payload = get_json(S2_BASE, params, source="semanticscholar")
    out: list[dict] = []
    for item in payload.get("data") or []:
        title = clean_text(item.get("title"))
        if not title:
            continue
        ext = item.get("externalIds") or {}
        doi = clean_text(ext.get("DOI"))
        venue = clean_text(item.get("venue"))
        out.append(
            {
                "uid": make_uid(f"s2:{item.get('paperId') or doi or title}"),
                "title": title,
                "abstract": clean_text(item.get("abstract")),
                "authors": [clean_text(a.get("name")) for a in item.get("authors") or []],
                "venue": venue,
                "year": _to_int(item.get("year")),
                "date": _parse_date(item.get("publicationDate")),
                "url": clean_text(item.get("url")) or (f"https://doi.org/{doi}" if doi else ""),
                "pdf_url": clean_text((item.get("openAccessPdf") or {}).get("url")),
                "doi": doi,
                "citations": _to_int(item.get("citationCount")),
                "source": "semanticscholar",
                "source_name": "Semantic Scholar",
                "type": "article",
                "is_oa": bool(item.get("openAccessPdf")),
                "topics": [topic["id"]],
                "journal_weight": _journal_weight(venue),
                "language": "en",
            }
        )
    return out


# ---------------------------------------------------------------- 统一入口

FETCHERS = {
    "openalex": fetch_openalex,
    "arxiv": fetch_arxiv,
    "crossref": fetch_crossref,
    "semanticscholar": fetch_semanticscholar,
}


def fetch_topic(topic: dict, enabled=None, skip_sources=None):
    """抓取单个主题下所有启用的数据源。

    逐个源捕获异常：某个源不可用不会影响其它源。
    返回 (文献列表, 错误列表)。
    """
    enabled = enabled or config.SOURCES
    skip_sources = skip_sources or set()
    papers: list[dict] = []
    errors: list[dict] = []

    active = [
        name for name, fetcher in FETCHERS.items()
        if enabled.get(name) and name not in skip_sources
    ]
    if not active:
        return papers, errors

    def _fetch_one(name: str) -> tuple[list[dict], list[dict]]:
        try:
            got = FETCHERS[name](topic)
            for p in got:
                p["topic_primary"] = topic["id"]
            return got, []
        except FetchError as exc:
            return [], [{"topic": topic["id"], "source": name, "error": str(exc)}]
        except Exception as exc:  # noqa: BLE001 - 单点故障兜底
            return [], [{
                "topic": topic["id"],
                "source": name,
                "error": f"{type(exc).__name__}: {exc}",
            }]

    workers = min(config.MAX_SOURCE_WORKERS, len(active))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, name): name for name in active}
        for future in as_completed(futures):
            got, errs = future.result()
            papers.extend(got)
            errors.extend(errs)

    return papers, errors


def dedupe(papers: list[dict]) -> list[dict]:
    """跨源去重：DOI 相同，或标题归一化后相同，即视为同一篇。"""
    by_doi: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    result: list[dict] = []

    for p in papers:
        doi = (p.get("doi") or "").lower().strip()
        tkey = title_key(p.get("title") or "")

        existing = None
        if doi and doi in by_doi:
            existing = by_doi[doi]
        elif tkey and tkey in by_title:
            existing = by_title[tkey]

        if existing is not None:
            _merge_paper(existing, p)
            continue

        result.append(p)
        if doi:
            by_doi[doi] = p
        if tkey:
            by_title[tkey] = p

    return result


def _merge_paper(target: dict, incoming: dict) -> None:
    """把重复文献的信息并入已有条目：取更完整的字段与更高的被引数。"""
    for topic in incoming.get("topics") or []:
        if topic not in target["topics"]:
            target["topics"].append(topic)

    if len(incoming.get("abstract") or "") > len(target.get("abstract") or ""):
        target["abstract"] = incoming["abstract"]
    if len(incoming.get("authors") or []) > len(target.get("authors") or []):
        target["authors"] = incoming["authors"]
    if not target.get("doi") and incoming.get("doi"):
        target["doi"] = incoming["doi"]
    if not target.get("pdf_url") and incoming.get("pdf_url"):
        target["pdf_url"] = incoming["pdf_url"]
    if incoming.get("is_oa"):
        target["is_oa"] = True
    if (incoming.get("journal_weight") or 0) > (target.get("journal_weight") or 0):
        target["journal_weight"] = incoming["journal_weight"]
    if incoming.get("venue") and (not target.get("venue") or target.get("source") == "arxiv"):
        target["venue"] = incoming["venue"]

    target["citations"] = max(
        _to_int(target.get("citations")), _to_int(incoming.get("citations"))
    )

    # 预印本被正式期刊收录后，用期刊版的元数据替换展示
    if target.get("source") == "arxiv" and incoming.get("source") != "arxiv":
        target["source"] = incoming["source"]
        target["source_name"] = incoming.get("source_name", target.get("source_name"))
        if incoming.get("url"):
            target["url"] = incoming["url"]
        if incoming.get("date") and incoming["date"] < target.get("date", "9999"):
            target["date"] = incoming["date"]
