# Synapse

A daily AI **research × industry** briefing agent for OpenClaw. Five skills, one shared SQLite database, no browser.

Every morning at 9 AM, Synapse:

1. Pulls new papers from the **arXiv API** matching your watchlist of keywords × categories.
2. Pulls fresh AI **industry news** from HackerNews, Reddit (r/MachineLearning, r/LocalLLaMA, r/artificial), TechCrunch AI, VentureBeat AI, The Verge, MIT Tech Review.
3. Ranks papers (keyword + novelty + citation velocity) and news (AI-relevance + recency).
4. **Cross-references** them — finds papers whose topics are echoing in the market right now, lifting them in the daily ranking.
5. Extracts structured `{problem, method, contributions, results}` summaries for the top papers.
6. Synthesizes **buildable opportunities** — concrete project ideas where a paper insight meets a market signal, biased toward the user's `industry_focus` preference.
7. Renders a 4-section markdown digest: Top Research · Industry Pulse · Research ↔ Industry Bridges · Buildable Opportunities.

The differentiator is sections 4–6: it closes the loop from research → industry context → things you could ship.

## Quick links

- **[AGENT.md](AGENT.md)** — system overview, layout, call hierarchy
- **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)** — user-facing explanation, sample report, knobs you can turn
- **[GUIDANCE.md](GUIDANCE.md)** — install / register / cron walkthrough for OpenClaw operators
- **[CRON.md](CRON.md)** — daily-cron prompt + scheduling
- **[SETUP.md](SETUP.md)** — prerequisites

## Skills (in `skills/`)

| Skill | Trigger | Purpose |
|---|---|---|
| `/synapse-watchlist` | "show watchlist" / "add topic" / "set industry focus" | Manage topics, news sources, prefs |
| `/synapse-monitor`   | "fetch new papers" / "rank papers"                    | arXiv pipeline (fetch + rank + summarize) |
| `/synapse-pulse`     | "fetch AI news" / "industry pulse"                    | News pipeline (fetch + rank) |
| `/synapse-synth`     | "what can I build from today's papers"                | Cross-reference + opportunity synthesis (the creative core) |
| `/synapse-briefing`  | "synapse briefing" / "morning report"                 | Entry point + 4-section daily digest |

## Standalone Skill: `synapse-synth`

The `synapse-synth/` folder at the repo root packages the same skill in StudyClawHub's `<folder>/SKILL.md` format for individual-skill registration.

## Built for the Spring 2026 Social Network Analysis course

Implements Topic #2 from the project guidance (Daily arXiv Research Briefing Agent), with an added creative dimension: cross-referencing papers with industry news and synthesizing buildable opportunities.

## License

MIT
