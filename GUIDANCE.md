# Synapse — Install & Run Guide for OpenClaw

This is the operator-facing guide. Follow it to unzip, install, register the five skills with OpenClaw, set the 9 AM cron, and verify the first run. Total time: ~10 minutes once you're SSH'd into the OpenClaw VM.

---

## 0. Prerequisites

- An OpenClaw VM where you already run other agents (e.g. the LinkedIn tracker).
- Python 3.10+ available as `python3` on the VM (verify: `python3 --version`).
- `pip` and outbound network access to:
  - `export.arxiv.org` (paper metadata)
  - `api.semanticscholar.org` (citation counts — optional, soft-fails)
  - `hacker-news.firebaseio.com` (HN top stories)
  - `www.reddit.com` (subreddit RSS)
  - `techcrunch.com`, `venturebeat.com`, `www.theverge.com`, `www.technologyreview.com` (RSS feeds)

No API keys, no auth, no browser.

---

## 1. Unzip on the VM

From your local machine:

```bash
scp synapse.zip <your-vm-user>@<vm-ip>:/tmp/
```

SSH in and:

```bash
ssh <your-vm-user>@<vm-ip>
sudo mkdir -p /opt/openclaw/synapse
sudo unzip -o /tmp/synapse.zip -d /opt/openclaw/
sudo chown -R openclaw:openclaw /opt/openclaw/synapse
```

