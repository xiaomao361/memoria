# Memoria Lite 迁移指南

> 本文档描述 Lite 版本与 Full 版本之间的数据迁移方法。

---

## 1. 版本概述

| 版本 | 向量搜索 | 外部依赖 | 适用场景 |
|------|---------|---------|---------|
| **Lite** | ❌ | 零依赖 | 新手、日常记忆 |
| **Full** | ✅ bge-m3 | Ollama + ChromaDB | 语义搜索、高级用户 |

**核心优势**：Lite 和 Full 的数据格式**完全兼容**，可以随时互转。

---

## 2. 数据兼容性

### 2.1 共享格式

```
✅ Archive TXT      — 完全兼容
✅ 热缓存 (memoria.json) — 完全兼容
✅ links.json       — 完全兼容
❌ 向量库 (chroma_db/)  — Lite 不使用，Full 独有
```

### 2.2 迁移时的数据处理

| 数据类型 | Lite → Full | Full → Lite |
|----------|-------------|-------------|
| Archive TXT | 保留 | 保留 |
| 热缓存 | 保留 | 保留 |
| links.json | 保留 | 保留 |
| 向量库 | 需要重建 | 自动忽略 |

---

## 3. 迁移方案

### 3.1 Lite → Full（添加向量搜索）

当你需要更强大的语义搜索能力时：

```bash
# Step 1: 安装 Full 版本的依赖
pip install chromadb ollama

# Step 2: 启动 Ollama 并拉取模型
ollama pull bge-m3

# Step 3: 运行迁移脚本
python -m memoria migrate --to full
```

**迁移脚本做了什么**：
1. 扫描 `archive/*.txt`
2. 对每个 TXT 计算 bge-m3 向量
3. 写入向量库
4. 更新配置文件

**预计时间**：
- 100 条记忆：约 1 分钟
- 1000 条记忆：约 10 分钟

### 3.2 Full → Lite（降级为轻量版）

当你想简化依赖时：

```bash
# Step 1: 运行迁移脚本
python -m memoria migrate --to lite

# Step 2:（可选）删除向量库释放空间
rm -rf ~/.qclaw/memoria/chroma_db/
```

**迁移脚本做了什么**：
1. 确认 Archive TXT 完整
2. 更新配置文件，关闭向量选项
3. 提示用户可以删除向量库

**不会删除任何数据**，只是不再使用向量搜索。

---

## 4. migrate.py 实现

### 4.1 命令行接口

```python
# migrate.py
import argparse

def main():
    parser = argparse.ArgumentParser(description="Memoria Lite ↔ Full 迁移工具")
    parser.add_argument(
        "--to",
        choices=["lite", "full"],
        required=True,
        help="目标版本: lite 或 full"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制迁移，覆盖已有数据"
    )
    
    args = parser.parse_args()
    
    if args.to == "full":
        migrate_to_full(force=args.force)
    else:
        migrate_to_lite(force=args.force)
```

### 4.2 Lite → Full 迁移

```python
def migrate_to_full(force: bool = False):
    """从 Lite 迁移到 Full（重建向量库）"""
    
    print("🔄 正在迁移到 Full 版本...")
    
    # 检查 Ollama 是否运行
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags")
        if response.status_code != 200:
            print("❌ Ollama 未运行，请先启动 Ollama")
            return
    except:
        print("❌ Ollama 未运行，请先启动 Ollama")
        return
    
    # 检查向量库是否已存在
    chroma_db_path = CHROMA_DB_PATH
    if chroma_db_path.exists() and not force:
        print("⚠️  向量库已存在，使用 --force 强制重建")
        return
    
    # 扫描 Archive
    archive_paths = list_archive_txts()
    print(f"📁 发现 {len(archive_paths)} 条记忆")
    
    # 重建向量库
    from lib.vector import write_vector, get_collection
    
    collection = get_collection()  # 创建/获取 collection
    
    for i, path in enumerate(archive_paths):
        data = read_archive(path)
        
        write_vector(
            memory_id=data["memory_id"],
            archive_path=path,
            content=data["content"],
            tags=data["metadata"].get("tags", []),
            links=data["metadata"].get("links", []),
            source=data["metadata"].get("source", "manual"),
            session_id=data["metadata"].get("session_id", "")
        )
        
        if (i + 1) % 10 == 0:
            print(f"  进度: {i + 1}/{len(archive_paths)}")
    
    # 更新配置
    update_config({"vector_enabled": True})
    
    print("✅ 迁移完成！现在你可以使用 Full 版本的语义搜索功能")
```

