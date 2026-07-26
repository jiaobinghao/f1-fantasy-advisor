# F1 Fantasy Advisor

[Chinese README](README.zh-CN.md)

F1 Fantasy Advisor helps you use Codex as a Formula 1 Fantasy assistant. It
keeps public fantasy data up to date, tracks prices and race-week scores, and
turns that information into lineup, chip, and budget-building advice.

By the way,I have found a [website](https://f1fantasytools.com),which has more data than mine,but I still think my f1-fantasy-advisor useful,even though I may not update it anymore.

## Start Here

Open Codex with this skill available and say:

```text
Help me start F1 Fantasy guidance.
```

If this is your first time using the advisor, you do not need to provide
previous race scores, driver prices, constructor prices, or screenshots of the
public statistics pages. The advisor can fetch those public values.

## What You Need To Provide

The public F1 Fantasy feeds do not include your private account state. Be ready
to provide:

- Which fantasy teams you want to manage
- Each team's current remaining budget or cost cap
- Each team's current lineup: 5 drivers, 2 constructors, and boosted driver
- Chips already used and any chip active this race week
- Transfer penalties already taken this race week
- Your league objective: budget growth, points ceiling, safer play, or
  split-team risk coverage

The advisor records this private race-week state in local CSV files under
`data/`, so you do not need to repeat the same information every session.

## What The Advisor Can Help With

- Race-week lineup and transfer decisions
- Chip timing, including `Wildcard`, `Limitless`, `No Negative`, `3x`,
  `Final Fix`, and `Autopilot`
- Budget-building paths and price-change impact
- Comparing aggressive and conservative team strategies
- Tracking a normal lineup behind a temporary `Limitless` lineup
- Explaining driver and constructor fantasy scores by event

## Data It Can Fetch

The advisor uses public first-party F1 Fantasy feeds to fetch:

- Current driver and constructor prices
- Current total fantasy points
- Per-race fantasy points
- Per-race price movement
- Target-round price-zone score floors
- Race-week/session metadata

Price advice must account for the driver floor: driver selling price cannot go
below `3.0M`. A driver already at `3.0M` cannot lose more budget, but can still
be a sell candidate because of poor expected points, reliability risk, or
transfer opportunity cost.

These feeds do not require your F1 Fantasy login. They are public website feeds,
not a formally documented long-term API, so the project keeps manual CSV or
screenshot input as a fallback.

## Live Race Weeks

During a race week, the fantasy site may show partial points after qualifying,
sprint qualifying, or sprint sessions. The advisor can show those live points
for context, but it should not use them for budget or rolling-score state until
the race week is complete.

## Local Setup

Requirements:

- Python 3.10 or newer
- Network access to `fantasy.formula1.com`
- No third-party Python packages are required

Local fantasy state lives in `data/`. That directory is ignored by Git because
it can contain your real teams, budgets, chips, and fetched race-week data.
Committed CSV headers live in `data-templates/`.

Fetch public fantasy data:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
```

Initialize local CSV state if needed:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
```

Record one team's private race-week state:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py record-team --data-dir data --round Spain --team-id Team1 --lineup 11161,13,11051,129,11059,25,28 --boost-asset-id 11161 --budget-before 4.7 --transfer-penalty -10
```

For beginners, you can give names in chat instead of asset ids; Codex should
look up the ids from fetched public data and write the CSV for you.

Run tests:

```bash
python3 -m unittest discover -s tests
```

## Repository Notes

The Codex skill lives under:

```text
skill-dev/f1-fantasy-advisor/
```

`now.md` is for local personal working notes and is ignored by Git.

## Tool Commands

### Official Data Fetch

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
```

### Auto-Pilot Calculation

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/auto_pilot_lineup.py 112
python3 skill-dev/f1-fantasy-advisor/scripts/auto_pilot_lineup.py 112 --top 10
```

### Best Lineup From Previous Lineup

Interactively enter last week's 5 drivers, 2 constructors, and remaining
budget. The script automatically accounts for extra-transfer penalties:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/best_lineup_with_transfers.py --interactive
```

### Live Race-Week Lineup Score

Use two separate commands. First fetch and cache the hydrated current scores
from the public `/api/live-scoring` endpoint used by the Live page. Each run
makes one request:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --fetch
```

Then interactively select 5 drivers, 2 constructors, and the 2x driver from the
cached scores:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --interactive
```

Combine cached Live scores with the previous round's official `last1_price` and
find the theoretical highest-scoring lineup for this round:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/best_live_lineup.py budget 112
```

Or enter the previous lineup and remaining bank interactively, then optimize
this round's score after extra-transfer penalties:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/best_live_lineup.py transfers --interactive
```

The bridge does not modify `auto_pilot_lineup.py` or
`best_lineup_with_transfers.py`. It rejects mismatched Live and official target
rounds. Provisional Live scores remain usable but are clearly labeled.

Use clipboard import as a fallback if the page structure or network changes:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --fetch --clipboard
```

Import copied table text, endpoint JSON, or complete saved HTML from a file.
Complete HTML contains only the initial page snapshot and may be older than the
hydrated endpoint data:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --fetch --input live_scores.txt
```
