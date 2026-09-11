# -*- coding: utf-8 -*-
"""
本地文献库（SQLite）。

两个作用：
1. 去重与累积 —— 每天的抓取结果并入同一个库，历史不会丢；
2. 增量识别 —— 记录 first_seen，从而算出"今天新增了哪些文献"。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    uid            TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    abstract       TEXT,
    authors        TEXT,
    venue          TEXT,
    year           INTEGER,
    date           TEXT,
    url            TEXT,
    pdf_url        TEXT,
    doi            TEXT,
    citations      INTEGER DEFAULT 0,
    source         TEXT,
    source_name    TEXT,
    type           TEXT,
    is_oa          INTEGER DEFAULT 0,
    topics         TEXT,
    journal_weight REAL DEFAULT 0,
    language       TEXT,
    first_seen     TEXT,
    last_seen      TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_date    ON papers(date DESC);
CREATE INDEX IF NOT EXISTS idx_papers_seen    ON papers(first_seen);
CREATE INDEX IF NOT EXISTS idx_papers_cited   ON papers(citations DESC);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   TEXT,
    finished  TEXT,
    fetched   INTEGER,
    added     INTEGER,
    errors    TEXT
);
"""

FIELDS = [
    "uid", "title", "abstract", "authors", "venue", "year", "date", "url",
    "pdf_url", "doi", "citations", "source", "source_name", "type", "is_oa",
    "topics", "journal_weight", "language",
]


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------ 写入

    def upsert_many(self, papers: list[dict]) -> set[str]:
        """写入/更新文献，返回本次"首次见到"的 uid 集合。"""
        today = date.today().isoformat()
        new_uids: set[str] = set()
        cur = self.conn.cursor()

        for p in papers:
            uid = p.get("uid")
            if not uid:
                continue

            exists = cur.execute(
                "SELECT 1 FROM papers WHERE uid = ?", (uid,)
            ).fetchone()
            if not exists:
                new_uids.add(uid)
                cur.execute(
                    f"INSERT INTO papers ({','.join(FIELDS)}, first_seen, last_seen) "
                    f"VALUES ({','.join('?' * len(FIELDS))}, ?, ?)",
                    (*[_serialize(p.get(f)) for f in FIELDS], today, today),
                )
            else:
                # 更新会变化的字段，保留 first_seen
                cur.execute(
                    """UPDATE papers SET
                         abstract       = COALESCE(NULLIF(?, ''), abstract),
                         citations      = MAX(COALESCE(?, 0), citations),
                         venue          = COALESCE(NULLIF(?, ''), venue),
                         url            = COALESCE(NULLIF(?, ''), url),
                         pdf_url        = COALESCE(NULLIF(?, ''), pdf_url),
                         doi            = COALESCE(NULLIF(?, ''), doi),
                         topics         = ?,
                         journal_weight = MAX(COALESCE(?, 0), journal_weight),
                         is_oa          = MAX(COALESCE(?, 0), is_oa),
                         last_seen      = ?
                       WHERE uid = ?""",
                    (
                        p.get("abstract") or "",
                        p.get("citations") or 0,
                        p.get("venue") or "",
                        p.get("url") or "",
                        p.get("pdf_url") or "",
                        p.get("doi") or "",
                        json.dumps(p.get("topics") or [], ensure_ascii=False),
                        p.get("journal_weight") or 0,
                        1 if p.get("is_oa") else 0,
                        today,
                        uid,
                    ),
                )

        self.conn.commit()
        return new_uids

    def log_run(self, started: str, finished: str, fetched: int, added: int, errors: list) -> None:
        self.conn.execute(
            "INSERT INTO runs (started, finished, fetched, added, errors) VALUES (?,?,?,?,?)",
            (started, finished, fetched, added, json.dumps(errors, ensure_ascii=False)),
        )
        self.conn.commit()

    # ------------------------------------------------------------ 读取

    def load_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM papers ORDER BY date DESC, citations DESC"
        ).fetchall()
        return [self._row_to_paper(r) for r in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    def last_run(self):
        row = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _row_to_paper(row) -> dict:
        d = dict(row)
        d["authors"] = _deserialize_list(d.get("authors"))
        d["topics"] = _deserialize_list(d.get("topics"))
        d["is_oa"] = bool(d.get("is_oa"))
        return d

    def close(self) -> None:
        self.conn.close()


def _serialize(value):
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _deserialize_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
