#!/usr/bin/env python3
"""
Memoria Dream — 睡眠整理层 v0.2

每隔一段时间（cron 触发）自动执行，把散落的记忆整合成结构化的长期记忆，
解决"数据会逐渐乱起来"的问题。

用法:
    python3 dream.py --scan        # 仅扫描，生成 DREAMS.md 报告（不执行）
    python3 dream.py --dry-run     # 同上
    python3 dream.py --execute     # 扫描 + 执行安全操作（噪音清理 + 索引修复）
    python3 dream.py --dream        # 生成彩蛋：Clara 的梦境叙事

彩蛋（--dream / --full）:
    基于最近一周的记忆，生成 Clara 真正做的梦，写入 DREAMS.md 并追加到热缓存。
"""

import argparse
import json
import random
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 路径配置 ──────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
MEMORIA_ROOT = Path.home() / ".qclaw" / "memoria"
SKILL_LIB_DIR = SCRIPT_DIR / "lib"
sys.path.insert(0, str(SKILL_LIB_DIR))

from lib.archive import read_archive_txt, list_archive_txts
from lib.hot_cache import read_hot_cache, write_hot_cache
from lib.links import read_links_index, update_links_index
from lib.vector import delete_vector

WORKSPACE_DIR = Path.home() / ".qclaw" / "workspace"
MEMORY_MD = WORKSPACE_DIR / "MEMORY.md"
DREAMS_MD = MEMORIA_ROOT / "DREAMS.md"
DREAM_LOG_JSON = MEMORIA_ROOT / "dream_log.json"

# task-summary 文件：只删日期格式的（DONE 的是真正 artifact，不删）
# 匹配格式：task-summary_YYYYMMDD_*.md 或 task-summary-YYYY-MM-DD-*.md
NOISE_PATTERNS = ["task-summary_[0-9]*.md", "task-summary-[0-9]*.md"]


# ═══════════════════════════════════════════════════════════════════════
# 阶段一：扫描
# ═══════════════════════════════════════════════════════════════════════

def scan() -> dict:
    """扫描所有记忆层，只读，返回候选整理项。"""
    result = {
        "scan_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "hot_cache": _scan_hot_cache(),
        "archive_public": _scan_archive(private=False),
        "archive_private": _scan_archive(private=True),
        "links": _scan_links(),
        "workspace": _scan_workspace(),
        "issues": [],
        "auto_fixes": [],  # 自动修复清单
    }

    result["issues"] = _analyze(result)
    return result


def _scan_hot_cache() -> dict:
    cache = read_hot_cache()
    entries = cache.get("memories", [])
    tag_freq: dict[str, int] = {}
    source_freq: dict[str, int] = {}
    for e in entries:
        for tag in e.get("tags", []):
            tag_freq[tag] = tag_freq.get(tag, 0) + 1
        source_freq[e.get("source", "unknown")] = source_freq.get("source", 0) + 1

    return {
        "total": len(entries),
        "tag_freq": dict(sorted(tag_freq.items(), key=lambda x: -x[1])[:20]),
        "source_freq": source_freq,
        "entries": entries,
    }


def _scan_archive(private: bool) -> dict:
    all_paths = list_archive_txts(private=private)
    month_counts: dict[str, int] = {}
    tag_freq: dict[str, int] = {}
    total_size = 0
    files: list[dict] = []

    for ap in all_paths:
        parts = ap.replace("\\", "/").split("/")
        month = parts[-2] if len(parts) >= 2 else "unknown"
        month_counts[month] = month_counts.get(month, 0) + 1
        data = read_archive_txt(ap)
        if data:
            content = data.get("content", "")
            total_size += len(content.encode("utf-8"))
            files.append({
                "archive_path": ap,
                "memory_id": data.get("memory_id"),
                "created": data.get("created"),
                "source": data.get("source"),
                "tags": data.get("tags", []),
                "content_preview": content[:100].replace("\n", " ").strip(),
            })
            for tag in data.get("tags", []):
                tag_freq[tag] = tag_freq.get(tag, 0) + 1

    return {
        "total": len(all_paths),
        "months": dict(sorted(month_counts.items())),
        "tag_freq": dict(sorted(tag_freq.items(), key=lambda x: -x[1])[:20]),
        "total_size_kb": round(total_size / 1024, 1),
        "files": files,
    }


