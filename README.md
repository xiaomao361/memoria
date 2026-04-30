# Memoria — Clara 的记忆系统

> 跨会话记忆持久化与智能召回。永不遗忘。

## 快速开始

```bash
# 写入记忆
python3 scripts/store.py --content "重要内容" --tags "项目,决策"

# 召回记忆
python3 scripts/recall.py --query "关键词"

# 启动 Web 管理界面
python3 scripts/web_server.py --port 8080
```

## 核心功能

- **跨会话记忆** — 热缓存 + 向量库 + 冷备份 三层存储
- **语义搜索** — ChromaDB + bge-m3 模型
- **双向链接** — `[[链接名]]` 语法，自动构建知识图谱
- **重要度加权** — 高频召回的记忆自动强化
- **私密记忆** — 独立存储， `--private` 参数隔离
- **管理工具** — CLI + Web 界面，支持去重/清理/标签归一

## 文档

- [SKILL.md](SKILL.md) — OpenClaw Skill 入口
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 技术架构
- [docs/RUNBOOK.md](docs/RUNBOOK.md) — 运维手册
- [CHANGELOG.md](CHANGELOG.md) — 版本变更

## 目录结构

```
~/.qclaw/skills/memoria/
├── scripts/          # 核心脚本
│   ├── store.py      # 写入入口
│   ├── recall.py     # 检索入口
│   ├── dream.py      # 梦境整理层
│   ├── manage.py     # CLI 管理工具
│   ├── web_server.py # Web 管理界面
│   └── lib/          # 共享库
├── docs/             # 技术文档
├── README.md         # 本文件
├── SKILL.md          # OpenClaw Skill
└── CHANGELOG.md      # 变更记录

~/.qclaw/memoria/     # 数据目录（自动创建）
├── memoria.json      # 热缓存
├── chroma_db/        # 向量库
├── archive/          # 冷备份
├── links.json        # 链接索引
└── private/          # 私密记忆
```

## 版本

当前版本：**v5.2** — 管理工具套件

## 作者

Clara 🍷
