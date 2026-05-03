# How Synapse Works

A user-facing explanation of what Synapse does, how the five skills fit together, and what knobs you can turn. For install instructions see [GUIDANCE.md](GUIDANCE.md). For the system architecture, see [AGENT.md](AGENT.md).

---

## The one-line story

> Every morning at 9 AM, Synapse fetches new arXiv papers, fetches AI industry news, scores both, finds where research and market are talking about the same thing, and synthesizes concrete project ideas you could actually build.

The thing that makes it different from a generic paper digest is **step 4** — the bridge from research to market — and **step 5** — turning that bridge into buildable opportunities.

---

## What you'll see at 9 AM

A markdown report with four sections, posted into your OpenClaw chat:

```
# 📡 Synapse — 2026-05-04
_Daily AI research × industry digest_

## 🔬 Top Research Today
| # | score | ir   | title                                  | keywords     |
|---|------:|-----:|----------------------------------------|--------------|
| 1 | 4.91  | 1.60 | Efficient Tabular LLM …                | LLM, AI      |
| 2 | 4.77  | 1.27 | Strategy-Space Evolution for Algo …    | LLM          |
…

#### Top 3 — expanded
### Efficient Tabular LLM …
- Problem: Tabular reasoning at production scale needs huge models that …
- Method: A 70 M-parameter token-mixing model trained on …
- Contributions: Matches GPT-4 on TabFact while running on a laptop CPU.
- Results: 87.3 % accuracy at 6× lower latency.

## 📰 Industry Pulse
**TechCrunch — AI**
- [2.10] Anthropic launches Cowork, a desktop agent that works …
- [1.97] Pentagon inks deals with Nvidia, Microsoft, AWS …

**Reddit r/artificial**
- [2.74] AI agents hiring other AI agents
…

## 🔗 Research ↔ Industry Bridges
**Efficient Tabular LLM …**  · ir 1.60
  - sim 0.31 · "Anthropic launches Cowork…" (TechCrunch — AI)
  - sim 0.22 · "Local-first analytics is back" (HN top stories)
…

## 💡 Buildable Opportunities

**1. Ship a desktop SQL copilot that runs the 70 M model on CPU …**
  - Why now: Mid-market analysts need NL data tools but balk at cloud LLMs.
  - Paper insight: 70 M tabular model matches 7 B general LLM on TabFact.
  - Market signal: Two analytics-startup rounds this week emphasized "no-cloud AI".

**2. Browser extension that runs the SeaEvo-style strategy search …**
  - Why now: …
…
```

The two scores per paper:
- **score** = keyword relevance (0–3) + novelty signal (0–1) + citation velocity (0–1) → 0–5
- **ir** (industry relevance, 0–2) = how strongly today's news is talking about this paper's topic. Adds to the score so industry-aligned research rises in the ranking.

---

## The five skills, plain English

```
┌──────────────────────────────────────────────────────────────────────┐
│                    /synapse-briefing  (entry point)                  │
│  reads everything; renders the 4-section daily report                │
└──────────────────────┬───────────────────────────────────────────────┘
                       │  orchestrates
       ┌───────────────┼─────────────────────────────┐
       ▼               ▼                             ▼
┌───────────────┐ ┌───────────────┐  ┌──────────────────────────────┐
│ /synapse-     │ │ /synapse-     │  │ /synapse-synth               │
│  monitor      │ │  pulse        │  │  (the creative core)         │
│               │ │               │  │                              │
│  fetch papers │ │  fetch news   │  │  cross_ref:                  │
│  rank papers  │ │  rank news    │  │   link papers ↔ news         │
│  summarize    │ │               │  │   compute industry-relevance │
│  top-K        │ │               │  │                              │
│               │ │               │  │  opportunities:              │
│               │ │               │  │   model generates buildable  │
│               │ │               │  │   ideas (paper + news → idea)│
└───────────────┘ └───────────────┘  └──────────────────────────────┘
       └───────────────┴─────────────────────────────┘
                       │  all share
                       ▼
              ┌─────────────────┐
              │  data/arxiv.db  │       ← single SQLite file, 11 tables
              │  (shared layer) │
              └─────────────────┘
                       ▲
              ┌─────────────────┐
              │ /synapse-       │       Independent skill — manages config:
              │  watchlist      │       topics, news sources, industry focus
              └─────────────────┘
```

