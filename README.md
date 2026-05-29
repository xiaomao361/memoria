# Memoria v6 — AI Agent 通用记忆系统

> 跨会话记忆持久化。SQLite + 向量语义检索 + Markdown 文件存储。

## 简介

Memoria 是一个为 AI Agent 设计的通用记忆系统。任何 agent 都可以通过 CLI 或 HTTP API 读写记忆。

- **语义检索** — Ollama bge-m3 向量搜索，自然语言查询
- **全文搜索** — SQLite FTS5 降级搜索
- **关系索引** — 标签 + `[[双向链接]]` 统一为 labels
- **共享记忆元数据** — kind / authority / retrieval_role / confidence / lifecycle status / agent provenance
- **候选记忆审核流** — agent 输出先进入 candidate staging，再审核提升为 durable memory
- **Agent trust policy** — 通过 agents registry 控制 direct write / candidate staging / read-only
- **Web 管理** — 中文控制台 + 上下文包 / 候选审核 / 代理策略 / 力导向图谱
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
- **结构化上下文** — 调用 `recall_context()`，按硬约束 / 当前状态 / 既有决策 / 参考资料分组展示
- **候选区** — 查看待审核候选，支持接收 / 驳回 / 丢弃，支持手工补录候选
- **代理** — 查看与注册 agents，配置信任级别、受限读取、正式写入能力
- **图谱** — 力导向关系图（拖拽/缩放/双击跳转）
- **标签** — 所有标签云（点击过滤）
- **全部** — 全部记忆列表
- **受限内容** — 单独确认后加载受限记忆

---

## 使用方式

详见 `SKILL.md`。

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v6.8 | 2026-05-29 | Web 管理台升级为共享记忆控制台：新增结构化上下文、候选区审核、代理策略视图，并完成中文化文案收口 |
| v6.7 | 2026-05-29 | 共享 agent 记忆 Phase 3：新增 agents registry 与 agent trust policy，支持 agent-store 自动路由到 durable memory 或 candidate |
| v6.6 | 2026-05-28 | 共享 agent 记忆 Phase 2：新增 memory_candidates 审核流，支持 candidate add/list/accept/reject 与对应 API |
| v6.5 | 2026-05-28 | 共享 agent 记忆 Phase 1：新增记忆类型、权威性、召回角色、置信度、生命周期状态、source_agent/source_run_id，并保持 Markdown 重建兼容 |
| v6.4 | 2026-05-15 | 治理三轴：importance 重算 + suggest-conflicts + nightly 一键维护；修复 dormant SQL 优先级 bug |
| v6.3 | 2026-05-14 | 合并记忆标签迁移；graph 统一到 core；Web 分页；restore/purge；图谱 hover；export/import |
| v6.2 | 2026-05-13 | 标签过滤（排除私密+归档）；标签大小写统一；Web 标签页全量加载 |
| v6.1 | 2026-05-13 | Web 管理界面优化（中文化 + 图谱集成 + UI 美化） |
| v6.0 | 2026-05-13 | 架构重构：SQLite + ChromaDB + Ollama bge-m3 |
| v5.4 | 2026-05-09 | links 孤立引用清理 |
| v5.0 | 2026-04-20 | Strengthen Layer + 主动召回 |
| v4.0 | 2026-04-14 | 双向链接 + 增量更新 |
| v3.0 | 2026-04-10 | 向量库上线 |

## 当前建议

- `maintain classify-metadata` 目前适合先用 `--dry-run` 预览，再按公开区小批量应用。
- 这轮优化后，推荐优先使用 `candidate`、`agent-store`、`agent-recall`、`recall-context` 四条新入口。
