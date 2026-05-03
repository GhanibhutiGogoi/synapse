"""Shared SQLite layer for the arxiv-tracker agent.

All five skills (arxiv-watchlist, arxiv-monitor, news-pulse, insight-synth,
arxiv-briefing) read and write through this module. Skills NEVER import each
other — they only share state through this DB.

Usage:
    from data.db import get_conn, init_db
    init_db()
    with get_conn() as conn:
        conn.execute("SELECT ...")

The DB file lives next to this module at data/arxiv.db unless overridden by
the ARXIV_DB_PATH environment variable.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "arxiv.db"
DB_PATH = Path(os.environ.get("ARXIV_DB_PATH", DEFAULT_DB_PATH))


SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    category TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(keyword, category)
);

CREATE TABLE IF NOT EXISTS news_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    kind TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(url)
);

CREATE TABLE IF NOT EXISTS prefs (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    authors TEXT NOT NULL,
    categories TEXT NOT NULL,
    published_at TEXT NOT NULL,
    pdf_url TEXT,
    fetched_at TEXT NOT NULL,
    industry_relevance REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS paper_rankings (
    paper_id TEXT PRIMARY KEY,
    total_score REAL NOT NULL,
    kw_score REAL NOT NULL,
    novelty_score REAL NOT NULL,
    citation_score REAL NOT NULL,
    top_keywords TEXT NOT NULL,
    ranked_at TEXT NOT NULL,
    FOREIGN KEY(paper_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS paper_summaries (
    paper_id TEXT PRIMARY KEY,
    problem TEXT,
    method TEXT,
    contributions TEXT,
    results TEXT,
    summarized_at TEXT NOT NULL,
    FOREIGN KEY(paper_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_rankings (
    news_id INTEGER PRIMARY KEY,
    total_score REAL NOT NULL,
    ai_score REAL NOT NULL,
    recency_score REAL NOT NULL,
    ranked_at TEXT NOT NULL,
    FOREIGN KEY(news_id) REFERENCES news_items(id)
);

CREATE TABLE IF NOT EXISTS paper_news_links (
    paper_id TEXT NOT NULL,
    news_id INTEGER NOT NULL,
    similarity REAL NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (paper_id, news_id),
    FOREIGN KEY(paper_id) REFERENCES papers(arxiv_id),
    FOREIGN KEY(news_id) REFERENCES news_items(id)
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    news_ids_json TEXT NOT NULL,
    idea TEXT NOT NULL,
    rationale TEXT NOT NULL,
    paper_insight TEXT NOT NULL,
    market_signal TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    FOREIGN KEY(paper_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    papers_fetched INTEGER NOT NULL DEFAULT 0,
    news_fetched INTEGER NOT NULL DEFAULT 0,
    opportunities_generated INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_at);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_paper_rankings_score ON paper_rankings(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_news_rankings_score ON news_rankings(total_score DESC);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- topics / sources / prefs ----------

def upsert_topic(keyword: str, category: str, priority: int = 1) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO topics(keyword, category, priority, active, created_at)
               VALUES(?, ?, ?, 1, ?)
               ON CONFLICT(keyword, category) DO UPDATE SET
                 priority=excluded.priority, active=1""",
            (keyword.strip(), category.strip(), priority, now_iso()),
        )


def list_topics(active_only: bool = True) -> list[dict[str, Any]]:
    with get_conn() as conn:
        q = "SELECT * FROM topics"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY priority DESC, keyword"
        return [dict(r) for r in conn.execute(q).fetchall()]


def delete_topic(keyword: str, category: str | None = None) -> int:
    with get_conn() as conn:
        if category:
            cur = conn.execute(
                "UPDATE topics SET active=0 WHERE keyword=? AND category=?",
                (keyword, category),
            )
        else:
            cur = conn.execute(
                "UPDATE topics SET active=0 WHERE keyword=?", (keyword,)
            )
        return cur.rowcount


