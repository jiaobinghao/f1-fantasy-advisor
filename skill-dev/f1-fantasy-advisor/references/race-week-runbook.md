# From a race-week request to a computed recommendation

Use this when the user asks to calculate this week's lineup or compare transfers.
The model collects and extracts evidence, prepares inputs and interprets results;
`fantasy_forecast.py run` generates probabilities, scores and searches lineups.
The user need not author JSON or supply public statistics. The workflow needs no
model API key. Schemas live in [forecast-inputs.md](forecast-inputs.md); formulas
and account constraints live in [forecast-model.md](forecast-model.md).

## 1. Establish the target and available state

Read the workspace README and available `data/assets_state.csv`,
`data/race_scores.csv`, `data/team_state.csv`. Also read
`data/strategy_preferences.md` if present. Inspect existing run inputs for useful
sources, but do not treat their target, timestamps or account states as current.

Refresh public metadata when making a current recommendation:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
```

Read `official_round_context.csv` for season, target gameday, race and sessions;
cross-check the official event schedule and the Fantasy deadline. For this
pipeline `target_round` is the integer Fantasy GamedayId used by its histories,
not a race-page URL ID or another website's round index. `first_session_start`
can be FP1 and is not automatically the lock time. Verify `standard` versus
`sprint`, and use a timezone-aware `lock_at`. The program does not discover the
target or deadline from the phrase "this week".

Before lock, proceed with v1. After lock, distinguish a historical replay from
live-score observation; v1 does not provide executable post-lock/Final Fix
advice. A historical replay requires evidence actually available at its cutoff.

## 2. Build the current three-team input

Prepare a run-specific `teams.json` with `schema_version: 1` and `teams: [...]`.
The program does not automatically read or convert `team_state.csv`. Select the
latest confirmed snapshot for each managed team; row order alone does not prove
freshness. Map names to current public asset IDs, not remembered IDs.

| Forecast field | Source and interpretation |
| --- | --- |
| `team_id` | Preserve the actual managed team identifier. |
| `previous_lineup` | Split the CSV's comma-separated `lineup_asset_ids` into seven string IDs. Despite the name, this must be the currently saved roster after any submitted changes. |
| `bank` | Confirmed unspent balance at this decision point. `budget_before` may supply it only if its meaning and freshness are established. Do not substitute total squad value or automatically take `budget_after`. |
| `free_transfers` | Remaining free transfers, integer 0-3. The CSV has no dedicated column. Use an explicit saved fact or obtain it from the current account. If the UI explicitly shows used transfers as "1 of 3", remaining is 2. Do not assume every team has 2. |
| `penalty_already_incurred` | Positive magnitude of the already incurred deduction; a stored -10 becomes 10. Confirmed zero is valid; unknown is not zero. Submitted transfers must not be counted again. |
| `chip` | `none` only when no chip is active. Do not silently clear an active chip to make v1 run. |
| `notes` | Record account snapshot time/source and any confirmed field interpretations. These notes are provenance for the model, not parser-enforced freshness checks. |

An explicit user-confirmed official transfer-accounting baseline takes
precedence over the default current-roster interpretation. Use its matching
bank, free allowance and incurred penalty together, and state that basis in
the report. Do not replace a confirmed baseline merely because the screenshot
comes from an earlier round.

Record newly supplied account facts with `fantasy_state.py record-team`,
preserving other known fields when replacing the same round/team row. Store
remaining free transfers and their observation time explicitly in `--notes`
and the run's `teams.json`; do not invent a `record-team --free-transfers` option.
See [forecast-model.md](forecast-model.md#teamsjson) for the JSON example and
optional constraints. The 2x choice is optimized before lock; the saved boost
does not constrain the optimizer.

If a team lacks a required private fact, ask only for that fact and continue
collecting public data. Run the known teams and flag omissions, or omit `teams`
entirely for asset forecasts. Do not fill gaps with demo accounts, assume cash
from an old screenshot, or replace an unknown current team with a fresh-budget
search. Existing `ReplayT*` inputs remain `state_status: simulation_only`.

## 3. Collect this weekend's evidence

Use `public` collection for current feeds, or normalized `input` for a sourced
export. The routine `fetch_fantasy_public.py` CSV export does not include all
event history needed by the generator; `run` fetches the per-asset histories.
Do not derive event probabilities from total-score CSVs alone.

Public fixtures identify the target physical circuit. Resolve its name/alias in
`circuit-profiles.json`; the program reads the fixed coefficient without new
circuit research or historical aggregate imports. Check the selected rationale
and flag low-confidence entries. Unknown circuits use a neutral 50% grid weight
and a warning; a documented sensitivity override uses `circuit_difficulty`.
Do not match a relocated race by its Grand Prix title. The table's assessment
date/version must be disclosed if using it in a retrospective replay.

Find official result-page links for completed FP sessions and supply their
rankings through `public.practice`. Verify event, season and session in
`title_contains`. Include only completed sessions before the cutoff; never
invent an FP3 result. No practice data is allowed as a disclosed historical
baseline. Keep reserve-driver identities separate.

Read official team comments and penalty reports. For each relevant fact, retain
the exact quote, publication time and source. Write practice corrections to
`news.json` as a JSON array, and penalties to `grid.json` as an object with
`events`. Register article sources in `sources` and reference their IDs in the
facts. Use only `incident_compensation`, `handling_instability` and grid events
under v1; input schemas and examples are in `forecast-inputs.md`.

Empty `[]` or `{"events": []}` means no applicable facts were supplied. It does
not prove that news was checked. Record coverage or unavailable sources in a
local run note and explain that limitation in the recommendation. Unknown
publication times cannot enter a time-restricted forecast. Unverified penalties
are not confirmed, and expected penalties do not acquire invented probabilities.

## 4. Write a real run config

Keep inputs together, for example under `data/forecast/<season>/<round>/inputs/`.
For real data, start a fresh config instead of reusing a fictional example's
`synthetic: true`, drivers, dates or 256-sample override. Omit `synthetic` or set
it to false; the default simulation size is 8192.

The following is a structural template. Replace all angle-bracket values with
verified values; `season` and `target_round` must become JSON integers:

```json
{
  "schema_version": 1,
  "season": "<INTEGER_SEASON>",
  "target_round": "<INTEGER_GAMEDAY_ID>",
  "format": "<standard_OR_sprint>",
  "lock_at": "<VERIFIED_ISO_TIME_WITH_TIMEZONE>",
  "public": {"practice": []},
  "teams": "teams.json",
  "allow": 10
}
```

Populate practice and news sources using `forecast-inputs.md`; the empty
practice list is a historical-only starting point. The normal public feed
endpoints are defaults, so `public.web_config` need not be repeated. Add
`sources`, `news_input` and `grid_input` when supplying article-derived facts.
For cached JSON descriptors, `observed_at` is the real snapshot time and
`source_ref` describes the source; it is not an arbitrary pre-lock timestamp.

Choose live acquisition or replay explicitly. Live acquisition omits `as_of`
and uses URL descriptors; the program freezes the cutoff when acquisition
finishes. Replay supplies `as_of` and cached `path` descriptors for every source,
then uses `--offline`. A newly fetched page cannot be backdated to an old cutoff.
Confirm that the season's scoring and grid profiles apply; currently shipped
2026 grid rules pin Issue 06 and do not automatically track later revisions.

## 5. Run and inspect

Commands below use placeholders for the prepared config and a new output
directory. Paths inside the config resolve relative to that config; command-line
paths such as `--teams` resolve from the shell's working directory.

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py run \
  --config <INPUT_DIR>/run_config.json --allow 10 --out-dir <NEW_RUN_DIR>
```

