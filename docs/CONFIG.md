# Memoria Lite 配置说明

> 本文档描述 Lite 版本的配置管理和跨平台路径处理。

---

## 1. 配置层级

Memoria Lite 的配置遵循以下优先级：

```
环境变量 > 用户配置文件 > 默认值
```

### 1.1 配置项说明

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 根目录 | `MEMORIA_ROOT` | `~/.qclaw/memoria` | 记忆系统根目录 |
| 热缓存容量 | `MEMORIA_HOT_CACHE_LIMIT` | `200` | 热缓存最大条数 |
| 配置文件路径 | `MEMORIA_CONFIG` | `~/.qclaw/memoria/config.json` | 配置文件位置 |

### 1.2 配置文件格式

`config.json` 存储在根目录下：

```json
{
    "version": "4.0",
    "root": "~/.qclaw/memoria",
    "hot_cache_limit": 200,
    "archive_path": "archive",
    "links_path": "links.json",
    "hot_cache_path": "memoria.json"
}
```

---

## 2. 路径处理

### 2.1 跨平台路径解析

Memoria Lite 使用 `pathlib` 处理路径，自动适配 Windows / macOS / Linux：

```python
from pathlib import Path
import os

def resolve_memoria_root() -> Path:
    """解析并返回 Memoria 根目录"""
    
    # 1. 优先使用环境变量
    env_root = os.environ.get("MEMORIA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    
    # 2. 使用配置文件
    config_path = Path.home() / ".qclaw" / "memoria" / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            root = config.get("root", "~/.qclaw/memoria")
            return Path(root).expanduser().resolve()
    
    # 3. 使用默认值
    return (Path.home() / ".qclaw" / "memoria").resolve()
```

### 2.2 路径约定

```
~/.qclaw/memoria/           # 根目录
├── config.json              # 配置文件
├── memoria.json             # 热缓存
├── links.json               # 双向链接索引
└── archive/                 # 归档存储
    └── {year-month}/
        └── {memory_id}.txt
```

**各系统展开后的实际路径：**

| 系统 | 路径 |
|------|------|
| Windows | `C:\Users\{user}\.qclaw\memoria\` |
| macOS | `/Users/{user}/.qclaw/memoria/` |
| Linux | `/home/{user}/.qclaw/memoria/` |

### 2.3 文件操作封装

```python
class PathHelper:
    """跨平台路径辅助类"""
    
    def __init__(self, root: Path | None = None):
        self.root = root or resolve_memoria_root()
    
    @property
    def archive_dir(self) -> Path:
        return self.root / "archive"
    
    @property
    def hot_cache_path(self) -> Path:
        return self.root / "memoria.json"
    
    @property
    def links_path(self) -> Path:
        return self.root / "links.json"
    
    @property
    def config_path(self) -> Path:
        return self.root / "config.json"
    
    def get_archive_path(self, memory_id: str, year_month: str = None) -> Path:
        """获取指定 memory_id 的 Archive 路径"""
        if year_month is None:
            now = datetime.now(timezone.utc)
            year_month = f"{now.year}-{now.month:02d}"
        
        return self.archive_dir / year_month / f"{memory_id}.txt"
    
    def list_archive_paths(self) -> list[Path]:
        """列出所有 Archive TXT 路径"""
        if not self.archive_dir.exists():
            return []
        
        paths = []
        for txt_file in self.archive_dir.rglob("*.txt"):
            paths.append(txt_file)
        return sorted(paths)
```

---

## 3. 配置初始化

### 3.1 init 命令

```bash
python -m memoria init
```

执行以下操作：
1. 创建根目录 `~/.qclaw/memoria/`
2. 创建 `archive/` 子目录
3. 生成默认 `config.json`

### 3.2 初始化代码

```python
def init(root: Path | None = None):
    """初始化 Memoria 目录结构"""
    
    root = root or resolve_memoria_root()
    
    # 创建目录
    root.mkdir(parents=True, exist_ok=True)
    (root / "archive").mkdir(exist_ok=True)
    
    # 生成配置文件
    config = {
        "version": "4.0",
        "root": str(root),
        "hot_cache_limit": 200,
        "archive_path": "archive",
        "links_path": "links.json",
        "hot_cache_path": "memoria.json"
    }
    
    config_path = root / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Memoria Lite 初始化完成")
    print(f"   根目录: {root}")
    print(f"   配置文件: {config_path}")
```

---

## 4. 用户自定义配置

### 4.1 修改热缓存容量

```json
{
    "hot_cache_limit": 500
}
```

### 4.2 使用自定义存储路径

```json
{
    "root": "/mnt/data/memoria"
}
```

### 4.3 环境变量覆盖

```bash
# Linux/macOS
export MEMORIA_ROOT="/mnt/data/memoria"
export MEMORIA_HOT_CACHE_LIMIT=500

# Windows (PowerShell)
$env:MEMORIA_ROOT="D:\memoria"
$env:MEMORIA_HOT_CACHE_LIMIT="500"
```

---

## 5. OpenClaw Skill 集成配置

### 5.1 Skill 配置示例

在 Skill 的 `SKILL.md` 中添加：

```markdown
## 环境变量

Memoria Lite 使用以下环境变量（可选）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MEMORIA_ROOT` | `~/.qclaw/memoria` | 根目录 |
| `MEMORIA_HOT_CACHE_LIMIT` | `200` | 热缓存容量 |

## 使用示例

```python
import os
os.environ.setdefault("MEMORIA_ROOT", "~/.qclaw/memoria")

from memoria import store, recall

# 记住重要信息
store(
    content="# 用户偏好\n\n喜欢简洁回答",
    tags=["用户偏好"]
)

# 检索记忆
results = recall(query="用户偏好", mode="tags")
```
```

---

## 6. 故障排查

### 6.1 常见问题

**Q: 提示 "No such file or directory"**
```
A: 运行 `python -m memoria init` 初始化目录结构
```

**Q: 路径包含乱码（Windows 中文系统）**
```
A: 检查 Python 环境变量 PYTHONIOENCODING=utf-8
```

**Q: 配置文件不存在**
```
A: 配置文件不是必需的，系统会使用默认值
   如需自定义，运行 init 或手动创建 config.json
```

### 6.2 调试模式

```bash
# 启用调试输出
export MEMORIA_DEBUG=1
python -m memoria recall --query "用户偏好"
```

---

*本文档为 Memoria Lite v4.0 配置说明。*
