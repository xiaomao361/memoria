---
name: memoria
description: |
  Clara 的记忆增强插件。跨会话记忆持久化与智能召回。
  当用户提到"记住"、"这个重要"、"之前说过"、"你还记得吗"，
  或需要持久化跨会话信息时使用。
  
  多 Claw 兼容：支持通过环境变量配置独立数据路径。
metadata:
  openclaw:
    emoji: "🧠"
---

# Memoria — 记忆之网

> 个人知识库，跨平台、跨会话、永不遗忘。

---

## 核心定位

Memoria 是**周维的个人知识库**，与 OpenClaw 原生记忆系统并行：

| 系统 | 目标 | 形态 |
|------|------|------|
| **OpenClaw 原生** | 让 AI 回答更准 | 对话上下文注入 |
| **Memoria** | 让周维的知识可管理 | 事件/主题/渠道网状索引 |

---

## 三层存储架构

```
┌─────────────────────────────────────────────────────────┐
│  索引层（memoria.json）                                  │
│  → 精华摘要 + 标签 + 渠道 + 存储类型 + 引用路径           │
│  → 检索唯一入口，轻量快速                                │
├─────────────────────────────────────────────────────────┤
│  热存储（session 引用）                                  │
│  → 指向 OpenClaw 原生 sessions/*.jsonl                   │
│  → 默认方案，依赖 OpenClaw 的清理策略                    │
├─────────────────────────────────────────────────────────┤
│  冷存储（archive/）                                      │
│  → 重要内容永久备份，按年月归档                           │
│  → 防止 session 被清理时丢失                             │
└─────────────────────────────────────────────────────────┘
```

**存储类型标识：**
- 🔥 `hot` — 仅热存储（session 引用）
- 🧊 `cold` — 仅冷存储（archive 备份）
- ❄️ `cold+hot` — 双存储（重要内容）

---

## 写入触发

| 触发方式 | 时机 | 存储类型 |
|----------|------|----------|
| **用户指令** | "记住 xxx"、"这个重要" | 默认 hot，可指定 `--archive` |
| **Heartbeat** | 定期评估当前对话 | 默认 hot |
| **讨论深度** | 同一话题 >3 轮 | 建议 `--archive` |

---

## 读取策略

```
新对话启动
    ↓
recall.py --simple → 注入最近 7 天摘要（轻量）
    ↓
对话中提及历史 → recall.py --id <id> --full → 展开全量
```

**全量展开优先级：**
1. 优先读 `cold_path`（archive/）— 永久保留
2. Fallback 读 `session_path` — 可能被清理

---

## 多 Claw 兼容

通过环境变量实现多个 Claw 独立使用：

```bash
# Clara（默认）
python3 ~/.qclaw/skills/memoria/scripts/recall.py

# Vera（独立数据）
export MEMORIA_DIR=~/.qclaw/agents/vera/memoria
export WORKSPACE=~/.qclaw/agents/vera/workspace
python3 ~/.qclaw/skills/memoria/scripts/recall.py
```

| 环境变量 | 作用 | 默认值 |
|----------|------|--------|
| `MEMORIA_DIR` | 数据存储路径 | `~/.qclaw/skills/memoria` |
| `WORKSPACE` | 配置注入目标 | `~/.qclaw/workspace` |

---

## 使用接口

### 写入记忆

```bash
# 基础写入（热存储）
python3 ~/.qclaw/skills/memoria/scripts/remember.py \
  --channel feishu \
  --tags "副业,规划" \
  --session-label "副业方案讨论" \
  --summary "讨论了每月增加3000收入的方案，考虑技术内容变现"

# 重要内容（同时冷存储备份）
python3 ~/.qclaw/skills/memoria/scripts/remember.py \
  --channel webchat \
  --tags "架构,重要" \
  --session-label "Memoria架构重构" \
  --summary "确定三层存储架构：索引+热存储+冷存储" \
  --archive
```

### 检索记忆

```bash
# 默认检索（最近7天，最多5条，简化格式）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --simple

# 详细格式（含存储类型图标）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 14 --limit 10

# 按标签筛选
python3 ~/.qclaw/skills/memoria/scripts/recall.py --tags "副业,技术"

# 关键词搜索
python3 ~/.qclaw/skills/memoria/scripts/recall.py --keyword "架构"

# 展开全量
python3 ~/.qclaw/skills/memoria/scripts/recall.py --id <记忆ID前8位> --full
```

---

## 数据格式

### 索引条目（memoria.json）

```json
{
  "id": "uuid-v4",
  "timestamp": "2026-03-30T14:00:00+08:00",
  "channel": "feishu",
  "tags": ["副业", "规划"],
  "summary": "讨论了每月增加3000收入的方案...",
  "session_id": "session-uuid",
  "session_path": "/path/to/session.jsonl",
  "cold_path": "/path/to/archive/2026-03/feishu_label_xxxx.json",
  "session_label": "副业方案讨论",
  "message_count": 12,
  "storage_type": "cold+hot"
}
```

### 冷存储格式（archive/YYYY-MM/）

```json
{
  "archived_at": "2026-03-30T14:00:00+08:00",
  "channel": "feishu",
  "session_label": "副业方案讨论",
  "session_id": "session-uuid",
  "message_count": 12,
  "messages": [
    {"role": "user", "text": "...", "timestamp": "..."},
    {"role": "assistant", "text": "...", "timestamp": "..."}
  ]
}
```

---

## 安装与集成

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/xiaomao361/memoria/main/install.sh | bash

# 手动集成到其他 Claw
export WORKSPACE=~/.qclaw/agents/vera/workspace
python3 ~/.qclaw/skills/memoria/scripts/integrate_with_claw.py
```

---

## 路线图

- [x] 三层存储架构（索引 + 热存储 + 冷存储）
- [x] 多 Claw 兼容（环境变量配置）
- [x] 标签 + 渠道 + 关键词检索
- [ ] 向量语义搜索（二期）
- [ ] 多 Claw 记忆共享策略（二期）
- [ ] 自动归档策略（定期将旧 session 备份到 archive）

---

## License

MIT
