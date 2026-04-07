# Memoria 存储设计文档

> 本文档记录 Memoria 记忆系统的存储架构设计
> 适用于: v4.0+
> 最后更新: 2026-04-07

---

## 1. 概述

Memoria 是 Clara 的记忆系统，采用多级存储架构：

- **热缓存**: 快速访问的记忆入口（FIFO 淘汰）
- **向量库**: 语义搜索能力（持久化）
- **文本存储**: 最终的内容载体（持久化）
- **冷备份**: 防止 session 数据丢失（独立模块）

---

## 2. 存储介质

### 2.1 热缓存 (memoria.json)

| 属性 | 值 |
|------|-----|
| 路径 | `~/.qclaw/memoria/memoria.json` |
| 格式 | JSON |
| 容量 | 可配置，默认 200 条 |
| 淘汰策略 | FIFO（按创建时间） |
| 刷新方式 | 实时写入 |

**每条记录结构**:
```json
{
  "id": "uuid",
  "timestamp": "2026-04-07T10:00:00Z",
  "channel": "feishu",
  "tags": ["标签1", "标签2"],
  "links": ["链接1", "链接2"],
  "summary": "一行摘要，给热缓存快速扫描用",
  "source": "manual",
  "memory_id": "uuid",
  "archive_path": "2026-04/memory_id.txt",
  "session_id": "session_uuid",
  "storage_type": "hot"
}
```

### 2.2 向量库 (chroma_db/)

| 属性 | 值 |
|------|-----|
| 路径 | `~/.qclaw/memoria/chroma_db/` |
| 用途 | 语义搜索 |
| 模型 | bge-m3 |
| embedding 维度 | 1536 |
| embedding 输入 | content 前 512 字（截断，保证搜索质量） |
| document 存储 | content 全文（不截断） |

**metadata 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `memory_id` | string | 对应 archive TXT 的 memory_id |
| `archive_path` | string | TXT 文件路径，深度回溯原文 |
| `timestamp` | string | 创建时间（ISO 8601） |
| `source` | string | `manual` 或 `proactive` |
| `tags` | string | 逗号拼接，ChromaDB 不支持数组 |
| `links` | string | 逗号拼接 |
| `session_id` | string | 可选，关联的 session |

### 2.3 双向链接索引 (links.json)

| 属性 | 值 |
|------|-----|
| 路径 | `~/.qclaw/memoria/links.json` |
| 用途 | 通过标签快速查找关联记忆 |
| 增长方式 | 只增不减（永久知识图谱） |

**结构**:
```json
{
  "标签名": ["memory_id_1", "memory_id_2"],
  "kraken": ["abc123", "def456"],
  "memoria": ["xyz789"]
}
```

### 2.4 重要内容归档 (archive/)

| 属性 | 值 |
|------|-----|
| 路径 | `~/.qclaw/memoria/archive/{YYYY-MM}/` |
| 用途 | 有价值的记忆内容（永久存储） |
| 格式 | TXT（YAML front matter + Markdown 正文） |

**文件命名**: `{memory_id}.txt`

> 使用 UUID 作为文件名，保证唯一且无特殊字符。标题放在 front matter 的 `title` 字段（从 content 自动提取）。

**TXT 完整格式**:
```markdown
---
memory_id: <uuid>
created: 2026-04-07T10:00:00Z
source: manual | proactive
tags: [标签1, 标签2]
links: [链接1, 链接2]
session_id: <可选>
version: 1
---

## 摘要
一两句话概括核心内容。

## 背景
为什么聊这个（可选，没有就删掉这个区块）。

## 要点
- 关键点 1
- 决策：xxx
- 方案选择：xxx

## 后续
- 待做：xxx
- 相关：[[链接1]], [[链接2]]
```

**Front Matter 字段说明**:

| 字段 | 来源 | 说明 |
|------|------|------|
| `memory_id` | store() 生成 | UUID |
| `created` | store() 生成 | UTC 时间 |
| `source` | 调用方传入 | `manual` 或 `proactive` |
| `tags` | Clara 传 pre_tags | 数组 |
| `links` | 从 content 提取 `[[xxx]]` | 数组，自动去重 |
| `session_id` | 可选 | 关联的 session |
| `version` | store() 生成 | 初始为 1，增量更新时递增 |

**正文区块规则**:
- **摘要**: 必填。一两句话。
- **背景**: 可选。有就写，没有就不写。
- **要点**: 必填。核心内容，用列表。
- **后续**: 可选。有待办或关联就写。
- 不限制固定区块，可按需扩展（如「技术方案」「决策记录」），store() 不做硬校验。

### 2.5 Session 冷备份 (sessions_backup/)

| 属性 | 值 |
|------|-----|
| 路径 | `~/.qclaw/memoria/sessions_backup/{YYYY-MM}/` |
| 用途 | 防止 OpenClaw 清理 sessions 导致对话丢失 |
| 内容 | 原始 session JSONL |
| 策略 | 覆盖最新全量 |
| **独立性** | **完全独立模块，不涉及记忆写入流程** |

**文件命名**: `{session_id}_{timestamp}.jsonl`

---

## 3. 目录结构

```
~/.qclaw/memoria/
├── memoria.json           # 热缓存（FIFO 淘汰）
├── links.json             # 双向链接索引（只增不减）
├── chroma_db/             # 向量库（持久化）
│   └── ...
├── archive/               # 重要内容归档（持久化）
│   └── {YYYY-MM}/
│       └── {title}-{id}.txt
└── sessions_backup/       # Session 冷备份（独立模块）
    └── {YYYY-MM}/
        └── {session_id}_{timestamp}.jsonl
```

---

## 4. 写入场景

### 4.1 触发机制（当前实现）

