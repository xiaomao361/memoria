# Memoria Lite 快速开始

> 轻量级 AI Agent 记忆系统。零外部依赖，五分钟跑起来。

---

## 安装

### 方式1：作为 OpenClaw Skill

```bash
cd ~/.qclaw/skills
git clone -b feature/lite-no-vector git@github.com:xiaomao361/memoria.git memoria-lite
chmod +x memoria-lite/scripts/*.py
```

### 方式2：独立使用

```bash
git clone -b feature/lite-no-vector git@github.com:xiaomao361/memoria.git ~/memoria-lite
export MEMORIA_ROOT=~/memoria-data  # 可选
```

---

## 初始化

首次使用会自动创建数据目录：

```bash
python3 ~/.qclaw/skills/memoria-lite/scripts/store.py \
  --content "# 初始化\n\n## 摘要\nMemoria Lite 初始化" \
  --tags "初始化"
```

数据目录结构：

```
~/.qclaw/memoria/
├── archive/          # 记忆归档（按月分目录）
├── memoria.json      # 热缓存（最近 200 条）
├── links.json        # 双向链接索引
└── private/          # 私密区
    ├── memories/
    └── links.json
```

---

## 基本用法

### 写入记忆

```bash
# 公开记忆
python3 store.py --content "# 标题\n\n## 摘要\n内容" --tags "标签1,标签2"

# 私密记忆
python3 store.py --content "# 私密\n\n## 摘要\n内容" --tags "私密" --private
```

### 读取记忆

```bash
# 热缓存快速加载
python3 recall.py --hot-cache --simple

# 关键词搜索
python3 recall.py --search "关键词"

# 标签搜索
python3 recall.py --tags "标签1,标签2"

# 最近 7 天
python3 recall.py --days 7

# 搜索私密区
python3 recall.py --search "关键词" --private
```

---

## OpenClaw 集成

在你的 Skill 中添加：

```markdown
## 记忆集成

**启动时加载：**
```bash
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --hot-cache --simple
```

**写入记忆：**
```bash
python3 ~/.qclaw/skills/memoria-lite/scripts/store.py \
  --content "# 标题\n\n## 摘要\n内容" \
  --tags "标签"
```

**检索记忆：**
```bash
python3 ~/.qclaw/skills/memoria-lite/scripts/recall.py --search "关键词"
```
```

---

## 与 Full 版本对比

| 特性 | Lite | Full |
|------|------|------|
| 向量语义搜索 | ❌ | ✅ |
| 外部依赖 | 零依赖 | Ollama + ChromaDB |
| 安装复杂度 | 极简 | 中等 |
| 适用场景 | 日常记忆、新手 | 语义搜索、高级用户 |
| 私密记忆区 | ✅ | ✅ |

**数据完全兼容**，可以随时互转。

---

## 文档

- [SKILL.md](SKILL.md) — 完整 Skill 文档
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构设计
- [UPGRADE.md](docs/UPGRADE.md) — 迁移指南

---

*Memoria Lite — 零门槛的记忆系统。*
