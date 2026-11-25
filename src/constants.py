"""全项目共用的常量。

这些表原来各有两份（聚合层与投递层各写一遍），改一处忘另一处就会让「日报排序」
和「邮件排序」不一致。统一放在这里，谁要谁 import。
"""

from __future__ import annotations

TYPE_USAGE: dict[str, list[str]] = {
    "BGM": ["卡点", "挑战拍摄", "配乐"],
    "模板": ["套模板", "同款翻拍"],
    "挑战": ["参与挑战", "套用玩法"],
}

# 排序兜底用：同分时 BGM → 模板 → 挑战
TYPE_RANK: dict[str, int] = {"BGM": 0, "模板": 1, "挑战": 2}

# 采集进程的退出码。
#
# 这里是**唯一定义处**：`collect_douyin.py` 用它返回，`daily_run.py` 用它分支。
# 2026-11-16 之前 3 被三种情况共用（验证码 / 连不上 Edge / 登录失效），
# 而 daily_run 靠字符串 "exit=3" 猜语义，于是「重启 Edge 续采」那条恢复路径
# 永远走不到。别再把新的失败类型塞进同一个码。
EXIT_VERIFY = 3    # 人机验证：换会话（重启 Edge）可能过，换进程没用
EXIT_PAGE = 4      # 页签 / CDP 会话恢复失败：换进程 --resume 可续
EXIT_EDGE = 5      # 连不上 127.0.0.1:9222：重启 Edge 可救
EXIT_LOGIN = 6     # 登录态失效：需要重新扫码
EXIT_STALLED = 7   # 静默超时（N 分钟没有任何输出）：已杀进程，可 --resume
EXIT_NO_PLAN = 8   # 没有检索计划：今天还没做侦察，重试没有意义

# 需要人工介入的退出码：重试只会再等一轮，直接停。
# EXIT_VERIFY 不在里面——它先由 daily_run 自动重启会话试几次，仍不行才转人工。
# EXIT_NO_PLAN 也不在里面：它不是登录问题，daily_run 单独给提示。
EXIT_NEEDS_HUMAN = frozenset({EXIT_LOGIN})

