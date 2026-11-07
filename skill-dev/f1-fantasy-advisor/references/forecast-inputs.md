# Running the v1 probability and budget pipeline

Use `scripts/fantasy_forecast.py run` for pre-lock predictions. It supports ordinary and Sprint weekends, normal fixed 2x, source snapshots, practice-rank adjustments, grid penalties, circuit-dependent finishing order, gain-linked overtakes, and per-team budget building. No API key or model API is required: the advising model extracts cited news into the structured inputs; Python estimates probabilities and scores them.

For an actual "calculate this week" request, follow [race-week-runbook.md](race-week-runbook.md) first. It explains how to determine the target/deadline, prepare current team JSON from local facts, obtain evidence and read the output. This document defines the detailed input contract. `run` does not automatically convert `team_state.csv` or search news.

## Try the full workflow

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py example-run --out-dir data/v1-example
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py run --config data/v1-example/run_config.json --offline --out-dir data/v1-example/result
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py optimize data/v1-example/result/forecast.json --teams data/v1-example/teams.json --allow 0
```

`example-run --format sprint` creates the Sprint version. Every example observation, news item, account and price is fictional. Existing `example/evaluate/validate/estimate/calibrate/optimize` commands remain available. `--allow` defaults to 10; `run` can also take it from its config. Existing non-normal chip scenarios can still be evaluated separately; the new `run` rejects active chips.

Each output directory must be new or empty. Config-relative paths work from any working directory. `run` never updates the private account state, executes transfers or overwrites previous reports. Use the latest confirmed account snapshot, not a stale screenshot after the user has already submitted changes.

## Config and source descriptors

Start with the generated `run_config.json` and replace the fictional input. Top-level keys:

- `schema_version: 1`, `season`, integer `target_round`, `format: standard|sprint`, `lock_at` with timezone.
- `as_of`: explicit information cutoff for replay. Omit it for live acquisition; it is frozen when acquisition finishes, before lock.
- `input`: a source descriptor for normalized JSON, **or** `public`: public collection settings. Choose one.
- `sources`: optional mapping from source ID to descriptor, for news articles/official decisions. IDs use letters, digits, `_` and `-`.
- `news_input`, `grid_input`, `history_prior_input`: optional JSON source descriptors overriding those sections of the normalized data.
- `circuit_id`: optional target physical circuit ID/name. Public collection discovers `identity(CircuitOfficialName)`; lookup accepts the fixed table's aliases, ignoring case, accents and punctuation. Conflicting physical-circuit overrides fail. Do not infer a circuit from a relocated Grand Prix title.
- `circuit_profiles_path`: optional local path to a versioned table, relative to the run config. Defaults to the skill's `references/circuit-profiles.json`; use a saved `circuit_profiles.json` to reproduce a prior table. It is a model input, not a freshly fetched source. Legacy `circuit_history_input` imports are rejected.
- `teams`: optional path to `schema_version: 1, teams: [...]`. `--teams` overrides it. Without accounts, produce asset forecasts only.
- `rules_path`, `grid_rules_path`: optional paths to season-specific profiles. The shipped 2026 grid profile pins FIA Section B Issue 06, articles B2.3.4/B2.5.4; verify applicable revisions instead of calling it the latest issue.
- `prices_observed_at`, `allow`, `model_parameters`: optional overrides. The rule season and complete active field must match.

Cached source descriptor:

```json
{
  "path": "sources/friday.html",
  "source_ref": "https://www.formula1.com/en/latest/article/ACTUAL-ARTICLE",
  "observed_at": "2026-10-31T08:00:00Z"
}
```

For a live public fetch, use `{"url": "https://..."}`. Under `sources`, use `format: "json"` for JSON; otherwise HTML/text is cached. Every response is copied into `raw/` with a hash and timestamp. A supplied snapshot timestamp is recorded as declared evidence, not independently verified. News publication, result completion and prior availability cannot postdate their cited source snapshot or the run cutoff. Newly fetched pages cannot be backdated to an earlier forecast cutoff. `--offline` forbids URL-only sources.

## Public collection

`public` can fetch configuration, current assets and per-asset history from the established Fantasy feeds. The existing feed-export commands still work; `run` adds normalized event/session outputs without changing those CSV contracts.

```json
{
  "public": {
    "web_config": {"url": "https://fantasy.formula1.com/feeds/v2/apps/web_config.json"},
    "practice": [{
      "session": "fp2",
      "completed_at": "2026-10-31T00:00:00Z",
      "title_contains": ["2026", "Mexico", "Practice 2"],
      "source": {"url": "https://www.formula1.com/en/results/2026/races/1298/mexico/practice/2"}
    }]
  }
}
```

Use the actual season's race-page links, not a guessed race ID. Instead of `source`, a practice entry can supply `discover` (source descriptor for the actual race results page) and `link_suffix` such as `/practice/2`; discovery must identify exactly one link. The HTML parser checks the result table and supplied title terms. FP ranks include reserves; their results are never assigned to the regular driver.

Offline/public overrides are `statistics`, `assets` (JSON asset list), `histories` (asset-ID to source descriptor), and `history_template` (descriptor whose path/URL may contain `{asset_id}`). Per-asset `IsActive` for the target weekend determines current eligibility. Session type is cross-checked with event names, including Sprint events labeled Sprint Qualifying. Unknown events and inconsistent totals fail with diagnostics. Zero-point event records are retained; an empty weekend event list is not invented as a zero price input.

Historical starting positions can be reconstructed from classified finish plus signed position points where uncapped. NC grids and capped Sprint losses stay unknown unless normalized official data are supplied. This limits comparable traffic samples and is reported. Snapshot times are completion upper bounds, not invented exact finish times.

## Normalized JSON input

The `input` JSON contains these arrays/objects. Register every `source_ref` in `sources`; `input` itself is a registered source for a self-contained, sourced export.

| Key | Required row fields |
| --- | --- |
| `assets` | `asset_id, type, name, price`; drivers also `person_id, constructor_id`. Optional `active`, `selectable`, `aliases`, `price_history`. Keep historical identity distinct from Fantasy cards. |
| `history` | `round, session, asset_id, person_id, constructor_id, field_size, status, position, start_position, started, completed_at, source_ref`. Race/Sprint rows also have nonnegative integer `overtakes`, boolean `fastest_lap, driver_of_day`. |
| `practice` | `asset_id` (null for reserves without a card), `person_id, session, rank, field_size, completed_at, source_ref`. Use `fp1/fp2/fp3`; an unranked participant has `rank: null`. |
| `pits` | `round, constructor_id, mode, source_ref`, nullable boolean `had_stop`. Proxy rows have `band_points: 0|2|5|10|20`; measured rows have `stationary_seconds`. |
| `news` | Practice corrections described below. Defaults to an empty list. |
| `grid` | Penalty facts and optional official orders described below. Defaults to an empty object. |
| `circuit_id` | Optional target physical circuit name/ID accepted by the fixed table. |

`session` is `qualifying/race/sprint`; status is `classified/nc/dns/dsq`. Nonclassified rows have `position: null`; absent data are null, not zero. `started` can be unknown for NC, but estimating the NC/DNS split requires some actual start evidence. DNS/DSQ have no eligible awards or overtake rewards. Do not label all retired drivers NC if the official results still classify them.

Historical session rows may include `circuit_id`; public collection supplies it from `CircuitOfficialName`. These rows still train driver history, but no longer train circuit coefficients. The packaged fixed table supplies circuit difficulty; do not collect full-event overtaking aggregates for this purpose.

A confirmed replacement before all scoring sessions can be represented in a sourced normalized input. Retain the withdrawn Fantasy asset with `active: false` and its actual selling price for transfer accounting. Add the real replacement as an active driver with their own `person_id`, history and practice identity. If no Fantasy card/price is available, use a distinct local entrant ID, `selectable: false`, `price: null` and no invented price history. This entrant participates in the full-field and constructor scoring, but cannot be bought and has no price forecast. Their missing price does not disable budget optimization for selectable assets. Do not transfer the withdrawn driver's practice ranks or identity to the replacement. The withdrawn holding has no retention baseline in v1; report sourced non-participation penalties separately. This does not support changing drivers between scoring sessions. Public collection does not apply these overrides automatically: retain the announcement, scoring rule and transformation notes.

`price_history` is exactly two records `{round, points, settled_at, source_ref}` from the two latest settled weekends. Missing inputs leave prices unavailable and disable the budget recommendation if any legal lineup might contain an unknown asset. Point forecasts still run. `previous_rounds` in config can name the last two settled rounds when the calendar has cancellations; public collection derives them from settled history.

If a same-season status pool is unavailable, `priors` needs `source_ref`, `available_at`, and session objects containing `status: {classified, nc, dsq}` probabilities. An evidence-backed `nc_started_probability` may cover the missing NC/DNS split. Prior probabilities are explicit model inputs, never inferred universal F1 base rates. Overtake and pit sample distributions must still have actual support.

Measured pit rows may include the complete `stops: [{order, seconds}, ...]`, where order is a comparable chronological coordinate for the whole race, and the minimum equals `stationary_seconds`. With `pit_record: {seconds, source_ref, available_at}`, record setters are derived chronologically. Without full chronology and a pre-weekend record, record probability is unavailable; proxy seconds never create record bonuses. Empirical resampling cannot generate unseen faster stops.

## News extraction standard

Read the actual source, retain an exact quote and publication time, and emit only these practice tags:

```json
{
  "incident_id": "driver-fp2-damage",
  "tag": "incident_compensation",
  "person_ids": ["real-person-id"],
  "affected_sessions": ["fp2"],
  "quote": "Exact source quote describing the disruption",
  "published_at": "2026-10-31T01:00:00Z",
  "source_ref": "friday"
}
```

`handling_instability` requires explicit handling/balance/difficult-to-drive evidence. Generic statements about room to improve do not qualify. `constructor_id` without `person_ids` applies to both drivers only when the evidence concerns both cars. Each tag is applied at most once per driver/session, including reposts and overlapping team/individual reports. Defaults are +2/-2 rank-equivalent points, clipped to the field range. They are not direct Fantasy points or reliability adjustments. Missing ranks with incident evidence use the forecast session's own historical performance with no extra +2: qualifying history for qualifying pace, race history for race pace, and Sprint history for Sprint pace. Otherwise missing practice uses history. Include a sourced practice row with `rank: null` for a confirmed unranked participant. News targeting a wholly absent practice row is flagged and does not invent participation.

Grid facts belong in `grid.events`, separately from practice corrections:

```json
{
  "event_id": "driver-race-power-unit",
  "revision_id": "decision-1",
  "active": true,
  "asset_id": "driver-card-id",
  "session": "race",
  "penalty_type": "grid_places",
  "places": 20,
  "status": "confirmed",
  "rule_ref": "Applicable FIA decision/article",
  "quote": "Exact source quote establishing the grid penalty",
  "published_at": "2026-10-31T01:00:00Z",
  "source_ref": "penalty-report"
}
```

Penalty types are `grid_places/back_of_grid/pit_lane`; statuses are `confirmed/expected/unverified`. Replacing an engine does not itself establish a penalty. `supersedes` names the prior revision; `active: false` cancels the fact. Multiple component penalties accumulate; duplicate facts do not. Only the named race/Sprint is affected, and qualifying points stay unchanged.

One expected event may supply `probability`, `probability_method`, `probability_source`. Without justified probabilities, report separate conditional branches. Multiple expected events are not assumed independent: provide `grid.joint_branches: [{active_events, probability}]`, `joint_probability_method` and `joint_probability_source`, or inspect the unweighted branches. More than six uncertain events require explicit branches.

`grid.official_orders[session]` contains `asset_ids` in order, `published_at`, `source_ref`, and `applied_event_ids`. The applied events must match the branch, preventing double penalties or silently ignoring a new penalty. Fixed official grids cannot be inverted for a no-penalty counterfactual; the impact report marks that attribution unavailable. Use a simulated pre-penalty grid for that comparison. Pit-lane starts require `pit_lane_convention: {method: "ordered_after_grid", source_ref}` and, if multiple, `pit_lane_order`; extra pit-exit delay remains a disclosed limitation.

## Probability and selection defaults

`model_parameters` accepts `window=4`, `decay_mode="linear"`, `half_life=2`, `prior_strength=8`, `practice_weight=0.4`, `fp_weights={fp1:0.2,fp2:0.3,fp3:0.5}`, `incident_bonus=2`, `instability_penalty=2`, `temperature=3`, `circuit_difficulty=null`, `min_effective_samples=3`, `samples=8192`, `seed=42`. Explicit config values override defaults. Parameters are uncalibrated and are always exported. Grid weights are fixed to the mapping `g=0.2+0.6*d`; its endpoints are not tunable parameters. An explicit difficulty in `[0,1]` overrides the table and is labeled `configured_scenario`.

The user-selected default takes the latest four valid rounds within each estimation pool, including the latest four Sprint weekends for Sprint samples. Sort distinct valid rounds newest first, giving ages `j=0,1,2,3`, and assign `w_j=max(0,1-j/(2*half_life))`: **1, 0.75, 0.5, 0.25**, or 40%, 30%, 20%, 10% after normalization. Multiple drivers from the same round share its age; missing sessions are not zero observations. Status likelihoods, historical ranks, NC start evidence, awards, overtakes and pits use this weighting. Prior pools remain separately documented; these percentages are not the total model's mixture weights.

`half_life` in linear mode denotes the distance in valid observations from weight 1 to weight 0.5. This is not exponential halving. To reproduce the earlier calendar-round method, explicitly set `decay_mode="exponential"` and the original `half_life`; then `w_t=2^(-((target_round-1)-t)/half_life)`. Do not silently substitute exponential weights for the specified four values. Per-model audits export `rounds` and aligned `sample_weights`.

Qualifying, race and Sprint have separate historical pace scores. Each uses only classified results from its own session type, including constructor fallbacks. Race/Sprint finishing ranks are performance proxies, not measured lap pace with strategy and traffic removed. Observed FP ranks and news corrections supply the same practice evidence to each model; only an incident fallback for a missing FP rank depends on the forecast session. With available practice, the default blends are:

```text
A_qualifying = 0.6 * H_qualifying + 0.4 * F_qualifying
A_race       = 0.6 * H_race       + 0.4 * F_race
A_sprint     = 0.6 * H_sprint     + 0.4 * F_sprint
strength_session = exp((A_session - field_size) / temperature)
```

Without usable practice, `A_session = H_session`. The practice weight is shared configuration, not a second independent observation of the history. Missing-rank incident fallbacks can therefore leave that session's blended score equal to its historical score.

The model smooths classified/NC/DSQ frequencies and draws separate complete Plackett-Luce pace orders from these strengths. Qualifying uses qualifying strength; race and Sprint recovery use their respective strengths. Classified finishers are sorted by `g_c*grid + (1-g_c)*pace_rank`, breaking ties by starting position; the resulting ordinal finish `F`, not the sorting key, determines position gains.

Load `d_c` from `references/circuit-profiles.json`, then calculate:

```text
g_c = 0.2 + 0.6 * d_c
pace_weight = 1 - g_c
```

`d=0 / 0.5 / 1` gives grid weights `20% / 50% / 80%`. The coefficients are fixed editorial assessments informed by the linked circuit guides and historical examples, not fitted probabilities or optimal weights. The table includes its rubric, aliases, rationale, confidence and sources. Race and Sprint share the same coefficient in v1. Unknown tracks use `d=0.5` and a warning. An explicit `circuit_difficulty` overrides the selected value but preserves the original table value in the audit. Review/version the table for significant layout/rule changes or better evidence; weekly runs never solve it again.

For a positive classified position gain `D = G-F > 0`, estimate:

```text
q_i = sum(w_t * (G_t-F_t)) / sum(w_t * O_t)
mean_overtakes_i = D / q_i
O_i = floor(mean_overtakes_i) + Bernoulli(fractional_part(mean_overtakes_i))
```

Use only classified historical rows with known grids and positive gains, selecting their latest four valid rounds per pool. Retain rows with zero overtakes. Prefer driver history; if effective sample size is below 3, try the current constructor, then the field, within the same session type. Pooling weights rounds, not the number of distinct drivers. Use the ratio of weighted sums, not the mean of per-race ratios. If all supported overtake counts are zero, `q_status=infinite`, `q=null`, and the overtake rate is zero; no division by zero occurs. If no pool is sufficient, mark the ratio unavailable and sample classified overtake history instead. Gains beyond the training range are flagged. Stochastic rounding preserves the estimated mean while producing integer scoring events; additional conditional variance has not been fitted.

For classified level/losing finishes (`G-F <= 0`), sample recent non-gaining classified overtake history, trying driver, constructor, then field. If no such records exist, use same-status history and report the relaxation. Started NC uses started-NC history with the same pool fallbacks; DNS/DSQ gives zero. Thus level finishes and retirements can still earn overtakes. There is no extra circuit multiplier or old 0.6 thinning: circuit influence reaches positive-gain overtakes through `g_c -> F -> D -> D/q`. All assets share scenarios and constructor results derive from their drivers. Award winners are categorical and unique.

Legacy `circuit_factor`, `overtake_bandwidth`, `grid_weight`, `max_grid_weight`, `circuit_density_floor`, `circuit_history_input` and normalized `circuit_history` now fail with a migration message. Remove them when adopting the fixed table. Set `circuit_difficulty=0` for 20% or `=1` for 80% grid influence in sensitivity analysis. Old saved forecasts remain evaluable without rerunning their generator.

First compute the best net expected lineup score after fees, then maximize estimated price growth over **all** legal lineups within `--allow` points of that optimum. The default is 10; zero means score-first with growth as tie-break. Price changes use raw scenario scores before 2x and fees. The selected 2x driver is fixed across scenarios. Ties prefer score, fewer transfers, lower spend, then deterministic IDs. This is one-round budget building, not a solved season-long policy.

## Read the results

Start with `advisor_input.json`: asset means/price estimates, team recommendations, practice adjustments, penalty impact breakdown, citations and limitations. Read `grid_penalty_impacts.json` for conditional branches and paired comparisons, and `model_parameters.json` for priors, sample sizes and extrapolation. Its `circuit_models` exports the selected fixed profile, original table difficulty, actual difficulty/grid/pace weights, method, source URLs, assessment date and table version/content hash; `overtake_models` exports weighted gains/overtakes, q, rates, all attempted pools and fallback conditions. These replace the old `conditional_overtakes` audit. `circuit_profiles.json` saves the exact table values used. `table_content_sha256` hashes UTF-8 JSON serialized with `ensure_ascii=True, sort_keys=True, separators=(",", ":")`; whitespace changes do not change this content hash. A table assessed after the cutoff is flagged as a retrospective model revision, not frozen pre-lock evidence. `forecast.json` can be re-evaluated and optimized with another allow value without re-sampling.

In `model_parameters.json`, `models["qualifying:<asset_id>"]`, `models["race:<asset_id>"]` and, when applicable, `models["sprint:<asset_id>"]` each export `history_score`, `practice_score`, effective `practice_weight`, `combined_score` and `strength`. Their `pace_history` objects identify the historical `session`, `score`, `fallback`, `rounds`, `sample_weights`, `sample_count`, `effective_sample_size` and `source_refs` actually used for pace. These can differ from the enclosing status sample audit, especially after constructor fallback. `practice_adjustments.csv` has one row per driver/FP/`forecast_session`; `session` still identifies the original FP. Select the forecast session when reading adjustments rather than counting those rows as additional practice observations.

Other outputs include `component_probabilities.csv`, `asset_score_distributions.json`, `price_distributions.json`, `lineups.json`, normalized input tables, cached raw evidence, effective config, rules, teams and `run_manifest.json` with hashes. Failures preserve `data_quality.json` and a failed manifest. Report baseline/scenario labels honestly. Do not turn passing structural tests or thousands of Monte Carlo draws into a claim of calibrated predictive accuracy.

`run` writes `expected_driver_positions.csv` and the same rows under
`advisor_input.json`'s `driver_positions`. Each active sporting driver,
including a non-selectable replacement, has `asset_id`, `name`, and fields:

| Session | Conditional mean | Probability of an available position |
| --- | --- | --- |
| Qualifying | `mean_qualifying_position` | `p_qualifying_position_available` |
| Race start | `mean_race_start_position` | `p_race_start_position_available` |
| Race finish | `mean_race_finish_position` | `p_race_finish_position_available` |
| Sprint start, when modeled | `mean_sprint_start_position` | `p_sprint_start_position_available` |
| Sprint finish, when modeled | `mean_sprint_finish_position` | `p_sprint_finish_position_available` |

For each field, sum scenario probability times position and divide by the
probability of scenarios with an eligible position; report the denominator
alongside limitations. Qualifying requires `status=classified` and a position.
Start requires `status != dns` and a known start position; classified, NC and
DSQ starters can contribute. Finish requires `status=classified` and a
position. A zero denominator produces null, not zero or last place. The main
forecast's actual scenario probabilities are used, including probability-
weighted penalty mixtures; unweighted conditional branches are not silently
averaged. The v1 Sprint generator has Sprint start and finish outcomes but no
separate Sprint qualifying position. Older runs predate this export: derive
the same weighted values from their saved `forecast.json` or rerun the saved
inputs into a new output directory, without presenting a refreshed feed as an
old frozen snapshot.
