#!/usr/bin/env python3
"""
Memoria 数据迁移脚本

将旧数据从 ~/.qclaw/skills/memoria/ 迁移到 ~/.qclaw/memoria/

流程：
1. 备份旧 JSON 到安全位置
2. 转换 JSON → TXT（清洗无效内容）
3. 迁移 TXT 到新 archive/
4. 生成迁移报告

清洗规则（不迁移）：
- Cron session（文件名含 [cron:）
- Heartbeat 消息
- 网络错误/超时
- 摘要无效（"自动归档"、"任务完成"等）
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.config import ARCHIVE_DIR, MEMORIA_ROOT
from lib.utils import generate_memory_id, get_utc_timestamp

# 旧路径
OLD_MEMORIA_ROOT = Path.home() / ".qclaw" / "skills" / "memoria"
OLD_ARCHIVE_DIR = OLD_MEMORIA_ROOT / "archive"

# 备份路径
BACKUP_DIR = Path.home() / ".qclaw" / "memoria_backup_旧数据"

# 清洗规则
SKIP_PATTERNS = [
    r"\[cron:",           # Cron session
    r"heartbeat",         # Heartbeat
    r"自动归档",          # 自动归档标记
    r"任务完成，归档了",  # 自动归档完成消息
]

# 无效摘要模式
INVALID_SUMMARY_PATTERNS = [
    r"^自动归档$",
    r"^任务完成",
    r"^总结对话核心内容如下",
    r"^无摘要$",
]


def should_skip(filename: str, summary: str = "") -> tuple[bool, str]:
    """
    判断是否应该跳过
    
    Returns:
        (should_skip, reason)
    """
    # 检查文件名
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, filename, re.IGNORECASE):
            return True, f"匹配跳过规则: {pattern}"
    
    # 检查摘要
    if summary:
        for pattern in INVALID_SUMMARY_PATTERNS:
            if re.search(pattern, summary, re.IGNORECASE):
                return True, f"无效摘要: {pattern}"
    
    return False, ""


def extract_summary_from_json(data: dict) -> str:
    """从旧 JSON 数据中提取摘要"""
    # 尝试从 session_label 提取
    session_label = data.get("session_label", "")
    if session_label:
        # 去掉前缀时间戳
        label = re.sub(r"^\[[^\]]+\]\s*", "", session_label)
        if label and len(label) > 5:
            return label[:200]
    
    # 尝试从 messages 提取第一条用户消息
    messages = data.get("messages", [])
    for msg in messages:
        if msg.get("role") == "user":
            text = msg.get("text", "")
            # 去掉 Sender 元数据
            text = re.sub(r"Sender \(untrusted metadata\):.*?```\n\n", "", text, flags=re.DOTALL)
            text = re.sub(r"^\[[^\]]+\]\s*", "", text)
            if text and len(text) > 5:
                return text[:200]
    
    return "无摘要"


def extract_content_from_json(data: dict) -> str:
    """从旧 JSON 数据中提取内容（用于 TXT 正文）"""
    messages = data.get("messages", [])
    lines = []
    
    for msg in messages:
        role = msg.get("role", "")
        text = msg.get("text", "")
        
        if not text:
            continue
        
        # 去掉 Sender 元数据
        text = re.sub(r"Sender \(untrusted metadata\):.*?```\n\n", "", text, flags=re.DOTALL)
        
        # 截断过长消息
        if len(text) > 500:
            text = text[:500] + "..."
        
        if role == "user":
            lines.append(f"用户: {text}")
        elif role == "assistant":
            lines.append(f"Clara: {text}")
    
    return "\n\n".join(lines)


def infer_tags_from_json(data: dict) -> list[str]:
    """从旧 JSON 数据推断 tags"""
    tags = ["memoria", "迁移"]
    
    # 从 channel 推断
    channel = data.get("channel", "")
    if channel:
        tags.append(channel)
    
    # 从 session_label 推断
    session_label = data.get("session_label", "")
    if session_label:
        # 关键词匹配
        keywords = {
            "memoria": "memoria",
            "记忆": "memoria",
            "Clara": "clara",
            "clara": "clara",
            "织影": "织影",
            "Vera": "vera",
            "Iris": "iris",
            "Nova": "nova",
            "Kraken": "kraken",
            "ThreadVibe": "threadvibe",
            "埃洛维亚": "埃洛维亚",
            "divine": "divine",
            "技术": "技术",
            "设计": "设计",
            "架构": "架构",
        }
        for kw, tag in keywords.items():
            if kw in session_label:
                if tag not in tags:
                    tags.append(tag)
    
    return tags[:10]  # 最多 10 个


def convert_json_to_txt(json_path: Path, output_dir: Path) -> tuple[Path | None, str]:
    """
    转换旧 JSON 到新 TXT 格式
    
    Returns:
        (txt_path, error_msg)
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, f"读取失败: {e}"
    
    # 提取摘要
    summary = extract_summary_from_json(data)
    
    # 检查是否跳过
    should_skip_it, reason = should_skip(json_path.name, summary)
    if should_skip_it:
        return None, f"跳过: {reason}"
    
    # 生成 memory_id
    memory_id = generate_memory_id()
    
    # 提取字段
    timestamp_str = data.get("archived_at", "")
    if timestamp_str:
        try:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            created_str = dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        except:
            created_str = get_timestamp_iso()
    else:
        created_str = get_utc_timestamp()
    
    # 推断 tags
    tags = infer_tags_from_json(data)
    links = tags.copy()  # 初始 links = tags
    
    # 提取内容
    content = extract_content_from_json(data)
    
    # 确定 archive 子目录（按月）
    dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
    month_dir = output_dir / f"{dt.year}-{dt.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成 TXT 内容
    txt_content = f"""# {summary[:50]}

memory_id: {memory_id}
created: {created_str}
source: migrated
tags: {', '.join(tags)}
links: {', '.join(links)}
session_id: {data.get('session_id', '')}
version: 4.0

---

## 摘要

{summary}

## 背景

从旧 Memoria 系统迁移（原文件：{json_path.name}）

## 要点

{content[:1000]}

## 后续

无
"""
    
    # 写入 TXT
    txt_path = month_dir / f"{memory_id}.txt"
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(txt_content)
        return txt_path, ""
    except Exception as e:
        return None, f"写入失败: {e}"


