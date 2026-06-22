#!/usr/bin/env python3
"""Memoria MCP Server — 常驻进程，stdio transport

用于 Claude Code 等 MCP 客户端挂载。
每个 MCP tool 直接映射到 memoria.core 的对应函数。

使用方式:
    python3 server/mcp.py
    # Claude Code settings.json:
    # { "mcpServers": { "memoria": {
    #     "command": "python3",
    #     "args": ["/path/to/server/mcp.py"]
    # }}}
"""

import asyncio
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent
sys.path = [
    path for path in sys.path
    if path and Path(path).resolve() != SERVER_DIR
]
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from memoria.core import (
    store,
    recall,
    get_memory,
    delete_memory,
    restore_memory,
    purge_memory,
    update_tags,
    get_labels,
    get_stats,
)
from memoria.records import add_record, query_records, summarize_records

server = Server("memoria", version="6.11.0")


def _split_tags(raw: str) -> list[str]:
    """逗号分隔转标签列表"""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


_TOOLS = [
    Tool(
        name="memoria_store",
        description="写入一条记忆。tags 逗号分隔，如 '运维,JVM'",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "记忆内容"},
                "tags": {"type": "string", "description": "标签，逗号分隔"},
                "source": {"type": "string", "default": "manual"},
                "private": {"type": "boolean", "default": False},
                "kind": {"type": "string", "default": "fact"},
                "authority": {"type": "string", "default": "confirmed"},
                "source_agent": {"type": "string", "default": ""},
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="memoria_recall",
        description="检索记忆。传 query 语义搜索，传 tags 标签搜索，都不传返回最近记忆",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "tags": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 10},
                "private": {"type": "boolean", "default": False},
                "include_content": {"type": "boolean", "default": False},
                "include_archived": {"type": "boolean", "default": False},
            },
        },
    ),
    Tool(
        name="memoria_get",
        description="获取单条记忆详情（含全文+标签）",
        inputSchema={
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    ),
    Tool(
        name="memoria_delete",
        description="删除记忆（默认软删除 archived）。purge=true 永久删除",
        inputSchema={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "purge": {"type": "boolean", "default": False},
            },
            "required": ["memory_id"],
        },
    ),
    Tool(
        name="memoria_restore",
        description="恢复已归档的记忆",
        inputSchema={
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    ),
    Tool(
        name="memoria_tag",
        description="管理标签。add/remove 逗号分隔，如 add='kraken,运维' remove='旧标签'",
        inputSchema={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "add": {"type": "string", "default": ""},
                "remove": {"type": "string", "default": ""},
            },
            "required": ["memory_id"],
        },
    ),
    Tool(
        name="memoria_stats",
        description="系统统计：总数、活跃数、归档数、标签数等",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="memoria_labels",
        description="列出所有标签及其关联记忆数",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 0},
                "include_private": {"type": "boolean", "default": False},
            },
        },
    ),
    Tool(
        name="memoria_record_add",
        description="新增一条高频时序流水，不写入长期记忆。user_id 必填，data 必须是对象，occurred_at 必须带时区。",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "record_type": {"type": "string", "default": "fitness"},
                "occurred_at": {"type": "string", "description": "带时区的 ISO 8601 时间"},
                "timezone": {"type": "string", "default": "Asia/Shanghai"},
                "data": {"type": "object"},
                "schema_version": {"type": "integer", "default": 1},
                "note": {"type": "string", "default": ""},
                "source": {"type": "string", "default": "manual"},
                "source_agent": {"type": "string", "default": ""},
                "source_run_id": {"type": "string", "default": ""},
                "dedupe_key": {"type": "string", "default": ""},
            },
            "required": ["user_id", "record_type", "occurred_at", "data"],
        },
    ),
    Tool(
        name="memoria_record_query",
        description="按用户、类型和时间查询高频流水。流水不是长期记忆，user_id 必填。",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "record_type": {"type": "string", "default": ""},
                "start": {"type": "string", "default": ""},
                "end": {"type": "string", "default": ""},
                "local_date": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 100},
                "offset": {"type": "integer", "default": 0},
            },
            "required": ["user_id"],
        },
    ),
    Tool(
        name="memoria_record_summary",
        description="汇总某个用户的锻炼流水。时间参数必须带时区，user_id 必填。",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "record_type": {"type": "string", "default": "fitness"},
                "start": {"type": "string", "default": ""},
                "end": {"type": "string", "default": ""},
                "local_date": {"type": "string", "default": ""},
            },
            "required": ["user_id"],
        },
    ),
]

