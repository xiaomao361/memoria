# Memoria 写入设计文档

> 本文档记录 Memoria 记忆系统的写入流程设计
> 适用于: v4.0+
> 最后更新: 2026-04-07

---

## 1. 概述

Memoria 写入采用**统一入口 + 多触发机制**的设计：

- **一个核心函数**: `store(content, pre_tags, source, session_id)`
- **两种触发方式**: 手动触发、主动触发
- **四种存储位置**: archive TXT / 向量库 / 热缓存 / links 索引

---

## 2. 统一写入入口 store()

### 2.1 函数签名

```python
def store(
    content: str,           # 正文内容（按 TXT 模板格式）
    pre_tags: list = None,  # 预置标签
    source: str = "manual", # manual | proactive
    session_id: str = None  # 可选，关联的 session
) -> dict:
    """
    写入一条记忆。
    
    Returns:
        {
            "memory_id": "uuid",
            "archive_path": "archive/.../xxx.txt",
            "status": {
                "archive": "ok",
                "vector": "ok",
                "hot_cache": "ok",
                "links": "ok"
            }
        }
    """
```

### 2.2 输入说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `content` | ✅ | 正文内容，按 TXT 模板格式（摘要/背景/要点/后续），可包含 `[[links]]` |
| `pre_tags` | 可选 | Clara 传入的预置标签，会和提取的 links 合并 |
| `source` | ✅ | `manual`（手动触发）或 `proactive`（主动触发） |
| `session_id` | 可选 | 关联的 session UUID |

### 2.3 输出说明

```python
{
    "memory_id": "abc123",
    "archive_path": "archive/2026-04/xxx.txt",
    "status": {
        "archive": "ok",
        "vector": "ok",
        "hot_cache": "ok",
        "links": "ok"
    }
}
```

失败时对应的字段会显示错误信息，例如：
```python
{
    "memory_id": "abc123",
    "archive_path": "archive/2026-04/xxx.txt",
    "status": {
        "archive": "ok",
        "vector": "failed: timeout",
        "hot_cache": "ok",
        "links": "ok"
    }
}
```

---

## 3. 内部处理流程

### 3.1 四步写入

```
store(content, pre_tags, source, session_id)
    │
    ├─→ Step 1: 写 archive TXT
    │     - 生成 memory_id, created, version
    │     - 从 content 提取 [[links]]
    │     - 合并 pre_tags + links
    │     - 拼装 YAML front matter + 正文
    │     - 写入 archive/{YYYY-MM}/{title}-{id}.txt
    │
    ├─→ Step 2: 写向量库
    │     - embedding 输入: content 前 512 字（截断）
    │     - document 存储: content 全文
    │     - metadata: memory_id, archive_path, timestamp, source, tags, links, session_id
    │
    ├─→ Step 3: 写热缓存
    │     - 新条目 insert(0) 到 memoria.json["memories"] 头部
    │     - 超过容量时删除尾部（FIFO）
    │
    └─→ Step 4: 写 links 索引
          - 遍历 links，更新 links.json（增量合并）
```

### 3.2 失败处理

| 步骤 | 失败影响 | 恢复方式 |
|------|---------|---------|
| Step 1 失败 | 核心失败，整个 store() 返回错误 | 调用方重试 |
| Step 2 失败 | 向量搜索找不到，但 archive 仍存在 | rebuild 重建 |
| Step 3 失败 | 热缓存没有，但向量和 archive 存在 | rebuild 重建 |
| Step 4 失败 | links 索引不完整 | rebuild 重建 |

每步独立 try/catch，不回滚已成功的步骤。

### 3.3 返回值

返回四步各自的成败状态，调用方可根据结果决定是否重试或报警。

---

## 4. 触发机制

### 4.1 手动触发

**用户说"记一下"、"单独记"、"这个要记"**

```
用户："记一下，Kraken 项目用 Redis 做队列"
    ↓
Clara 在对话中生成 content（按 TXT 模板）
    ↓
Clara 调用 store(content, pre_tags=["kraken", "redis"], source="manual")
    ↓
store() 完成写入，返回结果
    ↓
Clara 告诉用户："记好了"
```

**特点**：
- 用户明确要求，无需确认环节
- Clara 全程在对话中，上下文最全，content 质量最高
- pre_tags 由 Clara 根据对话内容推断

### 4.2 主动触发

**Clara 判断有价值，先询问用户确认**

```
对话进行中...
    ↓
Clara 判断：这段对话有价值（做了决策 / 发现新信息 / 解决问题）
    ↓
Clara 问："这个要记一下吗？"
    ↓
用户："好" / "记" / "不用"
    ↓
├→ "好"/"记" → Clara 生成 content → store(content, pre_tags, source="proactive")
└→ "不用" → 跳过，继续对话
```

**判断标准**（写入 SOUL.md，不是代码）：

