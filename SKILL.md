---
name: memoria
description: |
  AI Agent 通用记忆系统 v6.10.0。跨会话记忆持久化与智能召回。BM25 多信号检索 + MCP 常驻进程。
  当用户提到"记住"、"这个重要"、"之前说过"、"你还记得吗"，
  或需要持久化跨会话信息时使用。
metadata:
  openclaw:
    emoji: "🧠"
---

# Memoria v6 使用指南

> 通用 Agent 记忆系统。SQLite + 向量语义检索，一条命令读写。

---

## 环境

所有命令使用 conda 环境：
```bash
conda run -n zhouwei python3 cli.py <command>
```

---

## 写入记忆

当以下情况发生时，**必须**写入 memoria：
1. 用户做了决定（"那就这么定了"、"先按这个来"）
2. 项目有进展（跑通、报错、做完、发现问题）
3. 用户说了关于自己/项目/别人的重要事实
4. 用户明确表达了情绪或偏好时，只记录“用户表达了什么”，不要记录 Agent 对关系或信任的推断
5. 用户说"记一下"

Memoria 只保存可观察事实。不要把“用户信任 Agent”“关系更近”“用户依赖 Agent”
这类解释当成事实写入；这类当前接续位置应该放在 Continuity。

```bash
# 基本写入
conda run -n zhouwei python3 cli.py store \
  --content "要记录的内容" \
  --tags "tag1,tag2"

# 带共享 agent 记忆元数据写入
conda run -n zhouwei python3 cli.py store \
  --content "用户决定先做 Phase 1 元数据基础。" \
  --tags "memoria,decision" \
  --kind decision \
  --authority user_decision \
  --retrieval-role hard_constraint \
  --source-agent codex

# 私密写入
conda run -n zhouwei python3 cli.py store \
  --content "私密内容" \
  --tags "tag1" \
  --private

# 合并写入（将多条旧记忆合并为一条新的）
conda run -n zhouwei python3 cli.py store \
  --content "合并后的内容" \
  --tags "tag1" \
  --merge-from "old_id1,old_id2"
```

**内容格式建议：**
- 使用 `[[链接名]]` 标记关联实体（项目名、人名、技术名），标签和链接均自动小写化
- 内容中可包含 `## 摘要` 段落，系统会自动提取为 summary
- 不需要写 front matter，系统自动生成

---

## 检索记忆

```bash
# 语义搜索（最常用）
conda run -n zhouwei python3 cli.py recall \
  --query "关键词或自然语言描述"

# 标签搜索
conda run -n zhouwei python3 cli.py recall \
  --tags "kraken,项目"

# 精确查找
conda run -n zhouwei python3 cli.py recall \
  --id "uuid"

# 最近 N 条
conda run -n zhouwei python3 cli.py recall \
  --limit 20

# 搜索私密区
conda run -n zhouwei python3 cli.py recall \
  --query "关键词" --private

# 包含全文
conda run -n zhouwei python3 cli.py recall \
  --query "关键词" --with-content

# 包含已归档
conda run -n zhouwei python3 cli.py recall \
  --query "关键词" --include-archived

# 按生命周期状态召回
conda run -n zhouwei python3 cli.py recall \
  --limit 20 --include-statuses "active,pinned"

# 旧数据元数据回填：建议先 dry-run，再按公开区小批量应用
conda run -n zhouwei python3 cli.py maintain classify-metadata \
  --dry-run --public-only --limit 50

# 只读质量审计：汇总摘要、来源、元数据、候选队列、疑似合并/冲突等信号
conda run -n zhouwei python3 cli.py maintain audit-quality \
  --public-only --limit 20

# 历史来源回填：按 source=clara/codex/lara/hermes 回填 source_agent，并修正旧 manual 默认值
conda run -n zhouwei python3 cli.py maintain backfill-source-agent \
  --dry-run --include-private --limit 0
```

---

## 管理

```bash
# 系统统计
conda run -n zhouwei python3 cli.py stats

# 查看所有公开活跃标签
conda run -n zhouwei python3 cli.py labels

# 包含私密标签
conda run -n zhouwei python3 cli.py labels --include-private

# 获取单条详情
conda run -n zhouwei python3 cli.py get <uuid>

# 删除（软删除，标记为 archived）
conda run -n zhouwei python3 cli.py delete <uuid>

# 恢复已归档记忆
conda run -n zhouwei python3 cli.py restore <uuid>

# 永久删除（不可恢复）
conda run -n zhouwei python3 cli.py delete --purge <uuid>

# 管理标签
conda run -n zhouwei python3 cli.py tag <uuid> --add "new_tag" --remove "old_tag"
```

---

## 治理三轴

