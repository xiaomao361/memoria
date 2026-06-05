"""SQLite 数据层"""

import sqlite3
from contextlib import contextmanager
from typing import Optional

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_recalled_at TEXT,
    recall_count INTEGER DEFAULT 0,
    importance REAL DEFAULT 0.0,
    private INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    kind TEXT DEFAULT 'fact',
    authority TEXT DEFAULT 'confirmed',
    retrieval_role TEXT DEFAULT 'background',
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active',
    superseded_by TEXT,
    valid_from TEXT,
    valid_until TEXT,
    source_agent TEXT,
    source_run_id TEXT,
    file_path TEXT
);

CREATE TABLE IF NOT EXISTS labels (
    memory_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'tag',
    UNIQUE(memory_id, name),
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_candidates (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    summary TEXT,
    proposed_tags TEXT,
    proposed_kind TEXT,
    proposed_authority TEXT,
    proposed_retrieval_role TEXT,
    confidence REAL DEFAULT 0.7,
    source TEXT NOT NULL,
    source_agent TEXT,
    source_run_id TEXT,
    private INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT,
    promoted_memory_id TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    trust_level TEXT NOT NULL DEFAULT 'trusted_writer',
    can_read_private INTEGER DEFAULT 0,
    can_write_durable INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED, summary, content, tokenize='unicode61'
);

CREATE INDEX IF NOT EXISTS idx_labels_name ON labels(name);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_private ON memories(private);
CREATE INDEX IF NOT EXISTS idx_memories_archived ON memories(archived);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON memory_candidates(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_agent ON memory_candidates(source_agent, status);
CREATE INDEX IF NOT EXISTS idx_agents_trust ON agents(trust_level, can_write_durable);
"""

MIGRATIONS = [
    ("kind", "ALTER TABLE memories ADD COLUMN kind TEXT DEFAULT 'fact'"),
    ("authority", "ALTER TABLE memories ADD COLUMN authority TEXT DEFAULT 'confirmed'"),
    ("retrieval_role", "ALTER TABLE memories ADD COLUMN retrieval_role TEXT DEFAULT 'background'"),
    ("confidence", "ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 1.0"),
    ("status", "ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active'"),
    ("superseded_by", "ALTER TABLE memories ADD COLUMN superseded_by TEXT"),
    ("valid_from", "ALTER TABLE memories ADD COLUMN valid_from TEXT"),
    ("valid_until", "ALTER TABLE memories ADD COLUMN valid_until TEXT"),
    ("source_agent", "ALTER TABLE memories ADD COLUMN source_agent TEXT"),
    ("source_run_id", "ALTER TABLE memories ADD COLUMN source_run_id TEXT"),
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_memories_table(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)")
        conn.execute(
            "UPDATE memories SET status = 'archived' WHERE archived = 1 AND (status IS NULL OR status = 'active')"
        )
        conn.execute(
            "UPDATE memories SET status = 'active' WHERE archived = 0 AND status IS NULL"
        )


def _migrate_memories_table(conn):
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(memories)").fetchall()
    }
    for column, sql in MIGRATIONS:
        if column not in columns:
            conn.execute(sql)


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
