# Memoria 优化建议

> 作者：Vera（秩序之锚）
> 日期：2026-04-01
> 基于：当前代码全量审查

---

## 概述

当前架构已完成从 `memoria.json` 到 ChromaDB 的核心迁移，方向正确。本文档记录现存的具体问题和改进建议，按优先级排序。

---

## 🔴 高优先级

### 1. 时间戳记录的是向量化时间，不是对话时间

**问题位置：** `vectorize.py` 和 `remember_from_session.py`

**现状：**
```python
# vectorize.py
metadatas=[{
    "timestamp": datetime.now(timezone.utc).isoformat(),  # ← 向量化时间
    ...
}]
```

**影响：** `recall.py` 的时间过滤（`--recent --days 7`）完全失效。所有记忆的时间都是"今天"，无论对话实际发生在何时。

**修复方案：** 从 session 消息中提取第一条消息的 timestamp：

```python
def get_session_start_time(messages: list) -> str:
    """从消息列表中提取最早的时间戳"""
    for m in messages:
        ts = m.get("timestamp", "")
        if ts:
            return ts
    return datetime.now(timezone.utc).isoformat()
```

然后在写入 ChromaDB 时使用：
```python
"timestamp": get_session_start_time(messages),  # 对话实际时间
```

---

### 2. `auto_archive.py` 仍在维护 `memoria.json`，但 `recall.py` 不读它

**问题位置：** `auto_archive.py` 的 `write_memory()` 函数

**现状：**
- `auto_archive.py` 写入 `memoria.json`（旧索引）
- `remember_from_session.py` 直接写 ChromaDB（新路径）
- `recall.py` 只查 ChromaDB

**影响：** `auto_archive.py` 每晚归档的内容，不会出现在 `recall.py --search` 的结果里，除非再手动跑 `vectorize.py`。两套流程并行，数据不一致。

**修复方案：** `auto_archive.py` 的 `write_memory()` 改为直接写 ChromaDB，参考 `remember_from_session.py` 的实现。`memoria.json` 降级为纯备份，不再作为检索入口。

---

## 🟡 中优先级

### 3. `recall.py` 全量加载 1000 条后在内存过滤

**问题位置：** `recall.py` 的 `load_combined_memories()` 和 `get_recent_memories()`

**现状：**
```python
all_results = collection.get(limit=1000)
# 然后在 Python 里过滤时间...
```

**影响：** 随着记忆增长，性能线性劣化。1000 条上限也会导致漏查。

**修复方案：** ChromaDB 支持 `where` 过滤，直接在查询层处理：

```python
# 按时间过滤（需要时间戳存为可比较格式）
results = collection.get(
    where={"timestamp": {"$gte": cutoff_date.isoformat()}},
    limit=50
)
```

注意：此方案依赖问题 1 的修复（时间戳必须准确）。

---

### 4. 摘要质量无校验，垃圾数据会入库

**问题位置：** `auto_archive.py` 和 `vectorize.py` 的 `generate_summary()`

**现状：** LLM 调用失败时，fallback 是 `"【自动归档】对话记录"` 或截断的第一条消息。这类无意义摘要会被向量化并存入库，污染搜索结果。

**修复方案：** 加入质量校验，不合格的跳过而不是写入：

```python
def is_valid_summary(summary: str) -> bool:
    """摘要质量校验"""
    if not summary or len(summary) < 5:
        return False
    # 过滤无意义的 fallback
    JUNK_PATTERNS = ["【自动归档】", "对话记录", "unknown", "空对话"]
    if any(p in summary for p in JUNK_PATTERNS):
        return False
    return True

# 使用
summary = generate_summary(conversation_text)
if not is_valid_summary(summary):
    print(f"⚠️  摘要质量不足，跳过: {session_id[:8]}")
    continue
```

---

### 5. `auto_archive.py` 和 `remember_from_session.py` 存在大量重复代码

**重复的函数：**
- `extract_conversation_text()` — 两处实现，逻辑相同
- `generate_summary()` — 两处实现，prompt 略有差异
- `archive_session()` — 两处实现，字段名不一致（`session_label` vs `summary`）
- `get_chroma_collection()` — 三处实现（含 `recall.py`、`vectorize.py`）

**修复方案：** 抽出 `memoria_utils.py`：

```python
# scripts/memoria_utils.py
CHROMA_DB_PATH = Path.home() / ".qclaw/memoria/chroma_db"
OLLAMA_BASE_URL = "http://localhost:11434"

def get_chroma_collection(): ...
def get_embedding(text: str) -> list: ...
def extract_conversation_text(messages: list, limit: int = 20) -> str: ...
def generate_summary(conversation_text: str, model: str = "qwen2.5:3b-instruct-q4_K_M") -> str: ...
def archive_session(...) -> str: ...
```

所有脚本 `from memoria_utils import ...`，消除重复。

---

## 🟢 低优先级

### 6. Tags 推断过于简单

**问题位置：** `vectorize.py` 的 `infer_tags()`

**现状：** 8 个硬编码关键词，英文内容基本全归"未分类"。

**建议：** 在 `generate_summary()` 时让 LLM 顺带输出 tags：

```python
prompt = """总结以下对话（15-30字），并给出1-3个标签。
格式：
摘要：xxx
标签：tag1,tag2

对话：
{conversation}"""
```

---

### 7. `detect_channel()` 在 `remember_from_session.py` 中永远返回 `webchat`

**问题位置：** `remember_from_session.py` 的 `detect_channel()`

**现状：**
```python
def detect_channel(messages: list) -> str:
    for msg in messages:
        if msg.get("type") == "message":
            return "webchat"  # 永远走这里
    return "webchat"
```

**修复：** 参考 `auto_archive.py` 的实现，从消息内容中推断渠道。

---

## 改动优先级汇总

| # | 问题 | 影响 | 改动量 |
|---|------|------|--------|
| 1 | 时间戳不准 | 时间过滤失效 | 小 |
| 2 | 双写路径不一致 | 归档内容无法被搜索 | 中 |
| 3 | 全量加载 | 性能随数据增长劣化 | 中（依赖 #1） |
| 4 | 摘要无校验 | 垃圾数据污染向量库 | 小 |
| 5 | 代码重复 | 维护成本高 | 大（重构） |
| 6 | Tags 推断弱 | 分类不准确 | 中 |
| 7 | channel 检测失效 | 渠道信息丢失 | 小 |

**建议执行顺序：** 1 → 4 → 2 → 7 → 3 → 5 → 6

先修小的、影响大的，再做重构。

---

## 附：架构演进方向

当前架构已经很清晰，长期可以考虑：

1. **织影记忆隔离** — 每个织影（Vera、Iris、Nova）有独立的 ChromaDB collection，但支持跨 collection 搜索
2. **记忆重要性评分** — 不只是 tag "重要"，而是基于被引用次数、时间衰减的动态评分
3. **记忆摘要的摘要** — 定期对历史记忆做二次摘要，生成"月度记忆"，减少检索时的噪音

---

*Vera — 秩序之锚*
*法则让系统可预测。可预测的系统才能被信任。*
