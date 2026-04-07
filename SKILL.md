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

# Memoria — 记忆系统 v4.0

> 跨会话记忆，向量检索，双向链接，永不遗忘。

---

## 架构

```
~/.qclaw/agents/main/sessions/*.jsonl   → 原始对话（OpenClaw 管理）
                    ↓
auto_archive.py    → 每天 23:30 冷备份（三层同时写入）
                    ↓
┌──────────────────────────────────────────┐
│  ~/.qclaw/memoria/                       │
│  ├── memoria.json   热缓存（最近50条）    │
│  ├── chroma_db/    向量索引（语义搜索）   │
│  ├── archive/      冷备份（全量历史）     │
│  ├── links.json    双向链接索引           │
│  └── sessions_backup/  Session 备份      │
└──────────────────────────────────────────┘
                    ↓
recall.py / store.py  → 写入/检索入口
```

**存储位置：**
- 代码：`~/.qclaw/skills/memoria/scripts/`
- 数据：`~/.qclaw/memoria/`

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

## 写入（store）

**触发方式：**

| 用户说法 | 内容类型 | 调用方式 |
|----------|----------|----------|
| 「记一下」+ 日常琐事/偏好 | 偏好、趣事 | store.py（自动判断写热缓存） |
| 「记一下」+ 项目/技术/决策 | 方案、待办、约定 | store.py（自动判断写冷存储） |
| 「单独记」「全量记」 | 重要内容 | store.py --content |

```bash
# 方式1：自动判断写入（根据内容类型自动选择热缓存/冷存储）
python3 ~/.qclaw/skills/memoria/scripts/store.py \
  --content "要记录的内容" \
  --tags "tag1,tag2" \
  --links "链接1,链接2"

# 方式2：手动指定写入热缓存
python3 ~/.qclaw/skills/memoria/scripts/store.py \
  --type hot \
  --content "日常琐事" \
  --tags "偏好,爱好"
```

**写入流程（四步独立）：**
1. archive TXT → 冷备份
2. 向量库 → 语义索引
3. 热缓存 → 最近50条
4. links.json → 双向链接索引

---

## 检索（recall）

```bash
# 热缓存（最快，新会话默认）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --hot-cache --simple

# 语义搜索（向量 + 链接自动合并）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --search "关键词"

# 深度搜索（自动获取 archive 原文）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --search "关键词" --with-content

# 标签精确匹配
python3 ~/.qclaw/skills/memoria/scripts/recall.py --tags "Memoria,技术"

# 最近 N 天
python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7
```

---

## 双向链接

**使用方式：**
1. 内容中写 `[[链接名]]`（自动提取）
2. 调用时传 `--links "链接1,链接2"`（手动传入）
3. 两者会合并去重

**链接类型：**
- 项目名：Kraken、Memoria、ThreadVibe
- 技术名：Redis、ChromaDB、WebSocket
- 人物：Clara、毛仔、Vera

**索引文件：** `~/.qclaw/memoria/links.json`

---

## 运维

```bash
# 重建索引（增量模式，默认不删除现有数据）
python3 ~/.qclaw/skills/memoria/scripts/rebuild.py

# 重建索引（强制清空）
python3 ~/.qclaw/skills/memoria/scripts/rebuild.py --force

# Session 冷备份（cron 每天 23:30 自动执行）
python3 ~/.qclaw/skills/memoria/scripts/auto_archive.py
```

---

## 脚本说明

| 脚本 | 作用 |
|------|------|
| `store.py` | 统一写入入口（热缓存/冷存储/向量/链接） |
| `recall.py` | 检索入口（热缓存/向量搜索/标签匹配） |
| `auto_archive.py` | Session 冷备份（每天 23:30） |
| `rebuild.py` | 重建索引（运维用） |
| `lib/` | 公共模块（archive/vector/hot_cache/links） |

---

## 依赖

- **Ollama**：本地 LLM
  - `bge-m3` — 向量化（只用这个，不调用3b模型）
- **ChromaDB**：向量数据库（`pip3 install chromadb`）

---

## 数据状态

```
当前数据量：
- Archive: 94 条
- 向量库: 94 条
- 热缓存: 94 条
- Links: 49 个
- Sessions备份: 8 个
```

---

## 废弃脚本

`scripts/_deprecated/` 目录下有旧版本脚本，暂时保留备份。