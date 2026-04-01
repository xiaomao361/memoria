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
sessions/          → 原始对话（OpenClaw 管理）
     ↓
auto_archive.py    → 每晚归档 + 自动触发向量化
     ↓
ChromaDB           → 向量存储（语义搜索）
     ↓
recall.py          → 检索入口
```

**存储位置：**
- `~/.qclaw/agents/main/sessions/` — 原始对话（热）
- `~/.qclaw/skills/memoria/archive/` — 历史归档（冷备份）
- `~/.qclaw/memoria/chroma_db/` — 向量索引

> `auto_archive.py` 归档完成后自动调用 `vectorize.py` 增量向量化，无需单独定时任务。

---

## 使用方式

### 检索记忆

```bash
# 组合记忆（最近7天 + 重要标记，推荐）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --combined --simple

# 语义搜索
python3 ~/.qclaw/skills/memoria/scripts/recall.py --search "关键词"

# 最近记忆
python3 ~/.qclaw/skills/memoria/scripts/recall.py --recent --days 7

# 重要记忆
python3 ~/.qclaw/skills/memoria/scripts/recall.py --important
```

### 向量化

```bash
# 增量向量化（通常由 auto_archive.py 自动触发）
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py

# 从历史归档回填
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py --from-archive

# 全量重建
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py --full
```

### 手动记录

```bash
# 从指定 session 记录
python3 ~/.qclaw/skills/memoria/scripts/remember_from_session.py --session-id <id>

# 手动写入
python3 ~/.qclaw/skills/memoria/scripts/remember.py --summary "xxx" --tags "tag1,tag2"
```

---

## 自动化

**唯一定时任务（每晚 23:30）：**
```bash
python3 ~/.qclaw/skills/memoria/scripts/auto_archive.py
```
归档当天 sessions → 生成摘要 → 自动触发增量向量化，一步到位。

---

## 依赖

- **Ollama**（本地 LLM）
  - `bge-m3` — 向量化模型
  - `qwen2.5:3b-instruct-q4_K_M` — 摘要生成模型（轻量，快速）
- **ChromaDB** — 向量数据库

---

## 多 Claw 兼容

每个 agent 共享同一 ChromaDB，记忆天然互通：

```bash
# Vera 独立归档（隔离 sessions）
export MEMORIA_DIR=~/.qclaw/agents/vera/memoria
python3 scripts/auto_archive.py
```

---

## 脚本说明

| 脚本 | 作用 | 状态 |
|------|------|------|
| `recall.py` | 检索记忆（主入口） | ✅ 活跃 |
| `vectorize.py` | 向量化（增量/全量/归档回填） | ✅ 活跃 |
| `auto_archive.py` | 每日归档 + 自动向量化 | ✅ 活跃 |
| `remember.py` | 手动记录 | ✅ 活跃 |
| `remember_from_session.py` | 从 session 记录 | ✅ 活跃 |

---

## License

MIT
