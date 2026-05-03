"""synapse-watchlist tool — manage research topics, news sources, and prefs.

CLI:
    watchlist.py seed-defaults
    watchlist.py list-topics
    watchlist.py add-topic <keyword> --category cs.LG [--priority 2]
    watchlist.py remove-topic <keyword> [--category cs.LG]
    watchlist.py set-priority <keyword> <priority> [--category cs.LG]
    watchlist.py list-sources
    watchlist.py add-source <name> <url> --kind {hn,reddit,rss}
    watchlist.py remove-source <url>
    watchlist.py set-industry-focus "<comma-separated>"
    watchlist.py show-prefs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Project root = parent of tools/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402


DEFAULT_KEYWORDS = [
    "AI",
    "deep learning",
    "neural networks",
    "transformers",
    "LLM",
    "graph neural networks",
    "representation learning",
]

DEFAULT_CATEGORIES = ["cs.LG", "cs.AI", "cs.NE", "cs.CV", "cs.CL", "stat.ML"]

DEFAULT_NEWS_SOURCES = [
    ("HackerNews — top stories", "https://hacker-news.firebaseio.com/v0/topstories.json", "hn"),
    ("Reddit r/MachineLearning", "https://www.reddit.com/r/MachineLearning/.rss", "reddit"),
    ("Reddit r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/.rss", "reddit"),
    ("Reddit r/artificial", "https://www.reddit.com/r/artificial/.rss", "reddit"),
    ("TechCrunch — AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "rss"),
    ("VentureBeat — AI", "https://venturebeat.com/category/ai/feed/", "rss"),
    ("The Verge — front page", "https://www.theverge.com/rss/index.xml", "rss"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/", "rss"),
]


def cmd_seed_defaults(_: argparse.Namespace) -> None:
    db.init_db()
    n_topics = 0
    for kw in DEFAULT_KEYWORDS:
        for cat in DEFAULT_CATEGORIES:
            db.upsert_topic(kw, cat, priority=2 if kw in {"LLM", "transformers"} else 1)
            n_topics += 1
    n_sources = 0
    for name, url, kind in DEFAULT_NEWS_SOURCES:
        db.upsert_source(name, url, kind)
        n_sources += 1
    print(f"Seeded {n_topics} topics across {len(DEFAULT_CATEGORIES)} categories.")
    print(f"Seeded {n_sources} news sources.")
    print('Tip: set an industry focus with: tools/watchlist.py set-industry-focus "healthcare, dev tools, fintech"')


def cmd_list_topics(_: argparse.Namespace) -> None:
    rows = db.list_topics(active_only=True)
    if not rows:
        print("No topics. Run: tools/watchlist.py seed-defaults")
        return
    by_kw: dict[str, list[str]] = {}
    for r in rows:
        by_kw.setdefault(r["keyword"], []).append(f'{r["category"]}(p{r["priority"]})')
    print(f"{len(rows)} active topic rows ({len(by_kw)} unique keywords):\n")
    for kw, cats in by_kw.items():
        print(f"  • {kw} → {', '.join(cats)}")


def cmd_add_topic(args: argparse.Namespace) -> None:
    db.init_db()
    db.upsert_topic(args.keyword, args.category, args.priority)
    print(f"Added/updated: {args.keyword} ({args.category}, priority={args.priority})")


def cmd_remove_topic(args: argparse.Namespace) -> None:
    n = db.delete_topic(args.keyword, args.category)
    if n == 0:
        print(f"No matching topic for '{args.keyword}'.", file=sys.stderr)
        sys.exit(1)
    print(f"Deactivated {n} topic row(s) for '{args.keyword}'.")


def cmd_set_priority(args: argparse.Namespace) -> None:
    if args.category:
        db.upsert_topic(args.keyword, args.category, args.priority)
        print(f"Set priority={args.priority} for {args.keyword} ({args.category})")
    else:
        rows = [r for r in db.list_topics(active_only=False) if r["keyword"] == args.keyword]
        if not rows:
            print(f"No topic '{args.keyword}'.", file=sys.stderr)
            sys.exit(1)
        for r in rows:
            db.upsert_topic(args.keyword, r["category"], args.priority)
        print(f"Set priority={args.priority} for {args.keyword} across {len(rows)} categories")


def cmd_list_sources(_: argparse.Namespace) -> None:
    rows = db.list_sources(active_only=True)
    if not rows:
        print("No news sources. Run: tools/watchlist.py seed-defaults")
        return
    by_kind: dict[str, list[str]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(f'{r["name"]} — {r["url"]}')
    for kind, items in by_kind.items():
        print(f"\n[{kind}]")
        for it in items:
            print(f"  • {it}")


def cmd_add_source(args: argparse.Namespace) -> None:
    db.init_db()
    db.upsert_source(args.name, args.url, args.kind)
    print(f"Added/updated source: {args.name} ({args.kind})")


def cmd_remove_source(args: argparse.Namespace) -> None:
    n = db.delete_source(args.url)
    if n == 0:
        print(f"No source matching {args.url}.", file=sys.stderr)
        sys.exit(1)
    print(f"Deactivated source {args.url}")


def cmd_set_industry_focus(args: argparse.Namespace) -> None:
    db.set_pref("industry_focus", args.focus.strip())
    print(f"Set industry focus = {args.focus.strip()!r}")


def cmd_show_prefs(_: argparse.Namespace) -> None:
    focus = db.get_pref("industry_focus", "")
    print(json.dumps({"industry_focus": focus}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Manage Synapse watchlist.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed-defaults").set_defaults(func=cmd_seed_defaults)
    sub.add_parser("list-topics").set_defaults(func=cmd_list_topics)

    a = sub.add_parser("add-topic")
    a.add_argument("keyword")
    a.add_argument("--category", default="cs.LG")
    a.add_argument("--priority", type=int, default=1)
    a.set_defaults(func=cmd_add_topic)

    r = sub.add_parser("remove-topic")
    r.add_argument("keyword")
    r.add_argument("--category", default=None)
    r.set_defaults(func=cmd_remove_topic)

    sp = sub.add_parser("set-priority")
    sp.add_argument("keyword")
    sp.add_argument("priority", type=int)
    sp.add_argument("--category", default=None)
    sp.set_defaults(func=cmd_set_priority)

    sub.add_parser("list-sources").set_defaults(func=cmd_list_sources)

    s = sub.add_parser("add-source")
    s.add_argument("name")
    s.add_argument("url")
    s.add_argument("--kind", choices=["hn", "reddit", "rss"], required=True)
    s.set_defaults(func=cmd_add_source)

    rs = sub.add_parser("remove-source")
    rs.add_argument("url")
    rs.set_defaults(func=cmd_remove_source)

    f = sub.add_parser("set-industry-focus")
    f.add_argument("focus", help='e.g. "healthcare, developer tools, fintech"')
    f.set_defaults(func=cmd_set_industry_focus)

    sub.add_parser("show-prefs").set_defaults(func=cmd_show_prefs)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
