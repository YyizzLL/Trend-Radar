"""复用短语检测：从一堆文案里找出「被多条视频共同使用的短句」。

为什么不用整句聚类：
- 整句聚类要求文案几乎一字不差，实际只会抓到「宣发贴」和「真的在抄」两类
- 而文案梗常常是「半句相同、后半句各写各的」，整句相似度掉到阈值以下

所以先做短语级统计：一个 4~10 字的中文短语，如果出现在 ≥N 条**不同视频**里，
它就是「疑似文案梗」，值得人工看一眼。它不直接进日报热点，只作发现线索。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median

from ..judge.domain import DOMAIN_NOISE, HARD_NOISE_GROUPS, hit as domain_hit
from ..judge.works import looks_like_title, works_ratio
from ..models import Candidate

HASHTAG_RE = re.compile(r"#[^\s#]{1,20}")
AT_RE = re.compile(r"@[^\s@]{1,20}")
NON_CJK_RE = re.compile(r"[^\u4e00-\u9fa5]+")

MIN_LEN = 4
# 10 太短：「愿人生常驻 上上上上上 上升期」这种整句会被切成半截，
# 合并后的代表词只能是「愿人生常驻上上上上」这种窗口。提到 16 让整句能成为候选；
# 长串要过 `min_videos` 门槛才会留下，不会引入太多噪声（2026-11-17 实测）。
MAX_LEN = 16
DEFAULT_MIN_VIDEOS = 3

# 新鲜度权重：按「使用它的内容年龄中位数」打折。
# 一条老梗只要今天还有 3 条在用，光看条数就能上榜（2026-11-11 用户反馈：
# 「你就这样闯进我」「这么晚了你在干什么」都是几个月前的梗）。
# 中位年龄越小说明这句子最近才被大量复用，越可能是新起的梗。
_FRESH_TIERS = ((3, 1.0), (7, 0.85), (14, 0.6))
_STALE_WEIGHT = 0.4
_AGE_CAP = 40          # 每个短语最多记多少个年龄样本，防内存膨胀

# 硬噪声领域的词（体育/时政/电竞）：整条内容直接不参与
_HARD_WORDS = {
    w for group, words in DOMAIN_NOISE.items() if group in HARD_NOISE_GROUPS for w in words
}

# 标签统计：抖音的「梗」大量以 #话题 形态存在（#MAMA、#权志龙mama），
# 正文里可能一字不提。所以单独统计，不混进 n-gram——
# 混进去会和正文粘连成「首秀权志龙」这种窗口，反而更脏。
TAG_RE = re.compile(r"#([^\s#]{2,20})")

# 高赞独特句：不等「被复制」，直接按点赞×时效取。
# 2026-11-25 实测：「舞台杀疯啦」「我宣布 GiiiRIP 为 2026 神作」这类单条爆款
# 只出现一次，被 ≥3 条门槛全挡掉，而它们比复用梗更鲜活。
HOT_MIN_LIKES = 30000
HOT_MAX_AGE = 3
HOT_MIN_LEN = 8

# 类别词过滤：「一键换装」「年末舞台」「声生不息」这类是**分类名**，不是可复用的句子。
# 判据：6 字以内 + 不含任何虚词/情绪词 → 纯名词组合，当类别处理（2026-11-25）。
# 真正能用的文案几乎都带「的我了是吗」或情绪词，不会被误伤。
_FUNCTION_WORDS = set(
    "我你他她它们这那么什怎谁的了着过是在有和与就都也还又很太最不没别把被给让对从向往会能要想说看真"
)

# 引流套话：跨主体度很高，但不是文案（「喜欢别忘记一键三连哦」跨了 9 个主体）
_WATERMARK = (
    "一键三连", "点赞", "关注", "转发", "收藏", "投币", "弹幕",
    "评论区", "口德", "你为谁打", "艾特", "私信", "主页",
)


def _is_category_word(gram: str) -> bool:
    """短且没有虚词 = 类别名，不是句子。"""
    if len(gram) >= 6:
        return False
    return not (set(gram) & _FUNCTION_WORDS)


def _is_watermark(gram: str) -> bool:
    return any(w in gram for w in _WATERMARK)


def _body(text: str) -> str:
    t = HASHTAG_RE.sub(" ", text or "")
    t = AT_RE.sub(" ", t)
    t = NON_CJK_RE.sub(" ", t)
    return " ".join(t.split())


def _noise_terms() -> set[str]:
    terms: set[str] = set()
    for words in DOMAIN_NOISE.values():
        terms.update(w for w in words if len(w) >= 2 and w.isascii() is False)
    return terms


def top_phrases(
    candidates: list[Candidate],
    *,
    exclude_names: set[str] | None = None,
    exclude_phrases: set[str] | None = None,
    min_videos: int = DEFAULT_MIN_VIDEOS,
    limit: int = 8,
    subject_names: set[str] | None = None,
) -> list[dict]:
    """返回 [{phrase, videos, likes_max, sample, ...}]，按覆盖视频数 × 新鲜度降序。

    `subject_names` 用来算 `circle_ratio`：这个短语出现在多少条「提到关注主体」的内容里。
    纯跨圈的句子（ratio=0）可能是圈外专用梗，也可能是刚起来还没被追星圈采用的新梗，
    两者要区别对待，所以这里只给信号、不做硬过滤。
    """
    exclude_names = {n for n in (exclude_names or set()) if n}
    exclude_phrases = {p for p in (exclude_phrases or set()) if p}
    noise = _noise_terms()

    counter: Counter[str] = Counter()
    best_like: dict[str, float] = defaultdict(float)
    sample: dict[str, str] = {}
    contexts: dict[str, list[str]] = defaultdict(list)
    ages: dict[str, list[float]] = defaultdict(list)
    circle_hits: Counter[str] = Counter()
    # 跨主体度：这条短语出现在几个不同主体的内容里。
    # 跨 2 个以上说明是通用表达，跨 1 个大概率是粉丝黑话（2026-11-25）。
    subject_sets: dict[str, set[str]] = defaultdict(set)
    subjects = {s for s in (subject_names or set()) if s}

    for cand in candidates:
        raw = cand.term or ""
        # 英文噪声词按词边界匹配：否则 `ig` 会命中 `Highlight` 这类正常英文
        low_raw = raw.lower()
        if any(domain_hit(low_raw, w) for w in _HARD_WORDS):
            continue
        body = _body(raw)
        if len(body) < MIN_LEN:
            continue
        likes = float(cand.field.get("likes") or 0)
        age = cand.field.get("age_days")
        age_ok = isinstance(age, (int, float)) and age >= 0
        # 圈内：文案里出现任一关注主体或其别名
        hit_subjects = {n for n in subjects if n in raw}
        in_circle = bool(hit_subjects)
        seen: set[str] = set()
        for n in range(MIN_LEN, MAX_LEN + 1):
            for i in range(len(body) - n + 1):
                gram = body[i : i + n]
                if " " in gram:
                    continue
                seen.add(gram)
        for gram in seen:
            counter[gram] += 1
            if in_circle:
                circle_hits[gram] += 1
                subject_sets[gram] |= hit_subjects
            if len(contexts[gram]) < 6:
                contexts[gram].append(cand.term)
            if age_ok and len(ages[gram]) < _AGE_CAP:
                ages[gram].append(float(age))
            if likes > best_like[gram]:
                best_like[gram] = likes
                sample[gram] = cand.term

    cands = []
    for gram, count in counter.items():
        if count < min_videos:
            continue
        if any(name in gram or gram in name for name in exclude_names):
            continue
        if any(word in gram for word in exclude_phrases):
            continue
        if any(w in gram for w in noise):
            continue
        # 类别名（一键换装 / 年末舞台）和引流套话（一键三连）不是文案
        if _is_category_word(gram) or _is_watermark(gram):
            continue
        # 规则层：来源文案在讲作品，且短语本身不像一句话 → 判专名
        if looks_like_title(gram, contexts.get(gram, [])):
            continue
        cands.append((gram, count))
    # 去碎片（2026-11-17 改）：n-gram 会把同一句切成互相重叠的窗口，
    # 例如「愿人生常驻」/「常驻上上上」/「上上上上上上升期」/「愿人生常驻上上上上上」。
    # 只比「谁包含谁」不够——中段窗口和核心句互不为子串；所以用**传递闭包**：
    # 任意两条互为子串就连边，连成一片的就是同一句。
    #
    # 代表词取组内**最长**的那条（见下），不取计数最高的：
    # 最短窗口计数天然最高，让它当代表就只剩「上上升期」这种碎片。
    # 互不为子串、只是很像的，交给模型分组，见 llm/phrases.merge_variants。
    parent_of: dict[str, str] = {g: g for g, _ in cands}

    def _find(x: str) -> str:
        while parent_of[x] != x:
            parent_of[x] = parent_of[parent_of[x]]
            x = parent_of[x]
        return x

    grams = [g for g, _ in cands]
    for i, a in enumerate(grams):
        for b in grams[i + 1:]:
            if a in b or b in a:
                ra, rb = _find(a), _find(b)
                if ra != rb:
                    parent_of[ra] = rb

    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for gram, count in cands:
        groups[_find(gram)].append((gram, count))

    kept: dict[str, int] = {}
    variants: dict[str, list[str]] = defaultdict(list)
    # 代表词取组内**最长**的那条：传递闭包里所有成员都是它的子串，
    # 所以最长的就是「这句话的完整写法」。取计数最高的会挑到「上上升期」这种
    # 最短窗口（它出现得最多），正是用户抱怨的碎片（2026-11-17 实测）。
    for members in groups.values():
        rep = max(members, key=lambda x: (len(x[0]), x[1]))[0]
        kept[rep] = max(c for _, c in members)
        variants[rep] = [g for g, _ in members if g != rep]

    def _age_stats(gram: str) -> tuple[float | None, float | None, float | None]:
        """(中位年龄, 最老年龄, ≤3 天占比)。没有年龄数据时返回三个 None。"""
        a = ages.get(gram) or []
        if not a:
            return None, None, None
        return (
            round(median(a), 1),
            round(max(a), 1),
            round(sum(1 for x in a if x <= 3) / len(a), 2),
        )

    def _fresh_weight(gram: str) -> float:
        med = _age_stats(gram)[0]
        if med is None:
            return 1.0          # 没有年龄数据就不惩罚，别误伤
        for limit, weight in _FRESH_TIERS:
            if med <= limit:
                return weight
        return _STALE_WEIGHT

    # 排序：条数 × 新鲜度 × 跨主体加成。
    # 跨主体加分是「通用度」：一句话在 2 个团的内容里都出现，说明它能跨场景用；
    # 只在 1 个团出现 20 次，大概率是粉丝黑话。用乘数而不是硬排序，
    # 避免「跨 2 主体各 1 条」压过「单主体 20 条」（2026-11-25）。
    def _score(gram: str, count: int) -> float:
        spread = len(subject_sets.get(gram, ()))
        return count * (1 + 0.5 * max(0, spread - 1)) * _fresh_weight(gram)

    ordered = sorted(kept.items(), key=lambda kv: -_score(kv[0], kv[1]))
    return [
        {
            "phrase": gram,
            "videos": count,
            "variants": variants.get(gram, []),
            "likes_max": best_like.get(gram, 0),
            "sample": sample.get(gram, ""),
            "contexts": contexts.get(gram, [])[:3],
            "works_ratio": round(works_ratio(contexts.get(gram, [])), 2),
            "median_age": _age_stats(gram)[0],
            "max_age": _age_stats(gram)[1],
            "fresh_ratio": _age_stats(gram)[2],
            # 出现在多少条「提到关注主体」的内容里；0 = 纯跨圈
            "circle_hits": circle_hits.get(gram, 0),
            "circle_ratio": round(circle_hits.get(gram, 0) / count, 2) if count else 0.0,
            # 跨主体度：出现在几个不同主体下，>=2 说明是通用表达
            "subjects": sorted(subject_sets.get(gram, ()))[:5],
            "subject_count": len(subject_sets.get(gram, ())),
        }
        for gram, count in ordered[:limit]
    ]


def top_tags(
    candidates: list[Candidate],
    *,
    min_videos: int = 3,
    limit: int = 12,
) -> list[dict]:
    """高频话题标签：#MAMA / #权志龙mama 这类「梗以标签形态传播」的入口。

    正文里可能一字不提，所以单列一条通道，不混进 n-gram（2026-11-25）。
    返回按「使用条数 × 新鲜度」排序，字段与 top_phrases 对齐，方便复用判定层。
    """
    counter: Counter[str] = Counter()
    best_like: dict[str, float] = defaultdict(float)
    ages: dict[str, list[float]] = defaultdict(list)
    ctx: dict[str, list[str]] = defaultdict(list)

    for cand in candidates:
        raw = cand.term or ""
        tags = {t.strip() for t in TAG_RE.findall(raw) if t.strip()}
        if not tags:
            continue
        likes = float(cand.field.get("likes") or 0)
        age = cand.field.get("age_days")
        age_ok = isinstance(age, (int, float)) and age >= 0
        for tag in tags:
            counter[tag] += 1
            if likes > best_like[tag]:
                best_like[tag] = likes
            if age_ok and len(ages[tag]) < _AGE_CAP:
                ages[tag].append(float(age))
            if len(ctx[tag]) < 3:
                ctx[tag].append(raw)

    def _fresh(age_list: list[float]) -> float:
        if not age_list:
            return 1.0
        med = median(age_list)
        for limit_, weight in _FRESH_TIERS:
            if med <= limit_:
                return weight
        return _STALE_WEIGHT

    rows = [
        {
            "phrase": tag,
            "videos": count,
            "variants": [],
            "likes_max": best_like.get(tag, 0),
            "sample": (ctx.get(tag) or [""])[0],
            "contexts": ctx.get(tag, []),
            "works_ratio": 0.0,
            "median_age": round(median(ages[tag]), 1) if ages.get(tag) else None,
            "max_age": round(max(ages[tag]), 1) if ages.get(tag) else None,
            "fresh_ratio": None,
            "circle_hits": count,
            "circle_ratio": 1.0,
            "subjects": [],
            "subject_count": 0,
            "kind": "tag",
        }
        for tag, count in counter.items()
        if count >= min_videos
    ]
    rows.sort(key=lambda r: -(_fresh(ages.get(r["phrase"], [])) * r["videos"]))
    return rows[:limit]


def hot_lines(
    candidates: list[Candidate],
    *,
    min_likes: float = HOT_MIN_LIKES,
    max_age: float = HOT_MAX_AGE,
    min_len: int = HOT_MIN_LEN,
    limit: int = 10,
) -> list[dict]:
    """高赞视频的独特表达：不等「被复制」，直接按点赞×时效取。

    一条 6 万赞的视频，它的文案本身就被 6 万人验证过，不需要「被复制 3 次」
    才叫梗。这类句子只出现一次，会被 top_phrases 的门槛全挡掉（2026-11-25）。
    返回结构对齐 top_phrases，可直接进同一套评估。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for cand in candidates:
        raw = (cand.term or "").strip()
        if not raw or raw in seen:
            continue
        likes = float(cand.field.get("likes") or 0)
        age = cand.field.get("age_days")
        if likes < min_likes:
            continue
        if not isinstance(age, (int, float)) or age > max_age:
            continue
        body = _body(raw)
        if len(body) < min_len:
            continue
        # 纯宣发/纯数据的不算：这类句子没有情绪
        if any(w in raw for w in ("官宣", "定档", "开播", "上线", "预告", "榜单", "销量")):
            continue
        seen.add(raw)
        out.append(
            {
                "phrase": raw[:60],
                "videos": 1,
                "variants": [],
                "likes_max": likes,
                "sample": raw,
                "contexts": [raw],
                "works_ratio": 0.0,
                "median_age": float(age),
                "max_age": float(age),
                "fresh_ratio": 1.0,
                "circle_hits": 0,
                "circle_ratio": 0.0,
                "subjects": [],
                "subject_count": 0,
                "kind": "hot_line",
            }
        )
    out.sort(key=lambda r: -r["likes_max"])
    return out[:limit]
