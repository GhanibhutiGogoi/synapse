# Synapse — instructions for Claude Code

You are working inside the **Synapse** repository: a five-skill
OpenClaw agent that builds a daily *cross-referenced* research
briefing by pairing arXiv papers with AI-industry news, then
synthesising buildable opportunities. This file tells you how the
project is laid out, the invariants you must preserve, and where to
look for what.

User-facing project description: see `AGENT.md`.
End-to-end install/run guide: see `GUIDANCE.md` and `SETUP.md`.

---

## Mental model: one agent, five skills, one shared SQLite layer

```
                 /synapse-briefing            ← the only user-invoked skill
                       │ (orchestrates)
        ┌──────────┬───┴───┬──────────┐
        ▼          ▼       ▼          ▼
    watchlist   monitor   pulse     synth     ← producer skills
        │          │       │          │
        └──────────┴───┬───┴──────────┘
                       ▼
                  data/arxiv.db                ← shared SQLite (11 tables)
```

**The single invariant:** *skills never import each other.* They
communicate only by reading and writing the SQLite tables they own,
through helpers in `data/db.py`. Any skill can be deleted, rewritten,
or run standalone without breaking the others. Hold this line — it
is what makes the agent independently testable, maintainable, and
publishable on StudyClawHub.

| Skill | Owns | Reads |
|---|---|---|
| `/synapse-watchlist` | `topics`, `news_sources`, `prefs` | – |
| `/synapse-monitor`   | `papers`, `paper_rankings`, `paper_summaries` | `topics` |
| `/synapse-pulse`     | `news_items`, `news_rankings` | `news_sources` |
| `/synapse-synth`     | `paper_news_links`, `opportunities` | `papers`, `paper_rankings`, `news_items`, `news_rankings`, `prefs` |
| `/synapse-briefing`  | `runs` | (every other table — read-only) |

If you need a piece of data not yet in the schema, **add a column or
a new table** rather than passing it in-process between skills.

---

## Repository layout

```
synapse/
├── AGENT.md              ← user-facing description (rendered on the hub)
├── GUIDANCE.md           ← OpenClaw operator install/run instructions
├── SETUP.md              ← prerequisites
├── HOW_IT_WORKS.md       ← deeper architecture write-up
├── CRON.md               ← daily-cron prompt + scheduling notes
├── README.md             ← repo landing page
├── CLAUDE.md             ← (this file) — instructions for Claude Code
├── requirements.txt      ← feedparser, httpx
│
├── data/
│   ├── db.py             ← shared SQLite schema + helpers (the only
│   │                       module any skill imports across boundaries)
│   └── arxiv.db          ← runtime DB (gitignored)
│
├── tools/                ← runnable CLIs, one per skill function
│   ├── watchlist.py            (synapse-watchlist)
│   ├── fetch_papers.py         (synapse-monitor)
│   ├── rank_papers.py          (synapse-monitor)
│   ├── summarize_papers.py     (synapse-monitor, LLM in the loop)
│   ├── fetch_news.py           (synapse-pulse)
│   ├── rank_news.py            (synapse-pulse)
│   ├── cross_ref.py            (synapse-synth)
│   ├── opportunities.py        (synapse-synth, LLM in the loop)
│   └── briefing.py             (synapse-briefing)
│
├── skills/               ← OpenClaw flat-file skill prompts
│   ├── synapse-watchlist.md
│   ├── synapse-monitor.md
│   ├── synapse-pulse.md
│   ├── synapse-synth.md
│   └── synapse-briefing.md
│
├── synapse-watchlist/    ← StudyClawHub-format folders, one per skill
├── synapse-monitor/      ← (each contains a SKILL.md with frontmatter
├── synapse-pulse/         that the registry bot expects)
├── synapse-synth/
├── synapse-briefing/
│
└── analysis/             ← reproducible-results scripts (separate from
    ├── simulate_week.py    skill code; reads data/arxiv.db, never
    ├── charts.py           writes to it from outside the skill layer)
    ├── RESULTS.md
    └── images/
```

