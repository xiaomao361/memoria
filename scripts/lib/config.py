"""
配置模块
"""

from pathlib import Path

# 路径配置 - 日常区
MEMORIA_ROOT = Path.home() / ".qclaw" / "memoria"
ARCHIVE_DIR = MEMORIA_ROOT / "archive"
CHROMA_DB_PATH = MEMORIA_ROOT / "chroma_db"
HOT_CACHE_PATH = MEMORIA_ROOT / "memoria.json"
LINKS_PATH = MEMORIA_ROOT / "links.json"
LOGS_DIR = MEMORIA_ROOT / "logs"

# 路径配置 - 私密区
PRIVATE_ROOT = MEMORIA_ROOT / "private"
PRIVATE_ARCHIVE_DIR = PRIVATE_ROOT / "memories"
PRIVATE_CHROMA_DB_PATH = PRIVATE_ROOT / "chroma_db"
PRIVATE_LINKS_PATH = PRIVATE_ROOT / "links.json"
PRIV_MEMORIA_JSON_PATH = PRIVATE_ROOT / "memoria.json"  # 私密热缓存（架构对齐）

# 热缓存配置
HOT_CACHE_CAPACITY = 200

# 重要度配置
IMPORTANCE_THRESHOLD = 0.3          # 重要度门槛（≥0.3 → 需要加强，与保护标签基础分对齐）
IMPORTANCE_WEIGHT_TAGS = 0.3        # 保护标签权重
IMPORTANCE_WEIGHT_RECALL = 0.2      # 高频召回权重
IMPORTANCE_WEIGHT_RECENT = 0.2      # 近期召回权重
IMPORTANCE_WEIGHT_MANUAL = 0.3     # 手动标记权重
IMPORTANCE_STRENGTHEN_STEP = 0.05  # 每次加强提升量
IMPORTANCE_STRENGTHEN_GAP_DAYS = 7 # 加强间隔天数
IMPORTANCE_RECALL_BONUS = 0.5      # recall 重排序加成系数（×1.5 封顶）

# 保护标签列表
PROTECTION_TAGS = {
    "长期项目", "核心任务", "重要", "项目",
    "keep", "不清理", "Kraken", "bi项目", "doctor项目",
    "长期", "保命", "永久"
}

# 向量库配置
EMBEDDING_MODEL = "BAAI/bge-m3"
COLLECTION_NAME = "memoria"
PRIVATE_COLLECTION_NAME = "memoria_private"
EMBEDDING_MAX_CHARS = 512

# 增量更新配置
SIMILARITY_THRESHOLD = 0.85
