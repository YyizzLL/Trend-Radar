"""把「文案模板（整句簇）」和「可用文案（短语）」对齐成一份名单。

两个栏原先各跑各的：
- `cluster_captions` 做整句 3-gram 相似度聚类，得到「同一句被多条视频照抄」
- `top_phrases` 做 4~16 字 n-gram 统计，得到「半句相同、后半句各写各的」

同一个梗两边都会命中（2026-11-17：「愿人生常驻 上上上上上升期」同时出现在两栏），
所以渲染前先按「包含 / 高相似」对齐，对齐后只出一条。

对齐只解决**展示重复**，不改变两边的统计口径：
- `size`   整句簇的规模（几乎一字不差的条数）
- `videos` 短语的包含计数（提到这句话的内容数，通常更大）
两个数都保留，读者自己判断。
"""

from __future__ import annotations

import re
from typing import Any

_NORM_RE = re.compile(r"[^\u4e00-\u9fa5a-zA-Z0-9]+")


def _norm(text: str) -> str:
    return _NORM_RE.sub("", text or "")


def _lcs(a: str, b: str) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, cj in enumerate(b, 1):
            if ch == cj:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def related(a: str, b: str, threshold: float = 0.6) -> bool:
    """两条文案是不是同一句：包含关系，或最长公共子串占较短那条 ≥60%。"""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    common = _lcs(na, nb)
    if common < 4:
        return False
    return common / min(len(na), len(nb)) >= threshold


def _entry(**kw: Any) -> dict[str, Any]:
    base = {
        "text": "", "size": 0, "likes_max": 0.0, "likes_median": 0.0,
        "tags": [], "variants": [], "members": [],
        "videos": 0, "use": "", "usage": "", "source": "", "bgm": "",
        "circle_hits": None, "days": None,
    }
    base.update(kw)
    return base


def _from_phrase(p: dict[str, Any], text: str = "") -> dict[str, Any]:
    return _entry(
        text=text or str(p.get("phrase") or ""),
        likes_max=float(p.get("likes_max") or 0),
        variants=list(p.get("variants") or []),
        videos=int(p.get("videos") or 0),
        use=str(p.get("use") or ""),
        usage=str(p.get("usage") or ""),
        source=str(p.get("source") or ""),
        bgm=str(p.get("bgm") or ""),
        circle_hits=p.get("circle_hits"),
        days=p.get("first_seen_days"),
    )


def merge(clusters: list[dict], phrases: list[dict]) -> list[dict[str, Any]]:
    """clusters 与 phrase_eval 对齐后返回一份名单（按 use 优先、规模降序）。"""
    entries: list[dict[str, Any]] = []
    used: set[int] = set()

    for c in clusters or []:
        rep = str(c.get("rep") or "")
        match = next(
            (i for i, p in enumerate(phrases or [])
             if i not in used and related(rep, str(p.get("phrase") or ""))),
            None,
        )
        if match is None:
            entries.append(_entry(
                text=rep,
                size=int(c.get("size") or 0),
                likes_max=float(c.get("likes_max") or 0),
                likes_median=float(c.get("likes_median") or 0),
                tags=list(c.get("tags") or []),
                variants=list(c.get("variants") or []),
                members=list(c.get("members") or []),
            ))
            continue
        used.add(match)
        p = phrases[match]
        entry = _from_phrase(p, text=rep)
        entry.update({
            "size": int(c.get("size") or 0),
            "likes_median": float(c.get("likes_median") or 0),
            "tags": list(c.get("tags") or []),
            "members": list(c.get("members") or []),
            "likes_max": max(float(c.get("likes_max") or 0), float(p.get("likes_max") or 0)),
        })
        entry["variants"] = list(dict.fromkeys(
            list(c.get("variants") or []) + list(p.get("variants") or [])
        ))
        entries.append(entry)

    for i, p in enumerate(phrases or []):
        if i in used:
            continue
        entries.append(_from_phrase(p))

    order = {"use": 0, "watch": 1, "skip": 2, "": 3}
    entries.sort(key=lambda e: (order.get(str(e.get("use")), 3),
                                -(int(e.get("size") or 0) or int(e.get("videos") or 0))))
    return entries
