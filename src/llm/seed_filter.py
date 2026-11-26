"""热点种子：把聚合榜的热搜标题，变成能去抖音搜的查询词。

两步：
1. `select()` —— 模型判断「这条有没有二创价值」，不做关键词卡点
2. `to_queries()` —— 按类型套转化模板，生成查询词

为什么不让模型直接给查询词：模型容易编出平台上不存在的词。
这里让模型只做「判断 + 抽主体」，查询词由规则拼，可控。

产出的查询词**不是结论**——必须回抖音搜一次看真实使用量，
和「歌名搜回来再看 mentions」是同一个逻辑。
"""

from __future__ import annotations

import logging
from typing import Any

from . import prompts
from .client import LLM

log = logging.getLogger("radar.llm.seeds")

VALID_TYPES = {"A", "B", "C", "D"}

def select(
    llm: LLM,
    seeds: list[dict[str, Any]],
    *,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """模型筛出有二创价值的热搜。返回 (保留项, 统计)。

    失败时返回空列表——这只是「找种子」，拿不到就不加查询，不能拖垮跑批。
    """
    picked = [dict(s, idx=i) for i, s in enumerate(seeds[:limit], start=1)]
    stats: dict[str, Any] = {"input": len(picked), "calls": 0, "kept": 0}
    if not picked:
        return [], stats

    system, user = prompts.seed_prompt(picked)
    res = llm.json_call(layer="seed_filter", system=system, user=user)
    stats["calls"] = 1
    if not res.ok:
        stats["failed"] = 1
        log.warning("热点筛选失败：%s", res.error)
        return [], stats

    by_idx = {p["idx"]: p for p in picked}
    data = res.data if isinstance(res.data, dict) else {}
    out: list[dict[str, Any]] = []
    for row in data.get("keep") or []:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("idx"))
        except (TypeError, ValueError):
            continue
        src = by_idx.get(idx)
        typ = str(row.get("type") or "").strip().upper()
        if not src or typ not in VALID_TYPES:
            continue
        out.append(
            {
                "title": src["title"],
                "url": src.get("url", ""),
                "platform": src.get("platform", ""),
                "rank": src.get("rank", 0),
                "heat": src.get("heat", ""),
                "type": typ,
                "subject": str(row.get("subject") or "").strip()[:20],
                "why": str(row.get("why") or "").strip()[:40],
            }
        )
        stats[typ] = stats.get(typ, 0) + 1

    stats["kept"] = len(out)
    if out:
        log.info(
            "热点筛选：%d 条 → 保留 %d（A物料 %d / B玩法 %d / C句子 %d / D主体 %d）",
            len(picked), len(out),
            stats.get("A", 0), stats.get("B", 0), stats.get("C", 0), stats.get("D", 0),
        )
    else:
        log.info("热点筛选：%d 条 → 保留 0", len(picked))
    return out, stats


