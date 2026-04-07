#!/usr/bin/env python3
"""
Memoria auto_archive.py — Session 冷备份

定时任务：每天 23:30 执行
扫描当天新增 sessions，备份到 sessions_backup/{YYYY-MM}/

注意：
- 完全独立于记忆写入流程
- 不写入 memoria.json / 向量库 / links.json
- 只做 session 冷备份，防止 OpenClaw 清理导致对话丢失
"""

import argparse
import json
import sys
from datetime import datetime, timezone, date
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.config import MEMORIA_ROOT

# Session 冷备份目录
SESSIONS_BACKUP_DIR = MEMORIA_ROOT / "sessions_backup"

# OpenClaw sessions 目录（main agent）
SESSIONS_DIR = Path.home() / ".qclaw" / "agents" / "main" / "sessions"


def get_archived_session_ids() -> set:
    """获取已备份的 session_id 集合"""
    if not SESSIONS_BACKUP_DIR.exists():
        return set()
    
    archived_ids = set()
    for month_dir in SESSIONS_BACKUP_DIR.iterdir():
        if month_dir.is_dir():
            for f in month_dir.glob("*.jsonl"):
                # 文件名格式：{session_id}_{timestamp}.jsonl
                session_id = f.name.split("_")[0]
                archived_ids.add(session_id)
    
    return archived_ids


def get_sessions(since_days: int = 1) -> list[Path]:
    """获取最近 N 天修改的 session 文件"""
    if not SESSIONS_DIR.exists():
        return []
    
    today = date.today()
    sessions = []
    
    for f in SESSIONS_DIR.glob("*.jsonl"):
        if ".deleted." in f.name:
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if (today - mtime.date()).days < since_days:
            sessions.append(f)
    
    return sorted(sessions, key=lambda f: f.stat().st_mtime, reverse=True)


def backup_session(session_path: Path) -> tuple[str, str]:
    """
    备份单个 session
    
    Returns:
        (session_id, backup_path)
    """
    session_id = session_path.stem
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    # 按月归档
    dt = datetime.now(timezone.utc)
    month_dir = SESSIONS_BACKUP_DIR / f"{dt.year}-{dt.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    
    # 备份文件名
    backup_file = month_dir / f"{session_id}_{timestamp}.jsonl"
    
    # 复制文件
    import shutil
    shutil.copy2(session_path, backup_file)
    
    return session_id, str(backup_file)


def auto_archive(since_days: int = 1, dry_run: bool = False) -> dict:
    """
    自动备份 sessions
    
    Args:
        since_days: 扫描最近 N 天的 sessions
        dry_run: 仅列出，不实际备份
    
    Returns:
        {
            "total": 总数,
            "archived": 新备份数,
            "skipped": 已存在跳过数,
            "errors": [错误信息]
        }
    """
    print(f"Memoria Session 冷备份")
    print(f"扫描最近 {since_days} 天的 sessions...")
    print("=" * 50)
    
    # 获取已备份的 session_id
    archived_ids = get_archived_session_ids()
    print(f"已备份 session 数: {len(archived_ids)}")
    
    # 获取待备份的 sessions
    sessions = get_sessions(since_days)
    print(f"待扫描 session 数: {len(sessions)}")
    
    if not sessions:
        print("\n无需备份")
        return {
            "total": 0,
            "archived": 0,
            "skipped": 0,
            "errors": []
        }
    
    # 备份
    archived_count = 0
    skipped_count = 0
    errors = []
    
    for session_path in sessions:
        session_id = session_path.stem
        
        # 跳过已备份的
        if session_id in archived_ids:
            skipped_count += 1
            continue
        
        if dry_run:
            print(f"  [dry-run] 会备份: {session_id}")
            archived_count += 1
            continue
        
        try:
            session_id, backup_path = backup_session(session_path)
            print(f"  ✅ {session_id}")
            archived_count += 1
        except Exception as e:
            errors.append(f"{session_id}: {e}")
            print(f"  ❌ {session_id}: {e}")
    
    print("\n" + "=" * 50)
    print(f"备份完成: 新增 {archived_count} 条，跳过 {skipped_count} 条（已备份）")
    
    if errors:
        print(f"\n错误: {len(errors)} 条")
    
    return {
        "total": len(sessions),
        "archived": archived_count,
        "skipped": skipped_count,
        "errors": errors
    }


def main():
    parser = argparse.ArgumentParser(description="Memoria Session 冷备份")
    parser.add_argument("--since-days", type=int, default=1, help="扫描最近 N 天的 sessions")
    parser.add_argument("--dry-run", action="store_true", help="仅列出，不实际备份")
    
    args = parser.parse_args()
    
    result = auto_archive(since_days=args.since_days, dry_run=args.dry_run)
    
    # 输出 JSON 结果
    print("\nJSON 结果:")
    print(json.dumps({
        "total": result["total"],
        "archived": result["archived"],
        "skipped": result["skipped"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
