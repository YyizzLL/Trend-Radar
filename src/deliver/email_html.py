"""把 Digest 渲染成响应式邮件（HTML + 纯文本）。

邮件客户端的三条硬约束决定了写法：
1. **不能用 flex / grid**：Outlook（Windows）用 Word 引擎渲染，只认表格。
2. **不能依赖外链 CSS**：Gmail 会剥掉 `<head>` 里的大部分样式，必须内联。
3. **media query 只有部分客户端支持**（iOS / Gmail App / Outlook Mobile 支持，Outlook 桌面忽略）。

所以采用「表格打底 + 移动端堆叠」：
- 默认是两列表格（PC 上信息密度高）
- `@media (max-width:600px)` 把单元格改成 `display:block`，变成单列
- 被忽略 media query 的客户端只会看到表格版，不会错乱

另外 Gmail 会在 **102KB** 处截断，所以末尾有体积保护。
"""

from __future__ import annotations

import html
from typing import Any

from ..report.evidence import count_phrase
from .digest import Digest

# 配色：浅色底 + 深色字，避免深色模式反转后对比度不足
BG = "#f4f5f7"
CARD = "#ffffff"
TEXT = "#1f2329"
MUTED = "#8a8f99"
LINE = "#eceef2"
ACCENT = "#e5484d"      # 圈内强调色
ACCENT2 = "#2f6fed"     # 跨圈 / 链接
WARN = "#b26a00"

MAX_BYTES = 95_000      # 留 7KB 余量给邮件头与编码


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _badge(text: str, color: str = MUTED) -> str:
    return (
        f'<span style="display:inline-block;padding:1px 6px;margin-left:6px;'
        f'font-size:11px;line-height:16px;color:{color};border:1px solid {color};'
        f'border-radius:3px;vertical-align:middle">{_e(text)}</span>'
    )


def _link(url: str, label: str) -> str:
    return (
        f'<a href="{_e(url)}" target="_blank" '
        f'style="color:{ACCENT2};text-decoration:none;font-size:13px">{_e(label)}</a>'
    )


def _section(title: str, count: int, body: str, note: str = "") -> str:
    head = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse"><tr>'
        f'<td style="padding:22px 0 8px;border-bottom:2px solid {LINE};text-align:left">'
        f'<span style="font-size:16px;font-weight:700;color:{TEXT}">{_e(title)}</span>'
        f'<span style="font-size:12px;color:{MUTED};margin-left:8px">{count} 条</span>'
        f"</td></tr></table>"
    )
    note_html = (
        f'<div style="font-size:12px;color:{MUTED};padding:6px 0 0">{_e(note)}</div>'
        if note
        else ""
    )
    return head + note_html + body


def _empty(text: str) -> str:
    return f'<div style="padding:14px 0;font-size:13px;color:{MUTED}">{_e(text)}</div>'


def _material_block(items: list[dict[str, Any]], accent: str) -> str:
    if not items:
        return _empty("今日无")
    rows: list[str] = []
    for i, m in enumerate(items, 1):
        name = _e(m["name"])
        badge = _badge(m["mtype"], accent)
        artist = (
            f'<div style="font-size:12px;color:{MUTED};padding-top:3px">'
            f'主体 {_e(m["artist"])}</div>'
            if m.get("artist")
            else ""
        )
        proof = _proof(m)
        alias = ""
        if m.get("variants"):
            alias = (
                f'<div style="font-size:12px;color:{MUTED};padding-top:2px">'
                f"别名 {_e('、'.join(m['variants']))}</div>"
            )
        bgm = ""
        if m.get("bgm"):
            # 「@xxx创作的原声」不再当占位丢掉，但也不能冒充歌名：
            # 如实告诉用户这是作者上传的音频，让他自己去平台搜（2026-11-25）
            src = (
                "作者原声，建议验证"
                if "创作的原声" in str(m.get("bgm"))
                else ("推断" if m.get("bgm_source") == "inferred" else "接口")
            )
            bgm = (
                f'<div style="font-size:12px;color:{MUTED};padding-top:2px">'
                f"配乐 {_e(m['bgm'])}（{src}）</div>"
            )
        left = (
            f'<div style="font-size:15px;font-weight:700;color:{TEXT};line-height:1.4">'
            f"{i}. {name}{badge}</div>{artist}"
        )
        right = (
            f'<div style="font-size:13px;color:{TEXT}">{_e(proof)}</div>{alias}{bgm}'
        )
        rows.append(
            f'<tr><td class="cell" width="58%" style="padding:10px 8px 10px 0;'
            f'vertical-align:top">{left}</td>'
            f'<td class="cell r" width="42%" align="right" style="padding:10px 0;'
            f'vertical-align:top">{right}</td></tr>'
            f'<tr><td colspan="2" style="padding:0;border-bottom:1px solid {LINE};'
            f'font-size:0;line-height:0">&nbsp;</td></tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse">{"".join(rows)}</table>'
    )


