# F1 Fantasy Public Data Access

Use public first-party F1 Fantasy feeds before asking the user for screenshots.
These feeds do not require login credentials.

## Fetch Command

From the fantasy workspace:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
```

For a quick current-price/current-total refresh only:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official --skip-history
```

For endpoint testing with a small sample:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official --asset-id 11161 --asset-id 28
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
price_before = this gameday PlayerValue
price_after = next gameday PlayerValue, or current common-statistics curvalue
price_change = price_after - price_before
current_price = common statistics curvalue
season_total = common statistics statvalue
```

Treat `GamedayWiseStats[].PlayerValue` as the price entering that gameday. For
the latest completed pre-target gameday, the next visible price is the current
common-statistics `curvalue`. Do not use `OldPlayerValue` as the routine settled
price-change source: low-price floor/cap behavior can make that field differ
from the actual visible price movement.

## Generated CSVs

By default, `fetch_fantasy_public.py` writes only the v3 official team-selection
CSVs:

```text
data/official/official_round_context.csv
data/official/official_asset_metrics.csv
data/official/official_asset_rankings.csv
```

`data/` is local private state and should be ignored by Git. Commit reusable
headers or examples under `data-templates/` instead.

Use `official_asset_metrics.csv` for current price, current total fPoints, the
last two completed pre-target gameday entry prices and scores, official settled
price changes, and target-round price-zone floors. To initialize
`data/assets_state.csv`,
map `last2_fpoints` to `previous_race_fpoints` and `last1_fpoints` to
`last_race_fpoints`.

Use `official_asset_rankings.csv` only as a narrow sorted index derived from
`official_asset_metrics.csv`. It does not repeat current price, current total
fPoints, or rolling scores. Lower `score_floor` is better for each
`ranking_metric`.

Use `official_round_context.csv` to confirm which gameday is the target and
whether that gameday is already complete.

`--skip-history` writes only `current_assets.csv` for a quick current-price and
current-total refresh. Score breakdowns are not part of the routine CSV output;
query per-asset history temporarily when an event-level explanation is needed.

Official v3 schemas:

```text
official_round_context.csv
target_round_id,season,gameday_id,meeting_name,country,circuit,is_complete,session_types,first_session_start,last_session_start,fetched_at
```

```text
official_asset_metrics.csv
target_round_id,asset_id,type,name,current_price,last1_price,last2_price,current_total_fpoints,rank,last1_round_id,last1_fpoints,last1_price_change,last2_round_id,last2_fpoints,last2_price_change,rolling2_fpoints,score_floor_big_rise,score_floor_small_rise,score_floor_avoid_big_fall,is_active,fetched_at
```

```text
official_asset_rankings.csv
target_round_id,type,ranking_metric,metric_rank,asset_id,name,score_floor,value_note
```

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
official_round_context.csv:is_complete
```

`official_asset_metrics.csv` uses only complete gamedays before the target round
for `last1_fpoints`, `last2_fpoints`, and `rolling2_fpoints`.

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
- Keep CSV snapshots under `data/official` after each fetch, so old
  race-week data is preserved if the feed changes later.
- Keep screenshot/CSV import as a fallback path.
- Do not hardcode season-specific IDs except in tests or sample commands.
- Do not replace `data/assets_state.csv` from a live or partially scored race
  week without reviewing whether the latest gameday is final.
- Do not use login credentials, bearer tokens, or private cookies unless the
  user explicitly starts a separate authenticated-data exploration.

## External References

Treat third-party F1 Fantasy projects as endpoint maps and test references, not
as default runtime dependencies.

- `zeroclutch/f1-fantasy-api`: Node client for an older F1 Fantasy API shape;
  useful for historical endpoint naming, but do not depend on it for current
  public-feed syncing.
- `subinium/awesome-f1`: Curated index with F1 Fantasy API docs, endpoint cheat
  sheets, F1 Fantasy Tools, and Pitwall-style optimizers.
- `dltHub F1 Fantasy Python API Docs`: Useful when separately exploring
  authenticated private/account APIs. Keep that separate from this public-feed
  workflow because it requires login/session handling.
