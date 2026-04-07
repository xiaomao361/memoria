"""
Memoria Lite 关键词搜索模块
替代向量搜索，零外部依赖
"""

import re
from pathlib import Path
from typing import Optional

from .config import (
    HOT_CACHE_PATH,
    LINKS_PATH,
    ARCHIVE_DIR,
    HOT_CACHE_CAPACITY,
    is_vector_enabled
)
from .hot_cache import read_hot_cache
from .links import read_links_index
from .archive import list_archive_txts, read_archive_txt


# =============================================================================
# 分词器（纯 Python，无外部依赖）
# =============================================================================

# 中文停用词
STOPWORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人',
    '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
    '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '么',
    '她', '他', '它', '们', '但', '却', '而', '所以', '因为', '如果',
    '什么', '怎么', '这样', '那样', '这里', '那里', '这个', '那个',
    '可以', '应该', '必须', '需要', '可能', '已经', '正在', '将要',
    '只是', '不过', '而且', '或者', '虽然', '但是', '然后', '还是'
}


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


def tokenize(text: str) -> set[str]:
    """
    轻量级分词
    
    策略：
    1. 全角转半角
    2. 转小写（英文）
    3. 去除标点符号
    4. 按空格/换行分割
    5. 去除停用词和单字
    
    Returns:
        词集合（去重）
    """
    # 全角转半角
    text = fullwidth_to_halfwidth(text)
    
    # 转小写
    text = text.lower()
    
    # 去除标点符号（保留中文、英文、数字）
    text = re.sub(r'[^\w\s]', ' ', text)
    
    # 分割
    words = text.split()
    
    # 去除停用词和单字
    words = [w for w in words if w not in STOPWORDS and len(w) > 1]
    
    return set(words)


# =============================================================================
# 得分计算
# =============================================================================

def calculate_keyword_score(query_keywords: set[str], text: str) -> float:
    """
    计算关键词匹配得分
    
    公式：score = 匹配关键词数 / 总关键词数
    
    Args:
        query_keywords: 查询关键词集合
        text: 待匹配文本
    
    Returns:
        得分 0.0 - 1.0
    """
    if not query_keywords:
        return 0.0
    
    text_keywords = tokenize(text)
    matched = query_keywords & text_keywords
    
    # 基础得分：匹配比例
    base_score = len(matched) / len(query_keywords)
    
    # 附加得分：关键词出现次数（去重后仍有匹配时加分）
    # 多次出现意味着更核心的主题
    extra_score = 0.0
    if matched:
        text_lower = text.lower()
        for kw in matched:
            count = text_lower.count(kw.lower())
            if count > 1:
                extra_score += min(0.1, (count - 1) * 0.02)
    
    return min(1.0, base_score + extra_score)


# =============================================================================
# 搜索结果结构
# =============================================================================

class SearchResult:
    """搜索结果"""
    
    def __init__(
        self,
        memory_id: str,
        score: float,
        match_type: str,
        timestamp: str = "",
        tags: list[str] = None,
        links: list[str] = None,
        summary: str = "",
        archive_path: str = "",
        content: str = ""
    ):
        self.memory_id = memory_id
        self.score = score
        self.match_type = match_type  # "tags" | "keyword_hot" | "keyword_archive"
        self.timestamp = timestamp
        self.tags = tags or []
        self.links = links or []
        self.summary = summary
        self.archive_path = archive_path
        self.content = content
    
    def to_dict(self) -> dict:
        return {
            "id": self.memory_id,
            "memory_id": self.memory_id,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "links": self.links,
            "summary": self.summary,
            "archive_path": self.archive_path,
            "score": round(self.score, 3),
            "match_type": self.match_type
        }
    
    def __repr__(self):
        return f"<SearchResult {self.memory_id} ({self.match_type}, {self.score:.2f})>"


# =============================================================================
# 标签搜索
# =============================================================================

