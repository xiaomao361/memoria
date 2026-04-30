# CHANGELOG — Memoria 记忆系统

所有重要变更记录在此，按时间倒序。

---

## [v5.2] — 2026-04-30

### ✨ 新增功能

- **写入去重（短期窗口）**：1小时内相似度≥80%的内容自动合并，避免单次对话重复写入
- **标签自动归一化**：所有标签自动转小写，解决 "Clara/clara" 大小写混乱问题
- **CLI 管理工具套件**：
  - `manage.py` — 记忆列表/统计/重复检测/删除/合并/标签管理
  - `cleanup_dupes.py` — 批量清理重复记忆（基于相似度+时间窗口）
  - `normalize_tags.py` — 标签大小写统一与合并
- **Web 管理界面**：FastAPI + 纯前端，支持浏览/搜索/删除/标签编辑

### 📊 数据清理成果

- 清理前：299条记忆
- 清理后：285条记忆
- 删除重复：14组（多为迁移遗留的带前缀ID与纯UUID重复）
- 标签归一：94条（统一为小写）

---

## [v5.1] — 2026-04-23

### 🐛 Bug 修复

- **私密热缓存架构对齐**：私密记忆现在正确写入 `private/memoria.json`，与公开架构完全对齐
- **dream.py 链接访问 Bug**：`links.raw` → `links` 直接访问，修复 links sync 分析逻辑
- **dream.py 摘要 Key Bug**：修复 `missing_previews` 中 `summary` key 不存在时的 fallback
- **demote 变量 Bug**：`demote_stale_memories()` 中使用 `entries` 替代错误的 `memories` 变量
- **recall.py dormant 兼容**：`_reactivate_from_dormant()` 同时兼容新旧热缓存格式
- **recall.py 内容获取**：修复私密记忆 archive 内容获取路径（自动加 `private/` 前缀）
- **build_graph.py 路径**：从 `~/.qclaw/memoria/` 移入 `scripts/` 目录，与其他脚本同目录
- **store.py 私密热缓存**：删掉 `if not private:` 条件，私密写入同样写热缓存

### ✨ 新增功能

- **私密 graph 重建**：`dream.py --execute` 后自动重建公开 + 私密 graph.json
- **scan_private_memories.py**：私密记忆独立扫描脚本
- **dream.py --rebuild-graph**：新增独立命令行参数，可单独重建 graph.json
- **SKILL.md recall 新参数**：`--private`、`--recent N`、`--include-private`

### 📖 文档

- 新增 `docs/ARCHITECTURE.md`（v5.0+ 完整架构文档）
- 删除所有 `_deprecated/` 废弃脚本和旧设计文档

---

## [v5.0] — 2026-04-20

### ✨ 重大功能

- **Strengthen Layer（重要度加权层）**：记忆按 importance_score 动态强化（+0.05/次，间隔≥7天），上限 1.0
- **主动召回（proactive_recall）**：每日 10:00 检查重要记忆（importance ≥ 0.3，≥20天未召回），主动推送飞书
- **月度摘要**：每月末（28-31日）自动汇总当月记忆，生成 `archive/monthly/` 月度报告

### 🔧 架构变更

- **热缓存格式重构**：从 `{"memories": [...]}` 数组格式迁移到 top-level dict 格式（memory_id 直接作 key），提升读写效率
- **新增字段**：`importance_score`、`last_strengthened`、`last_recalled`、`recall_count`
- **Strengthen Layer cron**：每日 02:00 执行，与 Dream Layer 整合

---

## [v4.3] — 2026-04-17

### ✨ 功能

- **Dream Layer 三层架构正式上线**：Extract（每次对话）→ Dream（每日 02:00）→ Refine（每周日 03:00）→ Demote（每周六 04:00）
- **沉睡机制**：30天未访问的记忆自动降权沉睡至 `dormant/`，保留全文 + 双向链接，可唤醒
- **私密记忆区完善**：私密记忆独立存储（archive、links、memoria.json），`--private` 参数支持
- **向量索引同步清理**：记忆降权 dormant 时，自动删除 ChromaDB 向量记录，重新唤醒时补写
- **cron 任务群**：6 个定时任务全部配置完成，静默运行

---

## [v4.0] — 2026-04-14

### ✨ 重大功能

- **双向链接系统**：`links.json` 双向链接索引，支持 `[[链接名]]` 语法
- **增量更新**：同一 session_id 多次"记一下" → 追加到已有记忆（version 递增），而非新建
- **Session 冷备份**：对话结束后自动备份 session JSON 到 `sessions_backup/`
- **统一 store/recall 入口**：所有记忆操作统一通过 `store.py` 和 `recall.py`

---

## [v3.0] — 2026-04-10

### ✨ 重大功能

- **向量库上线**：ChromaDB + bge-m3 模型，支持语义搜索
- **三层存储架构**：热缓存（50条）→ 向量库 → 冷备份（archive TXT）

---

_更早版本（v1.0 - v2.x）略，详见 git log_
