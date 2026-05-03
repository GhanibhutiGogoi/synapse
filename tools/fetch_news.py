"""synapse-pulse / fetch_news — pull AI industry news from configured sources.

Sources (kind): hn (HN top-stories) | reddit (subreddit RSS) | rss (any RSS/Atom).

CLI:
    fetch_news.py [--limit N] [--per-source M] [--hn-scan K]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402

USER_AGENT = (
    "Mozilla/5.0 (compatible; synapse/1.0; +https://github.com/your/repo) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

AI_TERMS = re.compile(
    r"\b(ai|a\.i\.|machine learning|ml|llm|gpt|"
    r"transformer|neural|deep learning|model|agent|agi|"
    r"openai|anthropic|deepmind|google\s+ai|meta\s+ai|nvidia|"
    r"diffusion|stable\s+diffusion|chatgpt|claude|gemini|"
    r"reinforcement\s+learning|rlhf|fine[- ]tun(e|ing)|inference|"
    r"foundation\s+model|multi[- ]?modal|computer\s+vision|nlp)\b",
    re.IGNORECASE,
)


def normalize_iso(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return ""


def fetch_hn(source: dict, client: httpx.Client, scan_top: int,
             insert_cap: int) -> int:
    inserted = 0
    try:
        r = client.get("https://hacker-news.firebaseio.com/v0/topstories.json",
                       timeout=20.0)
        r.raise_for_status()
        ids = r.json()[:scan_top]
    except Exception as e:
        print(f"  ! HN topstories failed: {e}", file=sys.stderr)
        return 0

    for hid in ids:
        if inserted >= insert_cap:
            break
        try:
            ir = client.get(
                f"https://hacker-news.firebaseio.com/v0/item/{hid}.json",
                timeout=15.0,
            )
            if ir.status_code != 200:
                continue
            item = ir.json() or {}
        except Exception:
            continue
        title = item.get("title") or ""
        url = item.get("url") or f"https://news.ycombinator.com/item?id={hid}"
        if not title:
            continue
        if not AI_TERMS.search(title):
            continue
        ts = item.get("time")
        published = (
            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
            if ts else ""
        )
        new_id = db.insert_news_item({
            "source": source["name"],
            "title": title.strip(),
            "url": url.strip(),
            "summary": (item.get("text") or "")[:1000],
            "published_at": published,
        })
        if new_id is not None:
            inserted += 1
        time.sleep(0.05)
    return inserted


def fetch_feed(source: dict, client: httpx.Client, insert_cap: int) -> int:
    inserted = 0
    try:
        r = client.get(source["url"], timeout=20.0,
                       headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            print(f"  ! {source['name']}: HTTP {r.status_code}", file=sys.stderr)
            return 0
        feed = feedparser.parse(r.text)
    except Exception as e:
        print(f"  ! {source['name']} failed: {e}", file=sys.stderr)
        return 0

    for e in feed.entries[: insert_cap * 3]:
        if inserted >= insert_cap:
            break
        title = (e.get("title") or "").strip()
        url = (e.get("link") or "").strip()
        if not title or not url:
            continue
        summary = (e.get("summary") or e.get("description") or "").strip()
        summary = re.sub(r"<[^>]+>", " ", summary)[:1000].strip()
        published = normalize_iso(
            e.get("published") or e.get("updated") or ""
        )
        new_id = db.insert_news_item({
            "source": source["name"],
            "title": title,
            "url": url,
            "summary": summary,
            "published_at": published,
        })
        if new_id is not None:
            inserted += 1
    return inserted


def main() -> None:
    p = argparse.ArgumentParser(description="Pull AI industry news from configured sources.")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--per-source", type=int, default=40)
    p.add_argument("--hn-scan", type=int, default=80)
    args = p.parse_args()

    db.init_db()
    sources = db.list_sources(active_only=True)
    if not sources:
        print("No news sources. Run tools/watchlist.py seed-defaults first.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching news from {len(sources)} sources...")
    total_inserted = 0
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for s in sources:
            if total_inserted >= args.limit:
                break
            cap = min(args.per_source, args.limit - total_inserted)
            if s["kind"] == "hn":
                n = fetch_hn(s, client, args.hn_scan, cap)
            else:
                n = fetch_feed(s, client, cap)
            print(f"  [{s['kind']}] {s['name']}: +{n}")
            total_inserted += n

    print(f"\n✓ Inserted {total_inserted} new news items.")


if __name__ == "__main__":
    main()
