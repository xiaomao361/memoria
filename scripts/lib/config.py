"""
Memoria Lite 配置模块
去掉向量相关配置，零外部依赖
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
    
    # 2. 用户配置（~/.qclaw/memoria/config.json）
    config_path = Path.home() / ".qclaw" / "memoria" / "config.json"
    if config_path.exists():
        import json
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            root = config.get("root")
            if root:
                return Path(root).expanduser().resolve()
        except Exception:
            pass
    
    # 3. 默认值
    return (Path.home() / ".qclaw" / "memoria").resolve()


# 根目录
MEMORIA_ROOT = _resolve_memoria_root()

# 子目录和文件
ARCHIVE_DIR = MEMORIA_ROOT / "archive"
HOT_CACHE_PATH = MEMORIA_ROOT / "memoria.json"
LINKS_PATH = MEMORIA_ROOT / "links.json"
LOGS_DIR = MEMORIA_ROOT / "logs"

# =============================================================================
# 热缓存配置
# =============================================================================

# 热缓存最大容量（FIFO 淘汰）
HOT_CACHE_CAPACITY = int(os.environ.get("MEMORIA_HOT_CACHE_LIMIT", 200))

# =============================================================================
# 向量搜索配置（保留但默认关闭，仅用于 Full 版本兼容）
# =============================================================================

# 向量库路径（Lite 版本不使用，但 Full 版本需要）
CHROMA_DB_PATH = MEMORIA_ROOT / "chroma_db"

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


def enable_vector():
    """启用向量搜索（切换到 Full 模式）"""
    global VECTOR_ENABLED
    VECTOR_ENABLED = True


def disable_vector():
    """禁用向量搜索（切换到 Lite 模式）"""
    global VECTOR_ENABLED
    VECTOR_ENABLED = False


def is_vector_enabled() -> bool:
    """检查向量搜索是否启用"""
    return VECTOR_ENABLED
