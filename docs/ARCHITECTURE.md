# Memoria 架构设计文档

> 适用版本: v5.0+
> 最后更新: 2026-04-21

---

## 1. 概述

Memoria 是一个 AI Agent 记忆系统，提供跨会话记忆持久化、语义检索、重要度加权、自动整理能力。

核心设计原则：
- **Archive 是唯一真实来源**：所有可恢复存储（向量库、热缓存、链接索引）都从 archive 重建
- **写入幂等**：相同内容多次写入不会产生重复
- **每步独立失败**：四步写入中任一步失败不影响其他步骤，失败步骤可通过 rebuild 恢复

---

## 2. 存储架构

### 2.1 五层存储

```
┌─────────────────────────────────────────────────────────┐
│  ~/.qclaw/memoria/                                      │
│                                                         │
│  ┌─ 公开区 ──────────────────────────────────────────┐  │
│  │  memoria.json        热缓存（top-level dict）      │  │
│  │  chroma_db/          向量索引（语义搜索）          │  │
│  │  archive/            冷备份（全量历史）            │  │
│  │  links.json          双向链接索引                  │  │
│  │  sessions_backup/    Session 冷备份                │  │
│  └────────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─ 私密区 ──────────────────────────────────────────┐  │
│  │  private/                                          │  │
│  │  ├── memoria.json     私密热缓存                  │  │
│  │  ├── memories/        私密归档                     │  │
│  │  │   └── archive/     按月归档                     │  │
│  │  └── links.json       私密链接索引                 │  │
│  └────────────────────────────────────────────────────┘  │
│                                                         │
│  DREAMS.md            梦境整理报告                      │
│  dream/               梦境叙事归档                      │
│  dream_log.json       Dream 层执行日志                  │
└─────────────────────────────────────────────────────────┘
```

### 2.2 各层详解

#### 热缓存 (memoria.json)

| 属性 | 值 |
|------|-----|
| 格式 | JSON，top-level dict（key = memory_id） |
| 容量 | 200 条（可配置 `HOT_CACHE_CAPACITY`） |
| 淘汰 | FIFO（按创建时间，容量满时删最旧） |
| 用途 | 新会话启动时快速加载上下文 |

**条目结构**：

```json
{
  "memory_id": {
    "summary": "一行摘要",
    "tags": ["标签1", "标签2"],
    "links": ["链接1", "链接2"],
    "timestamp": "2026-04-21T10:00:00Z",
    "source": "manual",
    "session_id": "optional-session-uuid",
    "storage_type": "hot",
    "archive_path": "2026-04/memory_id.txt",
    "dormant": false,
    "importance_score": 0.0,
    "recall_count": 0,
    "last_strengthened": null,
    "last_recalled": "2026-04-21T10:00:00Z"
  }
}
```

> v5.0 起格式为 top-level dict（之前是 `{"memories": [...]}` 数组格式，已废弃）。
> `read_hot_cache()` 会自动检测旧格式并迁移。

#### 向量库 (chroma_db/)

| 属性 | 值 |
|------|-----|
| 引擎 | ChromaDB |
| 模型 | BAAI/bge-m3 |
| embedding 输入 | content 前 512 字符 |
| document 存储 | content 全文 |

**metadata 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| memory_id | string | 对应 archive 文件 |
| archive_path | string | TXT 相对路径 |
| timestamp | string | 创建时间 |
| source | string | manual / proactive / dream |
| tags | string | 逗号拼接（ChromaDB 不支持数组） |
| links | string | 逗号拼接 |

#### 归档 (archive/)

| 属性 | 值 |
|------|-----|
| 路径 | `{YYYY-MM}/{memory_id}.txt` |
| 格式 | YAML front matter + Markdown 正文 |
| 性质 | **唯一真实来源**，所有可恢复存储从此重建 |

**TXT 格式**：

