"""synapse-synth / cross_ref — link recent papers to recent AI news.

For each top-ranked paper from the last `--paper-days`, finds news items from the
last `--news-days` whose title+summary share enough keyword content with the
paper's title+abstract. Writes paper_news_links and updates papers.industry_relevance.

CLI:
    cross_ref.py [--paper-days N] [--news-days M] [--top-papers K]
                 [--min-sim S] [--max-links-per-paper L]
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "were",
    "have", "has", "had", "but", "not", "can", "will", "would", "could", "may",
    "any", "all", "our", "their", "they", "them", "his", "her", "its", "you",
    "your", "into", "more", "than", "then", "such", "also", "been", "being",
    "where", "when", "what", "which", "who", "how", "why", "use", "uses", "used",
    "using", "based", "show", "shows", "showed", "results", "method", "methods",
    "approach", "task", "tasks", "model", "models", "data", "set", "sets", "new",
    "novel", "first", "paper", "work", "works", "experiment", "experiments",
    "performance", "compared", "compare", "across", "between", "however",
    "moreover", "furthermore", "consider", "considering", "note", "notes",
    "well", "without", "within", "make", "makes", "made", "while", "after",
    "before", "each", "every", "some", "most", "many", "few", "much", "very",
    "introduce", "propose", "present", "study", "studies", "studying",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")


def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)
            if t.lower() not in STOPWORDS]


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def industry_relevance(num_strong: int, max_recent_news_score: float) -> float:
    if num_strong == 0:
        return 0.0
    base = min(1.5, 0.4 + 0.4 * math.log2(1 + num_strong))
    bonus = min(0.5, 0.25 * max_recent_news_score)
    return round(min(2.0, base + bonus), 3)


def main() -> None:
    p = argparse.ArgumentParser(description="Link papers ↔ news and compute industry-relevance.")
    p.add_argument("--paper-days", type=int, default=4)
    p.add_argument("--news-days", type=int, default=14)
    p.add_argument("--top-papers", type=int, default=40)
    p.add_argument("--min-sim", type=float, default=0.10)
    p.add_argument("--max-links-per-paper", type=int, default=5)
    args = p.parse_args()

    db.init_db()
    papers = db.top_ranked_papers(args.top_papers, since_days=args.paper_days)
    if not papers:
        print("No recent ranked papers. Run synapse-monitor first.", file=sys.stderr)
        return

    news = db.recent_news(since_days=args.news_days, min_score=0.8)
    print(f"Cross-referencing {len(papers)} papers × {len(news)} news items...")

    if not news:
        print("No recent news. Skipping cross-ref.")
        for p_ in papers:
            db.update_industry_relevance(p_["arxiv_id"], 0.0)
        return

    news_vecs: list[tuple[dict, Counter]] = [
        (n, Counter(tokens(f"{n['title']}. {n['summary']}")))
        for n in news
    ]

    total_links = 0
    for paper in papers:
        text = f"{paper['title']}. {paper['abstract']}"
        pv = Counter(tokens(text))
        scored: list[tuple[float, dict]] = []
        for n, nv in news_vecs:
            sim = cosine(pv, nv)
            if sim >= args.min_sim:
                scored.append((sim, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        kept = scored[: args.max_links_per_paper]
        for sim, n in kept:
            db.write_paper_news_link(paper["arxiv_id"], n["id"], sim)
            total_links += 1
        max_news_score = max(
            (n.get("total_score", 0.0) for _, n in kept),
            default=0.0,
        )
        ir = industry_relevance(len(kept), max_news_score)
        db.update_industry_relevance(paper["arxiv_id"], ir)
        if kept:
            print(f"  {paper['arxiv_id'][:14]} ir={ir:.2f}  links={len(kept)}  "
                  f"top-sim={kept[0][0]:.2f}  '{paper['title'][:60]}'")

    print(f"\n✓ Wrote {total_links} paper↔news links across {len(papers)} papers.")


if __name__ == "__main__":
    main()
