# F1 Fantasy Price Model

## Minimum State

Prefer building this state from the public-feed fetcher in
`references/public-data-access.md`. Screenshots are now a fallback, not the
routine path.

Only use completed gamedays for budget and rolling-score state. Public feeds may
show partial live race-week scores; those are useful for monitoring but must not
enter budget calculations until the race week has settled.

To onboard at any point in the season, capture this once for every driver and
constructor:

```text
asset_id,type,name,current_price,current_total_fpoints,previous_race_fpoints,last_race_fpoints
```

After that, each completed race only needs new driver and constructor total
fPoints. The script computes:

```text
race_fpoints = new_total_fpoints - old_total_fpoints
rolling_3 = previous_race_fpoints + last_race_fpoints + race_fpoints
avg_ppm = rolling_3 / 3 / current_price
```

## Price Tiers

Use the working tier split from the fantasy workspace:

```text
expensive asset: current_price > 18.5
cheap asset: current_price <= 18.5
```

Price changes:

| AvgPPM | Expensive | Cheap |
|---:|---:|---:|
| `> 1.2` | `+0.3M` | `+0.6M` |
| `0.9 - 1.2` | `+0.1M` | `+0.2M` |
| `0.6 - 0.9` | `-0.1M` | `-0.2M` |
| `< 0.6` | `-0.3M` | `-0.6M` |

Boundary handling:

- Exactly `1.2` is the good tier, not great.
- Exactly `0.9` is the good tier.
- Exactly `0.6` is the poor tier.

## Official Feed vs Model

For completed historical race weeks, prefer official feed values:

```text
official_price_change = PlayerValue - OldPlayerValue
```

Use the AvgPPM tier model for:

- pre-race and live scenario planning
- sanity checks against official feed output
- fallback calculations if public feeds fail or fields change

Do not overwrite settled official price movement with a model-derived value
unless the official feed is unavailable or clearly inconsistent.

## Limitless

`Limitless` creates a temporary unlimited-budget lineup for one race week. Price
changes apply to the underlying team, not the temporary Limitless lineup.

When a team row has `chip=Limitless`, use `shadow_lineup_asset_ids` for budget
impact reporting. If that field is blank, stop and ask for the underlying
lineup before claiming a team budget estimate.
