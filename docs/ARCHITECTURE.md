# Memoria v6 架构设计文档

> 适用版本: v6.0+
> 最后更新: 2026-05-13

---

## 1. 设计原则

- **store/*.md 是唯一真实来源** — 所有索引（SQLite、向量）都可从文件重建
- **写入幂等** — 相同 ID 多次写入覆盖而非重复
- **索引与数据分离** — 索引损坏不丢数据，`maintain rebuild` 恢复
- **不内置 LLM 推理** — 系统只做存储+检索，聚合/提炼由调用方 agent 完成

---

## 2. 存储架构

```
~/.qclaw/memoria/
├── store/                    # 唯一真实来源
│   ├── {YYYY-MM}/           # 按月归档
│   │   └── {uuid}.md        # 每条记忆一个文件
│   └── private/             # 私密区（结构镜像）
│       └── {YYYY-MM}/
├── memoria.db                # SQLite 索引
└── vectors/                  # ChromaDB 向量索引
    ├── public/
    └── private/
```

### 2.1 文件格式 (store/*.md)

```markdown
---
id: {uuid}
created: 2026-05-13T10:00:00+00:00
source: manual
tags: ["tag1", "tag2"]
links: ["链接1", "链接2"]
private: false
archived: false
kind: decision
authority: user_decision
retrieval_role: hard_constraint
confidence: 1.0
status: active
source_agent: codex
source_run_id: run-2026-05-28
---

记忆正文内容...
```

### 2.2 SQLite Schema

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,        -- 前 200 字符
    content TEXT NOT NULL,        -- 全文
    source TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_recalled_at TEXT,
    recall_count INTEGER DEFAULT 0,
    importance REAL DEFAULT 0.0,
    private INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,   -- 0=活跃, 1=沉睡/已删除
    kind TEXT DEFAULT 'fact',
    authority TEXT DEFAULT 'confirmed',
    retrieval_role TEXT DEFAULT 'background',
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active', -- active / pinned / stale / superseded / conflicted / archived / discarded
    superseded_by TEXT,
    valid_from TEXT,
    valid_until TEXT,
    source_agent TEXT,
    source_run_id TEXT,
    file_path TEXT                -- store/ 下的相对路径
);

CREATE TABLE memory_candidates (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    summary TEXT,
    proposed_tags TEXT,
    proposed_kind TEXT,
    proposed_authority TEXT,
    proposed_retrieval_role TEXT,
    confidence REAL DEFAULT 0.7,
    source TEXT NOT NULL,
    source_agent TEXT,
    source_run_id TEXT,
    private INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT,
    promoted_memory_id TEXT
);

CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    trust_level TEXT NOT NULL DEFAULT 'candidate_only',
    can_read_private INTEGER DEFAULT 0,
    can_write_durable INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE labels (
    memory_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'tag',      -- tag / link
    UNIQUE(memory_id, name),
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    id UNINDEXED, summary, content, tokenize='unicode61'
);
```

### 2.3 向量库

| 属性 | 值 |
|------|-----|
| 引擎 | ChromaDB 1.5.9 |
| Embedding | Ollama bge-m3 (1024 维) |
| 输入 | summary + content 前 2000 字符 |
| 距离 | cosine |
| Collection | `memoria` (公开) / `memoria_private` (私密) |

---

## 3. 写入流程

```
core.store(content, tags, source, private)
    │
    ├─ 1. filestore.write_file()     → store/{month}/{uuid}.md
    ├─ 2. db: INSERT memories + labels + FTS
    └─ 3. vector.upsert_vector()     → Ollama embedding → ChromaDB
```

- 三步独立，任一步失败不影响其他
- 失败步骤通过 `maintain rebuild` 恢复

### 3.1 Candidate Review Flow

```
core.create_candidate(...)
    └─ INSERT memory_candidates(status='pending')

core.promote_candidate(candidate_id, ...)
    ├─ 1. 读取候选
    ├─ 2. 可选审核编辑
    ├─ 3. 复用 core.store(...) 写 durable memory
    └─ 4. 回写 memory_candidates.reviewed_* / promoted_memory_id
```

- agent 输出默认可以先进入 candidate staging
- candidate 不参与正常 recall
- durable memory 仍只通过 `store()` 落地，避免双写路径分叉

### 3.2 Agent Trust Routing

```
core.store_from_agent(agent_id, ...)
    ├─ 1. 读取 agents registry
    ├─ 2. 校验 trust_level / private 权限
    ├─ 3a. trusted_writer -> core.store(...)
    └─ 3b. candidate_only / private_allowed -> core.create_candidate(...)
```

规则：
- `trusted_writer` 且 `can_write_durable=1` 才允许 direct durable write
- `candidate_only` 默认进入候选区
- `read_only` 禁止写入
- `private_allowed` 当前仅放开私密访问能力，写入仍先进 candidate

## 4. Agent-Aware Recall

```
core.recall_for_agent(agent_id, ..., private=false)
    ├─ 1. 读取 agents registry
    ├─ 2. 若 private=true，则要求 can_read_private=1
    ├─ 3. public recall -> 仅查公开记忆
    ├─ 4. private recall -> 仅在显式请求时查私密记忆
    └─ 5. memory_id 查询同样经过 private gate
```

- 不显式请求 `private=true` 时，即使 agent 有权限，也只返回公开记忆
- `memory_id` 查询不会绕过私密检查

### 4.1 Structured Context Recall

```
core.recall_context(query, agent_id=None, project=None, private=false)
    ├─ 1. 复用 recall() / recall_for_agent() 拿到候选记忆
    ├─ 2. 按 include_kinds / exclude_statuses 过滤
    ├─ 3. 结合 semantic + authority + retrieval_role + confidence 重排
    └─ 4. 输出 context_pack
         ├─ hard_constraints
         ├─ current_state
         ├─ prior_decisions
         ├─ references
         ├─ background
         └─ forbidden_directions
```

- `recall_context()` 是给多 agent 协作准备的结构化召回层，不替代底层 `recall()`
- `/api/recall/context` 与 Web 管理台的“结构化上下文”视图都走这一路径
- 每条 context item 会返回 `reason / score / authority / retrieval_role / source_agent`

---

## 4. 检索流程

```
core.recall(query, tags, memory_id, limit, private)
    │
    ├─ memory_id → SQLite 直接定位
    ├─ tags      → SQLite JOIN labels
    ├─ query     → vector.search_vectors() → SQLite 补全
    │              ↓ (向量失败时降级)
    │              → SQLite FTS5 全文搜索
    └─ (无参数)  → SQLite ORDER BY created_at DESC
```

每次召回自动更新 `last_recalled_at` 和 `recall_count`。

---

## 5. 聚合/提炼设计

**系统不做 LLM 推理，只提供候选：**

```bash
# 系统找出相似记忆候选
cli.py maintain suggest-merge

# Agent 拿到候选后，用自身 LLM 能力生成合并内容，写回：
cli.py store --content "合并后内容" --merge-from "id1,id2,id3"
# 原始记忆自动标记 archived=1
```

---

## 6. 沉睡机制

- 条件：`last_recalled_at < 30天前` 或 `created_at < 30天前 AND 从未召回`
- 操作：`archived = 1`，向量索引删除
- 恢复：`recall --include-archived` 可查到，手动 store 重新写入即可
- 触发：`cli.py maintain dormant`

---

## 7. Web 管理台

当前 Web 界面已经从“记忆浏览器”升级为“共享记忆控制台”，覆盖以下工作流：

- 概览 / 搜索 / 图谱 / 标签 / 全部记忆
- 结构化上下文：验证 `recall_context()` 的分桶和排序结果
- 候选区：审核 `memory_candidates`，执行接收 / 驳回 / 丢弃
- 代理：查看与注册 `agents`，配置 trust level、受限读取、正式写入能力
- 受限内容：单独确认后查看受限记忆

---

## 7. Web API

FastAPI 服务，端口默认 8000：

```bash
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/server/app.py --port 8000
```

### REST API

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /api/memories | 列表（支持 query/tags/limit/private） |
| GET | /api/memories/:id | 详情 |
| POST | /api/memories | 创建 |
| DELETE | /api/memories/:id | 软删除 |
| PUT | /api/memories/:id/tags | 更新标签 |
| POST | /api/memories/merge | 合并 |
| GET | /api/labels | 所有标签 |
| GET | /api/search?q=xxx | 语义搜索 |
| GET | /api/stats | 统计 |
| GET | /api/graph | 关系图数据（动态生成） |

### 前端界面

中文单页应用，功能视图：

| 视图 | 功能 |
|------|------|
| 概览 | 统计卡片 + 最近记忆列表 |
| 搜索 | 语义搜索（bge-m3 向量匹配） |
| 图谱 | 力导向关系图可视化（Canvas 绘制，支持拖拽/缩放/双击跳转） |
| 标签 | 标签云，点击过滤 |
| 全部 | 全部记忆列表 |

---

## 8. 配置

集中在 `memoria/config.py`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| STORE_DIR | ~/.qclaw/memoria/store | 文件存储目录 |
| DB_PATH | ~/.qclaw/memoria/memoria.db | SQLite 路径 |
| VECTORS_DIR | ~/.qclaw/memoria/vectors | 向量索引目录 |
| OLLAMA_URL | http://localhost:11434 | Ollama 地址 |
| EMBEDDING_MODEL | bge-m3 | Embedding 模型 |
| EMBEDDING_DIM | 1024 | 向量维度 |
| EMBEDDING_MAX_CHARS | 2000 | Embedding 输入截断 |
| DORMANT_DAYS | 30 | 沉睡阈值天数 |

---

## 9. 目录结构

```
~/.qclaw/skills/memoria/
├── SKILL.md                  # Agent 使用指南
├── README.md                 # 项目说明
├── docs/ARCHITECTURE.md      # 本文档
├── memoria/                  # Python 包
│   ├── __init__.py
│   ├── config.py             # 配置
│   ├── core.py               # 核心逻辑（store/recall/manage）
│   ├── db.py                 # SQLite
│   ├── vector.py             # ChromaDB + Ollama
│   ├── filestore.py          # 文件读写
│   └── maintain.py           # 维护任务
├── server/
│   ├── app.py                # FastAPI REST API
│   └── static/index.html     # 中文前端（概览/搜索/图谱/标签/列表）
├── cli.py                    # CLI 入口
└── migrate.py                # v5 → v6 迁移
```
