#!/usr/local/bin/python3.12
"""
Memoria 共用工具库

整合所有重复函数，消除代码冗余。

包含：
- P0-1: 时间戳修复
- P0-3: 摘要校验
- P1-2: 公共函数抽取
"""

import json
import requests
from datetime import datetime, timezone
from pathlib import Path

try:
    import chromadb
except ImportError:
    chromadb = None


# ========== 路径配置 ==========
CHROMA_DB_PATH = Path.home() / ".qclaw/memoria/chroma_db"
MEMORIA_DIR = Path.home() / ".qclaw/skills/memoria"
MEMORIA_INDEX_FILE = MEMORIA_DIR / "memoria.json"
ARCHIVE_DIR = MEMORIA_DIR / "archive"
SESSIONS_DIR = Path.home() / ".qclaw/agents/main/sessions"

# Ollama 配置
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "bge-m3"
SUMMARY_MODEL = "qwen2.5:3b-instruct-q4_K_M"


# ========== ChromaDB ==========

def get_chroma_collection():
    """获取 ChromaDB collection"""
    if not chromadb:
        raise ImportError("ChromaDB not installed. Run: pip3 install chromadb")
    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_or_create_collection(name="memories", metadata={"hnsw:space": "cosine"})


# ========== Embedding ==========

def get_embedding(text: str) -> list:
    """获取文本向量"""
    text = text[:500].strip()
    if not text:
        return None
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=30
        )
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        print(f"❌ Embedding failed: {e}")
        return None


# ========== 摘要生成 ==========

def generate_summary(conversation_text: str, model: str = SUMMARY_MODEL) -> str:
    """用 LLM 生成摘要"""
    if not conversation_text or not conversation_text.strip():
        return ""
    
    prompt = f"""你是一个记忆整理助手。
以下是一段对话，请用一句话总结核心内容（15-30字以内，不要超过30字）：

{conversation_text}

摘要："""
    
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "temperature": 0.3,
            },
            timeout=60
        )
        response.raise_for_status()
        summary = response.json().get("response", "").strip()
        
        if summary:
            summary = summary.split("\n")[0].strip()
            if len(summary) > 50:
                summary = summary[:50]
            return summary
    except Exception as e:
        print(f"⚠️  Summary generation failed: {e}")
    
    return ""


def generate_summary_from_messages(messages: list, limit: int = 15, model: str = SUMMARY_MODEL) -> str:
    """从消息列表生成摘要（统一接口）"""
    conversation_text = extract_conversation_text(messages, limit=limit)
    return generate_summary(conversation_text, model=model)


# ========== 摘要校验 (P0-3) ==========

def is_valid_summary(summary: str) -> bool:
    """
    摘要质量校验
    
    过滤规则：
    1. 长度过短（< 5 字符）
    2. 包含已知的垃圾模式
    3. 标点符号过多
    """
    if not summary or len(summary) < 5:
        return False
    
    # 1. 固定黑名单
    JUNK_PATTERNS = [
        "【自动归档】",
        "对话记录",
        "unknown",
        "空对话",
        "无内容",
        "自动归档对话",
    ]
    if any(p in summary for p in JUNK_PATTERNS):
        return False
    
    # 2. 长度检查（中文按字符数，英文按词数）
    chinese_chars = sum(1 for c in summary if '\u4e00' <= c <= '\u9fff')
    if chinese_chars > len(summary) * 0.3:
        if len(summary) < 10:
            return False
    else:
        words = summary.split()
        if len(words) < 3:
            return False
    
    # 3. 标点符号过多
    punct_count = sum(1 for c in summary if c in "。，、！？、；：")
    if len(summary) > 0 and punct_count / len(summary) > 0.3:
        return False
    
    return True


# ========== 时间戳 (P0-1) ==========

def get_session_start_time(messages: list) -> float:
    """
    从消息列表中提取最早的时间戳（对话实际发生时间）
    返回 Unix 时间戳（float），ChromaDB $gte 过滤用
    """
    for msg in messages:
        ts = msg.get("timestamp", "")
        if not ts and "message" in msg:
            ts = msg.get("message", {}).get("timestamp", "")
        
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except:
                pass
    
    return datetime.now(timezone.utc).timestamp()


# ========== 消息提取 ==========

def extract_conversation_text(messages: list, limit: int = 20) -> str:
    """从消息列表中提取对话文本"""
    texts = []
    
    for msg in messages:
        # 支持两种格式
        if "message" in msg:
            # session JSONL 格式
            msg_data = msg.get("message", {})
            role = msg_data.get("role", "")
            content = msg_data.get("content", [])
            timestamp = msg.get("timestamp", "")
        else:
            # archive 格式
            role = msg.get("role", "")
            content = msg.get("text", msg.get("content", ""))
            timestamp = msg.get("timestamp", "")
        
        if role not in ("user", "assistant"):
            continue
        
        text = ""
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c.get("text", "").strip()
                    break
        elif isinstance(content, str):
            text = content.strip()
        
        if text and "Sender (untrusted metadata)" not in text:
            prefix = "👤" if role == "user" else "🤖"
            texts.append(f"{prefix} {text[:200]}")
            if len(texts) >= limit * 2:
                break
    
    return "\n".join(texts[:limit])


