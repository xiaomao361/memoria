#!/usr/bin/env python3
"""
Memoria CLI - AI Agent 通用记忆系统

用法:
    # 写入
    memoria store --content "内容" --tags "tag1,tag2"
    memoria store --content "内容" --private
    memoria store --content "合并内容" --merge-from "id1,id2"

    # 检索
    memoria recall --query "关键词"
    memoria recall --tags "项目,kraken"
    memoria recall --recent 10
    memoria recall --id "uuid"

    # 管理
    memoria stats
    memoria labels
    memoria delete <id>
    memoria tag <id> --add "new_tag" --remove "old_tag"

    # 维护
    memoria maintain rebuild
    memoria maintain suggest-merge
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memoria.core import store, recall, get_memory, delete_memory, update_tags, get_labels, get_stats


def cmd_store(args):
    content = args.content
    if content == "-":
        content = sys.stdin.read()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    merge_from = [m.strip() for m in args.merge_from.split(",") if m.strip()] if args.merge_from else None

    result = store(
        content=content,
        tags=tags,
        source=args.source,
        private=args.private,
        merge_from=merge_from,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_recall(args):
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None

    results = recall(
        query=args.query,
        tags=tags,
        memory_id=args.id,
        limit=args.limit,
        private=args.private,
        include_archived=args.include_archived,
        include_content=args.with_content,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_stats(args):
    print(json.dumps(get_stats(), ensure_ascii=False, indent=2))


def cmd_labels(args):
    results = get_labels(limit=args.limit, include_private=args.include_private)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_delete(args):
    ok = delete_memory(args.id)
    print(json.dumps({"id": args.id, "deleted": ok}))


def cmd_tag(args):
    add = [t.strip() for t in args.add.split(",") if t.strip()] if args.add else None
    remove = [t.strip() for t in args.remove.split(",") if t.strip()] if args.remove else None
    ok = update_tags(args.id, add=add, remove=remove)
    print(json.dumps({"id": args.id, "updated": ok}))


def cmd_get(args):
    result = get_memory(args.id)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": "not found"}))
        sys.exit(1)


def cmd_maintain(args):
    from memoria.maintain import rebuild, suggest_merge, dormant_sweep

    if args.action == "rebuild":
        result = rebuild()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "suggest-merge":
        results = suggest_merge(limit=args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.action == "dormant":
        result = dormant_sweep(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Unknown action: {args.action}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Memoria - AI Agent 通用记忆系统")
    sub = parser.add_subparsers(dest="command")

    # store
    p_store = sub.add_parser("store", help="写入记忆")
    p_store.add_argument("--content", required=True, help="内容（传 - 从 stdin 读取）")
    p_store.add_argument("--tags", default=None, help="标签，逗号分隔")
    p_store.add_argument("--source", default="manual", help="来源")
    p_store.add_argument("--private", action="store_true", help="私密记忆")
    p_store.add_argument("--merge-from", default=None, help="合并来源 ID，逗号分隔")
    p_store.set_defaults(func=cmd_store)

    # recall
    p_recall = sub.add_parser("recall", help="检索记忆")
    p_recall.add_argument("--query", default=None, help="语义搜索")
    p_recall.add_argument("--tags", default=None, help="标签搜索，逗号分隔")
    p_recall.add_argument("--id", default=None, help="精确查找")
    p_recall.add_argument("--limit", type=int, default=10, help="返回条数")
    p_recall.add_argument("--private", action="store_true", help="搜索私密区")
    p_recall.add_argument("--include-archived", action="store_true", help="包含已归档")
    p_recall.add_argument("--with-content", action="store_true", help="返回全文")
    p_recall.set_defaults(func=cmd_recall)

    # stats
    p_stats = sub.add_parser("stats", help="系统统计")
    p_stats.set_defaults(func=cmd_stats)

    # labels
    p_labels = sub.add_parser("labels", help="查看所有标签")
    p_labels.add_argument("--limit", type=int, default=0)
    p_labels.add_argument("--include-private", action="store_true", help="包含私密标签")
    p_labels.set_defaults(func=cmd_labels)

    # get
    p_get = sub.add_parser("get", help="获取单条记忆详情")
    p_get.add_argument("id", help="记忆 ID")
    p_get.set_defaults(func=cmd_get)

    # delete
    p_del = sub.add_parser("delete", help="删除记忆（软删除）")
    p_del.add_argument("id", help="记忆 ID")
    p_del.set_defaults(func=cmd_delete)

    # tag
    p_tag = sub.add_parser("tag", help="管理标签")
    p_tag.add_argument("id", help="记忆 ID")
    p_tag.add_argument("--add", default=None, help="添加标签，逗号分隔")
    p_tag.add_argument("--remove", default=None, help="移除标签，逗号分隔")
    p_tag.set_defaults(func=cmd_tag)

    # maintain
    p_maint = sub.add_parser("maintain", help="维护任务")
    p_maint.add_argument("action", choices=["rebuild", "suggest-merge", "dormant"])
    p_maint.add_argument("--limit", type=int, default=10)
    p_maint.add_argument("--dry-run", action="store_true")
    p_maint.set_defaults(func=cmd_maintain)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
