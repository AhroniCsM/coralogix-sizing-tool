import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GCS persistence — keeps SQLite DB in a GCS bucket so it survives
# Cloud Run container restarts / new revisions.
# ---------------------------------------------------------------------------
GCS_BUCKET = os.getenv("GCS_DB_BUCKET", "")  # e.g. "coralogix-sizing-tool-data"
GCS_BLOB = "sizing.db"

_gcs_bucket_obj = None


def _get_gcs_bucket():
    """Lazily initialise GCS bucket handle."""
    global _gcs_bucket_obj
    if _gcs_bucket_obj is None and GCS_BUCKET:
        try:
            from google.cloud import storage as gcs
            client = gcs.Client()
            _gcs_bucket_obj = client.bucket(GCS_BUCKET)
            logger.info("GCS persistence enabled — bucket: %s", GCS_BUCKET)
        except Exception:
            logger.exception("Failed to initialise GCS client")
    return _gcs_bucket_obj


def _download_db_from_gcs() -> bool:
    """Download DB from GCS if it exists. Returns True on success."""
    bucket = _get_gcs_bucket()
    if not bucket:
        return False
    blob = bucket.blob(GCS_BLOB)
    try:
        if blob.exists():
            settings.db_path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(settings.db_path))
            logger.info("Downloaded DB from GCS (%s bytes)", settings.db_path.stat().st_size)
            return True
        logger.info("No existing DB in GCS — will create fresh")
    except Exception:
        logger.exception("Failed to download DB from GCS")
    return False


def _upload_db_to_gcs() -> None:
    """Upload current DB to GCS."""
    bucket = _get_gcs_bucket()
    if not bucket:
        return
    try:
        blob = bucket.blob(GCS_BLOB)
        blob.upload_from_filename(str(settings.db_path))
        logger.debug("Uploaded DB to GCS")
    except Exception:
        logger.exception("Failed to upload DB to GCS")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS sizing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK(provider IN ('datadog', 'newrelic', 'cloudwatch')),
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
    # Try to restore DB from GCS first
    _download_db_from_gcs()

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

        # Migration: update CHECK constraint to include 'cloudwatch'
        # SQLite can't ALTER CHECK constraints, so recreate the table
        check_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sizing_runs'"
        ).fetchone()
        if check_sql and "cloudwatch" not in (check_sql[0] or ""):
            logger.info("Migrating sizing_runs table to add 'cloudwatch' provider")
            # Disable FK checks during migration
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("ALTER TABLE sizing_runs RENAME TO sizing_runs_old")
            db.execute("""
                CREATE TABLE sizing_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL CHECK(provider IN ('datadog', 'newrelic', 'cloudwatch')),
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
                )
            """)
            db.execute("""
                INSERT INTO sizing_runs
                SELECT id, provider, created_at, raw_extraction, corrected_values,
                       results, missing_fields, screenshot_paths, status, user_email,
                       prompt_tokens, completion_tokens, api_cost_usd
                FROM sizing_runs_old
            """)
            db.execute("DROP TABLE sizing_runs_old")
            db.execute("PRAGMA foreign_keys=ON")

        # Seed initial admin
        db.execute(
            "INSERT OR IGNORE INTO admin_users (email) VALUES (?)",
            ("aharon.shahar@coralogix.com",),
        )

    # Back up the initialised DB
    _upload_db_to_gcs()


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
        # Sync to GCS after every successful commit
        _upload_db_to_gcs()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
