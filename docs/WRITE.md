# Memoria Lite 写入设计

> 本文档描述 Lite 版本的写入设计，三步写入（去掉向量层）。

---

## 1. 写入接口

### 1.1 store() 函数签名

```python
def store(
    content: str,
    tags: list[str] | None = None,
    links: list[str] | None = None,
    source: str = "manual",
    session_id: str | None = None,
    memory_id: str | None = None
) -> dict:
    """
    写入一条记忆
    
    Args:
        content: Markdown 格式的记忆内容
        tags: 标签列表，用于分类和检索
        links: 关联链接，自动从 content 中提取 [[双向链接]]
        source: 来源标识，如 "manual" / "auto" / "cron"
        session_id: 关联的会话 ID
        memory_id: 指定 memory_id（不指定则自动生成）
    
    Returns:
        dict: 写入结果，包含 memory_id 和 archive_path
    """
```

### 1.2 返回格式

```python
{
    "success": True,
    "memory_id": "abc123",
    "archive_path": "2026-04/abc123.txt",
    "tags": ["用户偏好", "沟通风格"],
    "links": ["沟通风格"],
    "created": "2026-04-08T06:00:00Z"
}
```

---

## 2. 三步写入流程

Lite 版本采用三步独立写入，不回滚：

```
┌─────────────────────────────────────────────────────────────┐
│                        store(content)                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: 写入 Archive TXT                                   │
│  • 内容: YAML front matter + Markdown 正文                   │
│  • 路径: archive/{year-month}/{memory_id}.txt              │
│  • 状态: 唯一真实来源                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 更新热缓存                                          │
│  • 追加到 memoria.json 的 memories[]                        │
│  • 超出容量时 FIFO 淘汰最旧条目                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: 更新 links 索引                                     │
│  • 从 content 中提取 [[双向链接]]                            │
│  • 合并到 links.json                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 详细实现

### 3.1 Step 1: 生成 memory_id

```python
import uuid
from datetime import datetime, timezone

def generate_memory_id() -> str:
    """生成唯一的 memory_id"""
    return str(uuid.uuid4())[:12]  # 取前12位，便于阅读


def now_iso() -> str:
    """获取当前 UTC 时间（ISO 格式）"""
    return datetime.now(timezone.utc).isoformat()
```

### 3.2 Step 1: 写入 Archive TXT

```python
from pathlib import Path

def write_archive(
    memory_id: str,
    content: str,
    tags: list[str],
    links: list[str],
    source: str,
    session_id: str | None
) -> Path:
    """写入 Archive TXT"""
    
    # 确定月份目录
    now = datetime.now(timezone.utc)
    month_dir = ARCHIVE_ROOT / f"{now.year}-{now.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    
    # 构建文件路径
    archive_path = month_dir / f"{memory_id}.txt"
    
    # 构建内容
    file_content = build_archive_content(
        memory_id=memory_id,
        content=content,
        tags=tags,
        links=links,
        source=source,
        session_id=session_id,
        created=now_iso()
    )
    
    # 写入文件
    archive_path.write_text(file_content, encoding="utf-8")
    
    return archive_path


def build_archive_content(
    memory_id: str,
    content: str,
    tags: list[str],
    links: list[str],
    source: str,
    session_id: str | None,
    created: str
) -> str:
    """构建 Archive TXT 内容（YAML front matter + Markdown）"""
    
    # 构建 YAML front matter
    front_matter_lines = [
        "---",
        f"memory_id: {memory_id}",
        f"created: {created}",
        f"modified: {created}",
        "tags:"
    ]
    
    for tag in tags:
        front_matter_lines.append(f"  - {tag}")
    
    front_matter_lines.append("links:")
    for link in links:
        front_matter_lines.append(f"  - {link}")
    
    front_matter_lines.extend([
        f"source: {source}",
        f"session_id: {session_id or ''}",
        "---"
    ])
    
    front_matter = "\n".join(front_matter_lines)
    
    return f"{front_matter}\n\n{content}"
