# Trend-Radar

> 中文版：[`README.md`](README.md) ｜ Version: **v0.5.0**

A daily radar that answers one question for fan-edit creators:
**what can I actually use in a video today?**

It scans Douyin (Chinese TikTok) and returns three kinds of reusable assets:

- **BGM** — songs being used right now, not just chart positions
- **Captions** — a line you can paste as a title or subtitle, with "how many videos use it" as evidence
- **Formats** — challenges with an entry point, templates you can re-shoot

The output is a Markdown digest, optionally delivered by email.

> Docs in `CoreAssets/` are written in Chinese. The code, config keys and this README are the
> English entry point.

---

## ⚠️ Read this first: this version runs through a conversational agent

**It is not a "install and it runs itself every morning" tool.**

There is exactly one reason: **deciding who to search for requires looking up "what is happening
this week" on the web** — award-show lineups, music-variety guest lists. Those are not in the
Douyin charts and not in any fixed RSS feed. That step is done by an agent in a conversation
(web search → map to the keyword library → write the plan file). The project itself only
**executes the plan**: collect → judge → render.

Three ways to run it:

| Mode | Who decides what to search | Needs a human | Coverage |
|---|---|---|---|
| **A. Conversational agent (default)** | Agent searches the web → writes `data/input/query_plan.json` | One conversation per day | Widest; finds event lineups |
| **B. Scripts only** | `scripts/plan_queries.py` uses hot list / charts / seeds | No | Narrow: only "someone released a song today" |
| **C. Scripts + search API** | `scripts/discover_events.py` calls a search API (**not implemented yet**) | No | Close to A; needs one API key |

> **If your goal is unattended automation**, wire in a search API (Bocha / Tavily / Baidu Qianfan —
> 3~4 calls a day, cost is negligible) and add `discover_events.py`.
> The `discover` prompt already exists in `CoreAssets/Prompts.md`; only the "who searches" layer is missing.
>
> Automation without an API is possible, but degrades to B: it will only search subjects who
> released something today. K-pop and event-driven spikes are essentially missed.

**With no plan file, collection fails loudly (`exit=8`)** instead of guessing.
Earlier versions silently fell back to "rotate subjects by day of year", burned 40 minutes on
people with no activity, and produced a digest that looked fine but was empty.

---

## What the output looks like

```
## Today's captions (10)

**Collected (3)**

1. You're under arrest!
   - In use: 4 videos | top 354,000 likes | in-circle 1/4

2. The moment the feather falls, all the noise goes quiet.
   - In use: 1 video | top 532,000 likes | cross-circle

**Hot list (6)**

1. This everyday makeup deserves to be welded onto my face
2. The me on stage right now shines
3. Time passes faster than bullets

## Today's formats (4 | Douyin hot list)

1. Seven days seven colors outfit-change challenge
2. All-black outfit switch, opened with BIGBANG's new song
```

The two groups differ:

- **Collected** — lines pulled from videos we found, with "how many videos use it" as evidence
- **Hot list** — lines picked from today's Douyin hot list; platform ranking, no usage count

"In use" means **how many distinct videos used that line**, not a popularity score.

---

## How it runs

```
1. Agent reconnaissance (in the conversation)
   Web search -> map to 109 subjects in the keyword library -> write query_plan.json
   Yields: 12 subjects / 12 songs / 4 formats / 6 seeds (20~34 queries, varies by day)
        |
2. Collection (script, CDP to local Edge)
   One search per query, each with its own time window: songs 5d / subjects 7d / formats 5d
        |
3. Judging
   Extract entities -> merge mentions of the same material into one card
   Threshold: >=2 in-circle videos, >=3 cross-circle; domain filter (sports/esports/politics out)
   Lifespan: a card whose heat has not grown for 3 days steps aside
        |
4. Render
   8 in-circle cards + 3 cross-circle -> captions -> formats -> new songs -> candidates
```

Criteria live in [`CoreAssets/HotspotCriteria.md`](CoreAssets/HotspotCriteria.md) and prompts in
[`CoreAssets/Prompts.md`](CoreAssets/Prompts.md) — both are single sources of truth; every
threshold in code follows them.

---

## Quick start

