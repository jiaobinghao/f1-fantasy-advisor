# F1 Fantasy Advisor

[![tests](https://github.com/jiaobinghao/f1-fantasy-advisor/actions/workflows/tests.yml/badge.svg)](https://github.com/jiaobinghao/f1-fantasy-advisor/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English README](README.md)

F1 Fantasy Advisor 可以让你用 Codex 做 Formula 1 Fantasy 助手。它会维护公开 fantasy 数据，追踪价格和每站积分，并把这些信息转化成阵容、芯片和预算增长建议。

顺带一提，我发现了一个[网站](https://f1fantasytools.com)，它的数据比我这里更全。我仍然觉得 f1-fantasy-advisor 有用，但我以后可能不再更新它了。

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
- 每队当前剩余的免费转会次数
- 你的 league 目标：爬预算、冲分、稳妥打法，或分队覆盖风险

advisor 会把这些私有比赛周状态记录到本地 `data/` 里的 CSV，所以你不用每次重新讲一遍。

advisor在检测到 `data/` 没有任何 team 状态时，会提示你初始化一个 team 的状态。你可以在对话中直接提供车手/车队名字，也可以提供fantasy网站的截图。

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

价格建议需要考虑底价规则：车手最低售价为 `3.0M`。处在 `3.0M` 的车手不会继续亏 budget，但仍可能因为正赛分数、退赛风险或占用转会名额而成为卖出对象。

这些 feed 不需要你的 F1 Fantasy 登录信息。它们是网站使用的公开 feed，不是官方承诺长期稳定的 API，所以项目仍保留手动 CSV 或截图作为兜底。

## 比赛周中的 live 数据

比赛周进行中，fantasy 网站可能在排位、冲刺排位或冲刺赛后显示临时分数。advisor 可以用这些 live 分数做观察，但在整个比赛周完成前，不应把它们纳入 budget 或 rolling-score 状态。

## 本地运行

环境要求：

- Python 3.10 或更新版本
- 可以访问 `fantasy.formula1.com`（官方数据抓取）
- 可以访问 `f1fantasytools.com`（第三方网站，仅 Live 本站工具需要）
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

### 近期行为变化

- 数字解析与格式化改为全部脚本共享：四舍五入后为负零的值显示为 `0`；
  价格/分数清洗在所有脚本统一接受 `$`、`M`、`,`、`+`、`▲`、`▼`。
- `best_live_lineup.py` 校验 Live 缓存时改为优先比较比赛名称；同一场比赛
  但轮次编号不同只会告警，因为官方 GamedayId 和 Live 站点的站序是两套编号。
- `fantasy_state.py record-team` 会拒绝不在阵容内的 boost id；当
  `assets_state.csv` 有数据时，还会拒绝未知 asset id 或不是 5 车手 + 2 车队
  的阵容。
- Live 页面的车手/车队三字母代码可以用 `data/official/asset_codes.csv`
  覆盖（表头模板在 `data-templates/`）；内置表覆盖当前车队和不规则车手代码。
- 交互模式在输入流结束（退出码 1）或 Ctrl-C（退出码 130）时干净退出，
  不再打印 traceback。

## 工具说明

### 官方数据收集

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/fetch_fantasy_public.py --out-dir data/official
```

### auto-pilot计算

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/auto_pilot_lineup.py 112
python3 skill-dev/f1-fantasy-advisor/scripts/auto_pilot_lineup.py 112 --top 10
```

### 从上周阵容计算本周最佳阵容

交互式输入上周 5 位车手、2 个车队和剩余 budget，并自动考虑超额换人扣分：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/best_lineup_with_transfers.py --interactive
```

### Live 本站阵容计分

分成两个独立步骤。首先通过 [f1fantasytools.com](https://f1fantasytools.com)
（第三方网站）Live 页面使用的公开 `/api/live-scoring` 接口获取水合后的最新分数
并缓存（每次运行请求一次）；下文的剪贴板和文件导入是兜底方案：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --fetch
```

随后从缓存交互选择 5 位车手、2 个车队和 2x 车手，并计算本站得分：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --interactive
```

把缓存的本站 Live 分数与官方快照中的上一站 `last1_price` 合并后，可直接求
本站理论最高分阵容：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/best_live_lineup.py budget 112
```

也可以交互输入上周阵容和剩余资金，求扣除超额换人罚分后的本站最高分阵容：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/best_live_lineup.py transfers --interactive
```

该桥接脚本不会修改 `auto_pilot_lineup.py` 或
`best_lineup_with_transfers.py`。它会校验 Live 轮次与官方目标轮次一致；Live
状态尚未 finalized 时仍可分析，但结果会标记为 provisional。

页面结构变化或网络不可用时，可以从剪贴板导入作为兜底：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --fetch --clipboard
```

也可以把网页表格文本、接口 JSON 或完整 HTML 保存成文件后导入。完整 HTML
只包含页面初始快照，可能比水合后的接口数据旧：

```bash
python3 skill-dev/f1-fantasy-advisor/scripts/live_lineup_score.py --fetch --input live_scores.txt
```

## 大致阵容评估

如果你想先了解当前阵容有哪些值得调整的地方，可以让 advisor 做一次大致评估。适合比赛周刚开始、练习赛还没跑完，或者你只想先筛选几个换人方向的时候。

你可以直接说：

```text
先帮我粗看本周三队阵容，不跑完整模拟。
指出优先保留、考虑更换的车手和车队，兼顾本周得分和预算增长。
```

advisor 会读取你已保存的阵容、余额和剩余免费转会次数，结合近期比赛表现、当前价格、涨跌价门槛，以及已有的练习赛和新闻信息，给出：

- **保留与更换的优先级**：哪些位置值得继续持有，哪些价格偏高、近期表现偏弱，或可能拖累预算。
- **可考虑的转会方向**：在现有预算下有哪些替代选择，是否需要付出额外转会扣分，以及这笔调整主要为了得分还是涨价。
- **预算机会与风险**：谁距离涨价门槛较近，谁有跌价压力；便宜车手是否值得占用一个阵容位置。
- **需要继续观察的消息**：例如等待下一节练习赛验证速度，或等待发车处罚确认后再决定换人。

这一步给出的是有依据的初步判断，不会把某套阵容称为已经计算出的最优解，也不会把达到涨价门槛的机会说成保证涨价。如果你想知道“这次换人预计多拿几分”“为了涨预算让出多少分值得”，可以继续做详细预测。

## 详细预测与阵容评估

如果你希望在提交阵容前比较具体方案，可以让 advisor 运行概率预测。它会模拟多种可能的比赛结果，计算车手、车队和整套阵容的预计得分与价格变化，再按照你的预算和转会限制筛选组合。普通比赛周和冲刺比赛周都可以使用。

你可以直接说：

```text
结合本周练习赛和新闻，详细计算三队阵容。
允许比最高预计积分少最多 10 分，优先积累预算，并解释每笔转会。
```

你不需要自己准备配置文件或查询公开统计。advisor 会复用已保存的账号信息、获取公开数据并运行程序；如果你已经在官网提交过换人，请告诉它更新后的阵容、余额和剩余免费转会次数，避免按旧状态计算。

预测会参考近期比赛、已完成的练习赛排名和相关的新闻。历史统计默认取最近四个有效比赛周，由近到远的权重为 `1、0.75、0.5、0.25`，让近期表现有更大影响；冲刺项目使用最近四个有效冲刺周末。这个权重只用于历史部分。排位和正赛分别使用各自的历史成绩估计速度，有练习资料时，两者各按“历史 60%＋练习 40%”混合；冲刺同样使用独立的冲刺历史。正赛排序中，发车位权重由固定赛道附表决定：`g_c = 0.2 + 0.6 * d_c`，范围为 20%—80%，其余权重给抽样正赛速度排名。附表随 skill 保存，也展示在本 README 末尾，每周直接查表；未知赛道暂用 50% 中性权重并明确提示。这里的历史正赛速度由完赛名次估计，还不是实测圈速。

有效超车与最终名次变化关联：有净上升时，用历史“上升位数／有效超车数”比例换算；车手样本不足时回退车队或全场。平位、掉位和已发车退赛仍可有有效超车，使用相应历史样本。赛道权重与比例换算都保留来源及回退标记，仍属于未校准模型。

新闻目前用于修正练习中遭遇意外、明确的赛车不稳定表现，以及发车处罚。对于罚退车手，会同时考虑追赶和超车得分的机会，以及最终名次可能降低的代价；处罚尚未确认时，会说明不同条件下的结果。

你会得到每支队伍的具体建议：

- **推荐阵容和操作**：5 位车手、2 个车队、2x 车手、换入换出名单、转会扣分和换人后的余额。
- **积分优先与预算优先两套方案**：分别列出扣除转会罚分后的预计积分、预计阵容涨跌价，以及预算方案让出了多少预计积分；两套方案也可能相同。
- **与少操作方案的对比**：保持现有阵容、只用免费转会和额外付分换人之间的差别，帮助你判断是否值得调整。
- **推荐理由和不确定性**：关键得分来自排位、完赛名次、超车还是其他项目，表现较差、一般和较好时的模拟得分大致如何，以及哪些数据不足或消息可能改变建议。

默认会先找出**扣除转会罚分后预计积分最高**的阵容，再在与它相差不超过 **10 分**的合法阵容中，选预计预算增长最多的一套。这是命令行参数 `--allow 10` 的含义，参照的是积分最高方案，不是你的原阵容，也不是实际比赛最多只会少拿 10 分。

例如，假设积分优先方案预计得到 200 分、阵容涨价 0.3M，另一套预计得到 194 分、涨价 0.9M。后者少 6 分，符合默认的 10 分额度，会作为预算候选；最终仍要与其他符合额度的阵容比较。这些数字仅用于说明取舍。这里的预算增长指持有的车手和车队预计涨价，购买便宜阵容后留下的现金会单独列出。

如果本周只想冲分，可以说“这次不为涨预算让分”，对应 `--allow 0`。如果你对某个人选有疑问，也可以继续问“比较保留和卖出贝尔曼的最佳组合”，advisor 会比较两边完整阵容的得分和预算，而不只比较两位车手。

预测提供的是当前数据和模型假设下的比较。默认参数还没有经过样本外回测，预计积分、涨价和结果范围都不保证兑现；预算建议目前着眼于本站的预计增长。缺少必要的价格历史时，仍可给出积分方案，并说明预算方案暂时无法计算。当前自动预测支持普通固定 2x；芯片需另外评估，Final Fix、锁定后换人和全赛季芯片分配尚未纳入这套计算。

想了解具体操作，可查看[比赛周运行指南](skill-dev/f1-fantasy-advisor/references/race-week-runbook.md)；希望自行运行示例或配置数据，可查看[输入与命令说明](skill-dev/f1-fantasy-advisor/references/forecast-inputs.md)；计分公式、概率估计和计算细节见[预测模型文档](skill-dev/f1-fantasy-advisor/references/forecast-model.md)。

## 固定赛道系数附表

固定数据见 [circuit-profiles.json](skill-dev/f1-fantasy-advisor/references/circuit-profiles.json)，版本 `2026-11-01.v2`。预测只查表，不按周重新求解。**$d_c$ 越大，越难超车，发车位影响越大**：

```math
\begin{aligned}
g_c &= 0.2 + 0.6\,d_c, \qquad 0 \le d_c \le 1 \\[6pt]
K_i &= \underbrace{g_c G_i}_{\text{发车位影响}}
     + \underbrace{(1-g_c)R_i}_{\text{速度影响}}
\end{aligned}
```

$G_i$ 为处罚后的发车位，$R_i$ 为抽样速度名次；全场按 $K_i$ 排序得到完赛位 $F_i$。当 $d_c$ 分别为 $0$、$0.5$、$1$ 时，发车位权重依次为 20%、50%、80%。正赛与冲刺共用系数；未知赛道暂用 $d_c=0.5$ 并提示。

这是根据下列公开赛道介绍、历史比赛例子和布局作出的初始人工评估，**未拟合统一的往年超车数据，也未回测出最优值**。0.0 为最易；0.1—0.3 为进攻机会较多；0.4—0.6 为中等或受限；0.7—0.9 为困难；1.0 为极难档，包括摩纳哥和马德里。系数不是概率，档距 0.1 也不代表精确测量。链接提供布局/历史依据，具体数值是本模型的判断。

按 [2026 年官方赛历](https://www.formula1.com/en/racing/2026)（2026-11-01 查阅）覆盖 23 个赛道，另保留萨基尔、吉达和伊莫拉。比赛迁址时按物理赛道识别，例如马来西亚举办的巴林大奖赛使用雪邦系数。标 * 的条目证据置信度低：马德里可比 F1 历史有限，雪邦近期可比 F1 场次有限。马德里与摩纳哥同档、蒙扎最低难度档，按用户要求作为模型假设固定。其余条目也仍未校准。

| 赛道 | 难度 $d_c$ | 发车位权重 | 速度权重 | 评估依据 |
|---|---:|---:|---:|---|
| [澳大利亚·阿尔伯特公园](https://www.formula1.com/en/racing/2025/australia/circuit) | 0.3 | 38% | 62% | 改线后速度快，但连续弯之间可用的重刹超车点仍有限。 |
| [中国·上海](https://www.formula1.com/en/racing/2025/china/circuit) | 0.1 | 26% | 74% | 1.2 公里后直道接发卡弯，为追车提供主要机会。 |
| [日本·铃鹿](https://www.formula1.com/en/racing/2025/japan/circuit) | 0.5 | 50% | 50% | 连续高速弯增加跟车难度，超车集中在少数制动区。 |
| [迈阿密](https://www.formula1.com/en/racing/2025/miami/circuit) | 0.2 | 32% | 68% | 三段直道有利追赶，低速狭窄段仍限制跟车。 |
| [加拿大·维伦纽夫](https://www.formula1.com/en/racing/2025/canada/circuit) | 0.2 | 32% | 68% | 启停布局、发卡弯与重刹区提供超车机会。 |
| [摩纳哥](https://www.formula1.com/en/racing/2025/monaco/circuit) | 1.0 | 80% | 20% | 极窄街道；官方介绍引用 2003 年零次超车，发车位置影响极大。 |
| [巴塞罗那·加泰罗尼亚](https://www.formula1.com/en/racing/2025/spain/circuit) | 0.4 | 44% | 56% | 混合高速低速弯对跟车有要求，主要机会在主直道末端。 |
| [奥地利·红牛环](https://www.formula1.com/en/racing/2025/austria/circuit) | 0.1 | 26% | 74% | 三段直道与上坡重刹区支持连续进攻。 |
| [英国·银石](https://www.formula1.com/en/racing/2025/great-britain/circuit) | 0.2 | 32% | 68% | 高速接近区与较宽弯道有利争夺，连续高速弯仍有跟车损失。 |
| [比利时·斯帕](https://www.formula1.com/en/racing/2025/belgium/circuit) | 0.1 | 26% | 74% | 长直道利于尾流进攻，高速中段也能体现速度差。 |
| [匈牙利·亨格罗宁](https://www.formula1.com/en/racing/2025/hungary/circuit) | 0.7 | 62% | 38% | 短直道与连续弯限制进攻，官方以摩纳哥级下压力需求作比较。 |
| [荷兰·赞德沃特](https://www.formula1.com/en/racing/2025/netherlands/circuit) | 0.6 | 56% | 44% | 起伏连续弯限制超车，倾斜弯和主直道提供部分机会。 |
| [意大利·蒙扎](https://www.formula1.com/en/racing/2025/italy/circuit) | 0.0 | 20% | 80% | 按用户设定归入最低超车难度档；长直道与减速弯重刹支持这一模型判断。 |
| [西班牙·马德里](https://www.formula1.com/en/racing/2026/spain/circuit) * | 1.0 | 80% | 20% | 按用户设定归入与摩纳哥相同的最高超车难度档；可比较的 F1 历史有限，仍属未校准假设。 |
| [阿塞拜疆·巴库](https://www.formula1.com/en/racing/2025/azerbaijan/circuit) | 0.3 | 38% | 62% | 超长直道抵消部分旧城区狭窄段限制，不能只按直道长度判断。 |
| [马来西亚·雪邦](https://www.racingcircuits.info/asia/malaysia/sepang.html) * | 0.1 | 26% | 74% | 宽赛道、两条长直道及重刹区利于进攻；近期可比较的 F1 场次有限。 |
| [新加坡·滨海湾](https://www.formula1.com/en/racing/2025/singapore/circuit) | 0.8 | 68% | 32% | 2023 年改线后仍是多弯街道，赛道位置依然重要。 |
| [美国·奥斯汀](https://www.formula1.com/en/racing/2025/united-states/circuit) | 0.1 | 26% | 74% | 宽阔一号弯与长直道重刹区提供多种进攻路线。 |
| [墨西哥城·罗德里格斯](https://www.formula1.com/en/racing/2025/mexico/circuit) | 0.4 | 44% | 56% | 长主直道利于进攻，但高海拔与连续弯、体育场段限制持续追赶。 |
| [巴西·英特拉格斯](https://www.formula1.com/en/racing/2025/brazil/circuit) | 0.1 | 26% | 74% | 塞纳 S 与四号弯前的加速区利于追赶，内场连续弯仍有约束。 |
| [拉斯维加斯](https://www.formula1.com/en/racing/2025/las-vegas/circuit) | 0.0 | 20% | 80% | 长直道与重刹区丰富，官方赛道介绍明确强调超车机会。 |
| [卡塔尔·卢赛尔](https://www.formula1.com/en/racing/2025/qatar/circuit) | 0.5 | 50% | 50% | 中高速弯占多数，主要超车机会集中在主直道接一号弯。 |
| [阿布扎比·亚斯码头](https://www.formula1.com/en/racing/2025/united-arab-emirates/circuit) | 0.3 | 38% | 62% | 长直道与 2021 年改线改善超车，后段弯道仍限制跟车。 |
| [巴林·萨基尔 GP 布局](https://www.formula1.com/en/racing/2025/bahrain/circuit)（补充） | 0.0 | 20% | 80% | 多处重刹进攻点，官方评价为通常有较多超车。 |
| [沙特·吉达](https://www.formula1.com/en/racing/2025/saudi-arabia/circuit)（补充） | 0.2 | 32% | 68% | 高速街道的长加速区有利进攻，狭窄高速连续弯仍有限制。 |
| [艾米利亚-罗马涅·伊莫拉](https://www.formula1.com/en/racing/2025/emiliaromagna/circuit)（补充） | 0.7 | 62% | 38% | 传统连续弯布局，主要超车机会集中在主直道末端。 |

只有显著改线、规则变化或经过验证的新证据才更新附表和版本；天气、单场事故不触发每周重算。每次结果保存使用的附表快照、版本与内容哈希，便于复跑。赛道系数经 $g_c \to F_i \to D_i \to D_i/q_i$ 影响净上升时的有效超车，不再额外乘一遍超车折扣。

## 预测计算原理

程序先从锁定前可用的数据估计概率，再模拟完整比赛周末，逐项计算每位车手和车队的积分与价格变化。这里描述当前 v1 实现，赛道附表使用 `2026-11-01.v2`；每次运行的实际参数和数据来源以输出文件为准。

**1. 从数据估计概率与速度。**

历史部分使用各估计池最近四个有效比赛周，权重由近到远为 `1、0.75、0.5、0.25`。不同池的有效轮次可能不同：冲刺用冲刺历史，超车比例用符合条件的正上升历史，缺失场次不会作为零表现加入。

排位、正赛、冲刺分别根据各自的历史名次估计速度评分，不共用一份历史排位评分。有练习资料时，各场次的混合评分为：

```math
A_{i,k} = 0.6\,H_{i,k} + 0.4\,\mathrm{FP}_{i,k},
\qquad k \in \{\mathrm{Q},\mathrm{R},\mathrm{Sprint}\}
```

其中 $H_{i,k}$ 是对应场次的历史评分，$\mathrm{FP}_{i,k}$ 是经过新闻修正的练习评分。FP1、FP2、FP3 默认权重为 `0.2、0.3、0.5`，只在该车手有可用评分的节次之间重新归一化。新闻仅对受影响的练习节次做事故补偿或操控不稳定修正；没有参加 FP1 的正式车手不会继承替补车手的排名。事故导致没有排名时，回退该预测场次的历史评分；完全没有可用练习资料时，历史权重为 100%。这些评分仍是名次表现的代理，不是清洗后的实测圈速。

状态概率另用先验平滑。对车手 $i$、某一场次的状态 $c$：

```math
\widehat{P}_i(c) =
\frac{
  \underbrace{8\,P_{\mathrm{prior},i}(c)}_{\text{先验}}
  + \underbrace{\displaystyle\sum_t w_t\,\mathbf{1}_{\{X_{i,t}=c\}}}_{\text{近期观测}}
}{8 + \displaystyle\sum_t w_t}
```

状态先验优先来自同赛季其他车手的同类场次记录，缺少历史时才使用有来源的显式先验。模型先区分正常分类、未分类组和取消资格；正赛与冲刺再根据是否发车的历史证据，将未分类组拆成已发车 NC 和未起步 DNS。

因此，**最近四站不是概率的唯一来源**。每站一条记录时，四站权重合计 2.5，而先验强度是 8，先验约占这个平滑公式总权重的 76%。这个参数影响较大，尚未校准；它也不是“历史 60%＋练习 40%”中的速度混合权重。

**2. 抽取排位结果，并应用罚退。**

程序抽取排位的分类状态，再将排位混合评分转换为排序强度：

```math
a_{i,k} = \exp\!\left(\frac{A_{i,k}-n}{\tau}\right),
\qquad \tau=3
```

$n$ 为当前参赛车手数，排名温度 $\tau$ 默认为 3。按剩余车手的相对强度抽取无重复的速度顺序，再结合分类状态得到排位名次和 Q2/Q3 晋级结果。正赛与冲刺速度也使用这一抽样方法，但各用自己的评分。

确认的罚退按本季规则作用于全场发车顺序，不改变原排位积分。已有官方发车表时使用官方表，不重复应用其中已生效的处罚。未确认处罚有可靠概率时按概率混合；没有概率依据时分别展示条件分支，主结果只包含已确认处罚。冲刺发车顺序单独处理，不直接复制正赛发车位。

**3. 抽取正赛速度，生成完赛顺序与有效超车。**

先抽取正赛分类状态和潜在速度名次 $R_i$，再对正常分类车手按下式从小到大排序：

```math
\begin{aligned}
g_c &= 0.2 + 0.6\,d_c, \qquad 0 \le d_c \le 1 \\[6pt]
K_i &= \underbrace{g_c G_i}_{\text{发车位影响}}
     + \underbrace{(1-g_c)R_i}_{\text{速度影响}}
\end{aligned}
```

$G_i$ 为处罚后的发车位，$d_c$ 从前面的固定赛道附表读取。当前摩纳哥和马德里为 `80% 发车位＋20% 速度`，蒙扎为 `20%＋80%`，墨西哥为 `44%＋56%`。正赛与冲刺共用赛道系数，未知赛道暂用 `50%＋50%` 并提示。

对全场排序后得到整数完赛位 $F_i$；$K_i$ 是排序指标，不能直接四舍五入成完赛名次，同值时按发车顺序处理。这是**按名次混合的简化模型**，没有逐圈模拟轮胎、进站策略或交通。

有效超车与最终名次变化关联。由于名次数字越小越靠前，净上升为 $D_i=G_i-F_i$。对正常分类且 $D_i>0$ 的车手：

```math
\begin{aligned}
q_i &= \frac{\displaystyle\sum_t w_t\bigl(G_{i,t}-F_{i,t}\bigr)}
             {\displaystyle\sum_t w_t O_{i,t}} \\[8pt]
\lambda_i &= \frac{D_i}{q_i}, \qquad D_i=G_i-F_i>0
\end{aligned}
```

历史比例只用有净上升、发车位和完赛位已知的正常分类记录，并保留其中的零超车记录。使用加权和之比，避免逐场比值除零。车手有效样本量不足时依次回退当前车队、全场，仍不足则用历史次数回退；若足够的正上升历史全部为零超车，换算出的超车数也为零。

期望超车数 $\lambda_i$ 通过保留期望的随机取整变成整数。例如 $\lambda_i=2.3$ 时，70% 抽到 2 次，30% 抽到 3 次。平位、掉位和已发车 NC 使用相应历史超车样本，DNS/DSQ 的超车奖励为零。赛道已经通过 $g_c \to F_i \to D_i \to D_i/q_i$ 产生影响，不再额外乘一次赛道折扣。

**4. 抽取其他计分事件，并计算车队分。**

最快圈和最佳车手（DOTD）使用历史获奖分布及先验平滑，在合法候选和“无人获奖”之间抽样；每个奖项每场最多一位获奖者，冲刺没有 DOTD。进站表现从历史样本抽取，再比较各队表现产生最快进站获奖者。

公共数据流程通常使用历史进站计分档位代理；只有各队都有可用实测样本时才切换为实测模式。缺少完整进站次序和赛前纪录资料时，不生成世界纪录奖励。车队分按照规则，从**同一情景**中的两名车手表现及车队专属项目派生，包括晋级、进站及适用的额外处罚，不单独抽取一个与两位车手无关的车队总分。

**5. 逐情景计分、计算涨跌价，然后取平均。**

令资产 $i$ 在情景 $s$ 的原始积分为 $S_i^{(s)}$，单个分支生成 $N$ 个等权情景（默认 $N=8192$），则车手和车队的预计积分都用：

```math
\boxed{\displaystyle\widehat{\mu}_i = \frac{1}{N}\sum_{s=1}^{N} S_i^{(s)}}
```

以 $P_i$ 表示当前价格，$\mathbf{h}_i$ 表示前两站已结算积分。涨跌价先对**每个情景的原始积分**应用本地价格模型，再平均：

```math
\widehat{\mathbb{E}}\!\left[\Delta P_i\right] =
\frac{1}{N}\sum_{s=1}^{N}
f\!\left(P_i,\,\mathbf{h}_i,\,S_i^{(s)}\right)
```

价格函数有分档门槛，因此不能先求平均积分，再只计算一次涨跌价；2x 和转会扣分也不进入资产涨跌价计算。缺少必要的价格历史时，预计涨跌价会标为不可用。

如果合并了有概率依据的罚退分支，则使用输出情景的实际权重 $p_s$，而不是统一除以 8192：

```math
\begin{aligned}
\widehat{\mu}_i
  &= \sum_s p_s\,S_i^{(s)} \\[6pt]
\widehat{\mathbb{E}}\!\left[\Delta P_i\right]
  &= \sum_s p_s\,f\!\left(P_i,\,\mathbf{h}_i,\,S_i^{(s)}\right) \\[6pt]
\sum_s p_s &= 1
\end{aligned}
```

例如，下面是**计分演算示例，不对应当前输出中的某个真实情景 ID**：一位车手排位第 8、发车第 8、正常完赛第 3，有效超车 1 次，没有最快圈或 DOTD。在当前 2026 计分规则下，标准周末得分为：

```math
\begin{aligned}
S_i^{(s)}
  &= \underbrace{3}_{\text{排位}}
   + \underbrace{15}_{\text{正赛}}
   + \underbrace{(8-3)}_{\text{位置上升}}
   + \underbrace{1}_{\text{超车}} \\[6pt]
  &= \boxed{24}\ \text{分}
\end{aligned}
```

这是一次可能的结果；全部情景加权平均后才得到该车手的预计积分。具体车手的均值会随输入、参数和模型版本变化，不能把某次旧预测的数字当成固定结论。

**6. 用预计积分和预算增长比较完整阵容。**

对每支账号队伍分别搜索合法的 5 位车手、2 个车队组合。普通固定 2x 下，阵容预计积分是各资产预计积分之和，再加一次所选 2x 车手的预计积分，减去额外转会费用；2x 人选在所有情景中保持一致。先找净预计积分最高方案，再在少分不超过 `--allow`（默认 10）的所有合法阵容中，找预计资产涨价总和最高的方案。两套方案都会展示，这仍是单站预算积累策略。

**为什么默认是 8192 个情景？**

[生成器默认参数](skill-dev/f1-fantasy-advisor/scripts/forecast_generate.py)将 `samples` 设为 8192，`seed` 设为 42。每个处罚分支默认生成 8192 次模拟，每次包含全场车手和车队；单个分支中的权重为 $1/8192$。有 $B$ 个正概率分支合并时，总情景数为 $B \times 8192$，每条情景的权重为对应分支概率除以 8192。独立的情景 ID 不保证比赛结果互不相同。

$8192=2^{13}$，但当前算法**不要求样本量是 2 的幂**；可以在运行配置的 `model_parameters` 中把 `samples` 改为 8000、10000 或 32768。它只是计算成本与抽样波动之间的默认取值，不是历史比赛数，也没有特殊的比赛含义。**目前没有通过收敛实验证明 8192 已经足够，更不能称为最优样本量。**

对单个分支的简单等权抽样，均值标准误差近似为：

```math
\mathrm{SE}\!\left(\widehat{\mu}_i\right)
\approx \frac{\sigma_{i,\mathrm{scenario}}}{\sqrt{N}}
```

$\sigma_{i,\mathrm{scenario}}$ 为情景积分的标准差；样本量增至四倍，抽样标准误差大致减半。它只描述模拟抽样波动，不包含数据误差或模型偏差，也不是实际比赛得分的预测区间。分支混合复用了配对随机数，不能把合并后的总情景数直接套进这条简单公式。固定输入、代码、附表版本和随机种子可复现结果，但不代表模型已经校准。

## 许可证

本项目使用 [MIT 许可证](LICENSE)。
