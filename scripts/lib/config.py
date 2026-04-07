"""
配置模块
"""

from pathlib import Path

# 路径配置
MEMORIA_ROOT = Path.home() / ".qclaw" / "memoria"
ARCHIVE_DIR = MEMORIA_ROOT / "archive"
CHROMA_DB_PATH = MEMORIA_ROOT / "chroma_db"
HOT_CACHE_PATH = MEMORIA_ROOT / "memoria.json"
LINKS_PATH = MEMORIA_ROOT / "links.json"
LOGS_DIR = MEMORIA_ROOT / "logs"

# 热缓存配置
HOT_CACHE_CAPACITY = 200

# 向量库配置
EMBEDDING_MODEL = "BAAI/bge-m3"
COLLECTION_NAME = "memoria"
EMBEDDING_MAX_CHARS = 512

# 增量更新配置
SIMILARITY_THRESHOLD = 0.85
