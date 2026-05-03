"""synapse-pulse / rank_news — score unranked news items 0–3.

Two dimensions:
  - AI-relevance (0–2): keyword TF over watchlist + AI-specific vocabulary.
  - Recency (0–1): full credit <24 h; half <72 h; small <168 h; zero beyond.

CLI:
    rank_news.py [--limit N] [--top-print K]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import db  # noqa: E402

AI_BONUS_TERMS = [
    "ai", "ml", "llm", "gpt", "model", "neural", "transformer",
    "agent", "agi", "openai", "anthropic", "deepmind", "google ai",
    "diffusion", "fine-tune", "fine tuning", "rlhf", "inference",
    "foundation model", "multimodal", "vision", "claude", "gemini",
    "chatgpt", "nvidia", "training",
]


def score_ai_relevance(text: str, watchlist_keywords: list[str]) -> float:
    text_l = text.lower()
    weighted = 0.0
    for kw in watchlist_keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        if " " in kw_l:
            n = text_l.count(kw_l)
        else:
            n = len(re.findall(rf"\b{re.escape(kw_l)}\b", text_l))
        weighted += n * 1.0
    for term in AI_BONUS_TERMS:
        if " " in term:
            n = text_l.count(term)
        else:
            n = len(re.findall(rf"\b{re.escape(term)}\b", text_l))
        weighted += n * 0.5
    if weighted <= 0:
        return 0.0
    return round(min(2.0, 0.5 * (weighted ** 0.6)), 3)


def score_recency(published_at: str) -> float:
    if not published_at:
        return 0.3
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.3
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.5
    if age_hours <= 168:
        return 0.2
    return 0.0


def main() -> None:
    p = argparse.ArgumentParser(description="Rank unranked news items.")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--top-print", type=int, default=10)
    args = p.parse_args()

    db.init_db()
    topics = db.list_topics(active_only=True)
    keywords = sorted({t["keyword"] for t in topics})
    todo = db.unranked_news()[: args.limit]
    if not todo:
        print("No unranked news.")
        return

    print(f"Ranking {len(todo)} news items...")
    for n in todo:
        text = f"{n['title']}. {n['summary']}"
        ai = score_ai_relevance(text, keywords)
        rec = score_recency(n["published_at"])
        total = round(ai + rec, 3)
        db.write_news_ranking(n["id"], total, ai, rec)

    print("\nTop news items:")
    for r in db.top_news(args.top_print, since_days=3, min_score=0.5):
        print(f"  [{r['total_score']:.2f}] {r['source']:25.25}  {r['title'][:90]}")


if __name__ == "__main__":
    main()
