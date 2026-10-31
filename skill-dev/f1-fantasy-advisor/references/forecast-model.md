# Auditable F1 Fantasy Forecasts

Read this before predictive lineup or chip evaluation. The implementation is
`scripts/fantasy_forecast.py`, with a versioned rule profile in
`references/scoring-2026.json`. All commands use Python's standard library.

Contents: scope; mathematics; probability standard; coherent scenarios; input
contracts; commands; reporting and limits.

## Scope And Meaning Of "Best"

Use the same pipeline at every standard or Sprint round:

```text
timestamped evidence -> probability model -> joint weekend scenarios
-> official category scores -> asset expectations -> legal lineup search
```

The tool computes the exact best expected-score lineup **conditional on the
generated or supplied scenarios, prices, rule version, and transfer constraints**.
The implemented v1 `run` estimates probabilities from normalized public event
history and practice ranks, applies sourced news/grid adjustments and generates
joint weekend scenarios. Read [forecast-inputs.md](forecast-inputs.md) for that
pipeline's inputs and defaults; the contracts below also support the original
manual-scenario tools. An LLM extracts evidence; Python estimates and scores it.
The uncalibrated defaults do not establish true probabilities or predictive skill.
The current `run` default uses four valid rounds with linear weights
`1, 0.75, 0.5, 0.25` (`decay_mode=linear, half_life=2`). The standalone
`estimate` command below retains its explicitly configured exponential estimator.
Qualifying, race and Sprint pace use separate session histories, each blended
with 40% practice evidence when available. Incident fallbacks for missing FP
ranks also use the matching session's history. Race/Sprint pace is a proxy from
finishing ranks, not cleaned lap times. Fixed assessments in
`circuit-profiles.json` set the finish-order grid weight by `g=0.2+0.6*d`,
covering 20%-80%. Race and Sprint share a coefficient; unknown circuits use
a flagged neutral 50%. No circuit statistics are fitted during weekly runs. Positive position
gains drive overtakes through a historical gain/overtake ratio; non-gaining
finishers and started NC drivers use empirical fallbacks. The old 0.6 thinning
factor is removed. See `forecast-inputs.md` for formulas, circuit evidence,
per-session audit fields and migration of older configs.

For normal fixed 2x, selection now has two passes: compute the best net score,
then maximize expected raw-score price growth over all legal lineups satisfying
`mu >= mu_best - allow`. The default `allow` is 10. Report both `score_best` and
`budget_best`; `top` retains its score ordering. If any legally selectable asset
lacks price history, budget selection is unavailable and the score result remains.
This is a one-round growth objective, not an optimal season-long transfer policy.
The v1 generator uses only the documented history, practice and three news types;
broader weather/reliability/strategy methods below are manual extensions, not
features automatically inferred by `run`.

One season profile supports every ordinary/Sprint round of that season, not
automatic rule compatibility with future seasons. Review the official rendered
rules and change the profile/version when needed. Do not silently reuse rules.
The current profile expects the full 22-driver, 11-constructor field. It uses a
fixed two-driver roster per constructor throughout the scoring sessions. A
confirmed replacement before all scoring sessions can be normalized using
the entrant procedure in [forecast-inputs.md](forecast-inputs.md), including
an unpriced, non-selectable sporting entrant. A replacement
between Sprint and GP qualifying, changed qualifying format, or a special
scoring ruling needs an explicit schema/profile extension and tests first.
Final Fix/post-lock optimization is deliberately rejected. Season-wide chip
allocation and temporary Limitless shadow-team price growth are separate work.

## Mathematics

### From Category Probabilities To Asset Means

For asset `i`, scoring category `k`, and category points `v`:

```text
p_ik(v) = P(X_ik = v)
mu_ik  = sum_v v * p_ik(v)
S_i    = sum_k X_ik
mu_i   = E[S_i] = sum_k mu_ik
```

Linearity of expectation does NOT require independent categories or assets.
Probabilities within a category must sum to one. Include zero-point outcomes;
do not normalize only over positive events. For example, a 15% chance of an
NC penalty of -20 contributes `-3`, not a deduction from a mean that already
includes that same NC event.

For a standard weekend, the 2026 driver score is:

```text
D_i = Q_i + R_i + G_i - L_i + O_i + 10*FL_i + 10*DOTD_i
```

- `Q`: qualifying P1..P10 = 10..1, other classified positions = 0;
  NC/no time/DNS/DSQ = -5.
