# CHANGELOG — 2026-04-04

## 自动归档内容提取

新增 `--auto` 参数，自动从当前 session 提取对话内容。

### 新增

- `--auto` 参数：自动从 session 提取对话
- `--session-id` 参数：指定 session ID
- `auto_extract_from_session()` 函数：提取 session 对话、生成摘要、推断标签

### 使用方式

```bash
# 自动抓取当前 session
python3 scripts/archive_important.py --project "auto" --auto

# 自动抓取 + 传链接
python3 scripts/archive_important.py --project "auto" --auto --links "memoria,clara"
```

### 判断逻辑

| 用户说法 | 模式 | 说明 |
|----------|------|------|
| 「记一下」 | 自动 | 自动抓取 session |
| 「单独记」 | 手动 | 我整理内容后传入 |

---

## 双向链接功能

借鉴 Obsidian 的双向链接设计，为 Memoria 增加了 `[[链接]]` 支持。

### 新增

- **链接提取**：`extract_links()` 从内容中自动提取 `[[链接]]`
- **链接索引**：`links.json` 记录所有链接关系
- **链接查询**：`search_by_link()` 按链接检索记忆
- **合并逻辑**：手动传入 `--links` + 自动提取 `[[链接]]` 合并去重

### 改动文件

| 文件 | 改动 |
|------|------|
| `memoria_utils.py` | 新增链接相关函数 |
| `archive_important.py` | 自动提取链接 + 支持手动传入 |
| `remember.py` | 新增 `--links` 参数 |
| `recall.py` | 语义搜索 + 链接查询合并 |

### 使用方式

```bash
# 方式 1：在内容中写 [[链接]]
python3 scripts/archive_important.py \
  --project "kraken" \
  --content "Kraken 二期用 [[Redis]] 做队列"

# 方式 2：手动传入链接
python3 scripts/archive_important.py \
  --project "kraken" \
  --content "Kraken 二期用 Redis 做队列" \
  --links "kraken,redis"

# 方式 3：两者合并
python3 scripts/archive_important.py \
  --project "kraken" \
  --content "Kraken 二期用 [[Redis]] 做队列" \
  --links "kraken"
# 结果：链接 = redis, kraken
```

### 设计决策

**不做自动推荐链接**：
- 我在对话上下文中判断更准确
- 不需要额外调用模型，速度快
- 避免规则匹配压制新链接

**链接来源优先级**：
1. 手动传入 `--links`（最高）
2. 内容中的 `[[链接]]`（次高）
3. ~~规则匹配~~（不用）
4. ~~本地模型推断~~（不用）

---

## 文档更新

- 删除 `README.md`，只保留 `SKILL.md`
- 更新 `SKILL.md`：增加双向链接说明
- 更新 `AGENTS.md`：增加双向链接规则
- 更新 `SOUL.md`：增加写入记忆时加链接的提示

---

## 待优化（P2）

- 关系图谱可视化
- 链接建议提示
- 自动扩展查询
