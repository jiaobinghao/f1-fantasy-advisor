---
name: f1-fantasy-advisor
description: Maintain and analyze F1 Fantasy data for race-week preparation. Use when Codex needs to fetch public F1 Fantasy driver/constructor feeds, ingest fallback screenshots or CSVs, compute race scores, rolling 3-race AvgPPM, price changes, current prices, budget-building paths, Limitless shadow-team effects, or recommend Team 1 and Team 3 fantasy strategy without using private F1 Fantasy API credentials.
---

# F1 Fantasy Advisor

## Core Workflow

Use the user's fantasy workspace as the source of truth. Read `README.md`,
`data/assets_state.csv`, `data/race_scores.csv`, and `data/team_state.csv`
before giving lineup or chip advice. If `now.md` exists, treat it as local
private working notes and read it for user-specific team context. `data/` is
local private state and should stay ignored by Git; committed CSV templates live
in `data-templates/`.

## Startup Prompt

When the user says `帮我开始fantasy指导`:

1. Inspect the workspace CSVs.
2. If the local `data/` CSVs are missing, initialize them with
   `scripts/fantasy_state.py init-data --data-dir data`.
3. If `data/assets_state.csv` is empty, fetch public F1 Fantasy data with
   `scripts/fetch_fantasy_public.py --out-dir data/imports/official`.
4. Use `data/imports/official/assets_state_snapshot.csv` as the public initial
   asset state. Do not ask the user for the previous two race scores; they are
   available from public per-asset history.
5. Ask only for private account state that public feeds cannot provide:
   current team lineup, remaining budget/cost cap, used chips, active chip,
   boosted driver, transfer penalties, and league/risk objective.
6. If network access is unavailable, explain that public data fetch is blocked
   and fall back to screenshots or CSVs.

For post-race updates:

1. Fetch public F1 Fantasy feeds with `scripts/fetch_fantasy_public.py`.
2. Use `data/imports/official/current_assets.csv`,
   `data/imports/official/assets_state_snapshot.csv`, and
   `data/imports/official/gameday_scores.csv` for public totals, prices,
   per-gameday scores, and price movement.
3. Convert screenshots into CSVs only if the public feed fails or the user is
   providing private account state.
4. Run `scripts/fantasy_state.py update-round` in dry-run mode before applying
   any state update.
5. Confirm the relevant gameday is complete before using it for budget or
   rolling AvgPPM calculations; live partial scores are observation-only.
6. Review missing assets, suspicious totals, negative scores, and price changes.
7. Re-run with `--apply` only after the imported totals look correct.
8. Use the updated data plus official session results, penalties, team comments,
   and weather for the next race-week recommendation.

Do not ask for F1 Fantasy login credentials, bearer tokens, or private API
access. Prefer public F1 Fantasy feeds and official public results; use
screenshots and manual CSVs as fallbacks or for private account state.

## Data Commands

From the fantasy workspace:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/imports/official
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/imports/official --skip-history
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py update-round --data-dir data --round Monaco --drivers data/imports/monaco_drivers.csv --constructors data/imports/monaco_constructors.csv
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py update-round --data-dir data --round Monaco --drivers data/imports/monaco_drivers.csv --constructors data/imports/monaco_constructors.csv --apply
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py report --data-dir data --round Monaco
```

The import CSVs may use either `asset_id,total_fpoints` or
`name,total_fpoints`. Matching by `asset_id` is preferred; matching by name is
supported for screenshot transcription.

When `assets_state.csv` is empty, public data can initialize the driver and
constructor state. The user should not be asked to provide historical scores
unless public feeds fail.

## References

- Read `references/public-data-access.md` before asking for screenshots or
  changing public-feed data acquisition.
- Read `references/price-model.md` before changing price-change calculations or
  onboarding a season at an arbitrary round.
- Read `references/strategy-workflow.md` before giving race-week lineup, chip,
  budget-building, or Team 1 / Team 3 split-strategy advice.
