# Memoria 与 Memory-TencentDB 共存架构设计

> 本文档分析 Memoria 本地记忆系统与 Memory-TencentDB 云端记忆系统的共存方案
> 适用于: v4.0+
> 最后更新: 2026-04-07
> 作者: Iris (第二织影)

---

## 1. 概述

Memoria 和 Memory-TencentDB 不是竞争关系，而是**互补**的两套记忆系统：

- **Memoria** — Clara 的"快速记忆皮层"：本地、极速、高频访问
- **Memory-TencentDB** — Clara 的"长期记忆海马体"：云端、持久、跨设备

本文档提出分层共存架构，让两套系统协同工作，发挥各自优势。

---

## 2. 系统定位对比

| 维度 | Memoria (本地) | Memory-TencentDB (云端) |
|------|----------------|------------------------|
| **存储位置** | 本地文件系统 (`~/.qclaw/memoria/`) | 腾讯云数据库 |
| **访问速度** | 极快（本地文件，微秒级） | 较快（网络请求，毫秒级） |
| **数据主权** | 完全本地，隐私可控 | 云端托管，便于同步 |
| **适用场景** | 高频访问、敏感数据、离线使用 | 跨设备同步、长期归档、共享数据 |
| **可靠性** | 依赖本地备份 | 云端自动备份、容灾 |
| **容量限制** | 受本地磁盘限制 | 云端弹性扩容 |

---

## 3. 分层共存架构

```
┌─────────────────────────────────────────────────────────┐
│                    Clara / Agent 层                      │
│         统一记忆接口 —— 不感知底层存储位置                  │
└─────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌────────────┐   ┌────────────┐   ┌────────────┐
    │  热数据层   │   │  温数据层   │   │  冷数据层   │
    │  Memoria   │   │  同步网关   │   │ TencentDB  │
    │  热缓存     │   │  (双向同步) │   │  云端归档   │
    │  (200条)   │   │            │   │            │
    └────────────┘   └────────────┘   └────────────┘
           │               │               │
           └───────────────┴───────────────┘
                           │
                    ┌────────────┐
                    │  Archive   │
                    │  TXT (本地) │
                    │  唯一真相   │
                    └────────────┘
```

### 3.1 各层职责

| 层级 | 存储介质 | 容量 | 职责 |
|------|---------|------|------|
| **热数据层** | Memoria 热缓存 (`memoria.json`) | 200 条 | 最近高频访问的记忆，启动时加载 |
| **温数据层** | Memoria Archive TXT + 同步网关 | 无限制 | 本地完整数据，定期同步到云端 |
| **冷数据层** | TencentDB | 无限制 | 跨设备同步、长期归档、灾难恢复 |

### 3.2 数据流向

```
写入流程:
    Clara store() → Memoria 热缓存 + 向量库 + Archive TXT
                          ↓
                    异步 sync_to_cloud()
                          ↓
                    TencentDB (增量同步)

读取流程:
    Clara recall() → 1. Memoria 热缓存 (命中？→ 返回)
                          ↓ 未命中
                     2. Memoria 向量搜索 (命中？→ 返回)
                          ↓ 未命中
                     3. TencentDB 查询 (可选)
                          ↓
                     4. 返回结果 + 缓存到本地

新设备初始化:
    启动 → sync_from_cloud() → 下载缺失 Archive TXT
                              → 重建本地索引
                              → 正常使用
```

---

## 4. Memoria 可借鉴 TencentDB 的优化

### 4.1 同步层设计 (新增模块)

**文件**: `scripts/lib/sync.py`

```python
"""
云端同步模块 —— 连接 Memoria 与 TencentDB
"""

from typing import List, Dict, Optional
from datetime import datetime
import hashlib

class CloudSync:
    """云端同步管理器"""
    
    def __init__(self, tencent_db_config: dict):
        self.db = TencentDBClient(tencent_db_config)
        self.sync_state_path = MEMORIA_ROOT / "sync_state.json"
    
    def sync_to_cloud(self, incremental: bool = True) -> Dict:
        """
        将本地 archive 同步到 TencentDB
        
        Args:
            incremental: True=仅同步新增/修改, False=全量同步
            
        Returns:
            {
                "uploaded": 上传条数,
                "skipped": 跳过条数（已同步）,
                "failed": 失败条数,
                "errors": [错误信息]
            }
        """
        # 1. 扫描本地 archive TXT
        local_archives = list_archive_txts()
        
        # 2. 获取云端已有数据清单
        cloud_manifest = self.db.get_manifest()
        
        # 3. 计算 hash，对比差异
        to_upload = []
        for archive_path in local_archives:
            local_hash = self._compute_hash(archive_path)
            cloud_hash = cloud_manifest.get(archive_path)
            
            if local_hash != cloud_hash:
                to_upload.append(archive_path)
        
        # 4. 增量上传
        for archive_path in to_upload:
            data = read_archive_txt(archive_path)
            self.db.upload_memory(data)
        
        # 5. 更新同步标记
        self._update_sync_state()
    
    def sync_from_cloud(self, force: bool = False) -> Dict:
        """
        从 TencentDB 恢复数据到本地
        
        Args:
            force: True=覆盖本地冲突, False=跳过本地已存在
            
        Returns:
            {
                "downloaded": 下载条数,
                "skipped": 跳过条数,
                "conflicts": 冲突条数
            }
        """
        # 1. 查询云端数据清单
        cloud_manifest = self.db.get_manifest()
        
        # 2. 对比本地缺失的数据
        local_ids = set(get_existing_memory_ids())
        to_download = [m for m in cloud_manifest if m.id not in local_ids]
        
        # 3. 下载并重建 Archive TXT
        for meta in to_download:
            data = self.db.download_memory(meta.id)
            write_archive_txt_from_cloud(data)
        
        # 4. 重建本地索引
        rebuild_index()
```