```

### 3.3 Step 2: 更新热缓存

```python
def append_to_hot_cache(
    memory_id: str,
    archive_path: Path,
    tags: list[str],
    links: list[str],
    summary: str,
    source: str,
    session_id: str | None
):
    """追加记录到热缓存"""
    
    # 读取现有热缓存
    hot_cache_path = HOT_CACHE_PATH
    if hot_cache_path.exists():
        with open(hot_cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"version": "4.0", "updated_at": now_iso(), "memories": []}
    
    # 构建新记录
    new_record = {
        "id": memory_id,
        "memory_id": memory_id,
        "timestamp": now_iso(),
        "tags": tags,
        "links": links,
        "summary": summary,
        "source": source,
        "archive_path": str(archive_path),
        "session_id": session_id or "",
        "storage_type": "hot"
    }
    
    # 插入到最前（最新）
    data["memories"].insert(0, new_record)
    data["updated_at"] = now_iso()
    
    # 检查容量，FIFO 淘汰
    if len(data["memories"]) > HOT_CACHE_LIMIT:
        data["memories"] = data["memories"][:HOT_CACHE_LIMIT]
    
    # 写回文件
    with open(hot_cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_summary(content: str, max_length: int = 100) -> str:
    """从 content 中提取摘要"""
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
```

### 3.4 Step 3: 更新 links 索引

```python
import re

def extract_links_from_content(content: str) -> list[str]:
    """从 content 中提取 [[双向链接]]"""
    pattern = r'\[\[([^\]]+)\]\]'
    matches = re.findall(pattern, content)
    return list(set(matches))  # 去重


def update_links_index(memory_id: str, links: list[str]):
    """更新 links.json"""
    
    # 读取现有索引
    links_path = LINKS_PATH
    if links_path.exists():
        with open(links_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"version": "4.0", "updated_at": now_iso(), "links": {}}
    
    # 合并新链接
    for link in links:
        if link not in data["links"]:
            data["links"][link] = []
        if memory_id not in data["links"][link]:
            data["links"][link].append(memory_id)
    
    data["updated_at"] = now_iso()
    
    # 写回文件
    with open(links_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
```

---

## 4. 完整 store() 实现

```python
def store(
    content: str,
    tags: list[str] | None = None,
    links: list[str] | None = None,
    source: str = "manual",
    session_id: str | None = None,
    memory_id: str | None = None
) -> dict:
    """
    写入一条记忆（三步独立执行，不回滚）
    """
    
    # 参数预处理
    tags = tags or []
    links = links or []
    memory_id = memory_id or generate_memory_id()
    
    # 从 content 中提取 [[双向链接]]
    auto_links = extract_links_from_content(content)
    links = list(set(links + auto_links))  # 合并去重
    
    # Step 1: 写入 Archive TXT
    archive_path = write_archive(
        memory_id=memory_id,
        content=content,
        tags=tags,
        links=links,
        source=source,
        session_id=session_id
    )
    
    # Step 2: 更新热缓存
    summary = extract_summary(content)
    append_to_hot_cache(
        memory_id=memory_id,
        archive_path=archive_path,
        tags=tags,
        links=links,
        summary=summary,
        source=source,
        session_id=session_id
    )
    
    # Step 3: 更新 links 索引
    update_links_index(memory_id=memory_id, links=links)
    
    return {
        "success": True,
        "memory_id": memory_id,
        "archive_path": str(archive_path),
        "tags": tags,
        "links": links,
        "created": now_iso()
    }
```

---

## 5. 写入保证

### 5.1 幂等性

- 重复写入同一 memory_id 会覆盖原有内容
- 热缓存同一 memory_id 只保留最新记录
- links.json 同一 link → memory_id 映射不会重复

### 5.2 不回滚原则

```
Step 1: 写入 Archive TXT    ✅ 可能失败
Step 2: 更新热缓存           ⚠️ 可能失败
Step 3: 更新 links 索引      ⚠️ 可能失败
```

**不回滚原因**：
- Archive TXT 是最终来源，失败则整条记忆丢失，无需回滚
- 热缓存可从 Archive 重建
- links.json 可从 Archive 重建
- 部分失败不影响数据完整性

### 5.3 故障恢复

```bash
# 如果写入中途失败，可以用 rebuild 重建索引
python -m memoria rebuild
```

---

## 6. 与 Full 版本的差异

| 维度 | Lite | Full |
|------|------|------|
| 写入步骤 | 3 步 | 4 步 |
| 向量计算 | ❌ | ✅ Step 2: bge-m3 embedding |
| 写入时间 | < 50ms | < 100ms |
| 失败风险点 | 热缓存、links | 热缓存、links、向量库 |

---

*本文档为 Memoria Lite v4.0 写入设计。*
