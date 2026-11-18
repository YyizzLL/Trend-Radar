# Trend-Radar

A daily radar that answers one question for fan-edit creators:
**what can I actually use in a video today?**

It scans Douyin (Chinese TikTok) every morning and returns three kinds of reusable assets:

- **BGM** — songs that are being used right now, not just chart positions
- **Captions** — lines copied across many videos that still work out of context
- **Formats** — dance challenges with an entry point, templates you can re-shoot

Runs at 09:00 daily and delivers a Markdown digest by email.

> Docs in `CoreAssets/` are written in Chinese. The code, config keys and this README are the
> English entry point.

---

## What the output looks like

```
## In-circle material (fan-edit vertical) (8)

| # | Item | Type | Subject | Evidence |
|---|------|------|---------|----------|
| 1 | I'll Arrest You dance challenge | Challenge | ILLIT | 28 videos using it, day 5 (rising) |
| 2 | Guandé Highway's End | BGM | Wang Yuan | New Song Chart #4; mentioned in 20 videos |
| 3 | CallMyName challenge | Challenge | NAME | 19 videos using it |

## Usable captions today (3)

| Caption | In use | How to use | Source |
|---------|--------|------------|--------|
| Draw a prison for myself | 3 | Slow montage of staying loyal to one idol | "Later Friends" |
```

"Evidence" means **how many videos use it**, not a popularity score —
high heat does not mean it is usable in an edit.

---

## How it decides

The unit of judgement is the **material**, not the video and not the news event.

```
[Seed]  ~100 trending topics -> LLM filters "can this become material?" -> query terms
   |
Collect ~400-1900 pieces of content
   |  extract entities (song names / template skeletons / "XX challenge")
   |  merge mentions of the same material into one card
   |  threshold: >=2 videos in-circle, >=3 cross-circle
   |  domain filter: sports / esports / politics out
   |  lifespan: a card older than N days steps aside for something new
Digest: 8 in-circle + 3 cross-circle cards
```

Full criteria live in [`CoreAssets/HotspotCriteria.md`](CoreAssets/HotspotCriteria.md) —
it is the single source of truth; every threshold in code follows it.

---

## Quick start

```bash
git clone https://github.com/YyizzLL/Trend-Radar.git && cd Trend-Radar

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then fill in keys, see below
# Build CoreAssets/keywords.json from CoreAssets/keywords.template.md
# (it is NOT in the repo - without it the plan is empty and nothing is collected)

python scripts/doctor.py      # deps / timezone / keys / port / keywords / data
python scripts/launch_edge.py # starts Edge; scan the QR code to log into Douyin
python scripts/collect_douyin.py   # collect (try --limit 3 first)
python -m src.main --run           # judge + render the digest
```

Output lands in `sandbox/runs/<timestamp>/report.md`.

To run it daily, register the Windows scheduled task
(09:00 main run + 2 min after logon + 11:30 retry on failure):

```bash
python scripts/install_task.py        # --query to inspect / --remove / --run-now
```

> `playwright install` is **not** needed. The collector uses `connect_over_cdp`
> against an existing browser and never downloads browser binaries.

---

## Prerequisites

**This is not a clone-and-run tool.** Every external service is bring-your-own.

### 1. Manual steps (nothing works without them)

| Item | Notes |
|------|-------|
| **Windows + Edge** | Collection uses CDP against a local Edge. Only verified on Windows |
| **Douyin account** | You must scan the QR code **once** in the Edge window. Session is stored in `.edge-cdp/` and never uploaded |
| **Edge debug port** | `python scripts/launch_edge.py` starts Edge with `--remote-debugging-port=9222` |

Sessions expire. If the search page opens but returns nothing, you were probably
logged out by the mobile app — scan again.

### 2. Bring your own API keys

| Env var | Purpose | Where | Free tier | If missing |
|---------|---------|-------|-----------|------------|
| `RADAR_LLM_KEY` | LLM layer: material understanding + caption review | Any OpenAI-compatible API (DeepSeek / OpenAI / SiliconFlow…) | varies; ~¥0.2/day in our runs | Falls back to rules-only: fewer cards, no caption column |
| `SANDBASE_API_KEY` | Real BGM behind a video | https://api.sandbase.ai | 100/day, $0.001/call | No "soundtrack" field on cards |
| `SMTP_USER` | Sender mailbox | QQ Mail | free | Markdown only, no email |
| `SMTP_PASS` | **App password** (16 chars, not your login password) | QQ Mail → Settings → enable POP3/IMAP/SMTP | free | same as above |
| `SMTP_TO` | Recipient | your choice | — | defaults to `SMTP_USER` |