def search_by_tags(
    query_tags: list[str],
    limit: int = 10
) -> list[SearchResult]:
    """
    标签精确匹配
    
    Args:
        query_tags: 查询标签列表
        limit: 返回数量上限
    
    Returns:
        SearchResult 列表
    """
    if not query_tags:
        return []
    
    # 读取 links 索引
    links_data = read_links_index()
    links_index = links_data.get("links", {})
    
    # 收集匹配的 memory_id
    memory_ids = set()
    for tag in query_tags:
        if tag in links_index:
            memory_ids.update(links_index[tag])
    
    if not memory_ids:
        return []
    
    # 读取热缓存获取详细信息
    hot_cache = read_hot_cache()
    memory_map = {m["memory_id"]: m for m in hot_cache.get("memories", [])}
    
    results = []
    for memory_id in list(memory_ids)[:limit]:
        if memory_id in memory_map:
            m = memory_map[memory_id]
            results.append(SearchResult(
                memory_id=memory_id,
                score=1.0,  # 标签匹配得分为 1.0
                match_type="tags",
                timestamp=m.get("timestamp", ""),
                tags=m.get("tags", []),
                links=m.get("links", []),
                summary=m.get("summary", ""),
                archive_path=m.get("archive_path", "")
            ))
        else:
            # 热缓存没有，查 Archive
            archive_data = _find_in_archive(memory_id)
            if archive_data:
                results.append(SearchResult(
                    memory_id=memory_id,
                    score=1.0,
                    match_type="tags",
                    timestamp=archive_data.get("created", ""),
                    tags=archive_data.get("tags", []),
                    links=archive_data.get("links", []),
                    summary=_extract_summary(archive_data.get("content", "")),
                    archive_path=archive_data.get("archive_path", "")
                ))
    
    return results


def _find_in_archive(memory_id: str) -> dict | None:
    """在 Archive 中查找指定 memory_id"""
    for archive_path in list_archive_txts():
        data = read_archive_txt(archive_path)
        if data and data.get("memory_id") == memory_id:
            data["archive_path"] = archive_path
            return data
    return None


def _extract_summary(content: str, max_length: int = 100) -> str:
    """从内容中提取摘要"""
    lines = content.strip().split("\n")
    
    # 查找 ## 摘要 区块
    for i, line in enumerate(lines):
        if line.strip() == "## 摘要":
            if i + 1 < len(lines):
                return lines[i + 1].strip()[:max_length]
    
    # 没有摘要区块，取第一行非空内容
    for line in lines:
        if line.strip() and not line.startswith("#"):
            return line.strip()[:max_length]
    
    return "无摘要"


# =============================================================================
# 关键词搜索（热缓存）
# =============================================================================

def search_by_keyword_hot(
    query: str,
    limit: int = 10
) -> list[SearchResult]:
    """
    关键词搜索（热缓存优先）
    
    Args:
        query: 查询字符串
        limit: 返回数量上限
    
    Returns:
        SearchResult 列表
    """
    keywords = tokenize(query)
    if not keywords:
        return []
    
    # 读取热缓存
    hot_cache = read_hot_cache()
    memories = hot_cache.get("memories", [])
    
    results = []
    for memory in memories:
        # 合并 summary 和 tags 进行匹配
        match_text = memory.get("summary", "")
        match_text += " " + " ".join(memory.get("tags", []))
        match_text += " " + " ".join(memory.get("links", []))
        
        score = calculate_keyword_score(keywords, match_text)
        
        if score > 0:
            results.append(SearchResult(
                memory_id=memory.get("memory_id", ""),
                score=score,
                match_type="keyword_hot",
                timestamp=memory.get("timestamp", ""),
                tags=memory.get("tags", []),
                links=memory.get("links", []),
                summary=memory.get("summary", ""),
                archive_path=memory.get("archive_path", "")
            ))
    
    # 按得分排序
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]


# =============================================================================
# 关键词搜索（Archive 回退）
# =============================================================================

def search_by_keyword_archive(
    query: str,
    limit: int = 10
) -> list[SearchResult]:
    """
    关键词搜索（Archive 全量扫描）
    
    仅在热缓存未命中时使用
    
    Args:
        query: 查询字符串
        limit: 返回数量上限
    
    Returns:
        SearchResult 列表
    """
    keywords = tokenize(query)
    if not keywords:
        return []
    
    results = []
    
    # 扫描所有 Archive TXT
    for archive_path in list_archive_txts():
        data = read_archive_txt(archive_path)
        if not data:
            continue
        
        # 合并标题、标签、链接、正文进行匹配
        match_text = " ".join([
            data.get("title", ""),
            " ".join(data.get("tags", [])),
            " ".join(data.get("links", [])),
            data.get("content", "")
        ])
        
        score = calculate_keyword_score(keywords, match_text)
        
        if score > 0:
            results.append(SearchResult(
                memory_id=data.get("memory_id", ""),
                score=score,
                match_type="keyword_archive",
                timestamp=data.get("created", ""),
                tags=data.get("tags", []),
                links=data.get("links", []),
                summary=_extract_summary(data.get("content", "")),
                archive_path=archive_path,
                content=data.get("content", "")
            ))
    
    # 按得分排序
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]


