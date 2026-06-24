#!/usr/bin/env python3
"""真实临时目录闭环：两天流水、去重、汇总、记忆回归、MCP 汇总。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="memoria-v612-smoke-"))
os.environ["MEMORIA_ROOT"] = str(TEMP_ROOT)
sys.path.insert(0, str(ROOT))

from memoria.core import purge_memory, recall, store
from memoria.records import add_record, query_records, summarize_records


def mcp_summary() -> dict:
    env = os.environ.copy()
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "server" / "mcp_server.py")],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    next_id = 1

    def request(method, params=None):
        nonlocal next_id
        message = {"jsonrpc": "2.0", "id": next_id, "method": method}
        if params is not None:
            message["params"] = params
        next_id += 1
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(process.stderr.read())
        return json.loads(line)

    try:
        request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "v612-smoke", "version": "1"},
        })
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }) + "\n")
        process.stdin.flush()
        response = request("tools/call", {
            "name": "memoria_record_summary",
            "arguments": {"user_id": "zhouwei", "record_type": "fitness"},
        })
        return json.loads(response["result"]["content"][0]["text"])
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def main():
    try:
        first = add_record(
            user_id="zhouwei",
            record_type="fitness",
            occurred_at="2026-06-20T20:00:00+08:00",
            data={"activity": "步行", "steps": 10000, "duration_minutes": 60},
            dedupe_key="smoke-2026-06-20",
            source="codex",
            source_agent="codex",
        )
        second = add_record(
            user_id="zhouwei",
            record_type="fitness",
            occurred_at="2026-06-21T20:00:00+08:00",
            data={"activity": "步行", "steps": 16000, "duration_minutes": 90},
            dedupe_key="smoke-2026-06-21",
            source="codex",
            source_agent="codex",
        )
        duplicate = add_record(
            user_id="zhouwei",
            record_type="fitness",
            occurred_at="2026-06-21T20:00:00+08:00",
            data={"activity": "步行", "steps": 16000, "duration_minutes": 90},
            dedupe_key="smoke-2026-06-21",
            source="codex",
            source_agent="codex",
        )
        records = query_records("zhouwei", record_type="fitness")
        summary = summarize_records("zhouwei", record_type="fitness")
        assert first["status"] == "created"
        assert second["status"] == "created"
        assert duplicate["status"] == "exists"
        assert len(records) == 2
        assert summary["total_steps"] == 26000
        assert summary["total_duration_minutes"] == 150

        memory = store(
            content="Memoria v6.12 临时闭环回归记录",
            tags=["codex", "v6.12-smoke"],
            source="codex",
            source_agent="codex",
        )
        recalled = recall(memory_id=memory["id"], include_content=True)
        assert recalled and recalled[0]["content"] == "Memoria v6.12 临时闭环回归记录"
        assert purge_memory(memory["id"])

        via_mcp = mcp_summary()
        assert via_mcp["record_count"] == 2
        assert via_mcp["total_steps"] == 26000

        print(json.dumps({
            "status": "ok",
            "record_count": len(records),
            "total_steps": summary["total_steps"],
            "total_duration_minutes": summary["total_duration_minutes"],
            "duplicate_status": duplicate["status"],
            "memory_store_status": memory["status"],
            "mcp_total_steps": via_mcp["total_steps"],
            "temp_root": str(TEMP_ROOT),
        }, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(TEMP_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