def upsert_source(name: str, url: str, kind: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO news_sources(name, url, kind, active, created_at)
               VALUES(?, ?, ?, 1, ?)
               ON CONFLICT(url) DO UPDATE SET
                 name=excluded.name, kind=excluded.kind, active=1""",
            (name, url, kind, now_iso()),
        )


def list_sources(active_only: bool = True) -> list[dict[str, Any]]:
    with get_conn() as conn:
        q = "SELECT * FROM news_sources"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY kind, name"
        return [dict(r) for r in conn.execute(q).fetchall()]


def delete_source(url: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE news_sources SET active=0 WHERE url=?", (url,)
        )
        return cur.rowcount


def set_pref(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO prefs(key, value) VALUES(?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )


def get_pref(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


# ---------- papers ----------

def insert_paper(p: dict[str, Any]) -> bool:
    """Returns True if inserted, False if it already existed."""
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO papers(arxiv_id, title, abstract, authors,
                       categories, published_at, pdf_url, fetched_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["arxiv_id"], p["title"], p["abstract"], p["authors"],
                 p["categories"], p["published_at"], p.get("pdf_url"), now_iso()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def paper_exists(arxiv_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM papers WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        return row is not None


def unranked_papers() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.* FROM papers p
               LEFT JOIN paper_rankings r ON p.arxiv_id = r.paper_id
               WHERE r.paper_id IS NULL"""
        ).fetchall()
        return [dict(r) for r in rows]


