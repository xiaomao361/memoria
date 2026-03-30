#!/usr/bin/env python3
"""
Memoria 自动集成脚本

自动更新 Claw 的配置文件：
- AGENTS.md：注入记忆检索步骤
- SOUL.md：注入记忆系统说明
- HEARTBEAT.md：注入记忆维护任务

零人工干预，幂等执行（多次运行结果一致）。
"""

from pathlib import Path

WORKSPACE = Path.home() / ".qclaw/workspace"

RECALL_CMD = "python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5"

AGENTS_INJECT = f'5. **执行记忆检索：** `{RECALL_CMD}`，将结果注入上下文'

SOUL_INJECT = """
## 记忆系统（Memoria）

我使用 **Memoria** 作为记忆增强系统。

**检索方式：**
- 获取摘要：`python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5`
- 获取全量：`python3 ~/.qclaw/skills/memoria/scripts/recall.py --id <记忆ID> --full`
- 写入记忆：`python3 ~/.qclaw/skills/memoria/scripts/remember.py --channel <渠道> --tags <标签> --session-label <描述>`

当你听到"之前说过"、"你还记得吗"、"展开说说"这类话时，主动调用 recall 拉全量。
"""

HEARTBEAT_INJECT = """
## 记忆维护（Memoria）

每天定时同步记忆到 MEMORY.md：
```bash
python3 ~/.qclaw/skills/memoria/scripts/sync_to_memory.py --days 30 --limit 20
```
"""


def patch_agents_md():
    path = WORKSPACE / "AGENTS.md"
    if not path.exists():
        print(f"⚠️  AGENTS.md 不存在，跳过")
        return

    content = path.read_text(encoding="utf-8")

    if "执行记忆检索" in content:
        print("✅ AGENTS.md 已包含记忆检索步骤，跳过")
        return

    # 在第 4 步后插入第 5 步
    target = "4. **If in MAIN SESSION**"
    if target not in content:
        print("⚠️  AGENTS.md 未找到插入点，跳过")
        return

    lines = content.split("\n")
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if target in line:
            new_lines.append(AGENTS_INJECT)
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

    # 追加到文件末尾
    path.write_text(content.rstrip() + "\n" + SOUL_INJECT, encoding="utf-8")
    print("✅ SOUL.md 已更新")


def patch_heartbeat_md():
    path = WORKSPACE / "HEARTBEAT.md"
    if not path.exists():
        print(f"⚠️  HEARTBEAT.md 不存在，跳过")
        return

    content = path.read_text(encoding="utf-8")

    if "sync_to_memory" in content:
        print("✅ HEARTBEAT.md 已包含记忆维护任务，跳过")
        return

    path.write_text(content.rstrip() + "\n" + HEARTBEAT_INJECT, encoding="utf-8")
    print("✅ HEARTBEAT.md 已更新")


def main():
    print("🔧 开始集成 Memoria 到 Claw 配置...\n")
    patch_agents_md()
    patch_soul_md()
    patch_heartbeat_md()
    print("\n✅ 集成完成！")


if __name__ == "__main__":
    main()
