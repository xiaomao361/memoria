# Memoria 运维手册

> 面向 AI Agent 的操作指南
> 版本: v5.2

---

## 1. 日常运维

### 1.1 检查系统状态

```bash
# 查看统计
python3 scripts/manage.py stats

# 查看私密记忆统计
python3 scripts/manage.py --private stats

# 检测重复
python3 scripts/manage.py dupes
python3 scripts/manage.py --private dupes
```

### 1.2 清理重复

```bash
# 自动清理（相似度>95%）
python3 scripts/cleanup_dupes.py auto-delete --threshold 0.95

# 私密记忆清理
python3 scripts/cleanup_dupes.py --private auto-delete --threshold 0.95
```

### 1.3 标签归一化

```bash
# 统一大小写
python3 scripts/normalize_tags.py --execute
```

---

## 2. 故障排查

### 2.1 热缓存损坏

**症状**: recall.py 报错或返回空

**修复**:
```bash
# 从 archive 重建热缓存
python3 scripts/rebuild.py hot-cache
```

### 2.2 向量库损坏

**症状**: 语义搜索返回异常结果

**修复**:
```bash
# 从 archive 重建向量库
python3 scripts/rebuild.py vector
```

### 2.3 链接索引不一致

**症状**: `[[链接]]` 无法跳转

**修复**:
```bash
# 重建链接索引
python3 scripts/rebuild.py links
```

### 2.4 全量重建

**最后手段**: 从 archive 重建所有存储
```bash
python3 scripts/rebuild.py all
```

---

## 3. 定时任务

| 任务 | 脚本 | 建议时间 |
|-----|------|---------|
| Session 冷备份 | auto_archive.py | 每天 23:30 |
| 梦境整理 | dream.py --execute | 每天 02:00 |
| 主动召回 | proactive_recall.py | 每天 10:00 |
| Refine 层 | refine.py | 每周日 03:00 |
| 沉睡降权 | demote_stale.py | 每周六 04:00 |

---

## 4. Web 管理界面

### 4.1 启动

```bash
python3 scripts/web_server.py --port 8080
```

### 4.2 功能

- 浏览记忆列表
- 搜索（关键词/标签）
- 删除记忆
- 编辑标签

---

## 5. 配置项

见 `scripts/lib/config.py`:

| 配置 | 默认值 | 说明 |
|-----|--------|------|
| HOT_CACHE_CAPACITY | 200 | 热缓存容量 |
| SIMILARITY_THRESHOLD | 0.85 | 增量更新阈值 |
| DEDUP_WINDOW_HOURS | 1 | 去重时间窗口 |
| DEDUP_SIMILARITY | 0.8 | 去重相似度阈值 |

---

## 6. 紧急联系

遇到问题:
1. 检查 `scripts/` 日志输出
2. 查看 `~/.qclaw/memoria/` 文件权限
3. 运行 `rebuild.py` 恢复