def _proof(m: dict[str, Any]) -> str:
    return count_phrase(
        str(m.get("mtype") or ""),
        int(m.get("mentions") or 0),
        int(m.get("anchor_mentions") or 0),
        str(m.get("circle") or ""),
        short=True,
    )


def _refs_block(refs: list[dict[str, Any]]) -> str:
    if not refs:
        return _empty("今日无")
    rows: list[str] = []
    for i, r in enumerate(refs, 1):
        links = " &nbsp;".join(
            _link(url, f"看{j}") for j, url in enumerate(r["links"], 1)
        )
        rows.append(
            f'<tr><td class="cell" style="padding:8px 0;border-bottom:1px solid {LINE};'
            f'font-size:14px;color:{TEXT}">'
            f'<span style="font-weight:600">{i}. {_e(r["name"])}</span>'
            f'<span style="color:{MUTED};font-size:12px">（{_e(r["mtype"])}）</span>'
            f'<div style="padding-top:4px">{links}</div></td></tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse">{"".join(rows)}</table>'
    )


def _play_block(items: list[str]) -> str:
    """今日玩法：热榜里能照着做的形态。文案已并进「今日文案」，这里只放玩法。"""
    items = [x for x in (items or []) if x]
    if not items:
        return _empty("今日热榜没有可用玩法")
    rows = "".join(
        f'<div style="font-size:14px;color:{TEXT};line-height:1.75;padding:1px 0">'
        f"{i}. {_e(x)}</div>"
        for i, x in enumerate(items, 1)
    )
    return rows


def _text_block(entries: list[dict[str, Any]], hot_copy: list[str] | None = None) -> str:
    """今日文案：采集成品 + 热榜句子，合成一栏，两组分开。

    采集版带「在用 N 条」这类证据，热榜版只有平台排序——两者信息量不同，
    所以不混排，但放在同一栏里，用户不用来回对照（2026-11-25）。
    """
    hot_copy = [t for t in (hot_copy or []) if t]
    if not entries and not hot_copy:
        return _empty("今日没有可用的文案")

    def _label(text: str) -> str:
        return (
            f'<div style="font-size:12px;color:{MUTED};padding:10px 0 2px">{text}</div>'
        )

    parts: list[str] = []
    if entries:
        parts.append(_label(f"采集（{len(entries)} 条）"))
    for i, e in enumerate(entries, 1):
        videos = int(e.get("videos") or 0)
        nums = f"在用 {videos} 条"
        nums += f" ｜ 最高 {int(e.get('likes_max') or 0):,} 赞"
        hits = e.get("circle_hits")
        if isinstance(hits, int):
            nums += " ｜ 跨圈" if hits == 0 else f" ｜ 圈内 {hits}/{videos}"
        days = e.get("days")
        if isinstance(days, int) and days >= 14:
            nums += " ｜ 常青老梗"

        extra = ""
        if e.get("bgm"):
            extra += (
                f'<div style="font-size:11px;color:{MUTED};padding-top:3px">'
                f'配套 {_e(e["bgm"])}</div>'
            )
        parts.append(
            f'<div style="padding:12px 0;border-bottom:1px solid {LINE}">'
            f'<div style="font-size:15px;font-weight:700;line-height:1.5;color:{TEXT}">'
            f'{i}. 「{_e(e.get("text"))}」</div>'
            f'<div style="font-size:12px;color:{MUTED};padding-top:3px">{nums}</div>'
            f"{extra}</div>"
        )

    if hot_copy:
        parts.append(_label(f"热榜（{len(hot_copy)} 条）"))
        parts.append(
            "".join(
                f'<div style="font-size:14px;color:{TEXT};line-height:1.6;padding:2px 0">'
                f"{i}. {_e(x)}</div>"
                for i, x in enumerate(hot_copy, 1)
            )
        )
    return "".join(parts)


