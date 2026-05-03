# Synapse

A daily AI research → industry → opportunity briefing agent for OpenClaw. Five skills, one shared SQLite database, no browser.

## What it does

Every day at 9 AM (or whenever `/synapse-briefing` is triggered):

1. Pulls new papers from the **arXiv API** matching your watchlist of keywords × categories.
2. Pulls fresh AI **industry news** from HackerNews, Reddit (r/MachineLearning, r/LocalLLaMA, r/artificial), TechCrunch AI, VentureBeat AI, The Verge front page, MIT Tech Review.
3. Ranks papers (keyword + novelty + citation velocity) and news (AI-relevance + recency).
4. **Cross-references** them — finds papers whose topics are echoing in the market right now, lifting them in the daily ranking.
5. Extracts structured `{problem, method, contributions, results}` summaries for the top papers.
6. Synthesizes **buildable opportunities** — concrete project ideas that pair a paper insight with a market signal, biased toward the user's `industry_focus` pref.
7. Renders a 4-section markdown digest: Top Research · Industry Pulse · Research ↔ Industry Bridges · Buildable Opportunities.

## Single Invariant

Skills never import each other. They communicate only through `data/arxiv.db` via the helpers in `data/db.py`. A skill can be deleted, rewritten, or run standalone without breaking the others. (Same pattern as the PokerBot reference agent's shared data layer.)

## Layout

```
synapse/                          ← project root (zip → install on OpenClaw VM)
├── AGENT.md                      ← this file
├── GUIDANCE.md                   ← unzip → install → register → cron walkthrough
├── SETUP.md                      ← prerequisites
├── requirements.txt              ← feedparser + httpx
├── skills/                       ← OpenClaw flat-skill directory
│   ├── synapse-watchlist.md
│   ├── synapse-monitor.md
│   ├── synapse-pulse.md
│   ├── synapse-synth.md
│   └── synapse-briefing.md
├── tools/                        ← Python tool scripts (called by skill prompts)
│   ├── watchlist.py
│   ├── fetch_papers.py
│   ├── rank_papers.py
│   ├── summarize_papers.py
│   ├── fetch_news.py
│   ├── rank_news.py
│   ├── cross_ref.py
│   ├── opportunities.py
│   └── briefing.py
└── data/
    ├── db.py                     ← shared SQLite schema + helpers
    └── arxiv.db                  ← created at first run
```

## Skills

Five flat `.md` skill files in `skills/`. Trigger via slash-command or natural-language phrase — full rules in each skill file.

### `/synapse-briefing` — Entry point + 4-section daily report
Orchestrates the daily pipeline, formats the report, handles follow-up queries.
**Trigger**: "synapse briefing", "morning report", "daily digest", "what's new on arxiv", or 9 AM cron.

### `/synapse-watchlist` — Config (topics, categories, news sources, industry focus)
Manages the configuration that drives every other skill. No networking.
**Trigger**: "add topic", "show watchlist", "list news sources", "set my industry focus", "seed defaults".

### `/synapse-monitor` — Paper fetch + rank + summarize
Three sub-tools (`fetch_papers.py`, `rank_papers.py`, `summarize_papers.py`) producing the paper side of the daily run.
**Trigger**: "fetch new papers", "rank papers", "summarize top papers". Also internal stage 1 of `/synapse-briefing`.

### `/synapse-pulse` — Industry news fetch + rank
HN top-stories (filtered to AI), Reddit RSS, TechCrunch, VentureBeat, The Verge, MIT Tech Review. Pure HTTP; no auth, no browser.
**Trigger**: "fetch AI news", "what's the AI industry talking about". Also internal stage 2 of `/synapse-briefing`.

### `/synapse-synth` — The creative core
Cross-references papers ↔ news, computes `industry_relevance` per paper, and synthesizes buildable opportunities. The unique-value-add module.
**Trigger**: "what can I build from today's papers", "find opportunities", "link papers to news". Also internal stage 3 of `/synapse-briefing`.

## Call Hierarchy

```
/synapse-briefing  (entry point)
    ├── synapse-monitor.fetch_papers
    ├── synapse-pulse.fetch_news
    ├── synapse-monitor.rank_papers
    ├── synapse-pulse.rank_news
    ├── synapse-synth.cross_ref       ← writes paper_news_links + papers.industry_relevance
    ├── synapse-monitor.summarize     ← LLM extraction step
    ├── synapse-synth.opportunities   ← LLM synthesis step
    └── synapse-briefing.report       ← format + post

/synapse-watchlist is independently invokable for config edits.
Each tool can also be run directly for testing or partial digests.
```

## Quick API

Every operation is a Python script under `tools/`. Run from the project root. No daemon, no FastAPI, no MCP server.

| Command | Purpose |
|---|---|
| `python3 tools/watchlist.py seed-defaults` | First-time setup |
| `python3 tools/watchlist.py list-topics` | Show watchlist |
| `python3 tools/fetch_papers.py` | Pull new papers |
| `python3 tools/fetch_news.py` | Pull news |
| `python3 tools/rank_papers.py` | Rank papers |
| `python3 tools/rank_news.py` | Rank news |
| `python3 tools/cross_ref.py` | Link papers ↔ news |
| `python3 tools/briefing.py report` | Format daily digest |
| `python3 tools/briefing.py status` | Recent run history |
| `python3 tools/briefing.py query <terms>` | Follow-up search |

## Why no browser

The user's prior LinkedIn tracker depended on the OpenClaw browser skill to scrape profiles. Academic and news content doesn't need that complexity:

- **arXiv** has a clean Atom-XML API at `https://export.arxiv.org/api/query`.
- **HackerNews** has a Firebase JSON API.
- **Reddit subreddits** expose RSS at `<subreddit>/.rss`.
- **TechCrunch / VentureBeat / The Verge / MIT Tech Review** all expose Atom/RSS feeds.

`feedparser` + `httpx` are the only third-party deps. Everything else is stdlib.

## See also

- [GUIDANCE.md](GUIDANCE.md) — install / unzip / register / cron instructions for the OpenClaw operator.
- [SETUP.md](SETUP.md) — prerequisites (python 3.10+, pip).
