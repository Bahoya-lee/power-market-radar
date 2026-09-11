# -*- coding: utf-8 -*-
"""
建站环节：把文献库 + 分析结果导出成前端可直接读取的静态数据。

同时写两份：
  data/*.json —— 体积小、便于其它程序消费；
  data/data.js —— 挂到 window.__PM_DATA__，这样直接双击 index.html
                  （file:// 协议）也能看到数据，不需要起本地服务器。
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from . import analyze, config


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_site(
    papers: list[dict],
    *,
    root: Path,
    errors: list[dict] | None = None,
    new_uids: set[str] | None = None,
    stats: dict | None = None,
) -> dict:
    """生成站点数据文件，返回本次的 meta。"""
    errors = errors or []
    new_uids = new_uids or set()

    papers = analyze.enrich(papers)
    papers.sort(key=lambda p: (p.get("date") or "", p.get("citations") or 0), reverse=True)
    papers = papers[: config.MAX_PAPERS_IN_SITE]

    for p in papers:
        if p.get("abstract") and len(p["abstract"]) > config.ABSTRACT_KEEP:
            p["abstract"] = p["abstract"][: config.ABSTRACT_KEEP] + "…"
        p["is_new"] = p.get("uid") in new_uids
        p["first_seen"] = p.get("first_seen") or ""

    trends = analyze.topic_trends(papers)
    hot = analyze.hotspots(papers, trends)
    rising = analyze.rising_terms(papers)
    summary = analyze.summarize(papers, new_uids)

    now = datetime.now()
    meta = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "updated_date": now.strftime("%Y-%m-%d"),
        "generated_ts": int(now.timestamp() * 1000),
        "source_count": len({p.get("source") for p in papers if p.get("source")}),
        "errors": errors[:60],
        "error_count": len(errors),
        "source_status": (stats or {}).get("source_status", []),
        "stats": stats or {},
    }
    meta.update(
        {
            "total": summary["total"],
            "recent30": summary["recent30"],
            "new_today": summary["new_today"],
            "oa": summary["oa"],
        }
    )

    insights = {
        "hotspots": hot,
        "trends": trends,
        "rising": rising,
        "summary": summary,
    }

    payload = {
        "meta": meta,
        "insights": insights,
        "papers": papers,
        "topics": [
            {"id": t["id"], "zh": t["zh"], "color": t["color"], "keywords": t["keywords"]}
            for t in config.TOPICS
        ],
    }

    data_dir = root / "data"
    _write(data_dir / "papers.json", _dumps(papers))
    _write(data_dir / "insights.json", _dumps(insights))
    _write(data_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    _write(
        data_dir / "data.js",
        "/* 由 crawler/build.py 自动生成，请勿手工修改 */\n"
        f"window.__PM_DATA__ = {_dumps(payload)};\n",
    )

    _write_demo(root, papers, payload)
    return meta


# ---------------------------------------------------------------- 演示数据

_DEMO_TOPIC_TITLES = {
    "spot_market": ["高比例新能源下现货市场出清机制改进", "节点电价与阻塞管理的协同优化"],
    "price_forecast": ["基于深度学习的日前电价概率预测", "极端天气下的电价尖峰识别"],
    "demand_response": ["工业负荷需求响应的市场化激励设计", "柔性负荷参与现货市场的聚合建模"],
    "ancillary": ["调频辅助服务市场的出清与结算机制", "储能参与调频市场的容量配置"],
    "carbon": ["电碳耦合市场的协同出清框架", "绿证与碳市场的价格传导分析"],
    "vpp": ["虚拟电厂多资源聚合的竞标策略", "分布式资源聚合商的市场参与路径"],
    "p2p": ["社区级点对点电能交易的机制设计", "微网内部交易的定价与结算"],
    "storage": ["储能参与能量与调频市场的联合套利", "共享储能的容量租赁定价"],
    "ai": ["强化学习在发电侧报价中的应用", "大语言模型辅助电力市场规则解析"],
    "renewable": ["新能源消纳的市场机制与政策协同", "风电不确定性下的市场合约设计"],
}


def _write_demo(root: Path, real_papers: list[dict], payload: dict) -> None:
    """生成一份明显标注为"演示"的数据，让用户首次打开就能看到界面效果。

    所有演示条目标题均以【演示】开头、摘要中写明非真实文献，
    避免与真实检索结果混淆。
    """
    rng = random.Random(20260101)
    today = date.today()
    venues = list(config.TOP_JOURNALS.keys())
    authors = [
        "Zhang, Wei", "Li, Ming", "Wang, Hui", "Chen, Yu", "Liu, Jie",
        "Yang, Fan", "Zhao, Lei", "Sun, Qian", "Xu, Hao", "Guo, Rui",
    ]

    demo: list[dict] = []
    for topic in config.TOPICS:
        titles = _DEMO_TOPIC_TITLES.get(topic["id"]) or [
            f"{topic['zh']}研究进展",
            f"{topic['zh']}的机制设计与实证",
        ]
        for i, base in enumerate(titles):
            offset = rng.randint(5, 300)
            d = today - timedelta(days=offset)
            venue = rng.choice(venues[:16])
            citations = rng.randint(0, 90)
            demo.append(
                {
                    "uid": f"demo-{topic['id']}-{i}",
                    "title": f"【演示】{base}",
                    "abstract": (
                        "【演示数据，非真实文献】本条记录仅用于预览网站界面效果。"
                        "请双击「一键更新.bat」抓取真实文献后，本演示数据会自动隐藏。"
                    ),
                    "authors": rng.sample(authors, k=3),
                    "venue": venue.title(),
                    "year": d.year,
                    "date": d.isoformat(),
                    "url": "https://openalex.org",
                    "pdf_url": "",
                    "doi": "",
                    "citations": citations,
                    "cite_per_year": round(citations / max(1, today.year - d.year + 1), 2),
                    "source": "demo",
                    "source_name": "演示",
                    "type": "article",
                    "is_oa": rng.random() > 0.5,
                    "topics": [topic["id"]],
                    "topic_primary": topic["id"],
                    "journal_weight": config.TOP_JOURNALS.get(venue, 0.0),
                    "is_top_venue": config.TOP_JOURNALS.get(venue, 0.0) >= 0.85,
                    "language": "zh",
                    "is_new": False,
                    "first_seen": d.isoformat(),
                    "recency_days": offset,
                }
            )

    # 演示数据的热点/趋势必须基于演示文献本身重算，
    # 否则界面里的排行和趋势图会全是 0。
    demo = analyze.enrich(demo)
    demo_trends = analyze.topic_trends(demo)
    insights = {
        "hotspots": analyze.hotspots(demo, demo_trends),
        "trends": demo_trends,
        "rising": analyze.rising_terms(demo),
        "summary": analyze.summarize(demo, set()),
    }
    demo_payload = {
        "meta": {
            **payload["meta"],
            "is_demo": True,
            "total": len(demo),
            "recent30": 0,
            "new_today": 0,
            "updated_at": "尚未抓取真实数据",
        },
        "insights": insights,
        "papers": demo,
        "topics": payload["topics"],
    }

    _write(
        root / "data" / "demo.js",
        "/* 演示数据，仅用于预览界面，不是真实文献 */\n"
        f"window.__PM_DEMO__ = {_dumps(demo_payload)};\n",
    )
