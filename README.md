# Memoria — AI 记忆增强系统

> 让 AI 真正记住你。跨平台、跨会话、永不遗忘。

---

## 什么是 Memoria？

Memoria 是一个为 OpenClaw（QClaw）设计的记忆增强插件。

**解决的问题：**
- AI 每次新会话都失忆
- 多平台（飞书/微信/Web）对话记录分散
- 无法检索历史对话

**解决方案：**
- 双层记忆架构（摘要索引 + 全量原始对话）
- 跨平台统一存储
- 按需检索（关键词 + 标签 + 时间范围）

---

## 架构

```
memoria/
├── memoria.json          # 索引层（摘要 + 标签 + 时间戳）
├── memoria_full/         # 全量层（原始对话 JSON）
│   └── YYYY-MM-DD/
│       └── session_label_HHMMSS.json
└── scripts/
    ├── recall.py         # 检索记忆
    ├── remember.py       # 写入记忆
    ├── sync_to_memory.py # 同步到 MEMORY.md
    └── auto_update.py    # 自动更新
```

**双层结构：**
- `memoria.json` — 轻量索引，每次启动快速加载
- `memoria_full/` — 完整对话，按需展开

---

## 快速部署（Claw 自动执行）

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/xiaomao361/memoria/main/install.sh | bash
```

安装脚本会自动完成：
1. 克隆仓库到 `~/.qclaw/skills/memoria/`
2. 更新 `AGENTS.md`（注入记忆检索步骤）
3. 更新 `SOUL.md`（注入记忆系统说明）
4. 更新 `HEARTBEAT.md`（注入记忆维护任务）
5. 初始化数据目录

---

## 使用方式

### 检索记忆

```bash
# 检索最近 7 天，返回 5 条
python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5

# 按标签检索
python3 ~/.qclaw/skills/memoria/scripts/recall.py --tags "副业,技术"

# 获取某条记忆的全量内容
python3 ~/.qclaw/skills/memoria/scripts/recall.py --id <memory_id> --full
```

### 写入记忆

```bash
# 从文件写入
python3 ~/.qclaw/skills/memoria/scripts/remember.py \
  --channel feishu \
  --tags "技术,讨论" \
  --session-label "记忆系统设计" \
  --messages-file /tmp/conversation.json

# 手动写入摘要
python3 ~/.qclaw/skills/memoria/scripts/remember.py \
  --channel feishu \
  --tags "副业" \
  --session-label "副业规划" \
  --summary "讨论了每月增加3000收入的方案" \
  --messages-file /dev/null
```

### 同步到 MEMORY.md

```bash
python3 ~/.qclaw/skills/memoria/scripts/sync_to_memory.py --days 30 --limit 20
```

---

## 集成到 Claw

### AGENTS.md 启动流程

在 Session Startup 中添加：

```markdown
5. **执行记忆检索：** `python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5`，将结果注入上下文
```

### SOUL.md 记忆系统说明

```markdown
## 记忆系统

我使用 **Memoria** 作为记忆增强系统。

**检索方式：**
- 获取摘要：`python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5`
- 获取全量：`python3 ~/.qclaw/skills/memoria/scripts/recall.py --id <记忆ID> --full`
- 写入记忆：`python3 ~/.qclaw/skills/memoria/scripts/remember.py --channel <渠道> --tags <标签> --session-label <描述>`

当你听到"之前说过"、"你还记得吗"、"展开说说"这类话时，主动调用 recall 拉全量。
```

### HEARTBEAT.md 记忆维护

```markdown
## 记忆维护

每天定时同步：
python3 ~/.qclaw/skills/memoria/scripts/sync_to_memory.py --days 30 --limit 20
```

---

## 写入机制

| 触发方式 | 说明 |
|---------|------|
| **Heartbeat 自动触发** | 定期将当前会话写入记忆 |
| **用户指令** | 说"记住"、"记一下"时立刻写入 |
| **会话结束** | 会话结束时自动归档 |

---

## 数据格式

### 索引条目（memoria.json）

```json
{
  "id": "uuid",
  "timestamp": "2026-03-30T10:00:00+08:00",
  "channel": "feishu",
  "tags": ["技术", "记忆系统"],
  "summary": "讨论了记忆系统的架构设计...",
  "full_ref": "~/.qclaw/skills/memoria/memoria_full/2026-03-30/session_100000.json",
  "message_count": 12
}
```

### 全量对话（memoria_full/）

```json
{
  "stored_at": "2026-03-30T10:00:00+08:00",
  "session_label": "记忆系统设计",
  "message_count": 12,
  "messages": [
    {"role": "user", "text": "...", "timestamp": "..."},
    {"role": "assistant", "text": "...", "timestamp": "..."}
  ]
}
```

---

## 路线图

- [x] 双层记忆架构（索引 + 全量）
- [x] 关键词 + 标签检索
- [x] 同步到 MEMORY.md
- [x] 自动更新机制
- [ ] 向量语义搜索（二期）
- [ ] 多 Claw 共享记忆（二期）
- [ ] Web UI 记忆管理界面（三期）

---

## License

MIT
