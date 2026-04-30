"""
Lightweight SQLite database layer for Bitcoin Sentinel.

Only *flagged* (pivot) addresses are persisted — clean, inactive addresses
consume zero disk space, keeping the footprint minimal even for address sets
that date back to 2013.

Schema
------
addresses   — pivot address store (risk_score, category, cluster, metadata)
clusters    — named groups of related addresses (ransomware family, etc.)
alerts      — append-only log of emitted alerts
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

from sentinel import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS addresses (
        address     TEXT PRIMARY KEY,
        risk_score  INTEGER NOT NULL DEFAULT 0,
        category    TEXT    NOT NULL DEFAULT 'UNKNOWN',
        cluster_id  TEXT,
        first_seen  TEXT    NOT NULL,
        last_seen   TEXT    NOT NULL,
        tx_count    INTEGER NOT NULL DEFAULT 0,
        notes       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_addr_category ON addresses(category)",
    "CREATE INDEX IF NOT EXISTS idx_addr_cluster  ON addresses(cluster_id)",
    """
    CREATE TABLE IF NOT EXISTS clusters (
        id          TEXT PRIMARY KEY,
        name        TEXT    NOT NULL,
        category    TEXT    NOT NULL,
        description TEXT,
        confidence  INTEGER NOT NULL DEFAULT 50
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_hash     TEXT    NOT NULL,
        address     TEXT    NOT NULL,
        risk_score  INTEGER NOT NULL,
        category    TEXT    NOT NULL,
        cluster_id  TEXT,
        timestamp   TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_alert_address ON alerts(address)",
    "CREATE INDEX IF NOT EXISTS idx_alert_ts      ON alerts(timestamp)",
]


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    """Thread-safe SQLite wrapper for Sentinel pivot data."""

    def __init__(self, db_path: str = config.DB_PATH) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
        logger.debug("Database initialised at %s", db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            for stmt in _DDL:
                conn.execute(stmt)

    # ------------------------------------------------------------------
    # Address operations
    # ------------------------------------------------------------------

    def add_address(
        self,
        address: str,
        risk_score: int,
        category: str,
        cluster_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """Insert or replace a flagged address.  Returns True on success."""
        now = _utcnow()
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO addresses
                        (address, risk_score, category, cluster_id,
                         first_seen, last_seen, tx_count, notes)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(address) DO UPDATE SET
                        risk_score = excluded.risk_score,
                        category   = excluded.category,
                        cluster_id = excluded.cluster_id,
                        last_seen  = excluded.last_seen,
                        notes      = COALESCE(excluded.notes, addresses.notes)
                    """,
                    (address, risk_score, category, cluster_id, now, now, notes),
                )
            return True
        except sqlite3.Error as exc:
            logger.error("add_address(%s) failed: %s", address, exc)
            return False

    def get_address(self, address: str) -> Optional[Dict[str, Any]]:
        """Return the stored record for *address*, or ``None``."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM addresses WHERE address = ?", (address,)
            ).fetchone()
        return dict(row) if row else None

    def address_exists(self, address: str) -> bool:
        """Return True if *address* is flagged in the database."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM addresses WHERE address = ?", (address,)
            ).fetchone()
        return row is not None

    def update_address_seen(self, address: str) -> None:
        """Increment tx_count and update last_seen for *address*."""
        now = _utcnow()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE addresses
                SET last_seen = ?, tx_count = tx_count + 1
                WHERE address = ?
                """,
                (now, address),
            )

    def list_addresses(
        self,
        category: Optional[str] = None,
        min_risk: int = 0,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return flagged addresses, optionally filtered."""
        query = "SELECT * FROM addresses WHERE risk_score >= ?"
        params: list = [min_risk]
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY risk_score DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Cluster operations
    # ------------------------------------------------------------------

    def add_cluster(
        self,
        cluster_id: str,
        name: str,
        category: str,
        description: Optional[str] = None,
        confidence: int = 50,
    ) -> bool:
        """Insert or replace a named address cluster."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO clusters (id, name, category, description, confidence)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name        = excluded.name,
                        category    = excluded.category,
                        description = excluded.description,
                        confidence  = excluded.confidence
                    """,
                    (cluster_id, name, category, description, confidence),
                )
            return True
        except sqlite3.Error as exc:
            logger.error("add_cluster(%s) failed: %s", cluster_id, exc)
            return False

    def get_cluster(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored record for *cluster_id*, or ``None``."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM clusters WHERE id = ?", (cluster_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_clusters(self) -> List[Dict[str, Any]]:
        """Return all registered clusters."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM clusters ORDER BY category, name"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Alert operations
    # ------------------------------------------------------------------

    def record_alert(
        self,
        tx_hash: str,
        address: str,
        risk_score: int,
        category: str,
        cluster_id: Optional[str] = None,
    ) -> int:
        """Append an alert record and return its auto-increment id."""
        timestamp = _utcnow()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO alerts
                    (tx_hash, address, risk_score, category, cluster_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tx_hash, address, risk_score, category, cluster_id, timestamp),
            )
        return cursor.lastrowid  # type: ignore[return-value]

    def list_alerts(
        self,
        limit: int = 100,
        min_risk: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return recent alerts, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM alerts
                WHERE risk_score >= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (min_risk, limit),
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
