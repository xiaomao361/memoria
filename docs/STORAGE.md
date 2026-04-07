# Memoria Lite 存储设计

> 本文档描述 Lite 版本的存储设计，去掉了向量库后的简化架构。

---

## 1. 存储目录结构

```
~/.qclaw/memoria/              # 根目录（可配置）
├── config.json                # 配置文件
├── memoria.json               # 热缓存
├── links.json                 # 双向链接索引
└── archive/                   # 归档存储
    ├── 2026-03/
    │   ├── abc123.txt
    │   └── def456.txt
    └── 2026-04/
        ├── 789xyz.txt
        └── ...
```

**跨平台处理：**
- `~/.qclaw/` 使用 `pathlib.Path.home() / ".qclaw"`，自动适配各系统
- Windows：`C:\Users\{user}\.qclaw\`
- macOS：`/Users/{user}/.qclaw/`
- Linux：`/home/{user}/.qclaw/`

---

## 2. 热缓存 (memoria.json)

### 2.1 用途

热缓存存储**最近访问的记忆摘要**，用于快速查询。读取时优先查热缓存，未命中再扫描 Archive。

### 2.2 数据结构

```json
{
    "version": "4.0",
    "updated_at": "2026-04-08T06:00:00Z",
    "memories": [
        {
            "id": "abc123",
            "timestamp": "2026-04-08T06:00:00Z",
            "tags": ["用户偏好", "沟通风格"],
            "links": ["沟通风格", "项目决策"],
            "summary": "用户喜欢简洁的回答，不喜欢废话",
            "source": "manual",
            "memory_id": "abc123",
            "archive_path": "2026-04/abc123.txt",
            "session_id": "sess_456",
            "storage_type": "hot"
        },
        ...
    ]
}
```

### 2.3 容量与淘汰

- **容量**：默认 200 条（可配置 `hot_cache_limit`）
- **淘汰策略**：FIFO（先进先出），超出容量时删除最旧的条目
- **淘汰时机**：每次写入新记忆后检查，超出容量则删除最早的条目

### 2.4 刷新方式

**实时写入**：
```python
# 写入时直接追加到 memoria.json
def append_to_hot_cache(memory_record: dict):
    data = read_hot_cache()
    data["memories"].insert(0, memory_record)  # 插入到最前
    data["updated_at"] = now_iso()
    
    # 检查容量，超出则删除最旧的
    if len(data["memories"]) > HOT_CACHE_LIMIT:
        data["memories"] = data["memories"][:HOT_CACHE_LIMIT]
    
    write_hot_cache(data)
```

---

## 3. 双向链接索引 (links.json)

### 3.1 用途

links.json 存储**标签和链接的映射关系**，用于：
- 快速按标签查询记忆
- 追踪记忆之间的关联
- 支持 `[[双向链接]]` 语法

### 3.2 数据结构

```json
{
    "version": "4.0",
    "updated_at": "2026-04-08T06:00:00Z",
    "links": {
        "用户偏好": ["abc123", "def456"],
        "沟通风格": ["abc123", "xyz789"],
        "项目决策": ["def456"],
        "梦织者": ["lmn001", "lmn002"]
    }
}
```

### 3.3 链接提取规则

从记忆内容中自动提取 `[[双向链接]]`：

```python
import re

def extract_links(content: str) -> list[str]:
    """从 Markdown 内容中提取 [[链接]]"""
    pattern = r'\[\[([^\]]+)\]\]'
    matches = re.findall(pattern, content)
    return list(set(matches))  # 去重

# 示例
content = """
用户提到他喜欢 [[简洁风格]]，特别讨厌 [[废话连篇]]。
"""
links = extract_links(content)
# 结果：["简洁风格", "废话连篇"]
```

### 3.4 链接更新

```python
def update_links_index(memory_id: str, new_links: list[str]):
    """更新 links.json"""
    data = read_links_index()
    
    # 新增的链接 → 追加到映射
    for link in new_links:
        if link not in data["links"]:
            data["links"][link] = []
        if memory_id not in data["links"][link]:
            data["links"][link].append(memory_id)
    
    write_links_index(data)
