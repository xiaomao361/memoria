"""Memoria Web API - FastAPI"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from memoria.core import (
    store, recall, get_memory, delete_memory, restore_memory, purge_memory,
    update_tags, get_labels, get_stats, get_graph_data,
)
from memoria.records import (
    RecordValidationError, add_record, query_records, summarize_records,
)

app = FastAPI(title="Memoria", version="6.11.0")

STATIC_DIR = Path(__file__).parent / "static"


class StoreRequest(BaseModel):
    content: str
    tags: Optional[list[str]] = None
    source: str = "manual"
    private: bool = False
    merge_from: Optional[list[str]] = None
    kind: str = "fact"
    authority: str = "confirmed"
    retrieval_role: str = "background"
    confidence: float = 1.0
    status: str = "active"
    source_agent: Optional[str] = None
    source_run_id: Optional[str] = None


class TagUpdateRequest(BaseModel):
    add: Optional[list[str]] = None
    remove: Optional[list[str]] = None


class MergeRequest(BaseModel):
    ids: list[str]
    merged_content: str
    tags: Optional[list[str]] = None


class RecordRequest(BaseModel):
    user_id: str
    record_type: str
    occurred_at: str
    data: dict
    timezone: str = "Asia/Shanghai"
    schema_version: int = 1
    note: Optional[str] = None
    source: str = "manual"
    source_agent: Optional[str] = None
    source_run_id: Optional[str] = None
    dedupe_key: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = STATIC_DIR / "index.html"
    return html_file.read_text(encoding="utf-8")


@app.get("/api/memories")
async def list_memories(
    query: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    private: bool = False,
    include_archived: bool = False,
    include_content: bool = False,
    include_statuses: Optional[str] = None,
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    status_list = [s.strip() for s in include_statuses.split(",") if s.strip()] if include_statuses else None
    results = recall(
        query=query,
        tags=tag_list,
        limit=limit,
        offset=offset,
        private=private,
        include_archived=include_archived,
        include_content=include_content,
        include_statuses=status_list,
    )
    return {"memories": results, "count": len(results)}


@app.get("/api/memories/{memory_id}")
async def get_memory_detail(memory_id: str):
    result = get_memory(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="not found")
    return result


@app.post("/api/memories")
async def create_memory(req: StoreRequest):
    result = store(
        content=req.content,
        tags=req.tags,
        source=req.source,
        private=req.private,
        merge_from=req.merge_from,
        kind=req.kind,
        authority=req.authority,
        retrieval_role=req.retrieval_role,
        confidence=req.confidence,
        status=req.status,
        source_agent=req.source_agent,
        source_run_id=req.source_run_id,
    )
    return result


@app.delete("/api/memories/{memory_id}")
async def remove_memory(memory_id: str, purge: bool = False):
    if purge:
        ok = purge_memory(memory_id)
        return {"id": memory_id, "purged": ok}
    ok = delete_memory(memory_id)
    return {"id": memory_id, "deleted": ok}


@app.post("/api/memories/{memory_id}/restore")
async def restore(memory_id: str):
    ok = restore_memory(memory_id)
    return {"id": memory_id, "restored": ok}


@app.put("/api/memories/{memory_id}/tags")
async def modify_tags(memory_id: str, req: TagUpdateRequest):
    ok = update_tags(memory_id, add=req.add, remove=req.remove)
    return {"id": memory_id, "updated": ok}


@app.post("/api/memories/merge")
async def merge_memories(req: MergeRequest):
    result = store(
        content=req.merged_content,
        tags=req.tags,
        source="merge",
        merge_from=req.ids,
    )
    return result


@app.get("/api/labels")
async def list_labels(limit: int = 0, include_private: bool = False):
    return {"labels": get_labels(limit=limit, include_private=include_private)}


@app.get("/api/search")
async def search(q: str, limit: int = 10, private: bool = False):
    results = recall(query=q, limit=limit, private=private, include_content=True)
    return {"results": results, "count": len(results)}


@app.get("/api/stats")
async def stats():
    return get_stats()


@app.get("/api/graph")
async def graph_data(private: bool = False):
    return get_graph_data(private=private)


@app.post("/api/records")
async def create_record(req: RecordRequest):
    try:
        return add_record(
            user_id=req.user_id,
            record_type=req.record_type,
            occurred_at=req.occurred_at,
            data=req.data,
            timezone_name=req.timezone,
            schema_version=req.schema_version,
            note=req.note,
            source=req.source,
            source_agent=req.source_agent,
            source_run_id=req.source_run_id,
            dedupe_key=req.dedupe_key,
        )
    except RecordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/records")
async def list_records(
    user_id: str,
    record_type: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    local_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    try:
        records = query_records(
            user_id=user_id,
            record_type=record_type,
            start=start,
            end=end,
            local_date=local_date,
            limit=limit,
            offset=offset,
        )
        return {"records": records, "count": len(records)}
    except RecordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/records/summary")
async def record_summary(
    user_id: str,
    record_type: str = "fitness",
    start: Optional[str] = None,
    end: Optional[str] = None,
    local_date: Optional[str] = None,
):
    try:
        return summarize_records(
            user_id=user_id,
            record_type=record_type,
            start=start,
            end=end,
            local_date=local_date,
        )
    except RecordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def main():
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
