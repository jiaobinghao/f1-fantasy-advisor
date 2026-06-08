# F1 Fantasy 官方公开数据字段排查

调查时间：2026-06-08。

说明：文件名按当前需求写作 `offical_data.md`。这些接口是 F1 Fantasy 网页使用的 first-party public JSON，不需要登录，但没有官方 API 文档保证，字段语义需要用样本反推并持续校验。

## 总览

当前能稳定获取的公开数据分三类：

- `web_config.json`：当前赛季、规则开关、deadline、统计接口路径、图片路径、chip/booster 配置。
- `driverconstructors_{tourId}.json`：driver / constructor 的公开排行榜数据，包括当前价格、总分、排名、赛季价格趋势、选择率等。
- `playerstats_{asset_id}.json`：单个 driver / constructor 的历史赛周、session、单站得分拆解、赛季汇总、价格字段。

`web_config.json` 中还暴露了 `drivers_{tourId}.json` 和 `constructors_{tourId}.json`，但当前直接访问返回 `HTTP 403`。本项目暂不依赖这两个 endpoint。

## 入口配置

URL：

```text
https://fantasy.formula1.com/feeds/v2/apps/web_config.json
```

顶层字段：

```text
Data
Meta
```

`Data` 字段：

```text
boosters
cloudinary
config
constraints
```

### `Data.config`

关键字段：

```text
tourId
statistics
imagePaths
myTeam
homePage
leagues
menu
eos
clientHeaderFooter
completeYourProfile
predictorGameEnabled
teamsWithNoOptIn
maintenanceModeReloadCta
```

当前样本：

```text
tourId = 4
```

统计 endpoint 模板：

```text
Data.config.statistics.endPoints.commonStatistics = statistics/driverconstructors_{tourId}.json
Data.config.statistics.endPoints.driverStatistics = statistics/drivers_{tourId}.json
Data.config.statistics.endPoints.constructorStatistics = statistics/constructors_{tourId}.json
```

推测含义：

- `tourId`：当前 fantasy 赛季/游戏实例 id，不应该硬编码。
- `statistics.endPoints.*`：统计 feed 的相对路径模板，需要把 `{tourId}` 替换成当前 `tourId`。
- `imagePaths`：车手、车队、国旗、赛道、奖品等静态图片路径模板。
- `myTeam`、`homePage`、`leagues`：网页模块配置和部分私有功能 endpoint 名称；多数需要登录或不用于官方公开选队数据。

### `Data.constraints`

样本字段：

```text
ARRGamedayId
ActiveTour
DeadlineDate
FixtureUpdateFlag
GMCSubScenario
GamedayId
IsActiveForNewUser
IsLateOnboard
LPTourGamedayId
MatchdayId
MaxTeamValue
NextSeasonDeadline
PhaseId
ShowAnnouncementCard
ShowRaceweekTab
TREndGamedayId
isSwapSuggestion
```

推测含义：

- `GamedayId`：当前/目标 race week id。样本为 `7`。
- `ARRGamedayId`：当前 active race week id 列表。样本为 `[7]`。
- `LPTourGamedayId`：上一个已结算或最近完成的 gameday id。样本为 `6`。
- `DeadlineDate`：当前 race week 的锁定日期，格式是美国式日期字符串。
- `MaxTeamValue`：初始或规则层面的 cost cap，样本为 `100.0`。
- `PhaseId`、`GMCSubScenario`、`FixtureUpdateFlag`：网页状态/阶段控制字段，具体枚举未完全确认。
- `TREndGamedayId`：赛季最后 race week id，样本为 `22`。

### `Data.boosters`

样本字段：

```text
BoosterId
BoosterName
FromGameday
ToGameday
IsActive
IsExpiry
```

推测含义：

- `BoosterName`：chip/booster 名称，例如 `LIMITLESS`。
- `FromGameday` / `ToGameday`：可用范围。`0` 可能表示不限具体 gameday。
- `IsActive`：该 booster 当前是否可用。
- `IsExpiry`：是否存在过期状态。

## Common Statistics Feed

先从 `web_config.json` 解析：

```text
tourId = Data.config.tourId
endpoint = Data.config.statistics.endPoints.commonStatistics
```

当前实际 URL：

```text
https://fantasy.formula1.com/feeds/v2/statistics/driverconstructors_4.json
```

顶层字段：

```text
Data
Meta
```

`Data` 字段：

```text
season
driver
constructor
```

当前样本：

```text
Data.season = 2026
```

### `Data.driver[]` / `Data.constructor[]`

每一项是一个排行榜 group：

```text
config
participants
```

`config` 字段：

```text
category_id
columns
key
order
title
```

