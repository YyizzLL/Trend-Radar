# 二创热点雷达

> English version: [`README.en.md`](README.en.md) ｜ 当前版本：**v0.5.0**

每天扫一遍抖音，回答一个问题：**今天有什么东西可以直接拿来剪视频。**

输出的不是「今天有哪些娱乐新闻」，而是三类可复用资产：

- **BGM** —— 正在被大量使用的歌（不只看榜单）
- **文案** —— 能直接当标题/字幕的一句话，带「多少条在用」的证据
- **玩法** —— 能照着做的挑战 / 模板

产物是一份 Markdown 日报，可以发邮件，也可以只看本地文件。

---

## ⚠️ 先读这段：这个版本靠对话 Agent 运行

**它不是「装好就每天自动出报」的工具。**

原因只有一个：**「今天该搜谁」需要联网查「最近有什么活动」**——
比如某场大赏的出演名单、某档音综的嘉宾，这些信息不在抖音榜单里，也不在固定 RSS 里。
这一步现在由对话里的 Agent 完成（联网搜索 → 语义映射到词库 → 写计划文件），
项目本身只负责**执行计划**：采集 → 判定 → 出报。

三种用法：

| 用法 | 谁决定搜什么 | 要不要人 | 覆盖 |
|---|---|---|---|
| **A. 对话 Agent（默认）** | Agent 联网搜活动 → 写 `data/input/query_plan.json` | 每天开一次对话，说「跑今天的」 | 最宽，能挖到活动阵容 |
| **B. 纯脚本** | `scripts/plan_queries.py` 只用热榜 / 榜单 / 热种 | 不用 | 窄：只看当天有没有人发歌、上榜 |
| **C. 脚本 + 搜索 API** | `scripts/discover_events.py` 调搜索 API（**尚未实现**） | 不用 | 接近 A，需要注册一个 key |

> **如果你的目标是无人值守的全自动**，需要接入一个搜索 API（博查 / Tavily / 百度千帆都行，
> 每天 3~4 次调用，成本可以忽略），并补上 `discover_events.py`。
> `CoreAssets/Prompts.md` 里的 `discover` 提示词已经写好了，缺的只是「谁来搜」这一层。
>
> 不接 API 也能自动化，但会退化成 B：只会搜「今天有人发新歌」的主体，
> 韩娱、活动型热点基本抓不到。

**没有计划文件时，采集会直接报错退出（`exit=8`）**，不会自己瞎搜——
早期版本会退回「按日期轮转主体」，花 40 分钟搜一堆当天没活动的人，产出一份看着正常的空日报。

---

## 它长什么样

```
## 今日文案（10 条）

**采集（3 条）**

1. 你被逮捕了！
   - 在用：4 条｜最高 354,000 赞｜圈内 1/4

2. 羽毛落下的那刻，喧嚣都自动静音。
   - 在用：1 条｜最高 532,000 赞｜跨圈

**热榜（6 条）**

1. 这个日常妆值得焊在脸上
2. 此刻舞台上的我光芒万丈
3. 时间流逝比子弹快

## 今日玩法（4 条｜抖音热榜）

1. 七天七色变装挑战
2. 用BIGBANG新歌打开AllBlack穿搭
```

两组的区别：

- **采集**：从搜回来的视频里抽出来的句子，带「多少条内容在用」的证据
- **热榜**：抖音热榜当天挑出的句子，只有平台热度，没有使用量

「在用」写的是**多少条不同视频用过这句话**，不是热度值——热度高不代表能拿来剪。

---

## 它怎么运行

```
① Agent 侦察（对话里完成）
   联网搜近期活动 → 映射到词库 109 个主体 → 写 data/input/query_plan.json
   产出：主体 12 / 歌名 12 / 玩法 4 / 热种 6（共 20~34 条，随当天信号浮动）
        ↓
② 采集（脚本，CDP 连本机 Edge）
   按计划逐条搜，每条带自己的时间窗：歌名 5 天 / 主体 7 天 / 玩法 5 天
        ↓
③ 判定
   抽实体（歌名 / 模板骨架 / XX挑战）→ 同一素材合并成卡
   门槛：圈内 ≥2 条在用，跨圈 ≥3 条；领域过滤（体育/电竞/时政）
   跨天治理：连续 3 天热度不涨就「让位给新素材」
        ↓
④ 出报
   素材卡 8 张 + 跨圈 3 张 → 今日文案 → 今日玩法 → 今日新歌 → 候选池
```

判据在 [`CoreAssets/HotspotCriteria.md`](CoreAssets/HotspotCriteria.md)，
提示词在 [`CoreAssets/Prompts.md`](CoreAssets/Prompts.md)——两者都是唯一来源，代码里的阈值以它们为准。

---

## 快速开始

### 第 0 步：拿到代码

两种方式，选一种。

