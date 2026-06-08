# 项目结构说明

本文档记录当前 F1 Fantasy Advisor 仓库的整体架构、主要工作流，以及每个文件或目录的大致作用。该项目是一个面向 Codex 的 F1 Fantasy 辅助 skill：用公开 F1 Fantasy feed 获取官方数据，用本地 CSV 维护私人队伍状态，并辅助做阵容、芯片、价格和预算判断。

## 总体架构

项目分为五层：

1. 根目录文档层：`README.md`、`README.zh-CN.md`、`info.md`，给用户解释项目用途、运行方式和目录结构。
2. Codex skill 层：`skill-dev/f1-fantasy-advisor/`，定义 Codex 何时使用这个 fantasy advisor、应读取哪些数据、如何给建议。
3. 脚本层：`skill-dev/f1-fantasy-advisor/scripts/`，包含公开数据抓取脚本和本地状态维护脚本。
4. 数据层：`data-templates/` 存放可提交的 CSV 表头模板；`data/` 存放本地真实状态和抓取结果，按 `.gitignore` 设计应保持私有。
5. 测试层：`tests/`，用 Python `unittest` 覆盖价格计算、CSV 状态更新、官方 feed 解析和官方 CSV v3 schema。

核心数据流：

```text
fantasy.formula1.com public feeds
  -> fetch_fantasy_public.py
  -> data/official/official_*.csv
  -> Codex / 用户读取公开资产价格、分数、target-round score_floor

用户私有队伍状态
  -> fantasy_state.py record-team
  -> data/team_state.csv
  -> fantasy_state.py report / Codex 策略建议

每站总分导入
  -> fantasy_state.py update-round
  -> data/assets_state.csv + data/race_scores.csv
```

## 根目录文件

### `README.md`

英文用户说明。介绍 F1 Fantasy Advisor 的用途、首次使用方式、用户需要提供的私有信息、可自动抓取的公开数据、本地运行命令和测试命令。

重点内容：

- 说明 public feed 不需要 F1 Fantasy 登录。
- 说明 `data/` 是本地私有状态，`data-templates/` 是可提交模板。
- 给出抓取公开数据、初始化本地 CSV、记录 team 状态、运行测试的命令。

### `README.zh-CN.md`

中文用户说明，内容对应英文 README，但面向中文使用场景。说明：

- 通过 Codex 启用 skill 后如何开始 fantasy 指导。
- 哪些公开数据可以自动抓取。
- 哪些私有账号状态仍需要用户提供。
- 如何运行抓取脚本、初始化本地 CSV、记录 team 状态和测试。

### `info.md`

当前文件。用于集中说明项目架构和每个文件的用途。

### `.gitignore`

忽略本地私有和生成文件：

- Python 缓存：`__pycache__/`、`*.py[cod]`、`.pytest_cache/`
- 本地笔记和截图：`now.md`、`LOCAL_WORKING_NOTES.md`、`todolist.md`、`*.png`
- 本地 fantasy 状态和抓取数据：`data/`

### `todolist.md`

本地任务清单，按 `.gitignore` 设计不应提交。当前内容是后续改进方向，例如：

- 将真实 `data/` 和模板分开。
- 在空目录测试 skill。
- 引入 `LOCAL_WORKING_NOTES.md` 记录用户长期偏好。
- 改进公开数据收集方法。
- 注意低价资产价格变化可能有特殊规则。

### `now.md`

本地个人工作笔记，按 `.gitignore` 设计不应提交。它可能包含用户 fantasy 记录、阶段性分析或上下文。Skill 文档明确说它只能作为本地 scratch，不应作为权威状态；权威状态应写入 CSV。

## `data-templates/`

该目录保存可提交的 CSV 表头模板，用于初始化或说明本地数据格式。它不包含真实私有队伍数据。

### `data-templates/assets_state.csv`

资产状态模板。字段：

```text
asset_id,type,name,current_price,current_total_fpoints,previous_race_fpoints,last_race_fpoints
```

用途：

- 记录每个 driver / constructor 当前价格、赛季总 fantasy 分，以及最近两站已完成比赛的单站分。
- `fantasy_state.py update-round` 用它计算下一站 `race_fpoints`、`rolling_3` 和模型价格变化。

### `data-templates/race_scores.csv`

每站资产结果模板。字段：

```text
round,asset_id,type,name,race_fpoints,rolling_3,avg_ppm,price_change,price_after
```

用途：

- 保存每站计算后的单站分、三站滚动分、AvgPPM、价格变化和赛后价格。
- 用于回看某站价格结果和 team budget impact。

### `data-templates/team_state.csv`

私有队伍状态模板。字段：

