# F1 Fantasy Advisor

[English README](README.md)

F1 Fantasy Advisor 是一个 Codex skill，用来维护 Formula 1 Fantasy 数据，并把公开数据、价格变化、阵容、芯片和预算路径转化成可执行的分站备赛建议。

建议从这句话开始：

```text
帮我开始fantasy指导
```

## 这个 Skill 能做什么

- 无需登录，获取公开的 F1 Fantasy 车手和车队数据
- 生成当前价格、总分、每站积分和得分拆解 CSV
- 公共数据不再依赖截图
- 比赛周未结束时，不把赛中临时分数纳入预算和 rolling-score 状态
- 支持预算增长、Limitless shadow team、芯片时机和分队策略
- 区分公开数据和私有账号状态

## 游戏基础

常规 F1 Fantasy 阵容结构：

- 5 位车手
- 2 个车队
- 1 位车手获得标准 `2x` boost
- 除非使用 `Limitless`，否则受 cost cap 限制

常见 chips：

- `Wildcard`：本比赛周无限次转会，并永久保留新阵容
- `Limitless`：本比赛周临时使用无限预算阵容
- `No Negative`：保护本周负分
- `3x`：让一位车手获得三倍积分
- `Final Fix`：锁定后允许一次替换
- `Autopilot`：自动把 boost 给队内最高分的合格车手

## 环境要求

- Python 3.10 或更新版本
- 可以访问 `fantasy.formula1.com`
- 内置脚本不需要第三方 Python 包

## 快速开始

获取公开 fantasy 数据：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/imports/official
```

运行测试：

```bash
python3 -m unittest discover -s tests
```

如果本地 CSV 为空，先初始化：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
```

## 第一句对话流程

当用户说：

```text
帮我开始fantasy指导
```

助手应该：

1. 读取当前 workspace 状态。
2. 如果 `data/assets_state.csv` 为空，先获取公开数据。
3. 使用 `data/imports/official/assets_state_snapshot.csv` 建立公开的车手/车队状态。不要要求用户提供前两站分数。
4. 只向用户询问公开 feed 无法提供的私有账号信息。

首条回复应类似：

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

需要用户提供的私有信息：

- 需要管理哪些 fantasy team
- 每个 team 当前剩余 budget 或 cost cap
- 当前阵容：5 位车手、2 个车队、boosted driver
- 已经使用过的 chips，以及当前是否激活 chip
- 本比赛周是否已有 transfer penalty
- 联盟目标或风险偏好

## 公开数据

这个 skill 使用 F1 Fantasy 网站的一方公开 feed：

- `feeds/v2/apps/web_config.json`
- `feeds/v2/statistics/driverconstructors_{tourId}.json`
- `feeds/popup/playerstats_{asset_id}.json`

生成文件：

```text
data/imports/official/current_assets.csv
data/imports/official/assets_state_snapshot.csv
data/imports/official/gameday_scores.csv
data/imports/official/gameday_score_breakdown.csv
data/imports/official/gamedays.csv
```

这些 feed 不需要账号凭据，但它们不是官方公开承诺的长期 API。可以把它们作为日常自动化来源，同时保留截图/CSV 作为兜底。

## 比赛周中的 live 数据

比赛周进行中，公开 feed 可能在排位或冲刺后显示临时分数。这些数据可以用于观察，但不能进入预算、rolling AvgPPM 或赛后状态计算，直到整个比赛周完成。

脚本会显式标记：

```text
gameday_scores.csv:is_gameday_complete
gamedays.csv:is_complete
```

`assets_state_snapshot.csv` 默认排除未完成的 gameday。

## 仓库结构

```text
skill-dev/f1-fantasy-advisor/SKILL.md
skill-dev/f1-fantasy-advisor/agents/openai.yaml
skill-dev/f1-fantasy-advisor/references/
skill-dev/f1-fantasy-advisor/scripts/
tests/
data/
```

`now.md` 用于本地个人工作笔记，已被 Git 忽略。
