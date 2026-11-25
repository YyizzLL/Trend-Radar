"""文案候选的合并与评估。

2026-11-25 起「短语」不再是一个独立概念——它只是文案候选的三个来源之一
（n-gram 复用句 / 高赞独特句 / 热榜句）。原来的 copy/title/noise 三分类已删：
同一批句子判两遍、口径还打架。

- `merge_variants()` —— 同一句的不同切法合并成一条（「上上上升期」vs「上上上上升期」）。
- `evaluate()`       —— 唯一的加工入口：把候选句子补齐成能直接用的成品，
                        补不出来的丢掉。每天一次，结果直接进日报，不落长期状态。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from . import prompts
from .client import LLM

log = logging.getLogger("radar.llm.phrases")

# 交付句与原句的字重叠下限。低于这个值说明模型不是「补齐」而是「另写一句」。
# 2026-11-25 实测：「周深厦门演唱」被补成「一路打拼终抵百场…」——原句里没有这些字。
MIN_OVERLAP = 0.5

_NON_CJK_RE = re.compile(r"[^\u4e00-\u9fa5]")


def _overlap(text: str, source: str) -> float:
    """交付句里有多少字来自原句（按字频交集 / 交付句长度，只算汉字）。

    比最长公共子串宽松：允许删字、换专名、调语序，只挡住「整句另写」。
    """
    a, b = _NON_CJK_RE.sub("", text), _NON_CJK_RE.sub("", source)
    if not a:
        return 1.0
    if not b:
        return 0.0
    pool = Counter(b)
    common = sum(min(n, pool[ch]) for ch, n in Counter(a).items() if ch in pool)
    return common / len(a)


def _anchor(text: str, known: dict[str, dict[str, Any]], fallback: str) -> str:
    """交付句该挂在哪条原句上（决定「在用 N 条」这类统计口径）。

    模型给的 `from` 不一定是最佳锚点：它常挑「最完整的那个变体」当 from，
    而那个变体只有 1 条在用；真正的热度在更短的公共句上。
    所以优先取「被交付句包住、且在用条数最多」的那条。
    """
    body = _NON_CJK_RE.sub("", text)
    best, best_v = fallback, -1
    for phrase, src in known.items():
        core = _NON_CJK_RE.sub("", phrase)
        if core and core in body:
            vids = int(src.get("videos") or 0)
            if vids > best_v:
                best, best_v = phrase, vids
    return best


def merge_variants(
    llm: LLM,
    phrases: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把「像、但不是真子集」的写法交给模型判成同一句。

    真子集（「愿人生常驻」完整出现在「愿人生常驻上上上上上」里）由 `top_phrases`
    的规则直接合并，不进这里；这里只处理「首尾被切开、互相不是子串」的那种，
    例如「愿人生常驻上上上上上」和「上上上上上上升期」。

    模型只做分组：`keep` 必须是输入里逐字存在的某一条，改过的行整条作废——
    润色过的句子就不再是用户的原话，宁可多留一行。

    失败 / 不可用时原样返回，不影响出报。
    """
    items = [p for p in phrases if str(p.get("phrase") or "").strip()][:limit]
    stats: dict[str, Any] = {"calls": 0, "input": len(items), "groups": 0, "merged": 0}
    if len(items) < 2:
        return list(phrases), stats

    system, user = prompts.phrase_merge_prompt(items)
    res = llm.json_call(layer="phrase_merge", system=system, user=user)
    stats["calls"] = 1
    if not res.ok:
        stats["failed"] = 1
        return list(phrases), stats

    known = {str(p["phrase"]): p for p in items}
    drop: set[str] = set()
    data = res.data if isinstance(res.data, dict) else {}
    for row in data.get("groups") or []:
        if not isinstance(row, dict):
            continue
        keep = str(row.get("keep") or "").strip()
        if keep not in known or keep in drop:
            continue
        members = [
            m for m in (str(x).strip() for x in (row.get("merge") or []))
            if m in known and m != keep
        ]
        if not members:
            continue
        rec = known[keep]
        merged: list[str] = list(rec.get("variants") or [])
        for m in members:
            if m in drop:
                continue
            merged.append(m)
            merged.extend(known[m].get("variants") or [])
            # 证据取并集的上界：短的都是长的那条的切法，计数本来就是它的子集
            rec["videos"] = max(int(rec.get("videos") or 0), int(known[m].get("videos") or 0))
            rec["likes_max"] = max(
                float(rec.get("likes_max") or 0), float(known[m].get("likes_max") or 0)
            )
            drop.add(m)
            stats["merged"] += 1
        rec["variants"] = list(dict.fromkeys(x for x in merged if x))
        stats["groups"] += 1

    if drop:
        log.info("短语归并：%d 组，并入 %d 条", stats["groups"], stats["merged"])
    return [p for p in phrases if str(p["phrase"]) not in drop], stats