```text
round,team_id,budget_before,budget_after,total_fpoints,transfer_penalty,chip,lineup_asset_ids,boost_asset_id,shadow_lineup_asset_ids,notes
```

用途：

- 保存每个 fantasy team 的比赛周状态。
- `shadow_lineup_asset_ids` 用于 `Limitless`：真实预算变化应追踪底层队伍，而不是临时 limitless 阵容。

## `data/`

本地真实数据目录，按 `.gitignore` 设计应保持私有。当前存在以下文件。本文只描述用途，不展开私人内容。

### `data/assets_state.csv`

本地资产状态，表头与 `data-templates/assets_state.csv` 相同。当前为初始化状态文件。它是 `fantasy_state.py update-round` 的主要输入之一。

### `data/race_scores.csv`

本地每站 race scores，表头与 `data-templates/race_scores.csv` 相同。用于保存已处理比赛周的资产分数和价格变化。

### `data/team_state.csv`

本地私有 team 状态，表头与 `data-templates/team_state.csv` 相同。当前已有少量本地 team 记录。Codex 给队伍建议前应读取此文件，而不是依赖聊天历史。

### `data/imports/.gitkeep`

保持 `data/imports/` 目录存在的占位文件。该目录用于放临时导入 CSV，例如某站 driver / constructor 总分导入文件。

### `data/official/official_round_context.csv`

公开官方 round 上下文。字段：

```text
target_round_id,season,gameday_id,meeting_name,country,circuit,is_complete,session_types,first_session_start,last_session_start,fetched_at
```

用途：

- 确认当前 target round 是哪一站。
- 记录比赛名称、国家、赛道、session 类型、开始/结束时间。
- `is_complete` 用于判断该站是否已经结算。

### `data/official/official_asset_metrics.csv`

公开官方资产 metrics，是官方公开数据的宽事实表。字段：

```text
target_round_id,asset_id,type,name,current_price,last1_price,last2_price,current_total_fpoints,rank,last1_round_id,last1_fpoints,last1_price_change,last2_round_id,last2_fpoints,last2_price_change,rolling2_fpoints,score_floor_big_rise,score_floor_small_rise,score_floor_avoid_big_fall,is_active,fetched_at
```

用途：

- 每个 driver / constructor 一行。
- 保存当前价格、最近两站赛后价格、当前总 fantasy 分、官方 rank。
- 保存 target round 之前最近两站已完成比赛的 fantasy 分和官方价格变化。
- 计算 `rolling2_fpoints` 和三条 target-round 分数线：
  - `score_floor_big_rise`
  - `score_floor_small_rise`
  - `score_floor_avoid_big_fall`

`score_floor_*` 的含义：下一站单站 fantasy 分至少达到该值，才能进入或保持对应价格档位。负数不是锁定，只表示可以承受一定负分；如果 DNF/处罚导致分数低于该 floor，仍会跌出该档位。

### `data/official/official_asset_rankings.csv`

公开官方资产 rankings，是从 `official_asset_metrics.csv` 派生出来的窄排序索引。字段：

```text
target_round_id,type,ranking_metric,metric_rank,asset_id,name,score_floor,value_note
```

用途：

- 不重复当前价格、总分、rolling2 等事实字段。
- 每个 `ranking_metric` 生成一组排序。
- 当前排序维度：
  - `big_rise`
  - `small_rise`
  - `avoid_big_fall`
- 同一维度下 `score_floor` 越低越好，因为需要的下一站分数越少。

## `skill-dev/f1-fantasy-advisor/`

Codex skill 开发目录，包含 skill 元信息、行为说明、参考文档、脚本和 agent 配置。

### `skill-dev/f1-fantasy-advisor/SKILL.md`

Codex skill 主说明文件。内容包括：

- skill 名称和描述。
- 核心工作流：读取 README、本地 CSV、team_state；不要把 `now.md` 当权威状态。
- 启动 prompt：用户说 `帮我开始fantasy指导` 时，应如何初始化数据、抓取公开 feed、询问私有队伍状态。
- 赛后更新工作流：抓公开 feed、读取 official CSV、确认 gameday 是否完成、再运行本地状态更新。
- 常用命令：fetch public、init-data、record-team、update-round、report。
- 参考文档入口：public data、price model、strategy workflow。

### `skill-dev/f1-fantasy-advisor/agents/openai.yaml`

Agent/插件展示配置。内容很短：

```yaml
interface:
  display_name: "F1 Fantasy Advisor"
  short_description: "Maintain F1 Fantasy data and strategy"
  default_prompt: "帮我开始fantasy指导"
```

用途是给 Codex/界面展示 skill 名称、短描述和默认触发 prompt。

