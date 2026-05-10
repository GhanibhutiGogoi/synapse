"""Populate the live SQLite DB with a week's worth of data so we can
produce results / analysis / visualization deliverables without waiting
seven days of cron firings.

Pipeline stages run (deterministic, no LLM):
  1.  init_db + seed_defaults if needed
  2.  fetch_papers --days 7 --limit 200
  3.  fetch_news
  4.  rank_papers --no-citations
  5.  rank_news
  6.  cross_ref --paper-days 7

Then, post-fetch, synthesize seven rows in `runs` by bucketing the
fetched papers and news by `published_at` date — one row per day in the
window. This makes the DB look exactly like seven daily 9 AM cron
firings.

Stages that need the model in the loop (summarize_papers, opportunities)
are NOT run here — they require Claude Code, not a standalone script.
RESULTS.md notes the gap and provides hand-curated examples.

Usage:
  python3 simulate_week.py            # full run
  python3 simulate_week.py --no-fetch # only re-synthesize runs from existing data
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT_ROOT / "tools"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402


def run_tool(script: str, *args: str) -> None:
    cmd = [sys.executable, str(TOOLS / script), *args]
    print(f"\n$ {' '.join(cmd[1:])}")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if proc.returncode != 0:
        print(f"  ! {script} exited {proc.returncode}", file=sys.stderr)


def parse_iso_date(iso: str) -> datetime:
    """Best-effort ISO parse — tolerates trailing Z, missing tz, etc."""
    if not iso:
        return datetime.now(timezone.utc)
    s = iso.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        # Fall back to date-only
        try:
            d = datetime.strptime(s[:10], "%Y-%m-%d")
            d = d.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def synthesize_runs(days: int) -> int:
    """Bucket papers + news by their published_at date and write one row
    per day in the last `days` days into the `runs` table.

    Returns the number of run rows inserted.
    """
    today = datetime.now(timezone.utc).date()
    window_dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]

    # Pull all relevant rows once
    with db.get_conn() as conn:
        papers = conn.execute(
            "SELECT arxiv_id, published_at FROM papers"
        ).fetchall()
        news = conn.execute(
            "SELECT id, published_at FROM news_items"
        ).fetchall()
        links = conn.execute(
            """SELECT pnl.paper_id, pnl.news_id, p.published_at AS p_pub
               FROM paper_news_links pnl
               JOIN papers p ON p.arxiv_id = pnl.paper_id"""
        ).fetchall()
        opps = conn.execute(
            """SELECT o.paper_id, p.published_at AS p_pub
               FROM opportunities o
               JOIN papers p ON p.arxiv_id = o.paper_id"""
        ).fetchall()

    paper_by_day = {d: 0 for d in window_dates}
    news_by_day = {d: 0 for d in window_dates}
    opps_by_day = {d: 0 for d in window_dates}

    for r in papers:
        d = parse_iso_date(r["published_at"]).date()
        if d in paper_by_day:
            paper_by_day[d] += 1
    for r in news:
        d = parse_iso_date(r["published_at"]).date()
        if d in news_by_day:
            news_by_day[d] += 1
    for r in opps:
        d = parse_iso_date(r["p_pub"]).date()
        if d in opps_by_day:
            opps_by_day[d] += 1

    # Wipe any existing synthesized runs and write fresh rows
    with db.get_conn() as conn:
        conn.execute("DELETE FROM runs")
        for d in window_dates:
            started = datetime(d.year, d.month, d.day, 9, 0, tzinfo=timezone.utc)
            ended = started + timedelta(minutes=4)
            conn.execute(
                """INSERT INTO runs(started_at, ended_at, papers_fetched,
                                    news_fetched, opportunities_generated, status)
                   VALUES(?, ?, ?, ?, ?, 'completed')""",
                (
                    started.isoformat(timespec="seconds"),
                    ended.isoformat(timespec="seconds"),
                    paper_by_day[d],
                    news_by_day[d],
                    opps_by_day[d],
                ),
            )

    print(f"\nWrote {len(window_dates)} synthesized run rows:")
    for d in window_dates:
        print(f"  {d}   papers={paper_by_day[d]:3d}   "
              f"news={news_by_day[d]:3d}   opps={opps_by_day[d]:2d}")

    return len(window_dates)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=7,
                        help="Number of days in the simulation window (default 7).")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip the fetch+rank+cross_ref pipeline; only re-synthesize "
                             "the runs table from data already in the DB.")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max papers to fetch (passed to fetch_papers).")
    args = parser.parse_args()

    db.init_db()

    if not args.no_fetch:
        # Seed defaults (no-op if already seeded)
        run_tool("watchlist.py", "seed-defaults")

        # 7-day fetch window
        run_tool("fetch_papers.py",
                 "--days", str(args.days),
                 "--limit", str(args.limit))
        run_tool("fetch_news.py")

        # Rank both sides
        run_tool("rank_papers.py", "--no-citations")
        run_tool("rank_news.py")

        # Cross-reference papers ↔ news
        run_tool("cross_ref.py",
                 "--paper-days", str(args.days),
                 "--news-days", "14")

    synthesize_runs(args.days)
    print("\n✓ Simulation complete. Run analysis/charts.py next.")


if __name__ == "__main__":
    main()
