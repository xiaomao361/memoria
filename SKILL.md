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

# Memoria — 记忆系统 v5.0

> 跨会话记忆，向量检索，双向链接，永不遗忘。
> 新增：Strengthen Layer（重要度加权） + 主动召回 + 月度摘要

---

## 架构

```
~/.qclaw/agents/main/sessions/*.jsonl   → 原始对话（OpenClaw 管理）
                    ↓
auto_archive.py    → 每天 23:30 冷备份（三层同时写入）
                    ↓
┌──────────────────────────────────────────────────────┐
│  ~/.qclaw/memoria/                                  │
│  ├── memoria.json         热缓存（容量200条）        │
│  ├── chroma_db/           向量索引（语义搜索）        │
│  ├── archive/             冷备份（全量历史）          │
│  ├── private/             私密记忆（独立存储）        │
│  │   ├── memories/archive/                          │
│  │   ├── memoria.json                               │
│  │   └── links.json                                 │
│  ├── links.json           双向链接索引（公开）        │
│  └── sessions_backup/     Session 备份              │
└──────────────────────────────────────────────────────┘
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

# 方式3：增量更新（同一 session 追加内容）
python3 ~/.qclaw/skills/memoria/scripts/store.py \
  --content "追加的内容" \
  --session-id "当前会话ID"
```

**写入流程（四步独立）：**
1. archive TXT → 冷备份
2. 向量库 → 语义索引
3. 热缓存 → 最近50条
4. links.json → 双向链接索引

**增量更新规则：**
- 同一 session-id 多次"记一下" → 追加到已有记忆（而不是新建）
- 不同 session-id → 新增独立记忆
- 返回结果中 `mode: "update"` 表示增量更新，`mode: "new"` 表示新建

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

# 包含沉睡记忆（默认只搜索活跃记忆）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --search "关键词" --include-dormant
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

**索引文件：**
- `~/.qclaw/memoria/links.json` — 公开记忆索引（含权重、保护标签）
- `~/.qclaw/memoria/private/links.json` — 隐私记忆索引

**双向索引结构：**
- `tags`: tag → [uuids]（哪些记忆关联这个标签）
- `entities`: uuid → {tags, weight, last_linked}（每个记忆的详情）
- 权重：每次关联标签时 weight +1，可查询热门记忆
- 保护标签：带有"长期项目/核心任务/重要"等标签的记忆不会被自动清理

---

## 运维

```bash
# 重建索引（扫描 archive/ 和 private/memories/，自动重建完整索引）
cd ~/.qclaw/skills/memoria/scripts && python3 -c "
from lib.links import rebuild_index
# 需手动调用重建逻辑
"

# 自动清理过期待办（dry_run 预览）
python3 -c "from lib.links import auto_cleanup_stale_todos; print(auto_cleanup_stale_todos(days=30, dry_run=True))"

# 自动清理（实际执行）
python3 -c "from lib.links import auto_cleanup_stale_todos; print(auto_cleanup_stale_todos(days=30, dry_run=False))"

# Session 冷备份（cron 每天 23:30 自动执行）
python3 ~/.qclaw/skills/memoria/scripts/auto_archive.py
```

---

## 脚本说明

| 脚本 | 作用 |
|------|------|
| `store.py` | 统一写入入口（热缓存/冷存储/向量/链接），支持增量更新 |
| `recall.py` | 检索入口（热缓存/向量搜索/标签匹配/重要度加权召回） |
| `dream.py` | Dream 层（扫描/修复/Strengthen/沉睡/梦境生成） |
| `auto_archive.py` | Session 冷备份（每天 23:30） |
| `rebuild.py` | 重建索引（热缓存/向量/链接全量重建） |
| `proactive_recall.py` | 主动召回（每日 10:00 推送 HEARTBEAT 边缘重要记忆） |
| `monthly_summary.py` | 月度摘要生成 |
| `lib/` | 公共模块（archive/vector/hot_cache/links/config） |

---

## 增量更新

**规则**：同一 session-id 多次"记一下" → 追加到已有记忆，而不是新建。

```bash
# 增量更新（同一 session 追加内容）
python3 ~/.qclaw/skills/memoria/scripts/store.py \
  --content "追加内容" \
  --tags "标签" \
  --session-id "当前会话ID"
```

返回结果中 `mode: "update"` 表示增量更新，`mode: "new"` 表示新建。

---

## 依赖

- **Ollama**：本地 LLM
  - `bge-m3` — 向量化（只用这个，不调用3b模型）
- **ChromaDB**：向量数据库（`pip3 install chromadb`）

---

## 数据状态

```
当前数据量（2026-04-21）：
- 热缓存 (公开): ~108 条
- 热缓存 (私密): 6 条
- Archive (公开): ~184 个文件
- Archive (私密): ~46 个文件
- 向量库 (公开): ~135 条
- Links (公开): 176 实体
- Links (私密): 46 实体
- DREAMS.md: 每日 02:00 自动更新
```

---

## Dream 层（自动整理）

Memoria v4.3 引入三层自动整理机制，解决"数据逐渐混乱"的问题：

| 层级 | 触发 | 功能 |
|------|------|------|
| **Extract** | 每次对话 | 即时写入记忆 |
| **Strengthen** | 每天 02:00 | 重要度加权（每次召回+0.05，间隔7天） |
| **Dream** | 每天 02:00 | 扫描问题 + 自动修复（静默运行） |
| **Refine** | 每周日 03:00 | 提炼重要内容到 MEMORY.md |
| **Demote** | 每周六 04:00 | 沉睡机制（降权长期未访问的记忆） |

**Dream 层执行命令：**

```bash
# 仅扫描，生成报告（不执行）
python3 ~/.qclaw/skills/memoria/scripts/dream.py --scan

# 扫描 + 执行安全修复
python3 ~/.qclaw/skills/memoria/scripts/dream.py --execute

# 完整执行（扫描 + 修复 + 生成梦境叙事）
python3 ~/.qclaw/skills/memoria/scripts/dream.py --full
```

**报告位置：** `~/.qclaw/memoria/DREAMS.md`

---

## 沉睡机制

超过 30 天未被检索的记忆，自动进入"沉睡"状态：

- 向量索引删除（节省空间）
- 文件仍保留在 archive/ 中
- 热缓存中标记为 `dormant: true`

**召回沉睡记忆：**

```bash
# 搜索时包含沉睡记忆
python3 ~/.qclaw/skills/memoria/scripts/recall.py --query "关键词" --include-dormant

# 预演降权（查看哪些记忆将被沉睡）
python3 ~/.qclaw/skills/memoria/scripts/dream.py --demote

# 执行降权
python3 ~/.qclaw/skills/memoria/scripts/dream.py --demote --execute
```

**保护标签（自动清理时跳过）：**
- `长期项目`, `核心任务`, `重要`, `keep`
- 手动添加保护标签：记重要内容时加 `--tags "长期项目"`

---

## 废弃脚本

`scripts/_deprecated/` 目录下有旧版本脚本，暂时保留备份。