# Memoria v6 — AI Agent 通用记忆系统

> 跨会话记忆持久化。SQLite + 向量语义检索 + Markdown 文件存储。

## 简介

Memoria 是一个为 AI Agent 设计的通用记忆系统。任何 agent 都可以通过 CLI 或 HTTP API 读写记忆。

- **语义检索** — Ollama bge-m3 向量搜索，自然语言查询
- **全文搜索** — SQLite FTS5 降级搜索
- **关系索引** — 标签 + `[[双向链接]]` 统一为 labels
- **Web 管理** — 中文界面 + 力导向图谱可视化
- **可重建** — 所有索引从 store/*.md 文件重建

---

## 架构

```
~/.qclaw/memoria/
├── store/                    # 唯一真实来源（Markdown 文件）
│   ├── 2026-05/
│   │   └── {uuid}.md
│   └── private/
│       └── 2026-05/
│           └── {uuid}.md
├── memoria.db                # SQLite（元数据 + 关系 + FTS5）
├── vectors/                  # ChromaDB 向量索引（可重建）
│   ├── public/
│   └── private/
└── backups/                  # session 备份（保留）
```

**代码位置：** `~/.qclaw/skills/memoria/`

```
memoria/                      # Python 包
├── config.py                 # 配置
├── core.py                   # store() / recall() / manage() 统一入口
├── db.py                     # SQLite 操作
├── vector.py                 # ChromaDB + Ollama embedding
├── filestore.py              # store/*.md 文件读写
└── maintain.py               # 维护任务
server/
├── app.py                    # FastAPI Web 服务
└── static/index.html         # 前端
cli.py                        # CLI 入口
migrate.py                    # v5 → v6 迁移工具
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10 (conda: zhouwei) |
| 元数据 | SQLite 3.45 (WAL mode) |
| 向量 | ChromaDB 1.5.9 |
| Embedding | Ollama bge-m3 (1024 维, 本地) |
| Web | FastAPI + uvicorn |
| 文件格式 | Markdown + YAML front matter |

---

## 核心流程

### 写入

```
store(content, tags, source, private)
    ├─ 1. 写 store/{month}/{uuid}.md
    ├─ 2. 写 SQLite (memories + labels + FTS)
    └─ 3. 写向量 (Ollama embedding → ChromaDB)
```

### 检索

```
recall(query)     → 向量语义搜索 → SQLite 补全信息
recall(tags)      → SQLite JOIN labels 精确匹配
recall(id)        → SQLite 直接定位
recall(limit=N)   → SQLite ORDER BY created_at DESC
```

### 维护

```
maintain rebuild       → 从 store/*.md 重建 SQLite + 向量
maintain suggest-merge → 向量相似度找合并候选
maintain dormant       → >30天未召回 → archived=1
```

---

## 与 v5 的区别

| 方面 | v5 | v6 |
|------|----|----|
| 代码量 | 7500 行 / 25 文件 | 1659 行 / 8 文件 |
| 存储 | 4 层手动同步 | SQLite + ChromaDB（索引可重建） |
| 向量 | ChromaDB 内置模型（错误） | Ollama bge-m3 显式 embedding |
| 热缓存 | memoria.json (200条) | SQLite 查询（无上限） |
| 双向链接 | links.json 手动维护 | labels 表 SQL JOIN |
| 一致性 | 四层同步易出幽灵节点 | 文件是真实来源，索引可重建 |
| Web | 需要单独安装 fastapi | 内置 |

---

## 依赖

- **Ollama**: `bge-m3` 模型（embedding）
- **Python 包**: chromadb, fastapi, uvicorn, requests, pydantic

---

## Web 管理界面

启动：
```bash
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/server/app.py --port 8000
```

浏览器访问 `http://localhost:8000`，功能：

- **概览** — 统计卡片 + 最近记忆
- **搜索** — 语义搜索（bge-m3）
- **图谱** — 力导向关系图（拖拽/缩放/双击跳转）
- **标签** — 所有标签云（点击过滤）
- **全部** — 全部记忆列表

---

## 使用方式

详见 `SKILL.md`。

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v6.3 | 2026-05-14 | 合并记忆标签迁移；graph 统一到 core；Web 分页；restore/purge；图谱 hover；export/import |
| v6.2 | 2026-05-13 | 标签过滤（排除私密+归档）；标签大小写统一；Web 标签页全量加载 |
| v6.1 | 2026-05-13 | Web 管理界面优化（中文化 + 图谱集成 + UI 美化） |
| v6.0 | 2026-05-13 | 架构重构：SQLite + ChromaDB + Ollama bge-m3 |
| v5.4 | 2026-05-09 | links 孤立引用清理 |
| v5.0 | 2026-04-20 | Strengthen Layer + 主动召回 |
| v4.0 | 2026-04-14 | 双向链接 + 增量更新 |
| v3.0 | 2026-04-10 | 向量库上线 |
