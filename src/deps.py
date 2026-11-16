"""运行依赖清单：`daily_run` 的跑批预检与 `doctor` 的环境自检共用一份。

2026-11-16 之前这里是两份（`daily_run.ensure_deps` 与 `doctor.check_deps`），
再加上 `requirements.txt` 就是三份。当天 Python 3.13.12→3.13.14 升级丢包，
证明了「三份清单漏改一处」会直接变成「doctor 说没事、跑批却崩」。
现在至少让代码里的两份共用一个来源；`requirements.txt` 仍是安装清单，
由 `scripts/doctor.py` 负责对照（它做真实 import，能发现「装了但坏了」）。

两处检查的深度不同，这是有意的：
- `missing_modules()` 用 find_spec，快，适合跑批前的预检
- `doctor.py` 用真实 import，慢，适合排障（能抓到驱动缺失这类半坏状态）
"""

from __future__ import annotations

# 只列「缺了就跑不起来」的。可选依赖（如 pandas）不要加进来。
REQUIRED_MODULES: tuple[str, ...] = (
    "playwright",
    "httpx",
    "pydantic",
    "yaml",
    "dotenv",
)


def missing_modules() -> list[str]:
    """返回缺失的模块名（空列表 = 齐全）。不抛异常。"""
    import importlib.util

    return [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
