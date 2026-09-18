# -*- coding: utf-8 -*-
"""
离线自检：不联网，用内置的模拟数据跑通「抓取 -> 去重 -> 入库 -> 分析 -> 建站」全流程。

用途：
  · 确认代码本身没有语法/逻辑错误；
  · 在不具备网络条件时验证网站能否正常生成。

运行：python crawler/selftest.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from crawler import analyze, build, config, metrics, sources  # type: ignore
    from crawler.store import Store  # type: ignore
else:
    from . import analyze, build, config, metrics, sources
    from .store import Store


# ---------------------------------------------------------------- 模拟数据

def _openalex_payload():
    def inv(text):
        return {w: [i] for i, w in enumerate(text.split())}

    return {
        "meta": {"count": 2},
        "results": [
            {
                "id": "https://openalex.org/W1000000001",
                "doi": "https://doi.org/10.1016/j.apenergy.2026.100001",
                "display_name": "Electricity price forecasting with deep learning under high renewable penetration",
                "publication_date": "2026-03-11",
                "publication_year": 2026,
                "authorships": [
                    {"author": {"display_name": "Wei Zhang"}},
                    {"author": {"display_name": "Ming Li"}},
                ],
                "primary_location": {
                    "source": {"display_name": "Applied Energy"},
                    "landing_page_url": "https://example.org/a",
                    "pdf_url": None,
                },
                "type": "article",
                "cited_by_count": 42,
                "open_access": {"is_oa": True, "oa_url": "https://example.org/a.pdf"},
                "abstract_inverted_index": inv(
                    "This paper studies electricity price forecasting with deep learning "
                    "under high renewable penetration in spot market clearing."
                ),
                "language": "en",
                "is_retracted": False,
            },
            {
                "id": "https://openalex.org/W1000000002",
                "doi": "https://doi.org/10.1016/j.eneco.2026.100002",
                "display_name": "Carbon market and electricity market coupling: evidence from pilot regions",
                "publication_date": "2025-11-02",
                "publication_year": 2025,
                "authorships": [{"author": {"display_name": "Hui Wang"}}],
                "primary_location": {
                    "source": {"display_name": "Energy Economics"},
                    "landing_page_url": "https://example.org/b",
                },
                "type": "article",
                "cited_by_count": 15,
                "open_access": {"is_oa": False},
                "abstract_inverted_index": inv(
                    "We analyse carbon emission trading and electricity market coupling."
                ),
                "language": "en",
                "is_retracted": False,
            },
        ],
    }


def _arxiv_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2603.01234v1</id>
    <title>Reinforcement learning for bidding strategies in electricity spot markets</title>
    <summary>We propose a reinforcement learning approach for strategic bidding.</summary>
    <published>2026-03-09T10:00:00Z</published>
    <author><name>Lei Zhao</name></author>
    <author><name>Qian Sun</name></author>
    <link href="http://arxiv.org/abs/2603.01234v1" rel="alternate"/>
    <link title="pdf" href="http://arxiv.org/pdf/2603.01234v1"/>
    <arxiv:primary_category term="eess.SY"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2603.05678v1</id>
    <title>Deep learning for electricity price forecasting: a replication study</title>
    <summary>We revisit deep learning models for electricity price forecasting.</summary>
    <published>2026-03-05T10:00:00Z</published>
    <author><name>Wei Zhang</name></author>
    <link href="http://arxiv.org/abs/2603.05678v1" rel="alternate"/>
    <link title="pdf" href="http://arxiv.org/pdf/2603.05678v1"/>
    <arxiv:primary_category term="q-fin.GN"/>
  </entry>
</feed>
"""


