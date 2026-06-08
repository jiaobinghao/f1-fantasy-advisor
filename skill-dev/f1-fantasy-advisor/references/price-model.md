# F1 Fantasy Price Thresholds

Use this file as a target-race price-zone threshold reference, not as an
override for official settled prices.

## Official Settled Prices

For completed historical race weeks, use official public feed values:

```text
price_before = this gameday PlayerValue
price_after = next gameday PlayerValue, or current common-statistics curvalue
official_price_change = price_after - price_before
```

Treat `GamedayWiseStats[].PlayerValue` as the price entering that gameday. For
the latest completed pre-target gameday, the next visible price is the current
common-statistics `curvalue`. Do not use `OldPlayerValue` as the routine settled
price-change source: low-price floor/cap behavior can make that field misstate
the actual visible movement. Do not replace settled official price movement with
a model-derived value unless the official feed is unavailable or clearly
inconsistent.

## Target-Race State

Prefer building target-race state from the public-feed fetcher in
`references/public-data-access.md`.

Only completed gamedays before the target round enter the rolling-score base.
Public feeds may show partial live race-week scores; those are useful for
monitoring but must not enter `rolling2_fpoints` until the race week has
settled and is no longer the target round.

The v3 official metrics use:

```text
rolling2_fpoints = last1_fpoints + last2_fpoints
```

`last1_*` is the most recent completed gameday before the target round.
`last2_*` is the completed gameday before `last1_*`.

## Price Change Amounts

The local fallback model uses two asset price levels:

```text
expensive asset: current_price > 18.5M
standard asset: current_price <= 18.5M
```

`18.5M` itself belongs to the standard tier because the script uses a strict
`>` cutoff for expensive assets.

After a completed target round, calculate:

```text
rolling_3 = rolling2_fpoints + target_round_fpoints
avg_ppm = rolling_3 / 3 / current_price
```

Then map the asset to one of four price-change bands:

| Band | AvgPPM rule | Expensive asset | Standard asset |
|---|---:|---:|---:|
| Big rise | `avg_ppm > 1.2` | `+0.3M` | `+0.6M` |
| Small rise | `0.9 <= avg_ppm <= 1.2` | `+0.1M` | `+0.2M` |
| Small fall | `0.6 <= avg_ppm < 0.9` | `-0.1M` | `-0.2M` |
| Big fall | `avg_ppm < 0.6` | `-0.3M` | `-0.6M` |

Boundary handling:

- Exactly `1.2` is small rise, not big rise.
- Exactly `0.9` is small rise.
- Exactly `0.6` is small fall, not big fall.

Use this table for pre-race and live scenario planning, sanity checks, or
fallback calculations. For completed historical race weeks, prefer the official
settled visible price movement.

## Price-Zone Floors

The working fantasy thresholds are:

```text
big rise boundary: rolling_3 / 3 / current_price = 1.2
small rise zone: rolling_3 / 3 / current_price >= 0.9
avoid big fall zone: rolling_3 / 3 / current_price >= 0.6
```

For target-race planning, convert those to single-race score floors:

```text
score_floor_big_rise = 1.2 * 3 * current_price - rolling2_fpoints
score_floor_small_rise = 0.9 * 3 * current_price - rolling2_fpoints
score_floor_avoid_big_fall = 0.6 * 3 * current_price - rolling2_fpoints
```

There is no separate `score_floor_avoid_small_fall`: it is the same 0.9
threshold as `score_floor_small_rise`, so keeping both would duplicate the same
price-zone boundary.

`score_floor_*` may be negative. It means the target-race fantasy score must be
at least that floor to remain in the price zone. It does not mean the price
movement is locked, because fantasy race-week scores can be negative after a
DNF, penalty, DNS, or disqualification.

For `score_floor_big_rise`, remember the strict boundary above: a target score
equal to the floor only reaches `avg_ppm = 1.2`, which the fallback model treats
as small rise. To project a fallback-model big rise, the target score must be
greater than `score_floor_big_rise`.

Example:

```text
score_floor_big_rise = -27
```

Interpretation: the asset can still remain in the big-rise zone with a target
score of `-26`, but a target score of `-28` falls below the big-rise floor.

## Rankings

`official_asset_metrics.csv` is the wide source-of-truth table. It keeps one row
per asset with current price, current total fPoints, prior completed gameday
scores, official settled price changes, and all score floors.

`official_asset_rankings.csv` is only a narrow sorted index derived from
`official_asset_metrics.csv`. It has one ranking per `ranking_metric`; lower
`score_floor` is better because less target-race score is required to reach or
hold that zone.

## Limitless

`Limitless` creates a temporary unlimited-budget lineup for one race week. Price
changes apply to the underlying team, not the temporary Limitless lineup.

When a team row has `chip=Limitless`, use `shadow_lineup_asset_ids` for budget
impact reporting. If that field is blank, stop and ask for the underlying
lineup before claiming a team budget estimate.