- `R`: race P1..P10 = 25,18,15,12,10,8,6,4,2,1, otherwise 0;
  NC/DNS/DSQ = -20 instead of finishing points.
- `G=max(start-finish,0)`, `L=max(finish-start,0)` only when classified;
  neither is charged again for NC/DNS/DSQ. Use Fantasy's official normalized
  grid position, including its pit-lane/grid-penalty convention.
- `O`: eligible overtakes, not net positions gained. An NC driver can retain
  eligible overtakes; DNS/DSQ has no positive session rewards.
- `FL`, `DOTD`: eligible session award indicators. Do not assume an F1 World
  Championship fastest-lap scoring condition is also a Fantasy condition.

Equivalently, expected race finishing/NC contribution is:

```text
E[R_i] = sum_(r=1..10) race_points[r] * P(classified and finish=r)
         - 20 * P(NC or DNS or DSQ)
E[O_i] = sum_(o>=0) o * P(eligible_overtakes=o)
E[G_i-L_i] = sum_(g,r) (g-r) * P(start=g, finish=r, classified)
```

On Sprint weekends add Sprint finish points `8..1`, NC/DNS/DSQ `-10`,
positions gained, positions lost capped at 10, overtakes, and fastest lap `+5`.
Sprint has no DOTD or pit-stop score. Sprint qualifying is not a scoring session.
Never add a historical Sprint total to an ordinary-weekend prediction.

For constructor `c` with actual drivers `a,b`:

```text
C_c = (D_a - 10*DOTD_a) + (D_b - 10*DOTD_b)
      + QProgress_c + PitTime_c + 5*FastestPit_c + 15*RecordPit_c
      - 5*N_qualifying_DSQ - 20*N_race_DSQ - 10*N_sprint_DSQ

mu_constructor[c] = E[C_c]
```

These DSQ deductions are additional to the driver NC contribution. Current
rendered tables take precedence over stale JavaScript fallback text and unused
translation notes. Reconcile scoring changes with public per-event history.

`QProgress` is one exclusive tier: neither in Q2 `-1`, one in Q2 `1`, both
in Q2 `3`, one in Q3 `5`, both in Q3 `10`. Use the highest applicable tier,
not their sum. Pit points use the team's single fastest race stop:
`<2.0s:20`, `<2.2s:10`, `<2.5s:5`, `<3.0s:2`, otherwise `0`.
Exactly 3.00s earns zero. Fastest-of-race and record bonuses are additional.
Record setters must beat the documented pre-weekend benchmark; when more than
one team breaks it, account for stop chronology rather than flagging every
sub-benchmark stop independently.

The constructor formula contains the same simulated driver outcomes used for
driver assets. A selected driver's 2x/3x does not multiply their constructor.

### Joint Uncertainty And Chips

Use full-weekend scenarios `s` with `p_s >= 0`, `sum_s p_s = 1`:

```text
mu_i    = sum_s p_s * S_i(s)
Var(S_i)= sum_s p_s * (S_i(s)-mu_i)^2
mu_L    = sum_s p_s * L(s)
Var(L)  = sum_s p_s * (L(s)-mu_L)^2 = w' * Cov(S) * w
```

The covariance identity applies to fixed linear multipliers. Calculate all
chips directly scenario by scenario. Report SD, weighted P10/P50/P90, and
`P(L<0)`. These describe outcome volatility **under the model**, not confidence
that the model is correct. Model/parameter uncertainty needs separate refits
or sensitivity scenarios. P10 is not a guaranteed floor.

For ordinary 2x, add one extra copy of the chosen driver's total. Select that
driver before lock by highest mean, not the best driver after each scenario.
For 3x, add two extra copies of the triple driver and one of a different normal
2x driver. The highest mean gets 3x, the second highest gets 2x.

```text
Autopilot bonus = E[max_(i selected drivers) D_i]
                 NOT max_i E[D_i]
NoNegative asset score(s) = sum_k max(X_ik(s), 0)
                           NOT max(sum_k X_ik(s), 0)
```

For constructors, aggregate driver contributions to each constructor scoring
category before applying No Negative. Transfer penalties are never protected.
Correlated and anti-correlated drivers can have identical marginal means but
different lineup tails and Autopilot value; marginals alone cannot answer these.

### Legal Lineup Objective

With driver selections `x_i`, constructor selections `y_c`, current prices `v`,
remaining bank `B`, remaining free transfers `F`, and current saved holdings `H`:

```text
sum_i x_i = 5; sum_c y_c = 2; selections are binary
sum_i v_i*x_i + sum_c v_c*y_c <= sum_(a in H) current_price[a] + B
N_transfer = number of selected assets not in H
penalty = 10*max(0, N_transfer-F) + penalty_already_incurred
maximize E[sum_i x_i*D_i + sum_c y_c*C_c + boost_bonus] - penalty
```

The search enumerates all allowed active-asset combinations, not a greedy points-per-million
ranking. Price is a constraint; it is not an extra points reward. Default is
points-first, including premium drivers. Compare risk and price growth separately
unless the user supplies an explicit conversion from money to future points.

Wildcard removes new transfer fees; Limitless also removes the price constraint.
Both still report already-incurred penalties if supplied. Inputs must represent
the actual game/account treatment of previously incurred fees. Compare chips
against the same roster **without** a chip in a separate run to estimate chip
uplift; the optimizer's built-in no-transfer baseline uses the **same chip**.
Chip availability and future opportunity cost are not inferred.

`gain_vs_no_transfers` compares net points to retaining all holdings with its
boost reoptimized. `gain_vs_best_free` compares against the best lineup that
incurs no new fee. Do not recommend a paid transfer merely because its incoming
driver has higher raw points: account for the fee and the other transfer paths.
Top-K is ordered by mean, then fewer changes, then lower cost. Risk is reported,
not optimized: the best variance-penalized lineup need not be in this Top-K.

## Probability Standard: v1

### Evidence And Sample Rules

1. Freeze an `as_of` timestamp before the actual game's lock. Record all source
   URLs/file snapshots and when they were available. Current prices and rules
   need their own dates. Never use post-race actuals or updated prices to backtest
   a pre-race decision. A validation timestamp is not proof of historical access.
2. Prefer official Fantasy **event** histories for scoring labels; FIA/F1
   classifications and grids for positions; official timing/stints for pace;
   official team/penalty reports for current faults; a timestamped forecast for
   weather. Public Fantasy totals alone cannot identify event probabilities.
3. Count session opportunities, not laps as independent NC trials. Distinguish
   classified retirement (e.g. 90% distance) from Fantasy NC, DNS and DSQ.
   A missing field is not automatically zero; verify sparse feed conventions.
   Preserve zero-score weekends. Treat replacement/role changes explicitly.
4. Partition by session and outcome definition. Race/Sprint reliability and
   overtaking samples are not interchangeable. For pace, separate tyre, stint,
   fuel/run programme, track evolution and weather where data permits. Do not
   translate one FP ranking or "similar circuit" narrative into a precise
   probability without a fitted mapping or a labeled sensitivity case.
5. Record raw sample count, weighted exposure, effective N, prior source,
   hyperparameters, and exclusions. For pooled estimates use the same pool for
   comparable assets, and avoid using an observation in both prior and likelihood.
   Never select a window because it makes a preferred transfer look better.

### Reproducible Categorical Baseline

`estimate` implements a decayed Dirichlet/power-prior model. For disjoint outcomes
`k` (e.g. classified/NC/DNS/DSQ), base probabilities `pi_k`, prior strength
`kappa`, and past observation `j`:

```text
age_j = target_round - 1 - observation_round
w_j = reliability_j * 2^(-age_j/H)
n_k = sum_j w_j * I(outcome_j=k)
alpha_k = kappa*pi_k + n_k
p_hat_k = alpha_k / (kappa + sum_j w_j)
N_eff = (sum_j w_j)^2 / sum_j w_j^2
SD_parameter(p_k) = sqrt(p_hat_k*(1-p_hat_k)/(kappa+sum_j w_j+1))
```

All possible outcomes need positive prior mass. The most recent completed round
has age zero. Reliability weights are in `[0,1]`; verified complete labels get
1, excluded/unusable records get 0. Fractional weights require a reason, not an
LLM confidence feeling. Source duplicates are one observation, not more evidence.

Use walk-forward validation to assess `H` and `kappa`, and keep the chosen
convention fixed across comparable drivers. This standalone CLI requires
explicit values. The former six-round exponential setting describes older
forecasts; current `run` defaults follow the user-selected linear weights in
`forecast-inputs.md`. The same posterior formula applies with those likelihood
weights, while `kappa=8` remains an uncalibrated prior strength.