### `/synapse-watchlist` — config
Your "what am I tracking?" file. Stores:
- **Topics**: keywords × arXiv categories (e.g. *LLM × cs.LG*, *transformers × cs.CL*) with priority weights.
- **News sources**: HackerNews, Reddit subreddits, RSS feeds with `kind` ∈ {hn, reddit, rss}.
- **Industry focus**: free-text pref like *"healthcare, developer tools"* — biases opportunity ideas toward those verticals.

Run once at install (`seed-defaults`) and edit when your interests shift. The seeded defaults already cover AI / deep learning / neural networks / transformers / LLM / GNNs / representation learning across `cs.LG, cs.AI, cs.NE, cs.CV, cs.CL, stat.ML`.

### `/synapse-monitor` — papers in
Three Python scripts:
1. **fetch_papers.py** — hits the arXiv API once per topic+category (e.g. 42 queries on default seed), with a 3-second polite delay between requests. Dedupes by arXiv ID, stores last 48 h.
2. **rank_papers.py** — scores each paper 0–5:
   - 0–3 keyword relevance (how often watchlist keywords appear in the title+abstract, weighted by topic priority).
   - 0–1 novelty signal (regex hits for *novel*, *first*, *new state-of-the-art*, *we propose*, *outperforms*, etc.).
   - 0–1 citation velocity (one Semantic Scholar lookup per paper; soft-fails if API down).
3. **summarize_papers.py** — read/write helper. The skill prompt instructs the OpenClaw model to read each top-K abstract and emit `{problem, method, contributions, results}` JSON. The script stores it. This is the only place a model call is needed in the daily run.

### `/synapse-pulse` — news in
Two scripts, three source kinds:
- `hn` — pulls HackerNews top stories list, filters titles to AI vocabulary.
- `reddit` — RSS from r/MachineLearning, r/LocalLLaMA, r/artificial.
- `rss` — TechCrunch AI, VentureBeat AI, The Verge front page, MIT Tech Review.

Items get a 0–3 score = AI-relevance (0–2, keyword TF) + recency (0–1, full credit <24 h, half <72 h, zero past a week). Items below 0.5 are treated as noise.

### `/synapse-synth` — the bridge + the ideas
This is the unique-value-add module. Two sub-tools:

**cross_ref.py** — for each top-ranked paper, compute cosine similarity between the paper's `(title + abstract)` and each recent news item's `(title + summary)` over a TF vector of "interesting" tokens (alphanum, length ≥3, not stopword). Keep up to 5 strongest links per paper above a similarity threshold (default 0.10). Compute the paper's `industry_relevance` (0–2) from `(num strong links, max linked-news score)`. This score is added to the paper's daily ranking total — so research that's *also* in the news rises.

**opportunities.py** — for the top-K papers that have at least one strong news link, the OpenClaw model generates one buildable idea each. The output JSON has four fields:
- `idea` — 1–2 sentence concrete buildable product/tool/service
- `rationale` — why this is the right thing to build *right now*
- `paper_insight` — which capability from the paper enables it
- `market_signal` — which signal from the linked news makes it timely

The skill enforces a 5-rule rubric (must be buildable in <3 mo, must use the paper, must use the news, must be specific not vague, must not reinvent existing products). Ideas that fail any rule are rejected before being written.

