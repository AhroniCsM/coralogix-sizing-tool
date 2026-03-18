import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sizing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK(provider IN ('datadog', 'newrelic')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_extraction TEXT NOT NULL,
    corrected_values TEXT,
    results TEXT,
    missing_fields TEXT,
    screenshot_paths TEXT NOT NULL,
    status TEXT DEFAULT 'extracted',
    user_email TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    api_cost_usd REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES sizing_runs(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_accurate BOOLEAN NOT NULL,
    notes TEXT,
    field_corrections TEXT
);

CREATE TABLE IF NOT EXISTS admin_users (
    email TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS extraction_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    field_name TEXT NOT NULL,
    common_error TEXT,
    correction_hint TEXT,
    sample_count INTEGER DEFAULT 1,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, field_name, common_error)
);
"""


def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.executescript(SCHEMA)
        # Migration: add user_email column if missing (existing DBs)
        cols = [row[1] for row in db.execute("PRAGMA table_info(sizing_runs)").fetchall()]
        if "user_email" not in cols:
            db.execute("ALTER TABLE sizing_runs ADD COLUMN user_email TEXT")

        # Migration: add API cost tracking columns if missing
        if "api_cost_usd" not in cols:
            db.execute("ALTER TABLE sizing_runs ADD COLUMN prompt_tokens INTEGER DEFAULT 0")
            db.execute("ALTER TABLE sizing_runs ADD COLUMN completion_tokens INTEGER DEFAULT 0")
            db.execute("ALTER TABLE sizing_runs ADD COLUMN api_cost_usd REAL DEFAULT 0")

        # Seed initial admin
        db.execute(
            "INSERT OR IGNORE INTO admin_users (email) VALUES (?)",
            ("aharon.shahar@coralogix.com",),
        )


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(settings.db_path))
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
