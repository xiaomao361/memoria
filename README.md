# Memoria v6.9.1 — AI Agent 通用记忆系统

> 跨会话记忆持久化。SQLite + 向量语义检索 + Markdown 文件存储。

## 简介

Memoria 是一个为 AI Agent 设计的通用记忆系统。任何 agent 都可以通过 CLI 或 HTTP API 读写记忆。

- **语义检索** — Ollama bge-m3 向量搜索，自然语言查询
- **全文搜索** — SQLite FTS5 降级搜索
- **关系索引** — 标签 + `[[双向链接]]` 统一为 labels
- **共享记忆元数据** — kind / authority / retrieval_role / confidence / lifecycle status / agent provenance
- **RRF 混合检索** — 向量语义 + FTS5 全文并行搜索，Reciprocal Rank Fusion 融合排序
- **Web 管理** — 中文控制台 + 语义搜索 / 标签过滤 / 力导向图谱
- **可重建** — 所有索引从 store/*.md 文件重建

## 与 Continuity 的边界

Memoria 存可观察事实。Continuity 存这些事实在当前时刻形成的位置。

Memoria 应该保存：

- 明确发生过的事件
- 用户明确说过的话、决定和偏好
- 已验证的项目状态、路径、命令和结果
- 明确约定的后续工作方式

Memoria 不应该把 Agent 的解释长期保存为事实，例如“用户信任 Agent”“关系更近”
“用户依赖 Agent”。这些内容如果对当前续接有用，应该放在 Continuity 里，并且能
被复查、过期、关闭或由用户修正。

---

## 架构

```
/Users/zhouwei/.claracore/memoria/
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

**代码位置：** repository root

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
recall(query)     → RRF 混合检索（向量 + FTS 并行，RRF 融合 + importance 加权）
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
conda run -n zhouwei python3 server/app.py --port 8000
```

浏览器访问 `http://localhost:8000`，功能：

- **概览** — 统计卡片 + 最近记忆
- **搜索** — 语义搜索（bge-m3 RRF 混合检索）
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
| v6.9.1 | 2026-06-16 | RRF 混合检索（向量+FTS 并行 → RRF 融合 + importance 加权）；事实边界检查内置到 store()；移除 candidate/agent/recall-context（过度设计下沉到 Continuity 承接）；删除 adapters/、migrate.py；前端精简 |\n| v6.9 | 2026-06-01 | 标签别名系统、候选记忆审核流、Agent trust policy、状态生命周期完善；Web 控制台全面中文化 |
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

- `maintain classify-metadata` 使用保守规则识别 decision / preference / project_state / idea / person_context / conversation_summary / technical_note；先用 `--dry-run` 预览，再按公开区小批量应用。
- `classify-metadata --private-only` 目前只作为人工复核入口；私密关系和对话记录容易包含“状态、模型、必须”等非工程语境词，不建议无 review 批量应用。
- `maintain audit-quality` 是下一步清理前的只读入口，用来汇总摘要、来源、元数据、最近 source_agent 写入和 merge/conflict 候选。
- 标签治理现在支持 `/Users/zhouwei/.claracore/memoria/label_aliases.json` 别名归一；查询/写入会统一落到 canonical tag，可先用 `memoria labels --audit` 看疑似同义标签，再用 `memoria maintain canonicalize-labels --dry-run` 预览历史数据收口。
- 写入时 `core.store()` 会检查内容是否为可观察事实，如果包含推断性描述（信任、关系等），会在返回值中附加 `warnings` 字段提醒调用方应放到 Continuity 而不是 Memoria。
