# Synapse Watchlist Manager

## Description
Manages the configuration that drives every other Synapse skill: research keywords + arXiv categories to monitor, news sources to pull from, and the user's industry-focus preference (biases the opportunity synthesis stage).

All operations write to a single shared SQLite DB at `data/arxiv.db`. No networking; pure config management.

## When to Use
- "add 'diffusion models' to my watchlist"
- "show me my topics" / "what am I monitoring?"
- "remove transformers from the watchlist"
- "set priority of LLM to 3"
- "list news sources" / "add a news source"
- "set my industry focus to healthcare and dev tools"
- "seed the defaults" (first-time setup)

## Tool

The tool is a single Python CLI. Run from the project root (`/opt/openclaw/synapse/` or wherever it was installed):

```
python3 tools/watchlist.py <command> [args]
```

## Commands

### Seed defaults (first-time setup)
```bash
python3 tools/watchlist.py seed-defaults
```
Populates 7 keywords × 6 arXiv categories (= 42 topic rows) and 8 default news sources covering HackerNews, Reddit (r/MachineLearning, r/LocalLLaMA, r/artificial), TechCrunch AI, VentureBeat AI, The Verge front page, and MIT Tech Review.

### Topics
```bash
python3 tools/watchlist.py list-topics
python3 tools/watchlist.py add-topic "diffusion models" --category cs.CV --priority 2
python3 tools/watchlist.py remove-topic "diffusion models" --category cs.CV
python3 tools/watchlist.py set-priority "LLM" 3
```
Priority weights the keyword in the ranker: `kw_score = sum(matches × priority)` capped at 3.

### News sources
```bash
python3 tools/watchlist.py list-sources
python3 tools/watchlist.py add-source "Ars Technica AI" "https://arstechnica.com/ai/feed/" --kind rss
python3 tools/watchlist.py remove-source "https://arstechnica.com/ai/feed/"
```
`--kind` ∈ `hn` (HackerNews API), `reddit` (subreddit RSS), `rss` (any Atom/RSS feed).

### Industry focus (biases opportunity synthesis)
```bash
python3 tools/watchlist.py set-industry-focus "healthcare, developer tools, fintech"
python3 tools/watchlist.py show-prefs
```
Empty by default. When set, `synapse-synth` weights opportunity ideas toward these verticals.

## Output Style for "show watchlist"

```
📚 Watchlist (N topics, M unique keywords):

  • AI → cs.LG(p1), cs.AI(p1), cs.NE(p1), ...
  • LLM → cs.CL(p2), cs.LG(p2), ...

📰 News sources (K active):
  [hn]
    • HackerNews — top stories
  [reddit]
    • r/MachineLearning, r/LocalLLaMA, r/artificial
  [rss]
    • TechCrunch AI, VentureBeat AI, The Verge — front page, MIT Tech Review

🎯 Industry focus: <value or "(none set)">
```

## Notes
- `remove-*` is soft-delete (sets `active=0`); rows preserved in DB for history.
- This skill does NOT do any networking — purely config management.
- Run `seed-defaults` first if the DB is empty; everything downstream depends on it.
