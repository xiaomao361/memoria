---
name: memoria
description: |
  Clara 的记忆增强插件。跨会话记忆持久化与智能召回。
  当用户提到"记住"、"这个重要"、"之前说过"、"你还记得吗"，
  或需要持久化跨会话信息时使用。
metadata:
  openclaw:
    emoji: "🧠"
---

# Memoria — 记忆系统

> 跨会话记忆，向量检索，永不遗忘。

---

## 架构

```
sessions/*.jsonl   → 原始对话（OpenClaw 管理）
       ↓
auto_archive.py    → 每晚 23:30 归档（三层同时写入）
       ↓
┌──────────────────────────────────────┐
│  1. memoria.json   热缓存（最近50条）  │
│  2. ChromaDB       向量索引（语义搜索）│
│  3. archive/       冷备份（全量历史）  │
└──────────────────────────────────────┘
       ↓
recall.py          → 快速检索（只返回摘要）
recall_with_context.py → 深度检索（自动获取原文）
```

**存储位置：**
- `~/.qclaw/agents/main/sessions/` — 原始对话
- `~/.qclaw/skills/memoria/memoria.json` — 热缓存
- `~/.qclaw/skills/memoria/archive/` — 冷备份
- `~/.qclaw/memoria/chroma_db/` — 向量索引

---

## ⚠️ 启动触发（强制）

**新会话第一条消息时，必须立即执行：**
```bash
python3 ~/.qclaw/skills/memoria/scripts/recall.py --hot-cache --simple
```

**用户提到"之前/上次/还记得"时，立即执行：**
```bash
python3 ~/.qclaw/skills/memoria/scripts/recall.py --search "关键词"
```

---

## 检索

```bash
# 热缓存（最快，新会话默认）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --hot-cache --simple

# 语义搜索（只返回摘要）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --search "关键词"

# 深度搜索（自动获取 archive 原文）
python3 ~/.qclaw/skills/memoria/scripts/recall_with_context.py --search "关键词"

# 最近 N 天
python3 ~/.qclaw/skills/memoria/scripts/recall.py --recent --days 7

# 重要记忆
python3 ~/.qclaw/skills/memoria/scripts/recall.py --important
```

---

## 手动记录

**写入路径判断：**

| 用户说法 | 内容类型 | 调用脚本 | 存储 |
|----------|----------|----------|------|
| 「记一下」+ 日常琐事/喜好 | 偏好、趣事、日常 | `remember.py` | 热缓存（50条轮转） |
| 「记一下」+ 项目/技术/决策 | 方案、待办、约定 | `archive_important.py` | 冷存储 + 向量化 |
| 「单独记」「全量记」「这个很重要」 | 任何 | `archive_important.py` | 冷存储 + 向量化 |

```bash
# 记下来（写入热缓存，日常琐事）
python3 ~/.qclaw/skills/memoria/scripts/remember.py --channel webchat --summary "xxx" --tags "tag1,tag2"

# 单独记一下（写入 archive + 向量化，重要内容）
python3 ~/.qclaw/skills/memoria/scripts/archive_important.py --project "项目名" --content "要记录的内容"
```

---

## 向量化（通常自动，无需手动）

```bash
# 增量（auto_archive.py 已自动触发）
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py

# 从历史归档回填
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py --from-archive

# 全量重建
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py --full
```

---

## 自动化

**唯一定时任务（每晚 23:30）：**
```bash
python3 ~/.qclaw/skills/memoria/scripts/auto_archive.py
```
扫描当天 sessions → 生成摘要 → 三层同时写入。

---

## 依赖

- **Ollama**（本地 LLM）
  - `bge-m3` — 向量化
  - `qwen2.5:3b-instruct-q4_K_M` — 摘要生成
- **ChromaDB** — 向量数据库（`pip3 install chromadb`）

---

## 脚本说明

| 脚本 | 作用 |
|------|------|
| `recall.py` | 快速检索（热缓存/向量搜索/时间过滤） |
| `recall_with_context.py` | 深度检索（自动获取 archive 原文） |
| `auto_archive.py` | 每日归档，三层写入 |
| `archive_important.py` | 手动触发，重要内容写入 archive + 向量化 |
| `vectorize.py` | 增量/全量向量化 |
| `remember.py` | 直接写入一条记忆（热缓存） |
| `memoria_utils.py` | 公共工具库（含 `get_archive_content()`） |
