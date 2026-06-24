import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="memoria-interface-tests-"))
        self.env = os.environ.copy()
        self.env["MEMORIA_ROOT"] = str(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_cli(self, *args, expected=0):
        result = subprocess.run(
            [sys.executable, str(ROOT / "cli.py"), *args],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(expected, result.returncode, result.stderr)
        stream = result.stdout if expected == 0 else result.stderr
        return json.loads(stream)

    def test_cli_add_query_summary_and_invalid_json(self):
        created = self.run_cli(
            "record", "add",
            "--user-id", "zhouwei",
            "--type", "fitness",
            "--occurred-at", "2026-06-21T20:00:00+08:00",
            "--data", '{"steps":16000,"duration_minutes":90}',
            "--dedupe-key", "cli-day-1",
        )
        self.assertEqual("created", created["status"])
        duplicate = self.run_cli(
            "record", "add",
            "--user-id", "zhouwei",
            "--type", "fitness",
            "--occurred-at", "2026-06-21T20:00:00+08:00",
            "--data", '{"steps":16000,"duration_minutes":90}',
            "--dedupe-key", "cli-day-1",
        )
        self.assertEqual("exists", duplicate["status"])
        queried = self.run_cli("record", "query", "--user-id", "zhouwei", "--type", "fitness")
        self.assertEqual(1, len(queried))
        summary = self.run_cli("record", "summary", "--user-id", "zhouwei")
        self.assertEqual(16000, summary["total_steps"])
        error = self.run_cli(
            "record", "add",
            "--user-id", "zhouwei",
            "--type", "fitness",
            "--occurred-at", "2026-06-21T20:00:00+08:00",
            "--data", "not-json",
            expected=2,
        )
        self.assertIn("valid JSON", error["error"])

    def test_http_add_query_summary_and_validation(self):
        script = r'''
import json
from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)
payload = {
    "user_id": "zhouwei",
    "record_type": "fitness",
    "occurred_at": "2026-06-21T20:00:00+08:00",
    "data": {"steps": 8000, "duration_minutes": 40},
    "dedupe_key": "http-day-1"
}
created = client.post("/api/records", json=payload)
duplicate = client.post("/api/records", json=payload)
queried = client.get("/api/records", params={"user_id": "zhouwei", "record_type": "fitness"})
summary = client.get("/api/records/summary", params={"user_id": "zhouwei"})
invalid = client.post("/api/records", json={**payload, "occurred_at": "2026-06-21T20:00:00"})
print(json.dumps({
    "created_code": created.status_code,
    "created": created.json(),
    "duplicate": duplicate.json(),
    "query_code": queried.status_code,
    "query": queried.json(),
    "summary_code": summary.status_code,
    "summary": summary.json(),
    "invalid_code": invalid.status_code,
}, ensure_ascii=False))
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(200, data["created_code"])
        self.assertEqual("created", data["created"]["status"])
        self.assertEqual("exists", data["duplicate"]["status"])
        self.assertEqual(1, data["query"]["count"])
        self.assertEqual(8000, data["summary"]["total_steps"])
        self.assertEqual(422, data["invalid_code"])


class RawMcpClient:
    def __init__(self, env):
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "server" / "mcp_server.py")],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.next_id = 1

    def request(self, method, params=None):
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.next_id += 1
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError(self.proc.stderr.read())
        return json.loads(line)

    def notify(self, method):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()


class McpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="memoria-mcp-tests-"))
        self.env = os.environ.copy()
        self.env["MEMORIA_ROOT"] = str(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def tool_data(response):
        text = response["result"]["content"][0]["text"]
        return json.loads(text)

    def test_mcp_real_stdio_flow(self):
        client = RawMcpClient(self.env)
        try:
            initialized = client.request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            })
            self.assertEqual("memoria", initialized["result"]["serverInfo"]["name"])
            client.notify("notifications/initialized")
            listed = client.request("tools/list")
            names = {tool["name"] for tool in listed["result"]["tools"]}
            self.assertEqual(12, len(names))
            self.assertTrue({
                "memoria_update",
                "memoria_record_add",
                "memoria_record_query",
                "memoria_record_summary",
            }.issubset(names))
            stored = self.tool_data(client.request("tools/call", {
                "name": "memoria_store",
                "arguments": {"content": "原始内容", "tags": "旧标签"},
            }))
            updated = self.tool_data(client.request("tools/call", {
                "name": "memoria_update",
                "arguments": {
                    "memory_id": stored["id"],
                    "content": "更新后的内容",
                    "tags": "新标签",
                    "private": True,
                },
            }))
            fetched = self.tool_data(client.request("tools/call", {
                "name": "memoria_get",
                "arguments": {"memory_id": stored["id"]},
            }))
            self.assertEqual(stored["id"], updated["id"])
            self.assertEqual("更新后的内容", fetched["content"])
            self.assertEqual(["新标签"], fetched["tags"])
            self.assertTrue(fetched["private"])
            args = {
                "user_id": "zhouwei",
                "record_type": "fitness",
                "occurred_at": "2026-06-21T20:00:00+08:00",
                "data": {"steps": 6000, "duration_minutes": 30},
                "dedupe_key": "mcp-day-1",
            }
            created = self.tool_data(client.request("tools/call", {"name": "memoria_record_add", "arguments": args}))
            duplicate = self.tool_data(client.request("tools/call", {"name": "memoria_record_add", "arguments": args}))
            queried = self.tool_data(client.request("tools/call", {
                "name": "memoria_record_query",
                "arguments": {"user_id": "zhouwei", "record_type": "fitness"},
            }))
            summary = self.tool_data(client.request("tools/call", {
                "name": "memoria_record_summary",
                "arguments": {"user_id": "zhouwei"},
            }))
            self.assertEqual("created", created["status"])
            self.assertEqual("exists", duplicate["status"])
            self.assertEqual(1, len(queried))
            self.assertEqual(6000, summary["total_steps"])
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
