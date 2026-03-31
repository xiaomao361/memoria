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
vectorize.py       → 生成摘要 + 向量化
     ↓
ChromaDB           → 向量存储（语义搜索）
     ↓
recall.py          → 检索入口
```

**存储位置：**
- `~/.qclaw/agents/main/sessions/` — 原始对话（热）
- `~/.qclaw/skills/memoria/archive/` — 历史归档（冷备份）
- `~/.qclaw/memoria/chroma_db/` — 向量索引

---

## 使用方式

### 检索记忆

```bash
# 组合记忆（最近7天 + 重要标记）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --combined --simple

# 语义搜索
python3 ~/.qclaw/skills/memoria/scripts/recall.py --search "Clara Core"

# 最近记忆
python3 ~/.qclaw/skills/memoria/scripts/recall.py --recent --days 7

# 重要记忆
python3 ~/.qclaw/skills/memoria/scripts/recall.py --important
```

### 向量化（增量）

```bash
# 增量向量化新 session
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py

# 从历史归档回填
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py --from-archive

# 全量重建
python3 ~/.qclaw/skills/memoria/scripts/vectorize.py --full
```

### 记录记忆

```bash
# 从当前 session 记录
python3 ~/.qclaw/skills/memoria/scripts/remember_from_session.py --session-id <id>

# 手动记录
python3 ~/.qclaw/skills/memoria/scripts/remember.py --summary "xxx" --tags "tag1,tag2"
```

---

## 自动化

**推荐定时任务：**
- 每晚增量向量化：`python3 scripts/vectorize.py`
- 定期归档旧 session：`python3 scripts/auto_archive.py`

---

## 依赖

- **Ollama**（本地 LLM）
  - `bge-m3` — 向量化模型
  - `qwen2.5:7b` — 摘要生成模型
- **ChromaDB** — 向量数据库

---

## 数据格式

### ChromaDB 元数据

```json
{
  "timestamp": "2026-03-31T10:00:00Z",
  "channel": "webchat",
  "tags": "技术,memoria",
  "session_id": "abc123",
  "message_count": 15
}
```

### 冷存储（archive/）

```json
{
  "archived_at": "2026-03-31T10:00:00Z",
  "channel": "webchat",
  "session_id": "abc123",
  "session_label": "Memoria 重构讨论",
  "messages": [...]
}
```

---

## 多 Claw 兼容

```bash
# Vera 独立记忆
export MEMORIA_DIR=~/.qclaw/agents/vera/memoria
python3 scripts/recall.py --combined --simple
```

---

## 脚本说明

| 脚本 | 作用 |
|------|------|
| `recall.py` | 检索记忆（主入口） |
| `vectorize.py` | 向量化（增量/全量/归档回填） |
| `remember.py` | 手动记录 |
| `remember_from_session.py` | 从 session 记录 |
| `auto_archive.py` | 自动归档定时任务 |
| `batch_index.py` | 批量索引（旧，可废弃） |

---

## License

MIT
