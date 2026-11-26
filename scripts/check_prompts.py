"""校验 CoreAssets/Prompts.md：能解析、块齐全、占位符都能填上。

用法：
    python scripts/check_prompts.py

成功时打印一张表（每层字符数 + 占位符），失败时非 0 退出。
这是提示词改动的第一道闸门——比跑一轮日报便宜得多。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm import promptdoc
from src.llm.prompts import (
    discover_prompt,
    hotboard_prompt,
    material_prompt,
    phrase_eval_prompt,
    phrase_merge_prompt,
    seed_prompt,
)

REQUIRED = ["discover", "seed_filter", "material", "hotboard", "phrase_merge", "phrase_eval"]


def _build(layer: str) -> tuple[str, str]:
    if layer == "discover":
        return discover_prompt(
            date_str="2026-11-25",
            subjects=["ILLIT", "CORTIS"],
            search=["[1] 2026-11-25 · MAMA 公布阵容"],
            hotboard=["[11] #9 · 828万 · 此刻舞台上的我光芒万丈"],
            aggregate=["[21] 微博 #16 · 某团回归预告"],
            seeds=["[31] tunbang #9 · 网络剧"],
        )
    if layer == "seed_filter":
        return seed_prompt(
            [{"idx": 1, "title": "样例", "platform": "微博", "rank": 3, "heat": "27万"}]
        )
    if layer == "material":
        return material_prompt(
            query="时代少年团",
            items=[{"url": "https://v/1", "likes": 12345, "text": "样例文案 #tag"}],
        )
    if layer == "hotboard":
        return hotboard_prompt(
            [{"term": "此刻舞台上的我光芒万丈", "rank": 9, "hot_value": "828万"}],
            "2026-11-25",
        )
    if layer == "phrase_merge":
        return phrase_merge_prompt([{"phrase": "愿人生常驻", "videos": 4}])
    if layer == "phrase_eval":
        return phrase_eval_prompt(
            [
                {
                    "phrase": "愿人生常驻",
                    "videos": 4,
                    "likes_max": 367000,
                    "contexts": ["样例语境"],
                    "bgm": "某歌",
                    "circle_hits": 3,
                    "circle_ratio": 0.75,
                    "first_seen_days": 2,
                }
            ]
        )
    raise KeyError(layer)


def main() -> int:
    path = promptdoc.doc_path()
    if not path.exists():
        print(f"✗ 文档不存在：{path}")
        return 1
    print(f"文档：{path}（{len(path.read_text(encoding='utf-8')):,} 字符）")

    found = promptdoc.layers()
    missing = [x for x in REQUIRED if x not in found]
    extra = [x for x in found if x not in REQUIRED]
    print(f"解析到 {len(found)} 层：{'、'.join(found)}")
    if missing:
        print(f"✗ 缺少层：{missing}")
        return 1
    if extra:
        print(f"⚠ 未登记的层：{extra}（不影响运行，确认是否需要）")

    rows: list[tuple[str, int, int, str]] = []
    failed = 0
    for layer in REQUIRED:
        try:
            system, user = _build(layer)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {layer:<13} 拼装失败：{exc}")
            failed += 1
            continue

        problems: list[str] = []
        if len(system) < 100:
            problems.append("system 过短")
        if len(user) < 20:
            problems.append("user 过短")
        if "JSON" not in system:
            problems.append("system 未出现 JSON（json_object 模式会 400）")
        leftovers = promptdoc._PLACEHOLDER_RE.findall(system + user)
        if leftovers:
            problems.append(f"残留占位符 {sorted(set(leftovers))}")

        ph = promptdoc.placeholders(layer)
        keys = "、".join(sorted(ph["system"] | ph["user"])) or "（无）"
        flag = "✗" if problems else "✓"
        print(f"{flag} {layer:<13} system {len(system):>5} 字 / user {len(user):>5} 字  占位符：{keys}")
        if problems:
            print(f"    └ {'；'.join(problems)}")
            failed += 1
        rows.append((layer, len(system), len(user), keys))

    docs = promptdoc._all().get("material", {}).get("system", "")
    if "{docs}" in docs:
        from src.llm.context import for_layer

        injected = len(for_layer("material"))
        mark = "✓" if injected else "✗"
        print(f"{mark} material 注入业务文档：{injected} 字符")
        if not injected:
            failed += 1

    print()
    if failed:
        print(f"✗ 失败 {failed} 项")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
