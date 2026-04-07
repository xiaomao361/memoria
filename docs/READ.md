# Memoria Lite 读取设计

> 本文档描述 Lite 版本的检索/读取设计，基于关键词搜索替代向量搜索。

---

## 1. 读取接口

### 1.1 recall() 函数签名

```python
def recall(
    query: str,
    mode: str = "hybrid",
    limit: int = 10,
    tags: list[str] | None = None,
    memory_id: str | None = None
) -> list[dict]:
    """
    检索记忆
    
    Args:
        query: 搜索关键词
        mode: 检索模式
              - "tags": 标签精确匹配（最快）
              - "keyword": 关键词搜索
              - "hybrid": 混合模式（默认）
        limit: 返回结果数量上限
        tags: 额外指定的标签列表
        memory_id: 直接指定 memory_id（跳过搜索）
    
    Returns:
        list[dict]: 记忆列表，每条包含 id、summary、archive_path、score
    """
```

### 1.2 返回格式

```python
[
    {
        "id": "abc123",
        "timestamp": "2026-04-08T06:00:00Z",
        "tags": ["用户偏好", "沟通风格"],
        "links": ["沟通风格"],
        "summary": "用户喜欢简洁的回答，不喜欢废话",
        "source": "manual",
        "archive_path": "2026-04/abc123.txt",
        "score": 1.0,  # 匹配得分，0-1
        "match_type": "tags"  # 匹配类型：tags / keyword / exact
    },
    ...
]
```

---

## 2. 检索模式

### 2.1 标签匹配 (mode="tags")

**流程**：
```
1. 从 query 中提取标签
   - 用户输入 "用户偏好" → 直接作为标签
   - 用户输入 "用户偏好 项目" → 提取 ["用户偏好", "项目"]
   
2. 查 links.json
   - links_index["用户偏好"] → ["abc123", "def456"]
   
3. 加载对应 Archive TXT
4. 返回结果
```

**代码示例**：
```python
def recall_by_tags(query: str, limit: int = 10) -> list[dict]:
    # 从 query 提取标签
    query_tags = [q.strip() for q in query.split()]
    
    # 查 links.json
    links_data = read_links_index()
    memory_ids = set()
    
    for tag in query_tags:
        if tag in links_data["links"]:
            memory_ids.update(links_data["links"][tag])
    
    # 去重后返回
    results = []
    for memory_id in list(memory_ids)[:limit]:
        archive_path = find_archive_path(memory_id)
        if archive_path:
            results.append(load_memory_summary(archive_path))
    
    return results
```

**特点**：
- ✅ 最快（毫秒级）
- ✅ 精确匹配，不会有误匹配
- ⚠️ 依赖标签质量
- ⚠️ 无法找到未打标签的记忆

### 2.2 关键词搜索 (mode="keyword")

**流程**：
```
1. 分词：将 query 拆解为关键词
2. 热缓存扫描：匹配 memoria.json 中的 summary
3. Archive 回退：热缓存未命中时扫描 archive/
4. 排序：按匹配得分降序
5. 返回 Top N
```

**代码示例**：
```python
def recall_by_keyword(query: str, limit: int = 10) -> list[dict]:
    # Step 1: 分词
    keywords = tokenize(query)
    
    # Step 2: 热缓存扫描
    hot_cache = read_hot_cache()
    hot_results = []
    
    for memory in hot_cache["memories"]:
        score = calculate_keyword_score(keywords, memory["summary"])
        if score > 0:
            hot_results.append({
                **memory,
                "score": score,
                "match_type": "keyword_hot"
            })
    
    # Step 3: Archive 回退（如果热缓存未命中）
    if not hot_results:
        archive_results = scan_archive_for_keywords(keywords, limit)
        return archive_results
    
    # Step 4: 排序并返回
    hot_results.sort(key=lambda x: x["score"], reverse=True)
    return hot_results[:limit]
```

### 2.3 混合模式 (mode="hybrid")

**流程**：
```
1. 先执行标签匹配（最快路径）
2. 如果标签匹配结果足够（>= limit/2），返回
3. 否则，用关键词搜索补充结果
4. 合并去重，按 score 排序
```

**代码示例**：
```python
def recall_hybrid(query: str, limit: int = 10) -> list[dict]:
    # Step 1: 标签匹配
    tag_results = recall_by_tags(query, limit=limit)
    
    if len(tag_results) >= limit // 2:
        # 标签匹配结果足够，直接返回
        return tag_results
    
    # Step 2: 关键词搜索补充
    keyword_results = recall_by_keyword(query, limit=limit)
    
    # Step 3: 合并去重
    seen_ids = {r["id"] for r in tag_results}
    for r in keyword_results:
        if r["id"] not in seen_ids:
            tag_results.append(r)
            seen_ids.add(r["id"])
    
    # Step 4: 按 score 排序
    tag_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    return tag_results[:limit]
```

---

## 3. 关键词搜索算法

