# Synapse Synth — Research × Industry Bridge

## Description
The unique-value-add module of Synapse. It does two things:

1. **Cross-reference**: For each top-ranked paper from the last 48 h, finds news items from the last 14 days whose title+summary overlap meaningfully with the paper's title+abstract. Produces `paper_news_links` rows + a derived `papers.industry_relevance` score (0–2) added to the paper's daily ranking total.

2. **Opportunity synthesis**: For each paper that has at least one strong news link, produces a structured `{idea, rationale, paper_insight, market_signal}` JSON object — a concrete buildable product idea where the paper supplies the *technical enabler* and the news supplies the *market signal*.

Trigger when the user says "what can I build from today's papers", "find opportunities", "link papers to news", "show me yesterday's opportunities", or as the third stage of `/synapse-briefing`.

This is what distinguishes Synapse from a generic paper digest: it closes the loop from research → industry context → buildable idea.

## Tools

| Tool | Reads | Writes |
|------|-------|--------|
| `tools/cross_ref.py`     | top recent ranked papers, recent ranked news | `paper_news_links`, `papers.industry_relevance` |
| `tools/opportunities.py` | `papers_with_strong_links` + summaries + linked news | `opportunities` |

## Step 1 — Cross-reference

```bash
python3 tools/cross_ref.py \
    --paper-days 2 --news-days 14 --top-papers 40 --min-sim 0.10
```

For each paper, computes cosine similarity over a TF-vector of "interesting" tokens (alphanum, length ≥3, not stopword). Stores up to 5 strongest links per paper above `--min-sim`. Computes `industry_relevance` ∈ [0, 2] from `(num strong links, max linked-news score)` — papers with multiple recent strong news echoes get a higher score, lifting them in the next ranking round.

## Step 2 — Opportunity synthesis (LLM-driven)

This is where the model does the creative work. The script is just a queue + persistence helper.

### 2a — Get the queue
```bash
python3 tools/opportunities.py list --top-k 5 --min-sim 0.15
```

Emits JSON of the form:
```json
{
  "industry_focus": "healthcare, developer tools",
  "candidates": [
    {
      "arxiv_id": "2401.12345",
      "title": "Efficient ...",
      "abstract": "...",
      "score": 4.7,
      "industry_relevance": 1.6,
      "summary": {"problem": "...", "method": "...", "contributions": "...", "results": "..."},
      "linked_news": [
        {"source": "TechCrunch — AI", "title": "...", "url": "...", "summary": "...", "similarity": 0.31, ...}
      ]
    }
  ]
}
```

### 2b — Generate opportunities

For each candidate, produce **one** opportunity object. Output a single JSON array containing all opportunities (one per candidate) on stdout.

Each object must look exactly like this:
```json
{
  "arxiv_id": "2401.12345",
  "news_ids": [42, 47],
  "idea": "<1–2 sentence concrete buildable product/tool/service>",
  "rationale": "<1 sentence: WHY this is the right thing to build right now>",
  "paper_insight": "<1 sentence: which specific capability from the paper enables this>",
  "market_signal": "<1 sentence: which signal from the linked news makes this timely>"
}
```

### Quality rubric — the bar for an opportunity

Reject yourself before producing it if any of the following are true:

1. **Not buildable in <3 months by a small team.** Anything that requires a frontier-lab–scale data set or budget is out. Anything that's "let's research X" is out — the user wants products/tools/services, not paper ideas.
2. **Idea doesn't actually use the paper's contribution.** If you could write the same idea by reading only the news headline, the paper isn't load-bearing — reject.
3. **Idea ignores the market signal.** If you could write the same idea by reading only the abstract, the news isn't load-bearing — reject.
4. **Vague.** "Build an AI platform for X" is not an idea. "Build a Chrome extension that ..." or "ship a CLI that ..." or "package it as a Slack bot for ..." is an idea.
5. **Reinvents an existing product.** If the news article is already announcing a similar product, your idea is a derivative; pivot to a niche the announcement leaves open.

If `industry_focus` in the input is non-empty, bias your candidate ideas toward those verticals — but do not force a fit that breaks rule 2 or 3.

### Worked example (good output shape)

Input candidate (sketched): a paper on a 70 M-param model that matches a 7 B model on tabular reasoning + linked news about enterprise data-analytics startups raising rounds.

Good opportunity:
```json
{
  "arxiv_id": "2404.xxxxx",
  "news_ids": [12, 17],
  "idea": "Ship a desktop-resident SQL copilot for analysts: it ingests a CSV or SQLite file locally, the 70 M model runs on CPU, and answers tabular questions in natural language without sending data to a cloud LLM.",
  "rationale": "Mid-market analytics teams need natural-language data tools but balk at sending columns to OpenAI; a tiny on-device model that doesn't trade off accuracy unlocks them.",
  "paper_insight": "The paper shows a 70 M-parameter tabular-reasoning model matches a 7 B general LLM on TabFact and FetaQA — small enough to run on a laptop CPU.",
  "market_signal": "TechCrunch reported two analytics-startup rounds this week with messaging centered on 'private-by-default' and 'no-cloud' AI, signaling buyer demand for local inference."
}
```

Bad opportunity (would be rejected):
> "Build an AI platform for enterprise data analysis." → vague (rule 4) and doesn't anchor to either source (rules 2, 3).

### 2c — Persist

```bash
python3 tools/opportunities.py write < /tmp/ideas.json
# or inline:
echo '<json-array>' | python3 tools/opportunities.py write
```

### Inspection

```bash
python3 tools/opportunities.py show --since-days 1
```

## Direct Triggers

- "what can I build from today's papers" → run `cross_ref.py`, then `opportunities list` → LLM generation → `opportunities write`
- "show me yesterday's opportunities" → `python3 tools/opportunities.py show --since-days 1`
- "link papers to news" → `cross_ref.py`

## Failure Modes
- **No paper has a news link**: `cross_ref` writes `industry_relevance=0` for all and `opportunities list` returns empty `candidates`. Report it back; this is a thin-news day or topics that don't appear in news.
- **Top news scores all low**: lower `--min-sim` (e.g. 0.07) and re-run, or accept that today is a research-only day and skip the Opportunities section.