| 信号 | 例子 |
|------|------|
| 做了决策 | "决定用 Redis 替代 RabbitMQ"、"增量更新以后再做" |
| 发现了新东西 | "我不吃香菜"、"最近在玩丝之歌" |
| 解决了问题 | "原来是编码问题，GBK 改 UTF-8 就好了" |
| 跨会话关联 | "上次说的 X，现在用上了" |
| 用户暗示 | "这个很重要"、"记住这个" |

**不触发的场景**：
- 日常闲聊
- 查天气/搜东西（工具调用结果）
- Heartbeat 推送
- 重复信息

**特点**：
- 多一个确认环节，用户有最终决定权
- 判断标准是 Clara 的行为准则，不是代码逻辑
- 轻量询问，不长篇解释

### 4.3 自动触发（cron）— 暂不实现

**方案预留**：

```
cron 定时触发
    ↓
扫描最近 N 小时变更的 session
    ↓
对每个 session：本地模型二分类（有价值 / 无价值）
    ↓
├→ 无价值 → 跳过
└→ 有价值 → 本地模型生成摘要 + tags → store()
```

**暂不实现的原因**：
- 需要引入本地模型（qwen2.5:3b）做价值判断和摘要生成
- 增加系统复杂度
- 手动 + 主动已覆盖大部分有价值的场景

**后续迭代时补充**。

---

## 5. Clara 与 store() 的分工

### 5.1 Clara 负责（在对话中）

| 任务 | 说明 |
|------|------|
| 生成 content | 按 TXT 模板（摘要/背景/要点/后续） |
| 写入 `[[links]]` | 在 content 中用 `[[xxx]]` 标记关联实体 |
| 传入 pre_tags | 根据对话内容推断标签 |
| 判断是否主动触发 | 行为准则，写在 SOUL.md |

### 5.2 store() 负责（脚本内部）

| 任务 | 说明 |
|------|------|
| 生成 memory_id | UUID |
| 生成 created | UTC 时间戳 |
| 提取 `[[links]]` | 从 content 中解析，自动提取 |
| 合并 tags/links | pre_tags + 提取的 links 去重 |
| 写四地 | archive TXT → 向量 → 热缓存 → links 索引 |
| 处理失败 | 独立 try/catch，返回各步状态 |

### 5.3 content 生成模板

Clara 在对话中生成 content 时，按以下模板：

```markdown
## 摘要
一两句话概括。

## 背景
（可选）为什么聊这个。

## 要点
- 关键点 1
- 决策：xxx
- 相关：[[链接1]], [[链接2]]

## 后续
（可选）待做事项。
```

**示例**：

用户说："记一下，Kraken 项目用 Redis 做队列"

Clara 生成：
```markdown
## 摘要
Kraken 项目消息队列选用 Redis。

## 要点
- 决策：使用 Redis 替代 RabbitMQ
- 理由：性能优先，简化架构
- 相关：[[kraken]], [[redis]]
```

---

## 6. 调用示例

### 6.1 手动触发

```bash
# Clara 调用
python3 scripts/store.py \
  --content "# Memoria 写入方案确认

## 摘要
确认统一写入入口 store()，手动+主动两种触发，不依赖 3B 模型。

## 要点
- 一个 store() 函数，四步写入
- tags 由 Clara 传 pre_tags
- links 从 [[xxx]] 提取
- 暂不实现 cron 自动触发

## 后续
- 实现读取侧
- 相关：[[memoria]], [[bge-m3]]" \
  --tags "memoria,技术,设计" \
  --source manual \
  --session-id "abc123"
```

### 6.2 主动触发

```bash
# Clara 判断有价值，用户确认后调用
python3 scripts/store.py \
  --content "..." \
  --tags "..." \
  --source proactive
```

---

## 7. 与旧脚本的对比

| 维度 | 旧方案（v3.x） | 新方案（v4.0） |
|------|---------------|---------------|
| 写入入口 | `archive_important.py` + `remember.py` 两套 | 统一 `store()` |
| tags/links | 本地模型生成 | Clara 传 pre_tags + `[[xxx]]` 提取 |
| 3B 模型 | 依赖 | 不依赖（提速） |
| 触发机制 | 手动 + cron 自动 | 手动 + 主动确认（cron 暂缓） |
| archive 格式 | TXT（格式不统一） | TXT（YAML front matter + Markdown 正文） |
| meta.json | 有（独立文件） | 无（合并到 TXT front matter） |

---

## 8. 后续工作

### 当前版本（v4.0）
- [x] 统一 store() 函数设计
- [x] TXT 格式定稿
- [x] 向量库 metadata 设计
- [x] 主动触发判断标准
- [x] store() 脚本实现
- [x] 与 Clara 对话流程集成

### 后续迭代
- [x] cron 自动触发实现
- [x] 增量更新实现（session-id 判断 + 追加逻辑）
- [x] rebuild 命令实现
- [x] 配置文件设计

---

*本文档由 Clara 编写，记录 2026-04-07 的写入方案讨论成果*