def extract_messages_from_jsonl(path: Path) -> list:
    """从 session JSONL 文件提取消息列表"""
    messages = []
    if not path.exists():
        return messages
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except:
                    continue
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message", {})
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                timestamp = obj.get("timestamp", "")
                content = msg.get("content", [])
                text = ""
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text = c.get("text", "").strip()
                            break
                elif isinstance(content, str):
                    text = content.strip()
                if text:
                    messages.append({"role": role, "text": text, "timestamp": timestamp})
    except Exception as e:
        print(f"⚠️  Failed to read {path.name}: {e}")
    return messages


# ========== Tags 推断 ==========

def infer_tags(messages: list) -> list:
    """从消息内容推断标签（规则匹配 + 兜底）"""
    all_text = " ".join((m.get("text", m.get("content", "")).lower() for m in messages if isinstance(m, dict)))
    
    tags = []
    tag_map = {
        "memoria": ["memoria", "记忆系统", "向量", "chromadb", "recall"],
        "织影": ["织影", "aelovia", "weave", "vera", "iris", "nova"],
        "副业": ["副业", "兼职", "收入", "月入"],
        "埃洛维亚": ["埃洛维亚", "世界观", "lore", "法则"],
        "技术": ["python", "linux", "服务器", "架构", "运维", "docker", "git", "sql", "api"],
        "日常": ["日常", "聊天", "心情", "今天"],
        "日程": ["日历", "日程", "提醒", "cron", "定时", "heartbeat"],
        "ThreadVibe": ["threadvibe", "websocket"],
        "kraken": ["kraken", "春敏", "报告生成"],
        "clara": ["clara", "soul.md", "identity", "inner.md"],
    }
    for tag, keywords in tag_map.items():
        if any(kw in all_text for kw in keywords):
            tags.append(tag)
    return tags or ["未分类"]


def infer_tags_with_llm(summary: str, conversation_text: str = "", model: str = SUMMARY_MODEL) -> list:
    """用 LLM 从摘要推断标签（P1-3，更准确）"""
    if not summary:
        return ["未分类"]
    
    content = summary
    if conversation_text:
        content = f"摘要：{summary}\n\n对话片段：{conversation_text[:300]}"
    
    prompt = f"""根据以下内容，给出 1-3 个简短标签（中文，用逗号分隔，不要解释）。
标签应该反映主题，例如：技术、日常、memoria、织影、副业、埃洛维亚、kraken 等。

{content}

标签："""
    
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "temperature": 0.1,
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json().get("response", "").strip()
        
        if result:
            # 解析标签
            tags = [t.strip() for t in result.split(",") if t.strip()]
            tags = [t[:10] for t in tags[:3]]  # 最多 3 个，每个最长 10 字
            if tags:
                return tags
    except Exception as e:
        pass  # 静默失败，fallback 到规则
    
    return ["未分类"]


# ========== Channel 检测 ==========

def infer_channel(path: Path, messages: list) -> str:
    """从路径或消息内容推断渠道（OpenClaw session 不区分渠道，只能靠猜测）"""
    filename = path.name.lower()
    if "feishu" in filename:
        return "feishu"
    if "wechat" in filename:
        return "wechat"
    
    # 扫描所有用户消息，寻找渠道线索
    for m in messages:
        if m.get("role") == "user":
            text = m.get("text", m.get("content", "")).lower()
            # 直接提到渠道
            if "feishu" in text or "飞书" in text:
                return "feishu"
            if "wechat" in text or "微信" in text:
                return "wechat"
    
    # Fallback: 检查 Sender metadata 的 label
    for m in messages:
        if m.get("role") == "user":
            text = m.get("text", m.get("content", ""))
            if "Sender (untrusted metadata)" in text:
                # 提取 label 字段
                import re
                match = re.search(r'"label"\s*:\s*"([^"]+)"', text)
                if match:
                    label = match.group(1).lower()
                    if "feishu" in label:
                        return "feishu"
                    if "wechat" in label or "weixin" in label:
                        return "wechat"
                    # openclaw-control-ui 是 webchat
                    if "openclaw-control-ui" in label:
                        return "webchat"
                break
    
    return "webchat"


def detect_channel_from_messages(messages: list) -> str:
    """从消息列表检测渠道（P1-4 修复）"""
    for msg in messages:
        # 优先从顶层 channel 字段读取
        channel = msg.get("channel", "")
        if channel:
            ch = channel.lower()
            if "feishu" in ch or "飞书" in ch:
                return "feishu"
            if "weixin" in ch or "wechat" in ch or "微信" in ch:
                return "wechat"
            if "telegram" in ch:
                return "telegram"
        
        # 从消息内容推断
        if msg.get("type") == "message":
            msg_data = msg.get("message", {})
            content = msg_data.get("content", [])
            text = ""
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text = c.get("text", "").lower()
                        break
            elif isinstance(content, str):
                text = content.lower()
            
            if "feishu" in text or "飞书" in text:
                return "feishu"
            if "wechat" in text or "微信" in text:
                return "wechat"
            
            return "webchat"
    
    return "webchat"


# ========== 热缓存 ==========

def load_hot_cache() -> list:
    """加载热缓存（memoria.json）"""
    if not MEMORIA_INDEX_FILE.exists():
        return []
    
    try:
        with open(MEMORIA_INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        memories = []
        for entry in data.get("memories", []):
            memories.append((
                entry.get("id", ""),
                entry.get("summary", ""),
                {
                    "timestamp": entry.get("timestamp", ""),
                    "channel": entry.get("channel", ""),
                    "tags": entry.get("tags", []),
                    "session_id": entry.get("session_id", ""),
                    "source": "hot_cache",
                },
                None
            ))
        
        return memories
    except Exception as e:
        print(f"⚠️  Failed to load hot cache: {e}")
        return []