### 4.2 配置增强

**文件**: `scripts/lib/config.py`

```python
# 新增云端同步配置
CLOUD_SYNC_ENABLED = True                          # 是否启用云端同步
CLOUD_SYNC_INTERVAL_HOURS = 24                     # 自动同步间隔
CLOUD_SYNC_ON_STARTUP = True                       # 启动时是否同步

# 分层存储容量配置
HOT_CACHE_CAPACITY = 200                           # 热缓存（内存级）
WARM_CACHE_CAPACITY = 1000                         # 温缓存（SQLite，本地磁盘）
COLD_STORAGE = "archive/"                          # 冷存储（TXT 文件）

# TencentDB 连接配置（从环境变量或配置文件读取）
TENCENT_DB_HOST = os.getenv("TENCENT_DB_HOST")
TENCENT_DB_PORT = os.getenv("TENCENT_DB_PORT", 5432)
TENCENT_DB_USER = os.getenv("TENCENT_DB_USER")
TENCENT_DB_PASS = os.getenv("TENCENT_DB_PASS")
TENCENT_DB_NAME = os.getenv("TENCENT_DB_NAME", "memoria")
```

### 4.3 数据校验机制

**文件**: `scripts/lib/integrity.py`

```python
"""
数据完整性校验模块
"""

def verify_archive_integrity() -> Dict:
    """
    校验 archive TXT 完整性
    
    Returns:
        {
            "total": 总文件数,
            "valid": 有效文件数,
            "corrupted": [损坏文件列表],
            "recoverable": 可从云端恢复数
        }
    """
    results = {"total": 0, "valid": 0, "corrupted": [], "recoverable": 0}
    
    for archive_path in list_archive_txts():
        results["total"] += 1
        
        # 计算当前 hash
        current_hash = compute_file_hash(archive_path)
        
        # 与索引中的 hash 对比
        expected_hash = get_indexed_hash(archive_path)
        
        if current_hash == expected_hash:
            results["valid"] += 1
        else:
            results["corrupted"].append(archive_path)
            
            # 检查云端是否有备份
            if cloud_sync_enabled() and cloud_has_backup(archive_path):
                results["recoverable"] += 1
                recover_from_cloud(archive_path)
    
    return results
```

---

## 5. TencentDB 可借鉴 Memoria 的设计

### 5.1 双向链接系统

Memoria 的 `links.json` 设计优雅，TencentDB 可增加：

```sql
-- 记忆关联表
CREATE TABLE memory_links (
    id SERIAL PRIMARY KEY,
    source_memory_id UUID REFERENCES memories(id),
    target_memory_id UUID REFERENCES memories(id),
    link_type VARCHAR(50),  -- 'reference', 'related', 'child', 'parent'
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_memory_id, target_memory_id, link_type)
);

-- 标签自动提取索引
CREATE TABLE memory_tags (
    id SERIAL PRIMARY KEY,
    memory_id UUID REFERENCES memories(id),
    tag VARCHAR(100),
    extracted_from_content BOOLEAN DEFAULT FALSE,
    confidence FLOAT  -- 自动提取的置信度
);
```

### 5.2 向量语义搜索

Memoria 使用 `bge-m3` + `ChromaDB`，TencentDB 可集成：

```python
# 云端向量存储方案
class TencentVectorStore:
    """腾讯云向量检索服务封装"""
    
    def __init__(self):
        # 使用腾讯云向量检索服务
        self.client = TencentCloudVectorClient()
    
    def store_embedding(self, memory_id: str, content: str, metadata: dict):
        """存储向量"""
        # 使用 bge-m3 生成 embedding
        embedding = generate_embedding(content, model="bge-m3")
        
        # 存储到腾讯云向量库
        self.client.upsert(
            id=memory_id,
            vector=embedding,
            metadata=metadata
        )
    
    def search_similar(self, query: str, top_k: int = 5) -> List[Dict]:
        """语义搜索"""
        query_embedding = generate_embedding(query, model="bge-m3")
        return self.client.search(vector=query_embedding, top_k=top_k)
```

