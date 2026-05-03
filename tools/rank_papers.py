"""synapse-monitor / rank_papers — score unranked papers 0–5.

Three dimensions:
  - Keyword relevance (0–3): TF match weighted by topic.priority.
  - Novelty (0–1): regex on abstract for novel/first/new SOTA/we propose/...
  - Citation velocity (0–1, optional): single Semantic Scholar lookup.

CLI:
    rank_papers.py [--no-citations] [--limit N] [--top-print K] [--delay S]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"

NOVELTY_PATTERNS = [
    r"\bnovel\b",
    r"\bfirst\b",
    r"state[- ]of[- ]the[- ]art",
    r"\bnew\s+(approach|method|framework|architecture|paradigm)\b",
    r"\bwe\s+(propose|introduce|present)\b",
    r"\boutperform(s|ing)?\b",
    r"\bsignificantly\s+(improves|outperforms)\b",
    r"\bsurpass(es|ing)?\b",
]
NOVELTY_RE = re.compile("|".join(NOVELTY_PATTERNS), flags=re.IGNORECASE)


def score_keywords(text: str, topics: list[dict]) -> tuple[float, list[str]]:
    text_l = text.lower()
    counter: Counter[str] = Counter()
    weighted = 0.0
    for t in topics:
        kw = t["keyword"].lower()
        if not kw:
            continue
        if " " in kw:
            n = text_l.count(kw)
        else:
            n = len(re.findall(rf"\b{re.escape(kw)}\b", text_l))
        if n:
            counter[t["keyword"]] += n
            weighted += n * float(t["priority"])
    if weighted <= 0:
        return 0.0, []
    capped = min(3.0, 0.6 * (weighted ** 0.6))
    return round(capped, 3), [kw for kw, _ in counter.most_common(3)]


def score_novelty(text: str) -> float:
    hits = len(NOVELTY_RE.findall(text))
    if hits == 0:
        return 0.0
    return round(min(1.0, 0.3 + 0.2 * hits), 3)


def score_citations(arxiv_id: str, client: httpx.Client) -> float:
    try:
        url = SEMANTIC_SCHOLAR_API.format(arxiv_id=arxiv_id)
        r = client.get(url, params={"fields": "citationCount"}, timeout=10.0)
        if r.status_code != 200:
            return 0.0
        data = r.json()
        n = int(data.get("citationCount") or 0)
    except Exception:
        return 0.0
    if n <= 0:
        return 0.0
    if n >= 50:
        return 1.0
    if n >= 10:
        return 0.7
    if n >= 3:
        return 0.4
    return 0.2


def main() -> None:
    p = argparse.ArgumentParser(description="Rank unranked papers.")
    p.add_argument("--no-citations", action="store_true")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--top-print", type=int, default=10)
    p.add_argument("--delay", type=float, default=0.4)
    args = p.parse_args()

    db.init_db()
    topics = db.list_topics(active_only=True)
    if not topics:
        print("No topics. Run tools/watchlist.py seed-defaults first.", file=sys.stderr)
        sys.exit(1)

    todo = db.unranked_papers()[: args.limit]
    if not todo:
        print("No unranked papers.")
        return

    print(f"Ranking {len(todo)} papers...")
    headers = {"User-Agent": "synapse/1.0"}
    with httpx.Client(headers=headers) as client:
        for i, paper in enumerate(todo, 1):
            text = f"{paper['title']}. {paper['abstract']}"
            kw_score, top_kws = score_keywords(text, topics)
            nov_score = score_novelty(paper["abstract"])
            cit_score = 0.0
            if not args.no_citations:
                cit_score = score_citations(paper["arxiv_id"], client)
                time.sleep(args.delay)
            total = round(kw_score + nov_score + cit_score, 3)
            db.write_ranking(paper["arxiv_id"], total, kw_score, nov_score,
                             cit_score, top_kws)
            if i % 25 == 0 or i == len(todo):
                print(f"  ranked {i}/{len(todo)}")

    print("\nTop papers after ranking:")
    for r in db.top_ranked_papers(args.top_print):
        print(f"  [{r['base_score']:.2f}+ir={r['industry_relevance']:.2f}={r['combined_score']:.2f}] "
              f"{r['arxiv_id']} — {r['title'][:90]}")


if __name__ == "__main__":
    main()
