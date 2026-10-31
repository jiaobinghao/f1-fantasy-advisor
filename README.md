# F1 Fantasy Advisor

[![tests](https://github.com/jiaobinghao/f1-fantasy-advisor/actions/workflows/tests.yml/badge.svg)](https://github.com/jiaobinghao/f1-fantasy-advisor/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Chinese README](README.zh-CN.md)

F1 Fantasy Advisor helps you use Codex as a Formula 1 Fantasy assistant. It
keeps public fantasy data up to date, tracks prices and race-week scores, and
turns that information into lineup, chip, and budget-building advice.

By the way, I have found a [website](https://f1fantasytools.com) which has more
data than mine, but I still think my f1-fantasy-advisor is useful, even though I
may not update it anymore.

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
- Remaining free transfers for each team at the current decision point
- Your league objective: budget growth, points ceiling, safer play, or
  split-team risk coverage

The advisor records this private race-week state in local CSV files under
`data/`, so you do not need to repeat the same information every session.

If no team state is saved in `data/`, the advisor will help you set up a team.
You can provide driver and constructor names in chat or share a screenshot
from the Fantasy website.

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
- Network access to `fantasy.formula1.com` for official data fetch
- Network access to `f1fantasytools.com` (third-party site) only for the live
  race-week tools
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

Models working in this repository can start at [AGENTS.md](AGENTS.md), then
follow the [race-week runbook](skill-dev/f1-fantasy-advisor/references/race-week-runbook.md).
The runbook distinguishes live acquisition from cached replay and explains the
account mapping; the program does not automatically convert `team_state.csv`
into its required `teams.json` input.

### Recent Behavior Changes

- Numeric parsing and formatting are now shared by all scripts: values that
  round to negative zero print as `0`, and price/score cleanup accepts
  `$`, `M`, `,`, `+`, `▲`, `▼` everywhere.
- `best_live_lineup.py` validates the Live cache against the official target
  by race name first; a round-id difference on the same race is only a
  warning, because the official GamedayId and the Live site's round number
  are different numbering schemes.
- `fantasy_state.py record-team` rejects a boost id outside the lineup, and
  (once `assets_state.csv` has data) unknown asset ids or a lineup that is
  not 5 drivers plus 2 constructors.
- Live-page driver/constructor codes can be overridden in
  `data/official/asset_codes.csv` (header template in `data-templates/`);
  built-in tables cover the current constructors and irregular driver codes.
- Interactive prompts exit cleanly on end-of-input (exit code 1) and Ctrl-C
  (exit code 130) instead of printing a traceback.

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
from the public `/api/live-scoring` endpoint used by the
[f1fantasytools.com](https://f1fantasytools.com) Live page (a third-party site;
clipboard and file import below are the fallbacks). Each run makes one request:

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

## Quick Lineup Review

Ask for a quick review when you want to identify which parts of your lineup
may need attention. This is useful early in a race week, before all practice
sessions have finished, or when you just want a shortlist of possible transfers.

You can say:

```text
Give all three of my teams a quick review for this week without running a full simulation.
Suggest which drivers and constructors to keep or consider replacing, balancing points and budget growth.
```

The advisor reads your saved lineups, remaining cash and free transfers, then
considers recent performance, current prices, price-change thresholds, and
available practice results and news. You will get:

- **Priorities for keeping or replacing picks:** which drivers and constructors
  look worth holding, and which seem expensive, have struggled recently, or
  could hurt your budget.
- **Possible transfers:** alternatives you can afford, any extra transfer
  penalties, and whether each change mainly targets points or price growth.
- **Budget opportunities and risks:** who looks closer to a price-rise
  threshold, who faces a possible fall, and whether a cheap driver deserves
  a place in the lineup.
- **Updates to watch:** practice sessions that could clarify pace, or a grid
  penalty decision that could change the recommendation.

This is an initial assessment based on the available evidence. It does not
establish a mathematically optimal lineup or guarantee a price rise. If you
want to know how many points a transfer might gain, or how many points you
would give up for budget growth, ask for a detailed forecast next.

## Detailed Forecasts And Lineup Evaluation

Before submitting your lineup, you can ask the advisor to compare specific
options using a probability forecast. It simulates possible race-week results,
estimates points and price changes for drivers, constructors and complete
lineups, then searches for combinations within your budget and transfer
limits. Both standard and Sprint weekends are supported.

You can say:

```text
Calculate detailed lineup recommendations for all three teams using this week's practice results and news.
Prioritize budget growth while giving up no more than 10 expected points compared with the highest-scoring option, and explain each transfer.
```

You do not need to prepare configuration files or look up public statistics.
The advisor reuses your saved account information, gathers public evidence
and runs the calculation. If you have already submitted transfers on the
website, provide your updated lineup, remaining cash and free transfers so
it can calculate from your current position.

The forecast uses recent races, rankings from completed practice sessions and
relevant news. Historical estimates use the latest four valid race weekends,
weighted **1, 0.75, 0.5, 0.25** from newest to oldest so that recent form matters
more. Sprint categories use the latest four valid Sprint weekends. These
weights apply to the historical component. Qualifying and race pace use their
own historical results, each blended with 40% practice evidence when available;
Sprint pace uses Sprint history in the same way. Race finishing order assigns
20%-80% to starting position using a fixed circuit difficulty table:
$g_c = 0.2 + 0.6\,d_c$. The table is packaged with the skill
and shown at the end of this README; weekly runs only look it up. Unknown
circuits use an explicitly flagged neutral 50% weight. Positive position gains
estimate overtakes
using each driver's historical gain/overtake ratio, with documented team/field
fallbacks. Level or losing finishes and retirements retain separate historical
overtake samples. Historical finishing
positions serve as a pace proxy, rather than measured lap times.
News adjustments currently cover practice incidents,
explicit reports of handling instability, and grid penalties. For a penalized
driver, the forecast weighs opportunities to gain positions and overtake
against the chance of finishing lower. Unconfirmed penalties are explained
through results under different conditions.

For each team, you will get:

- **A recommended lineup and actions:** five drivers, two constructors, the
  2x driver, transfers in and out, transfer penalties, and remaining cash.
- **Options that prioritize points or budget growth:** expected points after
  transfer penalties, expected lineup price changes, and the points sacrificed
  for growth. Both priorities may lead to the same lineup.
- **Comparisons with fewer changes:** keeping your current lineup, using only
  free transfers, and paying for extra transfers, so you can judge whether
  a change is worthwhile.
- **Reasons and uncertainty:** whether key points come from qualifying,
  finishing positions, overtakes or other categories; simulated scores under
  poor, typical and good outcomes; and missing evidence or news that could
  change the advice.

By default, the advisor first finds the lineup with the **highest expected
points after transfer penalties**. It then chooses the greatest expected
budget growth among legal lineups within **10 points** of that result. This
is what the command-line option `--allow 10` means. The reference is the best
expected score, rather than your existing lineup. The allowance does not
limit how many points you might actually lose in the race.

For example, suppose the option with the highest expected score offers
200 points and a 0.3M price rise, while another offers 194 points and a 0.9M
rise. The second gives up six points, so it qualifies under the default
10-point allowance. It still needs to be compared with all other qualifying
lineups. These numbers only illustrate the tradeoff. Budget growth here means
the expected rise in the value of your drivers and constructors; cash left
over after buying a cheaper lineup is shown separately.

If points are your only priority this week, say "Do not sacrifice expected
points for budget growth," which corresponds to `--allow 0`. You can also ask
"Compare the best lineups that keep Bearman with those that sell him." The
advisor compares the points and budget impact of complete lineups in each
case, rather than just comparing two drivers in isolation.

The forecast compares options under the current evidence and model
assumptions. Default parameters have not yet been backtested out of sample;
expected points, price changes and outcome ranges are not guarantees.
Budget recommendations currently target expected growth for this round.
If necessary price history is missing, the advisor can still recommend a
lineup for points and explain why a budget recommendation is unavailable.
The automated forecast currently supports ordinary fixed 2x. Chips need
separate evaluation; Final Fix, changes after lock and season-wide chip
allocation are not part of this calculation.

See the [race-week runbook](skill-dev/f1-fantasy-advisor/references/race-week-runbook.md)
for the workflow, the [input and command guide](skill-dev/f1-fantasy-advisor/references/forecast-inputs.md)
to run examples or configure data yourself, and the
[forecast model reference](skill-dev/f1-fantasy-advisor/references/forecast-model.md)
for scoring formulas, probability estimates and calculation details.

## Fixed Circuit Coefficients

The versioned data lives in [circuit-profiles.json](skill-dev/f1-fantasy-advisor/references/circuit-profiles.json), version `2026-11-01.v2`. Weekly forecasts only look it up. **Higher $d_c$ means harder passing and greater grid influence**:

```math
\begin{aligned}
g_c &= 0.2 + 0.6\,d_c, \qquad 0 \le d_c \le 1 \\[6pt]
K_i &= \underbrace{g_c G_i}_{\text{grid influence}}
     + \underbrace{(1-g_c)R_i}_{\text{pace influence}}
\end{aligned}
```

$G_i$ is the grid position after penalties and $R_i$ the sampled pace rank; sorting the field by $K_i$ produces finish $F_i$. Values of $d_c$ equal to $0$, $0.5$ and $1$ map to 20%, 50% and 80% grid influence, respectively. Race and Sprint share a coefficient; unknown tracks use a flagged $d_c=0.5$ fallback.

These are initial editorial assessments from the linked circuit guides, historical examples and layout characteristics, **not a fit to a pooled historical overtaking dataset or a backtested optimum**. The rubric is 0.0 easiest; 0.1-0.3 several passing opportunities; 0.4-0.6 mixed/restricted; 0.7-0.9 difficult; 1.0 extreme difficulty, including Monaco and Madring. Coefficients are not probabilities; 0.1 steps do not imply measurement precision. Sources support layout/history descriptions; numerical choices are model judgments.

Coverage follows the [2026 official calendar](https://www.formula1.com/en/racing/2026) accessed 2026-11-01: 23 circuits plus Sakhir, Jeddah and Imola. Identify relocated events by physical circuit; the Bahrain Grand Prix in Malaysia uses Sepang. An asterisk marks low evidence confidence: Madring has limited comparable F1 history and Sepang has limited recent comparable F1 editions. Madring's Monaco-level difficulty and Monza's easiest-tier difficulty follow user-requested model assumptions. All entries remain uncalibrated.

| Circuit | Difficulty $d_c$ | Grid weight | Pace weight | Assessment rationale |
|---|---:|---:|---:|---|
| [Australia - Albert Park](https://www.formula1.com/en/racing/2025/australia/circuit) | 0.3 | 38% | 62% | Fast revised layout, but limited heavy-braking opportunities between flowing corners. |
| [China - Shanghai](https://www.formula1.com/en/racing/2025/china/circuit) | 0.1 | 26% | 74% | The 1.2 km back straight and hairpin give a strong passing opportunity. |
| [Japan - Suzuka](https://www.formula1.com/en/racing/2025/japan/circuit) | 0.5 | 50% | 50% | Fast linked corners make following demanding; passing is concentrated at a few braking zones. |
| [Miami](https://www.formula1.com/en/racing/2025/miami/circuit) | 0.2 | 32% | 68% | Three straights offer recovery opportunities despite the tight low-speed section. |
| [Canada - Gilles-Villeneuve](https://www.formula1.com/en/racing/2025/canada/circuit) | 0.2 | 32% | 68% | Stop-start layout, hairpin and heavy braking provide several passing chances. |
| [Monaco](https://www.formula1.com/en/racing/2025/monaco/circuit) | 1.0 | 80% | 20% | Very narrow streets; F1 cites zero passing moves in the 2003 race. Extreme grid dependence. |
| [Barcelona-Catalunya](https://www.formula1.com/en/racing/2025/spain/circuit) | 0.4 | 44% | 56% | Mixed-speed aero-sensitive corners; main-straight braking remains the key opportunity. |
| [Austria - Red Bull Ring](https://www.formula1.com/en/racing/2025/austria/circuit) | 0.1 | 26% | 74% | Three straights and uphill braking zones allow repeated attacks. |
| [Great Britain - Silverstone](https://www.formula1.com/en/racing/2025/great-britain/circuit) | 0.2 | 32% | 68% | Several fast approaches and wide corners allow racing, with some following loss in fast sequences. |
| [Belgium - Spa-Francorchamps](https://www.formula1.com/en/racing/2025/belgium/circuit) | 0.1 | 26% | 74% | Long straights support slipstreaming; the fast middle sector still rewards pace. |
| [Hungary - Hungaroring](https://www.formula1.com/en/racing/2025/hungary/circuit) | 0.7 | 62% | 38% | Short straights and linked corners; F1 compares its downforce demand with Monaco. |
| [Netherlands - Zandvoort](https://www.formula1.com/en/racing/2025/netherlands/circuit) | 0.6 | 56% | 44% | Flowing, undulating layout limits easy attacks despite the banked final approach. |
| [Italy - Monza](https://www.formula1.com/en/racing/2025/italy/circuit) | 0.0 | 20% | 80% | User-requested easiest passing tier; long straights and chicane braking support this model assumption. |
| [Spain - Madring](https://www.formula1.com/en/racing/2026/spain/circuit) * | 1.0 | 80% | 20% | User-requested Monaco-level passing difficulty; limited comparable F1 history, so this remains an uncalibrated model assumption. |
| [Azerbaijan - Baku](https://www.formula1.com/en/racing/2025/azerbaijan/circuit) | 0.3 | 38% | 62% | Very long slipstreaming straight offsets a narrow old-town section; not uniformly easy. |
| [Malaysia - Sepang](https://www.racingcircuits.info/asia/malaysia/sepang.html) * | 0.1 | 26% | 74% | Wide track, two long straights and heavy braking favour passing; limited recent comparable F1 editions. |
| [Singapore - Marina Bay](https://www.formula1.com/en/racing/2025/singapore/circuit) | 0.8 | 68% | 32% | Corner-heavy street layout retains strong track-position dependence after the 2023 changes. |
| [United States - COTA](https://www.formula1.com/en/racing/2025/united-states/circuit) | 0.1 | 26% | 74% | Very wide Turn 1 and long-straight braking provide multiple attacking lines. |
| [Mexico City - Hermanos Rodriguez](https://www.formula1.com/en/racing/2025/mexico/circuit) | 0.4 | 44% | 56% | Long main straight helps, but altitude and the twisty middle/stadium sections constrain sustained recovery. |
| [Sao Paulo - Interlagos](https://www.formula1.com/en/racing/2025/brazil/circuit) | 0.1 | 26% | 74% | Runs into the Senna S and Turn 4 support recovery despite the twisty infield. |
| [Las Vegas](https://www.formula1.com/en/racing/2025/las-vegas/circuit) | 0.0 | 20% | 80% | Long straights and heavy braking; F1 explicitly highlights overtaking opportunities. |
| [Qatar - Lusail](https://www.formula1.com/en/racing/2025/qatar/circuit) | 0.5 | 50% | 50% | Medium/high-speed corners dominate; the main straight into Turn 1 is the primary passing opportunity. |
| [Abu Dhabi - Yas Marina](https://www.formula1.com/en/racing/2025/united-arab-emirates/circuit) | 0.3 | 38% | 62% | Long straight and the 2021 changes help passing; the later corner sequence still matters. |
| [Bahrain - Sakhir GP layout](https://www.formula1.com/en/racing/2025/bahrain/circuit) (additional) | 0.0 | 20% | 80% | Several heavy-braking opportunities; F1 describes decent amounts of overtaking. |
| [Saudi Arabia - Jeddah](https://www.formula1.com/en/racing/2025/saudi-arabia/circuit) (additional) | 0.2 | 32% | 68% | Fast street layout with long flat-out sections, tempered by narrow high-speed sequences. |
| [Emilia-Romagna - Imola](https://www.formula1.com/en/racing/2025/emiliaromagna/circuit) (additional) | 0.7 | 62% | 38% | Old-school linked corners; most realistic passing concentrates on the main-straight approach. |

Revise and version the table for substantial layout/rule changes or validated new evidence. Weather or individual race incidents do not trigger weekly fitting. Results save the table snapshot, version and content hash for replay. Circuit influence reaches positive-gain overtakes through $g_c \to F_i \to D_i \to D_i/q_i$; there is no additional overtake discount.

## How the Forecast Is Calculated

The program estimates probabilities from evidence available before lock, simulates complete race weekends, and scores each driver's and constructor's points and price changes. This describes the current v1 implementation with circuit table `2026-11-01.v2`; each run's output records its actual parameters and sources.

**1. Estimate probabilities and pace from data.**

Each estimation pool uses its latest four valid race weekends, weighted `1, 0.75, 0.5, 0.25` from newest to oldest. Pools can cover different rounds: Sprint uses Sprint history, while the overtake ratio uses eligible positive-gain results. Missing sessions are not treated as zero performance.

Qualifying, race and Sprint each estimate pace from their own historical positions. They do not all reuse qualifying history. When practice evidence is available, each session's blended score is:

```math
A_{i,k} = 0.6\,H_{i,k} + 0.4\,\mathrm{FP}_{i,k},
\qquad k \in \{\mathrm{Q},\mathrm{R},\mathrm{Sprint}\}
```

$H_{i,k}$ is the matching historical score and $\mathrm{FP}_{i,k}$ the practice score after news corrections. FP1, FP2 and FP3 default to weights `0.2, 0.3, 0.5`, renormalized over that driver's usable sessions. News can compensate an incident or penalize explicit handling instability in the affected practice session. A regular driver who misses FP1 never inherits a reserve driver's ranking. An incident with no practice rank falls back to the matching forecast session's history; no usable practice means 100% history. These scores are rank-based performance proxies, not cleaned lap times.

Status probabilities separately use prior smoothing. For driver $i$ and status $c$ in a given session:

```math
\widehat{P}_i(c) =
\frac{
  \underbrace{8\,P_{\mathrm{prior},i}(c)}_{\text{prior}}
  + \underbrace{\displaystyle\sum_t w_t\,\mathbf{1}_{\{X_{i,t}=c\}}}_{\text{recent observations}}
}{8 + \displaystyle\sum_t w_t}
```

The status prior comes from other drivers' same-season results for that session type, or a sourced explicit prior when history is unavailable. The model first distinguishes classified, a nonclassified group, and disqualified. In race and Sprint sessions, historical start evidence then splits the nonclassified group into started NC and did-not-start DNS.

Thus **the last four rounds are not the only probability input**. With one record per round their weights sum to 2.5, versus prior strength 8: the prior accounts for about 76% of this smoothing formula's total weight. This influential parameter remains uncalibrated and is separate from the 60% history / 40% practice pace blend.

**2. Draw qualifying results and apply grid penalties.**

The program draws qualifying classification states and converts blended qualifying scores into ranking strengths:

```math
a_{i,k} = \exp\!\left(\frac{A_{i,k}-n}{\tau}\right),
\qquad \tau=3
```

$n$ is the current field size and the ranking temperature $\tau$ defaults to 3. Sampling in proportion to the remaining drivers' strengths produces an order without duplicate positions. Classification states then determine qualifying positions and Q2/Q3 progression. Race and Sprint pace use the same sampling method with their own scores.

Confirmed penalties act on the full grid under the season's rules, without changing qualifying points. A published official grid is used directly; penalties already incorporated into it are not applied again. Unconfirmed penalties are mixed only when justified probabilities exist. Otherwise, conditional branches are reported separately and the main result includes confirmed penalties only. The Sprint grid is handled separately rather than copied from the race grid.

**3. Draw race pace, finishing order and overtakes.**

After drawing race classification states and latent pace ranks $R_i$, sort classified drivers from lowest to highest by:

```math
\begin{aligned}
g_c &= 0.2 + 0.6\,d_c, \qquad 0 \le d_c \le 1 \\[6pt]
K_i &= \underbrace{g_c G_i}_{\text{grid influence}}
     + \underbrace{(1-g_c)R_i}_{\text{pace influence}}
\end{aligned}
```

$G_i$ is the grid position after penalties, and $d_c$ comes from the fixed circuit table above. Monaco and Madring currently use `80% grid / 20% pace`, Monza `20% / 80%`, and Mexico `44% / 56%`. Race and Sprint share a circuit coefficient; unknown tracks use a flagged `50% / 50%` fallback.

Sorting the field produces integer finishing positions $F_i$. $K_i$ is a sorting key, not a finishing position to round; ties use grid order. This is a **simplified mixture of ranks**, without lap-by-lap tyre, pit strategy or traffic simulation.

Overtakes depend on the resulting position change. Lower position numbers are better, so net gain is $D_i=G_i-F_i$. For a classified driver with $D_i>0$:

```math
\begin{aligned}
q_i &= \frac{\displaystyle\sum_t w_t\bigl(G_{i,t}-F_{i,t}\bigr)}
             {\displaystyle\sum_t w_t O_{i,t}} \\[8pt]
\lambda_i &= \frac{D_i}{q_i}, \qquad D_i=G_i-F_i>0
\end{aligned}
```

The historical ratio uses only positive-gain classified results with known grid and finish, retaining zero-overtake observations. It divides weighted sums instead of averaging individual ratios, which could divide by zero. Insufficient effective driver samples fall back to the current constructor, then the field, and finally empirical counts if the ratio remains unavailable. Sufficient positive-gain history containing only zero overtakes gives a zero conversion rate.

Expected overtakes $\lambda_i$ are rounded stochastically while preserving the mean: $\lambda_i=2.3$ gives two overtakes with probability 70% and three with probability 30%. Level or losing finishes and started NC outcomes use matching historical counts; DNS/DSQ receive no overtake rewards. Circuit influence already flows through $g_c \to F_i \to D_i \to D_i/q_i$, so no additional circuit discount is applied.

**4. Draw other scoring events and derive constructor points.**

Fastest lap and Driver of the Day (DOTD) use historical winner distributions with prior smoothing, sampling among eligible drivers and a no-winner option. Each award has at most one winner per session; Sprint has no DOTD. Pit performances are sampled from history, and comparing them determines the fastest-stop winner.

The public-data workflow normally uses historical pit scoring bands as proxies. Measured mode is used only when every constructor has usable measured samples. No world-record bonus is generated without full stop chronology and the pre-weekend record. Constructor points follow the rules using both drivers in the **same scenario**, together with constructor-specific progression, pit and applicable extra penalty items. Constructor totals are not sampled independently of their drivers.

**5. Score and price each scenario, then average.**

Let $S_i^{(s)}$ be asset $i$'s raw score in scenario $s$. For one branch with $N$ equally weighted scenarios (default $N=8192$), expected points for either a driver or a constructor are:

```math
\boxed{\displaystyle\widehat{\mu}_i = \frac{1}{N}\sum_{s=1}^{N} S_i^{(s)}}
```

Let $P_i$ be the current price and $\mathbf{h}_i$ the previous two settled scores. Apply the local price model to **each scenario's raw points** before averaging:

```math
\widehat{\mathbb{E}}\!\left[\Delta P_i\right] =
\frac{1}{N}\sum_{s=1}^{N}
f\!\left(P_i,\,\mathbf{h}_i,\,S_i^{(s)}\right)
```

Price changes have threshold bands, so mapping the mean score once is not equivalent. Neither 2x nor transfer fees enter asset price calculations. Missing required price history makes the price forecast unavailable.

When combining justified probability-weighted penalty branches, use the exported scenario weights $p_s$ instead of dividing everything by 8192:

```math
\begin{aligned}
\widehat{\mu}_i
  &= \sum_s p_s\,S_i^{(s)} \\[6pt]
\widehat{\mathbb{E}}\!\left[\Delta P_i\right]
  &= \sum_s p_s\,f\!\left(P_i,\,\mathbf{h}_i,\,S_i^{(s)}\right) \\[6pt]
\sum_s p_s &= 1
\end{aligned}
```

Here is an **illustrative scoring example, not a claim about a current output scenario ID**. A driver qualifies eighth, starts eighth, finishes third as classified, makes one eligible overtake, and earns neither fastest lap nor DOTD. Under the current 2026 rules, a standard weekend gives:

```math
\begin{aligned}
S_i^{(s)}
  &= \underbrace{3}_{\text{qualifying}}
   + \underbrace{15}_{\text{race}}
   + \underbrace{(8-3)}_{\text{positions gained}}
   + \underbrace{1}_{\text{overtake}} \\[6pt]
  &= \boxed{24}\ \text{points}
\end{aligned}
```

This is one possible result; averaging all scenario scores with their weights gives the driver's expected points. A specific driver's mean changes with evidence, parameters and model version, so a number from an older forecast is not a fixed conclusion.

**6. Compare complete lineups for points and budget growth.**

Each managed team independently searches legal combinations of five drivers and two constructors. With ordinary fixed 2x, expected lineup points are the sum of asset means plus one extra copy of the chosen boosted driver's mean, minus extra-transfer fees. The boosted driver is fixed across scenarios. First find the highest net expected score, then maximize total expected asset price growth among all legal lineups within `--allow` points, default 10. Both options are reported; this remains a one-round budget-building strategy.

**Why 8192 scenarios by default?**

The [generator defaults](skill-dev/f1-fantasy-advisor/scripts/forecast_generate.py) set `samples` to 8192 and `seed` to 42. Each penalty branch generates 8192 simulations of the complete field, each weighted $1/8192$ within that branch. Combining $B$ positive-probability branches gives $B \times 8192$ scenarios, each weighted by its branch probability divided by 8192. Distinct scenario IDs do not guarantee distinct race outcomes.

$8192=2^{13}$, but the algorithm **does not require a power of two**. Set `samples` under the run config's `model_parameters` to 8000, 10000 or 32768 if needed. It is a default tradeoff between computation and sampling variation, not a historical sample count or a number with racing significance. **No convergence experiment has established that 8192 is sufficient, and it is not a proven optimal sample size.**

For simple equally weighted sampling within one branch, the approximate standard error of the mean is:

```math
\mathrm{SE}\!\left(\widehat{\mu}_i\right)
\approx \frac{\sigma_{i,\mathrm{scenario}}}{\sqrt{N}}
```

Here $\sigma_{i,\mathrm{scenario}}$ is the standard deviation of scenario scores. Quadrupling $N$ roughly halves sampling standard error. This measures Monte Carlo variation, excluding data errors and model bias; it is not a prediction interval for the actual race score. Branch mixtures reuse paired random draws, so their combined scenario count cannot simply be substituted into this formula. Fixed inputs, code, table version and seed make a result reproducible, but do not establish calibration.

## License

This project is licensed under the [MIT License](LICENSE).
