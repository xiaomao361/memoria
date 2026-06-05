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
    update_tags, get_labels, get_stats, get_graph_data, create_candidate,
    list_candidates, get_candidate, promote_candidate, reject_candidate,
    register_agent, get_agent, list_agents, recall_context, recall_for_agent, store_from_agent,
)

app = FastAPI(title="Memoria", version="6.0")

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


class CandidateRequest(BaseModel):
    content: str
    tags: Optional[list[str]] = None
    source: str = "agent_candidate"
    source_agent: Optional[str] = None
    source_run_id: Optional[str] = None
    private: bool = False
    kind: str = "fact"
    authority: str = "model_generated"
    retrieval_role: str = "background"
    confidence: float = 0.7


class CandidatePromoteRequest(BaseModel):
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    kind: Optional[str] = None
    authority: Optional[str] = None
    retrieval_role: Optional[str] = None
    confidence: Optional[float] = None
    status: str = "active"
    source: Optional[str] = None
    source_agent: Optional[str] = None
    source_run_id: Optional[str] = None
    private: Optional[bool] = None
    merge_from: Optional[list[str]] = None


class CandidateRejectRequest(BaseModel):
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    status: str = "rejected"


class AgentRequest(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    trust_level: str = "trusted_writer"
    can_read_private: bool = False
    can_write_durable: Optional[bool] = None


class AgentStoreRequest(BaseModel):
    agent_id: str
    content: str
    tags: Optional[list[str]] = None
    source: str = "agent"
    private: bool = False
    merge_from: Optional[list[str]] = None
    kind: str = "fact"
    authority: Optional[str] = None
    retrieval_role: str = "background"
    confidence: Optional[float] = None
    status: str = "active"
    source_run_id: Optional[str] = None


class AgentRecallRequest(BaseModel):
    agent_id: str
    query: Optional[str] = None
    tags: Optional[list[str]] = None
    memory_id: Optional[str] = None
    limit: int = 10
    offset: int = 0
    private: bool = False
    include_archived: bool = False
    include_content: bool = False
    include_statuses: Optional[list[str]] = None


class RecallContextRequest(BaseModel):
    query: str
    agent_id: Optional[str] = None
    project: Optional[str] = None
    private: bool = False
    include_kinds: Optional[list[str]] = None
    exclude_statuses: Optional[list[str]] = None
    limit: int = 20
    include_content: bool = False


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


@app.get("/api/candidates")
async def get_candidates(
    status: Optional[str] = "pending",
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    source_agent: Optional[str] = None,
):
    results = list_candidates(
        status=status,
        limit=limit,
        offset=offset,
        source_agent=source_agent,
    )
    return {"candidates": results, "count": len(results)}


@app.get("/api/candidates/{candidate_id}")
async def get_candidate_detail(candidate_id: str):
    result = get_candidate(candidate_id)
    if not result:
        raise HTTPException(status_code=404, detail="not found")
    return result


@app.get("/api/agents")
async def get_agents(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
):
    results = list_agents(limit=limit, offset=offset)
    return {"agents": results, "count": len(results)}


@app.get("/api/agents/{agent_id}")
async def get_agent_detail(agent_id: str):
    result = get_agent(agent_id)
    if not result:
        raise HTTPException(status_code=404, detail="not found")
    return result


@app.post("/api/agents")
async def create_or_update_agent(req: AgentRequest):
    try:
        return register_agent(
            agent_id=req.id,
            name=req.name,
            description=req.description,
            trust_level=req.trust_level,
            can_read_private=req.can_read_private,
            can_write_durable=req.can_write_durable,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent/store")
async def create_memory_from_agent(req: AgentStoreRequest):
    try:
        return store_from_agent(
            agent_id=req.agent_id,
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
            source_run_id=req.source_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent/recall")
async def recall_memory_for_agent(req: AgentRecallRequest):
    try:
        return recall_for_agent(
            agent_id=req.agent_id,
            query=req.query,
            tags=req.tags,
            memory_id=req.memory_id,
            limit=req.limit,
            offset=req.offset,
            private=req.private,
            include_archived=req.include_archived,
            include_content=req.include_content,
            include_statuses=req.include_statuses,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/recall/context")
async def recall_structured_context(req: RecallContextRequest):
    try:
        return recall_context(
            query=req.query,
            agent_id=req.agent_id,
            project=req.project,
            private=req.private,
            include_kinds=req.include_kinds,
            exclude_statuses=req.exclude_statuses,
            limit=req.limit,
            include_content=req.include_content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/candidates")
async def create_candidate_memory(req: CandidateRequest):
    return create_candidate(
        content=req.content,
        tags=req.tags,
        source=req.source,
        source_agent=req.source_agent,
        source_run_id=req.source_run_id,
        private=req.private,
        proposed_kind=req.kind,
        proposed_authority=req.authority,
        proposed_retrieval_role=req.retrieval_role,
        confidence=req.confidence,
    )


@app.post("/api/candidates/{candidate_id}/promote")
async def promote_candidate_memory(candidate_id: str, req: CandidatePromoteRequest):
    try:
        return promote_candidate(
            candidate_id=candidate_id,
            reviewed_by=req.reviewed_by,
            review_note=req.review_note,
            content=req.content,
            tags=req.tags,
            kind=req.kind,
            authority=req.authority,
            retrieval_role=req.retrieval_role,
            confidence=req.confidence,
            status=req.status,
            source=req.source,
            source_agent=req.source_agent,
            source_run_id=req.source_run_id,
            private=req.private,
            merge_from=req.merge_from,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/candidates/{candidate_id}/reject")
async def reject_candidate_memory(candidate_id: str, req: CandidateRejectRequest):
    try:
        return reject_candidate(
            candidate_id=candidate_id,
            reviewed_by=req.reviewed_by,
            review_note=req.review_note,
            status=req.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
