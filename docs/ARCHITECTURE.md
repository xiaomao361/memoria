# Memoria Lite 架构设计

> 本文档描述 Memoria Lite 的整体架构和设计决策。

---

## 1. 设计理念

**简单即力量。**

Memoria Full 追求最强的检索能力，代价是复杂的依赖（Ollama + ChromaDB + bge-m3）。Lite 版本反其道而行：

> **如果 90% 的查询只需要标签匹配和关键词搜索，为什么要加载向量模型？**

Lite 的核心假设：
- 单用户使用，记忆量在百级别
- 查询以精确匹配为主，语义模糊查询为辅
- 用户希望零配置、零维护

---

## 2. 存储架构

### 2.1 三级存储

```
┌─────────────────────────────────────────────────────────────┐
│                      热缓存 (Hot Cache)                       │
│                        memoria.json                           │
│   • 最近 200 条记忆的摘要                                    │
│   • FIFO 淘汰策略                                            │
│   • 读取速度：毫秒级                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      链接索引 (Links Index)                   │
│                        links.json                            │
│   • 双向链接图谱                                            │
│   • 标签 → memory_id 映射                                   │
│   • 支持 [[链接]] 语法自动提取                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      归档存储 (Archive)                       │
│                        archive/                              │
│   • 按月分目录：archive/2026-04/                            │
│   • 完整内容存储（YAML front matter + Markdown 正文）        │
│   • 唯一真实来源，不可丢失                                   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 各层职责

| 存储层 | 文件 | 职责 | 淘汰策略 |
|--------|------|------|----------|
| 热缓存 | `memoria.json` | 快速读取入口 | FIFO，保留最近 200 条 |
| 链接索引 | `links.json` | 标签匹配、链接追踪 | 无（索引文件） |
| 归档存储 | `archive/*.txt` | 完整内容存储 | 无（永久保留） |

### 2.3 Archive TXT 格式

每条记忆以独立 TXT 文件存储，格式如下：

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

**格式规范：**
- 使用 YAML front matter 存储元数据
- 正文使用 Markdown 格式
- 文件名：`{memory_id}.txt`
- 编码：UTF-8（跨平台兼容）

---

## 3. 检索架构

### 3.1 三级检索

```
recall(query, mode)
    │
    ├─ mode="tags"
    │   │
    │   └─ ① links.json 精确匹配
    │       查询 links_index[tag] → memory_id 列表
    │       加载对应 Archive TXT → 返回结果
    │
    ├─ mode="keyword"
    │   │
    │   ├─ ② 热缓存摘要匹配
    │   │   分词 → 关键词 → 匹配 summary
    │   │
    │   └─ ③ Archive 全文扫描（回退）
    │       分词 → 关键词 → 扫描所有 TXT
    │
    └─ mode="hybrid"
        │
        ├─ 先 tags 匹配
        └─ 再 keyword 补充
```

### 3.2 关键词搜索算法

```python
def keyword_search(query: str, limit: int = 10) -> list[dict]:
    """
    关键词搜索流程：
    
    1. 分词：将 query 拆解为关键词
       "用户偏好 沟通风格" → ["用户偏好", "沟通", "风格"]
    
    2. 热缓存匹配：
       - 扫描 memoria.json 的所有 summary
       - 计算每个关键词的出现次数
       - 得分 = 匹配次数 / 总关键词数
    
    3. Archive 回退（如果热缓存未命中）：
       - 扫描 archive/*.txt 的标题 + 正文
       - 同样计算关键词得分
       - 返回 Top N
    
    4. 排序：按得分降序，返回 memory_id 和匹配摘要
    """
```

### 3.3 分词策略

Lite 版本不依赖外部分词库，使用简单的规则分词：

```python
def tokenize(text: str) -> set[str]:
    """
    分词策略（轻量）：
    
    1. 全角转半角
    2. 转小写（英文）
    3. 去除标点符号
    4. 按空格/换行分割
    5. 去除停用词（的、了、在、和、是...）
    6. 返回词集合（去重）
    """
```

**局限性：**
- 不支持同义词（如"电脑"和"计算机"不会匹配）
- 不支持拼音搜索
- 不支持语义理解

**这些是 Lite 的设计权衡**，向量搜索可以解决这些问题，但代价是依赖 Ollama。

---

## 4. 写入流程

### 4.1 四步写入（Full） → 三步写入（Lite）

**Full 版本：**
```
store(content, tags, links)
    │
    ├─ Step 1: 写入 Archive TXT
    ├─ Step 2: 写入向量库（bge-m3 embedding）
    ├─ Step 3: 更新热缓存
    └─ Step 4: 更新 links 索引
```

**Lite 版本：**
```
store(content, tags, links)
    │
    ├─ Step 1: 写入 Archive TXT       ← 真实来源
    ├─ Step 2: 更新热缓存              ← 快速读取
    └─ Step 3: 更新 links 索引         ← 标签匹配
```

### 4.2 写入保证

- **不回滚**：三步独立执行，任一步失败不影响其他步
- **幂等性**：重复写入同一 memory_id 会覆盖
- **最终一致性**：Archive TXT 是唯一真实来源，可以随时重建其他索引

---

## 5. 与 Full 版本的数据兼容性

### 5.1 格式完全一致

| 数据类型 | Lite | Full | 兼容 |
|----------|------|------|------|
| Archive TXT | ✅ | ✅ | 完全一致 |
| 热缓存 JSON | ✅ | ✅ | 完全一致 |
| links.json | ✅ | ✅ | 完全一致 |
| 向量库 | ❌ | ✅ | 不适用 |

### 5.2 迁移策略

```
Lite → Full：
    运行 rebuild.py --force
    自动重建向量库（基于 archive/）

Full → Lite：
    删除向量库目录
    配置文件关闭向量选项
```

详见 [UPGRADE.md](UPGRADE.md)。

---

## 6. 扩展性设计

### 6.1 插件化搜索

```python
# 用户可以自定义搜索插件
class SearchPlugin:
    def search(self, query: str, limit: int) -> list[dict]:
        raise NotImplementedError

# 注册插件
memoria.register_search_plugin("my_search", MyCustomSearch())
```

### 6.2 存储后端

当前使用文件系统存储，未来可扩展：

```python
class StorageBackend:
    def read(self, path: Path) -> str: ...
    def write(self, path: Path, content: str): ...
    def list(self, pattern: str) -> list[Path]: ...

class FileSystemBackend(StorageBackend): ...
class S3Backend(StorageBackend): ...  # 未来
class TencentCloudBackend(StorageBackend): ...  # 未来
```

---

## 7. 设计决策记录

| 决策 | 理由 | 备选方案 |
|------|------|----------|
| 去掉向量搜索 | 降低依赖，零配置 | 保留可选 |
| 使用纯 Python 分词 | 无外部依赖 | jieba / 其他分词库 |
| Archive TXT 为唯一来源 | 数据可靠性，可重建 | 混合存储 |
| 热缓存 FIFO 200 条 | 平衡内存占用和命中率 | 可配置 |
| JSON 格式存储索引 | 人类可读，易调试 | SQLite / 其他 |

---

## 8. 性能预期

| 操作 | Lite 性能 | Full 性能 |
|------|-----------|-----------|
| 写入记忆 | < 50ms | < 100ms（含向量计算） |
| 标签查询 | < 10ms | < 10ms |
| 关键词查询（热缓存命中） | < 50ms | < 50ms |
| 关键词查询（全量扫描） | 200-500ms | < 100ms（向量） |
| 1000 条记忆全量扫描 | ~500ms | ~100ms |

**结论**：在 1000 条记忆以内，Lite 的性能与 Full 相当。超过 1000 条时，Full 的向量搜索优势开始显现。

---

*本文档为 Memoria Lite v4.0 架构设计。*
