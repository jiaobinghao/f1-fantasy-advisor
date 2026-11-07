---
name: f1-fantasy-advisor
description: Maintain and analyze F1 Fantasy data for race-week preparation. Use for public feeds, fallback screenshots/CSVs, scores and price changes, probability-based driver/constructor forecasts, budget-constrained lineup and chip evaluation, or Team 1/2/3 strategy without private F1 Fantasy API credentials.
---

# F1 Fantasy Advisor

## Core Workflow

Use the user's fantasy workspace as the source of truth. Read `README.md`,
`data/assets_state.csv`, `data/race_scores.csv`, and `data/team_state.csv`
before giving lineup or chip advice. If `now.md` exists, treat it as local
private scratch only, not authoritative memory. Any user-specific team state
learned during a conversation must be recorded in `data/team_state.csv` with
`scripts/fantasy_state.py record-team`. Remaining free transfers have no CSV
column: preserve that fact and its timestamp in `--notes` and the forecast's
`teams.json`. `data/` is local private state and
should stay ignored by Git; committed CSV templates live in `data-templates/`.

Resolve `scripts/` and `references/` relative to this skill directory. Repository
examples use `skill-dev/f1-fantasy-advisor/`; when the skill is installed elsewhere,
use its actual path while keeping the user's `data/` in their workspace.

Treat Team 1, Team 2, and Team 3 as managed teams. Whenever giving race-week
lineup, transfer, boost, chip, budget, or portfolio advice, analyze all three
unless the user explicitly narrows the scope. If one team's state is missing or
stale, flag that limitation instead of silently omitting the team.

## Startup Prompt

When the user says `帮我开始fantasy指导` or `Help me start F1 Fantasy guidance.`:

1. Inspect the workspace CSVs.
2. If the local `data/` CSVs are missing, initialize them with
   `scripts/fantasy_state.py init-data --data-dir data`.
3. If `data/assets_state.csv` is empty, fetch public F1 Fantasy data with
   `scripts/fetch_fantasy_public.py --out-dir data/official`.
4. Use `data/official/official_asset_metrics.csv` as the public source for
   initial asset state. Map `last2_fpoints` to `previous_race_fpoints` and
   `last1_fpoints` to `last_race_fpoints`. Do not ask the user for the
   previous two race scores; they are available from public per-asset history.
5. Ask only for private account state that public feeds cannot provide:
   current team lineup, remaining budget/cost cap, used chips, active chip,
   boosted driver, remaining free transfers, transfer penalties, and league/risk
   objective. Reuse confirmed saved facts; ask only for missing or stale fields.
6. After the user provides private team state, record each team with
   `scripts/fantasy_state.py record-team` so future guidance reads CSV state
   instead of conversation history or `now.md`.
7. If network access is unavailable, explain that public data fetch is blocked
   and fall back to screenshots or CSVs.

For post-race updates:

1. Fetch public F1 Fantasy feeds with `scripts/fetch_fantasy_public.py`.
2. Use `data/official/official_asset_metrics.csv` and
   `data/official/official_round_context.csv` for public totals, prices,
   previous completed gameday scores, official settled price movement, and
   target-round price-zone floors.
3. Convert screenshots into CSVs only if the public feed fails or the user is
   providing private account state.
4. Run `scripts/fantasy_state.py update-round` in dry-run mode before applying
   any state update.
5. Confirm the relevant gameday is complete before using it for budget or
   rolling AvgPPM calculations; live partial scores are observation-only.
6. Review missing assets, suspicious totals, negative scores, and official price
   changes from visible price movement: next gameday `PlayerValue`, or current
   common-statistics `curvalue` for the latest completed pre-target gameday,
   minus this gameday `PlayerValue`. Do not use `OldPlayerValue` as the routine
   settled price-change source.
7. Re-run with `--apply` only after the imported totals look correct.
8. Use `official_asset_rankings.csv` for target-round price-risk screening;
   it is a narrow sorted view of score floors. Lower `score_floor` is better.
   Never call a rise locked while negative race-week scores remain possible.
9. Use the updated data plus official session results, penalties, team comments,
   and weather for the next race-week recommendation.

Do not ask for F1 Fantasy login credentials, bearer tokens, or private API
access. Prefer public F1 Fantasy feeds and official public results; use
screenshots and manual CSVs as fallbacks or for private account state.

## Data Commands