`config.columns[]` 字段：

```text
key
type
title
showOnMobile
```

`participants[]` 通用字段：

```text
playerid
playername
teamid
teamname
curvalue
statvalue
rnk
```

推测含义：

- `playerid`：fantasy asset id。车手和车队都用这个字段。
- `playername`：车手名；constructor 行通常为 `null`。
- `teamid`：车手所属 constructor id；constructor 行有时为 `null`，有时等于自身 id。
- `teamname`：车手所属车队名，或 constructor 名。
- `curvalue`：当前网页可见价格。应作为 `current_price` 的来源。
- `statvalue`：该 group 的统计值，含义随 `config.key` 改变。
- `rnk`：该 group 内排名。

### Driver group

当前 `Data.driver[].config.key`：

```text
fPoints
fAvg
priceChange
mostPicked
pointsPermillion
overTakepoints
podiumsStats
topFinshed
mostDnf
fastestLap
driverOfday
```

推测的 `statvalue` 含义：

| key | statvalue 含义推测 | 备注 |
|---|---|---|
| `fPoints` | 赛季 fantasy 总分 | 当前脚本用它做 `current_total_fpoints` |
| `fAvg` | 平均 fantasy 分 | 可能是赛季场均 |
| `priceChange` | 赛季累计价格变化趋势 | 不等于最近一站 price change |
| `mostPicked` | 被选择率百分比 | `type = percentage` |
| `pointsPermillion` | 每百万价格产出 | 价值效率指标 |
| `overTakepoints` | 超车相关累计分 | 字段名拼写为 `overTakepoints` |
| `podiumsStats` | 登台次数或登台相关统计 | 具体口径未校验 |
| `topFinshed` | 高名次完赛次数 | 官方字段拼写为 `topFinshed` |
| `mostDnf` | DNF / not classified 次数 | 风险参考 |
| `fastestLap` | 最快圈相关次数/分 | 具体口径未校验 |
| `driverOfday` | Driver of the Day 次数/分 | driver 专属 |

### Constructor group

当前 `Data.constructor[].config.key`：

```text
fPoints
fAvg
priceChange
mostPicked
pointsPermillion
overTakepoints
podiumsStats
topFinshed
mostDnf
fastestLap
fastestPitstopstats
```

推测的 `statvalue` 含义：

| key | statvalue 含义推测 | 备注 |
|---|---|---|
| `fPoints` | 赛季 fantasy 总分 | 当前脚本用它做 constructor `current_total_fpoints` |
| `fAvg` | 平均 fantasy 分 | 可能是赛季场均 |
| `priceChange` | 赛季累计价格变化趋势 | 不等于最近一站 price change |
| `mostPicked` | 被选择率百分比 | `type = percentage` |
| `pointsPermillion` | 每百万价格产出 | 价值效率指标 |
| `overTakepoints` | 两车合计超车相关累计分 | 具体口径未校验 |
| `podiumsStats` | 车队登台相关统计 | 具体口径未校验 |
| `topFinshed` | 两车高名次完赛相关统计 | 具体口径未校验 |
| `mostDnf` | constructor 旗下 DNF / not classified 次数 | 风险参考 |
| `fastestLap` | 最快圈相关次数/分 | constructor 口径 |
| `fastestPitstopstats` | 最快 pit stop 相关统计 | constructor 专属 |

## Driver / Constructor Statistics Endpoints

`web_config.json` 暴露了：

```text
https://fantasy.formula1.com/feeds/v2/statistics/drivers_4.json
https://fantasy.formula1.com/feeds/v2/statistics/constructors_4.json
```

当前直接访问结果：

```text
HTTP 403
```

结论：

- 这两个 endpoint 可能需要额外请求上下文、CDN 规则、或已废弃。
- 当前可用数据已经在 `driverconstructors_4.json` 中覆盖 driver 和 constructor 的主要公开排行榜。
- 本项目不应依赖这两个 403 endpoint。

## Player Stats Feed

URL 模板：

```text
https://fantasy.formula1.com/feeds/popup/playerstats_{asset_id}.json
```

样例：

```text
HUL: https://fantasy.formula1.com/feeds/popup/playerstats_111.json
Mercedes: https://fantasy.formula1.com/feeds/popup/playerstats_28.json
```

顶层字段：

```text
FeedTime
Value
```

`FeedTime` 字段：

```text
UTCTime
ISTTime
CESTTime
```

`Value` 字段：

```text
PlayerId
PlayerSkill
FixtureWiseStats
MatchWiseStats
GamedayWiseStats
TourWiseStats
```

推测含义：

