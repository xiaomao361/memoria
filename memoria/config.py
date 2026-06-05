"""配置模块"""

import json
import os
from pathlib import Path

MEMORIA_ROOT = Path(os.environ.get("MEMORIA_ROOT", Path.home() / ".claracore" / "memoria")).expanduser()
STORE_DIR = MEMORIA_ROOT / "store"
DB_PATH = MEMORIA_ROOT / "memoria.db"
VECTORS_DIR = MEMORIA_ROOT / "vectors"
BACKUPS_DIR = MEMORIA_ROOT / "backups"
LABEL_ALIASES_PATH = MEMORIA_ROOT / "label_aliases.json"

OLLAMA_URL = "http://localhost:11434"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIM = 1024
EMBEDDING_MAX_CHARS = 2000

CHROMA_COLLECTION = "memoria"
CHROMA_PRIVATE_COLLECTION = "memoria_private"

DORMANT_DAYS = 30
HOT_LIMIT = 50

DEFAULT_LABEL_ALIASES = {
    "kraken": ["kraken项目"],
    "memoria": ["memoria项目"],
}


def load_label_aliases() -> dict[str, list[str]]:
    """加载标签别名配置。文件不存在时回退到默认配置。"""
    aliases = DEFAULT_LABEL_ALIASES
    if LABEL_ALIASES_PATH.exists():
        try:
            data = json.loads(LABEL_ALIASES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                aliases = data
        except json.JSONDecodeError:
            aliases = DEFAULT_LABEL_ALIASES

    normalized = {}
    for canonical, variants in aliases.items():
        canonical_name = str(canonical).strip().lower()
        if not canonical_name:
            continue
        seen = set()
        merged = [canonical_name]
        seen.add(canonical_name)
        for item in variants or []:
            name = str(item).strip().lower()
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(name)
        normalized[canonical_name] = merged
    return normalized