def write_ranking(paper_id: str, total: float, kw: float, novelty: float,
                  citation: float, top_keywords: list[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO paper_rankings(paper_id, total_score, kw_score,
                   novelty_score, citation_score, top_keywords, ranked_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(paper_id) DO UPDATE SET
                 total_score=excluded.total_score,
                 kw_score=excluded.kw_score,
                 novelty_score=excluded.novelty_score,
                 citation_score=excluded.citation_score,
                 top_keywords=excluded.top_keywords,
                 ranked_at=excluded.ranked_at""",
            (paper_id, total, kw, novelty, citation,
             json.dumps(top_keywords), now_iso()),
        )


def top_ranked_papers(k: int = 10, since_days: int | None = None) -> list[dict[str, Any]]:
    """Top papers by (paper_rankings.total_score + papers.industry_relevance)."""
    with get_conn() as conn:
        q = """SELECT p.*, r.total_score AS base_score, r.top_keywords,
                      (r.total_score + p.industry_relevance) AS combined_score
               FROM papers p
               JOIN paper_rankings r ON p.arxiv_id = r.paper_id"""
        params: list[Any] = []
        if since_days is not None:
            q += " WHERE p.fetched_at >= datetime('now', ?)"
            params.append(f"-{since_days} days")
        q += " ORDER BY combined_score DESC LIMIT ?"
        params.append(k)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def write_summary(paper_id: str, problem: str, method: str,
                  contributions: str, results: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO paper_summaries(paper_id, problem, method,
                   contributions, results, summarized_at)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(paper_id) DO UPDATE SET
                 problem=excluded.problem,
                 method=excluded.method,
                 contributions=excluded.contributions,
                 results=excluded.results,
                 summarized_at=excluded.summarized_at""",
            (paper_id, problem, method, contributions, results, now_iso()),
        )


def get_summary(paper_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM paper_summaries WHERE paper_id=?", (paper_id,)
        ).fetchone()
        return dict(row) if row else None


def papers_needing_summary(k: int = 10) -> list[dict[str, Any]]:
    """Top-K ranked papers that don't yet have a summary."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.*, r.total_score
               FROM papers p
               JOIN paper_rankings r ON p.arxiv_id = r.paper_id
               LEFT JOIN paper_summaries s ON p.arxiv_id = s.paper_id
               WHERE s.paper_id IS NULL
               ORDER BY (r.total_score + p.industry_relevance) DESC
               LIMIT ?""",
            (k,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_industry_relevance(paper_id: str, score: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET industry_relevance=? WHERE arxiv_id=?",
            (score, paper_id),
        )


# ---------- news ----------

def insert_news_item(item: dict[str, Any]) -> int | None:
    """Returns the new row id, or None if duplicate."""
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO news_items(source, title, url, summary, published_at, fetched_at)
                   VALUES(?, ?, ?, ?, ?, ?)""",
                (item["source"], item["title"], item["url"],
                 item.get("summary", ""), item["published_at"], now_iso()),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def unranked_news() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT n.* FROM news_items n
               LEFT JOIN news_rankings r ON n.id = r.news_id
               WHERE r.news_id IS NULL"""
        ).fetchall()
        return [dict(r) for r in rows]


def write_news_ranking(news_id: int, total: float, ai_score: float,
                       recency: float) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO news_rankings(news_id, total_score, ai_score,
                   recency_score, ranked_at)
               VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(news_id) DO UPDATE SET
                 total_score=excluded.total_score,
                 ai_score=excluded.ai_score,
                 recency_score=excluded.recency_score,
                 ranked_at=excluded.ranked_at""",
            (news_id, total, ai_score, recency, now_iso()),
        )


def top_news(k: int = 10, since_days: int | None = 1,
             min_score: float = 1.0) -> list[dict[str, Any]]:
    with get_conn() as conn:
        q = """SELECT n.*, r.total_score
               FROM news_items n
               JOIN news_rankings r ON n.id = r.news_id
               WHERE r.total_score >= ?"""
        params: list[Any] = [min_score]
        if since_days is not None:
            q += " AND n.fetched_at >= datetime('now', ?)"
            params.append(f"-{since_days} days")
        q += " ORDER BY r.total_score DESC, n.published_at DESC LIMIT ?"
        params.append(k)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def recent_news(since_days: int = 14, min_score: float = 1.0) -> list[dict[str, Any]]:
    """All ranked news in the lookback window — used by cross_ref."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT n.*, r.total_score
               FROM news_items n
               JOIN news_rankings r ON n.id = r.news_id
               WHERE r.total_score >= ?
                 AND n.published_at >= datetime('now', ?)
               ORDER BY n.published_at DESC""",
            (min_score, f"-{since_days} days"),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- links + opportunities ----------

def write_paper_news_link(paper_id: str, news_id: int, similarity: float) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO paper_news_links(paper_id, news_id, similarity, linked_at)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(paper_id, news_id) DO UPDATE SET
                 similarity=excluded.similarity,
                 linked_at=excluded.linked_at""",
            (paper_id, news_id, similarity, now_iso()),
        )


def get_links_for_paper(paper_id: str, min_sim: float = 0.0) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT l.*, n.source, n.title, n.url, n.summary, n.published_at
               FROM paper_news_links l
               JOIN news_items n ON l.news_id = n.id
               WHERE l.paper_id = ? AND l.similarity >= ?
               ORDER BY l.similarity DESC""",
            (paper_id, min_sim),
        ).fetchall()
        return [dict(r) for r in rows]


def papers_with_strong_links(k: int = 5, min_sim: float = 0.15,
                             since_days: int = 2) -> list[dict[str, Any]]:
    """Top-K recent papers that have at least one strong news link."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.arxiv_id, p.title, p.abstract,
                      r.total_score, p.industry_relevance,
                      (r.total_score + p.industry_relevance) AS combined_score,
                      MAX(l.similarity) AS top_sim
               FROM papers p
               JOIN paper_rankings r ON p.arxiv_id = r.paper_id
               JOIN paper_news_links l ON p.arxiv_id = l.paper_id
               WHERE l.similarity >= ?
                 AND p.fetched_at >= datetime('now', ?)
               GROUP BY p.arxiv_id
               ORDER BY combined_score DESC
               LIMIT ?""",
            (min_sim, f"-{since_days} days", k),
        ).fetchall()
        return [dict(r) for r in rows]


def write_opportunity(paper_id: str, news_ids: list[int], idea: str,
                      rationale: str, paper_insight: str,
                      market_signal: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO opportunities(paper_id, news_ids_json, idea, rationale,
                   paper_insight, market_signal, generated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (paper_id, json.dumps(news_ids), idea, rationale,
             paper_insight, market_signal, now_iso()),
        )
        return cur.lastrowid or 0


def recent_opportunities(since_days: int = 1, limit: int = 20) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT o.*, p.title AS paper_title, p.arxiv_id
               FROM opportunities o
               JOIN papers p ON o.paper_id = p.arxiv_id
               WHERE o.generated_at >= datetime('now', ?)
               ORDER BY o.generated_at DESC
               LIMIT ?""",
            (f"-{since_days} days", limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- runs ----------

def start_run() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs(started_at, status) VALUES(?, 'running')",
            (now_iso(),),
        )
        return cur.lastrowid or 0


def end_run(run_id: int, papers_fetched: int = 0, news_fetched: int = 0,
            opportunities_generated: int = 0, status: str = "completed") -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE runs SET ended_at=?, papers_fetched=?, news_fetched=?,
                 opportunities_generated=?, status=? WHERE id=?""",
            (now_iso(), papers_fetched, news_fetched,
             opportunities_generated, status, run_id),
        )


def search_papers(query: str, since_days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
    """Simple LIKE-based search across title+abstract."""
    with get_conn() as conn:
        like = f"%{query.lower()}%"
        rows = conn.execute(
            """SELECT p.*, r.total_score
               FROM papers p
               LEFT JOIN paper_rankings r ON p.arxiv_id = r.paper_id
               WHERE (LOWER(p.title) LIKE ? OR LOWER(p.abstract) LIKE ?)
                 AND p.fetched_at >= datetime('now', ?)
               ORDER BY COALESCE(r.total_score, 0) DESC, p.published_at DESC
               LIMIT ?""",
            (like, like, f"-{since_days} days", limit),
        ).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")
