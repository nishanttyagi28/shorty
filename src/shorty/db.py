"""SQLite helpers for shorty."""

import os
import sqlite3

DEFAULT_DB = "shorty.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code       TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def db_path() -> str:
    """Return the configured database path (SHORTY_DB, default shorty.db)."""
    env = os.environ.get("SHORTY_DB")
    if env:
        return env
    if os.environ.get("VERCEL"):
        return "/tmp/shorty.db"
    return DEFAULT_DB


def connect() -> sqlite3.Connection:
    """Open a new connection with row access by name."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the schema if it does not exist yet."""
    with connect() as conn:
        conn.executescript(SCHEMA)