### `/synapse-briefing` — the daily entry point
Calls everything above in order, then renders the 4-section report. Also handles follow-up queries:
- `briefing.py query "graph neural networks" --since-days 7` — search stored papers + opportunities by keyword
- `briefing.py status --limit 7` — show last 7 daily runs

---

## The data flow on a typical morning

```
09:00  cron fires → /synapse-briefing kicks off
09:00  fetch_papers.py    → arXiv API → ~50–200 new papers in `papers` table
09:01  fetch_news.py      → 8 sources → ~30–80 new items in `news_items`
09:01  rank_papers.py     → keyword + novelty (+ citation) → `paper_rankings`
09:02  rank_news.py       → ai_score + recency             → `news_rankings`
09:02  cross_ref.py       → cosine over token vectors      → `paper_news_links`
                                                           → updates `papers.industry_relevance`
09:03  summarize_papers.py list  → JSON of top-10 papers
       (OpenClaw model)          → reads abstracts, emits structured summaries
       summarize_papers.py write → `paper_summaries`
09:04  opportunities.py list     → JSON of top-5 paper-news bundles
       (OpenClaw model)          → applies the 5-rule rubric, generates ideas
       opportunities.py write    → `opportunities`
09:05  briefing.py report        → renders + posts the 4-section markdown
```

Total wall time per run: ~3–6 minutes, dominated by polite API delays in fetch.

---

## DB schema (the shared layer)

11 tables in `data/arxiv.db`:

| Table | Holds | Used by |
|---|---|---|
| `topics` | watchlist keywords × arXiv categories | watchlist, monitor, pulse |
| `news_sources` | HN / reddit / rss endpoints | watchlist, pulse |
| `prefs` | industry_focus and other key/value config | watchlist, synth |
| `papers` | arXiv papers + derived `industry_relevance` | monitor, synth, briefing |
| `paper_rankings` | kw + novelty + citation scores | monitor, briefing |
| `paper_summaries` | LLM problem/method/contributions/results | monitor, briefing |
| `news_items` | fetched news rows | pulse, synth, briefing |
| `news_rankings` | ai_score + recency_score | pulse, synth, briefing |
| `paper_news_links` | paper ↔ news similarity edges | synth, briefing |
| `opportunities` | buildable ideas tied to (paper_id, news_ids) | synth, briefing |
| `runs` | one row per daily run | briefing |

You can poke around any time:
```bash
sqlite3 data/arxiv.db
> .tables
> SELECT COUNT(*) FROM papers;
> SELECT * FROM opportunities ORDER BY generated_at DESC LIMIT 5;
> .quit
```

---

## Knobs you can turn

### Change what you monitor

```
"Add 'diffusion models' to my watchlist with priority 2"
"Add 'state space models' to my watchlist for cs.LG"
"Set priority of LLM to 3"
"Remove neural networks from my watchlist"
```

### Change what news you read

```
"Add HuggingFace blog as a news source: https://huggingface.co/blog/feed.xml, kind rss"
"Remove the Reddit r/artificial source"
"Show me my news sources"
```

### Bias the opportunity ideas toward your industry

```
"Set my industry focus to fintech and developer tools"
"Show my prefs"
"Clear my industry focus"   (you'd run: tools/watchlist.py set-industry-focus "")
```

### Change ranking thresholds (advanced — edit args in the cron prompt)

- Want more paper-news bridges in the report? Lower `tools/cross_ref.py --min-sim` from 0.10 to 0.07.
- Want fewer but stronger opportunities? Lower `tools/opportunities.py list --top-k` from 5 to 3.
- Want more papers fetched per run? Raise `tools/fetch_papers.py --limit` from 200 to 400.

---

## Manual overrides — handy commands

Run from the project root (`/opt/openclaw/synapse/`).

