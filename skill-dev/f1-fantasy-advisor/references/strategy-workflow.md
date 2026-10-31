# F1 Fantasy Strategy Workflow

## Race-Week Inputs

Before recommending transfers or chips, refresh:

- Official session results: FP, Sprint, Qualifying, Starting Grid, Race.
- Official team comments: damage, penalties, PU/gearbox changes, pit-lane starts.
- Weather and safety-car risk.
- Fantasy data from public feeds via `references/public-data-access.md`, then
  `data/assets_state.csv`, `data/race_scores.csv`, and `data/team_state.csv`.
  For target-round price risk, read `data/official/official_asset_rankings.csv`
  as a narrow sorted view. Lower `score_floor` is better.

If the public feed fails, ask for fallback screenshots or CSVs containing asset
name, current price, total fPoints, and price movement.

For private account state, ask beginner-friendly questions and record the
answers in `data/team_state.csv` with `scripts/fantasy_state.py record-team`.
Do not depend on `now.md` or conversation memory for lineup, budget, chips, or
transfer penalties.

## Team Strategy

Team 1, Team 2, and Team 3 are all managed, league-relevant teams. Analyze all
three in every race-week recommendation unless the user explicitly narrows the
request. If a team's state is missing or stale, identify the missing input and
give the best provisional analysis possible rather than silently omitting it.

Do not assign any team a permanently conservative or aggressive role. Treat
each race as a three-team portfolio decision:

```text
expected fantasy points
+ price-change EV
+ next-race budget flexibility
- reliability / penalty / weather risk
- chip opportunity cost
```

Do not describe a price rise as locked solely because a `score_floor_*` is
negative. A negative floor is only room for a negative race-week score; a DNF or
penalty can still fall below that floor.

For drivers at the `3.0M` minimum selling price, do not use further price-loss
risk as a sell argument. They can still be sell candidates for poor expected
points, reliability risk, bad qualifying position, or because the transfer
unlocks a materially stronger lineup.

Use split strategies across the three teams when one race-week thesis can be
directly punished by a single failure mode.

## Limitless Checks

When preparing Team 1 for these high-value candidates, explicitly mention
`Limitless` as an option:

- Silverstone Sprint
- Zandvoort Sprint
- Hungary
- Singapore Sprint

If Team 1's underlying budget-building lineup can continue cleanly after the
`Limitless` week, then `Limitless` can serve both goals: temporary points ceiling
and continued shadow-team price growth.

Avoid saving `Limitless` too late by default. Its marginal value usually falls
as normal budgets grow closer to unlimited-budget lineups.

## Recommendation Shape

Give concrete recommendations:

- Best lineup or transfer set for Team 1, Team 2, and Team 3.
- 2x / 3x / Autopilot / No Negative / Final Fix / Limitless call.
- Budget impact from expected price changes.
- Main risks that would flip the recommendation.
- Data still needed from the user, if any.
