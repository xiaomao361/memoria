#!/usr/bin/env python3
"""
Memoria 标签归一化工具

将所有标签统一转为小写。

用法:
    # 预览（不执行）
    python3 normalize_tags.py --dry-run
    
    # 执行归一化
    python3 normalize_tags.py --execute
    
    # 私密区
    python3 normalize_tags.py --execute --private
"""

import argparse
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.manage_ops import normalize_all_tags


def main():
    parser = argparse.ArgumentParser(description="Memoria 标签归一化")
    parser.add_argument("--private", action="store_true", help="操作私密区")
    parser.add_argument("--execute", action="store_true", help="实际执行（默认仅预览）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    
    args = parser.parse_args()
    
    # --execute 为 False 时就是 dry_run
    dry_run = not args.execute
    
    if dry_run:
        print("🔍 预览模式（加 --execute 执行实际修改）\n")
    else:
        print("⚠️  执行模式\n")
    
    result = normalize_all_tags(private=args.private, dry_run=dry_run)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["success"]:
            print(f"发现 {result['changed']} 条需要修改的记忆")
            
            if result["details"]:
                print("\n变更详情:")
                for detail in result["details"][:20]:
                    print(f"  {detail['id']}: {detail['old']} → {detail['new']}")
                
                if len(result["details"]) > 20:
                    print(f"  ... 还有 {len(result['details']) - 20} 条")
            
            if dry_run and result["changed"] > 0:
                print(f"\n👉 运行 `python3 normalize_tags.py --execute` 执行修改")
        else:
            print(f"❌ 失败: {result.get('message', '未知错误')}")


if __name__ == "__main__":
    import json
    main()