## `skill-dev/f1-fantasy-advisor/references/`

Skill 的参考文档目录。Codex 在做不同类型任务前应读取对应参考文件。

### `references/public-data-access.md`

公开 F1 Fantasy 数据访问说明。主要内容：

- 使用 first-party public feed，不要求用户提供截图或登录。
- 从 `web_config.json` 动态解析 `tourId` 和 common statistics endpoint。
- 说明 common statistics feed 中 driver / constructor 的 fPoints 表位置。
- 说明 per-asset history feed：`playerstats_{asset_id}.json`。
- 定义官方 v3 CSV 输出：
  - `official_round_context.csv`
  - `official_asset_metrics.csv`
  - `official_asset_rankings.csv`
- 强调默认不输出 score breakdown CSV；得分拆解只作为临时调试查询。
- 说明 live race-week partial points 不能进入 budget / rolling state。

### `references/price-model.md`

价格区间门槛说明。主要内容：

- 已结算历史价格变化以“下一次可见价格 - 本站 `PlayerValue`”为准；最新完成站用当前 common-statistics `curvalue` 作为下一次可见价格。
- target-round 只用最近两个已完成 gameday 构成 `rolling2_fpoints`。
- 三个 price-zone floor：
  - `score_floor_big_rise = 1.2 * 3 * current_price - rolling2_fpoints`
  - `score_floor_small_rise = 0.9 * 3 * current_price - rolling2_fpoints`
  - `score_floor_avoid_big_fall = 0.6 * 3 * current_price - rolling2_fpoints`
- 解释为什么没有单独的 `score_floor_avoid_small_fall`：它和 `score_floor_small_rise` 是同一个 0.9 阈值。
- 说明 rankings 是从 metrics 派生的窄索引，lower `score_floor` is better。
- 说明 `Limitless` 预算影响要看底层 shadow lineup。

### `references/strategy-workflow.md`

策略建议工作流。主要内容：

- 给阵容/芯片建议前需要刷新官方 session 结果、车队评论、天气、安全车风险、fantasy 数据和本地 team 状态。
- Team 1 和 Team 3 是 league-relevant teams；Team 2 默认忽略。
- 不固定 Team 1 保守、Team 3 激进，而是按每站组合决策。
- 策略价值公式：

```text
expected fantasy points
+ price-change EV
+ next-race budget flexibility
- reliability / penalty / weather risk
- chip opportunity cost
```

- 对特定比赛周提醒 `Limitless` 选项。
- 推荐输出应包含 lineup / transfers、boost/chip、预算影响、主要风险和仍缺数据。

## `skill-dev/f1-fantasy-advisor/scripts/`

脚本目录。当前保留两个 Python 脚本；没有第三方 Python 包依赖。

### `scripts/fetch_fantasy_public.py`

公开官方数据抓取脚本。默认输出到 `data/official/`。

主要职责：

- 请求 `https://fantasy.formula1.com/feeds/v2/apps/web_config.json`。
- 动态解析 common statistics endpoint。
- 解析当前 driver / constructor 的 id、name、price、total fPoints、rank。
- 对每个 asset 请求 `playerstats_{asset_id}.json`。
- 从 history feed 提取：
  - 每站 fantasy total points。
  - 官方 price change：下一次可见价格减本站 `PlayerValue`。
  - gameday/session metadata。
  - gameday 是否 complete。
- 自动选择 target round：优先下一个 incomplete gameday，否则最后一个 gameday。
- 只用 target round 之前已完成 gameday 计算 `rolling2_fpoints`。
- 生成官方 v3 CSV：
  - `official_round_context.csv`
  - `official_asset_metrics.csv`
  - `official_asset_rankings.csv`

主要函数：

- `fetch_json`：HTTP GET JSON。
- `resolve_common_statistics_url`：从 web config 拼出 common statistics URL。
- `parse_current_assets`：解析当前资产列表。
- `parse_player_history`：解析单个 asset 的 gameday history、score rows、gameday metadata。
- `resolve_target_round_id`：确定 target round。
- `official_asset_metric_rows`：生成宽 metrics 表。
- `official_asset_ranking_rows`：生成窄 rankings 表。
- `fetch_public_data`：抓取和写 CSV 的主流程。

