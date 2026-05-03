"""synapse-monitor / fetch_papers — pull new papers from the arXiv API.

CLI:
    fetch_papers.py [--limit N] [--days D] [--max-per-query M] [--delay S]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402

ARXIV_API = "https://export.arxiv.org/api/query"
USER_AGENT = "synapse/1.0 (research-briefing-agent)"


def build_query(keyword: str, category: str) -> str:
    kw = keyword.replace('"', "")
    return f'cat:{category} AND (abs:"{kw}" OR ti:"{kw}")'


def fetch_one(query: str, max_results: int, client: httpx.Client) -> list[dict]:
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": max_results,
    }
    r = client.get(ARXIV_API, params=params, timeout=30.0)
    r.raise_for_status()
    feed = feedparser.parse(r.text)
    out = []
    for e in feed.entries:
        raw_id = (e.get("id") or "").rsplit("/", 1)[-1]
        arxiv_id = raw_id.split("v")[0] if raw_id else ""
        if not arxiv_id:
            continue
        authors = ", ".join(a.get("name", "") for a in e.get("authors", []))
        cats = " ".join(t.get("term", "") for t in e.get("tags", []))
        pdf_url = ""
        for link in e.get("links", []):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
                break
        out.append({
            "arxiv_id": arxiv_id,
            "title": (e.get("title") or "").strip().replace("\n", " "),
            "abstract": (e.get("summary") or "").strip().replace("\n", " "),
            "authors": authors,
            "categories": cats,
            "published_at": (e.get("published") or "").strip(),
            "pdf_url": pdf_url,
        })
    return out


def is_recent(published_at: str, days: int) -> bool:
    if not published_at:
        return False
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(days=days)


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch new arXiv papers per the Synapse watchlist.")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--days", type=int, default=4,
                   help="only keep papers published within last N days "
                        "(default 4 — wide enough to catch the Friday batch "
                        "when running on Mon, since arXiv has no Sat/Sun "
                        "announcements)")
    p.add_argument("--max-per-query", type=int, default=30)
    p.add_argument("--delay", type=float, default=3.0,
                   help="seconds between arXiv API requests (default 3, polite)")
    args = p.parse_args()

    db.init_db()
    topics = db.list_topics(active_only=True)
    if not topics:
        print("No active topics. Run tools/watchlist.py seed-defaults first.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching arXiv papers across {len(topics)} (keyword, category) queries"
          f" (--days {args.days})...")
    inserted = 0
    total_returned = 0
    dropped_old = 0
    dropped_dup_query = 0
    dropped_already_in_db = 0
    seen_arxiv_ids: set[str] = set()
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for i, t in enumerate(topics):
            if inserted >= args.limit:
                print(f"Hit insert cap of {args.limit}, stopping.")
                break
            q = build_query(t["keyword"], t["category"])
            try:
                entries = fetch_one(q, args.max_per_query, client)
            except Exception as exc:
                print(f"  ! query failed [{t['keyword']} / {t['category']}]: {exc}", file=sys.stderr)
                if i < len(topics) - 1:
                    time.sleep(args.delay)
                continue
            total_returned += len(entries)
            new_for_query = 0
            for entry in entries:
                aid = entry["arxiv_id"]
                if aid in seen_arxiv_ids:
                    dropped_dup_query += 1
                    continue
                seen_arxiv_ids.add(aid)
                if not is_recent(entry["published_at"], args.days):
                    dropped_old += 1
                    continue
                if db.paper_exists(aid):
                    dropped_already_in_db += 1
                    continue
                if db.insert_paper(entry):
                    inserted += 1
                    new_for_query += 1
                    if inserted >= args.limit:
                        break
            print(f"  [{i+1}/{len(topics)}] {t['keyword']} / {t['category']}: "
                  f"{len(entries)} returned, {new_for_query} new")
            if i < len(topics) - 1:
                time.sleep(args.delay)

    print(f"\n✓ Inserted {inserted} new papers.")
    print(f"  Diagnostics: returned={total_returned}, "
          f"dropped_old(>{args.days}d)={dropped_old}, "
          f"dropped_dup_in_query={dropped_dup_query}, "
          f"dropped_already_in_db={dropped_already_in_db}")
    if inserted == 0 and total_returned > 0 and dropped_old == total_returned - dropped_dup_query - dropped_already_in_db:
        print("\nNote: arXiv returned papers but ALL were older than the "
              f"--days {args.days} window. Try a wider window: --days 7")


if __name__ == "__main__":
    main()
