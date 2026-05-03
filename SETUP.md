# Synapse — Requirements

- **Python 3.10+** (tested on 3.10, 3.11, 3.12, 3.13)
- **pip** with internet access for the two third-party deps
- **sqlite3** (CLI binary; available by default on macOS and most Linux distros — only needed for manual DB inspection)

Third-party Python packages (`requirements.txt`):
- `feedparser >= 6.0.11` — Atom/RSS parsing for arXiv + news sources
- `httpx >= 0.27.0` — synchronous HTTP client

Everything else (sqlite3 driver, json, argparse, etc.) is in the Python standard library.

## Quick install

```bash
cd /opt/openclaw/synapse        # or wherever you unzipped
pip install -r requirements.txt
python3 -c "from data.db import init_db; init_db()"   # creates data/arxiv.db
python3 tools/watchlist.py seed-defaults
```

## Verify

```bash
python3 -c "import feedparser, httpx; print(feedparser.__version__, httpx.__version__)"
python3 tools/watchlist.py list-topics
```

If you see 42 topic rows and a watchlist printout, you're ready. Continue with `GUIDANCE.md`.
