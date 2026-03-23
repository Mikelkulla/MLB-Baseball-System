"""
Feed health monitoring and execution logging.
Equivalent to V8.0 Logging.js — tracks status of all data feeds.

Log files: logs/mlb_YYYY-MM-DD.log  (daily rotation, 30-day retention)
Level:      configurable at runtime via /api/logs/level

FeedHealthMonitor and ScheduleLogger persist to SQLite
(output_data/mlb.db) instead of JSON files.
"""

from __future__ import annotations
import logging
import logging.handlers
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from db.database import read_db, write_db

# Logs go to their own directory, separate from output_data
LOG_DIR = Path(__file__).parent.parent / "logs"
OUTPUT_DIR = Path(__file__).parent.parent / "output_data"

# Current runtime level (mutated by set_log_level)
_current_level: str = "INFO"

# Maximum schedule_log rows to retain
_SCHEDULE_LOG_MAX_ROWS = 500


class FeedStatus(str, Enum):
    OK       = "OK"
    FAIL     = "FAIL"
    PARTIAL  = "PARTIAL"
    RUNNING  = "RUNNING"


FEEDS = ["OddsAPI", "DraftKings", "Weather", "Injuries", "Pitchers"]


class FeedHealthMonitor:
    """Tracks the last-known status of each data feed (persisted in DB)."""

    def set_status(
        self,
        feed: str,
        status: FeedStatus,
        detail: str = "",
        record_count: int = 0,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with write_db() as conn:
            conn.execute("""
                INSERT INTO feed_health (feed, status, detail, record_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(feed) DO UPDATE SET
                    status       = excluded.status,
                    detail       = excluded.detail,
                    record_count = excluded.record_count,
                    updated_at   = excluded.updated_at
            """, (feed, status.value, detail, record_count, now))

    def get_status(self, feed: str) -> Optional[dict]:
        with read_db() as conn:
            row = conn.execute(
                "SELECT * FROM feed_health WHERE feed = ?", (feed,)
            ).fetchone()
        return dict(row) if row else None

    def get_all(self) -> dict[str, dict]:
        with read_db() as conn:
            rows = conn.execute("SELECT * FROM feed_health").fetchall()
        return {r["feed"]: dict(r) for r in rows}

    def all_ok(self) -> bool:
        health = self.get_all()
        return all(
            health.get(f, {}).get("status") == FeedStatus.OK.value
            for f in FEEDS
        )

    def print_summary(self) -> None:
        health = self.get_all()
        print(f"\n{'='*50}")
        print("  FEED HEALTH")
        print(f"{'='*50}")
        for feed in FEEDS:
            entry = health.get(feed, {})
            status = entry.get("status", "UNKNOWN")
            detail = entry.get("detail", "")
            updated = entry.get("updated_at", "never")
            icon = {"OK": "✓", "FAIL": "✗", "PARTIAL": "~", "RUNNING": "⟳"}.get(status, "?")
            print(f"  {icon} {feed:<15} {status:<10} {detail[:30]:<32} {updated[:19]}")
        print(f"{'='*50}\n")


class ScheduleLogger:
    """Appends timestamped entries to the schedule_log table; trims to 500 rows."""

    def log(self, task: str, status: str, detail: str = "", duration_ms: int = 0) -> None:
        now = datetime.utcnow().isoformat()
        with write_db() as conn:
            conn.execute("""
                INSERT INTO schedule_log (task, status, detail, duration_ms, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (task, status, detail, duration_ms, now))
            # Keep only the most recent rows to bound table growth
            conn.execute(f"""
                DELETE FROM schedule_log
                WHERE id NOT IN (
                    SELECT id FROM schedule_log
                    ORDER BY id DESC
                    LIMIT {_SCHEDULE_LOG_MAX_ROWS}
                )
            """)

    def get_recent(self, limit: int = 20) -> list[dict]:
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM schedule_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        # Return chronological order (oldest first)
        return [dict(r) for r in reversed(rows)]


def configure_logging(level: str = "INFO") -> None:
    """
    Set up console + daily-rotating file logging for the entire system.

    Files: logs/mlb_YYYY-MM-DD.log
    Rotation: midnight, 30-day retention
    File level: always DEBUG (captures everything)
    Console level: controlled by `level` parameter
    """
    global _current_level
    _current_level = level.upper()

    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / "mlb.log"   # handler adds date suffix on rotation

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove any existing handlers to avoid duplicates on re-configure
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console — respects runtime level
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, _current_level, logging.INFO))
    console.setFormatter(fmt)
    root.addHandler(console)

    # Rotating file — always DEBUG so every line is captured to disk
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=True,
    )
    file_handler.suffix = "%Y-%m-%d"       # mlb.log.2026-03-22
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def set_log_level(level: str) -> str:
    """Change the console log level at runtime. File always stays at DEBUG."""
    global _current_level
    level = level.upper()
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level not in valid:
        raise ValueError(f"Invalid level '{level}'. Valid: {valid}")
    _current_level = level
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.handlers.TimedRotatingFileHandler
        ):
            handler.setLevel(getattr(logging, level))
    logging.getLogger(__name__).info("Log level changed to %s", level)
    return level


def get_log_level() -> str:
    return _current_level


def get_log_files() -> list[dict]:
    """Return all available log files sorted newest first."""
    LOG_DIR.mkdir(exist_ok=True)
    files = sorted(LOG_DIR.glob("mlb.log*"), key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        stat = f.stat()
        result.append({
            "name": f.name,
            "path": str(f),
            "size_bytes": stat.st_size,
            "modified": datetime.utcfromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


def read_log_tail(lines: int = 500, level_filter: str = "DEBUG", filename: str = "") -> list[dict]:
    """
    Read the last `lines` lines from a log file, optionally filtered by minimum level.
    Returns list of dicts with keys: timestamp, level, logger, message, raw.
    """
    LOG_DIR.mkdir(exist_ok=True)

    # Determine which file to read
    if filename:
        target = LOG_DIR / filename
    else:
        # Today's active file
        target = LOG_DIR / "mlb.log"
        if not target.exists():
            # Fall back to most recent rotated file
            candidates = sorted(LOG_DIR.glob("mlb.log*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                target = candidates[0]

    if not target.exists():
        return []

    try:
        raw_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    # Take last N lines
    raw_lines = raw_lines[-lines:]

    level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_order = level_order.get(level_filter.upper(), 0)

    parsed = []
    for line in raw_lines:
        entry = _parse_log_line(line)
        if level_order.get(entry["level"], 0) >= min_order:
            parsed.append(entry)

    return parsed


def _parse_log_line(line: str) -> dict:
    """Parse a log line into structured fields. Falls back gracefully."""
    # Expected: 2026-03-22 10:30:45 [INFO    ] pipeline: message
    try:
        parts = line.split(" ", 3)
        timestamp = parts[0] + " " + parts[1]
        level = parts[2].strip("[]").strip()
        rest = parts[3] if len(parts) > 3 else ""
        if ": " in rest:
            logger_name, message = rest.split(": ", 1)
        else:
            logger_name, message = "", rest
        return {
            "timestamp": timestamp,
            "level": level,
            "logger": logger_name,
            "message": message,
            "raw": line,
        }
    except Exception:
        return {
            "timestamp": "",
            "level": "DEBUG",
            "logger": "",
            "message": line,
            "raw": line,
        }
