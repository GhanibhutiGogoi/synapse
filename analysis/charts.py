"""Read the live SQLite DB and produce the four result/analysis charts
plus a stats.json summary used by RESULTS.md and the deck.

Outputs (placed in `analysis/images/`):
  daily_activity.png       — papers + news + bridges per day, 7-day timeline
  score_breakdown.png      — kw / novelty / citation contributions, top-10 papers
  source_contribution.png  — bridges per news source, horizontal bar
  similarity_hist.png      — distribution of paper↔news cosine similarities
  stats.json               — every number RESULTS.md cites, dumped as JSON

Run:
  python3 analysis/charts.py
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "arxiv.db"
OUT = Path(__file__).resolve().parent / "images"
OUT.mkdir(parents=True, exist_ok=True)


# ── Palette (matches the deck) ────────────────────────────────────
PAPER  = "#F5F1E8"
INK    = "#1F1F1F"
INK_M  = "#65605A"
ACCENT = "#2D4A3E"
RULE   = "#C8BFAE"
ACCENT_LIGHT = "#5C7F70"  # lighter forest for stacked bars
SAND   = "#C9B690"        # warm sand for second stack
RUST   = "#A65A3A"        # restrained rust for third stack

mpl.rcParams.update({
    "font.family": "Georgia",
    "font.size": 11,
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "xtick.color": INK_M,
    "ytick.color": INK_M,
    "axes.spines.top": False,
    "axes.spines.right": False,
})


# ──────────────────────────────────────────────────────────────────
#  Stats — derive every number we cite
# ──────────────────────────────────────────────────────────────────

def parse_iso(s: str) -> datetime:
    s = (s or "").replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def compute_stats() -> dict:
    """Read the DB and return everything RESULTS.md / the slides need."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    c = con.cursor()

    # Counts
    counts = {
        "topics":       c.execute("SELECT COUNT(*) FROM topics WHERE active=1").fetchone()[0],
        "sources":      c.execute("SELECT COUNT(*) FROM news_sources WHERE active=1").fetchone()[0],
        "papers":       c.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
        "news_items":   c.execute("SELECT COUNT(*) FROM news_items").fetchone()[0],
        "rankings_p":   c.execute("SELECT COUNT(*) FROM paper_rankings").fetchone()[0],
        "rankings_n":   c.execute("SELECT COUNT(*) FROM news_rankings").fetchone()[0],
        "links":        c.execute("SELECT COUNT(*) FROM paper_news_links").fetchone()[0],
        "opportunities": c.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
        "summaries":    c.execute("SELECT COUNT(*) FROM paper_summaries").fetchone()[0],
        "runs":         c.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
    }

    # Daily activity
    runs = [dict(r) for r in c.execute(
        "SELECT started_at, papers_fetched, news_fetched, opportunities_generated "
        "FROM runs ORDER BY started_at"
    ).fetchall()]

    # Per-day bridge counts (links bucketed by paper.published_at)
    daily_links = c.execute(
        """SELECT date(p.published_at) AS d, COUNT(*) c
           FROM paper_news_links pnl
           JOIN papers p ON p.arxiv_id = pnl.paper_id
           GROUP BY d ORDER BY d"""
    ).fetchall()
    bridge_by_day = {row["d"]: row["c"] for row in daily_links}

    daily = []
    for r in runs:
        d = parse_iso(r["started_at"]).date().isoformat()
        daily.append({
            "date":    d,
            "papers":  r["papers_fetched"],
            "news":    r["news_fetched"],
            "links":   bridge_by_day.get(d, 0),
            "opps":    r["opportunities_generated"],
        })

    # Score component breakdown — top-10 papers
    top_papers = [dict(r) for r in c.execute(
        """SELECT p.arxiv_id, p.title,
                  pr.kw_score, pr.novelty_score, pr.citation_score, pr.total_score,
                  p.industry_relevance
           FROM paper_rankings pr
           JOIN papers p ON p.arxiv_id = pr.paper_id
           ORDER BY pr.total_score DESC, p.industry_relevance DESC
           LIMIT 10"""
    ).fetchall()]

    # Source contribution to bridges
    src_rows = c.execute(
        """SELECT ni.source, COUNT(*) c, AVG(pnl.similarity) avg_sim
           FROM paper_news_links pnl
           JOIN news_items ni ON ni.id = pnl.news_id
           GROUP BY ni.source ORDER BY c DESC"""
    ).fetchall()
    source_contrib = [{"source": r["source"], "count": r["c"],
                       "avg_sim": round(r["avg_sim"], 3)} for r in src_rows]

    # Coverage check: which of our 8 active sources contributed zero?
    active_sources = [r["name"] for r in c.execute(
        "SELECT name FROM news_sources WHERE active=1").fetchall()]
    contributing_sources = {r["source"] for r in src_rows}
    silent_sources = [s for s in active_sources if s not in contributing_sources]

    # Similarity distribution
    sims = [r[0] for r in c.execute("SELECT similarity FROM paper_news_links").fetchall()]
    sim_dist = {}
    if sims:
        sim_dist = {
            "n":      len(sims),
            "min":    round(min(sims), 3),
            "max":    round(max(sims), 3),
            "mean":   round(statistics.mean(sims), 3),
            "median": round(statistics.median(sims), 3),
        }

    # Industry-relevance distribution
    irs = [r[0] for r in c.execute(
        "SELECT industry_relevance FROM papers WHERE industry_relevance > 0"
    ).fetchall()]
    ir_dist = {}
    if irs:
        ir_dist = {
            "n":      len(irs),
            "max":    round(max(irs), 3),
            "mean":   round(statistics.mean(irs), 3),
            "median": round(statistics.median(irs), 3),
        }

    # Top keywords on ranked papers (from top_keywords TEXT field)
    kw_rows = c.execute("SELECT top_keywords FROM paper_rankings").fetchall()
    kw_counter: Counter[str] = Counter()
    for r in kw_rows:
        for tok in (r["top_keywords"] or "").split(","):
            tok = tok.strip().lower()
            if tok:
                kw_counter[tok] += 1
    top_keywords = [{"keyword": k, "count": v} for k, v in kw_counter.most_common(10)]

    # Best & worst paper-news bridges (by similarity)
    best_bridges = [dict(r) for r in c.execute(
        """SELECT pnl.paper_id, p.title AS paper_title,
                  ni.source, ni.title AS news_title, pnl.similarity
           FROM paper_news_links pnl
           JOIN papers p     ON p.arxiv_id = pnl.paper_id
           JOIN news_items ni ON ni.id = pnl.news_id
           ORDER BY pnl.similarity DESC LIMIT 5"""
    ).fetchall()]
    worst_bridges = [dict(r) for r in c.execute(
        """SELECT pnl.paper_id, p.title AS paper_title,
                  ni.source, ni.title AS news_title, pnl.similarity
           FROM paper_news_links pnl
           JOIN papers p     ON p.arxiv_id = pnl.paper_id
           JOIN news_items ni ON ni.id = pnl.news_id
           ORDER BY pnl.similarity ASC LIMIT 5"""
    ).fetchall()]

    con.close()

    return {
        "generated_at":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts":          counts,
        "daily":           daily,
        "top_papers":      top_papers,
        "source_contrib":  source_contrib,
        "silent_sources":  silent_sources,
        "active_sources":  active_sources,
        "sim_dist":        sim_dist,
        "ir_dist":         ir_dist,
        "top_keywords":    top_keywords,
        "best_bridges":    best_bridges,
        "worst_bridges":   worst_bridges,
    }


