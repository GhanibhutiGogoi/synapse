"""synapse-synth / opportunities — read/write helper for buildable-idea synthesis.

CLI:
    opportunities.py list [--top-k 5] [--min-sim 0.15]   # JSON queue for the model
    opportunities.py write < ideas.json                  # persist a JSON list
    opportunities.py show [--since-days 1] [--limit 20]  # print stored opportunities
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402


def cmd_list(args: argparse.Namespace) -> None:
    db.init_db()
    candidates = db.papers_with_strong_links(
        k=args.top_k, min_sim=args.min_sim, since_days=args.since_days
    )
    industry_focus = db.get_pref("industry_focus", "")

    out: list[dict] = []
    for c in candidates:
        summary = db.get_summary(c["arxiv_id"])
        links = db.get_links_for_paper(c["arxiv_id"], min_sim=args.min_sim)[:3]
        out.append({
            "arxiv_id": c["arxiv_id"],
            "title": c["title"],
            "abstract": c["abstract"],
            "score": c["combined_score"],
            "industry_relevance": c["industry_relevance"],
            "summary": {
                "problem": summary["problem"] if summary else None,
                "method": summary["method"] if summary else None,
                "contributions": summary["contributions"] if summary else None,
                "results": summary["results"] if summary else None,
            },
            "linked_news": [
                {
                    "news_id": l["news_id"],
                    "source": l["source"],
                    "title": l["title"],
                    "url": l["url"],
                    "summary": l["summary"][:400],
                    "similarity": round(l["similarity"], 3),
                    "published_at": l["published_at"],
                }
                for l in links
            ],
        })

    payload = {
        "industry_focus": industry_focus,
        "candidates": out,
    }
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_write(_: argparse.Namespace) -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print("Empty stdin.", file=sys.stderr)
        sys.exit(1)
    items = json.loads(raw)
    if not isinstance(items, list):
        print("Expected JSON list.", file=sys.stderr)
        sys.exit(1)
    saved = 0
    for it in items:
        try:
            db.write_opportunity(
                paper_id=it["arxiv_id"],
                news_ids=it.get("news_ids", []),
                idea=it["idea"],
                rationale=it["rationale"],
                paper_insight=it["paper_insight"],
                market_signal=it["market_signal"],
            )
            saved += 1
        except KeyError as e:
            print(f"  ! skipping item missing key {e}", file=sys.stderr)
    print(f"Saved {saved} opportunities.")


def cmd_show(args: argparse.Namespace) -> None:
    rows = db.recent_opportunities(since_days=args.since_days, limit=args.limit)
    if not rows:
        print("(no opportunities in window)")
        return
    for r in rows:
        print(f"\n💡  {r['idea']}")
        print(f"     ↳ rationale:      {r['rationale']}")
        print(f"     ↳ paper insight:  {r['paper_insight']}")
        print(f"     ↳ market signal:  {r['market_signal']}")
        print(f"     ↳ paper:          {r['arxiv_id']} — {r['paper_title'][:80]}")


def main() -> None:
    p = argparse.ArgumentParser(description="Read/write opportunity synthesis.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("list")
    a.add_argument("--top-k", type=int, default=5)
    a.add_argument("--min-sim", type=float, default=0.15)
    a.add_argument("--since-days", type=int, default=2)
    a.set_defaults(func=cmd_list)

    sub.add_parser("write").set_defaults(func=cmd_write)

    s = sub.add_parser("show")
    s.add_argument("--since-days", type=int, default=1)
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_show)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
