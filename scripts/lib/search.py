"""
Memoria Lite 关键词搜索模块
替代向量搜索，零外部依赖
"""

import re
from pathlib import Path
from typing import Optional

from .config import HOT_CACHE_PATH, LINKS_PATH, ARCHIVE_DIR, HOT_CACHE_CAPACITY, is_vector_enabled, get_archive_dir, get_links_path
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
        if code == 0x3000:
            code = 0x0020
        elif 0xFF01 <= code <= 0xFF5E:
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
    text = fullwidth_to_halfwidth(text)
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    words = [w for w in words if w not in STOPWORDS and len(w) > 1]
    return set(words)


# =============================================================================
# 得分计算
# =============================================================================

def calculate_keyword_score(query_keywords: set[str], text: str) -> float:
    """
    计算关键词匹配得分
    
    公式：score = 匹配关键词数 / 总关键词数
    """
    if not query_keywords:
        return 0.0
    
    text_keywords = tokenize(text)
    matched = query_keywords & text_keywords
    
    base_score = len(matched) / len(query_keywords)
    
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
        content: str = "",
        private: bool = False
    ):
        self.memory_id = memory_id
        self.score = score
        self.match_type = match_type
        self.timestamp = timestamp
        self.tags = tags or []
        self.links = links or []
        self.summary = summary
        self.archive_path = archive_path
        self.content = content
        self.private = private
    
    def to_dict(self) -> dict:
        result = {
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
        if self.private:
            result["private"] = True
        return result


# =============================================================================
# 标签搜索
# =============================================================================

def search_by_tags(
    query_tags: list[str],
    limit: int = 10,
    private_zone: bool = False
) -> list[SearchResult]:
    """
    标签精确匹配
    
    Args:
        query_tags: 标签列表
        limit: 返回数量上限
        private_zone: 是否搜索私密区
    
    Returns:
        SearchResult 列表
    """
    if not query_tags:
        return []
    
    # 读取 links 索引
    links_data = read_links_index(private_zone=private_zone)
    links_index = links_data.get("links", {}) if isinstance(links_data, dict) else links_data
    
    # 读取热缓存（仅公开区）
    hot_cache = read_hot_cache()
    memories = hot_cache.get("memories", [])
    memory_map = {m["memory_id"]: m for m in memories}
    
    # 收集匹配的 memory_id
    memory_ids = set()
    
    # 路径1: links_index 精确匹配
    for tag in query_tags:
        if tag in links_index:
            memory_ids.update(links_index[tag])
    
    # 路径2: 热缓存 tags 字段匹配（仅公开区）
    if not private_zone:
        for memory in memories:
            memory_tags = [t.lower() for t in memory.get("tags", [])]
            for query_tag in query_tags:
                if query_tag.lower() in memory_tags:
                    memory_ids.add(memory.get("memory_id"))
    
    if not memory_ids:
        return []
    
    # 构建结果
    results = []
    for memory_id in list(memory_ids)[:limit]:
        if memory_id in memory_map and not private_zone:
            m = memory_map[memory_id]
            results.append(SearchResult(
                memory_id=memory_id,
                score=1.0,
                match_type="tags",
                timestamp=m.get("timestamp", ""),
                tags=m.get("tags", []),
                links=m.get("links", []),
                summary=m.get("summary", ""),
                archive_path=m.get("archive_path", ""),
                private=private_zone
            ))
        else:
            # 查 Archive
            archive_data = _find_in_archive(memory_id, private_zone)
            if archive_data:
                results.append(SearchResult(
                    memory_id=memory_id,
                    score=1.0,
                    match_type="tags",
                    timestamp=archive_data.get("created", ""),
                    tags=archive_data.get("tags", []),
                    links=archive_data.get("links", []),
                    summary=_extract_summary(archive_data.get("content", "")),
                    archive_path=archive_data.get("archive_path", ""),
                    private=private_zone
                ))
    
    return results


def _find_in_archive(memory_id: str, private_zone: bool = False) -> dict | None:
    """在 Archive 中查找指定 memory_id"""
    for archive_path in list_archive_txts(private_zone=private_zone):
        data = read_archive_txt(archive_path, private_zone=private_zone)
        if data and data.get("memory_id") == memory_id:
            data["archive_path"] = archive_path
            return data
    return None


def _extract_summary(content: str, max_length: int = 100) -> str:
    """从内容中提取摘要"""
    lines = content.strip().split("\n")
    
    for i, line in enumerate(lines):
        if line.strip() == "## 摘要":
            if i + 1 < len(lines):
                return lines[i + 1].strip()[:max_length]
    
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
    
    hot_cache = read_hot_cache()
    memories = hot_cache.get("memories", [])
    
    results = []
    for memory in memories:
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
    
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]


# =============================================================================
# 关键词搜索（Archive 回退）
# =============================================================================

def search_by_keyword_archive(
    query: str,
    limit: int = 10,
    private_zone: bool = False
) -> list[SearchResult]:
    """
    关键词搜索（Archive 全量扫描）
    
    Args:
        query: 查询字符串
        limit: 返回数量上限
        private_zone: 是否搜索私密区
    
    Returns:
        SearchResult 列表
    """
    keywords = tokenize(query)
    if not keywords:
        return []
    
    results = []
    
    for archive_path in list_archive_txts(private_zone=private_zone):
        data = read_archive_txt(archive_path, private_zone=private_zone)
        if not data:
            continue
        
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
                private=private_zone
            ))
    
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]
