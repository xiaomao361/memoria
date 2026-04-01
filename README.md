# 🧠 Memoria

> Clara 的跨会话记忆系统。向量检索，永不遗忘。

---

## 简介

Memoria 是 Clara（OpenClaw AI 助手）的记忆增强插件，解决 AI 每次对话"失忆"的问题。

核心能力：
- **持久化**：每晚自动归档当天对话
- **语义搜索**：用自然语言检索历史记忆
- **多 Agent 共享**：Clara、Vera 等多个 agent 共用同一记忆库

---

## 架构

```
OpenClaw sessions/
       ↓
auto_archive.py   ← 每晚 23:30 定时触发
       ↓
archive/          ← 冷存储（JSON 备份）
       ↓
vectorize.py      ← 自动触发（archive 完成后）
       ↓
ChromaDB          ← 向量索引
       ↓
recall.py         ← 检索入口
```

**存储路径：**

| 路径 | 内容 |
|------|------|
| `~/.qclaw/agents/main/sessions/` | 原始对话（OpenClaw 管理） |
| `~/.qclaw/skills/memoria/archive/` | 冷存储归档（JSON） |
| `~/.qclaw/memoria/chroma_db/` | 向量索引（ChromaDB） |

---

## 快速开始

### 依赖

```bash
# Ollama（本地 LLM）
brew install ollama
ollama pull bge-m3        # 向量化模型
ollama pull qwen2.5:7b    # 摘要生成模型

# Python 依赖
pip3 install chromadb requests
```

### 检索记忆

```bash
# 语义搜索（最常用）
python3 scripts/recall.py --search "web01 事故"

# 最近 N 天
python3 scripts/recall.py --recent --days 3

# 组合模式（最近 + 重要，推荐日常使用）
python3 scripts/recall.py --combined --simple

# 重要记忆
python3 scripts/recall.py --important
```

### 手动触发归档

```bash
# 归档今天的 sessions（自动接着向量化）
python3 scripts/auto_archive.py

# 仅增量向量化
python3 scripts/vectorize.py

# 历史回填（首次部署时用）
python3 scripts/vectorize.py --from-archive

# 全量重建
python3 scripts/vectorize.py --full
```

---

## 自动化配置

只需一个定时任务，每晚 23:30 执行：

```bash
python3 ~/.qclaw/skills/memoria/scripts/auto_archive.py
```

`auto_archive.py` 会：
1. 扫描当天新增 sessions
2. 用 `qwen2.5:7b` 生成摘要
3. 写入冷存储 archive/
4. 自动触发 `vectorize.py` 增量向量化

---

## 多 Agent 支持

多个 agent 共享同一 ChromaDB，记忆天然互通。

```bash
# Vera 独立归档
export MEMORIA_DIR=~/.qclaw/agents/vera/memoria
python3 scripts/auto_archive.py
```

---

## 脚本一览

| 脚本 | 说明 |
|------|------|
| `recall.py` | 检索记忆（主入口） |
| `vectorize.py` | 向量化（增量 / 全量 / 归档回填） |
| `auto_archive.py` | 每日归档 + 自动向量化 |
| `remember.py` | 手动写入记忆 |
| `remember_from_session.py` | 从指定 session 写入 |
| `export_training_data.py` | 导出训练数据 |

---

## License

MIT
