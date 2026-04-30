#!/usr/bin/env python3
"""
Memoria 重复清理工具

检测并删除重复/相似记忆。

用法:
    # 预览重复（推荐先预览）
    python3 cleanup_dupes.py --dry-run
    
    # 列出重复（不删除）
    python3 cleanup_dupes.py --list
    
    # 自动删除 100% 重复
    python3 cleanup_dupes.py --threshold 1.0 --auto-delete
    
    # 删除指定 ID
    python3 cleanup_dupes.py --delete <memory_id>
    
    # 合并两条记忆
    python3 cleanup_dupes.py --merge <id1>,<id2>
"""

import argparse
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.manage_ops import find_duplicates, delete_memory, merge_memories


def cmd_list(args):
    """列出重复"""
    dupes = find_duplicates(threshold=args.threshold, private=args.private)
    
    if not dupes:
        print("✅ 未发现重复")
        return
    
    print(f"发现 {len(dupes)} 组可能重复:\n")
    
    for d in dupes[:args.limit]:
        print(f"相似度: {d['similarity']*100:.0f}%")
        print(f"  {d['id1'][:8]}: {d['summary1']}")
        print(f"  {d['id2'][:8]}: {d['summary2']}")
        
        if d['similarity'] >= 1.0:
            print(f"  💡 100%重复，建议删除其中一个")
        print()


def cmd_auto_delete(args):
    """自动删除高相似度重复"""
    dupes = find_duplicates(threshold=args.threshold, private=args.private)
    
    # 只处理 100% 重复
    exact_dupes = [d for d in dupes if d["similarity"] >= 1.0]
    
    if not exact_dupes:
        print("未发现 100% 重复")
        return
    
    print(f"发现 {len(exact_dupes)} 组 100% 重复\n")
    
    deleted = 0
    for d in exact_dupes:
        # 删除较短的 ID（通常带前缀的是旧格式）
        id_to_delete = d["id2"] if len(d["id2"]) > len(d["id1"]) else d["id1"]
        id_to_keep = d["id1"] if id_to_delete == d["id2"] else d["id2"]
        
        print(f"删除: {id_to_delete[:8]}... (保留: {id_to_keep[:8]}...)")
        
        if not args.dry_run:
            result = delete_memory(id_to_delete, private=args.private)
            if result["success"]:
                deleted += 1
                print(f"  ✅ 已删除")
            else:
                print(f"  ❌ 失败: {result['message']}")
        else:
            print(f"  [预览模式，未实际删除]")
    
    print(f"\n{'预览' if args.dry_run else '实际'}删除: {deleted}/{len(exact_dupes)}")


def cmd_delete(args):
    """删除指定记忆"""
    result = delete_memory(args.id, private=args.private, force=args.force)
    
    if result["success"]:
        print(f"✅ 已删除: {args.id[:8]}...")
        print(f"   从以下位置移除: {', '.join(result['deleted_from'])}")
    else:
        print(f"❌ 删除失败: {result['message']}")


def cmd_merge(args):
    """合并两条记忆"""
    ids = args.ids.split(",")
    if len(ids) != 2:
        print("错误: 需要两个 ID，用逗号分隔")
        return
    
    id1, id2 = ids[0].strip(), ids[1].strip()
    
    # 默认合并内容
    content = args.content or f"合并记忆 {id1[:8]} 和 {id2[:8]}"
    
    result = merge_memories(id1, id2, content, private=args.private)
    
    if result["success"]:
        print(f"✅ {result['message']}")
    else:
        print(f"❌ 合并失败: {result['message']}")


def main():
    parser = argparse.ArgumentParser(description="Memoria 重复清理")
    parser.add_argument("--private", action="store_true", help="操作私密区")
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # list
    list_parser = subparsers.add_parser("list", help="列出重复")
    list_parser.add_argument("--threshold", type=float, default=0.8, help="相似度阈值")
    list_parser.add_argument("--limit", type=int, default=20, help="显示数量")
    list_parser.set_defaults(func=cmd_list)
    
    # auto-delete
    auto_parser = subparsers.add_parser("auto-delete", help="自动删除100%重复")
    auto_parser.add_argument("--threshold", type=float, default=1.0, help="相似度阈值")
    auto_parser.add_argument("--dry-run", action="store_true", help="预览模式")
    auto_parser.set_defaults(func=cmd_auto_delete)
    
    # delete
    delete_parser = subparsers.add_parser("delete", help="删除指定记忆")
    delete_parser.add_argument("--id", required=True, help="记忆ID")
    delete_parser.add_argument("--force", action="store_true", help="强制删除")
    delete_parser.set_defaults(func=cmd_delete)
    
    # merge
    merge_parser = subparsers.add_parser("merge", help="合并两条记忆")
    merge_parser.add_argument("--ids", required=True, help="两个ID，逗号分隔")
    merge_parser.add_argument("--content", help="合并后的内容")
    merge_parser.set_defaults(func=cmd_merge)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