def migrate_txt_files(output_dir: Path) -> tuple[int, int]:
    """
    迁移旧 TXT 文件（直接复制）
    
    Returns:
        (success_count, failed_count)
    """
    success = 0
    failed = 0
    
    for month_dir in OLD_ARCHIVE_DIR.iterdir():
        if not month_dir.is_dir():
            continue
        
        for txt_file in month_dir.glob("*.txt"):
            try:
                # 目标目录
                target_month = output_dir / month_dir.name
                target_month.mkdir(parents=True, exist_ok=True)
                
                # 复制
                shutil.copy2(txt_file, target_month / txt_file.name)
                success += 1
            except Exception as e:
                print(f"  ✗ {txt_file.name}: {e}")
                failed += 1
    
    return success, failed


def main():
    parser = argparse.ArgumentParser(description="Memoria 数据迁移")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不实际迁移")
    parser.add_argument("--skip-cron", action="store_true", default=True, help="跳过 cron session")
    
    args = parser.parse_args()
    
    print("Memoria 数据迁移")
    print("=" * 50)
    
    # Step 1: 统计旧数据
    print("\n[1/4] 统计旧数据...")
    
    old_json_count = 0
    old_txt_count = 0
    cron_count = 0
    
    for month_dir in OLD_ARCHIVE_DIR.iterdir():
        if not month_dir.is_dir():
            continue
        
        for f in month_dir.iterdir():
            if f.suffix == ".json":
                old_json_count += 1
                if "[cron:" in f.name:
                    cron_count += 1
            elif f.suffix == ".txt":
                old_txt_count += 1
    
    print(f"  旧 JSON: {old_json_count} 条")
    print(f"  旧 TXT: {old_txt_count} 条")
    print(f"  Cron session: {cron_count} 条（将跳过）")
    print(f"  待迁移: {old_json_count - cron_count + old_txt_count} 条")
    
    if args.dry_run:
        print("\n[dry-run] 仅统计，不实际迁移")
        return
    
    # Step 2: 备份旧数据
    print("\n[2/4] 备份旧数据...")
    
    if BACKUP_DIR.exists():
        print(f"  备份目录已存在: {BACKUP_DIR}")
    else:
        shutil.copytree(OLD_ARCHIVE_DIR, BACKUP_DIR / "archive")
        print(f"  ✓ 已备份到: {BACKUP_DIR}")
    
    # Step 3: 迁移 TXT 文件
    print("\n[3/4] 迁移 TXT 文件...")
    
    txt_success, txt_failed = migrate_txt_files(ARCHIVE_DIR)
    print(f"  ✓ TXT 迁移: 成功 {txt_success} 条，失败 {txt_failed} 条")
    
    # Step 4: 转换 JSON → TXT
    print("\n[4/4] 转换 JSON → TXT...")
    
    json_success = 0
    json_skipped = 0
    json_failed = 0
    
    for month_dir in OLD_ARCHIVE_DIR.iterdir():
        if not month_dir.is_dir():
            continue
        
        for json_file in month_dir.glob("*.json"):
            txt_path, error = convert_json_to_txt(json_file, ARCHIVE_DIR)
            
            if txt_path:
                json_success += 1
            elif "跳过" in error:
                json_skipped += 1
            else:
                json_failed += 1
                if json_failed <= 10:
                    print(f"  ✗ {json_file.name}: {error}")
    
    print(f"  ✓ JSON 转换: 成功 {json_success} 条，跳过 {json_skipped} 条，失败 {json_failed} 条")
    
    # 总结
    print("\n" + "=" * 50)
    print("迁移完成")
    print(f"  TXT 迁移: {txt_success} 条")
    print(f"  JSON 转换: {json_success} 条")
    print(f"  跳过: {json_skipped} 条（cron/无效）")
    print(f"  失败: {txt_failed + json_failed} 条")
    print(f"\n下一步: 运行 python3 rebuild.py --force 重建索引")


if __name__ == "__main__":
    main()
