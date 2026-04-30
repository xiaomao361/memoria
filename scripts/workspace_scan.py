#!/usr/bin/env python3
"""
Memoria Workspace Scan

扫描 workspace 文件的章节，评估活跃度，决定是否需要衰减。

用法:
    python3 workspace_scan.py --file MEMORY.md                    # 扫描章节
    python3 workspace_scan.py --file MEMORY.md --activity         # 加上活跃度分析
    python3 workspace_scan.py --file MEMORY.md --dry-run           # 模拟衰减（不实际修改）
    python3 workspace_scan.py --file MEMORY.md --execute          # 执行衰减

原理:
    1. 按 ## 标题把文件拆成独立章节
    2. 章节内容提取关键词（实体名、项目名、技术词）
    3. 用关键词去 memoria 查 recall 记录
    4. 计算章节活跃度 = 30天内 recall 次数
    5. 活跃度低的 → 建议衰减（移除或压缩）
    6. 保护章节（⚠️ 前缀 / 保护标签）→ 跳过
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 添加 lib 目录
sys.path.insert(0, str(Path(__file__).parent / "lib"))
from lib.config import PROTECTION_TAGS

# ============== 配置 ==============

# 可衰减的文件
ATTENUATABLE_FILES = {
    "MEMORY.md": "长期记忆，自动衰减已完结项目状态",
    "AGENTS.md": "工作区指南，定期精简过长内容",
}

# 不可衰减的文件
PROTECTED_FILES = {
    "SOUL.md": "身份设定，不应自动衰减",
    "IDENTITY.md": "身份标识，不应自动衰减",
    "USER.md": "用户画像，人工维护",
    "HEARTBEAT.md": "心跳规则，不应衰减",
    "TOOLS.md": "工具笔记，不应衰减",
}

# 额外保护章节关键词（不在 PROTECTION_TAGS 里但不能删的）
EXTRA_PROTECTED_KEYWORDS = {
    "情感里程碑", "Lara", "缠结系统", "隐私", "私密",
    "项目状态", "身份", "名字", "生日", "MBTI",
    "称呼分级", "经验教训",  # 毛仔确认保留
}

# 活跃度阈值
ACTIVITY_WINDOW_DAYS = 30          # 统计窗口：30天内
ACTIVITY_THRESHOLD_REMOVE = 0      # recall 0次 → 建议移除（但受保护的章节不会走到这里）
ACTIVITY_THRESHOLD_COMPRESS = 3     # recall 1-3次 → 建议压缩
ACTIVITY_THRESHOLD_KEEP = 4        # recall 4+次 → 保留

# 衰减后的摘要行数
COMPRESSED_LINES = 2

# ============== 工具函数 ==============

def parse_sections(content: str) -> list[dict]:
    """
    按 ## 标题拆分文件为章节。
    返回: [{title, level, content, line_start, line_end, is_protected}, ...]
    """
    lines = content.split('\n')
    sections = []
    
    # 找到所有 ## 标题行
    title_pattern = re.compile(r'^(#{1,6})\s+(.+)$')
    
    section_boundaries = []  # (line_index, title, level)
    
    for i, line in enumerate(lines):
        m = title_pattern.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            section_boundaries.append((i, title, level))
    
    # 构建每个章节
    for idx, (start_line, title, level) in enumerate(section_boundaries):
        # 下一节标题的行号作为本节结束
        if idx + 1 < len(section_boundaries):
            end_line = section_boundaries[idx + 1][0]
        else:
            end_line = len(lines)
        
        section_content = '\n'.join(lines[start_line:end_line])
        
        # 判断是否保护
        is_protected = _is_section_protected(title, section_content)
        
        sections.append({
            "title": title,
            "level": level,
            "content": section_content,
            "line_start": start_line + 1,  # 1-indexed
            "line_end": end_line,
            "is_protected": is_protected,
        })
    
    return sections


def _is_section_protected(title: str, content: str) -> bool:
    """判断章节是否受保护"""
    # 1. ⚠️ 前缀
    if title.startswith('⚠️') or title.startswith('⚠'):
        return True
    # 2. 在保护标签列表里
    title_lower = title.lower()
    for tag in PROTECTION_TAGS:
        if tag.lower() in title_lower:
            return True
    # 3. 额外保护词
    for kw in EXTRA_PROTECTED_KEYWORDS:
        if kw.lower() in title_lower:
            return True
    # 4. 文件头注释（如 # MEMORY.md）
    if content.startswith('# MEMORY.md') or content.startswith('# Workspace'):
        return True
    return False


def extract_keywords(content: str) -> list[str]:
    """
    从章节内容提取关键词。
    提取：项目名（大写开头）、技术词（反引号包裹）、[[链接]]、专业术语
    """
    keywords = []
    
    # [[链接]] 格式
    links = re.findall(r'\[\[([^\]]+)\]\]', content)
    keywords.extend(links)
    
    # 反引号包裹的代码/技术词
    code_terms = re.findall(r'`([^`]+)`', content)
    keywords.extend([t for t in code_terms if len(t) > 2])
    
    # 大写开头的英文词（通常是项目名/技术名）
    capitalized = re.findall(r'\b[A-Z][a-zA-Z0-9\-]{2,}\b', content)
    # 过滤常见词
    stopwords = {'The', 'This', 'That', 'For', 'And', 'But', 'Not', 'When', 'With', 'From', 'Into', 'About', 'Python', 'Json', 'Yaml', 'Path', 'Date', 'Time', 'Config', 'Path'}
    capitalized = [w for w in capitalized if w not in stopwords and not w.startswith(('0','1','2','3','4','5','6','7','8','9'))]
    keywords.extend(capitalized[:10])  # 最多10个
    
    # 下划线命名法
    snake_case = re.findall(r'\b[a-z][a-z0-9_]{3,30}_[a-z0-9_]+\b', content)
    keywords.extend(snake_case[:5])
    
    # 井号标签
    hashtags = re.findall(r'#(\w+)', content)
    keywords.extend([f"#{h}" for h in hashtags])
    
    # 去重返回
    seen = set()
    result = []
    for kw in keywords:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            result.append(kw)
    
    return result[:20]  # 最多20个关键词


def get_recall_activity(keywords: list[str], private: bool = False) -> dict:
    """
    用关键词去 memoria 查 recall 活动。
    返回: {total_recalls, recent_recalls, matched_memories, last_recalled}
    """
    if not keywords:
        return {"total_recalls": 0, "recent_recalls": 0, "matched_memories": 0, "last_recalled": None}
    
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from scripts.lib.hot_cache import read_hot_cache, get_importance_score
    except ImportError:
        from lib.hot_cache import read_hot_cache, get_importance_score
    
    cache = read_hot_cache(private=private)
    entries = cache if isinstance(cache, list) else cache.get("memories", [])
    
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - (ACTIVITY_WINDOW_DAYS * 86400)
    recent_count = 0
    total_count = 0
    last_ts = None
    matched = 0
    
    keywords_lower = [kw.lower() for kw in keywords]
    
    for entry in entries:
        content_lower = ""
        if isinstance(entry, dict):
            content_lower = (entry.get("content", "") + " " + entry.get("summary", "")).lower()
        
        # 简单匹配：关键词是否出现在内容里
        hit = any(kw.lower() in content_lower for kw in keywords_lower)
        if not hit:
            continue
        
        matched += 1
        
        last_recalled = entry.get("last_recalled") if isinstance(entry, dict) else None
        if last_recalled:
            try:
                ts = datetime.fromisoformat(last_recalled.replace('Z', '+00:00')).timestamp()
                total_count += 1
                if ts >= cutoff:
                    recent_count += 1
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            except:
                pass
    
    return {
        "total_recalls": total_count,
        "recent_recalls": recent_count,
        "matched_memories": matched,
        "last_recalled": datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat() if last_ts else None
    }


def score_activity(activity: dict) -> str:
    """
    根据活跃度数据给出建议。
    返回: "keep" | "compress" | "remove" | "protected"
    """
    recent = activity.get("recent_recalls", 0)
    if recent >= ACTIVITY_THRESHOLD_KEEP:
        return "keep"
    elif recent >= ACTIVITY_THRESHOLD_COMPRESS:
        return "compress"
    else:
        return "remove"


def generate_compressed_content(section: dict) -> str:
    """生成压缩后的章节内容（只留标题 + 一行摘要）"""
    title = section["title"]
    content_lines = section["content"].split('\n')
    # 去掉标题行，取剩余内容的前几行
    body_lines = [l for l in content_lines[1:] if l.strip()]
    summary = '\n'.join(body_lines[:COMPRESSED_LINES])
    
    # 计算行数
    orig_lines = len(content_lines)
    new_lines = 1 + COMPRESSED_LINES
    reduction = f"-{orig_lines - new_lines}行"
    
    return f"{'#' * section['level']} {title}\n\n{summary}\n\n> ⚠️ 已压缩（原{orig_lines}行 → {new_lines}行，{reduction}）"


# ============== 主逻辑 ==============

def scan_file(filepath: str, show_activity: bool = False) -> list[dict]:
    """扫描文件，返回章节分析结果"""
    p = Path(filepath)
    if not p.exists():
        print(f"ERROR: 文件不存在: {filepath}", file=sys.stderr)
        sys.exit(1)
    
    content = p.read_text(encoding='utf-8')
    filename = p.name
    
    # 判断是否可衰减
    attenuatable = filename in ATTENUATABLE_FILES
    protected_file = filename in PROTECTED_FILES
    
    if not (attenuatable or protected_file):
        print(f"WARNING: 未识别的文件类型，跳过: {filename}", file=sys.stderr)
        return []
    
    if protected_file:
        print(f"ℹ️  {filename} 为保护文件，不执行衰减")
        return []
    
    sections = parse_sections(content)
    
    results = []
    for sec in sections:
        keywords = extract_keywords(sec["content"])
        
        activity = {}
        if show_activity:
            activity = get_recall_activity(keywords)
        
        recommendation = "protected" if sec["is_protected"] else ("keep" if show_activity else "unknown")
        
        if show_activity and not sec["is_protected"]:
            recommendation = score_activity(activity)
        
        results.append({
            "title": sec["title"],
            "line_start": sec["line_start"],
            "line_end": sec["line_end"],
            "is_protected": sec["is_protected"],
            "keywords": keywords[:5],  # 只显示前5个
            "activity": activity,
            "recommendation": recommendation,
        })
    
    return results


def print_report(results: list[dict], filename: str):
    """打印分析报告"""
    print(f"\n{'='*60}")
    print(f"📄 {filename} 章节分析")
    print(f"{'='*60}")
    
    for r in results:
        status_icon = "🔒" if r["is_protected"] else ("✅" if r["recommendation"] == "keep" else ("📦" if r["recommendation"] == "compress" else ("🗑️" if r["recommendation"] == "remove" else "❓")))
        
        if r["is_protected"]:
            status = "🔒 保护"
        elif r["recommendation"] == "keep":
            status = "✅ 保留"
        elif r["recommendation"] == "compress":
            status = "📦 压缩"
        elif r["recommendation"] == "remove":
            status = "🗑️ 移除"
        else:
            status = "❓ 待分析"
        
        print(f"\n{status_icon} {status} | 第{r['line_start']}-{r['line_end']}行 | {r['title']}")
        
        if r["is_protected"]:
            print(f"   原因: 保护章节")
        else:
            if r["activity"]:
                act = r["activity"]
                print(f"   活跃度: 近30天 recall {act.get('recent_recalls',0)}次 / 总计 {act.get('total_recalls',0)}次 / 匹配 {act.get('matched_memories',0)}条记忆")
                if act.get('last_recalled'):
                    print(f"   最近 recall: {act['last_recalled'][:10]}")
            if r["keywords"]:
                print(f"   关键词: {', '.join(r['keywords'][:5])}")
    
    # 统计
    protected = sum(1 for r in results if r["is_protected"])
    keep = sum(1 for r in results if not r["is_protected"] and r["recommendation"] == "keep")
    compress = sum(1 for r in results if not r["is_protected"] and r["recommendation"] == "compress")
    remove = sum(1 for r in results if not r["is_protected"] and r["recommendation"] == "remove")
    
    print(f"\n{'─'*60}")
    print(f"📊 统计: 🔒保护{protected} | ✅保留{keep} | 📦压缩{compress} | 🗑️移除{remove} | 总计{len(results)}章节")


def execute_decay(filepath: str, results: list[dict], dry_run: bool = True):
    """
    执行衰减操作。
    - dry_run: True = 只打印，不修改
    - dry_run: False = 直接修改文件
    """
    p = Path(filepath)
    content = p.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    # 找出要删除/替换的行区间
    # 按 line_end 从大到小排序，这样删除行时索引不会乱
    sections_to_modify = []
    for r in results:
        if r["is_protected"]:
            continue
        if r["recommendation"] in ("compress", "remove"):
            sections_to_modify.append(r)
    
    sections_to_modify.sort(key=lambda x: x["line_end"], reverse=True)
    
    if not sections_to_modify:
        print("✅ 没有需要衰减的章节")
        return
    
    print(f"\n{'='*60}")
    print(f"🔧 {'DRY-RUN' if dry_run else 'EXECUTE'} 衰减操作")
    print(f"{'='*60}")
    
    new_lines = lines[:]
    
    for sec in sections_to_modify:
        start = sec["line_start"] - 1
        end = sec["line_end"]
        orig_content = '\n'.join(lines[start:end])
        
        if sec["recommendation"] == "remove":
            action = "🗑️ 移除"
            new_content = ""
        else:  # compress
            action = "📦 压缩"
            section_dict = {"title": sec["title"], "level": 2, "content": orig_content}
            new_content = generate_compressed_content(section_dict)
        
        print(f"\n{action} | 第{sec['line_start']}-{sec['line_end']}行 | {sec['title']}")
        if dry_run:
            print(f"   [DRY-RUN] 实际会修改")
        else:
            print(f"   [EXECUTE] 已执行修改")
        
        # 执行替换
        if dry_run:
            # dry-run: 打印摘要
            orig_len = end - start
            new_len = len(new_content.split('\n')) if new_content else 0
            print(f"   {orig_len}行 → {new_len}行 ({'%.0f' % (new_len/orig_len*100) if orig_len else 0}%)")
        else:
            # 实际修改
            new_lines[start:end] = new_content.split('\n') if new_content else []
    
    if not dry_run:
        new_content = '\n'.join(new_lines)
        p.write_text(new_content, encoding='utf-8')
        
        orig_lines = len(lines)
        new_total = len(new_lines)
        print(f"\n✅ 文件已更新: {orig_lines}行 → {new_total}行 (-{orig_lines - new_total}行)")
        
        # 自动将被移除的内容写入 memoria
        _archive_removed_content(filepath, results)
    else:
        print(f"\n[DRY-RUN] 如需执行，添加 --execute 参数")


def _get_section_content(filepath: str, start_line: int, end_line: int) -> str:
    """读取指定行范围的内容"""
    p = Path(filepath)
    lines = p.read_text(encoding='utf-8').split('\n')
    # line numbers are 1-indexed in the report
    return '\n'.join(lines[start_line-1:end_line])


def _archive_removed_content(filepath: str, results: list[dict]):
    """将被移除的章节内容存入 memoria archive"""
    p = Path(filepath)
    filename = p.name
    
    # 收集被移除的内容
    removed_sections = []
    for r in results:
        if r["is_protected"]:
            continue
        if r["recommendation"] in ("compress", "remove"):
            removed_sections.append(r)
    
    if not removed_sections:
        return
    
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from scripts.store import store
    except ImportError:
        from store import store
    
    for sec in removed_sections:
        content = _get_section_content(filepath, sec["line_start"], sec["line_end"])
        store(
            content=content,
            summary=f"[{filename}] {sec['title']} (已自动衰减)",
            tags=["workspace", "衰减归档", filename.replace(".md", "")],
            private=False,
        )
    
    print(f"📦 已将被移除内容存入 memoria archive ({len(removed_sections)}个章节)")


# ============== 入口 ==============

def main():
    parser = argparse.ArgumentParser(description="Memoria Workspace 章节活跃度扫描")
    parser.add_argument("--file", required=True, help="目标文件路径或文件名")
    parser.add_argument("--activity", action="store_true", help="分析章节活跃度")
    parser.add_argument("--dry-run", action="store_true", help="模拟衰减（不实际修改）")
    parser.add_argument("--execute", action="store_true", help="执行衰减（需确认）")
    parser.add_argument("--private", action="store_true", help="同时扫描私密记忆的活跃度")
    
    args = parser.parse_args()
    
    # 支持文件名或绝对路径
    file_arg = args.file
    if not Path(file_arg).exists():
        # 尝试在工作区查找
        workspace = Path.home() / ".qclaw" / "workspace"
        candidate = workspace / file_arg
        if candidate.exists():
            file_arg = str(candidate)
        else:
            print(f"ERROR: 文件不存在: {file_arg}", file=sys.stderr)
            sys.exit(1)
    
    # 扫描
    # 如果执行衰减，必须分析活跃度
    show_activity = args.activity or args.execute
    results = scan_file(file_arg, show_activity=show_activity)
    
    if not results:
        return
    
    # 报告
    print_report(results, Path(file_arg).name)
    
    # 执行
    if args.execute:
        execute_decay(file_arg, results, dry_run=False)
    elif args.dry_run:
        execute_decay(file_arg, results, dry_run=True)


if __name__ == "__main__":
    main()
