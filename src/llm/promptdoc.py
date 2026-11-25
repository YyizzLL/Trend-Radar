"""把 `CoreAssets/Prompts.md` 解析成运行时可用的提示词。

为什么把提示词搬进文档：
- 改一句话不用碰 Python，也不用担心缩进和转义
- 六个环节摆在一起，能一眼看出判据有没有互相矛盾
- 代码里只剩「拼装」，输入字段和提示词正文分离

解析约定（详见 Prompts.md 的「使用说明」）：

    ## material · 素材理解     ← 层 id 必须是 [a-z_]+，和 json_call(layer=) 一致
    ### system
    ```system
    ...
    ```

围栏识别是**状态机**，不是正则全文扫描：`Prompts.md` 的说明章节里也写着
```system 示例，全文扫描会把示例当成真提示词。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..config import CORE_DIR

DOC_NAME = "Prompts.md"

_FENCE_RE = re.compile(r"^(`{3,})\s*([A-Za-z_]*)\s*$")
_LAYER_RE = re.compile(r"^##\s+([a-z][a-z0-9_]*)\s*(?:·.*)?$")
_BLOCK_RE = re.compile(r"^###\s+(system|user)\s*$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

REQUIRED_BLOCKS = ("system", "user")


def _is_close(line: str, ticks: str) -> bool:
    s = line.strip()
    return s.startswith(ticks) and s.strip("`") == ""


def _parse(text: str) -> dict[str, dict[str, str]]:
    lines = text.splitlines()
    out: dict[str, dict[str, str]] = {}
    layer: str | None = None
    block: str | None = None
    i, n = 0, len(lines)

    while i < n:
        stripped = lines[i].strip()

        fence = _FENCE_RE.match(stripped)
        if fence:
            ticks, info = fence.group(1), fence.group(2)
            j = i + 1
            while j < n and not _is_close(lines[j], ticks):
                j += 1
            if layer and block and info == block:
                out[layer][block] = "\n".join(lines[i + 1 : j]).strip("\n")
            i = j + 1
            continue

        m = _LAYER_RE.match(stripped)
        if m:
            layer, block = m.group(1), None
            out.setdefault(layer, {})
            i += 1
            continue

        m = _BLOCK_RE.match(stripped)
        if m:
            block = m.group(1)
            i += 1
            continue

        i += 1

    return out


def doc_path() -> Path:
    return CORE_DIR / DOC_NAME


@lru_cache(maxsize=1)
def _all() -> dict[str, dict[str, str]]:
    path = doc_path()
    if not path.exists():
        raise FileNotFoundError(f"提示词文档不存在：{path}")
    return _parse(path.read_text(encoding="utf-8"))


def layers() -> list[str]:
    return sorted(_all())


def blocks(layer: str) -> tuple[str, str]:
    """取某层的 (system, user)。缺块直接抛错——宁可启动失败，也不要半套提示词上线。"""
    data = _all().get(layer)
    if data is None:
        raise KeyError(f"提示词文档里没有层 {layer!r}，现有：{layers()}")
    missing = [b for b in REQUIRED_BLOCKS if not data.get(b)]
    if missing:
        raise KeyError(f"层 {layer!r} 缺少块：{missing}")
    return data["system"], data["user"]


def placeholders(layer: str) -> dict[str, set[str]]:
    """某层各块里出现的占位符名，供校验脚本对比。"""
    data = _all().get(layer) or {}
    return {
        b: set(_PLACEHOLDER_RE.findall(data.get(b) or ""))
        for b in REQUIRED_BLOCKS
    }


def render(template: str, *, layer: str = "", **values: object) -> str:
    """单次正则替换，不是 str.format。

    好处：模板里的 JSON 字面量（`{"items": [...]}`）不用写成 `{{...}}`，
    而且注入进去的值即使含花括号也不会被二次解析。
    """
    missing: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in values:
            return str(values[key])
        missing.append(key)
        return m.group(0)

    out = _PLACEHOLDER_RE.sub(_sub, template)
    if missing:
        where = f"层 {layer!r}" if layer else "模板"
        raise KeyError(f"{where} 缺少占位符：{sorted(set(missing))}")
    return out


