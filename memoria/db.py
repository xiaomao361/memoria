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
    file_path TEXT
);

CREATE TABLE IF NOT EXISTS labels (
    memory_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'tag',
    UNIQUE(memory_id, name),
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED, summary, content, tokenize='unicode61'
);

CREATE INDEX IF NOT EXISTS idx_labels_name ON labels(name);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_private ON memories(private);
CREATE INDEX IF NOT EXISTS idx_memories_archived ON memories(archived);
"""


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


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
