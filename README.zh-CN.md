# F1 Fantasy Advisor

[English README](README.md)

F1 Fantasy Advisor 可以让你用 Codex 做 Formula 1 Fantasy 助手。它会维护公开 fantasy 数据，追踪价格和每站积分，并把这些信息转化成阵容、芯片和预算增长建议。

## 从这里开始

在 Codex 中启用这个 skill 后，说：

```text
帮我开始fantasy指导
```

如果你是第一次使用，不需要提供前两站分数、车手价格、车队价格，也不需要截图公开统计页面。这些公开数据可以自动获取。

## 你需要提供什么

公开 F1 Fantasy feed 不包含你的私有账号状态。你需要准备：

- 需要管理哪些 fantasy team
- 每个 team 当前剩余 budget 或 cost cap
- 每个 team 当前阵容：5 位车手、2 个车队、boosted driver
- 已经使用过的 chips，以及本周是否有正在激活的 chip
- 本比赛周已经产生的 transfer penalty
- 你的 league 目标：爬预算、冲分、稳妥打法，或分队覆盖风险

advisor 会把这些私有比赛周状态记录到本地 `data/` 里的 CSV，所以你不用每次重新讲一遍。

## 它能帮你做什么

- 分站阵容和转会建议
- 芯片时机判断，包括 `Wildcard`、`Limitless`、`No Negative`、`3x`、`Final Fix`、`Autopilot`
- 预算增长路径和价格变化影响
- 比较激进和保守策略
- 追踪 `Limitless` 临时阵容背后的真实 budget-building 阵容
- 解释车手和车队的 fantasy 得分拆解

## 它能自动获取什么

这个 advisor 会使用 F1 Fantasy 网站的一方公开 feed 获取：

- 当前车手和车队价格
- 当前 fantasy 总分
- 每站 fantasy 积分
- 每站价格变化
- 本站价格区间分数门槛
- 比赛周/session 元数据

这些 feed 不需要你的 F1 Fantasy 登录信息。它们是网站使用的公开 feed，不是官方承诺长期稳定的 API，所以项目仍保留手动 CSV 或截图作为兜底。

## 比赛周中的 live 数据

比赛周进行中，fantasy 网站可能在排位、冲刺排位或冲刺赛后显示临时分数。advisor 可以用这些 live 分数做观察，但在整个比赛周完成前，不应把它们纳入 budget 或 rolling-score 状态。

## 本地运行

环境要求：

- Python 3.10 或更新版本
- 可以访问 `fantasy.formula1.com`
- 不需要第三方 Python 包

本地真实 fantasy 状态放在 `data/`。这个目录会被 Git 忽略，因为它可能包含你的真实队伍、budget、chips 和抓取到的分站数据。可提交的 CSV 表头模板放在 `data-templates/`。

获取公开 fantasy 数据：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
```

如果需要，初始化本地 CSV：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
```

记录一个 team 的私有比赛周状态：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py record-team --data-dir data --round Spain --team-id Team1 --lineup 11161,13,11051,129,11059,25,28 --boost-asset-id 11161 --budget-before 4.7 --transfer-penalty -10
```

如果你是新手，可以直接在对话里给车手/车队名字，不需要自己查 asset id；Codex 应该从已抓取的公开数据里查 id，然后帮你写入 CSV。

运行测试：

```bash
python3 -m unittest discover -s tests
```

## 仓库说明

Codex skill 位于：

```text
skill-dev/f1-fantasy-advisor/
```

`now.md` 用于本地个人工作笔记，已被 Git 忽略。

## 工具说明

# 官方数据收集

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
```

# auto-pilot计算

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/auto_pilot_lineup.py 112
python3 skill-dev/f1-fantasy-advisor/scripts/auto_pilot_lineup.py 112 --top 10
```