# ──────────────────────────────────────────────────────────────────
#  Charts
# ──────────────────────────────────────────────────────────────────

def chart_daily_activity(stats: dict) -> Path:
    daily = stats["daily"]
    labels = [d["date"][5:] for d in daily]  # MM-DD
    papers = [d["papers"] for d in daily]
    news   = [d["news"]   for d in daily]
    links  = [d["links"]  for d in daily]

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=200)
    ax.set_facecolor(PAPER)
    fig.patch.set_facecolor(PAPER)

    x = list(range(len(labels)))
    bw = 0.27

    ax.bar([i - bw for i in x], papers, bw, color=ACCENT,
           label=f"papers (Σ {sum(papers)})")
    ax.bar(x,                    news,   bw, color=SAND,
           label=f"news (Σ {sum(news)})")
    ax.bar([i + bw for i in x],  links,  bw, color=RUST,
           label=f"bridges (Σ {sum(links)})")

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylabel("Count")
    ax.set_title("Seven days of Synapse activity",
                 fontsize=14, color=INK, pad=14, loc="left", style="italic")
    ax.legend(frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=0.18, color=INK_M)

    out = OUT / "daily_activity.png"
    fig.savefig(out, dpi=200, bbox_inches="tight",
                facecolor=PAPER, pad_inches=0.25)
    plt.close(fig)
    print(f"  ✓ wrote {out.name}")
    return out


