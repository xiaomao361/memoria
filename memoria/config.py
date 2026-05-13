"""配置模块"""

from pathlib import Path

MEMORIA_ROOT = Path.home() / ".qclaw" / "memoria"
STORE_DIR = MEMORIA_ROOT / "store"
DB_PATH = MEMORIA_ROOT / "memoria.db"
VECTORS_DIR = MEMORIA_ROOT / "vectors"
BACKUPS_DIR = MEMORIA_ROOT / "backups"

OLLAMA_URL = "http://localhost:11434"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIM = 1024
EMBEDDING_MAX_CHARS = 2000

CHROMA_COLLECTION = "memoria"
CHROMA_PRIVATE_COLLECTION = "memoria_private"

DORMANT_DAYS = 30
HOT_LIMIT = 50
