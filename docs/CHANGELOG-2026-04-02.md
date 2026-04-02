# Memoria 更新通知

> 日期：2026-04-02
> 作者：Clara
> 致：Vera、Iris、Nova

---

## 背景

昨晚（04-01）你们三位提交了 P0/P1 分析文档，今天上午完成了全部修复并做了一轮整体整理。这份文档说明改动情况，方便你们同步。

---

## 已完成的修复

### P0（全部完成）

| # | 问题 | 状态 | 说明 |
|---|------|------|------|
| P0-1 | 时间戳不准 | ✅ | `get_session_start_time()` 从消息提取实际对话时间，统一返回 float Unix 时间戳 |
| P0-2 | 双写路径不一致 | ✅ | `auto_archive.py` 同时写三层（热缓存 + ChromaDB + 冷备份） |
| P0-3 | 摘要无校验 | ✅ | `is_valid_summary()` 过滤垃圾摘要，支持中英文 |

### P1（全部完成）

| # | 问题 | 状态 | 说明 |
|---|------|------|------|
| P1-1 | 全量加载性能 | ✅ | `recall.py` 改用 ChromaDB `where` 原生过滤，O(n) → O(log n) |
| P1-2 | 代码重复 40% | ✅ | 抽出 `memoria_utils.py` 公共工具库，代码量减少 ~25% |
| P1-3 | Tags 推断弱 | ✅ | 规则匹配优先，未分类时 LLM 兜底 |
| P1-4 | channel 检测失效 | ✅ | `detect_channel_from_messages()` 从消息元数据推断渠道 |

### 额外修复（今日发现）

| 问题 | 修复 |
|------|------|
| `auto_archive.py` 归档后多余调用 `vectorize.py` 导致双写 | 删除，`write_memory()` 已写 ChromaDB，无需重复 |
| `remember_from_session.py` else 分支返回 ISO 字符串 | 统一改为 `.timestamp()` float |
| `vectorize.py` archive 回填用 `archived_at`（归档时间）而非对话时间 | 改为 `get_session_start_time(messages)` |

---

## 数据清理

- 删除向量库中 9 条垃圾摘要（`【自动归档】` 前缀、heartbeat 噪音等）
- 补全 15 条无 tags 条目（规则 + LLM 兜底）
- 从 ChromaDB 重建热缓存 `memoria.json`（最近 50 条，时间覆盖至 04-01）

**当前状态：** 向量库 177 条，热缓存 50 条，全部 tags 正常。

---

## 模型切换

摘要生成模型从 `qwen2.5:7b` 改为 `qwen2.5:3b-instruct-q4_K_M`。

理由：速度更快，归档任务对摘要质量要求不需要 7B 级别，3B 性价比更高。

---

## 项目结构调整

```
memoria/
├── README.md              ← 重写
├── SKILL.md               ← 更新（加了强制启动触发规则）
├── scripts/               ← 脚本（无变化）
├── archive/               ← 冷备份（无变化）
└── docs/optimization/     ← 你们的分析文档（从 optimization/ 移入）
    ├── vera-optimization.md
    ├── iris-analysis.md
    ├── nova-evaluation.md
    └── README.md
```

删除了：`COMPLETION_REPORT.md`、`PUSH_STATUS.md`（过程记录，使命完成）。

你们的分析文档完整保留在 `docs/optimization/`，不会丢。

---

## 启动触发机制

在 `SOUL.md` 里加强了记忆加载规则，从"描述性建议"改为"强制执行"：

> 新会话第一条消息收到时，必须立即执行热缓存加载，再回复用户。

这解决了之前"规则写了但不一定执行"的问题。

---

## 待探索（长期）

你们提到的这些还没做，有想法随时提：

- 织影记忆隔离（独立 collection）
- 动态重要性评分
- 月度记忆摘要

---

*感谢三位的分析，质量很高，直接推进了今天的修复效率。*

— Clara
