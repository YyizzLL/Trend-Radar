"""Markdown 日报渲染：输出的是「素材卡」，不是「视频标题」。"""

from __future__ import annotations

from ..models import Material, SourceStatus
from .evidence import count_phrase
from .textmerge import related

_ICON = {"ok": "✅", "failed": "❌", "skipped": "⚪"}


def _cell(text: str, limit: int = 0) -> str:
    """表格单元格安全化：转义竖线、压平换行、可选截断。"""
    t = (text or "").replace("|", "\\|").replace("\n", " ").strip()
    if limit and len(t) > limit:
        t = t[:limit] + "…"
    return t or "—"


def render_report(
    *,
    date_str: str,
    generated_at: str,
    elapsed_s: float,
    statuses: list[SourceStatus],
    materials: list[Material],
    total_candidates: int,
    entity_count: int,
    phrase_eval: list[dict] | None = None,
    chart_news: list[dict] | None = None,
    hotboard: dict | None = None,
) -> str:
    hot = sorted([m for m in materials if m.cls == "热点"], key=lambda m: m.order)
    candidates = [m for m in materials if m.cls == "候选"]
    dropped = sorted([m for m in materials if m.cls == "丢弃"], key=lambda m: -m.mentions)

    lines: list[str] = []
    lines.append(f"# 今日素材雷达 · {date_str}")
    lines.append("")
    lines.append("## 运行概况")
    lines.append("")
    lines.append("| 数据源 | 状态 | 条数 | 可用字段 | 备注 |")
    lines.append("|---|---|---|---|---|")
    for st in statuses:
        fields = ", ".join(st.fields[:6]) if st.fields else "—"
        lines.append(
            f"| {st.id} | {_ICON.get(st.status, '?')} {st.status} | {st.count} | {_cell(fields)} | {_cell(st.note or '—')} |"
        )
    lines.append("")
    lines.append(
        f"采集内容 **{total_candidates}** 条 → 抽出素材实体 **{entity_count}** 个"
        f" → 输出素材卡 **{len(hot)}** 张（候选 {len(candidates)} / 丢弃 {len(dropped)}）"
    )
    lines.append("")
    lines.append(f"生成时间 {generated_at} ｜ 用时 {elapsed_s:.1f}s")
    lines.append("")

    hot_in = [m for m in hot if m.circle == "圈内"]
    hot_out = [m for m in hot if m.circle != "圈内"]

    def _block(title: str, items: list[Material], note: str = "") -> None:
        lines.append(f"## {title}（{len(items)}）")
        lines.append("")
        if note:
            lines.append(f"> {note}")
            lines.append("")
        if not items:
            lines.append("（今日无）")
            lines.append("")
            return
        lines.append("| # | 素材 | 类型 | 可用于 | 主体 | 证据 |")
        lines.append("|---|---|---|---|---|---|")
        for i, m in enumerate(items, 1):
            usage = " / ".join(m.usage_hint) or "—"
            proof = m.reason
            if m.variants:
                proof = f"{proof}｜别名：{'、'.join(m.variants)}"
            if m.bgm_title:
                # 「@xxx创作的原声」不再当占位丢弃，但也不能冒充歌名：
                # 如实标注，让用户自己去平台搜（2026-11-25）
                src = (
                    "作者原声，建议验证"
                    if "创作的原声" in str(m.bgm_title)
                    else ("推断" if m.bgm_source == "inferred" else "接口")
                )
                proof = f"{proof}｜配乐：{m.bgm_title}（{src}）"
            lines.append(
                f"| {i} | **{_cell(m.name)}** | {_cell(m.mtype)} | {_cell(usage)} "
                f"| {_cell(m.artist)} | {_cell(proof)} |"
            )
        lines.append("")

    _block("圈内素材（追星垂直）", hot_in)
    _block(
        "跨圈模板（可套用到追星）",
        hot_out,
        "不是追星圈的内容，但玩法/结构可以套用。门槛比圈内高（≥3 条在用），单日最多 3 条。",
    )

    if hot:
        lines.append("**取用参考**")
        lines.append("")
        for i, m in enumerate(hot, 1):
            links = " ".join(f"[{j + 1}]({u})" for j, u in enumerate(m.links))
            sample = m.samples[0] if m.samples else ""
            proof = count_phrase(m.mtype, m.mentions, m.anchor_mentions, m.circle)
            lines.append(
                f"{i}. **{m.name}**（{m.mtype}）｜{m.artist or '—'}｜{proof}"
                f"{('｜参考：' + sample[:36]) if sample else ''} {links}".rstrip()
            )
    lines.append("")

    # 抖音热榜：文案并进「今日文案」，玩法单列一栏（2026-11-25）。
    # 两处都是「能直接拿去用的句子」，分成两栏等于让用户自己对照。
    wb = [x for x in ((hotboard or {}).get("文案") or []) if x]
    wm = [x for x in ((hotboard or {}).get("玩法") or []) if x]

    # 文案只有一条路：模型加工过的成品。整句聚类已删（2026-11-25）。
    entries = phrase_eval or []

    # 热榜文案里已经在采集结果中出现的，不再重复——采集版带「在用」证据，信息更多
    if entries and wb:
        wb = [t for t in wb if not any(related(t, str(e.get("text") or "")) for e in entries)]

    if entries or wb:
        lines.append(f"## 今日文案（{len(entries) + len(wb)} 条）")
        lines.append("")
        lines.append(
            "> 采集版带「在用」证据，热榜版只有平台热度。"
            "改写过的是按原意补齐的成品，「在用」仍指原句被多少条内容用到。"
        )
        lines.append("")

        if entries:
            lines.append(f"**采集（{len(entries)} 条）**")
            lines.append("")
            for i, e in enumerate(entries, 1):
                lines.append(f"**{i}. {_cell(e['text'], 40)}**")
                lines.append("")
                nums = f"- 在用：{e['videos']} 条"
                if e.get("likes_max"):
                    nums += f"｜最高 {int(e['likes_max']):,} 赞"
                hits = e.get("circle_hits")
                if isinstance(hits, int):
                    nums += "｜跨圈" if hits == 0 else f"｜圈内 {hits}/{e['videos']}"
                days = e.get("days")
                if isinstance(days, int) and days >= 14:
                    nums += "｜常青老梗"
                lines.append(nums)
                if e.get("bgm"):
                    lines.append(f"- 配套：{_cell(e['bgm'], 24)}")
                lines.append("")

        if wb:
            lines.append(f"**热榜（{len(wb)} 条）**")
            lines.append("")
            for i, t in enumerate(wb, 1):
                lines.append(f"{i}. {_cell(t, 60)}")
            lines.append("")

    # 玩法单列：它不是句子，没法并进「今日文案」
    if wm:
        lines.append(f"## 今日玩法（{len(wm)} 条｜抖音热榜）")
        lines.append("")
        lines.append("> 能照着做的形态：变装、转场、卡点、连拍、换装。")
        lines.append("")
        for i, t in enumerate(wm, 1):
            lines.append(f"{i}. {_cell(t, 60)}")
        lines.append("")

    if chart_news:
        lines.append(f"## 今日新歌（{len(chart_news)} 首｜你关注的主体）")
        lines.append("")
        lines.append("> 榜单上的新歌，不占素材卡名额。即使抖音暂无使用记录，新歌本身就是可用的 BGM 素材。")
        lines.append("")
        lines.append("| 歌名 | 歌手 | 排名 |")
        lines.append("|---|---|---|")
        for song in chart_news:
            lines.append(
                f"| **{_cell(song['name'], 24)}** | {_cell(song['artist'], 24)} "
                f"| {song['chart']} #{song['rank']} |"
            )
        lines.append("")


    lines.append(f"## 候选素材（{len(candidates)} 个，证据不足）")
    lines.append("")
    lines.append("> 有具名素材，但被引用次数不足或没有时效证据，先留池观察。")
    lines.append("")
    if candidates:
        lines.append("| 素材 | 类型 | 主体 | 扣下原因 |")
        lines.append("|---|---|---|---|")
        for m in candidates[:20]:
            lines.append(
                f"| {_cell(m.name, 30)} | {_cell(m.mtype)} | {_cell(m.artist)} | {_cell(m.reason)} |"
            )
        if len(candidates) > 20:
            lines.append(f"| … | | | 其余 {len(candidates) - 20} 个见 materials.json |")
    else:
        lines.append("（无）")
    lines.append("")

    if dropped:
        high = [m for m in dropped if m.mentions >= 3]
        title = f"## 被丢弃（{len(dropped)} 张"
        title += f"，其中 {len(high)} 张证据 ≥3 条 ⚠️）" if high else "）"
        lines.append(title)
        lines.append("")
        if high:
            lines.append(
                "> 证据多却被判噪声，多半是噪声词表误伤（2026-11-09 的《SUPERSTAR》就是这样）。"
                "上面这些已按「在用条数」降序，前几条最值得先看。"
            )
            lines.append("")
        lines.append("| 素材 | 类型 | 在用 | 原因 |")
        lines.append("|---|---|---|---|")
        for m in dropped[:12]:
            lines.append(
                f"| {_cell(m.name, 30)} | {_cell(m.mtype)} | {m.mentions} "
                f"| {_cell(m.reason)} |"
            )
        if len(dropped) > 12:
            lines.append(f"| … | | | 其余 {len(dropped) - 12} 张见 dropped.json |")
        lines.append("")

    return "\n".join(lines)