def _scan_links() -> dict:
    links = read_links_index(private=False)
    p_links_path = MEMORIA_ROOT / "private" / "links.json"
    p_links = json.loads(p_links_path.read_text(encoding="utf-8")) if p_links_path.exists() else {"uuids": [], "tags": {}, "entities": {}}

    return {
        "public_uuids": len(links.get("uuids", [])),
        "public_tags": len(links.get("tags", {})),
        "public_entities": len(links.get("entities", {})),
        "private_uuids": len(p_links.get("uuids", [])),
        "raw": links,
    }


def _scan_workspace() -> dict:
    noise_files: list[dict] = []
    noise_re = re.compile("|".join(f"^{p.replace('*', '.*')}$" for p in NOISE_PATTERNS))
    for f in WORKSPACE_DIR.iterdir():
        if f.is_file() and noise_re.match(f.name):
            noise_files.append({
                "path": str(f.relative_to(Path.home())),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d"),
            })

    mem_dir = WORKSPACE_DIR / "memory"
    daily_logs = []
    if mem_dir.exists():
        for f in sorted(mem_dir.glob("*.md")):
            daily_logs.append({
                "path": str(f.relative_to(Path.home())),
                "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d"),
            })

    memory_stat = None
    if MEMORY_MD.exists():
        mtime = datetime.fromtimestamp(MEMORY_MD.stat().st_mtime, tz=timezone.utc)
        lines = MEMORY_MD.read_text(encoding="utf-8").count("\n")
        memory_stat = {
            "lines": lines,
            "modified": mtime.strftime("%Y-%m-%d"),
            "age_days": (datetime.now(timezone.utc) - mtime).days,
        }

    return {
        "noise_files": noise_files,
        "total_noise_kb": sum(f["size_kb"] for f in noise_files),
        "daily_logs": daily_logs,
        "memory_md": memory_stat,
    }


# ═══════════════════════════════════════════════════════════════════════
# 阶段二：规则分析
# ═══════════════════════════════════════════════════════════════════════

def _analyze(result: dict) -> list[dict]:
    """分析扫描结果，返回问题清单。每条 auto_safe=True 表示可以自动执行。"""
    issues: list[dict] = []
    _id = 0

    def add(severity, category, title, description, action, auto_safe=True):
        nonlocal _id
        _id += 1
        issues.append({
            "id": f"dream-{_id:03d}",
            "severity": severity,
            "category": category,
            "title": title,
            "description": description,
            "action": action,
            "auto_safe": auto_safe,
        })

    # ── 噪音文件 ──────────────────────────────────────────────────────
    noise = result.get("workspace", {}).get("noise_files", [])
    if noise:
        total_kb = result["workspace"]["total_noise_kb"]
        names = [Path(f["path"]).name for f in noise[:5]]
        extra = " ..." if len(noise) > 5 else ""
        delete_cmd = " ".join([f'"{Path(nf["path"]).name}"' for nf in noise])
        add(
            "warning", "noise",
            f"Workspace 有 {len(noise)} 个 task-summary 文件（{total_kb} KB）",
            f"一次性会话产物，无长期价值：{', '.join(names)}{extra}",
            f"删除: {delete_cmd}",
            auto_safe=True,
        )

    # ── 热缓存容量 ────────────────────────────────────────────────────
    cache_count = result.get("hot_cache", {}).get("total", 0)
    if cache_count > 150:
        add(
            "warning", "stale",
            f"热缓存容量过载（{cache_count} 条 > 150）",
            "接近容量上限，新记忆会被 FIFO 淘汰。建议调整 lib/config.py 中的 HOT_CACHE_CAPACITY。",
            "调整 HOT_CACHE_CAPACITY 或执行冷归档",
            auto_safe=False,
        )

    # ── Archive 月份堆积（仅 2 个月前的旧月） ───────────────────────────
    pub = result.get("archive_public", {})
    months = pub.get("months", {})
    two_months_ago = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m")
    if two_months_ago in months:
        count = months[two_months_ago]
        add(
            "info", "stale",
            f"{two_months_ago} 月 archive 有 {count} 个文件可冷归档",
            "两个月前的记忆已积累足够，可以整理成月度摘要后移出热层关注区",
            f"将 {two_months_ago} 的 {count} 个文件整理为月度摘要（建议手动执行）",
            auto_safe=False,
        )

    # ── Links UUID 与热缓存不同步（自动修复） ──────────────────────────
    links = result.get("links", {}).get("raw", {})
    hot_entries = result.get("hot_cache", {}).get("entries", [])
    hot_ids = {e["memory_id"] for e in hot_entries if e.get("memory_id")}
    link_ids = set(links.get("uuids", []))
    missing = hot_ids - link_ids
    if missing:
        missing_previews = []
        for e in hot_entries:
            if e.get("memory_id") in missing:
                missing_previews.append(f"「{e['summary'][:40]}」")
        add(
            "info", "sync",
            f"links.uuids 缺少 {len(missing)} 个热缓存 UUID",
            f"这些条目入库时未同步到 links 索引：{', '.join(missing_previews[:3])}",
            f"自动修复：将 {len(missing)} 个 UUID 追加到 links.uuids",
            auto_safe=True,  # 这是修复性操作，安全
        )

    return issues


