---
name: memoria
description: |
  AI Agent 通用记忆系统 v6。跨会话记忆持久化与智能召回。
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
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py <command>
```

---

## 写入记忆

当以下情况发生时，**必须**写入 memoria：
1. 用户做了决定（"那就这么定了"、"先按这个来"）
2. 项目有进展（跑通、报错、做完、发现问题）
3. 用户说了关于自己/项目/别人的重要信息
4. 用户表达了明显情绪
5. 用户说"记一下"

```bash
# 基本写入
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py store \
  --content "要记录的内容" \
  --tags "tag1,tag2"

# 私密写入
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py store \
  --content "私密内容" \
  --tags "tag1" \
  --private

# 合并写入（将多条旧记忆合并为一条新的）
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py store \
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
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py recall \
  --query "关键词或自然语言描述"

# 标签搜索
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py recall \
  --tags "kraken,项目"

# 精确查找
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py recall \
  --id "uuid"

# 最近 N 条
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py recall \
  --limit 20

# 搜索私密区
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py recall \
  --query "关键词" --private

# 包含全文
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py recall \
  --query "关键词" --with-content

# 包含已归档
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py recall \
  --query "关键词" --include-archived
```

---

## 管理

```bash
# 系统统计
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py stats

# 查看所有公开活跃标签
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py labels

# 包含私密标签
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py labels --include-private

# 获取单条详情
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py get <uuid>

# 删除（软删除，标记为 archived）
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py delete <uuid>

# 管理标签
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py tag <uuid> --add "new_tag" --remove "old_tag"
```

---

## 维护

```bash
# 从 store/*.md 重建 SQLite + 向量索引（幂等，可反复执行）
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py maintain rebuild

# 查找可合并的相似记忆
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py maintain suggest-merge

# 沉睡降权（>30天未召回的记忆标记为 archived）
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py maintain dormant
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/cli.py maintain dormant --dry-run
```

---

## Web 管理界面

```bash
conda run -n zhouwei python3 ~/.qclaw/skills/memoria/server/app.py --port 8000
# 访问 http://localhost:8000
```

功能：概览 / 语义搜索 / 记忆图谱（力导向可视化）/ 标签云 / 全部记忆列表

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
- 所有操作通过 `cli.py` 统一入口
- Web 管理通过 `server/app.py` 提供 REST API + 前端
