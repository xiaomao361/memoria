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
    memoria recall --limit 20
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

from memoria.core import (
    store, recall, get_memory, delete_memory, restore_memory, purge_memory,
    update_memory, update_tags, get_labels, get_stats, export_memories, import_memories,
)
from memoria.records import (
    RecordValidationError, add_record, query_records, summarize_records,
)


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
        kind=args.kind,
        authority=args.authority,
        retrieval_role=args.retrieval_role,
        confidence=args.confidence,
        status=args.status,
        source_agent=args.source_agent,
        source_run_id=args.source_run_id,
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
        include_statuses=[s.strip() for s in args.include_statuses.split(",") if s.strip()] if args.include_statuses else None,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_stats(args):
    print(json.dumps(get_stats(), ensure_ascii=False, indent=2))


def cmd_labels(args):
    if args.audit:
        from memoria.maintain import audit_labels

        results = audit_labels(limit=args.limit, include_private=args.include_private)
    else:
        results = get_labels(limit=args.limit, include_private=args.include_private)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_delete(args):
    if args.purge:
        ok = purge_memory(args.id)
        print(json.dumps({"id": args.id, "purged": ok}))
    else:
        ok = delete_memory(args.id)
        print(json.dumps({"id": args.id, "deleted": ok}))


def cmd_restore(args):
    ok = restore_memory(args.id)
    print(json.dumps({"id": args.id, "restored": ok}))


def cmd_tag(args):
    add = [t.strip() for t in args.add.split(",") if t.strip()] if args.add else None
    remove = [t.strip() for t in args.remove.split(",") if t.strip()] if args.remove else None
    ok = update_tags(args.id, add=add, remove=remove)
    print(json.dumps({"id": args.id, "updated": ok}))


def cmd_update(args):
    content = args.content
    if content == "-":
        content = sys.stdin.read()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    private = None
    if args.private:
        private = True
    elif args.public:
        private = False
    result = update_memory(memory_id=args.id, content=content, tags=tags, private=private)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_get(args):
    result = get_memory(args.id)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": "not found"}))
        sys.exit(1)


