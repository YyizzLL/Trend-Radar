"""六套 prompt 的拼装层。

**正文不在这里**，在 `CoreAssets/Prompts.md`。本模块只负责：
1. 从文档取 system / user 模板
2. 把调用方给的数据拼成 `{items}` 这类块
3. 注入业务准则（`{docs}`）

共同约束写在 Prompts.md 的「通用约束」一节，改的时候一起看。

为什么这么拆：提示词是产品判断，会频繁改；拼装是代码，很少改。
混在一个文件里，每次调提示词都要读一堆 f-string。
"""

from __future__ import annotations

from .context import for_layer
from .promptdoc import blocks, render

__all__ = [
    "discover_prompt",
    "seed_prompt",
    "material_prompt",
    "phrase_eval_prompt",
    "phrase_merge_prompt",
    "hotboard_prompt",
]

_DOCS_FALLBACK = "（准则文档缺失，按常识判断）"


def _system(layer: str, *, with_docs: bool = False) -> str:
    system, _ = blocks(layer)
    if with_docs:
        return render(system, layer=layer, docs=for_layer(layer) or _DOCS_FALLBACK)
    return render(system, layer=layer)


# --------------------------------------------------------------- 热点侦察


def discover_prompt(
    *,
    date_str: str,
    subjects: list[str],
    search: list[str],
    hotboard: list[str],
    aggregate: list[str],
    seeds: list[str],
) -> tuple[str, str]:
    """四路输入合成一次侦察调用。

    每路都是「日期/来源 + 标题」的纯文本行，已由调用方格式化好——
    这里不做筛选，也不再拆分来源权重，权重写在提示词里由模型判断。
    """
    system, user = blocks("discover")
    return render(system, layer="discover"), render(
        user,
        layer="discover",
        date=date_str,
        subject_n=len(subjects),
        subjects="、".join(subjects) or "（词库为空）",
        search="\n".join(search) or "（无）",
        hotboard="\n".join(hotboard) or "（无）",
        aggregate="\n".join(aggregate) or "（无）",
        seeds="\n".join(seeds) or "（无）",
    )


# --------------------------------------------------------------- 种子筛选


def seed_prompt(items: list[dict]) -> tuple[str, str]:
    """items 每项：idx / title / platform / rank / heat"""
    rows = []
    for it in items:
        meta = f"{it.get('platform') or '?'} #{it.get('rank') or '?'}"
        if it.get("heat"):
            meta += f"，{it['heat']}"
        rows.append(f"[{it['idx']}] {it.get('title')}（{meta}）")
    _, user = blocks("seed_filter")
    return _system("seed_filter"), render(
        user, layer="seed_filter", n=len(items), items="\n".join(rows)
    )


# --------------------------------------------------------------- 素材理解


def material_prompt(*, query: str, items: list[dict]) -> tuple[str, str]:
    """items 每项：{"url","likes","text"}。"""
    rows = []
    for i, it in enumerate(items, 1):
        text = str(it.get("text") or "").replace("\n", " ")[:180]
        rows.append(f"[{i}] url={it.get('url','')} 赞={int(it.get('likes') or 0)} 文案={text}")
    _, user = blocks("material")
    return _system("material", with_docs=True), render(
        user,
        layer="material",
        query=query or "（未记录）",
        n=len(items),
        items="\n".join(rows),
    )


# ----------------------------------------------------------- 抖音热榜热梗


def hotboard_prompt(items: list[dict], today: str) -> tuple[str, str]:
    """items 每项：term / rank / hot_value（可选）"""
    rows = []
    for i, it in enumerate(items, 1):
        title = str(it.get("term") or "").strip()
        rank = it.get("rank")
        hot = it.get("hot_value") or it.get("hot")
        meta = " · ".join(
            x for x in (f"#{rank}" if rank else "", str(hot) if hot else "") if x
        )
        rows.append(f"[{i}] {title}" + (f"（{meta}）" if meta else ""))
    _, user = blocks("hotboard")
    return _system("hotboard"), render(
        user, layer="hotboard", date=today, n=len(items), items="\n".join(rows)
    )


# --------------------------------------------------------------- 短语归并


def phrase_merge_prompt(items: list[dict]) -> tuple[str, str]:
    """items 每项：phrase / videos"""
    rows = [
        f"[{i}] 「{it.get('phrase')}」· {int(it.get('videos') or 0)} 条在用"
        for i, it in enumerate(items, 1)
    ]
    _, user = blocks("phrase_merge")
    return _system("phrase_merge"), render(
        user, layer="phrase_merge", n=len(items), items="\n".join(rows)
    )


# --------------------------------------------------------------- 文案评估


def phrase_eval_prompt(items: list[dict]) -> tuple[str, str]:
    """items 每项：phrase / videos / likes_max / contexts / bgm / circle_hits / circle_ratio / first_seen_days"""
    rows = []
    for i, it in enumerate(items, 1):
        ctx = " / ".join((it.get("contexts") or [])[:3])[:200]
        bgm = it.get("bgm") or ""
        videos = int(it.get("videos") or 0)
        circle = int(it.get("circle_hits") or 0)
        ratio = it.get("circle_ratio")
        days = it.get("first_seen_days")
        extra: list[str] = []
        if ratio is not None:
            extra.append(f"圈内 {circle}/{videos} 条" + ("（纯跨圈）" if circle == 0 else ""))
        if isinstance(days, int) and days > 0:
            extra.append(f"已出现 {days} 天")
        rows.append(
            f"[{i}] 「{it.get('phrase')}」"
            f"（{videos} 条视频在用，最高赞 {int(it.get('likes_max') or 0):,}）\n"
            f"    出现语境：{ctx or '（无）'}"
            + (f"\n    同期在火的素材：{bgm}" if bgm else "")
            + (f"\n    其他信号：{'；'.join(extra)}" if extra else "")
        )
    _, user = blocks("phrase_eval")
    return _system("phrase_eval"), render(
        user, layer="phrase_eval", n=len(items), items="\n\n".join(rows)
    )