```markdown
---
memory_id: <uuid>
created: 2026-04-21T10:00:00Z
source: manual | proactive | dream
tags: [标签1, 标签2]
links: [链接1, 链接2]
session_id: <可选>
version: 1
---

## 摘要
一两句话概括。

## 背景
（可选）

## 要点
- 关键点
- 决策：xxx
- 相关：[[链接1]], [[链接2]]

## 后续
（可选）
```

> 支持 `[[链接名]]` 语法，store() 自动提取并写入 links 索引。

#### 双向链接索引 (links.json)

```json
{
  "entities": {
    "memory_id": {
      "tags": ["tag1", "tag2"],
      "weight": 3,
      "last_linked": "2026-04-21T10:00:00Z",
      "protected": false
    }
  },
  "tags": {
    "tag1": ["memory_id_1", "memory_id_2"],
    "tag2": ["memory_id_3"]
  },
  "uuids": {}
}
```

- `entities`: 每个 memory 的标签、权重、保护状态
- `tags`: 标签 → memory_id 反向索引
- `weight`: 每次关联 +1，可查询热门记忆
- `protected`: 带保护标签的记忆不会被自动清理

#### 私密区 (private/)

结构与公开区镜像，但完全独立：
- 独立的热缓存、归档、链接索引
- recall 默认不搜索私密区（需显式指定 `--include-private`）
- store 时通过 `private: true` 标记写入私密区

---

## 3. 写入流程

### 3.1 统一入口 store()

```
store(content, tags, links, source, session_id, private)
    │
    ├─ Step 1: 写 archive TXT（核心，必须成功）
    ├─ Step 2: 写向量库
    ├─ Step 3: 写热缓存（初始化 importance_score 字段）
    └─ Step 4: 写 links 索引
```

每步独立 try/catch，不回滚。失败步骤可通过 `rebuild.py` 恢复。

### 3.2 增量更新

同一 session_id 多次写入 → 追加到已有记忆（version 递增），而非新建。

### 3.3 触发方式

| 方式 | 触发 | content 来源 |
|------|------|-------------|
| 手动 | 用户说"记一下" | Agent 在对话中生成 |
| 主动 | Agent 判断有价值 → 确认 | Agent 在对话中生成 |

---

## 4. 读取流程

### 4.1 三条路径

```
recall(tags=["xxx"])       → links.json 精确匹配（快）
recall(query="xxx")        → chroma_db 语义搜索（中）+ importance 重排序
recall(memory_id="xxx")    → archive TXT 直接定位（慢）
```

### 4.2 重要度加权召回（v5.0）

recall 结果按重要度重排序：

```
final_score = vector_similarity × (1.0 + importance_score × RECALL_BONUS)
```

- `RECALL_BONUS = 0.5`，最高 ×1.5 封顶
- 每次召回自动递增 recall_count
- 重要度评分公式：保护标签×0.3 + 高频召回×0.2 + 近期召回×0.2 + 手动标记×0.3

---

## 5. Dream 层（自动整理）

| 层级 | 触发 | 功能 |
|------|------|------|
| Extract | 每次对话 | 即时写入记忆 |
| Strengthen | 每天 02:00 | 重要记忆加强（+0.05，间隔7天） |
| Dream | 每天 02:00 | 扫描问题 + 自动修复 |
| Refine | 每周日 03:00 | 提炼重要内容到长期记忆 |
| Demote | 每周六 04:00 | 沉睡机制（>30天未访问） |

执行顺序：Strengthen → Dream → Demote（先加强后降权）。

### 5.1 Strengthen Layer

找出 `importance_score ≥ 0.3` 且距离上次加强 ≥7天 的记忆，`importance_score += 0.05`。

### 5.2 沉睡机制

>30天未召回的记忆自动沉睡：
- 向量索引删除
- 热缓存标记 `dormant: true`
- archive 文件保留
- 带保护标签的记忆跳过

### 5.3 保护标签

```
长期项目、核心任务、重要、项目、keep、不清理、
Kraken、bi项目、doctor项目、长期、保命、永久
```

保护标签的记忆不会被自动清理或降权。

---

## 6. 主动召回

`proactive_recall.py` 每天 10:00 执行：