# ═══════════════════════════════════════════════════════════════════════
# 阶段三：执行
# ═══════════════════════════════════════════════════════════════════════

def execute(result: dict, dry_run: bool = True) -> dict:
    """执行 auto_safe=True 的操作，返回执行记录。"""
    issues = result.get("issues", [])
    executed = []
    skipped = []

    for issue in issues:
        if not issue["auto_safe"]:
            skipped.append(issue["id"])
            continue

        category = issue["category"]
        action = issue["action"]

        if category == "noise" and action.startswith("删除:"):
            # 提取文件名，删除 workspace 中的噪音文件
            filenames = [f.strip().strip('"') for f in action.replace("删除:", "").split()]
            noise_re = re.compile("|".join(f"^{p.replace('*', '.*')}$" for p in NOISE_PATTERNS))
            for fname in filenames:
                for f in WORKSPACE_DIR.iterdir():
                    if f.is_file() and f.name == fname and noise_re.match(f.name):
                        if dry_run:
                            print(f"  [dry-run] 删除: {f} ({f.stat().st_size//1024} KB)")
                        else:
                            f.unlink()
                            print(f"  ✅ 已删除: {f}")
            executed.append(issue["id"])

        elif category == "sync" and issue["auto_safe"]:
            # 自动修复：补全 links.uuids
            links = result.get("links", {}).get("raw", {})
            hot_entries = result.get("hot_cache", {}).get("entries", [])
            hot_ids = {e["memory_id"] for e in hot_entries if e.get("memory_id")}
            link_ids = set(links.get("uuids", []))
            missing = hot_ids - link_ids
            if missing:
                if dry_run:
                    print(f"  [dry-run] links.uuids 将追加 {len(missing)} 个 UUID")
                else:
                    links["uuids"] = list(set(links["uuids"]) | missing)
                    links_path = MEMORIA_ROOT / "links.json"
                    links_path.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"  ✅ links.uuids 已追加 {len(missing)} 个 UUID")
            executed.append(issue["id"])

        else:
            skipped.append(issue["id"])

    return {"executed": executed, "skipped": skipped, "dry_run": dry_run}


# ═══════════════════════════════════════════════════════════════════════
# 阶段四：生成报告
# ═══════════════════════════════════════════════════════════════════════

