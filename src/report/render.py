"""Markdown 日报渲染：输出的是「素材卡」，不是「视频标题」。"""

from __future__ import annotations

from ..models import Material, SourceStatus
from ..normalize.cluster import CaptionCluster
from .evidence import count_phrase
from .textmerge import merge as merge_text

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
    clusters: list[CaptionCluster] | None = None,
    phrases: list[dict] | None = None,
    phrase_eval: list[dict] | None = None,
    chart_news: list[dict] | None = None,
) -> str:
    hot = sorted([m for m in materials if m.cls == "热点"], key=lambda m: m.order)
    candidates = [m for m in materials if m.cls == "候选"]
    clusters = clusters or []
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
            f"| {st.id} | {_ICON.get(st.status, '?')} {st.status} | {st.count} | {fields} | {st.note or '—'} |"
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
                src = "推断" if m.bgm_source == "inferred" else "接口"
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

    # 文案两栏合并：整句簇（模板）与短语（可用/观察）按相似度对齐后只出一条。
    # 两个数都保留：`整句` 是几乎一字不差的条数，`在用` 是提到这句话的内容数。
    cluster_dicts = [
        {
            "rep": c.rep, "size": c.size, "likes_max": c.likes_max,
            "likes_median": c.likes_median, "tags": c.tags,
            "variants": c.variants, "members": c.members,
        }
        for c in clusters
    ]
    entries = merge_text(cluster_dicts, phrase_eval or []) if phrase_eval else []

    if entries:
        usable = [e for e in entries if e.get("use") == "use"]
        watch = [e for e in entries if e.get("use") == "watch"]
        lines.append(f"## 今日文案（{len(usable) + len(watch)} 条｜可直接用 {len(usable)} 条）")
        lines.append("")
        lines.append(
            "> 「在用」是提到这句话的内容数，「整句」是几乎一字不差照抄的条数。"
            "两个数差得越多，说明大家越爱改着写。"
        )
        lines.append("")
        if not usable:
            lines.append("> 今日没有判断为「可直接套用」的句子。下面「观察中」有需要改写的候选。")
            lines.append("")
        for i, e in enumerate(usable, 1):
            lines.append(f"**{i}. {_cell(e['text'], 40)}**")
            lines.append("")
            nums = f"- 在用：{e['videos']} 条"
            if e.get("size"):
                nums += f"（整句 {e['size']}）"
            if e.get("likes_max"):
                nums += f"｜最高 {int(e['likes_max']):,} 赞"
            hits = e.get("circle_hits")
            if isinstance(hits, int):
                nums += "｜跨圈" if hits == 0 else f"｜圈内 {hits}/{e['videos']}"
            days = e.get("days")
            if isinstance(days, int) and days >= 14:
                nums += "｜常青老梗"
            lines.append(nums)
            if e.get("usage"):
                lines.append(f"- 怎么用：{_cell(e['usage'], 40)}")
            pair = "｜".join(x for x in (
                f"出处：{_cell(e.get('source') or '', 20)}" if e.get("source") else "",
                f"配套：{_cell(e.get('bgm') or '', 24)}" if e.get("bgm") else "",
            ) if x)
            if pair:
                lines.append(f"- {pair}")
            tags = " ".join(f"#{t}" for t in (e.get("tags") or [])[:5])
            if tags:
                lines.append(f"- 标签：{tags}")
            vs = [v for v in dict.fromkeys(e.get("variants") or []) if v and v != e["text"]]
            if vs:
                lines.append("- 变体：" + "；".join(_cell(v, 24) for v in vs[:4]))
            links = " ".join(
                f"[{j + 1}]({m['url']})"
                for j, m in enumerate(e.get("members") or [])
                if isinstance(m, dict) and m.get("url")
            )
            if links:
                lines.append(f"- 参考：{links}")
            lines.append("")

        if watch:
            lines.append(f"**观察中（{len(watch)} 条｜需要改写或只适合特定画面）**")
            lines.append("")
            for e in watch:
                note = e.get("usage") or ""
                lines.append(
                    f"- 「{_cell(e['text'], 26)}」{e['videos']} 条"
                    + (f" — {_cell(note, 40)}" if note else "")
                )
            lines.append("")

    elif clusters:
        lines.append(f"## 今日文案模板（{len(clusters)} 条）")
        lines.append("")
        lines.append("> 同一句文案被多条视频复制。常为歌词，标签里可能带歌名；可去抖音看它们配的 BGM/滤镜。")
        lines.append("")
        for i, c in enumerate(clusters[:8], 1):
            tags = " ".join(f"#{t}" for t in c.tags[:5])
            lines.append(f"**{i}. {_cell(c.rep, 40)}**")
            lines.append("")
            lines.append(
                f"- 规模：{c.size} 条 / 最高 {int(c.likes_max):,} 赞 / 中位 {int(c.likes_median):,}"
            )
            if tags:
                lines.append(f"- 相关标签：{tags}")
            if c.variants:
                uniq = [v for v in c.variants[1:4] if v != c.rep]
                if uniq:
                    lines.append("- 变体：" + "；".join(_cell(v, 30) for v in uniq))
            links = " ".join(
                f"[{j + 1}]({m['url']})" for j, m in enumerate(c.members[:3]) if m["url"]
            )
            if links:
                lines.append(f"- 参考：{links}")
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

    if not entries and not clusters and phrases:
        # 没有模型评估、也没有整句簇：退回原始短语清单，别让这一栏空着
        lines.append(f"## 复用短语（{len(phrases)} 个｜文案梗线索）")
        lines.append("")
        lines.append("> 被多条不同视频共同使用，可能是正在传的文案梗。不直接进热点，供人工判断。")
        lines.append("")
        lines.append("| 短语 | 视频数 | 最高赞 | 示例文案 |")
        lines.append("|---|---|---|---|")
        for p in phrases:
            lines.append(
                f"| **{_cell(p['phrase'], 16)}** | {p['videos']} | "
                f"{int(p['likes_max']):,} | {_cell(p.get('sample', ''), 34)} |"
            )
        lines.append("")

    elif not entries and not clusters:
        lines.append("## 复用短语（0 个｜文案梗线索）")
        lines.append("")
        lines.append(
            "> 今日未发现被 ≥3 条不同视频共同使用的短句。"
            "这一步能抓到「半句相同、后半句各写各的」的变体，整句聚类抓不到。"
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