def chart_score_breakdown(stats: dict) -> Path:
    papers = stats["top_papers"]

    titles = []
    kw, nv, ct, ir = [], [], [], []
    for p in reversed(papers):  # so highest-ranked appears at top
        t = p["title"][:55] + ("…" if len(p["title"]) > 55 else "")
        titles.append(t)
        kw.append(p["kw_score"])
        nv.append(p["novelty_score"])
        ct.append(p["citation_score"])
        ir.append(p["industry_relevance"])

    fig, ax = plt.subplots(figsize=(12.0, 7.0), dpi=200)
    ax.set_facecolor(PAPER)
    fig.patch.set_facecolor(PAPER)

    y = list(range(len(titles)))
    ax.barh(y, kw, color=ACCENT,       label="keyword", edgecolor=PAPER, linewidth=0.5)
    ax.barh(y, nv, left=kw, color=ACCENT_LIGHT, label="novelty", edgecolor=PAPER, linewidth=0.5)
    cum = [k + n for k, n in zip(kw, nv)]
    ax.barh(y, ct, left=cum, color=SAND, label="citation", edgecolor=PAPER, linewidth=0.5)
    cum2 = [c + ci for c, ci in zip(cum, ct)]
    ax.barh(y, ir, left=cum2, color=RUST, label="industry-relevance",
            edgecolor=PAPER, linewidth=0.5)

    ax.set_yticks(y)
    ax.set_yticklabels(titles, fontsize=10, color=INK)
    ax.set_xlabel("score contribution", fontsize=11)
    ax.set_title("Top-10 papers — what each component contributes",
                 fontsize=15, color=INK, pad=18, loc="left", style="italic")
    # Legend above the plot to avoid overlapping bars
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.18),
              ncol=4, fontsize=10)
    ax.grid(axis="x", alpha=0.18, color=INK_M)

    out = OUT / "score_breakdown.png"
    fig.savefig(out, dpi=200, bbox_inches="tight",
                facecolor=PAPER, pad_inches=0.25)
    plt.close(fig)
    print(f"  ✓ wrote {out.name}")
    return out