| 层级 | 触发方式 | 判断者 | content 来源 |
|------|---------|--------|-------------|
| **手动** | 用户说"记一下"、"单独记" | 用户明确 | Clara 在对话中生成 |
| **主动** | Clara 判断有价值 → 询问用户确认 | Clara（对话中） | Clara 在对话中生成 |

> **cron 自动触发暂不实现**，待基础链路跑通后再补充。
> 详见 [MEMORIA_WRITE_DESIGN.md](./MEMORIA_WRITE_DESIGN.md)。

### 4.2 统一写入入口

所有触发最终调用同一个 `store()` 函数，区别仅在 content 的来源和是否需要用户确认。

### 4.3 Session 冷备份

完全独立于记忆写入流程，由独立 cron 任务处理，不写入 memoria.json / 向量库 / links.json。

---

## 5. 读取链路

### 5.1 三条路径

```
memoria.json（热缓存）
    │
    ├─→ links.json（通过标签找确定的关联记忆）
    │       │
    │       └─→ archive/{id}.txt（直接定位原文）
    │
    └─→ chroma_db 向量（通过语义相似找相关记忆）
            │
            └─→ archive/{id}.txt（深度回溯原文）
```

### 5.2 路径对比

| 路径 | 原理 | 目的 |
|------|------|------|
| **links** | 标签匹配（`[[xxx]]`） | 找**确定关联**的记忆 |
| **向量** | 语义相似度 | 找**可能相关**的记忆 |
| **最终** | 都去 archive/ 读原文 | 深度回溯 |

---

## 6. 增量更新方案

### 6.1 场景

同一个主题的记忆可能有多个碎片（如 Memoria 项目的多次讨论），需要支持增量更新而非重复创建。

### 6.2 方案：向量相似度阈值

```
新归档内容
    ↓
bge-m3 向量化 → 搜索 chroma_db → Top 3 相似记忆
    ↓
cosine 相似度 ≥ 0.85？
    ├→ 是 → 判定属于已有记忆 → 追加
    └→ 否 → 新主题 → store() 新建
```

### 6.3 追加策略

增量更新逻辑**在 store() 外部**，作为独立层处理。store() 只管"写新的"。

```
追加到已有记忆：
  1. 读出 archive TXT（front matter + 正文）
  2. 在正文末尾追加新区块：
     ---
     ## 追加 (2026-04-08)
     - 新要点...
     - 新决策...
  3. 合并 tags（去重）
  4. 合并 links（去重）
  5. version +1
  6. 重写 TXT → 更新向量（新 embedding）→ 更新热缓存 → 更新 links
```

> **暂不实现**，待基础写入链路跑通后补充。阈值 0.85 为初始值，跑一段时间后根据效果调参。

---

## 7. 热缓存刷新机制

### 7.1 写入时机

**实时刷新**：每次 store() 完成后，立即更新 memoria.json。

### 7.2 淘汰策略

**FIFO（按时间）**：
- 新写入的放在列表头部
- 超过容量后，删除列表尾部（最旧的）
- 读取不影响顺序（纯读操作）
- 淘汰只影响热缓存，archive TXT 和向量库不受影响

### 7.3 容量配置

- 默认值：200 条
- 可通过配置调整

---

## 8. 写入原子性

### 8.1 优先级

```
1. 写 archive TXT（front matter + 正文）  ← 核心，必须成功
2. 写 chroma_db（向量 + metadata）       ← 重要，持久化
3. 写 memoria.json（热缓存条目）         ← 重要，FIFO 会清，失败可 rebuild
4. 写 links.json（增量更新）             ← 最轻量，失败影响最小
```

### 8.2 失败策略

- 每步独立 try/catch，**不回滚**前面已成功的步骤
- 失败记日志，不中断流程
- store() 返回四步各自的成败状态

### 8.3 rebuild 命令

```bash
# 扫描 archive/ TXT → 重建热缓存 + 向量库 + links 索引
python3 scripts/rebuild.py
```

---

## 9. tags/links 来源

### 9.1 当前方案（v4.0 精简）

| 元素 | 来源 | 说明 |
|------|------|------|
| **tags** | Clara 传 pre_tags | Clara 在对话中全程在场，上下文最全 |
| **links** | content 中的 `[[xxx]]` | Clara 生成 content 时写入，store() 自动提取 |

> 不依赖本地模型生成 tags/links。Clara 对对话的理解比 3B 模型更准确。
> 未来 cron 自动触发时，可引入本地模型补充 tags/links 生成。

### 9.2 扩展预留

当 cron 自动触发上线后，tags/links 的生成可引入 qwen2.5:3b 本地模型，从 session 内容推断。prompt 设计待后续讨论。

---

## 10. 后续待讨论

### 读取侧
- [ ] recall 完整实现（热缓存 → 向量搜索 → links → archive 原文）
- [ ] rebuild 命令实现
- [ ] 配置文件设计（如需）

### 写入侧（后续迭代）
- [ ] cron 自动触发实现
  - [ ] session 扫描策略（最近 N 小时变更）
  - [ ] 价值判断逻辑（二分类：有价值 / 无价值）
  - [ ] 3B 模型生成摘要 + tags
- [ ] 增量更新实现
  - [ ] 相似度阈值调参
  - [ ] 追加逻辑实现
- [ ] tags/links prompt 设计（cron 场景）

---

*本文档由 Clara 编写，基于 2026-04-07 的架构讨论成果更新*
 - [ ] 3B 模型生成摘要 + tags
- [ ] 增量更新实现
  - [ ] 相似度阈值调参
  - [ ] 追加逻辑实现
- [ ] tags/links prompt 设计（cron 场景）

---

*本文档由 Clara 编写，基于 2026-04-07 的架构讨论成果更新*
