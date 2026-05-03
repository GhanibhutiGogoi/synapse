# Synapse — Daily Cron Setup

How to register Synapse with OpenClaw's cron so Claude runs the **whole pipeline** — paper fetch + news fetch + ranking + cross-referencing + LLM-driven summaries + LLM-driven opportunity synthesis + final 4-section report — once every day at 9 AM, with zero manual intervention.

---

## How OpenClaw cron works

OpenClaw cron is the same machinery you already use for the LinkedIn tracker. At the scheduled time, OpenClaw:

1. Spawns a fresh Claude session.
2. Feeds it the cron prompt (the text below) as the user message.
3. Lets Claude walk through every step — including running shell commands and performing the LLM-driven extraction/synthesis steps inline.
4. Captures the rendered report from Claude's final output.

Concretely: **you do not write a bash script and put it in `crontab`**. You register a *prompt* with OpenClaw, and OpenClaw fires up Claude with that prompt at the scheduled time. Claude is the executor.

This means the LLM steps (summaries, opportunity synthesis) are not an afterthought — they happen inside the same daily session, with all the paper and news context loaded.

---

## 1. Find OpenClaw's cron CLI

This is the same step you took for the LinkedIn tracker. SSH into the VM and:

```bash
sudo -u openclaw HOME=/opt/openclaw openclaw cron --help 2>/dev/null
sudo -u openclaw HOME=/opt/openclaw openclaw --help 2>/dev/null | grep -i cron
```

The exact subcommand name (`cron add`, `cron create`, `schedule`, etc.) and flags depend on your OpenClaw version. The typical shape is:

```bash
openclaw cron add \
  --name synapse-daily \
  --schedule "0 9 * * *" \
  --cwd /opt/openclaw/synapse \
  --prompt "<paste prompt below>"
```

If your OpenClaw version uses a config file rather than a CLI, the same fields go into the config (name, schedule, cwd, prompt).

---

## 2. The cron prompt (paste this exactly)

