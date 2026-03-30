# Memoria — 记忆之网

> 个人知识库，跨平台、跨会话、永不遗忘。

---

## 核心定位

Memoria 是**周维的个人知识库**，与 OpenClaw 原生记忆系统并行：

| 系统              | 目标               | 形态                   |
| ----------------- | ------------------ | ---------------------- |
| **OpenClaw 原生** | 让 AI 回答更准     | 对话上下文注入         |
| **Memoria**       | 让个人的知识可管理 | 事件/主题/渠道网状索引 |

---

## 三层存储架构

```
┌─────────────────────────────────────────────────────────┐
│  索引层（memoria.json）                                  │
│  → 精华摘要 + 标签 + 渠道 + 存储类型 + 引用路径           │
│  → 检索唯一入口，轻量快速                                │
├─────────────────────────────────────────────────────────┤
│  热存储（session 引用）                                  │
│  → 指向 OpenClaw 原生 sessions/*.jsonl                   │
│  → 默认方案，依赖 OpenClaw 的清理策略                    │
├─────────────────────────────────────────────��──────────┤
│  冷存储（archive/）                                      │
│  → 重要内容永久备份，按年月归档                           │
│  → 防止 session 被清理时丢失                             │
└─────────────────────────────────────────────────────────┘
```

**存储类型标识：**
- 🔥 `hot` — 仅热存储（session 引用）
- 🧊 `cold` — 仅冷存储（archive 备份）
- ❄️ `cold+hot` — 双存储（重要内容）

---

## 快速安装

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/xiaomao361/memoria/main/install.sh | bash

# 安装到其他 Claw（如 Vera）
export MEMORIA_DIR=~/.qclaw/agents/vera/memoria
export WORKSPACE=~/.qclaw/agents/vera/workspace
bash install.sh
```

---

## 使用方式

### 写入记忆

```bash
# 基础写入（热存储）
python3 ~/.qclaw/skills/memoria/scripts/remember.py \
  --channel feishu \
  --tags "副业,规划" \
  --session-label "副业方案讨论" \
  --summary "讨论了每月增加3000收入的方案"

# 重要内容（同时冷存储备份）
python3 ~/.qclaw/skills/memoria/scripts/remember.py \
  --channel webchat \
  --tags "架构,重要" \
  --session-label "Memoria架构重构" \
  --summary "确定三层存储架构" \
  --archive
```

### 检索记忆

```bash
# 默认检索（简化格式，用于注入上下文）
python3 ~/.qclaw/skills/memoria/scripts/recall.py --simple

# 详细格式
python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 14 --limit 10

# 按标签筛选
python3 ~/.qclaw/skills/memoria/scripts/recall.py --tags "副业,技术"

# 关键词搜索
python3 ~/.qclaw/skills/memoria/scripts/recall.py --keyword "架构"

# 展开全量
python3 ~/.qclaw/skills/memoria/scripts/recall.py --id <记忆ID前8位> --full
```

---

## 多 Claw 兼容

通过环境变量实现多个 Claw 独立使用：

| 环境变量      | 作用         | 默认值                    |
| ------------- | ------------ | ------------------------- |
| `MEMORIA_DIR` | 数据存储路径 | `~/.qclaw/skills/memoria` |
| `WORKSPACE`   | 配置注入目标 | `~/.qclaw/workspace`      |

---

## 目录结构

```
~/.qclaw/skills/memoria/
├── memoria.json          # 索引层（精华摘要 + 引用）
├── archive/              # 冷存储（重要内容永久备份）
│   └── YYYY-MM/
│       └── {channel}_{label}_{session_id}.json
├── scripts/
│   ├── remember.py       # 写入记忆
│   ├── recall.py         # 检索记忆
│   ├── integrate_with_claw.py  # 配置集成
│   └── auto_update.py    # 自动更新
├── SKILL.md              # 技能定义
├── install.sh            # 安装脚本
└── README.md             # 本文件
```

---

## 与 OpenClaw 原生记忆的区别

| 特性     | OpenClaw 原生       | Memoria              |
| -------- | ------------------- | -------------------- |
| 组织方式 | 按 session/时间线性 | 按事件/主题/渠道网状 |
| 受益者   | AI（上下文注入）    | 人（知识管理）       |
| 内容形态 | 对话摘要            | 知识节点             |
| 时间跨度 | 最近对话            | 可跨月、年           |
| 多渠道   | 不区分              | 天然聚合             |
| 可控性   | prompt 驱动         | 代码层可编程         |

---

## 路线图

- [x] 三层存储架构（索引 + 热存储 + 冷存储）
- [x] 多 Claw 兼容（环境变量配置）
- [x] 标签 + 渠道 + 关键词检索
- [ ] 向量语义搜索（二期）
- [ ] 多 Claw 记忆共享策略（二期）
- [ ] 自动归档策略（定期将旧 session 备份到 archive）

---

## License

MIT