### Step 0: get the code

Two options, pick one.

**① Download the archive** (no git required)

Open [Releases](https://github.com/YyizzLL/Trend-Radar/releases/latest) and click **Source code (zip)** under **Assets**, then unpack it.

> The archive is the source tree (~0.6 MB): code, docs and sample config only.
> It contains **no** API keys, no collected data, no browser session, no logs.
>
> You will not find `.env` or real files under `data/` — those are created locally on first run.

**② Use git**

```bash
git clone https://github.com/YyizzLL/Trend-Radar.git && cd Trend-Radar
```

All commands below run from the **project root** (the folder containing `requirements.txt`).

### Step 1: install deps and log in to Douyin

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # fill RADAR_LLM_KEY
python scripts/doctor.py      # deps / timezone / keys / port / keyword library
python scripts/launch_edge.py # starts Edge; scan the QR code to log into Douyin
```

### Step 2: route A — conversational agent (recommended)

Have the agent do reconnaissance in a conversation; it writes `data/input/query_plan.json`, then:

```bash
python scripts/collect_douyin.py              # collect (reads query_plan.json)
python -m src.main --run                      # judge + render
# or in one shot:
python scripts/daily_run.py --trigger manual --skip-plan
```

Output lands in `sandbox/runs/<timestamp>/report.md`.

### Step 2 (alternative): route B — scripts only

```bash
python scripts/plan_queries.py     # plan from hot list / charts / seeds only
python scripts/collect_douyin.py   # collect
python -m src.main --run           # judge + render
```

No search API needed; coverage is narrower, as described above.

### Step 3 (optional): scheduled runs

```bash
python scripts/install_task.py     # 09:00 main run + 2 min after login + 11:30 retry
```

The scheduled task uses route B. **To get route-A quality unattended, wire in a search API first.**

> `playwright install` is **not** required. This uses `connect_over_cdp` against an existing
> browser and does not download browser binaries.

---

## Prerequisites


**This is not a clone-and-run tool.** External services must be provisioned by you.

### 1. Manual steps

| Item | Note |
|---|---|
| **Windows + Edge** | Collection uses CDP against local Edge; only verified on Windows |
| **Douyin account** | Log in once by scanning a QR code in the Edge window. Session is stored in `.edge-cdp/` and never uploaded |
| **Edge debug port** | `python scripts/launch_edge.py` starts Edge on port 9222 |

The session expires. If the search page opens but returns nothing, you were probably kicked off
by the mobile app — scan again.

### 2. API keys you must obtain

| Env var | Purpose | Where | Free tier | If missing |
|---|---|---|---|---|
| `RADAR_LLM_KEY` | Model layer: material extraction + caption finishing | Any OpenAI-compatible service (DeepSeek / Qwen / SiliconFlow…) | Varies; ~¥0.2/day measured here | Degrades to rules-only: fewer cards, no caption section |
| `SANDBASE_API_KEY` | Read the real BGM of a video | https://api.sandbase.ai | 100 calls/day | Cards lose the "BGM" field |
| `SMTP_USER` / `SMTP_PASS` / `SMTP_TO` | Email delivery | QQ Mail (`SMTP_PASS` is an **app password**, not your login password) | Free | Markdown only, no email |
| (optional) `SEARCH_API_KEY` | **Only needed for full automation**: let scripts search the web | Bocha / Tavily / Baidu Qianfan | Bocha 1000 calls, Tavily 1000/month, Qianfan 100/day | Route B, narrower coverage |

### 3. Directory conventions

| Path | Create manually? | Note |
|---|---|---|
| `.env` | Yes | Copy from `.env.example` |
| `CoreAssets/keywords.json` | No | **Ships with the repo** (109 subjects / 42 groups with member lists); edit per the [template](CoreAssets/keywords.template.md) |
| `data/` subdirectories | No | Created at runtime |
| `.edge-cdp/` | No | Created by `launch_edge.py`; session written after login |

The keyword library is the foundation. An empty subject list means an empty plan, zero collected
items, and an empty digest.

---

## Repository layout

```
Trend-Radar/
├── CoreAssets/          criteria, prompts, keyword library (single sources of truth)
│   ├── AgentRole.md     role, read order, work path
│   ├── InputOutput.md   data contract: input fields, output format
│   ├── HotspotCriteria.md  judging criteria (wins on conflict)
│   ├── Prompts.md       every LLM prompt (6 stages; edit here, not in code)
│   ├── Ops.md           operations manual: runs, troubleshooting, model layers
│   ├── keywords.template.md  keyword structure and how to fill it
│   └── keywords.json    ships with the repo (109 subjects)
│
├── config/sources.yaml  data sources, thresholds, delivery, model switches
├── src/
│   ├── main.py          CLI entry (--run / --prune / --clean)
│   ├── constants.py     shared constants + exit codes (EXIT_*, single definition)
│   ├── collectors/      Douyin / Bilibili / QQ Music / hot list / BGM sampling
│   ├── normalize/       normalization, entity extraction, aggregation, caption candidates
│   ├── judge/           judging (domain filter, thresholds, quotas, lifespan)
│   ├── llm/             model layer: material understanding + caption finishing
│   ├── report/          Markdown digest rendering
│   └── deliver/         email build, send, archive
│
├── scripts/
│   ├── daily_run.py     daily entry (lock → Edge → plan → collect → render → send)
│   ├── doctor.py        environment self-check; run this first when something breaks
│   ├── launch_edge.py   start Edge with a debug port (QR login happens here)
│   ├── install_task.py  register a Windows scheduled task
│   ├── collect_douyin.py  collection (CDP, --resume; fails loudly without a plan)
│   ├── plan_queries.py  route B: build a plan from day signals
│   ├── collect_seeds.py trending aggregator, one more input for reconnaissance (optional)
│   ├── check_prompts.py validate Prompts.md (all stages present, placeholders fillable)
│   ├── build_keywords.py  rebuild the keyword library
│   ├── llm_replay.py    offline replay of the model layer
│   └── probe/           development probes, not needed to run
│
├── memory/              daily retrospectives and optimization notes (local, not committed)
├── data/                runtime data (not committed, skeleton only)
└── fixtures/            sanitized samples for offline dry runs
```

---

## Model layer (optional)

Two layers are on by default; prompts live in [`CoreAssets/Prompts.md`](CoreAssets/Prompts.md):

| Layer | What it does | Switch |
|---|---|---|
| `material` | Reads ~40 captions per query and recovers song/format names rules miss | `layers.material.enabled` |
| `phrase` | Finishes candidate lines into ready-to-use captions, or drops them | `layers.phrase.enabled` |

The model only **extracts** and **finishes**; it never decides. Every card still goes through the
same thresholds and quotas. Any layer failing degrades silently.

Turn everything off and it still runs as a rules-only radar — fewer cards, no caption section.

To change a prompt: edit `CoreAssets/Prompts.md` → run `python scripts/check_prompts.py` → done,
no Python changes.

---

## Known limitations

- **Reconnaissance depends on a conversational agent.** No conversation, no new plan; the
  scheduled task falls back to route B (narrow coverage).
- **No search API means no true unattended operation.**
- **Only verified on Windows + Edge**; no headless or cross-platform support.
- **Collection coverage is not 100%.** Douyin soft-blocks after 3~9 queries per window; wait and
  `--resume`.
- **Captchas happen.** The script detects them and restarts Edge for a new session (2 attempts).
- **Douyin's web page does not expose BGM**; real tracks come from a second SandBase query.
- **Comments are not collected at all.**
- **For rewritten captions, "in use N" only applies to the original line** — it is a heat signal,
  not a chain of evidence.
- The keyword library needs maintenance; names and aliases go stale.

---

## Version

Current: **v0.5.0** (2026-11-25). See [`CHANGELOG.md`](CHANGELOG.md) for history.
Daily retrospectives live in the local `memory/` folder (not committed).

---

## Disclaimer

For personal study and technical research only.

- Respect `robots.txt` and the terms of service of any site you collect from; keep request rates low.
- Copyright of collected content belongs to its authors; this project only structures text and
  stores no audio or video.
- You are responsible for any consequences of using this project.

---

## License

[MIT](LICENSE) — free to use, modify and distribute, including commercially.

The only requirement: keep the copyright and license notice.
