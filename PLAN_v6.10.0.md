# Memoria v6.10.0 升级记录

> 2026-06-16 | 基于 Mem0 / MemPalace 等参考项目的可落地改进

## 范围

两个特性，增量升级。`6.9.1` → `6.10.0`

| # | 特性 | 来源参考 | 复杂度 | 优先级 |
|---|------|---------|--------|--------|
| 1 | BM25 多信号检索 | Mem0 多信号融合 | 中 | P0 |
| 2 | MCP 常驻进程包装器 | MemPalace/Mem0 MCP Server | 中 | P0 |

---

## 1. BM25 多信号检索

### 现状

`_recall_by_query` 原来用 RRF 融合两个信号：
- **向量**（ChromaDB cosine → 归一化分数 → 按 rank 转 RRF）
- **FTS5**（MATCH 排序 → 按 rank 转 RRF）

问题：两者都只用了 **rank position**，丢了**原始分数**的信息量。FTS5 内置 `bm25()` 函数可以直接返回 BM25 分数，比 rank 更精确。

### 改法

三个信号各自产出归一化分数，加权融合：

| 信号 | 实现 | 来源 |
|------|------|------|
| 语义向量 | 现有 `search_vectors()` 返回 cosine 分数 | 不变 |
| BM25 关键词 | FTS5 `bm25(memories_fts)` 返回原始 BM25 × 归一化 | 增强现有 `_recall_fts_ids` |
| 实体匹配 | 查询文本提取关键词 → 匹配 `labels` 表 → overlap 计数归一化 | 新增 |

**核心改动在 `core.py` `_recall_by_query`**：
1. 向量搜索：现有逻辑不变
2. FTS5 搜：改为 `SELECT id, bm25(memories_fts) AS score FROM memories_fts WHERE memories_fts MATCH ? ORDER BY score`，返回实际 BM25 分数后做 min-max 归一化
3. 实体匹配：从查询文本中提取可能的 tag 关键词，直接匹配 `labels` 表，匹配数归一化后进入融合分
4. 三个信号加权融合（权重：向量 0.4, BM25 0.35, 实体 0.25）
5. 查询翻页按 `limit + offset` 取足候选，避免深翻页时只有前两页有结果

### 不改的
- 不引入外部 BM25 库（rank_bm25 等）
- 不改变 Schema
- FTS5 无结果时保留 LIKE fallback
- `_recall_by_tags` / `_recall_recent` 保持直接 SQLite 查询

### 文件改动
- `memoria/core.py`：`_recall_by_query` + `_recall_fts_ids` 增强
- `memoria/db.py`：无需改动（FTS5 已建索引，`bm25()` 是内置函数）

---

## 2. MCP 常驻进程包装器

### 动机

CLI 每次调用都要启动 Python 进程并重新加载依赖。MCP 用 stdio 常驻进程，让 Claude Code 等客户端可以复用同一个服务入口调用 Memoria。

统一接口：Clara / ClaraVision / Codex / 任何 agent 都可以通过标准 MCP protocol 调 Memoria。

### 架构

```
CLI (cli.py) ─────保持不变────→ core.py
                                    │
FastAPI (server/app.py) ─保持不变─→ core.py
                                    │
MCP (server/mcp.py) ───新增─────→ core.py
```

全部复用 `core.py` 的 API，不重写逻辑。

### 选型

使用 `mcp` Python 包：
- stdio transport（给 Claude Code 挂 MCP server 的标准方式）
- 每个 MCP tool 直接映射到 `core.py` 的函数
- 业务逻辑仍只在 `core.py` 里维护

### 暴露的工具

| MCP Tool | 对应 core 函数 | 参数 |
|----------|---------------|------|
| `memoria_store` | `store()` | content, tags, source, private, kind, source_agent... |
| `memoria_recall` | `recall()` | query, tags, limit, private, include_content... |
| `memoria_get` | `get_memory()` | memory_id |
| `memoria_delete` | `delete_memory()` | memory_id, purge |
| `memoria_restore` | `restore_memory()` | memory_id |
| `memoria_stats` | `get_stats()` | — |
| `memoria_labels` | `get_labels()` | limit, include_private |
| `memoria_tag` | `update_tags()` | memory_id, add, remove |

### 文件改动
- `server/mcp.py`：新增 MCP stdio 服务入口
- `requirements-mcp.txt`：新增，仅 `mcp` 一个依赖

### 使用方式

```bash
# 启动（给 Claude Code 配置 MCP server）
conda run -n zhouwei python3 server/mcp.py

# Claude Code settings.json 里加：
# { "mcpServers": { "memoria": { "command": "conda", "args": ["run", "-n", "zhouwei", "python3", "/path/to/server/mcp.py"] } } }
```

---

## 版本

- `__init__.py`：`6.9.1` → `6.10.0`
- `server/app.py`：version string 同步
- `README.md` / `docs/ARCHITECTURE.md` / `SKILL.md`：同步 v6.10.0 说明

## 不做

- ❌ ADD-only 模式（不合适，毛仔已确认）
- ❌ 三层存储翼/房间/抽屉（量级没到）
- ❌ 知识图谱（太沉）
- ❌ 记忆溯源 episode 关联（tag 已够用）

## 验收

1. BM25：`memoria recall --query "JVM内存优化"` 召回相关度高于当前 RRF 两信号版本
2. MCP：Claude Code 通过 MCP 调 `memoria_store` + `memoria_recall` 正常
3. 现有 CLI 和 FastAPI 不受影响
4. 查询翻页：超过 20 条匹配时，第 3 页及后续页面仍能返回结果