Add `--offline` for a fully cached replay. Successful execution prints JSON with
`status: complete`. Inspect `run_manifest.json` and `data_quality.json`; on a
failure inspect saved diagnostics when present and correct the input rather
than deleting validation checks. Do not overwrite a prior run to hide changes.

Read `advisor_input.json` first, then `lineups.json`, `model_parameters.json`
and relevant `grid_penalty_impacts.json` branches. Inspect scoring categories
in `component_probabilities.csv` when explaining a driver or constructor.
Confirm the target, cutoff, three-team coverage, account status and budget
availability. Never present a `simulation_only` recommendation as actionable.

To change only the allowed point loss, reuse the frozen scenarios:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py optimize \
  <RUN_DIR>/forecast.json --teams <CURRENT_TEAMS_JSON> --allow 0 \
  --out <NEW_LINEUPS_JSON>
```

Reuse requires the same current price/evidence snapshot. New practice, news,
entrants or prices require updating inputs and running a new forecast.

## 6. Explain the computed choice

For detailed forecasts, use the following report order in the user's language.
Save the full report in the private run directory and include the asset tables
and both choices for all managed teams in the user-facing answer. A file link
does not replace the requested tables. Use human-readable names, not asset IDs.

### Context and conclusion

State the target season/round, information cutoff with timezone, lock time,
completed practice sessions, chip mode, sample count and `allow`. Identify live
pre-lock advice versus retrospective or conditional analysis. Confirm each
team's roster baseline, remaining free transfers and bank from saved facts.
Lead with the main computed recommendations and the evidence that could change
them. Verify withdrawals/replacements against actual sporting entries and the
Fantasy scoring treatment; stale active-card flags alone do not establish that
a driver will race. State any unresolved treatment before the numerical tables.

### Full asset tables

Show separate driver and constructor tables, sorted by expected raw points:

| Driver | Current price (M) | Expected points | Mean qualifying position | Mean race start | Mean classified race finish | Expected price change (M) | Price-fall probability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |

| Constructor | Current price (M) | Expected points | Expected price change (M) | Price-fall probability |
| --- | ---: | ---: | ---: | ---: |

Include every active asset, not only shortlisted picks. Explicitly list any
withdrawn asset or replacement with unavailable estimates and the reason. Use
`assets.json` for current prices and `expected_assets.csv` / `advisor_input.json`
for `mu`, `expected_price_change`, `p_fall` and `price_available`. Round prices to
0.1M, points and expected price changes to two decimals, and probabilities to
one decimal percent; use unrounded values in all comparisons. Show a sign on
price changes. Unknown values are N/A, never zero. Driver/constructor points
are raw: no 2x and no account transfer deductions. Expected price movement is
a probability-weighted mean of discrete changes, not a guaranteed settlement.

Join `expected_driver_positions.csv` or `advisor_input.json`'s
`driver_positions` by `asset_id`, and show position means to two decimals.
They are probability-weighted conditional means of the same final joint
scenarios, including penalties and any weighted penalty branches. Qualifying
means require a classified qualifying position; race start means include only
non-DNS outcomes with a known starting position; race finish means require a
classified race position. Explain these conditions and do not substitute last
place for NC/DNS/DSQ. Report N/A for zero available probability, and disclose
materially low position-availability probabilities. These means are not
guaranteed finishing positions or substitutes for full outcome distributions.
For Sprint weekends also show Sprint start and classified finish means as
separate columns or a separate table; do not imply v1 separately models Sprint
qualifying. See [forecast-inputs.md](forecast-inputs.md#read-the-results) for
the output field names and exact denominators.

### Two options for each managed team

For Team 1, Team 2 and Team 3 independently, show `score_best` as the points
option and `budget_best` as the budget-preservation/growth option. In Chinese,
use "得分方案" and "保价/增值方案". The latter maximizes expected price growth
within the allowed net expected-point loss; it does not minimize the chance of
losing value and does not guarantee protection. When they coincide, explicitly
say so while retaining both labels. If growth is unavailable, explain the
missing inputs and report the points option without inventing a budget result.

| Metric | Points option | Budget-preservation/growth option |
| --- | --- | --- |
| Five drivers | Complete names; mark 2x | Complete names; mark 2x |
| Two constructors | Complete names | Complete names |
| Transfers out / in | Explicit names | Explicit names |
| Transfer count / free allowance / points deducted | Values | Values |
| Expected net points | `mu` | `mu` |
| Points sacrificed versus score optimum | `loss_vs_best` | `loss_vs_best` |
| Expected lineup value change (M) | `expected_budget_change` | `expected_budget_change` |
| Cash after transfers (M) | `bank` | `bank` |
| Expected total value after settlement (M) | `expected_total_value` | `expected_total_value` |
| Simulated P10 / P50 / P90 net points | `p10` / `p50` / `p90` | `p10` / `p50` / `p90` |

Read these fields from `lineups.json` or `advisor_input.json`. Net points already
include the fixed 2x choice and all modeled transfer deductions; do not subtract
fees again. Cash left after purchases is separate from expected price growth.
Total value after settlement includes both the lineup and remaining cash.
Quantiles describe modeled outcomes, not confidence intervals for the mean.

Compare each option against `baseline` and `best_free`, reporting their net
points and expected growth. The no-transfer baseline reoptimizes 2x; disclose
that when comparing it with the screenshot's boost. An inactive holding can
make this baseline unavailable; do not manufacture a retention score.
`recommended` selects the budget result when available; `top` remains sorted
by points and must not be mistaken for the budget search. Explain why any paid
transfer improves the overall combination, using the best-free comparison.

### Reasons, limitations and reproduction

Explain practice corrections with their cited quotes, penalty effects using
paired comparisons, and conditional recommendations when penalty probabilities
are unknown. Mention material sample fallbacks and uncalibrated parameters.
Inspect `model_parameters.json` for `circuit_models` (fixed difficulty, effective
grid weight, table version/content hash, sources, confidence and fallback) and `overtake_models` (gain/overtake ratio,
actual training rounds, pool and extrapolation). A q pool uses recent positive-
gain races, which may be older than the driver's last four completed races.
Level/losing finishes and started NC use empirical counts; gain-linked counts
use stochastic rounding and do not yet model additional conditional variance.
Use the computed values; new evidence belongs in a rerun, not an LLM adjustment
to the resulting means. Finish with the output path and exact command used so
the user or a later model can reproduce the calculation. Distinguish a live
refresh command from replaying the frozen sources. A forecast does not execute
transfers or update the recorded account roster.
