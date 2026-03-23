"""
SQLite database connection manager.

Concurrency model:
  WAL journal mode      — concurrent readers never block each other and never
                          block the single writer; writer does not block readers.
  Per-thread connections — each OS/Python thread gets its own sqlite3.Connection
                          via threading.local, avoiding cross-thread sharing.
  _write_lock           — a process-level threading.Lock that serialises all
                          write transactions at the Python layer, so two threads
                          never race for the same SQLite write lock.
  busy_timeout=5000     — safety net: SQLite will retry for up to 5 s before
                          raising OperationalError on lock contention.

Usage:
    from db.database import read_db, write_db

    # Read (no lock, WAL allows concurrent reads):
    with read_db() as conn:
        rows = conn.execute("SELECT * FROM bets").fetchall()

    # Write (acquires _write_lock first, then BEGIN IMMEDIATE):
    with write_db() as conn:
        conn.execute("INSERT INTO bets ...")
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DB_PATH = Path(__file__).parent.parent / "output_data" / "mlb.db"

_thread_local = threading.local()
_write_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    """Open a new SQLite connection configured for WAL and safe operation."""
    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,   # we manage thread-safety ourselves
        isolation_level=None,      # autocommit; transactions are explicit
    )
    conn.row_factory = sqlite3.Row
    # WAL mode: readers/writers coexist without blocking each other
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL: flush at checkpoints, not every commit — good balance of perf/safety
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Wait up to 5 s if another connection holds a lock before raising
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _get_conn() -> sqlite3.Connection:
    """Return the per-thread connection, creating it on first access."""
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = _connect()
        _thread_local.conn = conn
    return conn


@contextmanager
def read_db() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for read-only queries.
    No lock is needed — WAL mode allows any number of concurrent readers.
    """
    yield _get_conn()


@contextmanager
def write_db() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for write operations.
    Acquires the process-level _write_lock first, then opens a
    BEGIN IMMEDIATE transaction on the per-thread connection.
    Commits on clean exit; rolls back on any exception.
    """
    with _write_lock:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