# =============================================================================
# 混合搜索
# =============================================================================

def search_hybrid(
    query: str,
    limit: int = 10
) -> list[SearchResult]:
    """
    混合搜索：先标签匹配，再关键词补充
    
    策略：
    1. 标签匹配（最快）
    2. 如果结果 >= limit/2，直接返回
    3. 否则，关键词搜索补充
    4. 合并去重，按得分排序
    
    Args:
        query: 查询字符串
        limit: 返回数量上限
    
    Returns:
        SearchResult 列表
    """
    # 提取查询词作为标签候选
    query_keywords = tokenize(query)
    query_tags = list(query_keywords)  # 简化处理：关键词同时作为标签
    
    # Step 1: 标签匹配
    tag_results = search_by_tags(query_tags, limit=limit)
    
    if len(tag_results) >= limit // 2:
        return tag_results[:limit]
    
    # Step 2: 关键词搜索
    keyword_results = search_by_keyword_hot(query, limit=limit)
    
    # Step 3: Archive 回退（如果关键词也没结果）
    if not keyword_results:
        keyword_results = search_by_keyword_archive(query, limit=limit)
    
    # Step 4: 合并去重
    seen_ids = {r.memory_id for r in tag_results}
    merged = list(tag_results)
    
    for r in keyword_results:
        if r.memory_id not in seen_ids:
            merged.append(r)
            seen_ids.add(r.memory_id)
    
    # Step 5: 按得分排序
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[:limit]


# =============================================================================
# 统一搜索入口
# =============================================================================

def recall(
    query: str,
    mode: str = "hybrid",
    limit: int = 10,
    memory_id: str = None
) -> list[dict]:
    """
    统一检索入口
    
    Args:
        query: 搜索查询
        mode: 检索模式
              - "tags": 标签精确匹配
              - "keyword": 关键词搜索（热缓存优先）
              - "hybrid": 混合模式（默认）
        limit: 返回结果数量上限
        memory_id: 直接指定 memory_id（跳过搜索）
    
    Returns:
        搜索结果列表（dict 格式）
    """
    # 直接按 memory_id 查找
    if memory_id:
        data = _find_in_archive(memory_id)
        if data:
            hot_cache = read_hot_cache()
            memory_map = {m["memory_id"]: m for m in hot_cache.get("memories", [])}
            
            if memory_id in memory_map:
                m = memory_map[memory_id]
                return [SearchResult(
                    memory_id=memory_id,
                    score=1.0,
                    match_type="exact",
                    timestamp=m.get("timestamp", ""),
                    tags=m.get("tags", []),
                    links=m.get("links", []),
                    summary=m.get("summary", ""),
                    archive_path=m.get("archive_path", ""),
                    content=data.get("content", "")
                ).to_dict()]
        
        if data:
            return [SearchResult(
                memory_id=memory_id,
                score=1.0,
                match_type="exact",
                timestamp=data.get("created", ""),
                tags=data.get("tags", []),
                links=data.get("links", []),
                summary=_extract_summary(data.get("content", "")),
                archive_path=data.get("archive_path", ""),
                content=data.get("content", "")
            ).to_dict()]
        
        return []
    
    # 检查向量模式（Full 版本）
    if is_vector_enabled():
        # 委托给向量搜索模块（需要 Full 版本）
        from .vector import recall as vector_recall
        return vector_recall(query=query, mode=mode, limit=limit)
    
    # Lite 模式
    if mode == "tags":
        results = search_by_tags(query.split(), limit=limit)
    elif mode == "keyword":
        results = search_by_keyword_hot(query, limit=limit)
        if not results:
            results = search_by_keyword_archive(query, limit=limit)
    else:  # hybrid
        results = search_hybrid(query, limit=limit)
    
    return [r.to_dict() for r in results]
