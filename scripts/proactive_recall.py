#!/usr/bin/env python3
"""
主动召回脚本 — HEARTBEAT cron 调用

找出即将陷入沉睡的重要记忆，主动提醒毛仔。

条件（满足任一）：
- importance_score >= 0.3 且 last_recalled >= 20 天前

输出：
- JSON 格式，供 HEARTBEAT agent 读取
- 格式：{"should_push": true/false, "messages": [...]}
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径 ────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
MEMORIA_ROOT = Path.home() / ".qclaw" / "memoria"
SKILL_LIB_DIR = SCRIPT_DIR / "lib"
sys.path.insert(0, str(SKILL_LIB_DIR))

from lib.hot_cache import list_hot_cache
from lib.config import PROTECTION_TAGS

# ── 参数 ────────────────────────────────────────────────────────────
MIN_IMPORTANCE = 0.3       # 重要度门槛
RECALL_GAP_DAYS = 20        # 超过多少天未召回 → 触发提醒
OUTPUT_PATH = MEMORIA_ROOT / "proactive_recall.json"


def format_memory_snippet(content: str, max_len: int = 80) -> str:
    """截取记忆内容摘要（用于展示）"""
    if not content:
        return "(无内容)"
    preview = content.replace("\n", " ").strip()
    if len(preview) > max_len:
        return preview[:max_len] + "…"
    return preview


def main():
    now = datetime.now(timezone.utc)
    gap_delta = timedelta(days=RECALL_GAP_DAYS)
    
    entries = list_hot_cache(limit=9999)
    
    candidates = []
    for e in entries:
        importance_score = e.get("importance_score", 0.0)
        if importance_score < MIN_IMPORTANCE:
            continue
        
        last_recalled = e.get("last_recalled")
        if not last_recalled:
            # 从未召回过 → 检查 created 时间
            created = e.get("created")
            if not created:
                continue
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if (now - created_dt) >= gap_delta:
                    days_ago = (now - created_dt).days
                    candidates.append({
                        "memory_id": e.get("memory_id", e.get("id")),
                        "importance_score": importance_score,
                        "days_ago": days_ago,
                        "summary": format_memory_snippet(e.get("summary", "")),
                        "content": e.get("content", ""),
                        "tags": e.get("tags", []),
                        "reason": f"创建后 {days_ago} 天未被召回",
                        "last_recalled": last_recalled or "从未",
                    })
            except Exception:
                continue
        else:
            try:
                last_dt = datetime.fromisoformat(last_recalled.replace("Z", "+00:00"))
                if (now - last_dt) >= gap_delta:
                    days_ago = (now - last_dt).days
                    candidates.append({
                        "memory_id": e.get("memory_id", e.get("id")),
                        "importance_score": importance_score,
                        "days_ago": days_ago,
                        "summary": format_memory_snippet(e.get("summary", "")),
                        "content": e.get("content", ""),
                        "tags": e.get("tags", []),
                        "reason": f"距上次召回 {days_ago} 天",
                        "last_recalled": last_recalled,
                    })
            except Exception:
                continue
    
    # 按重要度降序，取最多 3 条
    candidates.sort(key=lambda x: (-x["importance_score"], x["days_ago"]))
    candidates = candidates[:3]
    
    if not candidates:
        result = {"should_push": False, "messages": []}
    else:
        messages = []
        for c in candidates:
            tags_str = " ".join(f"#{t}" for t in c["tags"][:3])
            snippet = c["summary"]
            messages.append(
                f"📌 **{c['reason']}**，最近想起过吗？**\n"
                f"   {snippet}\n"
                f"   {tags_str}（重要度 {c['importance_score']:.1f}）"
            )
        
        lead = f"最近有 {len(candidates)} 条重要记忆好久没提起了，随口问问👇"
        result = {
            "should_push": True,
            "messages": [lead] + messages,
            "candidates": candidates,
        }
    
    # 写入输出文件（供 HEARTBEAT agent 读取）
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    # 同时打印供 cron agent 直接看到
    if result["should_push"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("NO_PUSH")
    
    return 0 if result["should_push"] else 0  # 总是成功


if __name__ == "__main__":
    sys.exit(main())
