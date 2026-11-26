"""把一次运行目录整理成「邮件摘要」需要的结构化数据。

为什么单独一层：
`report.md` 是给人看的排版，`materials.json` 只有素材本身；
文案簇 / 复用短语 / 今日新歌原本只在内存里，所以管线额外写了 `report_data.json`。
这一层负责把三者合并、截断到投递要的条数，让渲染层只管排版。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..constants import TYPE_RANK
from ..report.textmerge import related

DEFAULT_LIMITS = {
    "circle": 8,          # 圈内素材
    "cross": 3,           # 跨圈模板
    "refs_per_material": 3,
    "chart_news": 8,      # 今日新歌
    "phrase_eval": 6,     # 可用文案（模型评估过的）
    "candidates": 10,     # 候选素材
}


@dataclass
class Digest:
    date: str
    generated_at: str
    elapsed_s: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    circle: list[dict[str, Any]] = field(default_factory=list)
    cross: list[dict[str, Any]] = field(default_factory=list)
    refs: list[dict[str, Any]] = field(default_factory=list)
    chart_news: list[dict[str, Any]] = field(default_factory=list)
    # 模型评估过的文案：每项含 phrase / use / usage / source / bgm
    phrase_eval: list[dict[str, Any]] = field(default_factory=list)
    # 合并后的「今日文案」：整句簇 + 短语对齐后每条只出现一次（见 report/textmerge）
    text_entries: list[dict[str, Any]] = field(default_factory=list)
    # 抖音热榜热梗：{文案: [...], 玩法: [...], drops: [...]}
    # 平台排过序的当天内容，原始直出，不做二次判断（2026-11-25）
    hotboard: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "circle": len(self.circle),
            "cross": len(self.cross),
            "chart_news": len(self.chart_news),
            "phrase_eval": len(self.phrase_eval),
            "candidates": len(self.candidates),
            # 文案总数 = 采集成品 + 去重后的热榜句。摘要卡片和正文都用这个数。
            "text": len(self.text_entries) + len(self.hot_copy),
        }

    @property
    def hot_copy(self) -> list[str]:
        """热榜文案里不与采集成品重复的那些（采集优先，信息更多）。

        三处渲染（Markdown / HTML / 纯文本）都读这里，避免各算一遍。
        """
        hot = [x for x in ((self.hotboard or {}).get("文案") or []) if x]
        if self.text_entries and hot and hot:
            hot = [
                t for t in hot
                if not any(related(t, str(e.get("text") or "")) for e in self.text_entries)
            ]
        return hot


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def latest_run(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    dirs = [p for p in runs_dir.iterdir() if p.is_dir() and (p / "materials.json").exists()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.name)


def latest_run_for_date(runs_dir: Path, date: str) -> Path | None:
    """取指定日期（YYYY-MM-DD）最新一轮，供「当天已跑过」时补发邮件。"""
    stamp = date.replace("-", "")
    if not runs_dir.exists():
        return None
    dirs = [
        p for p in runs_dir.iterdir()
        if p.is_dir() and p.name.startswith(stamp) and (p / "materials.json").exists()
    ]
    return max(dirs, key=lambda p: p.name) if dirs else None


def _material_row(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": m.get("name", ""),
        "mtype": m.get("mtype", ""),
        "artist": m.get("artist", ""),
        "mentions": int(m.get("mentions") or 0),
        "anchor_mentions": int(m.get("anchor_mentions") or 0),
        "circle": m.get("circle", ""),
        "reason": m.get("reason", ""),
        "bgm": m.get("bgm_title", ""),
        "bgm_source": m.get("bgm_source", ""),
        "links": list(m.get("links") or [])[:3],
        "variants": list(m.get("variants") or []),
    }


def build(run_dir: Path, limits: dict[str, int] | None = None) -> Digest:
    lim = dict(DEFAULT_LIMITS)
    if limits:
        # 支持 phrases/phrase_eval 别名兼容
        parsed = dict(limits)
        if "phrases" in parsed and "phrase_eval" not in parsed:
            parsed["phrase_eval"] = parsed["phrases"]
        lim.update({k: int(v) for k, v in parsed.items() if k in lim})

    materials = _read(run_dir / "materials.json", [])
    meta = _read(run_dir / "meta.json", {})
    extra = _read(run_dir / "report_data.json", {})

    hot = [m for m in materials if m.get("cls") == "热点"]
    hot.sort(key=lambda m: int(m.get("order") or 0))
    circle = [_material_row(m) for m in hot if m.get("circle") == "圈内"][: lim["circle"]]
    cross = [_material_row(m) for m in hot if m.get("circle") != "圈内"][: lim["cross"]]

    refs: list[dict[str, Any]] = []
    for m in hot:
        links = list(m.get("links") or [])[: lim["refs_per_material"]]
        if not links:
            continue
        refs.append(
            {
                "name": m.get("name", ""),
                "mtype": m.get("mtype", ""),
                "artist": m.get("artist", ""),
                "links": links,
            }
        )

    # 候选：按证据强弱排，而不是按内部列表顺序
    candidates = [m for m in materials if m.get("cls") == "候选"]
    candidates.sort(
        key=lambda m: (
            -int(m.get("mentions") or 0),
            TYPE_RANK.get(str(m.get("mtype") or ""), 9),
            str(m.get("name") or ""),
        )
    )
    cand_rows = [
        {
            "name": m.get("name", ""),
            "mtype": m.get("mtype", ""),
            "mentions": int(m.get("mentions") or 0),
            "reason": m.get("reason", ""),
        }
        for m in candidates[: lim["candidates"]]
    ]

    chart_news = list(extra.get("chart_news") or [])[: lim["chart_news"]]
    # 评估过的全带上：模型给的是成品，没有「用不了」的混在里面
    phrase_eval = list(extra.get("phrase_eval") or [])[: lim["phrase_eval"]]

    # 只收 delivered（模型给过成品）：没有成品的条目不该冒充文案
    text_entries = [
        e for e in (extra.get("phrase_eval") or []) if e.get("delivered")
    ][: lim["phrase_eval"]]

    notes: list[str] = []
    failed = [s for s in meta.get("sources", []) if s.get("status") == "failed"]
    if failed:
        notes.append("数据源异常：" + "、".join(str(s.get("id")) for s in failed))

    # 抖音只覆盖了一部分查询时，日报必须自己说明不完整——
    # 早期版本靠 note 里有没有「失败」二字判断，而 note 从来不含这两个字，提示永远不出现。
    for src in meta.get("sources", []):
        if src.get("id") != "douyin_search":
            continue
        detail = src.get("detail") or {}
        planned = int(detail.get("queries_planned") or 0)
        ok_q = int(detail.get("queries_ok") or 0)
        if planned and ok_q < planned:
            notes.append(
                f"抖音采集仅覆盖 {ok_q}/{planned} 个查询"
                f"（{planned - ok_q} 个失败或未采完），今日结果可能不完整"
            )

    return Digest(
        date=str(meta.get("date") or ""),
        generated_at=str(meta.get("generated_at") or ""),
        elapsed_s=float(meta.get("elapsed_s") or 0),
        stats={
            "content": int(meta.get("candidates") or 0),
            "materials": sum(1 for m in materials if m.get("cls") == "热点"),
            "candidates": len(candidates),
        },
        sources=list(meta.get("sources") or []),
        circle=circle,
        cross=cross,
        refs=refs,
        chart_news=chart_news,
        phrase_eval=phrase_eval,
        text_entries=text_entries,
        hotboard=dict(extra.get("hotboard") or {}),
        candidates=cand_rows,
        notes=notes,
    )


def subject_line(d: Digest) -> str:
    c = d.counts
    parts = [
        f"圈内{c['circle']}",
        f"跨圈{c['cross']}",
        f"新歌{c['chart_news']}",
    ]
    # 文案数 = 采集成品 + 热榜句子（去重后），见 Digest.hot_copy
    usable = c["text"]
    if usable:
        parts.append(f"文案{usable}")
    return f"【追星二创雷达】{d.date[5:] if d.date else ''}｜" + " ".join(parts)
