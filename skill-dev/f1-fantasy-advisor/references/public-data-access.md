# F1 Fantasy Public Data Access

Use public first-party F1 Fantasy feeds before asking the user for screenshots.
These feeds do not require login credentials.

## Fetch Command

From the fantasy workspace:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/imports/official
```

For a quick current-price/current-total refresh only:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/imports/official --skip-history
```

For endpoint testing with a small sample:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/imports/official --asset-id 11161 --asset-id 28
```

## Public Endpoints

Resolve the current season dynamically:

```text
https://fantasy.formula1.com/feeds/v2/apps/web_config.json
```

Important fields:

```text
Data.config.tourId
Data.config.statistics.endPoints.commonStatistics
```

Then fetch the common statistics feed:

```text
https://fantasy.formula1.com/feeds/v2/{commonStatistics with {tourId} replaced}
```

The current fPoints table lives at:

```text
Data.driver[].config.key == "fPoints"
Data.constructor[].config.key == "fPoints"
```

Participant fields:

```text
playerid
playername or teamname
curvalue
statvalue
rnk
```

Per-asset history lives at:

```text
https://fantasy.formula1.com/feeds/popup/playerstats_{asset_id}.json
```

Important fields:

```text
Value.GamedayWiseStats[].GamedayId
Value.GamedayWiseStats[].PlayerValue
Value.GamedayWiseStats[].OldPlayerValue
Value.GamedayWiseStats[].StatsWise[]
Value.FixtureWiseStats[]
Value.TourWiseStats[]
```

Per-round values:

```text
race_fpoints = StatsWise item where Event == "Total"
price_change = PlayerValue - OldPlayerValue
current_price = latest PlayerValue, or common statistics curvalue
season_total = common statistics statvalue
```

## Generated CSVs

`fetch_fantasy_public.py` writes:

```text
data/imports/official/current_assets.csv
data/imports/official/assets_state_snapshot.csv
data/imports/official/gameday_scores.csv
data/imports/official/gameday_score_breakdown.csv
data/imports/official/gamedays.csv
```

Use `current_assets.csv` to build or refresh `data/assets_state.csv`.
Use `assets_state_snapshot.csv` as a ready-to-copy initial
`data/assets_state.csv` shape when onboarding mid-season after a race week has
settled. The snapshot excludes incomplete gamedays by default.
Use `gameday_scores.csv` to backfill any missed race week without screenshots.
Use `gameday_score_breakdown.csv` when a driver or constructor score needs an
event-level explanation.

## Live Race-Week Data

During a race week, `GamedayWiseStats` can contain partial points. Example: a
driver may show qualifying points before the race has happened. Keep those rows
for live observation, but do not use the latest incomplete gameday for budget,
rolling AvgPPM, price-change, or post-race state updates.

Completion rule:

```text
FixtureWiseStats[].RaceDayWise[].MatchStatus must all be "4"
```

If any session in the gameday is not `"4"`, treat that gameday as incomplete.
`fetch_fantasy_public.py` marks this in:

```text
gameday_scores.csv:is_gameday_complete
gamedays.csv:is_complete
```

`assets_state_snapshot.csv` uses only complete gamedays for
`previous_race_fpoints` and `last_race_fpoints`.

## Screenshot Policy

Do not ask for routine screenshots for public fantasy data:

- driver and constructor total fPoints
- current prices
- per-gameday points
- per-gameday price movement
- score breakdowns
- fixture/session metadata exposed by the playerstats feed

Still ask the user for private account state:

- Team 1 / Team 3 lineup
- budget after transfers
- selected chips and boosts
- transfer penalties
- any account-specific league view not available in public feeds

## Longevity

This is an official first-party public feed used by the F1 Fantasy web app, but
it is undocumented. Treat it as reliable enough for routine automation, not as a
guaranteed long-term API contract.

Mitigations:

- Always resolve `tourId` and the statistics endpoint from `web_config.json`.
- Keep CSV snapshots under `data/imports/official` after each fetch, so old
  race-week data is preserved if the feed changes later.
- Keep screenshot/CSV import as a fallback path.
- Do not hardcode season-specific IDs except in tests or sample commands.
- Do not replace `data/assets_state.csv` from a live or partially scored race
  week without reviewing whether the latest gameday is final.
- Do not use login credentials, bearer tokens, or private cookies unless the
  user explicitly starts a separate authenticated-data exploration.
