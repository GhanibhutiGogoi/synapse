# Synapse Briefing — Daily Digest & Entry Point

## Description
This is the **entry-point skill** of the Synapse agent. The user-facing experience routes through here. It calls the other four skills in sequence, then renders a 4-section markdown report:

1. 🔬 **Top Research Today** — top-K ranked papers (with industry-relevance) + top 3 expanded with structured summaries.
2. 📰 **Industry Pulse** — top AI news from the last 24–48 h, grouped by source.
3. 🔗 **Research ↔ Industry Bridges** — papers that have strong news echoes; shows which research is "in conversation" with the market.
4. 💡 **Buildable Opportunities** — concrete project ideas that pair a paper insight with a market signal.

Trigger phrases: "synapse briefing", "morning report", "daily digest", "what's new on arxiv", "what's new in AI today", or the 9 AM cron.

## Daily Pipeline (the 9 AM Run)

When triggered (manually or by cron), follow these steps **in order**, run from the project root (`/opt/openclaw/synapse/`).

```bash
# 0. Open a run record
RUN_ID=$(python3 -c "from data.db import start_run; print(start_run())")
echo "run_id=$RUN_ID"

# 1. Fetch new papers (synapse-monitor)
python3 tools/fetch_papers.py --limit 200 --days 2

# 2. Fetch news (synapse-pulse) — independent of step 1
python3 tools/fetch_news.py --limit 200 --per-source 40

# 3. Rank papers
python3 tools/rank_papers.py

# 4. Rank news
python3 tools/rank_news.py

# 5. Cross-reference papers ↔ news (synapse-synth)
python3 tools/cross_ref.py --paper-days 2 --news-days 14 --top-papers 40 --min-sim 0.10
```

### 5b. Summarize top-10 papers — LLM step

You (the model) must:
1. Run `python3 tools/summarize_papers.py list --top-k 10` to get the queue.
2. For each paper in the JSON, read its abstract and emit a `{arxiv_id, problem, method, contributions, results}` object as described in **synapse-monitor.md** (see "Quality rules").
3. Pipe the JSON array into `python3 tools/summarize_papers.py write`.

### 5c. Synthesize opportunities — LLM step

You (the model) must:
1. Run `python3 tools/opportunities.py list --top-k 5` to get the queue (already includes the summaries from 5b plus the linked news).
2. For each candidate, produce one opportunity object per the rubric in **synapse-synth.md**. Reject ideas that fail any of the 5 quality rules.
3. Pipe the JSON array into `python3 tools/opportunities.py write`.

### 6. Format and post the report

```bash
python3 tools/briefing.py report \
    --top-papers 10 --top-news 12 --top-opps 5

# Close the run (optionally with counts)
python3 -c "from data.db import end_run; end_run($RUN_ID, status='completed')"
```

The report is markdown — paste/render it directly into the OpenClaw chat.

### Counts for the run record

If you want accurate counts on the row:
```bash
python3 -c "from data.db import end_run; end_run($RUN_ID, papers_fetched=$P, news_fetched=$N, opportunities_generated=$O, status='completed')"
```
where `$P`, `$N`, `$O` are parsed from earlier stdout.

## Direct Triggers

| User says... | Run |
|---|---|
| "synapse briefing" / "morning report" / "daily digest" | Full pipeline above, render report |
| "show me today's papers" (no synthesis) | Skip 5c; render report (Opportunities will be empty) |
| "what's the AI industry talking about" | `synapse-pulse` only; render Industry Pulse section |
| "show me papers about graph neural networks from this week" | `python3 tools/briefing.py query "graph neural networks" --since-days 7` |
| "show last 7 runs" / "did the cron run today" | `python3 tools/briefing.py status --limit 7` |
| "show me yesterday's opportunities" | `python3 tools/opportunities.py show --since-days 1` |

## Cron Prompt (paste into OpenClaw cron at 9 AM local time)

```
Run /synapse-briefing for today's research-and-opportunity digest.

Working directory: /opt/openclaw/synapse

Steps:
1. Open a run id (data/db.py start_run)
2. tools/fetch_papers.py — pull last 48h of papers
3. tools/fetch_news.py — pull AI news
4. tools/rank_papers.py — score papers
5. tools/rank_news.py — score news
6. tools/cross_ref.py — link papers ↔ news, set industry_relevance
7. tools/summarize_papers.py list --top-k 10 → extract problem/method/contributions/results per paper → write back via summarize_papers.py write
8. tools/opportunities.py list --top-k 5 → produce one buildable-idea JSON per candidate per the rubric in synapse-synth.md → write back via opportunities.py write
9. tools/briefing.py report — render and post the 4-section markdown digest
10. Close the run id

If any step fails (network, source down), continue with the remainder and note the failure in a "Caveats" footnote at the end of the report.
```

## Output Sample

```markdown
# 📡 Synapse — 2026-05-04
_Daily AI research × industry digest_

_10 top papers · 12 top news items · window: 2 d papers / 2 d news_

## 🔬  Top Research Today

| # | score | ir | title | keywords |
|---|------:|---:|-------|----------|
| 1 | 4.91 | 1.60 | [Efficient ...](https://arxiv.org/abs/2401.xxxxx) | LLM, transformers, AI |
...

#### Top 3 — expanded
### [Efficient ...](https://arxiv.org/abs/2401.xxxxx)
_Authors_  ·  `cs.LG`  ·  score **4.91**  ·  industry-relevance **1.60**

- **Problem:** ...
- **Method:** ...
- **Contributions:** ...
- **Results:** ...

## 📰  Industry Pulse
**TechCrunch — AI**
- [2.1] [Headline](https://...)
...

## 🔗  Research ↔ Industry Bridges
**Efficient ...**  · ir **1.60**
  - sim 0.31 · [Headline](https://...) _(TechCrunch — AI)_
  - sim 0.22 · [Headline](https://...) _(HackerNews — top stories)_

## 💡  Buildable Opportunities

**1. Ship a desktop SQL copilot that runs the 70 M tabular model on CPU ...**
  - _Why now:_ Mid-market analysts need NL data tools but balk at cloud LLMs.
  - _Paper insight (2404.xxxxx):_ 70 M-param model matches 7 B on tabular reasoning.
  - _Market signal:_ Two analytics-startup rounds this week emphasized "no-cloud AI".
...
```

## Failure Modes
- **Empty Top Research**: `synapse-monitor` failed — investigate `fetch_papers.py` output before re-running.
- **Empty Industry Pulse**: `synapse-pulse` failed for the day — likely rate-limited; report still useful with empty Section 2.
- **Empty Bridges + Opportunities**: cross-ref found nothing above threshold — lower `--min-sim` or accept that today is a research-only day.
- **Stale data (no new run for >24 h)**: check the cron registration; `python3 tools/briefing.py status --limit 7` shows recent runs.