def _crossref_payload():
    return {
        "message": {
            "items": [
                {
                    "DOI": "10.1016/j.apenergy.2026.100001",
                    "title": [
                        "Electricity price forecasting with deep learning under high renewable penetration"
                    ],
                    "abstract": "<jats:p>Duplicate record used to test cross-source deduplication.</jats:p>",
                    "author": [{"given": "Wei", "family": "Zhang"}],
                    "container-title": ["Applied Energy"],
                    "issued": {"date-parts": [[2026, 3, 11]]},
                    "is-referenced-by-count": 44,
                    "type": "journal-article",
                    "URL": "https://doi.org/10.1016/j.apenergy.2026.100001",
                    "link": [
                        {"content-type": "application/pdf", "URL": "https://example.org/a.pdf"}
                    ],
                    "language": "en",
                },
                {
                    "DOI": "10.1016/j.epsr.2026.100003",
                    "title": ["Virtual power plant aggregation for ancillary service markets"],
                    "abstract": "<jats:p>We study virtual power plant aggregation.</jats:p>",
                    "author": [{"given": "Fan", "family": "Yang"}],
                    "container-title": ["Electric Power Systems Research"],
                    "issued": {"date-parts": [[2026, 1, 20]]},
                    "is-referenced-by-count": 3,
                    "type": "journal-article",
                    "URL": "https://doi.org/10.1016/j.epsr.2026.100003",
                    "link": [],
                    "language": "en",
                },
            ]
        }
    }


# ---------------------------------------------------------------- 打桩

def _patch_http():
    """把网络调用替换成内置模拟数据。"""
    def fake_get_json(url, params=None, **kw):
        if "openalex" in url:
            return _openalex_payload()
        if "crossref" in url:
            return _crossref_payload()
        raise AssertionError("自检不应请求：" + url)

    def fake_get_text(url, params=None, **kw):
        if "arxiv" in url:
            return _arxiv_xml()
        raise AssertionError("自检不应请求：" + url)

    sources.get_json = fake_get_json
    sources.get_text = fake_get_text
    sources.fetch_arxiv.__globals__["get_text"] = fake_get_text
    sources.fetch_openalex.__globals__["get_json"] = fake_get_json
    sources.fetch_crossref.__globals__["get_json"] = fake_get_json


# ---------------------------------------------------------------- 主流程

