"""synapse-briefing / briefing — orchestrator + 4-section report formatter + query mode.

CLI:
    briefing.py report                     # build the daily 4-section markdown digest
    briefing.py status                     # quick run summary (last 7 days)
    briefing.py query <terms> --since-days 7  # follow-up search across stored data
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402


def section_header(title: str, emoji: str) -> str:
    return f"\n## {emoji}  {title}\n"


def fmt_paper_block(p: dict) -> str:
    s = db.get_summary(p["arxiv_id"])
    arxiv_url = f"https://arxiv.org/abs/{p['arxiv_id']}"
    head = (
        f"### [{p['title'].strip()}]({arxiv_url})\n"
        f"_{p.get('authors', '')[:200]}_  ·  `{p.get('categories', '').split()[0] if p.get('categories') else ''}`  "
        f"·  score **{p.get('combined_score', p.get('total_score', 0)):.2f}**  "
        f"·  industry-relevance **{p.get('industry_relevance', 0):.2f}**\n\n"
    )
    if s:
        body = (
            f"- **Problem:** {s.get('problem') or 'not stated'}\n"
            f"- **Method:** {s.get('method') or 'not stated'}\n"
            f"- **Contributions:** {s.get('contributions') or 'not stated'}\n"
            f"- **Results:** {s.get('results') or 'not stated'}\n"
        )
    else:
        body = f"- _(no summary yet — abstract follows)_\n  > {p['abstract'][:400].strip()}...\n"
    return head + body


def cmd_report(args: argparse.Namespace) -> None:
    db.init_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    top_papers = db.top_ranked_papers(args.top_papers, since_days=args.paper_days)
    top_news = db.top_news(args.top_news, since_days=args.news_days, min_score=0.8)

    out: list[str] = []
    out.append(f"# 📡 Synapse — {today}\n")
    out.append("_Daily AI research × industry digest_\n\n")
    out.append(
        f"_{len(top_papers)} top papers · {len(top_news)} top news items · "
        f"window: {args.paper_days} d papers / {args.news_days} d news_\n"
    )

    out.append(section_header("Top Research Today", "🔬"))
    if not top_papers:
        out.append("\n_(no ranked papers in the window — try running `/synapse-monitor` first)_\n")
    else:
        out.append("\n| # | score | ir | title | keywords |\n|---|------:|---:|-------|----------|\n")
        for i, p in enumerate(top_papers, 1):
            kws = ""
            if p.get("top_keywords"):
                try:
                    kws = ", ".join(json.loads(p["top_keywords"])[:3])
                except Exception:
                    pass
            score = p.get("combined_score") or p.get("base_score") or 0
            arxiv_url = f"https://arxiv.org/abs/{p['arxiv_id']}"
            short_title = p["title"].strip().replace("|", "\\|")[:80]
            out.append(
                f"| {i} | {score:.2f} | {p.get('industry_relevance', 0):.2f} | "
                f"[{short_title}]({arxiv_url}) | {kws} |\n"
            )
        out.append("\n#### Top 3 — expanded\n\n")
        for p in top_papers[:3]:
            out.append(fmt_paper_block(p))
            out.append("\n")

    out.append(section_header("Industry Pulse", "📰"))
    if not top_news:
        out.append("\n_(no industry news in the window — sources may be quiet today)_\n")
    else:
        by_source: dict[str, list[dict]] = {}
        for n in top_news:
            by_source.setdefault(n["source"], []).append(n)
        for source, items in by_source.items():
            out.append(f"\n**{source}**\n")
            for n in items[:5]:
                out.append(f"- [{n['total_score']:.2f}] [{n['title'][:120]}]({n['url']})\n")

    out.append(section_header("Research ↔ Industry Bridges", "🔗"))
    bridge_papers = [p for p in top_papers if p.get("industry_relevance", 0) > 0]
    if not bridge_papers:
        out.append("\n_(no paper found a strong news echo today)_\n")
    else:
        for p in bridge_papers[:5]:
            arxiv_url = f"https://arxiv.org/abs/{p['arxiv_id']}"
            links = db.get_links_for_paper(p["arxiv_id"], min_sim=0.10)[:3]
            if not links:
                continue
            out.append(f"\n**[{p['title'].strip()[:90]}]({arxiv_url})**  "
                       f"· ir **{p['industry_relevance']:.2f}**\n")
            for l in links:
                out.append(f"  - sim {l['similarity']:.2f} · "
                           f"[{l['title'][:120]}]({l['url']}) "
                           f"_({l['source']})_\n")

    out.append(section_header("Buildable Opportunities", "💡"))
    opps = db.recent_opportunities(since_days=args.paper_days, limit=args.top_opps)
    if not opps:
        out.append("\n_(no opportunities synthesized yet — run synapse-synth's "
                   "`opportunities list` then the model writes them back)_\n")
    else:
        for i, o in enumerate(opps, 1):
            arxiv_url = f"https://arxiv.org/abs/{o['arxiv_id']}"
            out.append(
                f"\n**{i}. {o['idea']}**\n"
                f"  - _Why now:_ {o['rationale']}\n"
                f"  - _Paper insight ([{o['arxiv_id']}]({arxiv_url})):_ {o['paper_insight']}\n"
                f"  - _Market signal:_ {o['market_signal']}\n"
            )

    out.append("\n---\n_Follow up: ask `show me papers about <topic> from this week` "
               "or `show me yesterday's opportunities`._\n")

    print("".join(out))


def cmd_status(args: argparse.Namespace) -> None:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT id, started_at, ended_at, papers_fetched, news_fetched,
                      opportunities_generated, status
               FROM runs ORDER BY started_at DESC LIMIT ?""",
            (args.limit,),
        ).fetchall()
    if not rows:
        print("(no runs yet)")
        return
    print(f"{'id':<5} {'started_at':<22} {'status':<12} "
          f"{'papers':>7} {'news':>5} {'opps':>5}")
    for r in rows:
        print(f"{r['id']:<5} {r['started_at']:<22} {r['status']:<12} "
              f"{r['papers_fetched']:>7} {r['news_fetched']:>5} "
              f"{r['opportunities_generated']:>5}")