Using your QQ login password in `SMTP_PASS` fails with `535 Authentication failed`.

### 3. Directory conventions

| Path | Create it? | Notes |
|------|-----------|-------|
| `.env` | yes | copy from `.env.example` |
| `CoreAssets/keywords.json` | **yes** | not in the repo; follow the template |
| `data/*` | no | created at runtime |
| `.edge-cdp/` | no | created on first `launch_edge.py` |

The keyword file is the foundation. An empty `subjects` list means an empty plan,
zero content collected and an empty digest. `python scripts/plan_queries.py`
is the fastest way to check it.

---

## Repository layout

```
Trend-Radar/
├── CoreAssets/          criteria + keyword schema (Chinese docs)
│   ├── AgentRole.md     role, reading order, paths
│   ├── InputOutput.md   data contract
│   ├── HotspotCriteria.md   the criteria (wins any conflict)
│   ├── Ops.md           runbook: daily run, troubleshooting, LLM config
│   └── keywords.template.md
│
├── config/sources.yaml  sources, thresholds, delivery, LLM switches
├── src/
│   ├── main.py          CLI entry (--run / --prune / --clean)
│   ├── constants.py     shared constants + collector exit codes (EXIT_*)
│   ├── deps.py          dependency manifest (shared by preflight and doctor)
│   ├── collectors/      Douyin / Bilibili / QQ Music / BGM sampling
│   ├── normalize/       normalisation, entity extraction, aggregation
│   ├── judge/           filtering, thresholds, quotas, reuse governance
│   ├── llm/             optional LLM layer
│   ├── report/          Markdown rendering + text merge
│   └── deliver/         email build & send
│
├── scripts/
│   ├── daily_run.py     scheduler (lock -> Edge -> plan -> collect -> report -> mail)
│   ├── doctor.py        environment self-check
│   ├── launch_edge.py   start Edge with a debug port
│   ├── install_task.py  register the Windows scheduled task
│   ├── collect_douyin.py  CDP collector (supports --resume)
│   ├── collect_seeds.py   trending seeds (optional, non-blocking)
│   ├── plan_queries.py    build the daily query plan
│   ├── build_keywords.py  rebuild subject list and profiles
│   └── probe/           development probes, not required at runtime
│
├── data/                runtime data (gitignored, skeleton committed)
└── fixtures/            sanitised samples for offline runs
```

---

## LLM layer (optional)

Two layers are on by default: **material understanding** and **caption review**.

| Layer | What it does | Switch |
|-------|--------------|--------|
| L2 | Reads ~40 captions per query and recovers song/format names rules miss | `layers.material.enabled` |
| Caption review | Decides whether a reused phrase works as a caption, and how | `layers.phrase.enabled` |
| L3 noise review | Flags "high evidence but filtered as noise" cases (rarely fires) | `layers.adjudicate.enabled` |
| L1 query generation | LLM-suggested queries | not wired into the pipeline |

The LLM only **extracts** and **reviews**; it never decides. Every card still goes through
the same thresholds and quotas. Any layer failing degrades silently.

Turn everything off and the project still runs as a rules-only radar.

---

## Known limitations

- **Only verified on Windows + Edge.** No headless or cross-platform support.
- **Collection coverage is typically 70–98%**, never 100%. Douyin soft-blocks after
  a few queries; the collector pauses and resumes (`--resume`).
- **CAPTCHAs happen.** The collector detects them, restarts Edge with a fresh session
  (up to 2 attempts), and only then stops and alerts.
- **The web UI does not expose BGM**; real soundtracks come from SandBase, capped daily.
- **Comments are not collected at all** — comment-section memes are a blind spot.
- **Cross-circle discovery covers challenges/templates only**, not cross-circle BGM or captions.
- **You maintain the keyword file.** Subject lists and aliases go stale.
- **Formats have a shelf life.** Cards older than the configured lifespan step aside,
  which is intentional — a radar that repeats itself is not a radar.

---

## Disclaimer

For personal study and technical research only.

- Respect the target site's `robots.txt` and terms of service; keep request rates low.
- Copyright of collected content belongs to its authors. This project only structures
  metadata and stores no audio or video.
- Use at your own risk.

---

## License

[MIT](LICENSE). Keep the copyright and licence notice.