From the fantasy workspace:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official --skip-history
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py record-team --data-dir data --round Spain --team-id Team1 --lineup 11161,13,11051,129,11059,25,28 --boost-asset-id 11161 --budget-before 4.7 --transfer-penalty -10
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

When `team_state.csv` is empty, ask beginner-friendly questions and record the
answers. Do not rely on `now.md` or prior chat memory for lineup, budget, chips,
or transfer penalties.

## Lineup Tools

### Forward Predictions

For "calculate this week's lineup", start with
`references/race-week-runbook.md`. It connects race/deadline discovery, evidence
acquisition, current account conversion, execution and output interpretation.
Prepare the input files for the user; do not make them author JSON. `run` does
not read `team_state.csv` automatically or discover news from free text.

Read `references/forecast-model.md` before forecasting points or calling a
future lineup optimal. It defines scoring formulas, the probability standard,
source/sample requirements, coherent scenarios, calibration labels, and input
contracts. For the implemented v1 pipeline, also read
`references/forecast-inputs.md`: it defines acquisition, input schemas, news
extraction, grid penalties, defaults and budget selection. Use this workflow
for both standard and Sprint rounds:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py example-run --out-dir data/forecast-demo
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py run --config data/forecast-demo/run_config.json --offline --out-dir data/forecast-demo/result
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py optimize data/forecast-demo/result/forecast.json --teams data/forecast-demo/teams.json --allow 0
```

These commands use fictional examples, not race recommendations. For a real
forecast, configure public feeds or normalized cached evidence, refresh
prices/entrants before lock, and extract cited news into the documented inputs.
The program estimates history/practice probabilities and generates full-field
scenarios. News may only compensate practice incidents, penalize explicit
handling instability, or describe grid penalties; do not change reliability
probabilities from news in v1. Require publication times and exact quotes.
Uncertain penalties need justified probabilities or separate conditional
branches. Never invent equal odds or apply a penalty twice to an official grid.

Evaluate all managed teams with actual saved holdings, bank and remaining free
transfers, or an explicitly confirmed official transfer-accounting baseline
with its matching allowance and bank. If the user has submitted changes since
the saved snapshot and has not confirmed that baseline, label a
replay as simulation-only rather than inferring current accounts. The new `run`
supports normal fixed 2x; active chips use the separate manual-scenario tools.
Defaults are uncalibrated and exported. Report `scenario`, `baseline`, or
`calibrated` honestly;
metadata validation alone does not verify predictive quality. Use `calibrate`
on frozen pre-lock predictions and later outcomes to assess probability errors.

The default history uses four valid rounds per estimation pool, with linear
weights `1, 0.75, 0.5, 0.25` from newest to oldest. Explicit configs use
`window: 4, decay_mode: linear, half_life: 2`. This follows the user's specified
weights, not standard exponential halving; older reports describe their saved
settings. Read `forecast-inputs.md` for gaps, pooled observations and priors.
Qualifying, race and Sprint pace use their own historical results, each mixed
with available practice; missing-rank incident fallbacks stay in that session.
Inspect each model's `pace_history` audit rather than confusing it with status
samples. Look up fixed difficulty `d` in `references/circuit-profiles.json`;
`g=0.2+0.6*d` gives the 20%-80% grid weight for both Race and Sprint. Do not
re-estimate circuits or fetch circuit news during each forecast. Unknown tracks
use a flagged neutral 50% weight. These are uncalibrated editorial assessments;
low-confidence entries and overrides must be disclosed. Match physical circuit
names/aliases, not Grand Prix titles. Positive position gains use
`q=sum(w*gain)/sum(w*overtakes)` from positive-gain history, then `gain/q` with
expectation-preserving integer rounding. Non-gaining finishers and started NC
drivers use empirical fallbacks. Inspect `circuit_models` and `overtake_models`
in `model_parameters.json`; `circuit_profiles.json` snapshots the fixed table
with its version/content hash. A table assessed after the forecast cutoff is a
retrospective model revision. Legacy density imports and thinning are removed.
Historical finishing ranks are pace proxies, not lap-time estimates.

Show category-level mean contributions, net expected lineup points, transfer
fees, no-transfer/best-free comparisons, and joint uncertainty. Read
`advisor_input.json`, `model_parameters.json` and `grid_penalty_impacts.json`
before explaining results. By default `--allow 10` first finds the highest net
expected score, then maximizes expected budget growth across all legal lineups
within ten points of that score. Explain `score_best`, `budget_best`,
`loss_vs_best`, and expected value growth separately. Compute prices from raw
scenario scores, not mean scores or boosted points. Missing price history can
make the budget optimum unavailable; disclose it and report the score result.
For a keep/sell question, compare complete
legal lineups using `required_assets` versus `excluded_assets`, not an isolated
driver score. Review the versioned rules each season. Final Fix/post-lock and
season-wide chip allocation are not implemented by this prediction engine.

Whenever reporting individual driver point forecasts, also show each driver's
probability-weighted mean qualifying position, race starting position after
penalties and classified race finishing position. Use
`expected_driver_positions.csv` or `advisor_input.json`'s `driver_positions`;
the conditional denominators and availability probabilities are documented in
`references/forecast-inputs.md`. Position means may be fractional and are not
guaranteed outcomes; never assign a fictitious last-place finish to an NC, DNS
or DSQ. State the conditioning and label unavailable values N/A. On Sprint
weekends, additionally show Sprint starting and finishing positions separately;
the v1 model does not forecast a separate Sprint qualifying position.

For a detailed forecast, follow the reporting format in
`references/race-week-runbook.md` section 6: show every active driver's and
constructor's current price, expected raw points, expected price change and
price-fall probability, plus each driver's qualifying, race start and finish
position means, then both the score and budget options for each managed
team. In Chinese, label `budget_best` as "保价/增值方案" and explain that it
maximizes expected value growth within `--allow`, not guaranteed capital
protection or minimum loss probability. Include complete rosters, 2x, transfers,
fees, remaining cash, comparisons and evidence limitations. Explicitly identify
withdrawals, replacements or unavailable estimates rather than silently omitting
them or scoring a withdrawn driver as if still racing.

### Historical And Live Tools

These existing tools use completed or live scores, not forecast probabilities.
Run from the fantasy workspace after a public data fetch:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/auto_pilot_lineup.py 112 --top 10
python3 skill-dev/f1-fantasy-advisor/scripts/best_lineup_with_transfers.py --interactive
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --fetch
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --interactive
python3 skill-dev/f1-fantasy-advisor/scripts/best_live_lineup.py budget 112
python3 skill-dev/f1-fantasy-advisor/scripts/best_live_lineup.py transfers --interactive
```