1. 扫描热缓存中 `importance_score ≥ 0.3` 且最近未被召回的记忆
2. 生成 "最近想起了..." 格式的 HEARTBEAT 推送
3. 通过 OpenClaw cron 发送到 Agent 对话

---

## 7. 月度摘要

`monthly_summary.py` 按月生成归档摘要：

- 统计记忆数量、活跃天数、Top 标签
- 兼容旧迁移格式和新标准格式的 archive 文件
- 输出 Markdown 格式到 `archive/{YYYY-MM}_月度摘要.md`

---

## 8. 运维工具

### 8.1 rebuild.py

全量重建（从 archive 重建其他存储）：

| 重建目标 | 数据来源 |
|---------|---------|
| chroma_db | archive TXT 正文 |
| memoria.json | archive TXT front matter |
| links.json | archive TXT front matter |

幂等操作，可反复执行。

### 8.2 migrate.py

格式迁移工具，处理旧版本到新版本的数据格式转换。

### 8.3 管理工具套件（v5.2+）

**CLI 工具**（`scripts/` 目录）：

| 脚本 | 功能 | 常用命令 |
|------|------|----------|
| `manage.py` | 记忆管理 | `list`, `stats`, `dupes`, `delete <id>`, `merge <id1> <id2>`, `tag <id> --add/--remove` |
| `cleanup_dupes.py` | 批量去重 | `--dry-run` 预览, `--execute` 执行删除 |
| `normalize_tags.py` | 标签归一 | 统一转小写，合并大小写变体 |

**Web 管理界面**：
- 启动：`python3 scripts/web_server.py --port 8080`
- 功能：浏览记忆列表、搜索、删除、标签编辑
- 技术：FastAPI + 纯前端（无框架依赖）

**去重策略**：
- 短期窗口：1小时内相似度≥80%自动合并
- 批量清理：基于时间窗口+相似度检测历史重复

---

## 9. 配置

所有配置集中在 `scripts/lib/config.py`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `HOT_CACHE_CAPACITY` | 200 | 热缓存容量上限 |
| `IMPORTANCE_THRESHOLD` | 0.3 | 加强门槛 |
| `IMPORTANCE_WEIGHT_TAGS` | 0.3 | 保护标签权重 |
| `IMPORTANCE_WEIGHT_RECALL` | 0.2 | 高频召回权重 |
| `IMPORTANCE_WEIGHT_RECENT` | 0.2 | 近期召回权重 |
| `IMPORTANCE_WEIGHT_MANUAL` | 0.3 | 手动标记权重 |
| `IMPORTANCE_STRENGTHEN_STEP` | 0.05 | 每次加强量 |
| `IMPORTANCE_STRENGTHEN_GAP_DAYS` | 7 | 加强间隔天数 |
| `IMPORTANCE_RECALL_BONUS` | 0.5 | recall 加成系数 |
| `EMBEDDING_MODEL` | BAAI/bge-m3 | 向量模型 |
| `EMBEDDING_MAX_CHARS` | 512 | embedding 截断长度 |
| `SIMILARITY_THRESHOLD` | 0.85 | 增量更新相似度阈值 |

---

## 10. 目录结构

```
scripts/
├── store.py              # 写入入口
├── recall.py             # 检索入口（含重要度重排序）
├── dream.py              # Dream 层（扫描/修复/Strengthen/沉睡/梦境）
├── rebuild.py            # 全量重建
├── auto_archive.py       # Session 冷备份
├── proactive_recall.py   # 主动召回
├── monthly_summary.py    # 月度摘要
├── migrate.py            # 格式迁移
├── lib/
│   ├── config.py         # 配置
│   ├── hot_cache.py      # 热缓存读写
│   ├── archive.py        # 归档解析
│   ├── vector.py         # 向量操作
│   ├── links.py          # 链接索引
│   └── utils.py          # 工具函数
docs/
└── ARCHITECTURE.md       # 本文档
```

---

*本文档由 Clara 编写，反映 v5.2 实际实现*
