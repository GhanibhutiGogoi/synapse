# Synapse Monitor — Paper Pipeline

## Description
Daily arXiv ingestion and scoring pipeline. Three sub-tools that together form the paper-side of the daily run: fetch new papers via the arXiv API, rank them on keyword + novelty + citation velocity, and produce structured `{problem, method, contributions, results}` summaries of the top papers.

Trigger when the user says "fetch new papers", "rank today's papers", "summarize the top papers", or when invoked internally as the first stage of `/synapse-briefing`'s daily 9 AM run.

## Tools

| Tool | Use when... | Reads | Writes |
|------|-------------|-------|--------|
| `tools/fetch_papers.py`     | "pull new papers" / first stage of daily run | watchlist topics | `papers` table |
| `tools/rank_papers.py`      | after fetch, "rank papers"                   | unranked papers + topics | `paper_rankings` |
| `tools/summarize_papers.py` | "summarize top papers" / per-day digest      | top-K papers (out) + LLM JSON (in) | `paper_summaries` |

All operate on the shared SQLite DB at `data/arxiv.db`. No daemon, no API server, no MCP.

## Step 1 — Fetch new papers

```bash
python3 tools/fetch_papers.py --limit 200 --days 2 --max-per-query 30
```

Hits `https://export.arxiv.org/api/query` once per `(keyword × category)` pair. Default 3 s polite delay between requests. Skips arXiv IDs already in the DB. Reports the count of new papers inserted.

## Step 2 — Rank

```bash
python3 tools/rank_papers.py
# or, if Semantic Scholar is unreachable / faster run:
python3 tools/rank_papers.py --no-citations
```

Each unranked paper gets a 0–5 total: **keyword relevance** (0–3, TF match weighted by topic priority) + **novelty signal** (0–1, regex on abstract for *novel*, *first*, *we propose*, *outperforms*, etc.) + **citation velocity** (0–1, single Semantic Scholar lookup, soft-fails if API down).

Combined daily ranking = `paper_rankings.total_score + papers.industry_relevance` (the latter is set by `synapse-synth/cross_ref` later in the pipeline).

## Step 3 — Summarize top papers (LLM-driven)

This is the **only** step where the model does the work; the script is a read/write helper.

### 3a — Get the queue
```bash
python3 tools/summarize_papers.py list --top-k 10
```
Emits a JSON array on stdout, one entry per paper:
```json
[
  {"arxiv_id": "2401.12345", "title": "...", "abstract": "...", "categories": "cs.LG cs.AI", "score": 4.21},
  ...
]
```

### 3b — Extract structured summaries
For each paper in the queue, read its `abstract` and produce this JSON:

```json
{
  "arxiv_id": "2401.12345",
  "problem": "<1 sentence: what concrete challenge is this paper attacking?>",
  "method": "<1-2 sentences: the technical approach in plain language>",
  "contributions": "<1-2 sentences: what is new vs prior work — be specific>",
  "results": "<1 sentence: headline empirical result with numbers if given>"
}
```

**Quality rules** (apply per paper):
- Problem must name the *concrete* difficulty, not "we study X". Bad: "We study graph neural networks." Good: "GNNs underperform on heterophilic graphs because message passing assumes homophily."
- Method must be readable to a CS student who has not read this paper. No jargon-dumping. Translate any acronym used.
- Contributions must be testable claims, not marketing. Bad: "a powerful new framework." Good: "a 3-layer GNN that beats GAT on 4 of 6 benchmarks while using 40% fewer parameters."
- Results must include a number if the abstract gives one. Bad: "good results." Good: "+2.1 F1 on OGB-arxiv."
- If the abstract genuinely lacks a field, write "not stated" rather than fabricating.

### 3c — Persist
Pipe the JSON array into `summarize_papers.py write`:

```bash
python3 tools/summarize_papers.py write < /tmp/summaries.json
# or inline:
echo '<json-array>' | python3 tools/summarize_papers.py write
```

The script reports how many were saved.

### Inspection
```bash
python3 tools/summarize_papers.py show 2401.12345
```

## Typical Daily Run

When invoked by `/synapse-briefing` (or 9 AM cron):
1. `fetch_papers.py` — pulls last 48 h
2. `rank_papers.py` — scores everything new
3. `summarize_papers.py list --top-k 10` → produce JSON → run the LLM extraction → `summarize_papers.py write`

The summarized output feeds the briefing's *Top Research Today* section.

## Failure Modes
- **arXiv API down or 503**: per-query failures reported, continues to next, exits cleanly. Existing data untouched.
- **Semantic Scholar 429 / down**: `rank_papers.py` falls back to `citation_score=0`; keyword + novelty scores still produce a valid ordering.
- **No papers match the watchlist**: report it back to the user — likely means the watchlist is too narrow or the daily window (`--days 2`) is wrong.