def chart_source_contribution(stats: dict) -> Path:
    rows = stats["source_contrib"]
    silent = stats["silent_sources"]

    # Show every active source — silent ones get a 0-bar so the gap is visible
    counts = {r["source"]: r["count"] for r in rows}
    avg_sims = {r["source"]: r["avg_sim"] for r in rows}
    all_sources = stats["active_sources"]

    # Sort: contributing first (by count desc), silent last
    sorted_sources = (
        sorted([s for s in all_sources if counts.get(s, 0) > 0],
               key=lambda s: -counts.get(s, 0))
        + sorted([s for s in all_sources if counts.get(s, 0) == 0])
    )

    counts_sorted = [counts.get(s, 0) for s in sorted_sources]
    sims_sorted   = [avg_sims.get(s, 0.0) for s in sorted_sources]

    fig, ax = plt.subplots(figsize=(10.5, 5.5), dpi=200)
    ax.set_facecolor(PAPER)
    fig.patch.set_facecolor(PAPER)

    y = list(range(len(sorted_sources)))
    bars = ax.barh(y, counts_sorted, color=[
        ACCENT if c > 0 else RULE for c in counts_sorted
    ], edgecolor=PAPER, linewidth=0.5)

    # Annotate counts + avg-sim at end of each bar
    for i, (c, s) in enumerate(zip(counts_sorted, sims_sorted)):
        if c > 0:
            ax.text(c + 0.20, i, f"{c}   avg sim {s:.2f}",
                    va="center", fontsize=9, color=INK_M, style="italic")
        else:
            ax.text(0.20, i, "(no bridges this week)",
                    va="center", fontsize=9, color=INK_M, style="italic")

    ax.set_yticks(y)
    ax.set_yticklabels(sorted_sources, fontsize=10, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("paper–news bridges")
    ax.set_title("Which news sources connect to research",
                 fontsize=14, color=INK, pad=14, loc="left", style="italic")
    ax.set_xlim(0, max(max(counts_sorted) + 4, 5))
    ax.grid(axis="x", alpha=0.18, color=INK_M)

    out = OUT / "source_contribution.png"
    fig.savefig(out, dpi=200, bbox_inches="tight",
                facecolor=PAPER, pad_inches=0.25)
    plt.close(fig)
    print(f"  ✓ wrote {out.name}")
    return out


def chart_similarity_histogram(stats: dict) -> Path:
    # Re-pull raw similarities (stats only carries summary)
    con = sqlite3.connect(str(DB_PATH))
    sims = [r[0] for r in con.execute("SELECT similarity FROM paper_news_links").fetchall()]
    con.close()

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=200)
    ax.set_facecolor(PAPER)
    fig.patch.set_facecolor(PAPER)

    if sims:
        # Bins of width 0.025 from 0.10 (threshold) up to max
        bin_edges = [0.10 + i * 0.025 for i in range(int((max(sims) - 0.10) / 0.025) + 2)]
        n, bins, patches = ax.hist(sims, bins=bin_edges, color=SAND,
                                    edgecolor=PAPER, linewidth=0.6)

        # Recolor the strong-link bins (>= 0.20) accent
        for patch, edge in zip(patches, bin_edges[:-1]):
            if edge >= 0.20:
                patch.set_facecolor(ACCENT)

        ax.axvline(0.20, color=INK, lw=1.2, linestyle="--", alpha=0.6)
        ax.text(0.205, ax.get_ylim()[1] * 0.92, "strong-link cutoff (0.20)",
                fontsize=9, color=INK, style="italic")

    ax.set_xlabel("cosine similarity")
    ax.set_ylabel("number of bridges")
    ax.set_title("Distribution of paper–news similarities",
                 fontsize=14, color=INK, pad=14, loc="left", style="italic")
    ax.grid(axis="y", alpha=0.18, color=INK_M)

    out = OUT / "similarity_hist.png"
    fig.savefig(out, dpi=200, bbox_inches="tight",
                facecolor=PAPER, pad_inches=0.25)
    plt.close(fig)
    print(f"  ✓ wrote {out.name}")
    return out


# ──────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Reading {DB_PATH}…")
    stats = compute_stats()

    # Persist stats.json so RESULTS.md / external scripts can re-read.
    json_out = OUT / "stats.json"
    with json_out.open("w") as f:
        json.dump(stats, f, indent=2, default=str)
    print(f"  ✓ wrote {json_out.name}\n")

    print("Rendering charts…")
    chart_daily_activity(stats)
    chart_score_breakdown(stats)
    chart_source_contribution(stats)
    chart_similarity_histogram(stats)
    print("\nDone.")


if __name__ == "__main__":
    main()
