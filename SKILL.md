---
name: memoria
description: Clara 的记忆增强插件。跨会话记忆持久化与智能召回。当用户提到"记住"、"这个重要"、"之前说过"、"你还记得吗"，或需要持久化跨会话信息时使用。
---

# Memoria — 记忆之网

## 核心原则

**双层存储架构：**
- `memoria_full/` — 全量原始对话（按日期/session 存储，永久保留）
- `memoria.json` — 索引层（摘要 + 标签 + channel + full_ref）

**核心流程：**
```
对话结束（heartbeat 或指令）
    → 全量存入 memoria_full/
    → 生成摘要 → 写入 memoria.json（索引）
```

**重要原则：**
- 摘要优先注入上下文（省 token）
- 全量按需拉取（--full 参数）
- 摘要可重建，全量不丢失

## 存储结构

```
~/.qclaw/skills/memoria/
├── memoria.json              # 索引层
├── memoria_full/
│   └── YYYY-MM-DD/
│       └── {session_label}_{timestamp}.json
└── scripts/
    ├── remember.py           # 写入（双层结构）
    └── recall.py             # 检索（索引/全量两种模式）
```

### memoria.json 格式

```json
{
  "memories": [
    {
      "id": "uuid-v4",
      "timestamp": "2026-03-30T09:00:00+08:00",
      "channel": "feishu",
      "tags": ["周维副业", "记忆增强"],
      "summary": "讨论了记忆增强插件的一期方案...",
      "full_ref": "~/.qclaw/skills/memoria/memoria_full/2026-03-30/xxx.json",
      "message_count": 12
    }
  ]
}
```

## 触发场景

### 写入触发（满足任一即触发）

1. **Heartbeat 时** — 判断当前 session 是否有值得写入的内容
2. **用户指令** — 用户说"记住 xxx"、"这个重要"、"别忘了 xxx"
3. **讨论超过 3 轮** — 同一话题持续讨论超过 3 轮，自动评估是否写入

### 读取触发

1. **新对话启动** — 读取最近 7 天、最多 5 条相关记忆注入上下文
2. **用户问起** — "之前那个事怎么定的？"、"你还记得 xxx 吗？"
3. **按需全量** — 对话中需要展开某条记忆的细节

## 使用接口

### 写入记忆

```bash
# 通过 stdin 传入对话 JSON
cat conversation.json | python3 remember.py --channel feishu --tags "标签1,标签2" --session-label "会话描述"

# 人工指定摘要（覆盖自动生成）
python3 remember.py --channel webchat --tags "重要" --summary "这是核心摘要" --messages-file data.json
```

### 检索（索引模式，默认）

```bash
# 最近 7 天最多 5 条
python3 recall.py

# 自定义天数和数量
python3 recall.py --days 14 --limit 10

# 按标签筛选
python3 recall.py --tags "周维副业"

# 按渠道筛选
python3 recall.py --channel feishu
```

### 检索（全量模式）

```bash
# 按 ID 展开全量
python3 recall.py --id <uuid> --full

# 直接指定 full_ref
python3 recall.py --ref ~/.qclaw/skills/memoria/memoria_full/2026-03-30/xxx.json
```

## 一期默认配置

| 配置项 | 值 | 说明 |
|---|---|---|
| RECALL_DAYS | 7 | 默认拉取 7 天内记忆 |
| RECALL_MAX | 5 | 最多注入 5 条 |
| AUTO_SUMMARY | 启发式提取 | 一期摘要策略（用户首句 + 助手末句） |

## 渠道标识

| 渠道 | channel 值 | 说明 |
|---|---|---|
| 飞书 | `feishu` | 飞书消息 |
| 微信 | `wechat` | 微信消息 |
| Webchat | `webchat` | OpenClaw Web UI |
| iOS QClaw | `qclaw-ios` | QClaw App |
| 命令行 | `cli` | 终端交互 |

## 新对话启动注入流程

每次新 session 启动时：

```
→ 执行 recall.py --days 7 --limit 5
→ 将索引结果注入上下文（仅摘要，不含 full_ref 路径）
→ 继续标准启动流程
```

需要展开时，再调用 `recall.py --id <uuid> --full` 拉取全量。
