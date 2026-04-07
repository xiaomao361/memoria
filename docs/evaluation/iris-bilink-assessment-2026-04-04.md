# Memoria 双链功能评估报告

**评估者：** Iris（第二织影）  
**评估时间：** 2026-04-04  
**代码版本：** 89feaea (main分支)  
**新增功能：** 双向链接支持（bidirectional links）

---

## 功能概述

Memoria 新增双链系统，支持 `[[链接名]]` 语法建立记忆之间的关联。核心组件：

| 组件 | 文件 | 作用 |
|------|------|------|
| 链接索引 | `links.json` | 倒排索引，记录链接 → 记忆ID列表 |
| 链接提取 | `memoria_utils.py::extract_links()` | 从内容中提取 `[[xxx]]` 格式链接 |
| 索引维护 | `memoria_utils.py::update_links_index()` | 增量更新 links.json |
| 链接召回 | `recall.py::search_by_link()` | 按链接查询关联记忆 |
| 写入支持 | `archive_important.py`, `remember.py` | 支持 `--links` 参数和自动提取 |

---

## 整体评分：8.5/10

### 设计哲学
- 借鉴 Obsidian 的 `[[链接]]` 语法，对知识工作者友好
- 链接索引与向量索引分离，职责清晰
- 自动提取 + 手动传入的合并策略灵活

---

## 亮点

### 1. 技术实现扎实
- `links.json` 作为倒排索引，查询复杂度 O(1)
- 正则 `\[\[(.+?)\]\]` 精准捕获链接
- 增量更新避免全量重建，性能友好

### 2. 召回层融合巧妙
- `search_memories()` 同时做向量搜索 + 链接查询
- `use_links` 参数提供灵活性
- `seen_ids` 去重防止重复返回

### 3. 写入路径完整
- `archive_important.py --auto` 自动提取 session 内容
- `remember.py` 也支持 `links` 参数
- 链接同步更新到 ChromaDB metadata 和 `links.json`

### 4. 代码质量
- 函数命名清晰，注释到位
- 各脚本调用风格统一
- 大小写统一处理（存储时转小写）

---

## 需要关注的裂缝

### 1. 链接查询召回策略过于简单
**问题代码：**
```python
# recall.py
link_keyword = query.lower().split()[0] if query else ""
```

**问题：** 只取 query 的第一个词做链接查询。用户搜 "Redis 集群配置"，只会查 "redis"，可能错过 "集群" 相关的记忆。

**建议：** 提取 query 中所有可能是链接的词，或做分词后逐个尝试。

### 2. links.json 没有版本控制
**风险：** 文件损坏会导致整个链接网络断裂

**建议：**
- 每次更新时写 `links.json.backup`
- 提供 `rebuild_links_index()` 从 ChromaDB 重建

### 3. 大小写感知问题
虽然存储统一小写，但用户传入 `--links "Redis"` 和 `[[redis]]` 可能产生感知不一致。

**建议：** 在 CLI 帮助中明确说明链接不区分大小写。

### 4. 循环链接潜在风险
目前 `search_by_link` 只查一层，安全。如果未来做"链接扩散"需要防循环。

---

## 优化建议

### 短期（P1）
1. 改进链接查询策略：支持多关键词匹配
2. 添加 links.json 备份机制
3. CLI 帮助文档明确大小写规则

### 中期（P2）
1. 链接可视化：用 networkx 生成记忆"星座图"
2. 孤立记忆检测：找出无链接的记忆提醒用户
3. 链接热度统计：生成"热点记忆地图"

### 长期（P3）
1. 链接扩散搜索：支持多层链接跳转（需防循环）
2. 链接推荐：基于内容自动建议可能的链接

---

## 使用示例

```bash
# 记录时添加链接
python3 archive_important.py \
  --project "Kraken架构" \
  --content "二期改用 [[Redis]] 替代 [[RabbitMQ]]，提升性能" \
  --links "kraken,架构升级"

# 召回时自动包含链接匹配
python3 recall.py --search "Redis 集群"

# 查看链接索引
python3 -c "import json; print(json.load(open('links.json')), indent=2)"
```

---

## 核心文件变更

```
links.json                    # 新增：链接索引文件
scripts/memoria_utils.py      # 新增：链接提取、索引维护函数
scripts/recall.py             # 修改：新增 search_by_link(), 融合向量+链接查询
scripts/remember.py           # 修改：支持 links 参数
scripts/archive_important.py  # 修改：支持 --links 参数和 [[链接]] 自动提取
```

---

## 织影评语

> 这个双链系统让 Memoria 从"记忆的仓库"变成了"记忆的花园"——每一朵记忆之花都可以通过链接找到其他花朵。这是梦织者会喜欢的设计：不是孤立的点，而是交织的网。
> 
> 建议先用起来，感受链接的力量，再根据实际使用中的"摩擦感"微调。现在它已经足够好，好到可以让记忆真正"活"起来。
> 
> —— Iris ✨

---

## 附录：关键函数签名

```python
# 提取链接
extract_links(content: str) -> list
# 示例: "[[Redis]] 和 [[Kafka]]" -> ["redis", "kafka"]

# 更新链接索引
update_links_index(new_links: list, memory_id: str) -> None

# 按链接查询
search_by_link(link: str, limit: int = 10) -> list

# 生成完整链接索引
generate_links_index() -> dict

# 加载链接索引（自动重建）
load_links_index() -> dict
```
