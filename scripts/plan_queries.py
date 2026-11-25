"""生成当日检索计划：只搜「今天有信号」的主体，不做轮转。

2026-11-23 重构。三条原则：

1. **主体只看信号，不看轮转**
   热榜 / 榜单歌手 / 聚合榜热种 三源交叉，命中谁就搜谁。
   没信号的主体当天不搜——热点只活几天，十天轮一次等于没有。
   代价是冷门主体不会主动被搜，这是明确接受的取舍。

2. **玩法不做「形式词 + 舞台」式拼接**
   转场/卡点/换装是强标签（创作者靠它被搜到），可以跟主体拼；
   「舞台」是弱标签（文案常只有「啊啊啊」），加了限定词只会漏内容。
   所以主体查询一律裸名，只有玩法才拼形式词。

3. **时间窗按类下发**
   歌名 5 天 / 主体 7 天 / 玩法 5 天。目的是「知道它存在」，
   不是反复看见同一个东西。

删掉的东西：「发现」类——它的词源是历史记录，等于把过去搜过的再搜一遍。

用法：python scripts/plan_queries.py [--out 路径] [--seeds 路径]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

from src.collectors import douyin_hot  # noqa: E402
from src.collectors.http import Fetcher  # noqa: E402
from src.collectors.qq_music import fetch as fetch_chart  # noqa: E402
from src.config import (  # noqa: E402
    alias_map,
    keyword_layer,
    load_keywords,
    load_sources,
    subject_profiles,
)
from src.judge.anchor import context as anchor_context  # noqa: E402
from src.judge.anchor import match_subject  # noqa: E402
from src.judge.material import is_activity_container  # noqa: E402

OUT = ROOT / "data" / "input" / "query_plan.json"
# 验证时用 --seeds 指向 sandbox 的种子文件，不碰 data/input 的真实数据
SEEDS_PATH: Path | None = None

# 剪辑型玩法的形式词。创作者会主动打这些标签（靠它被搜到、被套用），
# 所以可以跟主体拼；「舞台/直拍」不在其中——那是弱标签，拼了会漏。
TEMPLATE_WORDS = ("转场", "卡点", "换装", "变装", "剪同款", "模板")

# 各类型的采集时间窗（天）。见文件头第 3 条。
DAYS = {"歌名": 5, "主体": 7, "玩法": 5}


def _fetch_signals() -> dict:
    """一次性抓三类外部信号，供后续所有查询生成复用。

    三个源在「生成计划」阶段本来就可用，以前各函数各抓一次，等于白跑两遍请求：
    - qq_music 榜单：原 `_chart_queries` 自己抓
    - 抖音热榜：原 `_hot_challenges` 自己抓
    - 聚合榜热种：`collect_seeds` 已写盘

    任一源失败都只返回空，不中断计划生成。
    """
    src = load_sources().get("sources", {})
    sig: dict = {"songs": [], "hot": [], "seed_titles": [], "seed_queries": []}

    qcfg = src.get("qq_music", {})
    try:
        sig["songs"] = fetch_chart(
            [str(c) for c in (qcfg.get("charts") or ["27"])],
            max_rank=int(qcfg.get("max_rank", 30)),
            qps_ms=int(qcfg.get("qps_ms", 800)),
        )["songs"]
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 榜单读取失败：{exc}")

    hcfg = src.get("douyin_hot", {})
    if hcfg.get("enabled"):
        fetcher = Fetcher("Mozilla/5.0")
        try:
            items, _ = douyin_hot.collect(
                fetcher, hcfg, datetime.now().isoformat(timespec="seconds")
            )
            sig["hot"] = items
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 热榜读取失败：{exc}")
        finally:
            fetcher.close()

    path = SEEDS_PATH or (ROOT / "data" / "input" / "hot_seeds.json")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            gen = str(data.get("generated_at") or "")[:10]
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            # 过期保护：只认今天或昨天的种子；拿不到就当没有
            if not gen or gen in {today, yesterday}:
                sig["seed_titles"] = [
                    str(k.get("title") or "") for k in (data.get("kept") or [])
                ]
                sig["seed_queries"] = data.get("queries") or []
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 热种读取失败：{exc}")
    return sig


def _group_names(kw: dict) -> set[str]:
    """团体名单：有成员表的都算团体，没有成员表的新团用画像 type 兜底。

    「玩法」只跟团体拼（`TWS 转场`），不跟个人歌手拼——`孙燕姿 转场`
    这类查询搜回来基本是空的，白占配额。
    """
    node = kw.get("锚点层") or {}
    raw = node.get("成员归属") if isinstance(node, dict) else {}
    # `keyword_layer` 只处理 list，成员归属是 dict，这里直接取
    names = set(raw.keys()) if isinstance(raw, dict) else set()
    for subject, info in subject_profiles(kw).items():
        if info.get("type") == "团体":
            names.add(subject)
    return names


def _hot_subjects(
    sig: dict, kw: dict, *, limit: int = 12
) -> list[tuple[str, int, str]]:
    """今天有热度信号的主体，按强度降序。返回 [(主体, 分值, 命中理由)]。

    权重：热榜命中 2 / 新歌·飙升榜歌手命中 2 / 热种标题命中 1。
    同一主体被多个源命中会累加——这是「今天确实有动静」的最强证据。

    **热歌榜不计信号**：它是常青榜，一首老歌能挂几个月，
    拿它当「今天有热点」会让孙燕姿、薛之谦这类常年霸榜的歌手
    每天占满主体配额，而真正有舞台的团体挤不进来。
    """
    subjects = keyword_layer(kw, "锚点层", "主体")
    amap = alias_map(kw)
    ctx = anchor_context(kw, load_sources().get("judge", {}) or {})
    signal_charts = {
        str(c) for c in (load_sources().get("sources", {})
                         .get("qq_music", {})
                         .get("signal_charts") or ["27", "62"])
    }
    score: Counter[str] = Counter()
    why: dict[str, list[str]] = defaultdict(list)

    def _hit(text: str) -> str:
        return match_subject(text or "", subjects, amap, **ctx)

    for cand in sig.get("hot") or []:
        s = _hit(str(cand.term or ""))
        if s:
            score[s] += 2
            why[s].append(f"热榜#{cand.rank or '-'}")

    for song in sig.get("songs") or []:
        if str(song.get("chart") or "") not in signal_charts:
            continue                  # 热歌榜不算「今天有动静」
        s = _hit("、".join(song.get("artists") or []))
        if s:
            score[s] += 2
            why[s].append(f"{song.get('chart', '')}#{song.get('rank', '')}")

    for title in sig.get("seed_titles") or []:
        s = _hit(title)
        if s:
            score[s] += 1
            why[s].append("热种")

    rows = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        (name, sc, "、".join(dict.fromkeys(why[name]))[:48])
        for name, sc in rows[:limit]
    ]


def _chart_queries(
    sig: dict, kw: dict, limit: int, *, days: int = DAYS["歌名"]
) -> list[dict]:
    """榜单歌名。词库只负责排序，不再一票否决。

    以前歌手不在词库就直接丢。词库收窄到唱跳之后，周杰伦发新歌也会被漏掉——
    榜单能看见这首歌，代码却因为「查无此人」跳过。
    现在：词库内歌手优先；词库外但榜位 ≤10 的也保留（榜单本身就是热度证明）。
    """
    subjects = keyword_layer(kw, "锚点层", "主体")
    amap = alias_map(kw)
    ctx = anchor_context(kw, load_sources().get("judge", {}) or {})

    inside: list[dict] = []
    outside: list[dict] = []
    for song in sig.get("songs") or []:
        artist = "、".join(song.get("artists") or [])
        hit = match_subject(artist, subjects, amap, **ctx)
        rank = int(song.get("rank") or 99)
        if not hit and rank > 10:
            continue
        row = {
            "q": song["name"],
            "type": "歌名",
            "reason": f"{song.get('chart', '')}#{rank} · {hit or '词库外'}",
            "publish_time": days,
        }
        (inside if hit else outside).append(row)

    return (inside + outside)[:limit]


def _rotate(pool: list[str], day: int, n: int) -> list[str]:
    """按天取模轮转，避免每次从头取、尾部的永远轮不到。"""
    if not pool or n <= 0:
        return []
    start = (day * max(1, n)) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(min(n, len(pool)))]


def _subject_queries(
    hot: list[tuple[str, int, str]],
    kw: dict,
    *,
    cap: int = 12,
    days: int = DAYS["主体"],
) -> list[dict]:
    """主体查询：有信号的优先，剩余按 region 均分轮转补齐。

    为什么要补轮转：三个信号源（抖音热榜 / QQ 音乐榜 / tunbang）都是内娱偏向，
    K-pop 团在里面几乎不出现。纯信号驱动会让韩娱内容归零——2026-11-24、11-25
    两天实测 `subjects_hit` 都是 1，日报里一张韩娱素材卡都没有，
    而改造前（tier 轮转）韩娱占 S 档一半，天天有内容。

    所以留一半配额按 region 轮转：内娱轮转 + 韩娱轮转各占剩余的一半，
    保证韩娱每天都有团被搜到。裸名，不拼场景词（舞台是弱标签，加了会漏）。
    """
    out: list[dict] = []
    used: set[str] = set()

    for name, sc, why in hot[:cap]:
        out.append(
            {
                "q": name,
                "type": "主体",
                "reason": f"信号{sc}｜{why}",
                "publish_time": days,
            }
        )
        used.add(name)

    gap = cap - len(out)
    if gap > 0:
        profiles = subject_profiles(kw)
        day = datetime.now().timetuple().tm_yday
        n_kr = gap // 2
        n_cn = gap - n_kr
        for region, need in (("内娱", n_cn), ("韩娱", n_kr)):
            groups_ = [
                s for s, i in profiles.items()
                if i.get("region") == region and i.get("type") == "团体" and s not in used
            ]
            solos = [
                s for s, i in profiles.items()
                if i.get("region") == region and i.get("type") == "个人" and s not in used
            ]
            # 团体占 2/3：搜一个团体能带出全团内容，搜一个个人只覆盖他自己。
            # 2026-11-25 实测：内娱池按原顺序抽，6 个名额全是时代少年团成员，
            # 同团内容高度重叠，等于浪费了 5 个查询。
            n_g = max(1, round(need * 2 / 3)) if groups_ else 0
            names = _rotate(groups_, day, n_g)
            names += _rotate(solos, day, need - len(names))
            if len(names) < need:      # 个人池不够（韩娱没有 solo）时用团体补满
                names += _rotate([s for s in groups_ if s not in names], day, need - len(names))
            for name in names[:need]:
                out.append(
                    {
                        "q": name,
                        "type": "主体",
                        "reason": f"轮转补齐·{region}",
                        "publish_time": days,
                    }
                )
    return out[:cap]


def _template_queries(
    sig: dict,
    hot: list[tuple[str, int, str]],
    limit: int,
    kw: dict,
    *,
    days: int = DAYS["玩法"],
) -> list[dict]:
    """玩法查询：热榜里的形式词标题 + 团体 × 形式词。

    不再用 `title.endswith("挑战")`——转场/卡点/换装从来不叫「挑战」，
    那条断言把整个剪辑型玩法挡在门外（2026-11-23 复盘）。

    第二条只拼**团体**：`TWS 转场` 有人搜，`孙燕姿 转场` 搜回来基本是空的。
    """
    out: list[dict] = []
    seen: set[str] = set()

    for cand in sig.get("hot") or []:
        title = str(cand.term or "").strip()
        if not 4 <= len(title) <= 24:
            continue
        if is_activity_container(title):
            continue                  # 「挑战赛/大赏」这类合集不是玩法
        if not any(w in title for w in TEMPLATE_WORDS):
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "q": title,
                "type": "玩法",
                "reason": f"热榜#{cand.rank or '-'}",
                "publish_time": days,
            }
        )
        if len(out) >= limit:
            return out

    groups = _group_names(kw)
    picked = 0
    for name, _sc, _why in hot:
        if name not in groups:
            continue                  # 个人歌手不做玩法查询
        word = TEMPLATE_WORDS[picked % len(TEMPLATE_WORDS)]
        picked += 1
        q = f"{name} {word}"
        if q.lower() in seen:
            continue
        seen.add(q.lower())
        out.append(
            {
                "q": q,
                "type": "玩法",
                "reason": f"热门团体×{word}",
                "publish_time": days,
            }
        )
        if len(out) >= limit:
            return out

    # 热榜没有形式词、热门团体也凑不出时，用泛词补。
    # 单独搜「变装」能带出当天在流行的手法，是跨圈玩法的主要来源——
    # 2026-11-25 一个「七天七色变装挑战」就撬出 3 张跨圈卡。
    for word in ("变装", "转场", "卡点"):
        if len(out) >= limit:
            break
        if word in seen:
            continue
        seen.add(word)
        out.append(
            {
                "q": word,
                "type": "玩法",
                "reason": "泛词（热榜无形式词）",
                "publish_time": days,
            }
        )
    return out


def _hot_seed_queries(used: set[str], limit: int) -> list[dict]:
    """读「热点种子」，来自 scripts/collect_seeds.py（抓 tunbang + 模型筛选 + 转化）。

    这是唯一还保留的「外部新词」入口：发现类已删除，热种是唯一能带来
    我们没见过的东西的通道。

    过期保护：只认今天或昨天的种子。拿不到就当没有——这是增强项，
    不能因为第三方站挂了就中断整个计划生成。
    """
    path = SEEDS_PATH or (ROOT / "data" / "input" / "hot_seeds.json")
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []

    gen = str(data.get("generated_at") or "")[:10]
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if gen and gen not in {today, yesterday}:
        return []

    out: list[dict] = []
    for q in data.get("queries") or []:
        word = str(q.get("q") or "").strip()
        if not word or word.lower() in used:
            continue
        used.add(word.lower())
        out.append(
            {
                "q": word,
                "type": "热种",
                "reason": f"聚合榜·{q.get('kind', '')}｜{str(q.get('from_title') or '')[:18]}",
                "publish_time": DAYS["玩法"],
            }
        )
        if len(out) >= limit:
            break
    return out


def _interleave(batches: list[list[dict]], max_queries: int) -> list[dict]:
    """按类型轮流取，而不是「一类跑完再下一类」。

    2026-11-09 的教训：计划是「歌名 10 → 挑战 10 → 主体 10 → 发现 5」，
    采集在第 10 个查询后就开始 502 熔断，于是日报里 8 张卡全是 BGM、跨圈 0 ——
    不是当天没有新挑战，而是挑战查询根本没轮到。
    交错后，同样的覆盖率会得到各类型都有的样本。
    """
    out: list[dict] = []
    seen: set[str] = set()
    depth = 0
    while len(out) < max_queries:
        added = False
        for batch in batches:
            if depth >= len(batch):
                continue
            item = batch[depth]
            key = item["q"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            added = True
            if len(out) >= max_queries:
                break
        if not added:
            break
        depth += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="计划输出路径（默认 data/input/query_plan.json）")
    ap.add_argument("--seeds", default="", help="热点种子文件（默认 data/input/hot_seeds.json）")
    args = ap.parse_args()

    global SEEDS_PATH
    if args.seeds:
        SEEDS_PATH = Path(args.seeds)
    out_path = Path(args.out) if args.out else OUT

    cfg = load_sources().get("sources", {}).get("douyin_search", {})
    max_queries = int(cfg.get("max_queries", 38))
    scroll = int(cfg.get("scroll", 5))
    quotas = cfg.get("quota") or {}

    kw = load_keywords()
    sig = _fetch_signals()

    subject_cap = int(quotas.get("主体", 12))
    hot = _hot_subjects(sig, kw, limit=subject_cap)
    subjects = _subject_queries(hot, kw, cap=subject_cap)
    # 主体没用完的配额给玩法：今天没热点的团不硬搜，把额度让给能出货的类
    template_quota = int(quotas.get("玩法", 8)) + max(0, subject_cap - len(subjects))
    template = _template_queries(sig, hot, template_quota, kw)

    # 歌名不补缺口：主体/玩法排不满时总量自然减少，不硬凑。
    # 少 10 个查询就少一半限流风险，而多搜几首歌名对「舞台」这个主轴没有帮助。
    chart = _chart_queries(sig, kw, int(quotas.get("歌名", 12)))

    used = {q["q"].lower() for q in chart + subjects + template}
    seeds = _hot_seed_queries(used, int(quotas.get("热种", 6)))

    # 交错：歌名 / 玩法 / 主体 / 热种 轮流上，避免「前面把额度用完、只剩一类」
    queries = _interleave([chart, template, subjects, seeds], max_queries)

    plan = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_by": "signal-driven",
        "budget": {"max_queries": max_queries, "scroll": scroll},
        "signals": {
            "hot": len(sig.get("hot") or []),
            "songs": len(sig.get("songs") or []),
            "seeds": len(sig.get("seed_titles") or []),
            "subjects_hit": len(hot),
        },
        "queries": queries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for q in queries:
        counts[q["type"]] = counts.get(q["type"], 0) + 1

    if not hot:
        print("[warn] 今日三源均未命中任何主体——主体查询为 0，请检查热榜/榜单是否抓到")

    print(f"信号：热榜 {len(sig.get('hot') or [])} / 榜单 {len(sig.get('songs') or [])} "
          f"/ 热种 {len(sig.get('seed_titles') or [])} → 命中主体 {len(hot)} 个")
    print(f"计划 {len(queries)} 个查询（{counts}），每查询滚动 {scroll} 次 → {out_path}")
    for q in queries[:10]:
        print(f"  [{q['type']}] {q['q'][:26]:<28}{q['reason'][:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