| 轴 | 动作 | 命令 | 决策方 |
|------|----|------|------|
| 强度 | 升 | `maintain recompute-importance` | 自动 |
| 强度 | 降 | `maintain dormant` | 自动 |
| 数量 | 合 | `maintain suggest-merge` → `store --merge-from` | LLM 判断 |
| 数量 | 删 | `delete` / `delete --purge` | LLM / 人工 |
| 内容 | 改 | `maintain suggest-conflicts` → `tag --add outdated` 或重写 | LLM 判断 |

`maintain nightly` 一次性跑完自动部分，产出待裁决候选清单。

### 推荐 cron

```bash
# 每天凌晨 3 点
0 3 * * *  conda run -n zhouwei python3 cli.py maintain nightly > /Users/zhouwei/.claracore/memoria/logs/nightly-$(date +\%F).json 2>&1
```

外部 agent（openclaw 等）读取 JSON 中的 `review` 部分，二次裁决后通过 store/delete/tag 命令落地。

---

## 维护

```bash
# 从 store/*.md 重建 SQLite + 向量索引（幂等，可反复执行）
conda run -n zhouwei python3 cli.py maintain rebuild

# 查找可合并的相似记忆
conda run -n zhouwei python3 cli.py maintain suggest-merge

# 沉睡降权（>30天未召回的记忆标记为 archived）
conda run -n zhouwei python3 cli.py maintain dormant
conda run -n zhouwei python3 cli.py maintain dormant --dry-run

# 重要度重算（基于 recall_count + 时效衰减）
conda run -n zhouwei python3 cli.py maintain recompute-importance
conda run -n zhouwei python3 cli.py maintain recompute-importance --half-life 30 --dry-run

# 冲突候选（同标签 + 中等相似度 + 时间跨度大，仅产清单）
conda run -n zhouwei python3 cli.py maintain suggest-conflicts

# 一键夜间维护：自动跑 importance + dormant，并产出 merge / conflict 候选清单
conda run -n zhouwei python3 cli.py maintain nightly
conda run -n zhouwei python3 cli.py maintain nightly --dry-run

# 质量审计（只读，不修改数据）
conda run -n zhouwei python3 cli.py maintain audit-quality --public-only --limit 20
conda run -n zhouwei python3 cli.py maintain audit-quality --skip-review-candidates
conda run -n zhouwei python3 cli.py maintain audit-quality --include-private --limit 20

# 来源治理（先 dry-run）
conda run -n zhouwei python3 cli.py maintain backfill-source-agent --dry-run --include-private --limit 0
```

### nightly 输出结构

```json
{
  "ran_at": "...",
  "dry_run": false,
  "auto": {
    "importance": { "scanned": N, "updated": N, "top": [...] },
    "dormant":    { "count": N, "samples": [...] }
  },
  "review": {
    "merge_candidates":    [{ "ids": [...], "score": 0.90, "summaries": [...] }],
    "conflict_candidates": [{ "older": id, "newer": id, "score": 0.78, "gap_days": 25, "shared_labels": [...] }]
  }
}
```

`auto` 部分 CLI 自动执行；`review` 部分需要外部 LLM agent 二次判断后通过 `store --merge-from` / `delete` / `tag` 落地。

---

## 导入导出

```bash
# 导出所有公开记忆为 JSON
conda run -n zhouwei python3 cli.py export -o backup.json

# 导出私密记忆（含已归档）
conda run -n zhouwei python3 cli.py export -o backup.json --private --include-archived

# 从 JSON 文件导入
conda run -n zhouwei python3 cli.py import backup.json
```

---

## Web 管理界面

```bash
conda run -n zhouwei python3 server/app.py --port 8000
# 访问 http://localhost:8000
```

功能：
- 概览 / 语义搜索 / 记忆图谱 / 标签云 / 全部记忆
- 受限内容：单独确认后加载受限记忆

---

## MCP 常驻进程

```bash
conda run -n zhouwei python3 server/mcp.py
```

给 Claude Code 等 MCP 客户端挂载时使用。工具包括写入、检索、读取详情、删除、恢复、标签管理、统计和标签列表。

---

## 查询优先级

| 场景 | 方法 |
|------|------|
| 用户问"之前/上次/还记得" | `recall --query "关键词"` |
| 需要某个项目的所有记忆 | `recall --tags "项目名"` |
| 需要精确某条记忆 | `recall --id "uuid"` |
| 新会话开始时 | `recall --limit 10`（最近 10 条） |

---

## 架构简述

```
store/*.md  →  唯一真实来源（人类可读 Markdown）
memoria.db  →  SQLite（元数据 + 关系 + FTS5 全文搜索）
vectors/    →  ChromaDB + Ollama bge-m3（语义检索，可重建）
```

- 写入：文件 → SQLite → 向量，三步独立
- 索引损坏时 `maintain rebuild` 从文件重建
- 日常命令通过 `cli.py` 入口
- Web 管理通过 `server/app.py` 提供 REST API + 前端
- MCP 常驻进程通过 `server/mcp.py` 提供 stdio 工具
