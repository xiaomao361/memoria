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

from memoria.core import (
    store, recall, get_memory, delete_memory, restore_memory, purge_memory,
    update_tags, get_labels, get_stats, export_memories, import_memories,
    create_candidate, list_candidates, promote_candidate, reject_candidate,
    register_agent, get_agent, list_agents, recall_context, recall_for_agent, store_from_agent,
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


def cmd_candidate(args):
    if args.action == "add":
        content = args.content
        if content == "-":
            content = sys.stdin.read()
        if not content:
            print(json.dumps({"error": "content is required for candidate add"}))
            sys.exit(1)
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        result = create_candidate(
            content=content,
            tags=tags,
            source=args.source,
            source_agent=args.source_agent,
            source_run_id=args.source_run_id,
            private=args.private,
            proposed_kind=args.kind or "fact",
            proposed_authority=args.authority or "model_generated",
            proposed_retrieval_role=args.retrieval_role or "background",
            confidence=args.confidence if args.confidence is not None else 0.7,
        )
    elif args.action == "list":
        result = list_candidates(
            status=args.status,
            limit=args.limit,
            offset=args.offset,
            source_agent=args.source_agent,
        )
    elif args.action == "accept":
        if not args.id:
            print(json.dumps({"error": "candidate id is required for accept"}))
            sys.exit(1)
        content = args.content
        if content == "-":
            content = sys.stdin.read()
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
        merge_from = [m.strip() for m in args.merge_from.split(",") if m.strip()] if args.merge_from else None
        result = promote_candidate(
            candidate_id=args.id,
            reviewed_by=args.reviewed_by,
            review_note=args.review_note,
            content=content,
            tags=tags,
            kind=args.kind,
            authority=args.authority,
            retrieval_role=args.retrieval_role,
            confidence=args.confidence,
            status=args.memory_status,
            source=args.source,
            source_agent=args.source_agent,
            source_run_id=args.source_run_id,
            private=args.private,
            merge_from=merge_from,
        )
    elif args.action == "reject":
        if not args.id:
            print(json.dumps({"error": "candidate id is required for reject"}))
            sys.exit(1)
        result = reject_candidate(
            candidate_id=args.id,
            reviewed_by=args.reviewed_by,
            review_note=args.review_note,
            status="discarded" if args.discard else "rejected",
        )
    else:
        print(f"Unknown candidate action: {args.action}")
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_agent(args):
    if args.action == "add":
        if not args.id or not args.name:
            print(json.dumps({"error": "agent id and name are required for add"}))
            sys.exit(1)
        result = register_agent(
            agent_id=args.id,
            name=args.name,
            description=args.description,
            trust_level=args.trust_level,
            can_read_private=args.can_read_private,
            can_write_durable=args.can_write_durable,
        )
    elif args.action == "get":
        if not args.id:
            print(json.dumps({"error": "agent id is required for get"}))
            sys.exit(1)
        result = get_agent(args.id)
        if not result:
            print(json.dumps({"error": "not found"}))
            sys.exit(1)
    elif args.action == "list":
        result = list_agents(limit=args.limit, offset=args.offset)
    else:
        print(f"Unknown agent action: {args.action}")
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_agent_store(args):
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    merge_from = [m.strip() for m in args.merge_from.split(",") if m.strip()] if args.merge_from else None
    content = args.content
    if content == "-":
        content = sys.stdin.read()
    try:
        result = store_from_agent(
            agent_id=args.agent_id,
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
            source_run_id=args.source_run_id,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_agent_recall(args):
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    try:
        result = recall_for_agent(
            agent_id=args.agent_id,
            query=args.query,
            tags=tags,
            memory_id=args.id,
            limit=args.limit,
            offset=args.offset,
            private=args.private,
            include_archived=args.include_archived,
            include_content=args.with_content,
            include_statuses=[s.strip() for s in args.include_statuses.split(",") if s.strip()] if args.include_statuses else None,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_recall_context(args):
    include_kinds = [k.strip() for k in args.include_kinds.split(",") if k.strip()] if args.include_kinds else None
    exclude_statuses = [s.strip() for s in args.exclude_statuses.split(",") if s.strip()] if args.exclude_statuses else None
    try:
        result = recall_context(
            query=args.query,
            agent_id=args.agent_id,
            project=args.project,
            private=args.private,
            include_kinds=include_kinds,
            exclude_statuses=exclude_statuses,
            limit=args.limit,
            include_content=args.with_content,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
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

    # recall-context
    p_recall_context = sub.add_parser("recall-context", help="结构化上下文召回")
    p_recall_context.add_argument("--query", required=True, help="语义查询")
    p_recall_context.add_argument("--agent-id", default=None, help="可选 agent ID，启用 agent policy")
    p_recall_context.add_argument("--project", default=None, help="项目名，用于额外排序")
    p_recall_context.add_argument("--private", action="store_true", help="请求私密上下文")
    p_recall_context.add_argument("--include-kinds", default=None, help="限定 kind，逗号分隔")
    p_recall_context.add_argument("--exclude-statuses", default=None, help="排除 status，逗号分隔")
    p_recall_context.add_argument("--limit", type=int, default=20, help="返回条数")
    p_recall_context.add_argument("--with-content", action="store_true", help="items 中返回全文")
    p_recall_context.set_defaults(func=cmd_recall_context)

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

    # candidate
    p_candidate = sub.add_parser("candidate", help="候选记忆审核流")
    p_candidate.add_argument("action", choices=["add", "list", "accept", "reject"])
    p_candidate.add_argument("id", nargs="?", help="候选 ID")
    p_candidate.add_argument("--content", default=None, help="候选内容（传 - 从 stdin 读取）")
    p_candidate.add_argument("--tags", default=None, help="标签，逗号分隔")
    p_candidate.add_argument("--source", default="agent_candidate", help="来源")
    p_candidate.add_argument("--private", action="store_const", const=True, default=None, help="私密候选 / 提升为私密记忆")
    p_candidate.add_argument("--kind", default=None, help="候选或提升后的记忆类型")
    p_candidate.add_argument("--authority", default=None, help="候选或提升后的权威性")
    p_candidate.add_argument("--retrieval-role", default=None, help="候选或提升后的召回角色")
    p_candidate.add_argument("--confidence", type=float, default=None, help="候选或提升后的置信度")
    p_candidate.add_argument("--source-agent", default=None, help="来源 agent")
    p_candidate.add_argument("--source-run-id", default=None, help="来源运行 ID")
    p_candidate.add_argument("--status", default="pending", help="list 时按状态过滤")
    p_candidate.add_argument("--offset", type=int, default=0, help="list 偏移")
    p_candidate.add_argument("--limit", type=int, default=20, help="list 条数")
    p_candidate.add_argument("--review-note", default=None, help="审核备注")
    p_candidate.add_argument("--reviewed-by", default=None, help="审核人")
    p_candidate.add_argument("--memory-status", default="active", help="accept 后 durable memory 的状态")
    p_candidate.add_argument("--merge-from", default=None, help="accept 时合并来源 ID，逗号分隔")
    p_candidate.add_argument("--discard", action="store_true", help="reject 时标记为 discarded")
    p_candidate.set_defaults(func=cmd_candidate)

    # agent
    p_agent = sub.add_parser("agent", help="agent 注册与查看")
    p_agent.add_argument("action", choices=["add", "get", "list"])
    p_agent.add_argument("id", nargs="?", help="agent ID")
    p_agent.add_argument("--name", default=None, help="agent 名称")
    p_agent.add_argument("--description", default=None, help="agent 描述")
    p_agent.add_argument("--trust-level", default="trusted_writer", help="candidate_only / trusted_writer / read_only / private_allowed")
    p_agent.add_argument("--can-read-private", action="store_true", help="允许访问私密记忆")
    p_agent.add_argument("--can-write-durable", action="store_true", default=None, help="允许直接写 durable memory；默认随 trust-level 决定")
    p_agent.add_argument("--limit", type=int, default=100, help="list 条数")
    p_agent.add_argument("--offset", type=int, default=0, help="list 偏移")
    p_agent.set_defaults(func=cmd_agent)

    # agent-store
    p_agent_store = sub.add_parser("agent-store", help="按 agent trust policy 写入记忆")
    p_agent_store.add_argument("--agent-id", required=True, help="agent ID")
    p_agent_store.add_argument("--content", required=True, help="内容（传 - 从 stdin 读取）")
    p_agent_store.add_argument("--tags", default=None, help="标签，逗号分隔")
    p_agent_store.add_argument("--source", default="agent", help="来源")
    p_agent_store.add_argument("--private", action="store_true", help="私密写入")
    p_agent_store.add_argument("--merge-from", default=None, help="合并来源 ID，逗号分隔")
    p_agent_store.add_argument("--kind", default="fact", help="记忆类型")
    p_agent_store.add_argument("--authority", default=None, help="权威性；trusted_writer durable 默认 confirmed，候选流默认 model_generated")
    p_agent_store.add_argument("--retrieval-role", default="background", help="召回角色")
    p_agent_store.add_argument("--confidence", type=float, default=None, help="置信度 0-1；trusted_writer durable 默认 1.0，候选流默认 0.7")
    p_agent_store.add_argument("--status", default="active", help="durable memory 的生命周期状态")
    p_agent_store.add_argument("--source-run-id", default=None, help="来源运行 ID")
    p_agent_store.set_defaults(func=cmd_agent_store)

    # agent-recall
    p_agent_recall = sub.add_parser("agent-recall", help="按 agent trust policy 召回记忆")
    p_agent_recall.add_argument("--agent-id", required=True, help="agent ID")
    p_agent_recall.add_argument("--query", default=None, help="语义搜索")
    p_agent_recall.add_argument("--tags", default=None, help="标签搜索，逗号分隔")
    p_agent_recall.add_argument("--id", default=None, help="精确查找")
    p_agent_recall.add_argument("--limit", type=int, default=10, help="返回条数")
    p_agent_recall.add_argument("--offset", type=int, default=0, help="偏移")
    p_agent_recall.add_argument("--private", action="store_true", help="请求私密召回")
    p_agent_recall.add_argument("--include-archived", action="store_true", help="包含已归档")
    p_agent_recall.add_argument("--include-statuses", default=None, help="限定生命周期状态，逗号分隔")
    p_agent_recall.add_argument("--with-content", action="store_true", help="返回全文")
    p_agent_recall.set_defaults(func=cmd_agent_recall)

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

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
