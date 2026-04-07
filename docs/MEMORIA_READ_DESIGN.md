# Memoria 读取设计文档

> 本文档记录 Memoria 记忆系统的读取架构设计
> 适用于: v4.0+
> 最后更新: 2026-04-07

---

## 1. 概述

Memoria 读取侧对应写入侧的 `store()`，提供统一的 `recall()` 入口。

核心原则：
- **links 和向量是两个独立意图**，不是 fallback 关系
  - links = 关系图谱，找**确定关联**的记忆（Obsidian backlinks 思路）
  - 向量 = 语义空间，找**可能相关**的内容（理解你在说什么）
- **Clara 按意图选路径**，不需要 mode 参数
- **原文按需读**，不默认展开

---

## 2. 统一读取入口 recall()

### 2.1 函数签名

```python
def recall(
    query: str = None,           # 语义搜索（向量）
    tags: list = None,           # links 精确匹配（标签）
    memory_id: str = None,       # 精确定位某条
    limit: int = 5,              # 返回条数
    include_content: bool = False  # True → 读 archive 原文
) -> list[dict]:
    """
    读取记忆。

    调用方根据意图传不同参数：
    - 找确定关联: recall(tags=["kraken"])
    - 找语义相关: recall(query="之前讨论的队列方案")
    - 深度回溯:   recall(memory_id="xxx", include_content=True)
    """
```

### 2.2 参数说明

| 参数 | 必填 | 路径 | 说明 |
|------|------|------|------|
| `query` | 可选 | 向量搜索 | 自然语言，走 chroma_db 语义匹配 |
| `tags` | 可选 | links 搜索 | 标签列表，走 links.json 精确匹配 |
| `memory_id` | 可选 | 直接读取 | 精确定位，直接读 archive TXT |
| `limit` | 可选 | — | 返回条数，默认 5 |
| `include_content` | 可选 | — | 是否返回 archive 原文，默认 False |

> 三种查询参数互斥，优先级：memory_id > tags > query
> 如果同时传了多个，按优先级取第一个。

### 2.3 返回结构

```python
[
    {
        "memory_id": "xxx",
        "summary": "一行摘要",
        "tags": ["标签1", "标签2"],
        "links": ["链接1", "链接2"],
        "timestamp": "2026-04-07T10:00:00Z",
        "source": "manual",
        "content": "..."              # 仅 include_content=True 时返回
    },
    ...
]
```

---

## 3. 三条路径

### 3.1 路径总览

```
recall(tags=["kraken"])
    │
    └─→ links.json["kraken"] → memory_id 列表
        └─→ memoria.json 匹配 summary
            └─→ include_content? → archive/{id}.txt

recall(query="之前讨论的队列方案")
    │
    └─→ chroma_db 向量搜索 → Top N (memory_id + score)
        └─→ memoria.json 匹配 summary
            └─→ include_content? → archive/{id}.txt

recall(memory_id="xxx", include_content=True)
    │
    └─→ 直接读 archive/{id}.txt → 解析 front matter + 正文
```

### 3.2 路径对比

| 路径 | 原理 | 适用场景 | 速度 |
|------|------|---------|------|
| **tags → links** | 标签精确匹配 | 找"所有关于 X 的记忆" | 快（JSON 查询） |
| **query → 向量** | 语义相似度 | 找"可能相关的内容" | 中（需要 embedding） |
| **memory_id → archive** | 直接定位 | 已知目标，深度回溯 | 慢（读文件） |

---

## 4. 路径组合：links 优先，向量补充

### 4.1 设计思路

links 和向量服务于不同意图，不是同一查询的两种实现：

- **links**: "给我所有关于 Kraken 的记忆" → 精确、穷举
- **向量**: "我想找之前讨论队列方案的内容" → 模糊、按相关性排序

### 4.2 Clara 的判断逻辑

写在行为准则中（AGENTS.md / SOUL.md），不是代码：

| 用户说 | Clara 判断 | 调用 |
|--------|-----------|------|
| "Kraken 之前怎么说的" | 明确项目名 → links | `recall(tags=["kraken"])` |
| "之前讨论队列方案了吧？" | 模糊意图 → 向量 | `recall(query="队列方案")` |
| "展开那条" | 已有结果 → 深度回溯 | `recall(memory_id="xxx", include_content=True)` |
| 先 links 找到了，想找更多相关的 | 组合查询 | `recall(query="...", tags=["kraken"])` |

> 最后一行是组合用法：已通过 links 找到了"确定关联"的记忆，再用向量搜索扩展"可能相关"的内容。
> 当前版本可暂不实现组合查询，Clara 分两次调用即可。

---

## 5. 启动加载

### 5.1 当前实现（保持不变）

```bash
python3 scripts/recall.py --hot-cache --simple
```

读取 memoria.json 中所有条目的 summary，作为 Clara 的短期上下文。

### 5.2 links 索引

不预加载。Clara 在对话中根据意图按需查询 links.json。

**行为准则**：当提到某个已知实体（项目名、人名、技术名）时，查 links.json 看有没有关联记忆。

---

## 6. 深度回溯

### 6.1 触发

用户说"展开说说"、"详细点"、"具体呢" → Clara 用上次结果的 memory_id 读原文：

```bash
recall(memory_id="xxx", include_content=True)
```

### 6.2 内容来源

直接读 `archive/{YYYY-MM}/{title}-{id}.txt`，解析 YAML front matter + Markdown 正文。

---

## 7. rebuild 命令

### 7.1 定位

手动运维工具，不纳入日常流程。发现数据不一致时使用。

### 7.2 功能

```bash
# 全量重建
python3 scripts/rebuild.py
```

扫描 `archive/` 目录下所有 TXT 文件 → 重建三个可恢复的存储：

| 重建目标 | 数据来源 |
|---------|---------|
| chroma_db（向量库） | archive TXT 正文 |
| memoria.json（热缓存） | archive TXT front matter |
| links.json（链接索引） | archive TXT front matter 中的 links 字段 |

### 7.3 注意

- archive TXT 是唯一真实来源，rebuild 从 archive 重建其他三个
- rebuild 是幂等的，可以反复执行
- 不删除 archive 中的任何文件

---

## 8. 调用示例

### 8.1 找某个项目的所有记忆

```bash
# Clara 调用
python3 scripts/recall.py --tags "kraken,redis"
```

### 8.2 语义搜索

```bash
# Clara 调用
python3 scripts/recall.py --query "之前讨论的队列方案"
```

### 8.3 深度回溯

```bash
# Clara 调用
python3 scripts/recall.py --memory-id "abc123" --include-content
```

### 8.4 启动加载

```bash
python3 scripts/recall.py --hot-cache --simple
```

---

## 9. 与写入侧的关系

```
写入: store(content, pre_tags, source, session_id)
      → archive TXT → 向量 → 热缓存 → links

读取: recall(query?, tags?, memory_id?, limit, include_content)
      → links / 向量 / 热缓存 → archive TXT
```

写入链路保证 archive TXT 始终是最完整的数据源。
读取链路从轻到重，按需深入。

---

## 10. 后续待讨论

- [ ] recall() 脚本实现
- [ ] rebuild.py 脚本实现
- [ ] 组合查询（tags + query 同时生效）
- [ ] 配置文件设计（如需）
- [ ] 热缓存容量 / 向量搜索 Top N 等参数调优

---

*本文档由 Clara 编写，基于 2026-04-07 的读取方案讨论成果*