The academic report (`REPORT.tex`) lives **outside** this repo, in
`../report/`, alongside `presentation/`. Do not put rendered LaTeX or
PDF artifacts in this repository.

---

## Common tasks

### "Add a new news source"
1. `python3 tools/watchlist.py add-source <name> <url> <kind>`
   where `kind ∈ {hn, reddit, rss}`.
2. The next `fetch_news.py` run will pick it up via
   `db.list_sources()` — no code changes anywhere else.

### "Add a new arXiv topic"
1. `python3 tools/watchlist.py add-topic <keyword> <category> --priority N`.
2. The next `fetch_papers.py` run picks it up. The keyword
   automatically participates in ranking via the same `topics` table.

### "Change the ranking formula"
- Paper ranking lives in `tools/rank_papers.py`, written to the
  `paper_rankings` table. Update both the formula and the schema if
  you add a new sub-score.
- News ranking lives in `tools/rank_news.py` (`news_rankings`).
- The `industry_relevance` term is computed by
  `tools/cross_ref.py` (synapse-synth), not by `rank_papers.py`.

### "Run the full pipeline once"
```
python3 tools/briefing.py
```
This is what the 9 AM cron invokes. It runs fetch + rank + cross-ref
+ summarize + opportunities + format-report in one shot.

### "Reproduce the results in REPORT.tex"
```
python3 analysis/simulate_week.py --days 10   # populate the DB
python3 analysis/charts.py                    # editorial-style charts
cd ../report
python3 make_report_figures.py                # academic-style figures
```

### "Publish or update a skill on StudyClawHub"
Each `synapse-<name>/` folder contains a `SKILL.md` with the
frontmatter (name, description, version, author, tags, install steps)
that the registry bot reads. Bump the `version` field, push, and
re-submit through the StudyClawHub web form — see
`GUIDANCE.md` for the operator-side steps.

---

## Conventions worth holding

- **Polite arXiv delay.** `fetch_papers.py` waits 3 s between
  queries, per arXiv's API guidance. Do not lower this.
- **Soft-fail on Semantic Scholar.** Citation-velocity lookups
  swallow errors and write `citation_score = 0`. The pipeline must
  keep running even if Semantic Scholar is down.
- **Pure HTTP.** No browser, no Selenium, no Playwright. Every input
  is a public feed parseable in two lines of Python (`feedparser`
  for Atom + RSS, `httpx` for everything else).
- **LLM in the loop.** Two scripts (`summarize_papers.py`,
  `opportunities.py`) are *read/write helpers* — they only persist
  JSON the model produced. The actual generation happens in the
  skill prompt, not in Python. Do not move generation logic into
  these scripts.
- **No new dependencies without good reason.** Current set is
  `feedparser` + `httpx`. Adding `sentence-transformers` is the one
  flagged future change (in `analysis/RESULTS.md` §4.3); other
  additions need a written rationale.
- **Idempotent writes.** All `tools/*.py` scripts can be re-run
  safely. UNIQUE constraints in `data/db.py` enforce this; preserve
  them when extending the schema.

---

## What does *not* belong in this repo

- The academic report (`*.tex`, `*.pdf`, NeurIPS-format figures) —
  lives in `../report/`.
- The presentation (`*.pptx`, deck-style PNGs) — lives in
  `../presentation/`.
- The runtime SQLite database (`data/arxiv.db`) — gitignored;
  recreate locally via `simulate_week.py` or `briefing.py`.
- Personal API keys, `.env` files, OAuth tokens — there are none in
  this project; do not introduce them.

---

## When in doubt

1. Read `AGENT.md` for the user-facing description.
2. Read `HOW_IT_WORKS.md` for the deeper architecture rationale.
3. Read the relevant `tools/*.py` — every CLI is short and
   self-documenting.
4. Read `data/db.py` if you need to know what's in the schema.

If a change touches more than one skill, that is a smell — see if it
can be expressed as a new column or table in `data/db.py` instead.