Estimate prior frequencies from a disclosed compatible, pre-cutoff pool
(same rule/technical era, session and asset role); use weak smoothing with
declared pseudo-counts to keep rare outcomes possible. The v1 fallback for a
nonempty compatible pool is `pi_k=(pool_count_k+0.5)/(pool_N+0.5*K)` on `K`
possible outcomes (symmetric Dirichlet smoothing, not an observed base rate).
Declare alternatives and validate them rather than silently changing this.
Separate this pool from
the asset's likelihood window or use an explicitly fitted hierarchical model.
If no credible pool exists, do not invent a universal F1 failure rate: label
the result `scenario` and report sensitivity. At a season opener or for a rookie,
document the inherited prior and its limitations; no samples means `prior_only`.
Effective N is not a count of independent race weekends and is not calibration.

### Standards By Component

| Component | Probability target | Acceptable baseline / evidence | Consistency requirement |
| --- | --- | --- | --- |
| Qualifying | Full order, NC/DNS/DSQ, Q2/Q3 | Recency-weighted official qualifying, shrink pace to team/field, then a fitted ranking model or joint historical bootstrap | One rank each; advancement matches rank; at most profile Q2/Q3 capacity |
| Race/Sprint classification | Classified/NC/DNS/DSQ | Categorical power prior; compatible session/team/driver pool; current confirmed fault handled with conditional scenarios | Do not apply NC penalty to an officially classified retirement |
| Race/Sprint order | Rank conditional on classified starters and grid | Fitted pace/order model or joint bootstrap conditional on grid and race regime | Without-replacement ranks, one winner, preserve shared car/weather effects |
| Overtakes | Count of eligible overtakes | Decayed count PMF, or fitted Poisson/negative-binomial conditional on grid, pace and circuit | Not net positions gained; maintain linkage with race order and NC time |
| Fastest lap | One categorical winner (or none) | Eligible driver distribution from pace/tyre/stop conditions, checked against history | Sum winner probabilities across field <=1; no DSQ/DNS reward |
| DOTD | One categorical winner (or none) | Separate vote/award history and story-sensitive scenario evidence | Not automatically the winner or fastest driver; race only |
| Pit stops | Team fastest time, overall fastest, record | Official fastest-team-stop samples conditional on stop count/team/regime | Sample times first, derive overall winner; no Sprint pit score; record chronology |

Count PMFs must retain their tail. Do not label a bucket `5+` as exactly five
overtakes. If binned, specify a within-bin distribution or conditional mean
for expectation and a full distribution for tail simulation. Extremely sparse
DSQ/record events should shrink toward a compatible prior, not zero by default.

Confirmed current information can change a conditional model. Unverified
"overheating risk" cannot justify, for example, 35% NC. Instead show a documented
base estimate and stress-test lower/higher risk. A sensitivity range is NOT a
probability distribution; do not average the cases without justified weights.

### Quality Labels And Calibration

- `scenario`: expert/manual/qualitative weights, or any synthetic demonstration.
  Useful for conditional decisions, not claimed calibrated probabilities.
- `baseline`: a reproducible historical/statistical estimate with disclosed
  parameters but without adequate out-of-sample validation.
- `calibrated`: a frozen model version supported by a linked walk-forward,
  round-held-out report, including sample sizes and comparison baselines.
  Merely running `calibrate` does not grant this label.

For saved categorical predictions with one-hot actuals `y`:

```text
multiclass_Brier = (1/N) * sum_n sum_k (p_nk-y_nk)^2
log_loss        = -(1/N) * sum_n log(p_n,actual)
```

`calibrate` reports both and per-outcome 10-bin reliability tables. It uses
multiclass Brier (binary values are twice the one-column binary convention).
If an actual outcome had probability zero, log loss is infinite, reported as
`null` with an explicit flag, not hidden by epsilon clipping. Fit/tune on earlier
rounds only; assess on subsequent whole rounds, not random driver rows. Compare
to climatology/recency baselines using the same rows. Inspect reliability-bin
counts and round-level uncertainty; small samples cannot certify calibration.
For rank/count and full-lineup distributions also assess appropriate ranked
probability/CRPS, mean error and interval coverage externally. The CLI's
categorical metrics do not validate the entire joint model.

## Building Coherent Scenarios

Use a generator or explicit scenario table that follows this dependency order:

1. Shared weekend regime (weather, safety-car/race regime, team pace/reliability).
2. Full qualifying order/status and actual grid penalties/normalized start grid.
3. Classification and conditional finishing order, plus conditional overtakes.
4. Eligible fastest-lap and DOTD winner; race pit times and record chronology.
5. Sprint sessions when applicable; retain correlation across the same weekend.

