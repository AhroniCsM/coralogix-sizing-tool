"""Learning & insights service.

Queries the extraction_insights table for prompt hints, processes feedback
to learn from corrections, and reads CSV files from screenshot directories.
"""

import csv
import json
import logging
from pathlib import Path

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)


def get_hints(provider: str) -> list[str]:
    """Return accumulated correction hints for a provider's extraction prompt."""
    with get_db() as db:
        rows = db.execute(
            "SELECT correction_hint, sample_count FROM extraction_insights "
            "WHERE provider = ? ORDER BY sample_count DESC LIMIT 20",
            (provider,),
        ).fetchall()
    return [row["correction_hint"] for row in rows]


def record_feedback(
    run_id: int,
    is_accurate: bool,
    notes: str | None,
    field_corrections: dict | None,
) -> None:
    """Store user feedback and update extraction_insights from corrections."""
    with get_db() as db:
        db.execute(
            "INSERT INTO feedback (run_id, is_accurate, notes, field_corrections) "
            "VALUES (?, ?, ?, ?)",
            (run_id, is_accurate, notes, json.dumps(field_corrections) if field_corrections else None),
        )

        # Update the run status
        db.execute(
            "UPDATE sizing_runs SET status = 'feedback_received' WHERE id = ?",
            (run_id,),
        )

        if not field_corrections:
            return

        # Get the provider for this run
        row = db.execute("SELECT provider FROM sizing_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return
        provider = row["provider"]

        # Upsert insights from each field correction
        for field_name, correction in field_corrections.items():
            extracted = correction.get("extracted")
            actual = correction.get("actual")
            if extracted is None or actual is None:
                continue

            common_error = f"Extracted {extracted} but actual was {actual}"
            correction_hint = (
                f"For '{field_name}': previously extracted as {extracted} "
                f"but the correct value was {actual}. Double-check this field."
            )

            db.execute(
                """INSERT INTO extraction_insights
                   (provider, field_name, common_error, correction_hint, sample_count)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(provider, field_name, common_error) DO UPDATE SET
                     sample_count = sample_count + 1,
                     last_updated = CURRENT_TIMESTAMP""",
                (provider, field_name, common_error, correction_hint),
            )


def get_all_insights(provider: str | None = None) -> list[dict]:
    """Return all extraction insights, optionally filtered by provider."""
    with get_db() as db:
        if provider:
            rows = db.execute(
                "SELECT * FROM extraction_insights WHERE provider = ? "
                "ORDER BY sample_count DESC, last_updated DESC",
                (provider,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM extraction_insights "
                "ORDER BY sample_count DESC, last_updated DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def learn_from_csv_files() -> dict[str, int]:
    """Scan screenshot directories for CSV files and learn field patterns.

    Returns a dict like {"datadog": 3, "newrelic": 1} with count of CSVs processed.
    """
    results: dict[str, int] = {}

    for provider in ("datadog", "newrelic"):
        provider_dir = settings.screenshots_dir / provider
        if not provider_dir.exists():
            continue

        csv_files = list(provider_dir.glob("*.csv"))
        count = 0

        for csv_path in csv_files:
            try:
                _process_csv(provider, csv_path)
                count += 1
            except Exception as e:
                logger.warning("Failed to process CSV %s: %s", csv_path, e)

        results[provider] = count

    return results


def _process_csv(provider: str, csv_path: Path) -> None:
    """Extract field-value patterns from a sizing CSV to build insights."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 2:
        return

    # Try to find header row and value rows
    # Common CSV formats: either key-value pairs or header + data rows
    header = rows[0]

    with get_db() as db:
        # Store a hint that this CSV was processed
        db.execute(
            """INSERT INTO extraction_insights
               (provider, field_name, common_error, correction_hint, sample_count)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(provider, field_name, common_error) DO UPDATE SET
                 sample_count = sample_count + 1,
                 last_updated = CURRENT_TIMESTAMP""",
            (
                provider,
                "_csv_source",
                f"Learned from {csv_path.name}",
                f"Reference CSV '{csv_path.name}' available with {len(rows)-1} data rows. "
                f"Columns: {', '.join(header[:10])}",
            ),
        )

        # Extract specific field patterns from known CSV formats
        _extract_csv_patterns(db, provider, header, rows[1:])


def _extract_csv_patterns(
    db, provider: str, header: list[str], data_rows: list[list[str]]
) -> None:
    """Extract reusable patterns from CSV data rows."""
    # Normalize headers
    norm_header = [h.strip().lower() for h in header]

    # Look for key columns that map to our extraction fields
    field_mappings_dd = {
        "infra host": "infra_hosts",
        "apm host": "apm_hosts",
        "container": "containers",
        "custom metric": "custom_metrics",
        "ingested log": "ingested_logs_gb",
        "indexed log": "indexed_logs",
        "ingested span": "ingested_spans_gb",
        "indexed span": "indexed_spans_million",
        "rum session": "rum_sessions",
        "total metric": "total_metrics_from_overview",
    }

    field_mappings_nr = {
        "logging": "logging_gb_day",
        "custom event": "custom_events_gb_day",
        "metric": "metrics_gb_day",
        "infra": "infra_hosts_gb_day",
        "apm": "apm_events_gb_day",
        "tracing": "tracing_gb_day",
        "browser": "browser_events_gb_day",
    }

    mappings = field_mappings_dd if provider == "datadog" else field_mappings_nr

    for col_idx, col_name in enumerate(norm_header):
        for pattern, field_name in mappings.items():
            if pattern in col_name:
                # Extract non-empty values from this column
                values = []
                for row in data_rows:
                    if col_idx < len(row) and row[col_idx].strip():
                        try:
                            val = row[col_idx].strip().replace(",", "")
                            float(val)
                            values.append(val)
                        except ValueError:
                            continue

                if values:
                    hint = (
                        f"CSV reference shows '{col_name}' values like: "
                        f"{', '.join(values[:3])}. "
                        f"Typical range for {field_name}."
                    )
                    db.execute(
                        """INSERT INTO extraction_insights
                           (provider, field_name, common_error, correction_hint, sample_count)
                           VALUES (?, ?, ?, ?, 1)
                           ON CONFLICT(provider, field_name, common_error) DO UPDATE SET
                             sample_count = sample_count + 1,
                             last_updated = CURRENT_TIMESTAMP""",
                        (provider, field_name, f"CSV range from {col_name}", hint),
                    )
                break


def get_run_history(limit: int = 50) -> list[dict]:
    """Return recent sizing runs with their feedback status."""
    with get_db() as db:
        rows = db.execute(
            """SELECT s.*,
                      f.is_accurate as feedback_accurate,
                      f.notes as feedback_notes
               FROM sizing_runs s
               LEFT JOIN feedback f ON f.run_id = s.id
               ORDER BY s.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
