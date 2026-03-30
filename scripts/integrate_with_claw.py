#!/usr/bin/env python3
"""
Memoria integrate_with_claw.py — 自动集成脚本

功能：
  1. 更新 AGENTS.md — 注入记忆检索步骤
  2. 更新 SOUL.md — 注入 Memoria 系统说明

多 Claw 兼容：
  - 通过 WORKSPACE 环境变量指定目标 workspace 路径
  - 默认 ~/.qclaw/workspace（当前 Claw）
  - 其他 Claw 可设置 WORKSPACE=/path/to/other/claw/workspace

幂等执行：多次运行结果一致。
"""

import os
from pathlib import Path


def resolve_workspace() -> Path:
    custom = os.environ.get("WORKSPACE", "").strip()
    if custom:
        return Path(os.path.expanduser(custom))
    return Path.home() / ".qclaw/workspace"


WORKSPACE = resolve_workspace()

RECALL_CMD = "python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5 --simple"

AGENTS_INJECT = f"""
5. **执行记忆检索：** `{RECALL_CMD}`，将结果注入上下文（Memoria 记忆系统）
"""

SOUL_INJECT = """
## 记忆系统（Memoria）

我使用 **Memoria** 作为个人知识库。

**检索方式：**
- 获取摘要：`python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5 --simple`
- 获取全量：`python3 ~/.qclaw/skills/memoria/scripts/recall.py --id <记忆ID> --full`
- 写入记忆：`python3 ~/.qclaw/skills/memoria/scripts/remember.py --channel <渠道> --tags <标签> --session-label <描述> --summary <精华摘要>`

**触发写入的时机：**
- 用户说"记住"、"记一下"、"这个重要"
- Heartbeat 时自动评估当前对话是否值得写入
- 同一话题讨论超过 3 轮

**存储策略：**
- 热存储：引用 OpenClaw 原生 session（默认）
- 冷存储：重要内容自动备份到 archive/（防止 session 被清理）

当你听到"之前说过"、"你还记得吗"、"展开说说"这类话时，主动调用 recall 拉全量。
"""


def patch_agents_md():
    path = WORKSPACE / "AGENTS.md"
    if not path.exists():
        print(f"⚠️  AGENTS.md 不存在，跳过")
        return

    content = path.read_text(encoding="utf-8")

    # 幂等检查：已存在则跳过
    if "Memoria" in content or "执行记忆检索" in content:
        print("✅ AGENTS.md 已包含 Memoria 配置，跳过")
        return

    # 在第 4 步后插入
    target = "4. **If in MAIN SESSION**"
    if target not in content:
        print("⚠️  AGENTS.md 未找到插入点，跳过")
        return

    lines = content.split("\n")
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if target in line:
            new_lines.append(AGENTS_INJECT.strip())
    path.write_text("\n".join(new_lines), encoding="utf-8")
    print("✅ AGENTS.md 已更新")


def patch_soul_md():
    path = WORKSPACE / "SOUL.md"
    if not path.exists():
        print(f"⚠️  SOUL.md 不存在，跳过")
        return

    content = path.read_text(encoding="utf-8")

    if "Memoria" in content:
        print("✅ SOUL.md 已包含 Memoria 说明，跳过")
        return

    path.write_text(content.rstrip() + "\n" + SOUL_INJECT, encoding="utf-8")
    print("✅ SOUL.md 已更新")


def main():
    print(f"🔧 开始集成 Memoria 到 Claw 配置...")
    print(f"   Workspace: {WORKSPACE}\n")
    patch_agents_md()
    patch_soul_md()
    print("\n✅ 集成完成！")


if __name__ == "__main__":
    main()