```bash
# Force a fresh run right now (manually, not via OpenClaw)
python3 tools/fetch_papers.py --limit 100
python3 tools/fetch_news.py
python3 tools/rank_papers.py
python3 tools/rank_news.py
python3 tools/cross_ref.py
python3 tools/briefing.py report   # renders without LLM-driven sections

# Re-rank everything (e.g. after changing keyword priorities)
sqlite3 data/arxiv.db "DELETE FROM paper_rankings"
python3 tools/rank_papers.py

# Re-do cross-references with a tighter threshold
sqlite3 data/arxiv.db "DELETE FROM paper_news_links; UPDATE papers SET industry_relevance=0"
python3 tools/cross_ref.py --min-sim 0.15

# Inspect a specific paper
python3 tools/summarize_papers.py show 2401.12345

# Read all of yesterday's opportunities
python3 tools/opportunities.py show --since-days 1

# Last 7 days at a glance
python3 tools/briefing.py status --limit 7

# Search across stored data
python3 tools/briefing.py query "graph neural networks" --since-days 14
```

---

## Why these design choices

### Why no browser?
The arXiv API gives you full paper metadata + abstracts via a single HTTP call. HN, Reddit, and major AI publications all expose RSS. There's nothing the browser skill could do here that direct HTTP can't, and the browser adds latency, fragility (CAPTCHAs, login state), and memory cost.

### Why a flat SQLite file instead of a real DB?
The whole project is a single user's personal pipeline — no concurrent writers, no multi-machine reads, no backups beyond `cp data/arxiv.db ~/backup.db`. SQLite handles 7 days × ~80 papers × ~50 news items × ~5 opportunities trivially. The flat file is also nice for the project report — you can `pandas.read_sql` it and produce the visualizations directly.

### Why five skills instead of one big one?
Each skill is independently testable and has its own SKILL prompt with its own quality rubric. The opportunity-synthesis quality rubric (the 5 rules) is its own first-class artifact in `synapse-synth.md` rather than buried in a 500-line briefing skill. If you decide tomorrow you want to swap the keyword-based cross-reference for embedding-based similarity, you replace one file.

### Why the LLM steps are 5b/5c, not orchestrated by Python?
The model has to actually *read* abstracts and generate ideas — those are inherent LLM workloads, not algorithmic ones. Keeping them as explicit steps in the skill prompt (rather than burying them in a Python `subprocess` call to a CLI) keeps OpenClaw in control of context, retry, and rate limiting. The Python tools are reduced to "give me the queue" and "save what I produced" — which is exactly what they should be.

### What's deliberately not in scope
- **Embedding-based similarity** for cross-ref. Catches subtler conceptual links than keyword overlap, but adds a `sentence-transformers` dependency (~500 MB) and CPU cost. Listed as the obvious next step in the project report's Analysis section.
- **PDF full-text** ingestion. Only abstracts are used. Full-text would lift summary quality but multiply bandwidth.
- **Slack / email delivery**. Briefing renders into the OpenClaw chat. Adding Slack later only needs a webhook URL.
- **A web dashboard**. SQLite is queryable directly during the 7-day test window.

---

## Mapping to the course rubric (individual report, 3 pages)

If you're using this for the *Daily arXiv Research Briefing Agent* topic in the Spring 2026 Social Network Analysis course, here's where each rubric section lives:

| Rubric section | Source |
|---|---|
| Functionality | The 5 skills, their I/O, the daily-pipeline diagram |
| References | arXiv API, Semantic Scholar API, HN API, prior work on academic recommendation (SPECTER, SciNCL) and tech-trend mining |
| Results | 7-day test: papers/news/opportunities counts per day, qualitative sample of best + worst opportunities |
| Analysis | What works (keyword overlap finds obvious bridges); what doesn't (subtle conceptual links missed without embeddings); industry-relevance lift on rankings |
| Visualization | Workflow diagram (5 skills + DB), bar chart of papers/news/opportunities per day, sample paper-news bipartite graph |

`runs`, `papers`, `news_items`, `paper_news_links`, and `opportunities` together give you all the raw material for those sections after the 7-day window.
