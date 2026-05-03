# Synapse Pulse — Industry News Aggregator

## Description
Pulls AI/ML industry news from heterogeneous sources via direct HTTP — no browser, no auth, no API keys. Three source kinds:

| Kind | Mechanism | Default sources |
|------|-----------|-----------------|
| `hn`     | HackerNews Firebase API + AI-keyword title filter | top stories |
| `reddit` | Subreddit RSS                                     | r/MachineLearning, r/LocalLLaMA, r/artificial |
| `rss`    | Any Atom/RSS feed                                 | TechCrunch AI, VentureBeat AI, The Verge front page, MIT Tech Review |

Each item gets a 0–3 score = **AI-relevance** (0–2, keyword TF over watchlist + AI vocabulary) + **recency** (0–1, full credit <24 h). Items below ≈1.0 don't propagate to cross-referencing — keeps the daily report tight.

Trigger when the user says "fetch AI news", "what's the AI industry talking about", "show industry news", or as the second stage of `/synapse-briefing`.

## Tools

| Tool | Reads | Writes |
|------|-------|--------|
| `tools/fetch_news.py` | `news_sources` (from watchlist) | `news_items` |
| `tools/rank_news.py`  | unranked `news_items`, `topics` | `news_rankings` |

## Step 1 — Fetch

```bash
python3 tools/fetch_news.py --limit 200 --per-source 40 --hn-scan 80
```

For each active source:
- **HN**: pulls `topstories.json`, fetches the first 80 items, keeps only those whose title matches the AI vocabulary regex.
- **Reddit / RSS**: feedparser-parses the feed and ingests up to `--per-source` items.

Dedupes by URL. Reports per-source insert counts.

## Step 2 — Rank

```bash
python3 tools/rank_news.py
```

Scores every unranked item, prints the top 10. Below score 0.5 is treated as noise downstream.

## Direct triggers (vs. via `/synapse-briefing`)

Use this skill standalone when the user wants the news view alone:
- "what's the AI industry talking about today?"
- "give me top HN AI stories"
- "fetch news now"

For the full daily digest with paper bridges and opportunities, route through `/synapse-briefing`.

## Output Style for "show industry news"

```
📰 Industry Pulse — [DATE]

[hackernews]
  • [score 2.1] Title — https://...
[reddit]
  • [score 1.8] Title — https://...
[rss / TechCrunch — AI]
  • [score 1.5] Title — https://...
```

Use `db.top_news(k=15, since_days=2, min_score=0.8)` to fetch the items.

## Failure Modes
- **HN API throttled / down**: skip source, continue with the rest.
- **Single RSS feed broken**: skip, log to stderr; user can disable the source via watchlist.
- **All sources empty**: report it back; means recently seeded sources or genuinely quiet news day.
- **Reddit 403**: usually IP-level rate limiting from a previous bad-UA run. Wait a few minutes and retry. The script ships a Mozilla-style UA that Reddit accepts.