```text
You are running the daily Synapse pipeline. Working directory:
/opt/openclaw/synapse. Run from this directory; every script auto-adds it
to sys.path.

Goal: produce a complete 4-section markdown digest for today, posted into
this chat. Do NOT skip the LLM-driven steps (5b, 5c) — they are what makes
the report useful.

Run these steps IN ORDER. If a single step fails (network blip, source
down), capture the error and continue with the rest, then add a "Caveats"
footnote to the report. Never abort early without producing a report.

────────────────────────────────────────────────────────────────────
STEP 0 — Open a run record
────────────────────────────────────────────────────────────────────
Run:
  RUN_ID=$(python3 -c "from data.db import start_run; print(start_run())")
Capture RUN_ID for step 6.

────────────────────────────────────────────────────────────────────
STEP 1 — Fetch new papers from arXiv
────────────────────────────────────────────────────────────────────
Run:
  python3 tools/fetch_papers.py --limit 200 --days 4
(Note: --days 4 is the safe weekly window. arXiv has no Sat/Sun
announcements, so a 2-day window misses Friday's batch when running
on Sunday or Monday morning. The script also prints diagnostics
breaking down returned/dropped counts so 0-paper days are explicable.)
Note the count of new papers inserted.

────────────────────────────────────────────────────────────────────
STEP 2 — Fetch AI industry news
────────────────────────────────────────────────────────────────────
Run:
  python3 tools/fetch_news.py --limit 200 --per-source 40
Note the count of new news items inserted.

────────────────────────────────────────────────────────────────────
STEP 3 — Rank papers
────────────────────────────────────────────────────────────────────
Run:
  python3 tools/rank_papers.py
If Semantic Scholar is throttling, fall back to:
  python3 tools/rank_papers.py --no-citations

────────────────────────────────────────────────────────────────────
STEP 4 — Rank news
────────────────────────────────────────────────────────────────────
Run:
  python3 tools/rank_news.py

────────────────────────────────────────────────────────────────────
STEP 5 — Cross-reference papers ↔ news
────────────────────────────────────────────────────────────────────
Run:
  python3 tools/cross_ref.py --paper-days 4 --news-days 14 \
                             --top-papers 40 --min-sim 0.10

────────────────────────────────────────────────────────────────────
STEP 5b — Summarize top papers (THIS IS A REQUIRED LLM STEP)
────────────────────────────────────────────────────────────────────
1. Run: python3 tools/summarize_papers.py list --top-k 10
   This emits a JSON array of papers needing summary.
2. For each paper in the array, read its abstract and emit:
     {
       "arxiv_id": "<id>",
       "problem":       "<1 sentence: the concrete challenge>",
       "method":        "<1-2 sentences: technical approach in plain language>",
       "contributions": "<1-2 sentences: what is new vs prior work>",
       "results":       "<1 sentence: headline empirical result with numbers>"
     }
3. Apply the quality rules from synapse-monitor.md (section "Quality rules"):
     - Problem must name the concrete difficulty, not "we study X"
     - Method must be readable to a CS student who hasn't read this paper
     - Contributions must be testable claims, not marketing
     - Results must include a number if the abstract gives one
     - Use "not stated" rather than fabricating
4. Collect all summaries into a single JSON array and write them:
     echo '<json-array>' | python3 tools/summarize_papers.py write
   Or write the JSON to /tmp/summaries.json and:
     python3 tools/summarize_papers.py write < /tmp/summaries.json

────────────────────────────────────────────────────────────────────
STEP 5c — Synthesize buildable opportunities (REQUIRED LLM STEP)
────────────────────────────────────────────────────────────────────
1. Run: python3 tools/opportunities.py list --top-k 5 --min-sim 0.15
   This emits a JSON object with industry_focus and a candidates array.
2. For each candidate, produce ONE opportunity object:
     {
       "arxiv_id":      "<id>",
       "news_ids":      [<ids of the linked_news items used>],
       "idea":          "<1-2 sentence concrete buildable product>",
       "rationale":     "<1 sentence: why now>",
       "paper_insight": "<1 sentence: which capability from the paper>",
       "market_signal": "<1 sentence: which signal from the news>"
     }
3. Apply the 5-rule rubric from synapse-synth.md. REJECT a candidate
   (skip it, don't fabricate) if any of these are true:
     1. Not buildable in <3 months by a small team
     2. Idea doesn't actually use the paper's contribution
     3. Idea ignores the linked news (could have been written from
        the abstract alone)
     4. Vague — "Build an AI platform for X" is not an idea; concrete
        forms ("Chrome extension that...", "CLI that...", "Slack bot
        that...") are
     5. Reinvents a product the news has already announced
4. If industry_focus is non-empty in the input, bias toward those
   verticals — but never force a fit that breaks rules 2 or 3.
5. Collect all opportunities into a single JSON array (it's fine to
   produce fewer opportunities than candidates if some fail the rubric)
   and write them:
     echo '<json-array>' | python3 tools/opportunities.py write

────────────────────────────────────────────────────────────────────
STEP 6 — Render the report and close the run
────────────────────────────────────────────────────────────────────
Run:
  python3 tools/briefing.py report --top-papers 10 --top-news 12 --top-opps 5 \
                                   --paper-days 4 --news-days 2

Then close the run record (substitute the captured counts):
  python3 -c "from data.db import end_run; end_run($RUN_ID, \
    papers_fetched=<P>, news_fetched=<N>, \
    opportunities_generated=<O>, status='completed')"

The output of briefing.py is the markdown report. Post it directly into
this chat as your final response. If any step had a failure, append a
short "## ⚠ Caveats" section listing what failed and what was missed,
so the user knows which sections might be thin.
```

---

## 3. Schedule string

The schedule field uses standard cron syntax. For 9 AM local time daily:

```
0 9 * * *
```

If your OpenClaw VM is on UTC and you want 9 AM in another timezone, adjust accordingly:
- 9 AM PST (UTC-8) → `0 17 * * *`
- 9 AM EST (UTC-5) → `0 14 * * *`
- 9 AM CET (UTC+1) → `0 8 * * *`
- 9 AM Beijing/Hong Kong (UTC+8) → `0 1 * * *`

Verify the VM's current timezone:
```bash
date
timedatectl 2>/dev/null
```

---

## 4. Verify the cron is registered

After registration, OpenClaw should let you list scheduled jobs:

```bash
sudo -u openclaw HOME=/opt/openclaw openclaw cron list 2>/dev/null
# or:
sudo -u openclaw HOME=/opt/openclaw openclaw cron status synapse-daily 2>/dev/null
```