_TOOL_MAP = {t.name: t for t in _TOOLS}


@server.list_tools()
async def handle_list_tools():
    return _TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    try:
        if name == "memoria_store":
            result = store(
                content=arguments["content"],
                tags=_split_tags(arguments.get("tags", "")),
                source=arguments.get("source", "manual"),
                private=arguments.get("private", False),
                kind=arguments.get("kind", "fact"),
                authority=arguments.get("authority", "confirmed"),
                source_agent=arguments.get("source_agent") or None,
            )
        elif name == "memoria_recall":
            tags = arguments.get("tags", "")
            tag_list = _split_tags(tags) if tags else None
            result = recall(
                query=arguments.get("query") or None,
                tags=tag_list,
                limit=arguments.get("limit", 10),
                private=arguments.get("private", False),
                include_content=arguments.get("include_content", False),
                include_archived=arguments.get("include_archived", False),
            )
        elif name == "memoria_get":
            result = get_memory(arguments["memory_id"])
            if not result:
                return [TextContent(type="text", text=json.dumps({"error": "not found", "id": arguments["memory_id"]}, ensure_ascii=False))]
        elif name == "memoria_delete":
            memory_id = arguments["memory_id"]
            if arguments.get("purge", False):
                ok = purge_memory(memory_id)
                result = {"id": memory_id, "purged": ok}
            else:
                ok = delete_memory(memory_id)
                result = {"id": memory_id, "deleted": ok}
        elif name == "memoria_restore":
            ok = restore_memory(arguments["memory_id"])
            result = {"id": arguments["memory_id"], "restored": ok}
        elif name == "memoria_tag":
            add_list = _split_tags(arguments.get("add", "")) if arguments.get("add") else None
            remove_list = _split_tags(arguments.get("remove", "")) if arguments.get("remove") else None
            ok = update_tags(arguments["memory_id"], add=add_list, remove=remove_list)
            result = {"id": arguments["memory_id"], "updated": ok}
        elif name == "memoria_stats":
            result = get_stats()
        elif name == "memoria_labels":
            result = get_labels(
                limit=arguments.get("limit", 0),
                include_private=arguments.get("include_private", False),
            )
        elif name == "memoria_record_add":
            result = add_record(
                user_id=arguments["user_id"],
                record_type=arguments.get("record_type", "fitness"),
                occurred_at=arguments["occurred_at"],
                timezone_name=arguments.get("timezone", "Asia/Shanghai"),
                data=arguments["data"],
                schema_version=arguments.get("schema_version", 1),
                note=arguments.get("note") or None,
                source=arguments.get("source", "manual"),
                source_agent=arguments.get("source_agent") or None,
                source_run_id=arguments.get("source_run_id") or None,
                dedupe_key=arguments.get("dedupe_key") or None,
            )
        elif name == "memoria_record_query":
            result = query_records(
                user_id=arguments["user_id"],
                record_type=arguments.get("record_type") or None,
                start=arguments.get("start") or None,
                end=arguments.get("end") or None,
                local_date=arguments.get("local_date") or None,
                limit=arguments.get("limit", 100),
                offset=arguments.get("offset", 0),
            )
        elif name == "memoria_record_summary":
            result = summarize_records(
                user_id=arguments["user_id"],
                record_type=arguments.get("record_type", "fitness"),
                start=arguments.get("start") or None,
                end=arguments.get("end") or None,
                local_date=arguments.get("local_date") or None,
            )
        else:
            return [TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False))]

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