### 4.3 Full → Lite 迁移

```python
def migrate_to_lite(force: bool = False):
    """从 Full 迁移到 Lite"""
    
    print("🔄 正在迁移到 Lite 版本...")
    
    # 确认 Archive 完整性
    archive_paths = list_archive_txts()
    print(f"📁 发现 {len(archive_paths)} 条记忆")
    
    if not archive_paths:
        print("⚠️  未发现 Archive 文件，请确认数据完整")
        return
    
    # 更新配置
    update_config({"vector_enabled": False})
    
    print("✅ 迁移完成！向量搜索已关闭")
    print()
    print("可选操作：删除向量库释放空间")
    print(f"  rm -rf {CHROMA_DB_PATH}")
```

---

## 5. 手动迁移

如果迁移脚本不可用，可以手动操作：

### 5.1 手动 Lite → Full

```bash
# 1. 安装依赖
pip install chromadb ollama

# 2. 启动 Ollama
ollama serve &

# 3. 拉取模型
ollama pull bge-m3

# 4. 重建向量库
python -c "
import sys
sys.path.insert(0, 'scripts')
from lib.archive import list_archive_txts, read_archive
from lib.vector import write_vector

for path in list_archive_txts():
    data = read_archive(path)
    write_vector(
        memory_id=data['memory_id'],
        archive_path=path,
        content=data['content'],
        tags=data['metadata'].get('tags', []),
        links=data['metadata'].get('links', []),
        source=data['metadata'].get('source', 'manual'),
        session_id=data['metadata'].get('session_id', '')
    )
    print(f'✓ {data[\"memory_id\"]}')
"
```

### 5.2 手动 Full → Lite

```bash
# 1. 关闭向量功能（修改 config.json）
# 将 "vector_enabled": true 改为 "vector_enabled": false

# 2. 删除向量库（可选）
rm -rf ~/.qclaw/memoria/chroma_db/
```

---

## 6. 故障排查

### 6.1 迁移失败

**问题**：Ollama 连接失败
```
❌ Ollama 未运行
```
**解决**：
```bash
# 确保 Ollama 正在运行
ollama serve

# 测试连接
curl http://localhost:11434/api/tags
```

**问题**：向量库已存在
```
⚠️ 向量库已存在
```
**解决**：
```bash
# 使用 --force 强制重建
python -m memoria migrate --to full --force
```

### 6.2 数据丢失

**问题**：迁移后数据不见了
**解决**：
- Archive TXT 是唯一真实来源
- 检查 `~/.qclaw/memoria/archive/` 目录
- 如果 Archive 完好，可以从 Archive 重建所有索引

```bash
# 从 Archive 重建所有索引
python -m memoria rebuild --force
```

---

## 7. 迁移检查清单

### Lite → Full
- [ ] 安装 Ollama
- [ ] 启动 Ollama 服务
- [ ] `ollama pull bge-m3`
- [ ] 运行 `migrate --to full`
- [ ] 验证向量搜索正常工作

### Full → Lite
- [ ] 运行 `migrate --to lite`
- [ ] 验证标签/关键词搜索正常工作
- [ ]（可选）删除向量库 `rm -rf chroma_db/`

---

*本文档为 Memoria Lite v4.0 迁移指南。*
