---
name: memoria-lite
description: |
  Memoria Lite — 轻量级 AI Agent 记忆系统。
  零外部依赖，五分钟上手。
  当用户提到"记住"、"这个重要"、"之前说过"、"你还记得吗"时使用。
metadata:
  openclaw:
    emoji: "🧠"
---

# Memoria Lite — 轻量级记忆系统 v4.0

> 跨会话记忆，标签检索，双向链接，永不遗忘。
> **零外部依赖** — 不需要 Ollama、ChromaDB 或任何向量服务。

---

## 与 Full 版本对比

| 特性 | Lite | Full |
|------|------|------|
| 向量语义搜索 | ❌ | ✅ bge-m3 + ChromaDB |
| 检索方式 | 标签 + 关键词 | 语义相似度 + 标签 |
| 外部依赖 | **零依赖** | Ollama + ChromaDB |
| 安装复杂度 | 极简 | 中等 |
| 适用场景 | 日常记忆、新手入门 | 语义搜索、高级用户 |
| 私密记忆区 | ✅ | ✅ |

**数据完全兼容**：Lite 和 Full 共用相同的 Archive TXT、热缓存和 links.json 格式，可以随时互转。

---

## 安装

### 方式1：作为 OpenClaw Skill 安装

```bash
# 克隆到 skills 目录
cd ~/.qclaw/skills
git clone -b feature/lite-no-vector git@github.com:xiaomao361/memoria.git memoria-lite

# 确保 scripts 可执行
chmod +x memoria-lite/scripts/*.py
```

### 方式2：独立使用

```bash
# 克隆到任意位置
git clone -b feature/lite-no-vector git@github.com:xiaomao361/memoria.git ~/memoria-lite

# 设置环境变量（可选）
export MEMORIA_ROOT=~/memoria-data
```

---

## 初始化

首次使用需要创建数据目录：

```bash
python3 ~/.qclaw/skills/memoria-lite/scripts/store.py \
  --content "# 初始化\n\n## 摘要\nMemoria Lite 初始化" \
  --tags "初始化"
```

这会创建：

```
~/.qclaw/memoria/
├── archive/          # 记忆归档（按月分目录）
│   └── 2026-04/
├── memoria.json      # 热缓存（最近 200 条）
├── links.json        # 双向链接索引
└── private/          # 私密区（使用 --private 时创建）
    ├── memories/
    └── links.json
```

---

## 启动触发（强制）

**新会话第一条消息时，必须立即执行：**

```bash
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --hot-cache --simple
```

**用户提到"之前/上次/还记得"时，立即执行：**

```bash
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --search "关键词"
```

---

## 写入记忆（store）

### 基本用法

```bash
# 写入公开记忆
python3 ~/.qclaw/skills/memoria-lite/scripts/store.py \
  --content "# 用户偏好\n\n## 摘要\n用户喜欢简洁的回答" \
  --tags "用户偏好,沟通风格"

# 写入私密记忆
python3 ~/.qclaw/skills/memoria-lite/scripts/store.py \
  --content "# 私密内容\n\n## 摘要\n..." \
  --tags "私密" \
  --private
```

### 触发方式

| 用户说法 | 调用方式 |
|----------|----------|
| 「记一下」+ 日常琐事 | `store.py --content` |
| 「记一下」+ 项目/技术 | `store.py --content --tags` |
| 「私密记一下」 | `store.py --content --private` |

### 写入流程

```
store(content, tags, private=False)
    │
    ├─ Step 1: 写入 Archive TXT（公开区或私密区）
    ├─ Step 2: 更新热缓存（私密区跳过）
    └─ Step 3: 更新 links 索引
```

**私密区特性：**
- 不写入热缓存
- 独立存储在 `private/` 目录
- 独立 links.json 索引
- 搜索时需加 `--private` 参数

---

## 检索记忆（recall）

### 基本用法

```bash
# 热缓存快速加载（启动时用）
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --hot-cache --simple

# 关键词搜索
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --search "用户偏好"

# 关键词搜索 + 返回完整内容
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --search "用户偏好" --with-content

# 标签精确匹配
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --tags "Memoria,技术"

# 最近 N 天
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --days 7

# 搜索私密区
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --search "关键词" --private

# 直接指定 memory_id
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --memory-id "xxx"
```

### 检索模式

```
recall(query)
    │
    ├─ --hot-cache: 加载热缓存（最快）
    ├─ --search: 关键词搜索（热缓存优先 → Archive 回退）
    ├─ --tags: 标签精确匹配（查 links.json）
    ├─ --days: 按时间筛选
    └─ --memory-id: 直接定位
```

---

## 双向链接

**使用方式：**
1. 内容中写 `[[链接名]]`（自动提取）
2. 调用时传 `--tags "标签1,标签2"`（同时加入 links 索引）

**链接类型：**
- 项目名：Kraken、Memoria、ThreadVibe
- 技术名：Redis、WebSocket
- 人物：Clara、毛仔

**索引文件：**
- 公开区：`~/.qclaw/memoria/links.json`
- 私密区：`~/.qclaw/memoria/private/links.json`

---

## 运维脚本

| 脚本 | 作用 |
|------|------|
| `store.py` | 统一写入入口 |
| `recall.py` | 检索入口 |
| `rebuild.py` | 重建索引（运维用） |
| `migrate.py` | Lite ↔ Full 迁移 |
| `auto_archive.py` | Session 冷备份 |

---

## 与 Full 版本互转

### Lite → Full（添加向量搜索）

```bash
# 1. 安装依赖
pip3 install chromadb

# 2. 启动 Ollama + bge-m3
ollama pull bge-m3

# 3. 重建向量索引
python3 ~/.qclaw/skills/memoria/scripts/rebuild.py --force
```

### Full → Lite（降级为轻量版）

```bash
# 1. 删除向量库
rm -rf ~/.qclaw/memoria/chroma_db

# 2. 切换到 Lite 分支
cd ~/.qclaw/skills/memoria
git checkout feature/lite-no-vector
```

---

## 架构

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
            │
            ▼
    ┌────────────┐
    │  私密区    │
    │ private/  │
    └────────────┘
```

---

## 数据状态

```
当前数据量：
- Archive: 94 条
- 热缓存: 94 条
- Links: 49 个
- 私密区: 2 条
```

---

## License

MIT License

---

*Memoria Lite — 让 AI Agent 记住一切，零门槛。*