**① 下载压缩包**（不想装 git 就选这个）

打开 [Releases](https://github.com/YyizzLL/Trend-Radar/releases/latest)，在 **Assets** 里点 **Source code (zip)**，解压后进入目录。

> 压缩包就是源码（约 0.6 MB），只有代码、文档和示例配置：
> **不含**密钥、采集数据、浏览器登录态、运行日志。
>
> 第一次打开时看不到 `.env` / `data/` 里的真实内容——它们都在本机运行时才生成。

**② 用 git**

```bash
git clone https://github.com/YyizzLL/Trend-Radar.git && cd Trend-Radar
```

下面所有命令都在**项目根目录**执行（含 `requirements.txt` 的那一层）。

### 第 1 步：装依赖 + 登录抖音

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # 填 RADAR_LLM_KEY（模型层要用）
python scripts/doctor.py      # 自检：依赖 / 时区 / 密钥 / 端口 / 词库
python scripts/launch_edge.py # 启动 Edge，在窗口里扫码登录抖音
```

### 第 2 步：路线 A —— 对话 Agent（推荐）

在对话里让 Agent 做侦察，它会写出 `data/input/query_plan.json`，然后：

```bash
python scripts/collect_douyin.py              # 采集（自动读 query_plan.json）
python -m src.main --run                      # 判定 + 出日报
# 或一步到位：
python scripts/daily_run.py --trigger manual --skip-plan
```

产物在 `sandbox/runs/<时间戳>/report.md`。

### 第 2 步（备选）：路线 B —— 纯脚本

```bash
python scripts/plan_queries.py     # 只用热榜/榜单/热种生成计划
python scripts/collect_douyin.py   # 采集
python -m src.main --run           # 判定 + 出日报
```

不接任何搜索 API，代价是覆盖面窄——见开头那张表。

### 第 3 步（可选）：定时跑

```bash
python scripts/install_task.py     # 09:00 主跑 + 登录后 2 分钟 + 11:30 失败重试
```

计划任务走的是路线 B。**要在无人值守下拿到 A 的效果，必须先接搜索 API。**

> **不需要** `playwright install`。这里用 `connect_over_cdp` 连已有浏览器，不下载浏览器二进制。

---

## 前置条件


**这不是 clone 下来就能跑的工具。** 外部服务要自己申请。

### 一、必须人工完成的

| 项 | 说明 |
|---|---|
| **Windows + Edge** | 采集靠 CDP 连本机 Edge，只在 Windows 上验证过 |
| **抖音账号** | 需要在 Edge 里**人工扫码登录**一次。登录态存在 `.edge-cdp/`，不会上传 |
| **Edge 调试端口** | `python scripts/launch_edge.py` 会自动用 9222 端口启动 |

登录态会过期。搜索页能打开但没有结果，大概率是被手机端顶掉了，重新扫码即可。

### 二、需要自己申请的 API

| 环境变量 | 用途 | 从哪拿 | 免费额度 | 不填会怎样 |
|---|---|---|---|---|
| `RADAR_LLM_KEY` | 模型层：素材理解 + 文案成品化 | 任意 OpenAI 兼容服务（DeepSeek / 通义 / 硅基流动…） | 各家不同，本项目实测约 ¥0.2/天 | 降级成纯规则版：素材卡少几张，没有文案栏 |
| `SANDBASE_API_KEY` | 读视频真实配乐 | https://api.sandbase.ai | 100 次/天 | 素材卡没有「配乐」字段 |
| `SMTP_USER` / `SMTP_PASS` / `SMTP_TO` | 发邮件 | QQ 邮箱（`SMTP_PASS` 填**授权码**，不是密码） | 免费 | 只出 Markdown，不发邮件 |
| （可选）`SEARCH_API_KEY` | **只有要做全自动才需要**：让脚本自己搜活动 | 博查 / Tavily / 百度千帆 | 博查 1000 次、Tavily 1000 次/月、千帆 100 次/天 | 走路线 B，覆盖面变窄 |

**`SMTP_PASS` 填 QQ 密码会报 `535 Authentication failed`**，必须填授权码。

### 三、目录约定

| 路径 | 要不要自己建 | 说明 |
|---|---|---|
| `.env` | 是 | 从 `.env.example` 复制 |
| `CoreAssets/keywords.json` | 否 | **已随仓库提供**（109 个主体 / 42 个团体有成员表）；按 [模板](CoreAssets/keywords.template.md) 增删 |
| `data/` 下的子目录 | 否 | 运行时自动创建 |
| `.edge-cdp/` | 否 | 首次 `launch_edge.py` 自动生成，扫码后写入登录态 |

词库是地基。`主体` 为空会导致计划为空、采集 0 条、日报全空。

---

## 目录结构

```
Trend-Radar/
├── CoreAssets/          判定准则、提示词、词库（都是唯一来源）
│   ├── AgentRole.md     角色、读取顺序、工作路径
│   ├── InputOutput.md   数据契约：输入字段用途、输出格式
│   ├── HotspotCriteria.md  判定准则（冲突时以它为准）
│   ├── Prompts.md       全部 LLM 提示词（六个环节，改这里不改代码）
│   ├── Ops.md           运维手册：跑批、排障、模型层配置
│   ├── keywords.template.md  词库结构与填法
│   └── keywords.json    随仓库提供（109 个主体），可自行增删
│
├── config/sources.yaml  数据源、门槛、投递、模型层开关
├── src/
│   ├── main.py          命令行入口（--run / --prune / --clean）
│   ├── constants.py     共用常量 + 采集退出码（EXIT_*，唯一定义处）
│   ├── collectors/      抖音 / B站 / QQ音乐 / 热榜 / BGM 采样
│   ├── normalize/       归一、实体抽取、聚合、文案候选
│   ├── judge/           判定（领域过滤、门槛、配额、跨天治理）
│   ├── llm/             模型层：素材理解 + 文案成品化（提示词从 Prompts.md 读）
│   ├── report/          Markdown 日报渲染
│   └── deliver/         邮件构建、发送、归档
│
├── scripts/
│   ├── daily_run.py     每日总入口（锁 → Edge → 计划 → 采集 → 出报 → 发信）
│   ├── doctor.py        环境自检，出问题先跑它
│   ├── launch_edge.py   启动带调试端口的 Edge（扫码登录在这里做）
│   ├── install_task.py  注册 Windows 计划任务
│   ├── collect_douyin.py  采集（CDP 驱动，--resume 续采；没计划直接报错）
│   ├── plan_queries.py  纯脚本路线：按当日信号生成计划
│   ├── collect_seeds.py 抓聚合榜，给侦察提供一路输入（可选）
│   ├── check_prompts.py 校验 Prompts.md（层齐全 / 占位符可填）
│   ├── build_keywords.py  重建词库
│   ├── llm_replay.py    离线回放模型层
│   └── probe/           开发期探索工具，非运行必需
│
├── memory/              每日复盘与优化分析（本地，不入库）
├── data/                运行时数据（内容不入库，只留目录骨架）
└── fixtures/            脱敏样例，用于离线试跑
```

---

## 模型层（可选）

默认开两层，提示词都在 [`CoreAssets/Prompts.md`](CoreAssets/Prompts.md)：

| 层 | 做什么 | 开关 |
|---|---|---|
| 素材理解 `material` | 整批读一个查询下的 40 条文案，补出规则抽不到的歌名/玩法名 | `layers.material.enabled` |
| 文案成品化 `phrase` | 把复用句 / 高赞句 / 热榜句补齐成能直接用的句子，补不出来的丢掉 | `layers.phrase.enabled` |

模型层只做「补抽」和「成品化」，**不做判定**：产出的素材照样走同一套门槛和配额。
任何一层失败都静默降级，不影响日报发出。

关掉全部模型层也能跑，就是纯规则版——素材卡少几张，没有文案栏。

改提示词：编辑 `CoreAssets/Prompts.md` → 跑 `python scripts/check_prompts.py` → 完成，不用碰 Python。

---

## 已知限制

- **侦察依赖对话 Agent**。不定时开对话，就没有新计划；计划任务会跑路线 B（覆盖窄）。
- **没有搜索 API 就没有真正的无人值守**。要补的话见开头那张表。
- **只在 Windows + Edge 上验证过**，没做无头浏览器和其他系统适配。
- **采集覆盖率不是 100%**。抖音有软拦截，一个窗口能连续采 3~9 个查询，停一会儿再 `--resume`。
- **可能触发人机验证**。脚本会识别并自动重启 Edge 换会话（默认 2 次），仍被拦才告警。
- **抖音网页版不暴露 BGM 字段**，真实配乐靠 SandBase 二次查询，受每日额度限制。
- **评论完全没采**，评论区的梗是盲区。
- **改写过的文案，「在用 N 条」只对原句成立**——那个数字是热度参考，不是证据链。
- 词库需要自己维护。主体名单、别名映射会随时间失效。

---

## 版本

当前 **v0.5.0**（2026-11-25）。变更历史见 [`CHANGELOG.md`](CHANGELOG.md)；
每日复盘在本地 `memory/` 目录（不入库）。

---

## 免责声明

本项目仅用于个人学习与技术研究。

- 采集行为请遵守目标网站的 `robots.txt` 与服务条款，控制频率，不要用于批量抓取。
- 抓取内容的版权归原作者所有，本项目只做结构化整理，不存储音视频。
- 使用本项目产生的任何后果由使用者自行承担。

---

## 许可

[MIT](LICENSE) —— 可自由使用、修改、分发，包括商业用途。

唯一要求：保留版权声明与许可声明原文。
