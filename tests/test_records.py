import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(tempfile.mkdtemp(prefix="memoria-records-tests-"))
os.environ["MEMORIA_ROOT"] = str(TEST_ROOT)

from memoria.config import DB_PATH, STORE_DIR
from memoria.core import delete_memory, get_memory, purge_memory, recall, restore_memory, store
from memoria.db import get_conn, init_db
from memoria.maintain import rebuild
from memoria.records import (
    RecordValidationError,
    add_record,
    query_records,
    summarize_records,
)


class RecordTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
        TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def add(self, **overrides):
        args = {
            "user_id": "zhouwei",
            "record_type": "fitness",
            "occurred_at": "2026-06-21T20:00:00+08:00",
            "timezone_name": "Asia/Shanghai",
            "data": {"activity": "步行", "steps": 16000, "duration_minutes": 90},
            "schema_version": 1,
            "source": "codex",
        }
        args.update(overrides)
        return add_record(**args)

    def test_init_creates_records_table_and_indexes(self):
        init_db()
        with get_conn() as conn:
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='records'"
            ).fetchone()
            indexes = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='records'"
                ).fetchall()
            }
        self.assertIsNotNone(table)
        self.assertIn("idx_records_user_type_occurred", indexes)
        self.assertIn("idx_records_user_local_date", indexes)
        self.assertIn("idx_records_dedupe", indexes)

    def test_add_reads_back_structured_record(self):
        result = self.add(note="晚间散步")
        self.assertEqual("created", result["status"])
        self.assertEqual(16000, result["record"]["data"]["steps"])
        self.assertEqual("2026-06-21", result["record"]["local_date"])
        with get_conn() as conn:
            stored = conn.execute("SELECT data_json FROM records WHERE id = ?", (result["id"],)).fetchone()
        self.assertIsNotNone(stored)

    def test_record_does_not_enter_memory_storage_or_recall(self):
        self.add()
        self.assertFalse(STORE_DIR.exists())
        self.assertEqual([], recall())
        with get_conn() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0])

    def test_dedupe_returns_existing_record(self):
        first = self.add(dedupe_key="fitness-2026-06-21")
        second = self.add(dedupe_key="fitness-2026-06-21")
        self.assertEqual("created", first["status"])
        self.assertEqual("exists", second["status"])
        self.assertEqual(first["id"], second["id"])
        with get_conn() as conn:
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def test_user_isolation_type_and_local_date(self):
        self.add()
        self.add(
            user_id="other",
            occurred_at="2026-06-22T08:00:00+08:00",
            data={"activity": "跑步", "distance_km": 5},
        )
        self.assertEqual(1, len(query_records("zhouwei")))
        self.assertEqual([], query_records("zhouwei", record_type="fitness", local_date="2026-06-22"))
        self.assertEqual(1, len(query_records("other", record_type="fitness", local_date="2026-06-22")))

    def test_time_range_is_start_inclusive_end_exclusive(self):
        self.add(occurred_at="2026-06-20T00:00:00+08:00", data={"steps": 1})
        self.add(occurred_at="2026-06-21T00:00:00+08:00", data={"steps": 2})
        rows = query_records(
            "zhouwei",
            start="2026-06-20T00:00:00+08:00",
            end="2026-06-21T00:00:00+08:00",
        )
        self.assertEqual([1], [row["data"]["steps"] for row in rows])

    def test_pagination_and_sorting_are_stable(self):
        for day in (20, 21, 22):
            self.add(
                occurred_at=f"2026-06-{day:02d}T08:00:00+08:00",
                data={"steps": day},
                dedupe_key=f"day-{day}",
            )
        first = query_records("zhouwei", limit=2)
        second = query_records("zhouwei", limit=2, offset=2)
        self.assertEqual([22, 21], [row["data"]["steps"] for row in first])
        self.assertEqual([20], [row["data"]["steps"] for row in second])

    def test_summary_and_empty_summary(self):
        self.add(
            occurred_at="2026-06-20T08:00:00+08:00",
            data={"steps": 1000, "duration_minutes": 30, "distance_km": 1.5, "sets": 2},
        )
        self.add(
            occurred_at="2026-06-21T08:00:00+08:00",
            data={"steps": 2000, "duration_minutes": 45, "repetitions": 20},
        )
        summary = summarize_records("zhouwei")
        self.assertEqual(2, summary["record_count"])
        self.assertEqual(2, summary["active_days"])
        self.assertEqual(3000, summary["total_steps"])
        self.assertEqual(75, summary["total_duration_minutes"])
        self.assertEqual(1.5, summary["total_distance_km"])
        self.assertEqual(20, summary["total_repetitions"])
        self.assertEqual(2, summary["total_sets"])
        self.assertEqual(0, summarize_records("nobody")["record_count"])

    def test_invalid_payloads_are_rejected_before_db_init(self):
        invalid_cases = [
            {"data": "text"},
            {"data": []},
            {"occurred_at": "2026-06-21T20:00:00"},
            {"data": {"steps": -1}},
            {"data": {"steps": 1.5}},
            {"data": {"steps": True}},
            {"data": {"stepz": 100}},
            {"data": {"activity": ""}},
            {"timezone_name": "Not/A-Timezone"},
        ]
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                shutil.rmtree(TEST_ROOT, ignore_errors=True)
                with self.assertRaises(RecordValidationError):
                    self.add(**overrides)
                self.assertFalse(DB_PATH.exists())

    @patch("memoria.core.upsert_vector", return_value=True)
    @patch("memoria.core.delete_vector")
    def test_existing_memory_flow_and_rebuild_preserve_records(self, _delete, _upsert):
        record = self.add(dedupe_key="preserve-me")
        memory = store(content="临时回归记忆", tags=["codex"], source="codex", source_agent="codex")
        memory_path = STORE_DIR / memory["file_path"]
        self.assertTrue(memory_path.exists())
        self.assertEqual(memory["id"], recall(memory_id=memory["id"])[0]["id"])
        self.assertTrue(delete_memory(memory["id"]))
        self.assertTrue(restore_memory(memory["id"]))
        self.assertIsNotNone(get_memory(memory["id"]))

        with patch("memoria.maintain.reset_collection"), patch(
            "memoria.maintain.upsert_vector", return_value=True
        ):
            rebuilt = rebuild()
        self.assertEqual(1, rebuilt["imported"])
        self.assertEqual(record["id"], query_records("zhouwei")[0]["id"])
        self.assertTrue(purge_memory(memory["id"]))
        self.assertFalse(memory_path.exists())


if __name__ == "__main__":
    unittest.main()