- `PlayerId`：asset id。
- `PlayerSkill`：asset 类型编码，疑似 driver / constructor 区分字段；当前脚本不依赖它。
- `FeedTime`：该 playerstats feed 的生成时间。

## FixtureWiseStats

结构：

```text
Value.FixtureWiseStats[]
```

字段：

```text
GamedayId
TourId
RaceDayWise
```

`RaceDayWise[]` 字段：

```text
RaceDayId
DateTime
MatchStatus
MeetingLocation
MeetingNumber
MeetingName
CountryId
CountryName
CircuitOfficialName
SessionName
SessionType
SessionNumber
SessionStartDate
Season
TeamId
SelectedPercentage
CapSelectedPercentage
PlayerValue
OldPlayerValue
```

推测含义：

- `FixtureWiseStats` 是赛程和 session 元数据。
- `RaceDayWise[]` 一项对应一个 session，例如 `Sprint Qualifying`、`Sprint`、`Qualifying`、`Race`。
- `MatchStatus == "4"` 表示该 session 已完成。当前脚本把一个 gameday 的所有 session 都是 `"4"` 作为该 gameday complete 的条件。
- 当前样本中未完成 target round 可能出现 `MatchStatus = "1"` 或 `"0"`；具体枚举还未完全确认。
- `SelectedPercentage`：该 asset 被选择比例。
- `CapSelectedPercentage`：被设置为 captain/boost 的比例；具体口径未完全确认。
- `PlayerValue` / `OldPlayerValue` 在这里和该 gameday 的可见价格字段一致，但不应用它直接计算该 gameday 的赛后价格变化。

## MatchWiseStats

结构：

```text
Value.MatchWiseStats[]
```

字段：

```text
GamedayId
TourId
RaceDayWise
```

`RaceDayWise[]` 字段比 `FixtureWiseStats.RaceDayWise[]` 多：

```text
IsPlayed
StatsWise
```

`StatsWise[]` 字段：

```text
Frequency
Event
Value
```

推测含义：

- `MatchWiseStats` 是 session-level 得分拆解。
- `RaceDayWise[].StatsWise[]` 记录某个 session 内的具体得分项。
- 如果需要解释“某车手这一站为什么得这些分”，应临时查询这里。
- 默认 CSV 不输出这一层，因为它是调试/解释用明细，不是本站选队常规表。

## GamedayWiseStats

结构：

```text
Value.GamedayWiseStats[]
```

字段：

```text
GamedayId
PlayerValue
OldPlayerValue
IsPlayed
IsActive
StatsWise
```

`StatsWise[]` 字段：

```text
Frequency
Event
Value
```

推测含义：

- `GamedayWiseStats[]` 一项对应一个 race week / gameday。
- `StatsWise[]` 是该 gameday 的汇总得分项。
- `Event == "Total"` 是该 gameday fantasy 总分。
- `IsPlayed`：该 gameday 是否已经有赛后/结算数据。未完成 target round 可为 `0`。
- `IsActive`：asset 当时是否 active。

### 价格字段的关键结论

HUL 的数据说明，`GamedayWiseStats[].PlayerValue` 不能理解为“这一站赛后价格”。更合理的解释是：

```text
GamedayWiseStats[G].PlayerValue = 进入 gameday G 时网页可见价格
GamedayWiseStats[G].OldPlayerValue = 进入 gameday G 前的上一次可见价格
```

因此，gameday G 的赛后实际 price change 应该用下一次可见价格计算：

```text
price_change_for_gameday_G = next_visible_price - GamedayWiseStats[G].PlayerValue
```

其中：

- 如果存在下一条 `GamedayWiseStats[G + 1]`，`next_visible_price = GamedayWiseStats[G + 1].PlayerValue`。
- 如果 G 是最新已完成且下一条未抓到，则 `next_visible_price = commonStatistics fPoints group 的 curvalue`。

不要把：

```text
GamedayWiseStats[G].PlayerValue - GamedayWiseStats[G].OldPlayerValue
```

当成 gameday G 的赛后价格变化。它更像是“进入 G 之前已经发生的价格变化”。

### HUL 证据

HUL `asset_id = 111` 的样本：

```text
Gameday 5: PlayerValue = 4.4, OldPlayerValue = 5.0, IsPlayed = 1
Gameday 6: PlayerValue = 3.8, OldPlayerValue = 4.4, IsPlayed = 1
Gameday 7: PlayerValue = 3.5, OldPlayerValue = 3.8, IsPlayed = 0
commonStatistics curvalue = 3.5
```

如果要算 gameday 6 的赛后价格变化：

```text
正确：Gameday 7 PlayerValue - Gameday 6 PlayerValue = 3.5 - 3.8 = -0.3M
错误：Gameday 6 PlayerValue - Gameday 6 OldPlayerValue = 3.8 - 4.4 = -0.6M
```