A fitted Plackett-Luce or random-utility ranking model can sample ranks without
replacement, e.g. `P(order|strength) = product_r exp(theta_i[r]) /
sum_(j remaining) exp(theta_j)`. This is a model family, not implemented training
or a license to invent strengths. Resampled complete historical event vectors
are another baseline, but need adjustment/validation for current grid and roster.
Independent draws of every driver's marginal position are not coherent.

For a sampled model, retain generator/version, seed, sample count and parameters
in the audit artifact; equal-weight Monte Carlo draws have `p_s=1/N`. For
stratified regimes, weights are regime probability times conditional draw weight.
No silent renormalization occurs. Rerun independent seeds/increase N until
ranking and transfer gains are stable relative to their Monte Carlo error.
Three handpicked cases are a scenario analysis, not a detailed empirical PMF.

The validator catches rank collisions, inconsistent advancement, double award
winners, invalid pit bonuses, missing active assets, future evidence, and bad
probability sums. It cannot prove the scenario weights, source truth, numerical
pace assumptions, or overtaking/position relationship are realistic.

## Input Contracts

Generate the complete runnable schema with `example`; do not copy its invented
probabilities into a real race. JSON schema version is currently `1`.

### forecast.json

- `metadata`: `season`, `rules_version`, `target_round`, `format` (`standard` or
  `sprint`), timezone-aware `as_of`, `lock_at`, `prices_observed_at`,
  `model_status`, `method`, and nonempty `evidence` entries with `source` and
  `observed_at`. `pit_record_seconds` and `pit_record_source` document the
  pre-weekend benchmark. `synthetic=true` permits a small tutorial field, and
  forces `model_status=scenario`; omit/set false for real predictions.
- `metadata.probability_models`: one audit object per component: `qualifying`,
  `race_classification`, `race_order`, `race_overtakes`, `race_fastest_lap`,
  `driver_of_day`, `pit_stops`; add `sprint_classification`, `sprint_order`,
  `sprint_overtakes`, `sprint_fastest_lap` for Sprint. Each needs `method`,
  `source_refs` matching evidence sources, `sample_count`,
  `effective_sample_size`, and `parameters`. Use a linked per-asset audit
  artifact in `parameters` when pooling different cells. Include priors, decay,
  exclusions, model/generator version, seed and sensitivity settings as applicable.
  Zero samples is allowed for an honestly labeled manual scenario/prior.
- `metadata.calibration`: required for `calibrated`; `report`, `method`,
  positive `test_rounds`, `evaluated_at <= as_of`. Structural validation does
  not inspect or certify the linked report.
- `assets`: unique string `asset_id`, `type` (`driver`/`constructor`), `name`,
  current `price` in millions at 0.1M precision, optional boolean `active`.
  Active drivers need `constructor_id`. Include all current race entrants,
  not just the fantasy-selected candidates. Inactive old holdings may be
  included for their current selling price but are not eligible selections.
- `scenarios`: nonempty list of unique `id`, `probability`, `qualifying`, `race`,
  optional `sprint`, and `pit_stops`. Every scoring session maps every active
  driver ID to an outcome. Pit stops map every active constructor ID.

Session outcome fields (all required; unexpected fields rejected):

```json
{"status":"classified", "position":1, "q2":true, "q3":true}
```

```json
{"status":"classified", "position":1, "start_position":2,
 "overtakes":2, "fastest_lap":true, "driver_of_day":false}
```

Statuses: `classified`, `nc`, `dns`, `dsq`; non-classified `position=null`.
DNS may have `start_position=null`; other race/Sprint outcomes need a normalized
grid position. NC can retain overtakes/awards; DNS/DSQ cannot. Non-classified
qualifying has false Q2/Q3 flags. Sprint DOTD must be false.

```json
{"fastest_stop_seconds":2.31, "fastest_of_race":false, "world_record":false}
```

No stop: time null, both flags false. Where timed stops exist, exactly one team
with the minimum time wins fastest stop. Use official tie attribution if tied.

### teams.json

Top-level `schema_version=1`, `teams` is a nonempty list with unique `team_id`.
For an existing team:

```json
{"team_id":"T1", "previous_lineup":["d1","d2","d3","d4","d5","c1","c2"],
 "bank":2.7, "free_transfers":2, "chip":"none", "max_transfers":7,
 "penalty_already_incurred":0}
```