def evaluate(
    llm: LLM,
    phrases: list[dict[str, Any]],
    *,
    material_names: list[str] | None = None,
    limit: int = 12,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把候选句子加工成能直接用的成品文案。

    模型只做两件事：给成品（`text`），或者丢掉。不再分类、不再解释怎么用。
    2026-11-25 之前是 use/watch/skip 三分类，`watch` 成了垃圾桶 ——
    16 条候选 8 条进去，其中 6 条只需删标签或补主语就是可交付的。

    返回 (带 from/text/videos/... 的列表, 统计)。失败返回空列表，不影响发信。
    """
    picked = [p for p in phrases if str(p.get("phrase") or "").strip()][:limit]
    stats: dict[str, Any] = {
        "calls": 0, "input": len(picked), "kept": 0, "rewritten": 0, "drops": 0,
    }
    if not picked:
        return [], stats

    names = [n for n in (material_names or []) if n]
    items: list[dict[str, Any]] = []
    for p in picked:
        row = dict(p)
        # 关联同日素材：看这句出现在哪些文案里，那些文案是否提到今天的热点素材名。
        # 命中就写进 prompt，让模型知道「这句词和哪首歌同期在火」。
        text = " ".join(p.get("contexts") or [])
        hit = [n for n in names if n and n in text]
        row["bgm"] = "、".join(dict.fromkeys(hit))[:40]
        items.append(row)

    system, user = prompts.phrase_eval_prompt(items)
    res = llm.json_call(layer="phrase_eval", system=system, user=user)
    stats["calls"] = 1
    if not res.ok:
        stats["failed"] = 1
        return [], stats

    # 用 items（带 bgm 的副本）而不是 picked：素材关联写在副本上
    known = {str(p["phrase"]): p for p in items}
    data = res.data if isinstance(res.data, dict) else {}
    out: list[dict[str, Any]] = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        frm = str(row.get("from") or "").strip()
        text = str(row.get("text") or "").strip()
        # 原句必须一字不差来自输入：模型爱「顺手改写 from」，改了就对不上统计
        if frm not in known or not text:
            continue
        # 补齐可以删字、换专名，但不能整句另写：交付句得有一半的字来自原句
        if _overlap(text, frm) < MIN_OVERLAP:
            stats["rejected"] = stats.get("rejected", 0) + 1
            continue
        # 统计口径挂在「被这句包住、在用最多」的原句上，而不是模型随手挑的 from
        anchor = _anchor(text, known, frm)
        src = known[anchor]
        out.append(
            {
                # 原句：在用条数、圈层、寿命这些口径都挂在它身上
                "phrase": anchor,
                # 成品：渲染只用这一条。等于 from 时就是原句
                "text": text[:60],
                "videos": src.get("videos", 0),
                "likes_max": src.get("likes_max", 0),
                "sample": (src.get("sample") or "")[:60],
                "bgm": src.get("bgm", ""),
                # 首见于几天前：None 表示今天第一次见（或没有历史）
                "first_seen_days": src.get("first_seen_days"),
                # 归一化后的代表词：同一句的不同切法共享年龄
                "canonical": src.get("canonical"),
                # 被并进来的其他写法（规则 + 模型两层的合并结果）
                "variants": src.get("variants") or [],
                # 圈层来源：circle_hits/videos，0 表示纯跨圈
                "circle_hits": src.get("circle_hits"),
                "circle_ratio": src.get("circle_ratio"),
                # 交付标记：下游据此区分「模型给过成品的」和「只有原始聚类的」
                "delivered": True,
            }
        )
        if text != frm:
            stats["rewritten"] += 1

    # 没改字的排前面：它们保留了原始统计口径
    out.sort(key=lambda x: (x["text"] != x["phrase"], -int(x.get("videos") or 0)))
    stats["kept"] = len(out)
    stats["drops"] = len(data.get("drops") or [])
    # 留一份被丢掉的原句：提示词调紧时靠它判断是"该丢"还是"误杀"
    stats["dropped"] = [str(x)[:40] for x in (data.get("drops") or [])][:20]
    if out:
        log.info(
            "文案评估：%d 条 → 成品 %d（改写 %d）/ 丢弃 %d / 拒收 %d",
            len(picked), stats["kept"], stats["rewritten"],
            stats["drops"], stats.get("rejected", 0),
        )
    return out, stats
