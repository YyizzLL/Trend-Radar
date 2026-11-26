"""主体命中判定：从一段文本里认出「这是谁的素材」。

规则全部来自实测误判，所以集中在这里，避免两个地方各写一套：

- 判定层（`main._match_subject` 的调用方）：算不算「圈内」
- 计划层（`plan_queries` / `collect_douyin.legacy_queries`）：该不该为这个主体搜歌

曾经计划层用裸子串匹配，`礼` 这种单字别名也能命中，于是拿一个误判的艺人名去搜歌，
判定层又不认——两头口径不一致。
"""

from __future__ import annotations

import re
from typing import Any

# 这些别名本身是普通词（十七 / 四代 / 三代），只有写成 #话题 才认
AMBIGUOUS_ALIASES = {"十七", "四代", "三代", "十八楼"}

# 成员艺名里混着大量常用英文词/人名，裸子串匹配会大面积误判：
#   `stella` 命中 `stellar`、`moon` 命中 `moonlight`、`young` 命中 `younger`、
#   `winter` 命中冬季文案、`sora` 命中 OpenAI Sora。
# 这些名字只有写成 #话题（#Ella / #Winter）才算命中该成员所属团体。
# 判断口径：这个词在普通英文文本里会自然出现，且不是该成员的强标识。
# 未列入的长专名（Seonghyeon / Yoonchae / Chanelle Moon）保留裸匹配。
AMBIGUOUS_MEMBERS = {
    "james", "martin", "ella", "anna", "moon", "young", "hana",
    "merci", "stella", "sophia", "athena", "winter", "sora",
}

# C 档（大众情怀型）不算圈内：一条用周杰伦 BGM 的剪辑，不该把圈内素材挤掉
MIN_WEIGHT = 0.3


def _probe_in(low: str, probe: str) -> bool:
    """探针是否出现在文本里。ASCII 要加词边界，否则 IU 会命中 giulietta。"""
    p = probe.lower()
    if not p:
        return False
    if p.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", low) is not None
    return p in low


def match_subject(
    text: str,
    subjects: list[str],
    aliases: dict[str, list[str]],
    *,
    profiles: dict[str, dict[str, Any]] | None = None,
    members: dict[str, str] | None = None,
    cp_names: list[str] | None = None,
    ambiguous: dict[str, list[str]] | None = None,
) -> str:
    """文本里命中哪个主体（含别名 / 团体成员 / CP），取最长命中。

    规则（都来自实测误判）：
    - 3 字以内的英文别名（TNT / SM / V）撞词率太高，不参与判定
    - **单字中文别名一律不认**：`礼` 命中「东方礼，送礼就送…」，把一条护肤品广告
      判成了 ILLIT 的圈内内容
    - 歧义别名（十七 / 四代 / 三代）必须带 `#话题` 才算
    - 成员名归到所属团体（命中「宋亚轩」= 命中「时代少年团」）
    - C 档（周杰伦 / 周星驰这类）命中也返回空：它们算大众热点，不算「圈内」
    - 歧义主体（染色体 / SM）需带上限定词，避免「基因在染色体上」被判成追星内容
    """
    low = (text or "").lower()
    profiles = profiles or {}
    members = members or {}
    ambiguous = ambiguous or {}
    best_subject, best_len = "", 0

    def _accept(probe: str, primary: bool = False) -> bool:
        if not probe:
            return False
        if probe.isascii():
            # 3 字以内英文别名（TNT / SM / BP）撞词率过高；正名本身不受此限（GAI / YG）
            return primary or len(probe) > 3
        # 单字中文别名（礼 / 迷 / 符 / 档）几乎必然误判
        return primary or len(probe) >= 2

    def _ambiguous_ok(subject: str) -> bool:
        need = ambiguous.get(subject)
        if not need:
            return True
        return any(w and w.lower() in low for w in need)

    for subject in subjects:
        if profiles.get(subject, {}).get("weight", 1.0) < MIN_WEIGHT:
            continue                      # C 档不算圈内
        if not _ambiguous_ok(subject):
            continue
        for probe in (subject, *aliases.get(subject, [])):
            if not _accept(probe, primary=(probe == subject)):
                continue
            if not _probe_in(low, probe) or len(probe) <= best_len:
                continue
            # 歧义别名：必须写成 #话题
            if probe != subject and probe in AMBIGUOUS_ALIASES and f"#{probe.lower()}" not in low:
                continue
            best_subject, best_len = subject, len(probe)

    for member, group in members.items():
        if not _accept(member):
            continue
        # 高歧义英文艺名：必须带 #话题，否则 "stellar" 会被认成 KATSEYE 的 Ella
        if member.lower() in AMBIGUOUS_MEMBERS and f"#{member.lower()}" not in low:
            continue
        if profiles.get(group, {}).get("weight", 1.0) < MIN_WEIGHT:
            continue
        if not _ambiguous_ok(group):
            continue
        if _probe_in(low, member) and len(member) > best_len:
            best_subject, best_len = group, len(member)

    for cp in (cp_names or []):
        if not _accept(cp):
            continue
        if _probe_in(low, cp) and len(cp) > best_len:
            best_subject, best_len = cp, len(cp)

    return best_subject


def context(
    keywords: dict[str, Any],
    judge_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`match_subject` 的固定参数：画像、成员归属、CP、歧义主体。

    计划层与判定层都用这一份，避免两边对同一个别名给出不同结论。
    """
    from ..config import keyword_layer, member_map, subject_profiles

    ambiguous = (judge_cfg or {}).get("ambiguous_anchors") or {}
    return {
        "profiles": subject_profiles(keywords),
        "members": member_map(keywords),
        "cp_names": keyword_layer(keywords, "锚点层", "CP"),
        "ambiguous": {
            str(k): [str(x) for x in v]
            for k, v in ambiguous.items()
            if isinstance(v, list)
        },
    }