Adjust user/path if your OpenClaw install differs (the LinkedIn tracker's `DEPLOY.md` shows where yours lives).

After unzip you should have:

```
/opt/openclaw/synapse/
├── AGENT.md
├── GUIDANCE.md           ← this file
├── SETUP.md
├── requirements.txt
├── skills/               ← 5 flat .md skill files
├── tools/                ← 9 Python scripts
└── data/                 ← shared DB lives here
```

---

## 2. Install Python deps

```bash
cd /opt/openclaw/synapse

# Option A — system pip (simplest)
sudo -u openclaw pip3 install --user -r requirements.txt

# Option B — virtualenv (isolated, recommended if other Python projects on the VM)
sudo -u openclaw python3 -m venv venv
sudo -u openclaw ./venv/bin/pip install -r requirements.txt
```

If you go with Option B, prefix every `python3` command below with `./venv/bin/`.

Verify imports:

```bash
sudo -u openclaw python3 -c "import feedparser, httpx; print('ok', feedparser.__version__, httpx.__version__)"
```

---

## 3. Initialize the DB and seed defaults

```bash
sudo -u openclaw python3 -c "from data.db import init_db; init_db()"
sudo -u openclaw python3 tools/watchlist.py seed-defaults
```

Expected:
```
Seeded 42 topics across 6 categories.
Seeded 8 news sources.
```

(Optional) Set an industry focus to bias opportunity synthesis:
```bash
sudo -u openclaw python3 tools/watchlist.py set-industry-focus "developer tools, fintech, healthcare"
```

---

## 4. Register the five skills with OpenClaw

Find where OpenClaw loads skills from on this VM (same trick as the LinkedIn tracker):

```bash
sudo -u openclaw find /opt/openclaw -type d -name skills 2>/dev/null
sudo -u openclaw ls /opt/openclaw/skills/ 2>/dev/null
```

This project ships skills as flat `.md` files in `synapse/skills/` — the same convention your LinkedIn tracker uses. To register:

```bash
SKILLS_DIR="/opt/openclaw/skills"     # adjust to whatever step 4's `find` showed

# Symlink each skill .md into OpenClaw's skills directory
for s in synapse-watchlist synapse-monitor synapse-pulse synapse-synth synapse-briefing; do
  sudo -u openclaw ln -sf "/opt/openclaw/synapse/skills/$s.md" "$SKILLS_DIR/$s.md"
done
```

Symlinks let you edit a skill in place without re-registering.

If your OpenClaw install needs copies instead of symlinks:
```bash
for s in synapse-watchlist synapse-monitor synapse-pulse synapse-synth synapse-briefing; do
  sudo -u openclaw cp "/opt/openclaw/synapse/skills/$s.md" "$SKILLS_DIR/$s.md"
done
```

### Verify

Open OpenClaw and ask: **"What synapse skills do you have?"** — it should list the five and recognize their trigger phrases.

---

## 5. Smoke tests (run before scheduling cron)

Run each skill once manually and confirm no errors. All commands run from `/opt/openclaw/synapse`:

```bash
cd /opt/openclaw/synapse

# Watchlist (no networking)
sudo -u openclaw python3 tools/watchlist.py list-topics
sudo -u openclaw python3 tools/watchlist.py list-sources

# Fetch + rank papers (small batch first)
sudo -u openclaw python3 tools/fetch_papers.py --limit 30 --max-per-query 10
sudo -u openclaw python3 tools/rank_papers.py --no-citations --top-print 5

# Fetch + rank news
sudo -u openclaw python3 tools/fetch_news.py --limit 50 --per-source 15
sudo -u openclaw python3 tools/rank_news.py --top-print 5

# Cross-reference
sudo -u openclaw python3 tools/cross_ref.py

# Render a partial briefing (Opportunities will be empty without the LLM steps)
sudo -u openclaw python3 tools/briefing.py report
```

If everything prints reasonable output and no exceptions surface, you're set. The full pipeline (with summaries + opportunities) requires the OpenClaw model to perform the LLM extraction steps — that's exercised by triggering `/synapse-briefing` from inside OpenClaw.

---

## 6. Try the full pipeline from inside OpenClaw

Open OpenClaw and prompt:

```
Run /synapse-briefing for today's digest.
```

OpenClaw will read `synapse-briefing.md`, walk through the 9-step pipeline, perform the two LLM-driven steps (summarize + opportunities), and post the 4-section markdown report.

Expected sections:
- 🔬 Top Research Today (table + top-3 expanded)
- 📰 Industry Pulse (grouped by source)
- 🔗 Research ↔ Industry Bridges
- 💡 Buildable Opportunities

If a section is empty, see "Failure Modes" in the relevant skill file.

---

## 7. Set the 9 AM cron (OpenClaw)

Your LinkedIn tracker already uses OpenClaw's cron — same machinery. Discover the cron CLI:

```bash
sudo -u openclaw HOME=/opt/openclaw openclaw cron --help 2>/dev/null
```

Register a daily 9 AM job with **this exact prompt** (working directory: `/opt/openclaw/synapse`):

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

---

## 8. Verify after the first scheduled run

```bash
sudo -u openclaw python3 tools/briefing.py status --limit 7
```

You should see one row per day, with `status='completed'` and non-zero counts. To inspect underlying data:

```bash
sudo -u openclaw sqlite3 /opt/openclaw/synapse/data/arxiv.db <<EOF
.headers on
SELECT COUNT(*) AS papers FROM papers;
SELECT COUNT(*) AS news FROM news_items;
SELECT COUNT(*) AS opps FROM opportunities;
SELECT * FROM runs ORDER BY started_at DESC LIMIT 7;
EOF
```

---

## 9. Operating notes

- **Run manually any time**: `Run /synapse-briefing` from inside OpenClaw.
- **Adjust topics**: `python3 tools/watchlist.py add-topic "diffusion" --category cs.CV --priority 2`.
- **Adjust industry focus**: `python3 tools/watchlist.py set-industry-focus "..."`.
- **Inspect a paper**: `python3 tools/summarize_papers.py show 2401.12345`.
- **Inspect opportunities**: `python3 tools/opportunities.py show --since-days 1`.
- **Follow-up query**: in OpenClaw, "show me papers about graph neural networks from this week" routes to `briefing.py query`.

---

## 10. Uninstall / reinstall

```bash
sudo rm -rf /opt/openclaw/synapse
# Remove the symlinks you placed in step 4
for s in synapse-watchlist synapse-monitor synapse-pulse synapse-synth synapse-briefing; do
  sudo rm -f "/opt/openclaw/skills/$s.md"
done
```

Backup the DB first if you want to keep your 7-day testing data:

```bash
sudo cp /opt/openclaw/synapse/data/arxiv.db ~/synapse.db.backup
```

---

## 11. Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `fetch_papers.py` returns 0 papers | watchlist empty | run `tools/watchlist.py seed-defaults` |
| `rank_papers.py` very slow | citation lookup throttled | re-run with `--no-citations` |
| All news scores below 0.5 | rate-limited HN/Reddit | re-run later; or disable the offending source |
| Reddit returns 403 | IP blocked from prior bad-UA hits | wait ~10 minutes and retry |
| Opportunities section always empty | no paper-news links above threshold | lower `tools/cross_ref.py --min-sim` to 0.07 |
| `briefing.py` reports "no ranked papers" | ran `report` before `rank` | run the full pipeline in order |
| `ImportError: data.db` | tool invoked from wrong cwd | run from `/opt/openclaw/synapse` (scripts auto-add the project root to sys.path, but the cwd must contain `data/`) |
| `sqlite3: file is not a database` | partial write; corrupted db | restore from backup, or `rm data/arxiv.db && python3 -c "from data.db import init_db; init_db()" && python3 tools/watchlist.py seed-defaults` |

For deeper debugging, every skill has a "Failure Modes" section at the bottom of its `.md` file in `skills/`.