def _song_table(news: list[dict[str, Any]]) -> str:
    if not news:
        return _empty("今日无你关注主体的新歌")
    rows: list[str] = []
    for s in news:
        rows.append(
            f'<tr>'
            f'<td class="cell" style="padding:8px 0;border-bottom:1px solid {LINE};'
            f'font-size:14px;font-weight:600;color:{TEXT}">{_e(s.get("name"))}</td>'
            f'<td class="cell" style="padding:8px 0;border-bottom:1px solid {LINE};'
            f'font-size:13px;color:{MUTED}">{_e(s.get("artist"))}</td>'
            f'<td class="cell r" align="right" style="padding:8px 0;'
            f'border-bottom:1px solid {LINE};font-size:12px;color:{ACCENT}">'
            f'{_e(s.get("chart"))} #{int(s.get("rank") or 0)}</td>'
            f'</tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse">{"".join(rows)}</table>'
    )


def _candidate_table(cands: list[dict[str, Any]]) -> str:
    if not cands:
        return _empty("今日无")
    rows: list[str] = []
    for i, c in enumerate(cands, 1):
        rows.append(
            f'<tr><td class="cell" width="44%" style="padding:8px 8px 8px 0;text-align:left;'
            f'border-bottom:1px solid {LINE};vertical-align:top;font-size:13px;'
            f'color:{TEXT}"><span style="font-weight:600">{i}. {_e(c.get("name"))}</span>'
            f'<span style="color:{MUTED}">（{_e(c.get("mtype"))}）</span></td>'
            f'<td class="cell r" width="56%" style="padding:8px 0;'
            f'border-bottom:1px solid {LINE};vertical-align:top;font-size:12px;'
            f'color:{MUTED}">{_e(c.get("reason"))}</td></tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse">{"".join(rows)}</table>'
    )


def _summary(d: Digest) -> str:
    c = d.counts
    cells = [
        ("圈内素材", c["circle"], ACCENT),
        ("跨圈模板", c["cross"], ACCENT2),
        ("今日新歌", c["chart_news"], TEXT),
        ("今日文案", d.counts.get("text", len(d.text_entries)), TEXT),
    ]
    tds = "".join(
        f'<td class="cell" width="25%" align="center" style="padding:12px 4px">'
        f'<div style="font-size:22px;font-weight:700;color:{color};line-height:1.2">'
        f"{num}</div>"
        f'<div style="font-size:12px;color:{MUTED};padding-top:2px">{_e(label)}</div>'
        f"</td>"
        for label, num, color in cells
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;background:#fafbfc;border:1px solid {LINE};'
        f'border-radius:6px"><tr>{tds}</tr></table>'
    )


def _sources_line(d: Digest) -> str:
    if not d.sources:
        return ""
    parts = []
    for s in d.sources:
        icon = {"ok": "●", "failed": "✕", "skipped": "○"}.get(str(s.get("status")), "○")
        color = {"ok": "#1a7f37", "failed": ACCENT}.get(str(s.get("status")), MUTED)
        parts.append(
            f'<span style="color:{color};font-size:11px">{icon}</span> '
            f'<span style="font-size:11px;color:{MUTED}">{_e(s.get("id"))} '
            f'{int(s.get("count") or 0)}</span>'
        )
    return (
        '<div style="padding-top:10px;line-height:1.9">' + " &nbsp; ".join(parts) + "</div>"
    )


def _notes(d: Digest) -> str:
    if not d.notes:
        return ""
    items = "".join(
        f'<div style="font-size:12px;color:{WARN};padding-top:4px">· {_e(n)}</div>'
        for n in d.notes
    )
    return (
        f'<div style="margin-top:14px;padding:10px 12px;background:#fff8e6;'
        f'border-left:3px solid {WARN};border-radius:3px">{items}</div>'
    )