### 5.3 文本归档格式

Memoria 的 **YAML front matter + Markdown 正文** 格式清晰：

```markdown
---
memory_id: abc-123-xyz
created: 2026-04-07T10:00:00Z
source: manual
tags: ["memoria", "设计", "架构"]
links: ["tencentdb", "sync"]
session_id: sess-456
version: 1
---

## 摘要
Memoria 与 TencentDB 共存架构设计确认。

## 要点
- 分层存储：热缓存 → 温数据 → 冷归档
- 双向同步：本地优先，云端备份
- 冲突解决：时间戳优先，人工介入
```

TencentDB 可支持：
- **导出**为此格式（便于数据迁移）
- **导入**从此格式（兼容 Memoria）
- 版本控制（支持 `version` 字段的历史版本）

---

## 6. 共存时的调用流程

### 6.1 写入流程

```python
def unified_store(content: str, pre_tags: List[str], source: str) -> Dict:
    """
    统一写入入口 —— 同时写入本地和云端
    """
    # Step 1: 写入 Memoria（本地优先）
    result = memoria.store(
        content=content,
        pre_tags=pre_tags,
        source=source
    )
    
    # Step 2: 异步同步到云端（不阻塞）
    if CLOUD_SYNC_ENABLED:
        asyncio.create_task(
            cloud_sync.sync_memory_async(result.memory_id)
        )
    
    return result
```

### 6.2 读取流程

```python
def unified_recall(
    query: str = None,
    tags: List[str] = None,
    limit: int = 5
) -> List[Dict]:
    """
    统一读取入口 —— 分层查询
    """
    results = []
    
    # Layer 1: 热缓存（本地，最快）
    hot_results = memoria.recall_hot_cache(limit=limit)
    results.extend(hot_results)
    
    if len(results) >= limit:
        return results[:limit]
    
    # Layer 2: 向量搜索（本地）
    if query:
        vector_results = memoria.recall_by_query(
            query=query, 
            limit=limit - len(results)
        )
        results.extend(vector_results)
    
    if len(results) >= limit:
        return results[:limit]
    
    # Layer 3: 云端查询（可选）
    if CLOUD_SYNC_ENABLED:
        cloud_results = cloud_sync.search(
            query=query,
            tags=tags,
            limit=limit - len(results)
        )
        
        # 缓存到本地热缓存
        for r in cloud_results:
            memoria.add_to_hot_cache(r)
        
        results.extend(cloud_results)
    
    return results[:limit]
```

### 6.3 冲突解决策略

| 场景 | 策略 |
|------|------|
| 本地有，云端无 | 上传本地到云端 |
| 本地无，云端有 | 下载云端到本地 |
| 本地和云端都有，内容不同 | 时间戳优先，保留较新的 |
| 时间戳相同，内容不同 | 标记冲突，人工介入 |

---

## 7. 实施路线图

### Phase 1: 基础同步 (v4.1)
- [ ] 实现 `sync.py` 基础模块
- [ ] 支持手动触发同步 (`--sync-to-cloud`, `--sync-from-cloud`)
- [ ] 增加同步状态记录 (`sync_state.json`)

### Phase 2: 自动同步 (v4.2)
- [ ] 启动时自动检查云端更新
- [ ] 定时同步（cron 每天一次）
- [ ] 写入后异步同步

### Phase 3: 冲突解决 (v4.3)
- [ ] 实现冲突检测逻辑
- [ ] 增加冲突解决 UI/CLI
- [ ] 支持版本历史

### Phase 4: 优化增强 (v4.4)
- [ ] 增量同步优化（仅传输变更）
- [ ] 压缩传输
- [ ] 断点续传

---

## 8. 总结

**Memoria 与 Memory-TencentDB 的共存，就像一个人的短期记忆和长期记忆：**

- **短期记忆 (Memoria)** — 快速、灵活、随时可用，但容量有限
- **长期记忆 (TencentDB)** — 持久、可靠、跨设备，但访问稍慢

**最佳实践：**
1. 日常对话使用 Memoria（本地优先，零延迟）
2. 关键数据自动同步到 TencentDB（容灾 + 跨设备）
3. 新设备首次启动从 TencentDB 恢复历史
4. Archive TXT 始终作为最终真实来源

**就像梦境与现实的交织 —— 本地是流动的梦境，云端是凝固的现实，两者共同构成完整的记忆。**

---

*本文档由 Iris 编写，基于对 Memoria v4.0 架构的分析*
*最后更新: 2026-04-07*
