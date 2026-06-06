# F1 Fantasy Advisor

F1 Fantasy Advisor is a Codex skill for maintaining Formula 1 Fantasy data and
turning it into practical race-week advice. It fetches public F1 Fantasy data,
tracks driver and constructor price movement, and helps evaluate lineups, chips,
budget-building paths, and split-team strategy.

Start with this prompt:

```text
帮我开始fantasy指导
```

## What This Skill Does

- Fetches public F1 Fantasy driver and constructor data without login
- Builds current-price and per-race scoring CSV snapshots
- Avoids screenshot collection for public totals, prices, and score breakdowns
- Keeps incomplete race-week scores out of budget and rolling-score state
- Supports budget-growth analysis, Limitless shadow-team tracking, and chip timing
- Separates public data from private account state

## Game Basics

Typical F1 Fantasy team structure:

- 5 drivers
- 2 constructors
- 1 selected driver receives the standard `2x` boost
- A cost cap applies unless `Limitless` is active

Common chips:

- `Wildcard`: unlimited permanent transfers for a race week
- `Limitless`: temporary unlimited-budget team for one race week
- `No Negative`: protects from negative fantasy scores
- `3x`: triples one selected driver's score
- `Final Fix`: allows one post-lock substitution
- `Autopilot`: applies the boost to the best-scoring eligible driver

## Requirements

- Python 3.10 or newer
- Network access to `fantasy.formula1.com`
- No third-party Python packages are required for the bundled scripts

## Quick Start

Install or stage the skill by copying this folder into your Codex skills area:

```text
skill-dev/f1-fantasy-advisor
```

Fetch public fantasy data:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/imports/official
```

Run tests:

```bash
python3 -m unittest discover -s tests
```

Initialize empty local CSVs if needed:

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
```

## First Conversation Flow

When the user says:

```text
帮我开始fantasy指导
```

the assistant should:

1. Read the workspace state.
2. If `data/assets_state.csv` is empty, fetch public data first.
3. Use `data/imports/official/assets_state_snapshot.csv` to build the public
   driver/constructor state. Do not ask the user for previous two race scores.
4. Ask only for private account information that public feeds cannot provide.

Expected first assistant response shape:

```text
我会先抓取公开 F1 Fantasy 数据来初始化车手/车队状态；你不需要提供前两站分数。

我还需要这些私有队伍信息：
- 你要管理哪些 team
- 每个 team 当前剩余 budget / cost cap
- 当前 5 位车手、2 个车队、boosted driver
- 已使用和当前激活的 chips
- 本周是否已有 transfer penalty
- league 目标：保守爬预算、冲分、还是分队覆盖风险
```

Private information to ask for:

- Which fantasy teams should be managed
- Current remaining budget or cost cap for each team
- Current lineup: 5 drivers, 2 constructors, and the boosted driver
- Chips already used and chips currently active
- Transfer penalties already taken this race week
- League goal or risk preference

## Public Data

The skill uses first-party public feeds from the F1 Fantasy web app:

- `feeds/v2/apps/web_config.json`
- `feeds/v2/statistics/driverconstructors_{tourId}.json`
- `feeds/popup/playerstats_{asset_id}.json`

Generated files:

```text
data/imports/official/current_assets.csv
data/imports/official/assets_state_snapshot.csv
data/imports/official/gameday_scores.csv
data/imports/official/gameday_score_breakdown.csv
data/imports/official/gamedays.csv
```

These feeds are public and do not require credentials, but they are
undocumented. Treat them as reliable enough for routine automation, not as a
guaranteed long-term API contract.

## Live Race Weeks

During a race week, the public feed may show partial points after qualifying or
sprint sessions. Those rows are useful for observation, but they must not enter
budget, rolling AvgPPM, or post-race state calculations until the race week is
complete.

The fetch script marks this explicitly:

```text
gameday_scores.csv:is_gameday_complete
gamedays.csv:is_complete
```

`assets_state_snapshot.csv` excludes incomplete gamedays by default.

## Repository Layout

```text
skill-dev/f1-fantasy-advisor/SKILL.md
skill-dev/f1-fantasy-advisor/agents/openai.yaml
skill-dev/f1-fantasy-advisor/references/
skill-dev/f1-fantasy-advisor/scripts/
tests/
data/
```

`now.md` is intended for local personal working notes and is ignored by Git.