`previous_lineup` means the **currently saved roster at this decision point**,
not an obsolete last-week roster if transfers have already been submitted.
If the user explicitly confirms a different official transfer-accounting
baseline, use that roster with its matching bank, free allowance and incurred
penalty, and record this interpretation in `notes`; do not infer it from age
or the screenshot alone.
`free_transfers` is the remaining count, not the UI's used count: `1 of 3` used
means 2 remaining. `penalty_already_incurred` is a positive deduction magnitude
(convert a stored `-10` to `10`). Do not count the same submitted transfer twice.
Bank and prices must come from the same snapshot. Retaining an inactive holding
has no no-transfer score baseline; it is never silently scored as zero. The
search then assumes inactive holdings must be replaced. If comparing continued
inactive ownership matters, extend the inactive-asset scoring model first;
the current optimizer cannot establish the optimum including that option.

A fresh budget search uses `{"team_id":"New","budget":100}` instead of
holdings/bank. Supported chips: `none`, `autopilot`, `no_negative`, `3x`,
`wildcard`, `limitless`. Provide T1/T2/T3 when all are managed; availability
must be checked against private team state before recommending a chip.

Optional `required_assets` and `excluded_assets` lists constrain selections,
not the simulated field. Run once with `required_assets:["bearman_id"]` and
once with `excluded_assets:["bearman_id"]` for a keep-vs-sell comparison.
They must be disjoint active IDs. Best-free search obeys the same constraints;
the reported no-transfer baseline still describes the actual current holdings.

### Estimation And Calibration Files

`probability_input.json`: `schema_version=1`, `target.round` (positive ordinal
within this season), `target.as_of`, positive `half_life_rounds`, `prior` with
positive normalized `probabilities`, positive `strength`, `source`,
`available_at`. `observations` contains unique `id`, past `round`,
`observed_at`, `source`, categorical `outcome`, optional reliability `weight`.
Round-age decay is season-local; aggregate older-season evidence into a
documented prior rather than reusing ambiguous round numbers.

`calibration_input.json`: `schema_version=1`, `predictions` with unique `id`,
`round`, `source`, `trained_through <= as_of < lock_at < outcome_known_at`,
`probabilities` on a common support, and `actual`. Preserve the immutable
pre-lock prediction artifact; timestamps alone cannot detect a rewritten file.

## Commands

From the workspace (choose a new example directory; files are not overwritten):

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py example --out-dir data/forecast-demo
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py estimate data/forecast-demo/probability_input.json
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py validate data/forecast-demo/forecast.json
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py evaluate data/forecast-demo/forecast.json --out-dir data/forecast-demo/results
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py optimize data/forecast-demo/forecast.json --teams data/forecast-demo/teams.json --top 5 --out data/forecast-demo/lineups.json
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_forecast.py calibrate data/forecast-demo/calibration_input.json
```

Use `example --format sprint` in another directory for a Sprint template.
`validate/evaluate/optimize --rules PATH` selects a reviewed custom rule profile.
`estimate/calibrate --out PATH` saves the report. All commands also print JSON;
validation failures exit nonzero. No command places transfers or changes CSV
team state. `evaluate` writes:

- `expected_assets.csv`: mean, SD, P10/P50/P90, negative-score probability,
  and category-clipped No Negative mean, for both drivers and constructors.
- `component_probabilities.csv`: asset, category, possible points, probability,
  and `probability * points` expectation contribution.
- `evaluation.json`: same results with metadata and warnings.

Runtime scales with the field/scenario count. Standard fixed-boost search uses
asset means during enumeration and scores full distributions only for finalists;
Autopilot additionally evaluates a scenario-wise maximum per driver combination.

## Recommendation Output

State target round, cutoff, rule version and quality label first. Show the
largest category contributions to each relevant driver's/constructor's mean,
then T1/T2/T3 net lineup score, cost, remaining bank, boost, transfers and fees.
Compare retaining the lineup, best free changes and paid changes. Report risk,
probability of beating the no-transfer baseline, evidence weaknesses and the
assumptions that would reverse a recommendation. Do not overstate small deltas
that change sign under plausible model/sampling sensitivity.

For "why not replace Bearman?", compare **complete feasible lineups** with and
without him, not just his previous DNF or price threshold. Describe an avoided
transfer as optimal only if the search supports it under documented assumptions.

Keep rolling three-week price-growth analysis separate: it uses full official
weekend totals, including Sprint, even when predicting a standard next round.
Never feed forecast means into settled state or label demo numbers Mexico
predictions. Historical/live lineup tools remain hindsight/observation tools;
their `last1_fpoints` and `last1_price` are not forward prediction inputs.