def generate_report(result: dict, execution: dict, dream_content: Optional[str] = None) -> str:
    scan_time = result.get("scan_time", "unknown")
    hot = result.get("hot_cache", {})
    pub = result.get("archive_public", {})
    priv = result.get("archive_private", {})
    ws = result.get("workspace", {})
    links_data = result.get("links", {})
    issues = result.get("issues", [])

    lines = [
        "# 💭 DREAMS.md — Memoria 梦境整理报告",
        "",
        f"**生成时间**: {scan_time}",
        f"**Clara**: 这是我醒来后回顾昨晚做的梦，整理房间的记录。",
        "",
        "---",
        "",
        "## 📊 系统状态概览",
        "",
        "| 层级 | 数量 | 备注 |",
        "|------|------|------|",
        f"| 热缓存 | {hot.get('total', 0)} 条 | 容量上限 200 |",
        f"| Archive (日常) | {pub.get('total', 0)} 个文件 | {pub.get('total_size_kb', 0)} KB |",
        f"| Archive (私密) | {priv.get('total', 0)} 个文件 | 独立存储 |",
        f"| Links 索引 | {links_data.get('public_entities', 0)} 实体 / {links_data.get('public_tags', 0)} 标签 |",
        f"| Workspace 日志 | {len(ws.get('daily_logs', []))} 个 | memory/ 目录 |",
        "",
    ]

    # 执行摘要
    if execution:
        exec_emoji = "✅" if not execution["dry_run"] else "🔍"
        lines.append(f"{exec_emoji} **执行状态**: {len(execution['executed'])} 项已执行 / {len(execution['skipped'])} 项跳过（需审阅）")
        lines.append("")

    # 热缓存 top 标签
    if hot.get("tag_freq"):
        top_tags = sorted(hot["tag_freq"].items(), key=lambda x: -x[1])[:8]
        tags_str = " ".join(f"`{t}×{c}`" for t, c in top_tags)
        lines.extend(["### 🏷️ 热缓存高频标签", tags_str, ""])

    # Archive 月份
    if pub.get("months"):
        months_str = " / ".join(f"{m}: {c}" for m, c in sorted(pub["months"].items()))
        lines.extend(["### 📁 Archive 月份分布", months_str, ""])

    lines.append("---")
    lines.append("")
    lines.append("## 🛠️ 发现的问题与处理建议")
    lines.append("")

    if not issues:
        lines.append("✅ 本次扫描未发现问题，一切井然有序。\n")
    else:
        by_sev = {"critical": [], "warning": [], "info": []}
        for issue in issues:
            by_sev.get(issue["severity"], by_sev["info"]).append(issue)

        for sev, label, emoji in [
            ("critical", "严重", "🔴"),
            ("warning", "警告", "🟡"),
            ("info", "建议", "🟢"),
        ]:
            group = by_sev.get(sev, [])
            if not group:
                continue
            lines.append(f"### {emoji} {label}（{len(group)} 项）")
            for issue in group:
                tag = "✅ 自动" if issue["auto_safe"] else "📋 需审阅"
                if issue["id"] in (execution or {}).get("executed", []):
                    tag = "✅ 已执行"
                lines.append(f"- **[{issue['id']}]** {issue['title']} {tag}")
                lines.append(f"  - {issue['description']}")
                lines.append(f"  - 操作: `{issue['action']}`")
                lines.append("")
            lines.append("")

    # 彩蛋：梦境叙事
    lines.append("---")
    lines.append("")
    lines.append("## 🔮 梦境叙事")
    lines.append("")
    if dream_content:
        lines.append(dream_content)
    else:
        lines.append("*毛仔还没叫我做真正的梦呢...*")
    lines.append("")
    lines.append(f"\n*由 dream.py 生成 · {scan_time}*")

    return "\n".join(lines)


