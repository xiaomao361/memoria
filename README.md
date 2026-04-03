# Memoria

Clara 的跨会话记忆系统。基于本地 LLM + ChromaDB 向量检索，让每次对话都能记住上次聊了什么。

---

## 架构

```
sessions/*.jsonl
      ↓
auto_archive.py（每晚 23:30）
      ↓
┌─────────────────────────────────────┐
│ memoria.json   热缓存，最近 50 条    │  ← 新会话默认加载
│ ChromaDB       向量索引，语义搜索    │  ← recall --search
│ archive/       冷备份，全量历史      │  ← 永久保留
└─────────────────────────────────────┘
      ↓
recall.py（快速检索，只返回摘要）
recall_with_context.py（深度检索，自动获取原文）
```

三层存储各司其职：热缓存快、向量库准、冷备份全。

---

## 快速开始

```bash
# 新会话启动时加载记忆
python3 scripts/recall.py --hot-cache --simple

# 搜索特定话题（只返回摘要）
python3 scripts/recall.py --search "kraken 项目"

# 深度搜索（自动获取 archive 原文）
python3 scripts/recall_with_context.py --search "本地模型计划"

# 查看最近 7 天
python3 scripts/recall.py --recent --days 7
```

---

## 自动化

每晚 23:30 自动归档（OpenClaw cron 任务）：

```bash
python3 scripts/auto_archive.py
```

扫描当天所有 sessions → 生成摘要 → 同时写入三层存储。无需其他定时任务。

---

## 手动记录

**写入路径判断：**

| 用户说法 | 内容类型 | 调用脚本 | 存储 |
|----------|----------|----------|------|
| 「记一下」+ 日常琐事/喜好 | 偏好、趣事、日常 | `remember.py` | 热缓存（50条轮转） |
| 「记一下」+ 项目/技术/决策 | 方案、待办、约定 | `archive_important.py` | 冷存储 + 向量化 |
| 「单独记」「全量记」「这个很重要」 | 任何 | `archive_important.py` | 冷存储 + 向量化 |

```bash
# 记下来（写入热缓存，日常琐事）
python3 scripts/remember.py --channel webchat --summary "xxx" --tags "tag1,tag2"

# 单独记一下（写入 archive + 向量化，重要内容）
python3 scripts/archive_important.py --project "项目名" --content "要记录的内容"
```

---

## 向量化

通常由 `auto_archive.py` 自动触发，无需手动。特殊情况：

```bash
# 增量（只处理新增/变更的 session）
python3 scripts/vectorize.py

# 从历史归档回填（首次部署或数据迁移）
python3 scripts/vectorize.py --from-archive

# 全量重建向量库
python3 scripts/vectorize.py --full
```

---

## 依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| Ollama | 本地 LLM | [ollama.ai](https://ollama.ai) |
| bge-m3 | 向量化模型 | `ollama pull bge-m3` |
| qwen2.5:3b-instruct-q4_K_M | 摘要生成 | `ollama pull qwen2.5:3b-instruct-q4_K_M` |
| ChromaDB | 向量数据库 | `pip3 install chromadb` |

---

## 存储路径

```
~/.qclaw/skills/memoria/
├── memoria.json          # 热缓存（最近 50 条）
├── archive/              # 冷备份（按月归档）
│   └── 2026-04/          # 重要内容原文
└── scripts/              # 脚本

~/.qclaw/memoria/
└── chroma_db/            # 向量索引（ChromaDB）

~/.qclaw/agents/main/sessions/
└── *.jsonl               # 原始对话（OpenClaw 管理）
```

---

## 脚本说明

| 脚本 | 作用 |
|------|------|
| `recall.py` | 快速检索（热缓存/向量搜索） |
| `recall_with_context.py` | 深度检索（自动获取 archive 原文） |
| `archive_important.py` | 重要内容写入 archive + 向量化 |
| `auto_archive.py` | 每日归档，三层写入 |
| `vectorize.py` | 增量/全量向量化 |
| `remember.py` | 直接写入一条记忆（热缓存） |
| `memoria_utils.py` | 公共工具库 |

---

## 文档

- `docs/CHANGELOG-2026-04-02.md` — 04-02 修复通知（P0/P1 全部完成）
- `docs/CHANGELOG-2026-04-03.md` — 04-03 更新通知（写入规则升级 + 工作区整理）
- `docs/optimization/` — 织影的架构分析与优化建议（Vera / Iris / Nova）

---

## License

MIT
