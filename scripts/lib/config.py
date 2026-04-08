"""
Memoria Lite 配置模块
零外部依赖，支持私密区
"""

from pathlib import Path
import os

# =============================================================================
# 路径配置（支持跨平台）
# =============================================================================

def _resolve_memoria_root() -> Path:
    """解析 Memoria 根目录，支持环境变量覆盖"""
    # 1. 环境变量
    env_root = os.environ.get("MEMORIA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    
    # 2. 默认值
    return (Path.home() / ".qclaw" / "memoria").resolve()


# 根目录
MEMORIA_ROOT = _resolve_memoria_root()

# 公开区路径
ARCHIVE_DIR = MEMORIA_ROOT / "archive"
HOT_CACHE_PATH = MEMORIA_ROOT / "memoria.json"
LINKS_PATH = MEMORIA_ROOT / "links.json"
LOGS_DIR = MEMORIA_ROOT / "logs"

# 私密区路径
PRIVATE_ROOT = MEMORIA_ROOT / "private"
PRIVATE_ARCHIVE_DIR = PRIVATE_ROOT / "memories"
PRIVATE_LINKS_PATH = PRIVATE_ROOT / "links.json"

# =============================================================================
# 热缓存配置
# =============================================================================

# 热缓存最大容量（FIFO 淘汰）
HOT_CACHE_CAPACITY = int(os.environ.get("MEMORIA_HOT_CACHE_LIMIT", 200))

# =============================================================================
# 向量搜索配置（Lite 默认关闭）
# =============================================================================

# 向量库路径（Lite 版本不使用）
CHROMA_DB_PATH = MEMORIA_ROOT / "chroma_db"
PRIVATE_CHROMA_DB_PATH = PRIVATE_ROOT / "chroma_db"

# 向量搜索是否启用（Lite 版本默认为 False）
VECTOR_ENABLED = False

# 向量模型配置（Full 版本使用，Lite 版本忽略）
EMBEDDING_MODEL = "BAAI/bge-m3"
COLLECTION_NAME = "memoria"
EMBEDDING_MAX_CHARS = 512

# 相似度阈值（Full 版本使用）
SIMILARITY_THRESHOLD = 0.85

# =============================================================================
# 版本标识
# =============================================================================

VERSION = "4.0-lite"


def ensure_directories():
    """确保必要目录存在"""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_private_directories():
    """确保私密区目录存在"""
    PRIVATE_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def is_vector_enabled() -> bool:
    """检查向量搜索是否启用"""
    return VECTOR_ENABLED


def get_archive_dir(private_zone: bool = False) -> Path:
    """获取归档目录"""
    return PRIVATE_ARCHIVE_DIR if private_zone else ARCHIVE_DIR


def get_links_path(private_zone: bool = False) -> Path:
    """获取链接索引路径"""
    return PRIVATE_LINKS_PATH if private_zone else LINKS_PATH