You should see `synapse-daily` with schedule `0 9 * * *` and your prompt attached.

---

## 5. Trigger a manual run before waiting for 9 AM

Don't wait until tomorrow morning to find out something's broken. Either:

### Option A — fire the cron job manually

If OpenClaw exposes it:
```bash
sudo -u openclaw HOME=/opt/openclaw openclaw cron run synapse-daily 2>/dev/null
```

### Option B — paste the prompt directly into OpenClaw chat

Open OpenClaw and paste the entire prompt from section 2 (the text inside the code block). It will execute exactly the same way the cron will, just on demand.

### Option C — minimal smoke test

If you just want to confirm the pipeline is wired up without burning the full LLM run:

```bash
cd /opt/openclaw/synapse
python3 tools/fetch_papers.py --limit 20 --days 14
python3 tools/fetch_news.py --limit 30 --per-source 10
python3 tools/rank_papers.py --no-citations
python3 tools/rank_news.py
python3 tools/cross_ref.py
python3 tools/briefing.py report
```

You'll get a partial report (Top Research, Industry Pulse, Bridges all populated; Buildable Opportunities empty because no LLM ran). That's enough to confirm steps 0–5 work.

---

## 6. Verify after the first scheduled run

The morning after the cron fires, check that a row was added to `runs`:

```bash
cd /opt/openclaw/synapse
python3 tools/briefing.py status --limit 7
```

Expected output:
```
id    started_at             status        papers   news  opps
1     2026-05-04T09:00:01    completed         87     34     4
```

Also check the report itself was posted into your OpenClaw chat at ~9 AM. If it didn't show up, see "Failure modes" below.

---

## 7. The 7-day test window

For the first week, treat each daily run as a test. After each morning's report:

1. Skim the four sections — anything obviously broken?
2. Check `runs` (`status` should be `completed`, not `running` or `failed`).
3. Check the opportunities — are they passing the 5-rule rubric? If you see vague ideas like "Build an AI platform for X", that's a sign the rubric isn't being enforced.
4. Note anything to tune (priorities, news sources, industry focus) for the report.

After day 7, the DB will have:
- 7 rows in `runs`
- ~300–600 papers
- ~150–400 news items
- ~50–100 paper-news links
- ~20–35 opportunities

That's enough material to write the *Results* and *Analysis* sections of the 3-page individual report.

---

## 8. Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| No report appeared in chat at 9 AM | Cron didn't fire, or Claude session timed out | Check `openclaw cron list` and the cron logs; manually fire to confirm prompt works |
| Report posted but `runs` row stuck at `status='running'` | Claude crashed before STEP 6 | Manually run `python3 -c "from data.db import end_run; end_run(<id>, status='aborted')"` to clean up |
| Buildable Opportunities section empty | No paper had a strong news link | Lower `tools/cross_ref.py --min-sim` to 0.07 in the cron prompt and re-register |
| Opportunities are all vague / not buildable | Rubric not being enforced | Re-check that the cron prompt includes the full 5-rule rubric (it does, in the prompt above) |
| Top Research empty | arXiv API failed | Check `python3 tools/fetch_papers.py` manually; rate-limit usually clears in <30 min |
| Industry Pulse empty | All news sources failed | Likely Reddit IP block; wait, or temporarily disable Reddit sources via `tools/watchlist.py remove-source` |
| `ImportError: data.db` | Cron working directory not set | Confirm `--cwd /opt/openclaw/synapse` in registration; the prompt itself also names the directory |

---

## 9. Stopping / changing the cron

```bash
# Disable temporarily
sudo -u openclaw HOME=/opt/openclaw openclaw cron disable synapse-daily 2>/dev/null

# Remove
sudo -u openclaw HOME=/opt/openclaw openclaw cron remove synapse-daily 2>/dev/null

# Update prompt (typical workflow: remove + add with new prompt)
sudo -u openclaw HOME=/opt/openclaw openclaw cron remove synapse-daily 2>/dev/null
sudo -u openclaw HOME=/opt/openclaw openclaw cron add --name synapse-daily \
  --schedule "0 9 * * *" --cwd /opt/openclaw/synapse \
  --prompt "<new prompt>"
```

If your OpenClaw version uses a different syntax, the LinkedIn tracker's existing cron registration is the canonical reference for what works on your VM.