### 3.1 分词器 (tokenize)

Lite 版本使用纯 Python 实现，无外部依赖：

```python
import re

# 中文停用词
STOPWORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人',
    '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
    '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '么'
}

def tokenize(text: str) -> set[str]:
    """
    轻量级分词：
    1. 全角转半角
    2. 转小写（英文）
    3. 去除标点符号
    4. 按空格/换行分割
    5. 去除停用词
    """
    # 全角转半角
    text = fullwidth_to_halfwidth(text)
    
    # 转小写
    text = text.lower()
    
    # 去除标点
    text = re.sub(r'[^\w\s]', ' ', text)
    
    # 分割
    words = text.split()
    
    # 去除停用词和单字
    words = [w for w in words if w not in STOPWORDS and len(w) > 1]
    
    return set(words)


def fullwidth_to_halfwidth(text: str) -> str:
    """全角转半角"""
    result = []
    for char in text:
        code = ord(char)
        if code == 0x3000:  # 全角空格
            code = 0x0020
        elif 0xFF01 <= code <= 0xFF5E:  # 全角字符
            code -= 0xFEE0
        result.append(chr(code))
    return ''.join(result)
```

### 3.2 得分计算

```python
def calculate_keyword_score(keywords: set[str], text: str) -> float:
    """
    计算关键词匹配得分：
    score = 匹配关键词数 / 总关键词数
    """
    text_keywords = tokenize(text)
    
    matched = keywords & text_keywords
    score = len(matched) / len(keywords) if keywords else 0
    
    # 考虑出现次数
    # 多次出现的关键词权重更高
    # （简化版暂不实现）
    
    return score
```

### 3.3 Archive 扫描

```python
def scan_archive_for_keywords(keywords: set[str], limit: int = 10) -> list[dict]:
    """
    扫描 Archive TXT 查找关键词匹配
    用于热缓存未命中时的回退
    """
    results = []
    
    # 扫描所有 Archive TXT
    archive_paths = list_archive_txts()
    
    for archive_path in archive_paths:
        data = read_archive(archive_path)
        
        # 合并标题 + 正文进行匹配
        full_text = data["content"]
        
        # 提取摘要（第一个 ## 摘要 下的内容）
        summary = extract_summary(full_text)
        full_text_for_match = summary + " " + full_text
        
        score = calculate_keyword_score(keywords, full_text_for_match)
        
        if score > 0:
            results.append({
                "id": data["memory_id"],
                "timestamp": data["metadata"].get("created", ""),
                "tags": data["metadata"].get("tags", []),
                "links": data["metadata"].get("links", []),
                "summary": summary,
                "archive_path": str(archive_path),
                "score": score,
                "match_type": "keyword_archive"
            })
    
    # 排序并返回 Top N
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
```

---

## 4. 精确查找

### 4.1 按 memory_id 查找

```python
def recall_by_id(memory_id: str) -> dict | None:
    """
    直接通过 memory_id 查找记忆
    用于已知 memory_id 的场景
    """
    # 先查热缓存
    hot_cache = read_hot_cache()
    for memory in hot_cache["memories"]:
        if memory["memory_id"] == memory_id:
            return memory
    
    # 热缓存未命中，查 Archive
    archive_path = find_archive_path(memory_id)
    if archive_path:
        data = read_archive(archive_path)
        return {
            "id": memory_id,
            "memory_id": memory_id,
            "timestamp": data["metadata"].get("created", ""),
            "tags": data["metadata"].get("tags", []),
            "links": data["metadata"].get("links", []),
            "content": data["content"],
            "archive_path": str(archive_path),
            "source": data["metadata"].get("source", "manual")
        }
    
    return None
```

---

## 5. 检索性能

### 5.1 各模式性能预期

| 模式 | 100 条记忆 | 500 条记忆 | 1000 条记忆 |
|------|-----------|-----------|------------|
| tags | < 5ms | < 5ms | < 5ms |
| keyword（热缓存命中） | < 20ms | < 50ms | < 100ms |
| keyword（Archive 扫描） | < 100ms | < 300ms | < 500ms |

### 5.2 优化策略

**热缓存命中的重要性**：
- 热缓存容量 200 条，涵盖最近活跃的记忆
- 90% 的查询应该命中热缓存
- Archive 扫描仅作为回退路径

**未来优化方向**：
- 索引文件（`links.json`）按字母排序，二分查找
- 热缓存增加关键词倒排索引
- Archive 扫描增加文件名缓存

---

## 6. 与 Full 版本的差异

| 维度 | Lite | Full |
|------|------|------|
| 语义搜索 | ❌ | ✅ bge-m3 向量相似度 |
| 同义词支持 | ❌ | ✅ |
| 拼音搜索 | ❌ | ✅ |
| 检索速度（大量数据） | 较慢 | 更快 |
| 依赖 | 零依赖 | Ollama + ChromaDB |

---

*本文档为 Memoria Lite v4.0 读取设计。*