- `auto_pilot_lineup.py BUDGET` finds the theoretical best lineup for a cost
  cap from historical `data/official` metrics, not next-race expected scores.
- `best_lineup_with_transfers.py` starts from last week's lineup and accounts
  for extra-transfer penalties; `--interactive` prompts for the previous
  lineup, remaining bank, and exclusions.
- `live_lineup_score.py --fetch` caches live race-week scores from the
  third-party `f1fantasytools.com/api/live-scoring` endpoint into
  `data/live/live_asset_scores.csv`; `--fetch --clipboard` and
  `--fetch --input FILE` are the fallbacks when that site changes or is
  unreachable. `--interactive` scores a chosen lineup from the cache.
- `best_live_lineup.py` merges the live cache with official `last1_price`:
  `budget` mode finds the theoretical best live lineup, `transfers` mode
  optimizes from the previous lineup after penalties. It rejects a live cache
  from a different race than the official target round, and labels
  non-finalized scores as provisional.

Live scores are observation-only until the race week completes; never feed
them into budget or rolling-score state.

## References

- Read `references/race-week-runbook.md` to execute an actual race-week request
  from saved state and public evidence through to the final recommendation.
- Read `references/public-data-access.md` before asking for screenshots or
  changing public-feed data acquisition.
- Read `references/price-model.md` before changing price-change calculations or
  onboarding a season at an arbitrary round.
- Read `references/strategy-workflow.md` before giving race-week lineup, chip,
  budget-building, or three-team portfolio advice.
- Read `references/forecast-model.md` for probability-based forecasts, scoring
  expectations, uncertainty, and forward lineup optimization; its rules profile
  is `references/scoring-2026.json`.
- Read `references/circuit-profiles.json` for fixed circuit coefficients, aliases,
  rationales and public sources. Revise/version this table only when maintaining
  the model, not as a weekly acquisition step.
- Read `references/forecast-inputs.md` for the v1 `run` workflow, reproducible
  source snapshots, practice/news inputs, grid penalties and `--allow` selection.
