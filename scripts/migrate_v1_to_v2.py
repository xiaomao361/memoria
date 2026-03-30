#!/usr/bin/env python3
"""
Memoria 记忆迁移脚本

将旧格式记忆（[助手末次回复] 格式）迁移到新格式（一句话精华）。
对于 full_ref 中没有用户消息的记录，直接从 summary 提取精华。
"""

import json
import re
from pathlib import Path
from datetime import datetime

MEMORIA_DIR = Path.home() / ".qclaw/skills/memoria"
MEMORIA_INDEX = MEMORIA_DIR / "memoria.json"


def clean_summary(raw: str) -> str:
    """清理旧格式摘要，提取核心内容"""
    if not raw:
        return "（无内容）"

    # 去掉 [助手末次回复]: 前缀
    raw = re.sub(r'\[助手末次回复\]:\s*', '', raw)
    # 去掉 [用户\d+]: 前缀
    raw = re.sub(r'\[用户\d+\]:\s*', '', raw)
    # 去掉多余换行
    raw = re.sub(r'\n+', ' ', raw).strip()

    # 截取前 150 字作为精华
    if len(raw) > 150:
        return raw[:150] + "..."
    return raw


def rebuild_summary_from_full(full_ref: str) -> str:
    """从 full_ref 文件重建摘要（如果有完整对话）"""
    path = Path(full_ref)
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    messages = data.get("messages", [])

    user_msgs = [m["text"] for m in messages if m["role"] == "user"]
    asst_msgs = [m["text"] for m in messages if m["role"] == "assistant"]

    if not user_msgs and not asst_msgs:
        return None

    first_user = user_msgs[0][:80] if user_msgs else ""
    last_asst = asst_msgs[-1][:120] if asst_msgs else ""

    if first_user and last_asst:
        return f"{first_user}... → {last_asst}..."
    elif first_user:
        return first_user
    elif last_asst:
        return last_asst
    return None


def migrate():
    if not MEMORIA_INDEX.exists():
        print("❌ memoria.json 不存在")
        return

    data = json.loads(MEMORIA_INDEX.read_text(encoding="utf-8"))
    memories = data.get("memories", [])

    print(f"📦 共 {len(memories)} 条记忆，开始迁移...\n")

    updated = 0
    for m in memories:
        old_summary = m.get("summary", "")
        full_ref = m.get("full_ref", "")

        # 优先从 full_ref 重建（有完整对话的）
        new_summary = None
        if full_ref:
            new_summary = rebuild_summary_from_full(full_ref)

        # 没有完整对话，从旧 summary 清理
        if not new_summary:
            new_summary = clean_summary(old_summary)

        if new_summary != old_summary:
            m["summary"] = new_summary
            updated += 1
            label = m.get("tags", ["?"])[0] if m.get("tags") else "?"
            print(f"  ✅ [{m['id'][:8]}] {label}")
            print(f"     旧: {old_summary[:60]}...")
            print(f"     新: {new_summary[:80]}")
            print()

    # 保存
    MEMORIA_INDEX.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"✅ 迁移完成，更新了 {updated}/{len(memories)} 条记忆")


if __name__ == "__main__":
    migrate()
