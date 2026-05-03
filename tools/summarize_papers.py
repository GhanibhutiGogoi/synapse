"""synapse-monitor / summarize_papers — read/write helper for paper summaries.

CLI:
    summarize_papers.py list [--top-k 10]            # JSON of top-K papers needing summary
    summarize_papers.py write < summaries.json       # persist a JSON list of summaries
    summarize_papers.py show <arxiv_id>              # show stored summary for a paper
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
    rows = db.papers_needing_summary(args.top_k)
    out = []
    for r in rows:
        out.append({
            "arxiv_id": r["arxiv_id"],
            "title": r["title"],
            "abstract": r["abstract"],
            "categories": r["categories"],
            "score": r["total_score"],
        })
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_write(_: argparse.Namespace) -> None:
    payload = sys.stdin.read().strip()
    if not payload:
        print("Empty stdin. Pipe JSON list of summaries.", file=sys.stderr)
        sys.exit(1)
    items = json.loads(payload)
    if not isinstance(items, list):
        print("Expected JSON list.", file=sys.stderr)
        sys.exit(1)
    saved = 0
    for it in items:
        try:
            db.write_summary(
                it["arxiv_id"],
                it.get("problem", ""),
                it.get("method", ""),
                it.get("contributions", ""),
                it.get("results", ""),
            )
            saved += 1
        except KeyError as e:
            print(f"  ! skipping item missing key {e}", file=sys.stderr)
    print(f"Saved {saved} summaries.")


def cmd_show(args: argparse.Namespace) -> None:
    s = db.get_summary(args.arxiv_id)
    if not s:
        print(f"No summary for {args.arxiv_id}.", file=sys.stderr)
        sys.exit(1)
    json.dump(s, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Read/write paper summaries.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("list")
    a.add_argument("--top-k", type=int, default=10)
    a.set_defaults(func=cmd_list)

    sub.add_parser("write").set_defaults(func=cmd_write)

    s = sub.add_parser("show")
    s.add_argument("arxiv_id")
    s.set_defaults(func=cmd_show)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