def cmd_query(args: argparse.Namespace) -> None:
    q = " ".join(args.terms).strip()
    if not q:
        print("Provide query terms.", file=sys.stderr)
        sys.exit(1)
    db.init_db()
    papers = db.search_papers(q, since_days=args.since_days, limit=args.limit)
    print(f"# Search: '{q}' (last {args.since_days} d)\n")
    print(f"## Papers ({len(papers)})\n")
    if not papers:
        print("_(no matches)_\n")
    else:
        for p in papers:
            arxiv_url = f"https://arxiv.org/abs/{p['arxiv_id']}"
            print(f"- [{p.get('total_score') or 0:.2f}] [{p['title'].strip()[:120]}]({arxiv_url})")
    opps = db.recent_opportunities(since_days=args.since_days, limit=50)
    related = [o for o in opps if q.lower() in (o["idea"] + o["rationale"]
                                                + o["paper_insight"]
                                                + o["market_signal"]).lower()]
    if related:
        print(f"\n## Related opportunities ({len(related)})\n")
        for o in related:
            print(f"- 💡 {o['idea']}  _(paper {o['arxiv_id']})_")


def main() -> None:
    p = argparse.ArgumentParser(description="Synapse briefing report + queries.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report")
    r.add_argument("--top-papers", type=int, default=10)
    r.add_argument("--top-news", type=int, default=12)
    r.add_argument("--top-opps", type=int, default=5)
    r.add_argument("--paper-days", type=int, default=4)
    r.add_argument("--news-days", type=int, default=2)
    r.set_defaults(func=cmd_report)

    s = sub.add_parser("status")
    s.add_argument("--limit", type=int, default=7)
    s.set_defaults(func=cmd_status)

    q = sub.add_parser("query")
    q.add_argument("terms", nargs="+")
    q.add_argument("--since-days", type=int, default=7)
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(func=cmd_query)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