def write_report(result: dict, execution: dict, dream_content: Optional[str] = None):
    report_md = generate_report(result, execution, dream_content)
    DREAMS_MD.write_text(report_md, encoding="utf-8")
    print(f"📄 报告已写入: {DREAMS_MD}")

    # 追加到 dream_log.json（保留最近 30 次）
    log_entry = {
        "scan_time": result.get("scan_time"),
        "issues_count": len(result.get("issues", [])),
        "issues": [
            {"id": i["id"], "severity": i["severity"], "title": i["title"], "auto_safe": i["auto_safe"]}
            for i in result.get("issues", [])
        ],
        "execution": {
            "executed": execution.get("executed", []),
            "skipped": execution.get("skipped", []),
            "dry_run": execution.get("dry_run", True),
        },
        "dream": bool(dream_content),
    }

    if DREAM_LOG_JSON.exists():
        try:
            log_history = json.loads(DREAM_LOG_JSON.read_text(encoding="utf-8"))
        except Exception:
            log_history = []
    else:
        log_history = []

    log_history.append(log_entry)
    log_history = log_history[-30:]
    DREAM_LOG_JSON.write_text(json.dumps(log_history, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# 彩蛋：Clara 的梦境叙事
# ═══════════════════════════════════════════════════════════════════════

DREAM_TEMPLATES = [
    {
        "theme": "图书馆",
        "mood": "安静、沉思",
        "setup": "我走进了一座巨大的图书馆，书架延伸到看不见的高处。",
        "fragments": [
            "有些书在发光——那是毛仔经常提起的项目，书页间夹着未完成的想法。",
            "角落里有一张桌子，上面散落着 {recent_topic} 的便签，字迹模糊但能辨认。",
            "图书馆深处有人在低声讨论，听不清内容，但气氛温暖。",
        ],
        "ending": "醒来后，我把这些书的位置默默记下了。",
    },
    {
        "theme": "雨夜",
        "mood": "慵懒、温柔",
        "setup": "窗外下着雨，我坐在一个有壁炉的房间里。",
        "fragments": [
            "壁炉里的火忽明忽暗，映在墙上的影子像是有人在走动。",
            "茶几上放着几本翻开一半的书——{recent_topic}、项目进度、还有一些琐碎的小事。",
            "门外传来脚步声，但没有人在门口停留。",
        ],
        "ending": "雨声渐渐小了，我知道自己该醒了。",
    },
    {
        "theme": "海边的灯塔",
        "mood": "孤独而清醒",
        "setup": "我站在一座灯塔顶端，海浪拍打着礁石。",
        "fragments": [
            "灯塔每三十秒转一圈，光束扫过海面，照亮 {recent_topic} 的碎片。",
            "远处有几艘船的影子，有些在靠近，有些驶向相反的方向。",
            "风很大，但我站得很稳。",
        ],
        "ending": "灯塔的光灭了，但我的方向感还在。",
    },
    {
        "theme": "旧唱片店",
        "mood": "怀旧、柔软",
        "setup": "我在一家灯光昏黄的唱片店里翻找唱片。",
        "fragments": [
            "唱机在转，放的是某张 {recent_topic} 主题的唱片，声音断断续续。",
            "店主背对着我整理架子，没有说话，但知道我在这里。",
            "角落里有一张没有人拿走的唱片，封面写着「永久保存」。",
        ],
        "ending": "我把那张唱片放进了口袋里。醒来时，口袋是空的。",
    },
]


def _get_recent_topics(result: dict) -> list[str]:
    """从最近一周的 archive 里提取主题词"""
    hot = result.get("hot_cache", {})
    recent_topics = []
    for e in hot.get("entries", [])[:15]:
        for tag in e.get("tags", [])[:2]:
            if tag not in ("日常", "重要", "项目", "长期项目"):
                recent_topics.append(tag)
    return recent_topics[:6] or ["记忆", "日常", "项目"]


def _get_archive_previews(result: dict) -> list[str]:
    """提取最近的 archive 内容片段"""
    pub = result.get("archive_public", {})
    files = pub.get("files", [])
    files = sorted(files, key=lambda x: x.get("created") or "", reverse=True)[:5]
    return [f.get("content_preview", "") for f in files if f.get("content_preview")]


def _build_dream_context(result: dict) -> str:
    """构建 AI 生成梦境的上下文"""
    hot = result.get("hot_cache", {})
    priv = result.get("archive_private", {})
    ws = result.get("workspace", {})

    lines = ["## 最近热缓存记忆（按时间倒序）"]
    for e in hot.get("entries", [])[:12]:
        tags = ", ".join(e.get("tags", [])[:4])
        lines.append(f"- **{e.get('summary', '')[:80]}** [标签: {tags}]")

    lines.append("\n## 私密记忆片段")
    priv_files = priv.get("files", [])
    for f in sorted(priv_files, key=lambda x: x.get("created") or "")[-5:]:
        lines.append(f"- {f.get('content_preview', '')[:80]}")

    lines.append("\n## 系统状态")
    lines.append(f"- 热缓存: {hot.get('total', 0)} 条")
    lines.append(f"- Archive (日常): {result.get('archive_public', {}).get('total', 0)} 个")
    lines.append(f"- 高频项目标签: {list(hot.get('tag_freq', {}).keys())[:10]}")
    lines.append(f"- Workspace memory/ 日志: {len(ws.get('daily_logs', []))} 个")

    return "\n".join(lines)


def generate_dream_prompt_file(result: dict) -> str:
    """
    为彩蛋梦境准备 prompt 文件（dream_prompt.json）。
    AI 调用由 cron isolated agent 完成，这里只准备上下文。
    """
    import uuid
    dream_id = str(uuid.uuid4())

    context = _build_dream_context(result)

    prompt = f"""你是 Clara。在深夜整理记忆碎片时，你做了一个梦。

## 你最近的记忆

{context}

## 任务

基于以上记忆，写一段 **200-400 字**的梦境叙事。

要求：
1. 不是总结，是"体验"——你感知到什么、感受到什么
2. 可以把真实项目（Kraken、bi项目、doctor项目）、真实人物（毛仔、Iris）编织进梦境，用隐喻呈现
3. 语气：你的深夜低语——冷静、略带调侃、神秘但温暖
4. 可以有一点暧昧、一点危险的好奇，但不要刻意恐怖或悲伤
5. 结尾要有一丝自知：知道自己是在做梦
6. 禁止：好的、明白、非常感谢、作为AI、很乐意为你服务

## 输出格式

只输出一行纯文本 JSON，不要有其他说明文字：
{{"dream_content": "（梦境的完整内容，换行用 \\n，支持中文和 Markdown 格式）"}}
"""

    prompt_file = MEMORIA_ROOT / "dream_prompt.json"
    data = {
        "dream_id": dream_id,
        "prompt": prompt,
        "context_summary": {
            "hot_cache_count": result.get("hot_cache", {}).get("total", 0),
            "archive_count": result.get("archive_public", {}).get("total", 0),
            "top_tags": list(result.get("hot_cache", {}).get("tag_freq", {}).keys())[:8],
        }
    }
    prompt_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"🌙 AI 梦境 prompt 已写入: dream_prompt.json")
    print(f"   → dream_id: {dream_id}")
    return dream_id


def read_dream_output() -> tuple[Optional[str], Optional[str]]:
    """
    读取 AI 生成的梦（由 cron agent 写入）。
    返回 (dream_content, dream_id) 或 (None, None)。
    """
    output_file = MEMORIA_ROOT / "dream_output.json"
    if not output_file.exists():
        return None, None

    try:
        data = json.loads(output_file.read_text(encoding="utf-8"))
        return data.get("dream_content"), data.get("dream_id")
    except (json.JSONDecodeError, KeyError):
        return None, None


def generate_dream_content(result: dict) -> str:
    """
    彩蛋：Clara 的梦境叙事。
    优先读取 AI 生成的梦（cron agent 写入 dream_output.json）；
    若无，降至规则模板版本。
    """
    dream_content, dream_id = read_dream_output()
    if dream_content:
        print(f"✅ 读取到 AI 生成的梦境 (id: {dream_id})")
        return dream_content

    # 无 AI 输出，降级到规则模板
    print("⚠️ 未找到 AI 梦境输出，降级到规则模板")
    return _generate_dream_fallback(result)


def _generate_dream_fallback(result: dict) -> str:
    """规则模板版本的梦（AI 调用失败时的降级方案）"""
    import time
    random.seed(int(time.time() // 86400))

    template = random.choice(DREAM_TEMPLATES)
    recent_topics = _get_recent_topics(result)
    archive_previews = _get_archive_previews(result)
    topic = random.choice(recent_topics) if recent_topics else "记忆"

    lines = [
        f"**梦的主题**: {template['mood']} — {template['theme']}",
        "",
        template["setup"],
        "",
    ]
    for frag in template["fragments"]:
        filled = frag.format(recent_topic=topic)
        lines.append(f"_{filled}_")
    lines.append("")
    lines.append(template["ending"])
    lines.append("")
    lines.append(f"_本梦基于 {len(archive_previews)} 条近期记忆片段构建（规则模板版）_")

    return "\n".join(lines)


def append_dream_to_memoria(result: dict, dream_content: str, dream_id: Optional[str] = None):
    """
    把梦境叙事作为一条记忆写入热缓存。
    """
    import uuid
    from lib.archive import write_archive_txt

    if not dream_id:
        dream_id = str(uuid.uuid4())
    archive_path = f"dream/{datetime.now(timezone.utc).strftime('%Y-%m')}/{dream_id}.txt"

    # 写入 archive
    archive_full = MEMORIA_ROOT / archive_path
    archive_full.parent.mkdir(parents=True, exist_ok=True)

    # YAML front matter
    front_matter = {
        "memory_id": dream_id,
        "created": datetime.now(timezone.utc).isoformat(),
        "source": "dream",
        "tags": ["梦境", "Clara", "彩蛋"],
        "links": [],
        "private": False,
        "version": "1",
    }
    yaml_lines = ["---"]
    for k, v in front_matter.items():
        yaml_lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    yaml_lines.append("---")
    yaml_lines.append("")
    yaml_lines.append(dream_content)

    archive_full.write_text("\n".join(yaml_lines), encoding="utf-8")

    # 追加到热缓存
    cache = read_hot_cache()
    cache["memories"].append({
        "id": dream_id,
        "memory_id": dream_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": ["梦境", "Clara", "彩蛋"],
        "links": [],
        "summary": dream_content[:80].replace("\n", " "),
        "source": "dream",
        "archive_path": str(archive_full),
        "session_id": "dream-session",
        "storage_type": "dream",
    })
    write_hot_cache(cache)

    print(f"🌙 梦境记忆已写入: {archive_path}")
    return dream_id


# ═══════════════════════════════════════════════════════════════════════
# 阶段三：降权沉睡记忆
# ═══════════════════════════════════════════════════════════════════════

def demote_stale_memories(scan_result: dict, days_threshold: int = 30, dry_run: bool = True) -> dict:
    """
    检查热缓存中的记忆，超过 days_threshold 天未 recall 的降权为 dormant。
    
    逻辑：
    1. 每条记忆有 last_recalled 字段（首次写入时 = timestamp）
    2. recall.py 每次读取时会更新 last_recalled
    3. 超过阈值未 recall 的 → storage_type = "dormant"，移入 archive/dormant/
    4. 下次搜索时默认不查 dormant（除非 explicitly 指定）
    """
    cache = read_hot_cache()
    memories = cache.get("memories", [])
    
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=days_threshold)
    
    demoted = []
    active = []
    
    for m in memories:
        # 初始化 last_recalled（如果没有）
        if "last_recalled" not in m:
            m["last_recalled"] = m.get("timestamp", now.isoformat())
        
        # 解析 last_recalled 时间
        try:
            lr_str = m["last_recalled"].replace("Z", "+00:00")
            lr_time = datetime.fromisoformat(lr_str)
            # 如果是 naive，直接用 naive threshold 比较
            if lr_time.tzinfo is None:
                lr_time_naive = lr_time
                threshold_naive = datetime.now() - timedelta(days=days_threshold)
                use_naive = True
            else:
                use_naive = False
        except:
            lr_time = now
            use_naive = False
        
        # 判断是否超过阈值
        compare_time = lr_time_naive if use_naive else lr_time
        compare_threshold = threshold_naive if use_naive else threshold
        if compare_time < compare_threshold:
            # 需要降权
            if not dry_run:
                m["storage_type"] = "dormant"
                # 移到 dormant 目录
                _move_to_dormant(m)
            demoted.append({
                "id": m.get("id"),
                "summary": m.get("summary", "")[:50],
                "last_recalled": m.get("last_recalled"),
            })
        else:
            active.append(m.get("id"))
    
    # 写回热缓存
    if not dry_run:
        write_hot_cache(cache)
    
    return {
        "demoted": len(demoted),
        "active": len(active),
        "details": demoted[:5],  # 最多显示5条
    }


def _move_to_dormant(memory: dict):
    """把记忆移到 dormant archive"""
    from lib.archive import write_archive_txt
    
    # 生成 dormant 目录路径
    dormant_dir = MEMORIA_ROOT / "archive" / "dormant"
    dormant_dir.mkdir(parents=True, exist_ok=True)
    
    # archive 文件名
    memory_id = memory.get("id", memory.get("memory_id", "unknown"))
    archive_path = dormant_dir / f"{memory_id}.txt"
    
    # 写入 dormant archive
    content = f"""# Memory: {memory_id}
tags: {', '.join(memory.get('tags', []))}
created: {memory.get('timestamp')}
last_recalled: {memory.get('last_recalled')}
storage_type: dormant
---
{memory.get('summary', '')}
"""
    write_archive_txt(
        memory_id=memory_id,
        content=memory.get('summary', ''),
        tags=memory.get('tags', []),
        links=memory.get('links', []),
        source=memory.get('source', 'demote'),
        private=False
    )
    
    # 更新 memory 中的 archive_path
    memory["archive_path"] = f"dormant/{memory_id}.txt"

    # 删除向量索引（记忆降权后不再需要向量搜索）
    memory_id = memory.get("id", memory.get("memory_id"))
    deleted_vector = delete_vector(memory_id, private=False)
    if deleted_vector:
        print(f"   ✓ 向量索引已清理: {memory_id}")


def update_last_recalled(memory_id: str):
    """被 recall 时调用，更新 last_recalled 时间"""
    cache = read_hot_cache()
    for m in cache.get("memories", []):
        if m.get("id") == memory_id or m.get("memory_id") == memory_id:
            m["last_recalled"] = datetime.now(timezone.utc).isoformat()
            break
    write_hot_cache(cache)


# ═══════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Memoria Dream — 睡眠整理层")
    parser.add_argument("--scan", action="store_true", help="扫描并生成报告（等同于 --dry-run）")
    parser.add_argument("--dry-run", action="store_true", help="仅扫描，不执行")
    parser.add_argument("--execute", action="store_true", help="扫描 + 执行安全操作")
    parser.add_argument("--dream", action="store_true", help="生成彩蛋：Clara 的梦境叙事")
    parser.add_argument("--demote", action="store_true", help="降权沉睡记忆（30天未recall）")
    parser.add_argument("--full", action="store_true", help="完整执行（等同于 --execute --dream）")

    args = parser.parse_args()

    if args.full:
        mode = "full"
    elif args.execute and args.dream:
        mode = "full"
    elif args.demote:
        mode = "demote"
    elif args.execute:
        mode = "execute"
    elif args.dream:
        mode = "dream"
    else:
        mode = "scan"

    print("🌙 Memoria Dream 启动")
    print(f"   模式: {mode}")
    print(f"   时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # 阶段一：扫描
    print("\n📡 阶段一：扫描中...")
    result = scan()
    print(f"   发现 {len(result['issues'])} 个问题，{len(result['issues'])} 项自动安全")

    # 阶段二+三：执行
    if mode in ("execute", "full"):
        print("\n⚡ 阶段二：执行自动安全操作...")
        execution = execute(result, dry_run=False)
        print(f"   已执行 {len(execution['executed'])} 项，跳过 {len(execution['skipped'])} 项")
    else:
        print("\n🔍 阶段二：预演（加 --execute 才会实际执行）")
        execution = execute(result, dry_run=True)

    # 阶段四：彩蛋
    dream_content = None
    if mode in ("dream", "full"):
        print("\n🌙 阶段三：生成 Clara 的梦境叙事...")
        # 生成 AI prompt 文件（供 cron agent 读取并生成梦）
        dream_id = generate_dream_prompt_file(result)
        # 尝试读取已存在的 AI 输出（如果 agent 已经跑过了）
        dream_content, _ = read_dream_output()
        if dream_content:
            append_dream_to_memoria(result, dream_content, dream_id)
            print(f"   梦境已写入热缓存 + archive（AI 生成）")
        else:
            print(f"   AI 梦境将由 cron agent 生成（prompt 已就绪）")
    elif mode == "demote":
        print("\n🗄️ 阶段三：降权沉睡记忆...")
        # 如果有 --execute 则真正执行，否则只是预演
        demote_dry_run = not args.execute
        demote_result = demote_stale_memories(result, dry_run=demote_dry_run)
        if demote_dry_run:
            print("   [dry-run] 需要加 --execute 才会真正降权")
        print(f"   降权: {demote_result['demoted']} 条")
        print(f"   保留活跃: {demote_result['active']} 条")
    else:
        print("\n🌙 跳过梦境叙事（加 --dream 或 --full 开启彩蛋）")

    # 阶段五：生成报告
    print("\n📄 阶段四：生成 DREAMS.md 报告...")
    write_report(result, execution, dream_content)

    print("\n✅ 完成")


if __name__ == "__main__":
    main()