def main() -> int:
    print("\n  电力市场前沿追踪 · 离线自检")
    print("  " + "-" * 46)

    _patch_http()

    topic = config.TOPICS[0]
    papers, errors = sources.fetch_topic(
        topic, {"openalex": True, "arxiv": True, "crossref": True, "semanticscholar": False}
    )
    print(f"  · 抓取：{len(papers)} 条（含跨源重复），错误 {len(errors)} 条")
    assert papers, "抓取阶段没有返回任何数据"

    deduped = sources.dedupe(papers)
    print(f"  · 去重：{len(papers)} -> {len(deduped)} 条")
    assert len(deduped) < len(papers), "跨源去重没有生效"

    # 检查关键字段都解析出来了
    sample = next((p for p in deduped if p.get("citations", 0) > 0), deduped[0])
    for field in ("uid", "title", "authors", "venue", "date", "url"):
        assert sample.get(field), f"字段 {field} 解析为空"
    assert sample["citations"] > 0, "被引数没有解析出来"
    assert any("Applied Energy" == p.get("venue") for p in deduped), "期刊名没有解析出来"
    print(f"  · 样例：{sample['title'][:40]}… / {sample['venue']} / 被引 {sample['citations']}")

    # 放在项目目录下，避免系统临时目录的权限限制
    tmp = Path(__file__).resolve().parent.parent / "_selftest_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    store = None
    try:
        store = Store(tmp / "data" / "library.db")
        new_uids = store.upsert_many(deduped)
        print(f"  · 入库：新增 {len(new_uids)} 篇，库内共 {store.count()} 篇")
        assert len(new_uids) == len(deduped)

        # 再写一次，应全部识别为已存在
        again = store.upsert_many(deduped)
        assert not again, "重复入库没有被识别"
        print("  · 增量识别：重复写入 0 篇新增（正确）")

        allp = store.load_all()
        meta = build.build_site(allp, root=tmp, errors=[], new_uids=new_uids)
        print(f"  · 建站：共 {meta['total']} 篇，时间戳 {meta['updated_at']}")

        for name in ("data.js", "demo.js", "papers.json", "insights.json", "meta.json"):
            f = tmp / "data" / name
            assert f.exists(), f"缺少输出文件 {name}"
            assert f.stat().st_size > 0, f"{name} 是空文件"
        print("  · 输出：data.js / demo.js / papers.json / insights.json / meta.json 均已生成")

        # 分析结果自检
        ins = json.loads((tmp / "data" / "insights.json").read_text(encoding="utf-8"))
        assert ins["hotspots"], "热点榜单为空"
        assert ins["hotspots"][0]["score"] > 0, "热点分为 0"
        assert ins["summary"]["total"] == meta["total"]
        top = ins["hotspots"][0]["zh"]
        print(f"  · 分析：热点榜首「{top}」，趋势序列 {len(ins['trends']['months'])} 个月")

        # data.js 应是合法 JS 赋值且能解析出 JSON
        raw = (tmp / "data" / "data.js").read_text(encoding="utf-8")
        payload = raw.split("window.__PM_DATA__ = ", 1)[1].rstrip().rstrip(";")
        parsed = json.loads(payload)
        assert parsed["papers"][0]["title"], "data.js 内容不完整"
        assert len(parsed["papers"][0]["topics"]) >= 1, "文献没有打上主题标签"
        print(f"  · 前端数据：data.js 可解析，含 {len(parsed['papers'])} 篇文献")

        # 打标签是否有效
        tagged = analyze.tag_paper(
            {"title": "Energy storage arbitrage in spot market clearing",
             "abstract": "battery storage market participation", "topics": []}
        )
        assert tagged, "关键词打标签失效"
        print(f"  · 打标签：样例归入 {tagged}")

        # 指标层：层级判定、标题匹配、缓存套用
        assert metrics.tier_label("T1") == "顶级期刊", "期刊层级文案异常"
        assert metrics._venue_tier("Applied Energy")[0] == "T1", "重点期刊没有定到 T1"
        assert metrics._venue_tier("Some Unknown Journal", src_type="repository")[0] == "PRE"
        assert metrics._venue_tier("Journal of Testing", impact=7.2)[0] == "T2"
        assert metrics._titles_match(
            "Virtual power plant aggregation for ancillary service markets",
            "Virtual Power Plant Aggregation for Ancillary Service Markets",
        ), "标题匹配失效"
        assert not metrics._titles_match(
            "Virtual power plant aggregation for ancillary service markets",
            "A completely different paper about weather forecasting",
        ), "标题匹配过于宽松"

        cache = {
            "version": metrics.CACHE_VERSION,
            "updated_at": "2026-09-18",
            "works": {
                "doi:10.1016/j.apenergy.2026.100001": {
                    "citations": 51,
                    "reference_count": 33,
                    "source_id": "S109565702",
                    "source_name": "Applied Energy",
                    "source_type": "journal",
                    "checked": "2026-09-18",
                }
            },
            "sources": {
                "S109565702": {
                    "name": "Applied Energy",
                    "type": "journal",
                    "impact": 15.2,
                    "h_index": 388,
                    "tier": "T1",
                    "checked": "2026-09-18",
                }
            },
        }
        probe = {
            "doi": "10.1016/j.apenergy.2026.100001",
            "title": "Electricity price forecasting with deep learning",
            "citations": 42,
        }
        assert metrics.apply_cache([probe], cache) == 1, "指标缓存没有套用"
        assert probe["citations"] == 51, "被引数没有取两者较大值"
        assert probe["reference_count"] == 33 and probe["venue_tier"] == "T1"
        analyze.enrich([probe])
        assert probe["venue_tier_label"] == "顶级期刊" and probe["heat"] >= 0, "热度计算异常"
        print(
            f"  · 指标：被引 {probe['citations']} / 参考文献 {probe['reference_count']} / "
            f"层级 {probe['venue_tier']}·{probe['venue_tier_label']} / 热度 {probe['heat']}"
        )

        # 站点选文：最新为主，同时保住高被引经典
        recent_pool = [
            {"uid": f"new-{i}", "title": f"new {i}", "topics": [],
             "date": "2026-09-01", "year": 2026, "citations": 0}
            for i in range(200)
        ]
        classic_pool = [
            {"uid": f"old-{i}", "title": f"classic {i}", "topics": [],
             "date": "2019-01-01", "year": 2019, "citations": 300 - i}
            for i in range(5)
        ]
        picked = build.select_for_site(recent_pool + classic_pool, 50)
        assert len(picked) == 50, "站点选文数量不对"
        assert any(p["uid"].startswith("old-") for p in picked), "高被引经典被挤出了站点"
        print(f"  · 选文：从 205 篇里挑 50 篇，保留 {sum(1 for p in picked if p['uid'].startswith('old-'))} 篇经典")

    finally:
        if store is not None:
            store.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("  " + "-" * 46)
    print("  √ 自检通过：整条流水线工作正常。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
