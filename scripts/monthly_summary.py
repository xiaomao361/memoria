#!/usr/bin/env python3
"""
月度摘要归档 — Cold Archive Layer

扫描 archive/ 下某月份的记忆文件，生成月度摘要，写入 archive/月度摘要.md。
用于长期归档时快速回顾某月发生的事。

用法：
    python3 monthly_summary.py [month]   # 例：python3 monthly_summary.py 2026-03
    python3 monthly_summary.py all       # 全部月份
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
MEMORIA_ROOT = Path.home() / ".qclaw" / "memoria"
ARCHIVE_DIR = MEMORIA_ROOT / "archive"
sys.path.insert(0, str(SCRIPT_DIR))

from lib.archive import read_archive_txt, list_archive_txts


def strip_markdown(text: str) -> str:
    """去掉 markdown 格式，返回纯文本"""
    import re
    # 去掉标题符号
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    # 去掉代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    # 去掉行内代码
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 去掉粗体斜体
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    # 去掉链接
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 去掉多余空白
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def generate_monthly_summary(month: str, files: list[Path]) -> dict:
    """为一个月份生成摘要"""
    
    # 按时间分组
    by_day = defaultdict(list)
    all_tags = defaultdict(int)
    entries = []
    
    for fpath in files:
        try:
            data = read_archive_txt(str(fpath))
            if not data:
                continue
            
            content = data.get("content", "")
            tags = data.get("tags", [])
            created = data.get("created", "")
            memory_id = data.get("memory_id", fpath.stem)
            title = data.get("title", "")
            
            # 按天分组
            day = created[:10] if created else "unknown"
            preview = strip_markdown(content)
            
            by_day[day].append({
                "id": memory_id,
                "title": title,
                "preview": preview[:200],
                "tags": tags,
                "created": created,
            })
            
            # 统计标签（排除迁移标签）
            for tag in tags:
                if tag not in ('迁移', 'migrated'):
                    all_tags[tag] += 1
            
            entries.append({
                "day": day,
                "content": content,
                "tags": tags,
                "memory_id": memory_id,
            })
        except Exception as e:
            print(f"  ⚠️  读取失败 {fpath}: {e}")
    
    # 生成摘要文本
    lines = [
        f"# 📅 {month} 月度记忆摘要",
        "",
        f"**生成时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**记忆总数**: {len(entries)} 条",
        "",
        "---",
        "",
        "## 标签频率",
        "",
    ]
    
    # Top 标签（排除迁移相关）
    if all_tags:
        sorted_tags = sorted(all_tags.items(), key=lambda x: -x[1])[:15]
        for tag, count in sorted_tags:
            bar = "▓" * min(count, 10)
            lines.append(f"- **{tag}**: {count} 次 {bar}")
    else:
        lines.append("*（无标签）*")
    
    lines.extend(["", "---", "", "## 每日摘要", ""])
    
    for day, day_entries in sorted(by_day.items()):
        lines.append(f"### 📆 {day}")
        for e in day_entries:
            tags_str = " ".join(f"`{t}`" for t in e["tags"][:4] if t not in ('迁移', 'migrated'))
            preview = e["preview"][:180].replace("\n", " ").strip()
            title_line = e.get("title", "")
            if title_line:
                display = f"**{title_line}**：{preview}"
            else:
                display = preview
            if tags_str:
                lines.append(f"- {display} {tags_str}")
            else:
                lines.append(f"- {display}")
        lines.append("")
    
    content = "\n".join(lines)
    
    # 写入月度摘要文件
    summary_path = ARCHIVE_DIR / f"{month}_月度摘要.md"
    summary_path.write_text(content, encoding="utf-8")
    
    return {
        "month": month,
        "total_entries": len(entries),
        "top_tags": dict(sorted(all_tags.items(), key=lambda x: -x[1])[:10]),
        "summary_path": str(summary_path),
        "days_count": len(by_day),
    }


def main():
    args = sys.argv[1:]
    
    if not args or args[0] == "--help" or args[0] == "-h":
        print(__doc__)
        return 0
    
    mode = args[0] if args else "2026-03"
    
    # 收集月份目录
    months_to_process = []
    if mode == "all":
        for d in ARCHIVE_DIR.iterdir():
            if d.is_dir() and d.name.startswith("2026"):
                months_to_process.append(d.name)
        months_to_process.sort()
    elif mode == "last":
        # 上个月
        now = datetime.now(timezone.utc)
        if now.month == 1:
            last_month = f"{now.year - 1}-12"
        else:
            last_month = f"{now.year}-{now.month - 1:02d}"
        months_to_process = [last_month]
    else:
        months_to_process = [mode]
    
    print(f"📦 将处理 {len(months_to_process)} 个月份: {months_to_process}")
    
    for month in months_to_process:
        month_dir = ARCHIVE_DIR / month
        if not month_dir.exists():
            print(f"  ⏭️  跳过 {month}（目录不存在）")
            continue
        
        # 收集该月所有 .txt 文件
        files = list(month_dir.glob("*.txt"))
        if not files:
            print(f"  ⏭️  跳过 {month}（无文件）")
            continue
        
        print(f"  📂 {month}: {len(files)} 个文件 → 生成摘要中...")
        
        result = generate_monthly_summary(month, files)
        print(f"  ✅ 已写入: {result['summary_path']}")
        print(f"     共 {result['total_entries']} 条记忆，{result['days_count']} 天")
        if result['top_tags']:
            top = ", ".join(f"{k}({v})" for k, v in list(result['top_tags'].items())[:5])
            print(f"     Top 标签: {top}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