这说明旧逻辑把“进入本站前的价格变化”误读成了“本站赛后价格变化”。

## TourWiseStats

结构：

```text
Value.TourWiseStats[]
```

字段：

```text
TourId
PlayerValue
OldPlayerValue
IsPlayed
IsActive
StatsWise
```

推测含义：

- `TourWiseStats` 是赛季/tour 级别汇总。
- `StatsWise[]` 中 `Event == "Total"` 是赛季累计 fantasy 总分。
- 其他 `StatsWise` 项是赛季累计事件分或次数。
- `PlayerValue` 是当前可见价格，`OldPlayerValue` 是上一次可见价格。
- 这层可以用来 sanity check 当前总分和当前价格，但常规选队 CSV 仍优先用 `commonStatistics` 的 `curvalue` / `statvalue`。

## StatsWise 事件名

Driver 样本出现的 `Event`：

```text
Total
Qualifying Position
Sprint Position
Sprint Position lost
Sprint overtake bonus
Sprint Not Classified
Race Position
Race position gained
Race Position lost
race overtake bonus
Race not classified 
```

Constructor 样本额外出现：

```text
Both Driver Q3
Race Fastest lap
Sprint Fastest lap
Fastest Pitstop
2nd Fastest Pitstop
```

注意：

- 事件名大小写和空格不完全规整，例如 `race overtake bonus` 小写开头，`Race not classified ` 末尾有空格。
- 解析时不要手写过于严格的字符串集合；至少 `Total` 需要精确用于总分。

## 当前脚本字段映射

`fetch_fantasy_public.py` 当前应使用以下映射：

| CSV 字段 | 来源 | 说明 |
|---|---|---|
| `asset_id` | common `participants[].playerid` | driver / constructor 共用 |
| `type` | common 中所在数组 | `driver` 或 `constructor` |
| `name` | `playername` 或 `teamname` | constructor 用 `teamname` |
| `current_price` | common fPoints `curvalue` | 当前网页可见价格 |
| `current_total_fpoints` | common fPoints `statvalue` | 当前赛季 fantasy 总分 |
| `rank` | common fPoints `rnk` | 总分榜排名 |
| `last1_round_id` | 最近一个 complete 且早于 target 的 `GamedayId` | 不包含未完成 target |
| `last1_fpoints` | last1 `GamedayWiseStats[].StatsWise[Total].Value` | 最近已完成站单站分 |
| `last1_price` | last1 `GamedayWiseStats[].PlayerValue` | 进入 last1 时的价格 |
| `last1_price_change` | 下一次可见价格 - `last1_price` | 若下一条是 target incomplete，则用该 target 的 `PlayerValue`；也可等价于 current `curvalue - last1_price` |
| `last2_round_id` | last1 之前一个 complete gameday | 只取 target 前已完成站 |
| `last2_fpoints` | last2 `Total` | 倒数第二个已完成站单站分 |
| `last2_price` | last2 `PlayerValue` | 进入 last2 时的价格 |
| `last2_price_change` | last1 `PlayerValue - last2 PlayerValue` | last2 赛后到 last1 赛前的可见价格变化 |
| `rolling2_fpoints` | `last1_fpoints + last2_fpoints` | target-round 预测基础 |
| `score_floor_*` | 价格区间公式 | 只用于 target-round 分数线预测 |
| `is_active` | 最新 playerstats row 的 `IsActive` | asset 是否 active |

## 当前不应直接相信的字段

- 不要用 `GamedayWiseStats[G].PlayerValue - GamedayWiseStats[G].OldPlayerValue` 当作 gameday G 的赛后 price change。
- 不要用 common `priceChange` group 的 `statvalue` 当最近一站 price change；它更像赛季累计价格趋势。
- 不要把未完成 target round 的 `StatsWise[Total]` 放进 `rolling2_fpoints`。
- 不要把 `MatchStatus != "4"` 的 session 当成完成。

## 仍需继续验证的问题

- `MatchStatus` 的完整枚举：目前只确认 `"4"` 可作为完成，`"0"` / `"1"` 出现在未完成 target round。
- `PlayerSkill` 的枚举含义：疑似 asset 类型编码，但当前不需要依赖。
- `priceChange` group 的 `statvalue` 是否严格等于赛季累计价格变化，需要用多个资产从初始价回算验证。
- `CapSelectedPercentage` 的精确定义：推测是 captain/boost 选择比例。
- 低价下限与高价上限的官方裁剪规则：HUL 说明至少存在 `3.5M` 底价或类似裁剪行为，但完整上下限还需要更多样本。