```

---

## 4. 归档存储 (archive/)

### 4.1 用途

Archive 是**唯一真实来源**，存储每条记忆的完整内容。即使热缓存和 links.json 损坏，也可以从 Archive 重建。

### 4.2 目录组织

按月分目录，避免单目录文件过多：

```
archive/
├── 2026-03/          # 3月归档
├── 2026-04/          # 4月归档（当前）
└── ...
```

**命名规则**：
- 目录名：`{year}-{month:02d}/`
- 文件名：`{memory_id}.txt`

### 4.3 Archive TXT 格式

每条记忆存储为一个独立 TXT 文件：

```markdown
---
memory_id: abc123
created: 2026-04-08T06:00:00Z
modified: 2026-04-08T06:00:00Z
tags:
  - 用户偏好
  - 沟通风格
links:
  - 沟通风格
  - 项目决策
source: manual
session_id: sess_456
---

# 用户偏好

## 摘要
用户喜欢简洁的回答，不喜欢废话。

## 详情
在 2026-04-07 的对话中，用户明确表示：
- 喜欢直接进入主题
- 不需要"当然可以"之类的铺垫
- 用列表而非表格

这是通过实际对话观察得出的结论。
```

### 4.4 写入 Archive

```python
def write_archive(memory_id: str, content: str, metadata: dict) -> Path:
    """写入 Archive TXT"""
    
    # 确定月份目录
    now = datetime.now(timezone.utc)
    month_dir = ARCHIVE_ROOT / f"{now.year}-{now.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    
    # 构建文件路径
    archive_path = month_dir / f"{memory_id}.txt"
    
    # 构建内容（YAML front matter + Markdown）
    file_content = build_archive_content(memory_id, content, metadata)
    
    # 写入文件
    archive_path.write_text(file_content, encoding="utf-8")
    
    return archive_path


def build_archive_content(memory_id: str, content: str, metadata: dict) -> str:
    """构建 Archive TXT 内容"""
    
    # YAML front matter
    front_matter = f"""---
memory_id: {memory_id}
created: {metadata.get('created', now_iso())}
modified: {now_iso()}
tags:"""
    
    for tag in metadata.get('tags', []):
        front_matter += f"\n  - {tag}"
    
    front_matter += f"""
links:"""
    
    for link in metadata.get('links', []):
        front_matter += f"\n  - {link}"
    
    front_matter += f"""
source: {metadata.get('source', 'manual')}
session_id: {metadata.get('session_id', '')}
---

{content}"""
    
    return front_matter
```

### 4.5 读取 Archive

```python
def read_archive(archive_path: Path) -> dict:
    """读取 Archive TXT"""
    
    content = archive_path.read_text(encoding="utf-8")
    
    # 解析 YAML front matter
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid archive format: {archive_path}")
    
    front_matter_text = parts[1].strip()
    body = parts[2].strip()
    
    # YAML 解析
    metadata = yaml.safe_load(front_matter_text)
    
    return {
        "metadata": metadata,
        "content": body,
        "memory_id": metadata["memory_id"]
    }
```

---

## 5. 配置文件 (config.json)

### 5.1 默认配置

```json
{
    "version": "4.0",
    "root": "~/.qclaw/memoria",
    "hot_cache_limit": 200,
    "archive_path": "archive",
    "links_path": "links.json",
    "hot_cache_path": "memoria.json"
}
```

### 5.2 配置优先级

1. 环境变量（如 `MEMORIA_ROOT`）
2. 用户配置文件 `~/.qclaw/memoria/config.json`
3. 默认值（代码中硬编码）

### 5.3 路径解析

```python
def resolve_path(path: str) -> Path:
    """解析配置路径，支持 ~ 和环境变量"""
    path = os.path.expanduser(path)  # 展开 ~
    path = os.path.expandvars(path)  # 展开环境变量
    return Path(path)

# 示例
resolve_path("~/.qclaw/memoria")
# Windows: C:\Users\{user}\.qclaw\memoria
# Linux: /home/{user}/.qclaw/memoria
```

---

## 6. 重建索引 (rebuild.py)

当热缓存或 links.json 损坏时，可以从 Archive 重建：

```bash
python -m memoria rebuild          # 增量重建
python -m memoria rebuild --force   # 强制清空后重建
```

### 6.1 重建流程

```
1. 清空热缓存和 links.json（--force 模式）
2. 扫描 archive/*.txt
3. 对每个 TXT：
   - 解析 YAML front matter
   - 提取 memory_id、tags、links
   - 追加到热缓存
   - 更新 links 索引
4. 写回热缓存和 links.json
```

### 6.2 幂等性保证

- 增量模式（无 `--force`）：跳过已存在的 memory_id
- 可反复执行，不会丢失数据
- Archive TXT 不会被打扰

---

*本文档为 Memoria Lite v4.0 存储设计。*
