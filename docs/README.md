# Memoria Lite

> 轻量级 AI Agent 记忆系统。零外部依赖，五分钟跑起来。

**Memoria Lite** 是 [Memoria](https://github.com/xiaomao361/memoria) 的轻量版本，专为追求简单和零门槛的 OpenClaw 用户设计。

---

## 特性

- ✅ **零外部依赖** — 仅使用 Python 标准库，不需要 Ollama、向量数据库或其他服务
- ✅ **五分钟上手** — `pip install` 后即可使用，无需配置任何服务
- ✅ **双向链接** — 类 Obsidian 的 `[[链接]]` 语法，构建知识图谱
- ✅ **极速检索** — 标签匹配 + 关键词搜索，覆盖 90% 的日常查询场景
- ✅ **数据可迁移** — Archive TXT 为唯一真实来源，与 Full 版本完全兼容

---

## 与 Full 版本对比

| 特性 | Lite | Full |
|------|------|------|
| 向量语义搜索 | ❌ | ✅ bge-m3 + ChromaDB |
| 检索方式 | 标签 + 关键词 | 语义相似度 + 标签 |
| 外部依赖 | **零依赖** | Ollama + ChromaDB |
| 安装复杂度 | 极简 | 中等 |
| 适用场景 | 日常记忆、新手入门 | 语义搜索、高级用户 |

**数据完全兼容**：Lite 和 Full 共用相同的 Archive TXT、热缓存和 links.json 格式，可以随时互转。

---

## 快速开始

### 安装

```bash
pip install memoria-lite
```

### 初始化

```bash
python -m memoria init
```

这会在 `~/.qclaw/memoria/` 下创建必要的数据目录：

```
~/.qclaw/memoria/
├── archive/          # 记忆归档（按月分目录）
│   └── 2026-04/
├── memoria.json      # 热缓存（最近 200 条）
└── links.json        # 双向链接索引
```

### 写入记忆

```python
from memoria import store

store(
    content="""# 用户偏好
            
## 摘要
用户喜欢简洁的回答，不喜欢废话。

## 标签
[[用户偏好]] [[沟通风格]]
""",
    tags=["用户偏好", "沟通风格"]
)
```

### 读取记忆

```python
from memoria import recall

# 按标签查询
results = recall(query="用户偏好", mode="tags")

# 按关键词查询
results = recall(query="简洁 回答", mode="keyword")
```

### OpenClaw Skill 集成

将以下内容添加到你的 Skill 的 `SKILL.md` 中：

```markdown
## 记忆集成

Memoria Lite 提供两个函数：

### 写入
Clara 调用 `memoria.store()` 记住重要信息：
- `content`: Markdown 格式的记忆内容
- `tags`: 标签列表，用于精确匹配
- `links`: 关联链接（可选），使用 `[[名称]]` 语法

### 读取
Clara 调用 `memoria.recall()` 检索记忆：
- `query`: 搜索关键词或标签
- `mode`: `"tags"`（标签优先）或 `"keyword"`（关键词匹配）
```

---

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                      CLI / Skill                     │
│           store()              recall()               │
└─────────────────────────────────────────────────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
    ┌────────────┐ ┌────────────┐ ┌────────────┐
    │  热缓存    │ │ links索引  │ │  Archive   │
    │memoria.json│ │ links.json│ │   TXT      │
    │ (200条)   │ │ (双向链接) │ │ (最终来源) │
    └────────────┘ └────────────┘ └────────────┘
```

### 数据流

**写入 (store)**：
1. 写入 Archive TXT — 最终真实来源
2. 更新 links.json — 提取 `[[链接]]` 并建立索引
3. 更新热缓存 — 追加到 memoria.json

**读取 (recall)**：
1. 标签精确匹配 — 查 links.json
2. 关键词匹配 — 扫描热缓存的 summary
3. 全文回退 — 扫描 Archive TXT

---

## 目录结构

```
memoria-lite/
├── scripts/
│   ├── store.py          # 写入入口
│   ├── recall.py         # 读取入口
│   ├── rebuild.py        # 重建索引
│   ├── migrate.py        # Lite ↔ Full 迁移
│   └── lib/
│       ├── config.py     # 配置管理
│       ├── archive.py    # Archive TXT 读写
│       ├── hot_cache.py # 热缓存读写
│       ├── links.py     # links 索引读写
│       └── search.py    # 关键词搜索
├── docs/
│   ├── README.md         # 本文档
│   ├── ARCHITECTURE.md   # 架构设计
│   ├── STORAGE.md        # 存储设计
│   ├── READ.md           # 读取设计
│   ├── WRITE.md          # 写入设计
│   ├── CONFIG.md         # 配置说明
│   └── UPGRADE.md       # 迁移指南
└── SKILL.md             # OpenClaw Skill 接口
```

---

## 配置

Memoria Lite 使用 `~/.qclaw/memoria/config.json` 存储配置：

```json
{
    "root": "~/.qclaw/memoria",
    "hot_cache_limit": 200,
    "archive_path": "archive"
}
```

所有路径使用 `pathlib`，自动适配 Windows / macOS / Linux。

---

## 与 Full 版本互转

Lite 和 Full 的数据格式完全兼容，可以随时迁移：

```bash
# Lite → Full（添加向量搜索能力）
python -m memoria migrate --to full

# Full → Lite（降级为轻量版）
python -m memoria migrate --to lite
```

详见 [UPGRADE.md](docs/UPGRADE.md)。

---

## License

MIT License

---

*Memoria — 让 AI Agent 记住一切。*
