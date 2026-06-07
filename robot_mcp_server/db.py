"""
SQLite persistence layer for Robot Framework failure analysis.

Schema design
-------------
runs          — one row per ingested results directory (deduped by content hash)
scored_tests  — one row per failing test (base_score only; group_bonus computed at query time)

The content hash is a SHA-1 over sorted (xml_path, mtime) pairs so re-ingesting
an unchanged results directory is a silent no-op.

Group bonuses are NOT stored — they depend on the area_filter used at query time,
so they're computed on the fly with a window COUNT(*) OVER (PARTITION BY fp).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import warnings
from datetime import datetime, timezone
from typing import Optional

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    results_dir TEXT    NOT NULL,
    hash        TEXT    NOT NULL,
    ingested_at TEXT    NOT NULL,
    UNIQUE(hash)
);

CREATE TABLE IF NOT EXISTS scored_tests (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    area            TEXT    NOT NULL,
    suite           TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    tags            TEXT    NOT NULL DEFAULT '[]',
    message         TEXT    NOT NULL DEFAULT '',
    failure_type    TEXT    NOT NULL,
    priority        TEXT    NOT NULL,
    severity        TEXT    NOT NULL,
    defect_ids      TEXT    NOT NULL DEFAULT '[]',
    is_quarantined  INTEGER NOT NULL DEFAULT 0,
    fp              TEXT    NOT NULL,
    base_score      INTEGER NOT NULL,
    xml_path        TEXT    NOT NULL,
    api_endpoint    TEXT,
    escalated       INTEGER NOT NULL DEFAULT 0,
    received_code   INTEGER,
    response_error  TEXT
);

CREATE INDEX IF NOT EXISTS idx_st_run_fp    ON scored_tests(run_id, fp);
CREATE INDEX IF NOT EXISTS idx_st_run_area  ON scored_tests(run_id, area);
CREATE INDEX IF NOT EXISTS idx_st_run_score ON scored_tests(run_id, base_score DESC);
"""

_DB_FILENAME = "failure_analysis.db"

from .failure_matrix import GROUP_BONUS_PER_EXTRA as _GROUP_BONUS_PER_EXTRA, GROUP_BONUS_CAP as _GROUP_BONUS_CAP


def _db_path(results_dir: str) -> str:
    return os.path.join(results_dir, _DB_FILENAME)


def _connect(results_dir: str) -> sqlite3.Connection:
    """Open a connection with per-connection PRAGMAs. Does NOT create schema."""
    conn = sqlite3.connect(_db_path(results_dir))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _connect_and_init(results_dir: str) -> sqlite3.Connection:
    """Open a connection and ensure the schema exists (used only during ingest)."""
    conn = _connect(results_dir)
    conn.executescript(_DDL)
    conn.commit()
    return conn


def _content_hash(results_dir: str) -> str:
    """SHA-1 over sorted (xml_path, mtime) pairs for all robot/output.xml files found."""
    h = hashlib.sha1()
    entries: list[tuple[str, float]] = []
    for folder in sorted(os.listdir(results_dir)):
        xml = os.path.join(results_dir, folder, "robot", "output.xml")
        if os.path.exists(xml):
            entries.append((xml, os.path.getmtime(xml)))
    for path, mtime in sorted(entries):
        h.update(f"{path}:{mtime}".encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def db_exists(results_dir: str) -> bool:
    return os.path.exists(_db_path(results_dir))


def get_current_run_id(results_dir: str) -> Optional[int]:
    """Return the run_id if the DB is current (hash matches), else None."""
    if not db_exists(results_dir):
        return None
    try:
        conn = _connect(results_dir)
        current_hash = _content_hash(results_dir)
        row = conn.execute(
            "SELECT id FROM runs WHERE hash = ? ORDER BY id DESC LIMIT 1",
            (current_hash,),
        ).fetchone()
        conn.close()
        return row["id"] if row else None
    except Exception as exc:
        warnings.warn(f"DB read failed for {results_dir}: {exc}", stacklevel=2)
        return None


def ingest(results_dir: str, scored_tests: list) -> dict:
    """
    Write a list of ScoredTest objects into the DB for results_dir.

    If the content hash already exists this is a no-op and the existing
    run_id is returned.  Returns a stats dict:
        {run_id, ingested, already_current, total_failures}
    """
    from .failure_matrix import ScoredTest  # avoid circular import at module level

    current_hash = _content_hash(results_dir)
    conn = _connect_and_init(results_dir)

    # Idempotency check
    existing = conn.execute(
        "SELECT id FROM runs WHERE hash = ?", (current_hash,)
    ).fetchone()
    if existing:
        conn.close()
        return {
            "run_id": existing["id"],
            "ingested": False,
            "already_current": True,
            "total_failures": len(scored_tests),
        }

    # Insert run record
    conn.execute(
        "INSERT INTO runs(results_dir, hash, ingested_at) VALUES (?, ?, ?)",
        (results_dir, current_hash, datetime.now(timezone.utc).isoformat()),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Bulk-insert scored tests
    rows = [
        (
            run_id,
            t.area,
            t.suite,
            t.name,
            json.dumps(t.tags),
            t.message,
            t.failure_type,
            t.priority,
            t.severity,
            json.dumps(t.defect_ids),
            int(t.is_quarantined),
            t.fp,
            t.base_score,
            t.xml_path,
            t.api_endpoint,
            int(t.escalated),
            t.received_code,
            t.response_error,
        )
        for t in scored_tests
    ]
    conn.executemany(
        """INSERT INTO scored_tests(
            run_id, area, suite, name, tags, message, failure_type,
            priority, severity, defect_ids, is_quarantined, fp, base_score,
            xml_path, api_endpoint, escalated, received_code, response_error
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "ingested": True,
        "already_current": False,
        "total_failures": len(rows),
    }


def load_scored_tests(results_dir: str, run_id: int, area_filter: str = "") -> list:
    """
    Load ScoredTest objects from the DB for a given run_id.

    Group bonuses are computed here via a SQL window COUNT so the returned
    objects already have the correct .group_bonus for the given area_filter.
    """
    from .failure_matrix import ScoredTest

    conn = _connect(results_dir)

    area_clause = "AND LOWER(area) LIKE ?" if area_filter else ""
    area_param = f"%{area_filter.lower()}%" if area_filter else None

    params: list = [run_id]
    if area_param:
        params.append(area_param)

    # Window COUNT(*) OVER (PARTITION BY fp) gives group size for bonus calc
    sql = f"""
        SELECT *,
               COUNT(*) OVER (PARTITION BY fp) AS group_size
        FROM scored_tests
        WHERE run_id = ? {area_clause}
        ORDER BY base_score DESC
    """
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results: list[ScoredTest] = []
    for row in rows:
        group_bonus = min((row["group_size"] - 1) * _GROUP_BONUS_PER_EXTRA, _GROUP_BONUS_CAP)
        t = ScoredTest(
            area=row["area"],
            suite=row["suite"],
            name=row["name"],
            tags=json.loads(row["tags"]),
            message=row["message"],
            failure_type=row["failure_type"],
            priority=row["priority"],
            severity=row["severity"],
            defect_ids=json.loads(row["defect_ids"]),
            is_quarantined=bool(row["is_quarantined"]),
            fp=row["fp"],
            base_score=row["base_score"],
            xml_path=row["xml_path"],
            group_bonus=group_bonus,
            api_endpoint=row["api_endpoint"],
            escalated=bool(row["escalated"]),
            received_code=row["received_code"],
            response_error=row["response_error"],
        )
        results.append(t)
    return results
