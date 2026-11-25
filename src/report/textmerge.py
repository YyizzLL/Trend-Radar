"""文案相似度判据（只保留 `related`）。

历史：这里原来还做「整句簇 + 短语」的对齐合并（`merge`）。整句聚类删除后
（2026-11-25），只剩一件事——判断两句话是不是同一句，用来给热榜文案去重：
已经在采集结果里出现过的，不再重复列一遍。

判据：包含关系，或最长公共子串占较短那条 ≥60%。
"""

from __future__ import annotations

import re

_NORM_RE = re.compile(r"[^\u4e00-\u9fa5a-zA-Z0-9]+")


def _norm(text: str) -> str:
    return _NORM_RE.sub("", text or "")


def _lcs(a: str, b: str) -> int:
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