命令示例：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --skip-history
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --asset-id 11161 --asset-id 28
```

### `scripts/fantasy_state.py`

本地 fantasy 状态维护脚本。默认读写 `data/`。

主要职责：

- 初始化本地 CSV 表头。
- 读取 `assets_state.csv`。
- 从 driver / constructor 总分导入 CSV 计算某站单站分。
- 使用三站 rolling AvgPPM 模型估算价格变化。
- 更新 `assets_state.csv` 和 `race_scores.csv`。
- 记录或替换某个 team 的私有比赛周状态。
- 报告某站 team budget impact，尤其处理 `Limitless` 的 shadow lineup。

核心模型：

```text
rolling_3 = previous_race_fpoints + last_race_fpoints + race_fpoints
avg_ppm = rolling_3 / 3 / current_price
```

价格变化模型：

- 贵资产：`current_price > 18.5`
- 便宜资产：`current_price <= 18.5`
- `avg_ppm > 1.2`：大涨
- `0.9 <= avg_ppm <= 1.2`：小涨
- `0.6 <= avg_ppm < 0.9`：小跌
- `< 0.6`：大跌

主要命令：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py record-team --data-dir data --round Spain --team-id Team1 --lineup ... --boost-asset-id ... --budget-before ...
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py update-round --data-dir data --round Monaco --drivers data/imports/monaco_drivers.csv --constructors data/imports/monaco_constructors.csv
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py report --data-dir data --round Monaco
```

主要函数：

- `ensure_headers`：创建本地 CSV。
- `load_assets`：校验和加载 assets。
- `price_change_for`：根据 current price 和 rolling_3 计算 AvgPPM 与价格变化。
- `compute_round`：用新总分计算单站结果。
- `updated_assets`：赛后滚动更新资产状态。
- `replace_round_scores`：替换同一 round 的 race_scores。
- `replace_team_state`：按 round + team_id 替换 team row。
- `team_impact_lines`：估算阵容价格变化对预算的影响。

## `tests/`

Python `unittest` 测试目录。

### `tests/test_fetch_fantasy_public.py`

覆盖公开 feed 抓取和官方 CSV 生成逻辑。

测试点：

- 从 web config 解析 common statistics URL。
- 从 fPoints groups 解析 current assets。
- 解析 player history、官方 price change 和 score breakdown。
- 将 partial gameday 标记为 incomplete。
- 从最近两个 complete gameday 构建资产状态 snapshot。
- 生成 price-zone `score_floor_*`，并确认 negative floor 不代表锁定。
- `official_asset_rankings.csv` 是窄排序视图，不重复 metrics 字段。
- 默认生成 v3 三张官方 CSV，不生成 score breakdown CSV。

### `tests/test_fantasy_state.py`

覆盖本地状态维护和价格计算逻辑。

测试点：

- AvgPPM price tiers。
- 负分比赛周下仍能正确计算 race_fpoints、rolling_3、price_change 并更新 state。
- `Limitless` 使用 `shadow_lineup_asset_ids` 估算预算影响。
- `record-team` 对同一 round + team_id 执行替换而不是追加重复行。

### `tests/__pycache__/`

Python 运行测试后生成的缓存目录，按 `.gitignore` 应忽略，不属于项目源代码。

## 其他目录

### `.git/`

Git 仓库元数据目录，不属于应用代码，不应手工编辑。

### `.agents/` 和 `.codex/`

Codex / agent 运行环境相关目录。当前只作为环境配置目录存在，不属于 F1 Fantasy Advisor 的业务逻辑。

## 当前不存在但 IDE 可能仍打开的文件

### `skill-dev/f1-fantasy-advisor/scripts/render_official_charts.py`

当前工作区里不存在该文件。IDE 打开标签可能是之前生成后又删除的旧标签。项目当前不包含赛后画图脚本，官方数据输出仍以 CSV 为唯一存储格式。

### `data/official/charts/official_fantasy_dashboard.html`

当前工作区里不存在该文件。官方数据目录当前只保留三张 official CSV。

## 常用操作

运行测试：

```bash
python3 -m unittest discover -s tests
```

抓取官方公开 fantasy 数据：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py
```

初始化本地 CSV：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py init-data --data-dir data
```

记录 team 状态：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fantasy_state.py record-team --data-dir data --round Spain --team-id Team1 --lineup 11161,13,11051,129,11059,25,28 --boost-asset-id 11161 --budget-before 4.7 --transfer-penalty -10
```

## 维护注意事项

- `data/`、`now.md`、`todolist.md` 是本地私有或工作状态，不应提交。
- 已结算官方价格变化优先用下一次可见价格减本站 `PlayerValue`，不要用模型覆盖官方结果。
- `score_floor_*` 是 target-round 预测门槛，不代表价格变化锁定。
- 未完成 target round 不应进入 `rolling2_fpoints`。
- `official_asset_metrics.csv` 是宽事实表；`official_asset_rankings.csv` 是窄排序索引。
- `Limitless` 预算影响应使用 `shadow_lineup_asset_ids`。
