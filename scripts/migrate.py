#!/usr/bin/env python3
"""
Memoria Lite ↔ Full 迁移工具

用法:
    python3 migrate.py --to lite      # Full → Lite（降级）
    python3 migrate.py --to full      # Lite → Full（升级）
    python3 migrate.py --to full --force  # 强制重建向量库

功能:
    Lite ↔ Full 数据格式完全兼容，此脚本主要用于：
    - Lite → Full: 重建向量库（chroma_db）
    - Full → Lite: 确认数据完整，更新配置
    - 检查 Archive 完整性
"""

import argparse
import json
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.config import (
    MEMORIA_ROOT,
    ARCHIVE_DIR,
    CHROMA_DB_PATH,
    HOT_CACHE_PATH,
    LINKS_PATH,
    enable_vector,
    disable_vector,
    is_vector_enabled
)
from lib.archive import list_archive_txts, read_archive_txt


def check_archive_integrity() -> dict:
    """检查 Archive 完整性"""
    print("\n检查 Archive 完整性...")
    
    archive_paths = list_archive_txts()
    
    if not archive_paths:
        print("  ⚠️  未发现任何 Archive 文件")
        return {"total": 0, "valid": 0, "invalid": 0}
    
    valid_count = 0
    invalid_count = 0
    errors = []
    
    for path in archive_paths:
        try:
            data = read_archive_txt(path)
            if data and data.get("memory_id"):
                valid_count += 1
            else:
                invalid_count += 1
                errors.append(f"{path}: 缺少 memory_id")
        except Exception as e:
            invalid_count += 1
            errors.append(f"{path}: {e}")
    
    print(f"  总计: {len(archive_paths)} 条")
    print(f"  有效: {valid_count} 条")
    if invalid_count > 0:
        print(f"  无效: {invalid_count} 条")
        for err in errors[:5]:
            print(f"    - {err}")
    
    return {
        "total": len(archive_paths),
        "valid": valid_count,
        "invalid": invalid_count,
        "errors": errors
    }


def migrate_to_lite(force: bool = False):
    """从 Full 降级到 Lite"""
    print("🔄 正在迁移到 Lite 版本...")
    print("=" * 50)
    
    # 检查 Archive 完整性
    integrity = check_archive_integrity()
    
    if integrity["valid"] == 0:
        print("\n❌ Archive 数据不完整，无法迁移")
        return False
    
    # 更新配置：禁用向量
    disable_vector()
    
    # 写入配置文件
    config_path = MEMORIA_ROOT / "config.json"
    config = {
        "version": "4.0-lite",
        "root": str(MEMORIA_ROOT),
        "hot_cache_limit": 200,
        "vector_enabled": False
    }
    
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print("\n✅ 迁移完成！")
    print(f"  - 向量搜索已关闭")
    print(f"  - 配置文件已更新")
    print(f"\n可选操作：删除向量库释放空间")
    print(f"  rm -rf {CHROMA_DB_PATH}")
    
    return True


def migrate_to_full(force: bool = False):
    """从 Lite 升级到 Full"""
    print("🔄 正在迁移到 Full 版本...")
    print("=" * 50)
    
    # 检查 Ollama 是否运行
    print("\n检查 Ollama 状态...")
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("  ✓ Ollama 正在运行")
        else:
            print("  ⚠️  Ollama 返回异常状态")
    except ImportError:
        print("  ⚠️  requests 库未安装，跳过 Ollama 检查")
        print("    请手动确认 Ollama 已启动")
    except Exception:
        print("  ⚠️  Ollama 未运行")
        print("    请先启动 Ollama: ollama serve")
        print("    然后拉取模型: ollama pull BAAI/bge-m3")
    
    # 检查 Archive 完整性
    integrity = check_archive_integrity()
    
    if integrity["valid"] == 0:
        print("\n❌ Archive 数据为空，无法迁移")
        return False
    
    # 检查向量库
    if CHROMA_DB_PATH.exists() and not force:
        print(f"\n⚠️  向量库已存在 ({CHROMA_DB_PATH})")
        print("  使用 --force 强制重建")
        print("  或者删除向量库后重试")
        
        # 更新配置但不重建向量库
        enable_vector()
        config_path = MEMORIA_ROOT / "config.json"
        config = {
            "version": "4.0-full",
            "root": str(MEMORIA_ROOT),
            "hot_cache_limit": 200,
            "vector_enabled": True
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print("\n✅ 配置已更新（未重建向量库）")
        print("  如需重建向量库，使用: python3 migrate.py --to full --force")
        return True
    
    # 重建向量库
    print("\n重建向量库...")
    
    try:
        # 动态导入向量模块
        sys.path.insert(0, str(Path(__file__).parent / "lib"))
        from lib.vector import get_collection, write_vector
        
        collection = get_collection()
        
        archive_paths = list_archive_txts()
        success_count = 0
        fail_count = 0
        
        for i, path in enumerate(archive_paths):
            try:
                data = read_archive_txt(path)
                if not data or not data.get("memory_id"):
                    fail_count += 1
                    continue
                
                write_vector(
                    memory_id=data["memory_id"],
                    archive_path=path,
                    content=data.get("content", ""),
                    tags=data.get("tags", []),
                    links=data.get("links", []),
                    source=data.get("source", "manual"),
                    session_id=data.get("session_id", "")
                )
                success_count += 1
                
                if (i + 1) % 10 == 0:
                    print(f"  进度: {i + 1}/{len(archive_paths)}")
                
            except Exception as e:
                fail_count += 1
                print(f"  失败: {path} - {e}")
        
        # 更新配置
        enable_vector()
        config_path = MEMORIA_ROOT / "config.json"
        config = {
            "version": "4.0-full",
            "root": str(MEMORIA_ROOT),
            "hot_cache_limit": 200,
            "vector_enabled": True
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 迁移完成！")
        print(f"  - 向量库已重建: {success_count} 条成功，{fail_count} 条失败")
        print(f"  - 向量搜索已开启")
        print(f"  - 配置文件已更新")
        
        return fail_count == 0
        
    except ImportError as e:
        print(f"\n❌ 缺少依赖: {e}")
        print("  请安装 Full 版本依赖:")
        print("    pip install chromadb ollama")
        print("  然后重启迁移脚本")
        return False
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Memoria Lite ↔ Full 迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 降级到 Lite
    python3 migrate.py --to lite
    
    # 升级到 Full（首次）
    python3 migrate.py --to full
    
    # 升级到 Full（重建向量库）
    python3 migrate.py --to full --force
    
    # 检查当前状态
    python3 migrate.py --status
"""
    )
    parser.add_argument(
        "--to",
        choices=["lite", "full"],
        help="目标版本: lite 或 full"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制迁移，覆盖已有数据"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="检查当前状态"
    )
    
    args = parser.parse_args()
    
    # 状态检查
    if args.status or not args.to:
        print("Memoria 状态检查")
        print("=" * 50)
        print(f"版本: {'Full' if is_vector_enabled() else 'Lite'}")
        print(f"根目录: {MEMORIA_ROOT}")
        print(f"向量库: {'存在' if CHROMA_DB_PATH.exists() else '不存在'}")
        integrity = check_archive_integrity()
        print(f"Archive: {integrity['valid']} 条有效记录")
        return
    
    # 执行迁移
    if args.to == "lite":
        success = migrate_to_lite(force=args.force)
    else:
        success = migrate_to_full(force=args.force)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
