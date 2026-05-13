"""Memoria Web API - FastAPI"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from memoria.core import store, recall, get_memory, delete_memory, update_tags, get_labels, get_stats

app = FastAPI(title="Memoria", version="6.0")

STATIC_DIR = Path(__file__).parent / "static"


class StoreRequest(BaseModel):
    content: str
    tags: Optional[list[str]] = None
    source: str = "manual"
    private: bool = False
    merge_from: Optional[list[str]] = None


class TagUpdateRequest(BaseModel):
    add: Optional[list[str]] = None
    remove: Optional[list[str]] = None


class MergeRequest(BaseModel):
    ids: list[str]
    merged_content: str
    tags: Optional[list[str]] = None


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = STATIC_DIR / "index.html"
    return html_file.read_text(encoding="utf-8")


@app.get("/api/memories")
async def list_memories(
    query: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    private: bool = False,
    include_archived: bool = False,
    include_content: bool = False,
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = recall(
        query=query,
        tags=tag_list,
        limit=limit,
        private=private,
        include_archived=include_archived,
        include_content=include_content,
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
    )
    return result


@app.delete("/api/memories/{memory_id}")
async def remove_memory(memory_id: str):
    ok = delete_memory(memory_id)
    return {"id": memory_id, "deleted": ok}


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
    """动态生成关系图数据"""
    from memoria.db import get_conn, init_db
    init_db()

    nodes = []
    edges = []
    label_nodes = {}

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT m.id, m.summary, m.importance, l.name, l.type
               FROM memories m
               JOIN labels l ON m.id = l.memory_id
               WHERE m.archived = 0 AND m.private = ?""",
            (int(private),),
        ).fetchall()

    memory_set = set()
    for row in rows:
        mid = row["id"]
        if mid not in memory_set:
            memory_set.add(mid)
            nodes.append({
                "id": mid,
                "label": row["summary"][:30],
                "type": "memory",
                "importance": row["importance"],
            })

        label_name = row["name"]
        if label_name not in label_nodes:
            label_nodes[label_name] = {
                "id": f"label:{label_name}",
                "label": label_name,
                "type": row["type"],
            }

        edges.append({"source": mid, "target": f"label:{label_name}"})

    nodes.extend(label_nodes.values())
    return {"nodes": nodes, "edges": edges}


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