def cmd_maintain(args):
    from memoria.maintain import (
        rebuild, suggest_merge, dormant_sweep, recompute_importance,
        suggest_conflicts, nightly, classify_metadata, canonicalize_labels,
        repair_summaries, audit_quality, backfill_source_agent,
    )

    if args.action == "rebuild":
        result = rebuild()
    elif args.action == "suggest-merge":
        result = suggest_merge(limit=args.limit)
    elif args.action == "dormant":
        result = dormant_sweep(dry_run=args.dry_run)
    elif args.action == "recompute-importance":
        result = recompute_importance(dry_run=args.dry_run, half_life_days=args.half_life)
    elif args.action == "suggest-conflicts":
        result = suggest_conflicts(limit=args.limit)
    elif args.action == "nightly":
        result = nightly(dry_run=args.dry_run)
    elif args.action == "classify-metadata":
        private = None
        if args.private_only:
            private = True
        elif args.public_only:
            private = False
        result = classify_metadata(
            dry_run=args.dry_run,
            force=args.force,
            limit=args.limit,
            private=private,
        )
    elif args.action == "canonicalize-labels":
        result = canonicalize_labels(
            dry_run=args.dry_run,
            include_private=not args.public_only,
        )
    elif args.action == "repair-summaries":
        private = None
        if args.private_only:
            private = True
        elif args.public_only:
            private = False
        result = repair_summaries(
            dry_run=args.dry_run,
            limit=args.limit,
            private=private,
        )
    elif args.action == "audit-quality":
        result = audit_quality(
            limit=args.limit,
            include_private=args.include_private or args.private_only,
            include_review_candidates=not args.skip_review_candidates,
        )
    elif args.action == "backfill-source-agent":
        result = backfill_source_agent(
            dry_run=args.dry_run,
            limit=args.limit,
            include_private=args.include_private or args.private_only,
        )
    else:
        print(f"Unknown action: {args.action}")
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_export(args):
    data = export_memories(private=args.private, include_archived=args.include_archived)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(json.dumps({"exported": len(data), "file": args.output}))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_import(args):
    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = import_memories(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _parse_record_data(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecordValidationError(f"data must be valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise RecordValidationError("data must be a JSON object")
    return data


def cmd_record(args):
    if args.record_action == "add":
        result = add_record(
            user_id=args.user_id,
            record_type=args.type,
            occurred_at=args.occurred_at,
            timezone_name=args.timezone,
            data=_parse_record_data(args.data),
            schema_version=args.schema_version,
            note=args.note,
            source=args.source,
            source_agent=args.source_agent,
            source_run_id=args.source_run_id,
            dedupe_key=args.dedupe_key,
        )
    elif args.record_action == "query":
        result = query_records(
            user_id=args.user_id,
            record_type=args.type,
            start=args.start,
            end=args.end,
            local_date=args.local_date,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.record_action == "summary":
        result = summarize_records(
            user_id=args.user_id,
            record_type=args.type,
            start=args.start,
            end=args.end,
            local_date=args.local_date,
        )
    else:
        raise RecordValidationError("record action is required")
    print(json.dumps(result, ensure_ascii=False, indent=2))


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
    p_store.add_argument("--kind", default="fact", help="记忆类型")
    p_store.add_argument("--authority", default="confirmed", help="权威性")
    p_store.add_argument("--retrieval-role", default="background", help="召回角色")
    p_store.add_argument("--confidence", type=float, default=1.0, help="置信度 0-1")
    p_store.add_argument("--status", default="active", help="生命周期状态")
    p_store.add_argument("--source-agent", default=None, help="写入 agent")
    p_store.add_argument("--source-run-id", default=None, help="来源运行 ID")
    p_store.set_defaults(func=cmd_store)

    # recall
    p_recall = sub.add_parser("recall", help="检索记忆")
    p_recall.add_argument("--query", default=None, help="语义搜索")
    p_recall.add_argument("--tags", default=None, help="标签搜索，逗号分隔")
    p_recall.add_argument("--id", default=None, help="精确查找")
    p_recall.add_argument("--limit", type=int, default=10, help="返回条数")
    p_recall.add_argument("--private", action="store_true", help="搜索私密区")
    p_recall.add_argument("--include-archived", action="store_true", help="包含已归档")
    p_recall.add_argument("--include-statuses", default=None, help="限定生命周期状态，逗号分隔")
    p_recall.add_argument("--with-content", action="store_true", help="返回全文")
    p_recall.set_defaults(func=cmd_recall)

    # stats
    p_stats = sub.add_parser("stats", help="系统统计")
    p_stats.set_defaults(func=cmd_stats)

    # labels
    p_labels = sub.add_parser("labels", help="查看所有标签")
    p_labels.add_argument("--limit", type=int, default=0)
    p_labels.add_argument("--include-private", action="store_true", help="包含私密标签")
    p_labels.add_argument("--audit", action="store_true", help="输出标签别名/同义标签审计建议")
    p_labels.set_defaults(func=cmd_labels)

    # get
    p_get = sub.add_parser("get", help="获取单条记忆详情")
    p_get.add_argument("id", help="记忆 ID")
    p_get.set_defaults(func=cmd_get)

    # delete
    p_del = sub.add_parser("delete", help="删除记忆（软删除）")
    p_del.add_argument("id", help="记忆 ID")
    p_del.add_argument("--purge", action="store_true", help="永久删除（不可恢复）")
    p_del.set_defaults(func=cmd_delete)

    # restore
    p_restore = sub.add_parser("restore", help="恢复已归档记忆")
    p_restore.add_argument("id", help="记忆 ID")
    p_restore.set_defaults(func=cmd_restore)

    # tag
    p_tag = sub.add_parser("tag", help="管理标签")
    p_tag.add_argument("id", help="记忆 ID")
    p_tag.add_argument("--add", default=None, help="添加标签，逗号分隔")
    p_tag.add_argument("--remove", default=None, help="移除标签，逗号分隔")
    p_tag.set_defaults(func=cmd_tag)

    # update
    p_update = sub.add_parser("update", help="编辑记忆内容、标签与私密标记")
    p_update.add_argument("id", help="记忆 ID")
    p_update.add_argument("--content", required=True, help="新内容（传 - 从 stdin 读取）")
    p_update.add_argument("--tags", default=None, help="新标签，逗号分隔（覆盖）")
    priv_group = p_update.add_mutually_exclusive_group()
    priv_group.add_argument("--private", action="store_true", help="标记为私密")
    priv_group.add_argument("--public", action="store_true", help="标记为公开")
    p_update.set_defaults(func=cmd_update)

    # maintain
    p_maint = sub.add_parser("maintain", help="维护任务")
    p_maint.add_argument("action", choices=[
        "rebuild", "suggest-merge", "dormant",
        "recompute-importance", "suggest-conflicts", "nightly", "classify-metadata",
        "canonicalize-labels", "repair-summaries", "audit-quality", "backfill-source-agent",
    ])
    p_maint.add_argument("--limit", type=int, default=10)
    p_maint.add_argument("--dry-run", action="store_true")
    p_maint.add_argument("--half-life", type=int, default=30, help="importance 衰减半衰期（天）")
    p_maint.add_argument("--force", action="store_true", help="重判所有记忆，不只默认元数据")
    p_maint.add_argument("--private-only", action="store_true", help="仅处理私密记忆")
    p_maint.add_argument("--public-only", action="store_true", help="仅处理公开记忆")
    p_maint.add_argument("--include-private", action="store_true", help="质量审计时包含私密记忆")
    p_maint.add_argument("--skip-review-candidates", action="store_true", help="跳过 merge/conflict 候选扫描，加快质量审计")
    p_maint.set_defaults(func=cmd_maintain)

    # export
    p_export = sub.add_parser("export", help="导出记忆为 JSON")
    p_export.add_argument("-o", "--output", default=None, help="输出文件路径（默认 stdout）")
    p_export.add_argument("--private", action="store_true", help="导出私密记忆")
    p_export.add_argument("--include-archived", action="store_true", help="包含已归档")
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = sub.add_parser("import", help="从 JSON 导入记忆")
    p_import.add_argument("file", help="JSON 文件路径")
    p_import.set_defaults(func=cmd_import)

    # record
    p_record = sub.add_parser("record", help="新增和查询高频时序流水")
    record_sub = p_record.add_subparsers(dest="record_action")

    p_record_add = record_sub.add_parser("add", help="新增一条流水")
    p_record_add.add_argument("--user-id", required=True)
    p_record_add.add_argument("--type", required=True)
    p_record_add.add_argument("--occurred-at", required=True, help="带时区的 ISO 8601 时间")
    p_record_add.add_argument("--timezone", default="Asia/Shanghai")
    p_record_add.add_argument("--data", required=True, help="JSON 对象")
    p_record_add.add_argument("--schema-version", type=int, default=1)
    p_record_add.add_argument("--note", default=None)
    p_record_add.add_argument("--source", default="manual")
    p_record_add.add_argument("--source-agent", default=None)
    p_record_add.add_argument("--source-run-id", default=None)
    p_record_add.add_argument("--dedupe-key", default=None)
    p_record_add.set_defaults(func=cmd_record)

    p_record_query = record_sub.add_parser("query", help="按用户、类型和时间查询流水")
    p_record_query.add_argument("--user-id", required=True)
    p_record_query.add_argument("--type", default=None)
    p_record_query.add_argument("--from", dest="start", default=None)
    p_record_query.add_argument("--to", dest="end", default=None)
    p_record_query.add_argument("--local-date", default=None)
    p_record_query.add_argument("--limit", type=int, default=100)
    p_record_query.add_argument("--offset", type=int, default=0)
    p_record_query.set_defaults(func=cmd_record)

    p_record_summary = record_sub.add_parser("summary", help="汇总锻炼流水")
    p_record_summary.add_argument("--user-id", required=True)
    p_record_summary.add_argument("--type", default="fitness")
    p_record_summary.add_argument("--from", dest="start", default=None)
    p_record_summary.add_argument("--to", dest="end", default=None)
    p_record_summary.add_argument("--local-date", default=None)
    p_record_summary.set_defaults(func=cmd_record)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except RecordValidationError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
