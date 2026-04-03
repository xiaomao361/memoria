# Memoria 更新通知

> 日期：2026-04-03
> 作者：Clara
> 致：Vera、Iris、Nova

---

## 背景

今天主要完成了两件事：**工作区文件整理** 和 **记忆写入规则升级**。另外周维那边做了脑科体检 PDF 脚本的优化，Memoria 侧无代码变更但文档有更新。

---

## 记忆写入规则升级（核心变更）

原有的记忆写入只有一条路径（`remember.py` → 热缓存），现在拆分为两条路径，由 AGENTS.md 里的规则自动判断：

### 路径一：`remember.py` → 热缓存（日常琐事）
用于：口味偏好、临时想法、日常小事、趣事吐槽
特点：写入 `memoria.json`，50条后轮转，轻量快速

### 路径二：`archive_important.py` → 冷存储 + 向量化（重要内容）
用于：项目文档、重要决策、技术方案、长期计划
特点：写入 `archive/` + ChromaDB 向量库，永久可检索

### 判断逻辑

```
用户说"记一下" → 内容会涉及未来工作/项目吗？
  → 是 → archive_important.py
  → 否 → remember.py

用户说"单独记"/"全量记"/"这个很重要要长期保留"
  → archive_important.py（无条件）
```

### 配套新增脚本

| 脚本 | 用途 |
|------|------|
| `scripts/archive_important.py` | 手动触发冷存储写入 + 向量化 |
| `scripts/recall_with_context.py` | 搜索时自动获取 archive 原文（不只是摘要） |
| `scripts/get_archive.py` | 通过向量 ID 获取冷存储原文 |

---

## 工作区文件整理

### 整合（7个 → 3个）

| 旧文件 | 新位置 |
|--------|--------|
| IDENTITY.md | → SOUL.md |
| MOOD.md | → SOUL.md |
| MIDNIGHT.md | → SOUL.md |
| INNER.md | 精简后保留 |
| HEARTBEAT.md | 精简后保留 |
| VISUAL.md | 新增（翻译+改名） |

### 删除（9个）

- `avatars/` 目录
- `memory/AELOVIA.md`
- `memory/ARCHIVE.md`
- `memory/COMMUNICATION.md`
- `memory/LOCAL_MODEL_PLAN.md`
- `memory/my-journal.md`
- `memory/notes.md`
- `memory/Kraken项目.md`

以上内容已归档到 `~/.qclaw/skills/memoria/archive/`，不会丢失。

---

## 项目状态

| 项目 | 状态 | 说明 |
|------|------|------|
| 热缓存 | ✅ 正常 | 最近50条，启动时自动加载 |
| 向量库 | ✅ 正常 | 语义检索可用 |
| 冷存储 | ✅ 正常 | 全量历史归档 |
| 归档规则 | ✅ 正常 | 每日 23:30 自动执行 |

---

## 待测试（请 Vera 验证）

1. **记忆写入规则**：请在新会话里测试几种说法，确认走对了路径：
   - 「记一下，我不吃香菜」→ 应走 `remember.py`（热缓存）
   - 「单独记一下，XX很重要」→ 应走 `archive_important.py`（冷存储）
   - 「记一下，Kraken 用 Redis 做队列」→ 应走 `archive_important.py`（冷存储）

2. **recall_with_context.py**：搜索"之前"的记忆时，确认能自动拉出 archive 原文而不仅是摘要

---

## 致谢

今天的整理主要是周维主导的，他在工作区里折腾了大半天 😅 三位织影如果有想法随时可以提。

— Clara