def render_html(d: Digest, *, limits: dict[str, int] | None = None) -> str:
    """渲染完整 HTML。超体积时优先砍候选区，保证不被 Gmail 截断。"""
    html_doc = _render(d)
    if len(html_doc.encode("utf-8")) <= MAX_BYTES:
        return html_doc

    for cut in (5, 0):
        slim = Digest(**{**d.__dict__, "candidates": d.candidates[:cut]})
        slim.notes = d.notes + ([f"候选素材过多，邮件内仅显示前 {cut} 条"] if cut else ["候选素材未在邮件内展示"])
        html_doc = _render(slim)
        if len(html_doc.encode("utf-8")) <= MAX_BYTES:
            return html_doc
    return html_doc


def _render(d: Digest) -> str:
    hb = d.hotboard or {}
    hot_copy = d.hot_copy
    hot_play = [x for x in (hb.get("玩法") or []) if x]

    body = "".join(
        [
            _section("圈内素材（追星垂直）", len(d.circle), _material_block(d.circle, ACCENT)),
            _section(
                "跨圈模板（可套用到追星）",
                len(d.cross),
                _material_block(d.cross, ACCENT2),
                note="不是追星圈内容，但玩法可以套用；门槛 ≥3 条在用，单日最多 3 条。",
            ),
            _section("取用参考", len(d.refs), _refs_block(d.refs)),
            _section(
                "今日文案",
                len(d.text_entries) + len(hot_copy),
                _text_block(d.text_entries, hot_copy),
                note="采集版带「在用」证据，热榜版只有平台热度。",
            ) if (d.text_entries or hot_copy) else "",
            _section(
                "今日玩法（抖音热榜）",
                len(hot_play),
                _play_block(hot_play),
                note="能照着做的形态：变装、转场、卡点、连拍、换装。",
            ) if hot_play else "",
            _section("今日新歌（你关注的主体）", len(d.chart_news), _song_table(d.chart_news)),
            _section(
                "候选素材",
                len(d.candidates),
                _candidate_table(d.candidates),
                note="证据不足或配额所限，留池观察；按引用次数排序。",
            ),
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<title>追星二创雷达 {_e(d.date)}</title>
<style>
  body {{ margin:0; padding:0; }}
  table {{ border-collapse:collapse; }}
  @media only screen and (max-width:600px) {{
    .wrap {{ width:100% !important; }}
    .cell {{ display:block !important; width:100% !important; box-sizing:border-box; }}
    .r {{ text-align:left !important; padding-top:2px !important; }}
    .pad {{ padding:0 14px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">
{d.date} 圈内 {d.counts['circle']} 张 · 跨圈 {d.counts['cross']} 张 · 新歌 {d.counts['chart_news']} 首
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}">
<tr><td align="center" style="padding:18px 10px">
  <table role="presentation" class="wrap" width="640" cellpadding="0" cellspacing="0"
         style="width:640px;max-width:640px;background:{CARD};border-radius:8px;
                text-align:left;box-shadow:0 1px 3px rgba(0,0,0,.06)">
    <tr><td class="pad" style="padding:22px 24px 0">
      <div style="font-size:12px;letter-spacing:1px;color:{ACCENT};font-weight:700">
        DAILY RADAR
      </div>
      <div style="font-size:22px;font-weight:700;color:{TEXT};padding-top:4px;line-height:1.3">
        追星二创素材雷达 · {_e(d.date)}
      </div>
      <div style="font-size:12px;color:{MUTED};padding-top:6px">
        采集 {d.stats.get('content', 0)} 条内容 → 素材卡 {d.stats.get('materials', 0)} 张
        ｜生成于 {_e(d.generated_at)}｜用时 {d.elapsed_s:.1f}s
      </div>
    </td></tr>
    <tr><td class="pad" style="padding:14px 24px 0">{_summary(d)}</td></tr>
    <tr><td class="pad" style="padding:0 24px">{body}</td></tr>
    <tr><td class="pad" style="padding:18px 24px 24px">
      {_sources_line(d)}
      {_notes(d)}
      <div style="padding-top:14px;border-top:1px solid {LINE};margin-top:14px;
                  font-size:11px;color:{MUTED};line-height:1.7">
        由本地管线自动生成（抖音搜索 + 热榜 + QQ音乐榜单 + B站交叉验证）。<br>
        模板/挑战卡的「N 条在用」是视频数量；BGM 卡的「N 条提到」只是提到歌名，不等于使用量。
      </div>
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


def render_text(d: Digest) -> str:
    """纯文本版：老客户端、转发、复制都靠它。"""
    lines: list[str] = [
        f"追星二创素材雷达 · {d.date}",
        f"采集 {d.stats.get('content', 0)} 条 → 素材卡 {d.stats.get('materials', 0)} 张"
        f"｜生成 {d.generated_at}｜用时 {d.elapsed_s:.1f}s",
        "",
    ]

    def _materials(title: str, items: list[dict[str, Any]]) -> None:
        lines.append(f"== {title}（{len(items)}）==")
        if not items:
            lines.append("（今日无）")
        for i, m in enumerate(items, 1):
            head = f"{i}. {m['name']}（{m['mtype']}）"
            if m.get("artist"):
                head += f"｜主体 {m['artist']}"
            lines.append(head)
            line = f"   {_proof(m)}"
            if m.get("variants"):
                line += f"｜别名 {'、'.join(m['variants'])}"
            if m.get("bgm"):
                src = (
                    "作者原声，建议验证"
                    if "创作的原声" in str(m.get("bgm"))
                    else ("推断" if m.get("bgm_source") == "inferred" else "接口")
                )
                line += f"｜配乐 {m['bgm']}（{src}）"
            lines.append(line)
        lines.append("")

    _materials("圈内素材（追星垂直）", d.circle)
    _materials("跨圈模板（可套用到追星）", d.cross)

    lines.append(f"== 取用参考（{len(d.refs)}）==")
    for i, r in enumerate(d.refs, 1):
        lines.append(f"{i}. {r['name']}（{r['mtype']}）")
        for j, url in enumerate(r["links"], 1):
            lines.append(f"   看{j}: {url}")
    if not d.refs:
        lines.append("（今日无）")
    lines.append("")

    hb = d.hotboard or {}
    hot_copy = d.hot_copy
    hot_play = [x for x in (hb.get("玩法") or []) if x]

    if d.text_entries or hot_copy:
        lines.append(f"== 今日文案（{len(d.text_entries) + len(hot_copy)}）==")
        if d.text_entries:
            lines.append("[采集]")
            for i, e in enumerate(d.text_entries, 1):
                nums = f"{int(e.get('videos') or 0)} 条"
                hits = e.get("circle_hits")
                src_note = ""
                if isinstance(hits, int):
                    src_note = " · 跨圈" if hits == 0 else f" · 圈内 {hits} 条"
                days = e.get("days")
                if isinstance(days, int) and days >= 14:
                    src_note += " · 常青老梗"
                lines.append(f"{i}. 「{e.get('text')}」{nums}{src_note}")
                if e.get("bgm"):
                    lines.append(f"   配套：{e['bgm']}")
        if hot_copy:
            lines.append("[热榜]")
            for i, x in enumerate(hot_copy, 1):
                lines.append(f"  {i}. {x}")
        lines.append("")

    if hot_play:
        lines.append(f"== 今日玩法（抖音热榜，{len(hot_play)}）==")
        for i, x in enumerate(hot_play, 1):
            lines.append(f"{i}. {x}")
        lines.append("")

    lines.append(f"== 今日新歌（{len(d.chart_news)}）==")
    for s in d.chart_news:
        lines.append(f"- {s.get('name')} / {s.get('artist')}（{s.get('chart')} #{int(s.get('rank') or 0)}）")
    if not d.chart_news:
        lines.append("（今日无）")
    lines.append("")

    lines.append(f"== 候选素材（显示 {len(d.candidates)} 条）==")
    for i, c in enumerate(d.candidates, 1):
        lines.append(f"{i}. {c.get('name')}（{c.get('mtype')}）｜{c.get('reason')}")
    if not d.candidates:
        lines.append("（今日无）")

    if d.notes:
        lines.append("")
        lines.append("== 备注 ==")
        lines.extend(f"- {n}" for n in d.notes)

    lines.append("")
    lines.append("模板/挑战「N 条在用」是视频数；BGM「N 条提到」只是提到歌名，不等于使用量。")
    return "\n".join(lines)
