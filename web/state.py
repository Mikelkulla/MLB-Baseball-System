"""
Global state singleton — pipeline instance shared across all API routes.
Also manages runtime config overrides (editable from the UI).

Config is persisted in SQLite (config table, key='main') instead of a
JSON file, giving atomic reads/writes and no file-lock contention.
"""

from __future__ import annotations
import json
import logging
from typing import Optional

from db.database import read_db, write_db

logger = logging.getLogger(__name__)

# ── Pipeline singleton ────────────────────────────────────────────────────────
_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pipeline import MLBPipeline
        _pipeline = MLBPipeline()
    return _pipeline

# ── Scheduler singleton ───────────────────────────────────────────────────────
_scheduler = None
_scheduler_preset = "default"
_scheduler_running = False

def get_scheduler():
    global _scheduler
    if _scheduler is None:
        from scheduler.runner import MLBScheduler
        _scheduler = MLBScheduler(get_pipeline())
    return _scheduler

def scheduler_status() -> dict:
    return {
        "running": _scheduler_running,
        "preset": _scheduler_preset,
    }

def start_scheduler(preset: str = "default") -> None:
    global _scheduler_running, _scheduler_preset
    s = get_scheduler()
    if not _scheduler_running:
        s.start(preset=preset)
        _scheduler_running = True
        _scheduler_preset = preset

def stop_scheduler() -> None:
    global _scheduler_running
    s = get_scheduler()
    if _scheduler_running:
        s.stop()
        _scheduler_running = False

# ── Runtime config overrides ─────────────────────────────────────────────────
_DEFAULT_OVERRIDES = {
    "tiers": [
        {"name": "ELITE",     "min_confidence": 85.0, "units": 3.0},
        {"name": "STRONGEST", "min_confidence": 75.0, "units": 2.5},
        {"name": "BEST BET",  "min_confidence": 68.0, "units": 1.75},
        {"name": "GOLD",      "min_confidence": 60.0, "units": 1.0},
    ],
    "confidence_weights": {
        "ev": 0.35,
        "probability": 0.25,
        "clv": 0.20,
        "sharp_action": 0.20,
    },
    "betting": {
        "max_ml_odds": -200,
        "min_ev_threshold": 2.0,
        "unit_size_dollars": 100.0,
        "sp_gate_enabled": True,
    },
    "pitcher_weights": {
        "era": 0.30,
        "whip": 0.25,
        "k9": 0.20,
        "bb9": 0.15,
        "recent_form": 0.10,
    },
    # Logging
    "log_level": "INFO",     # DEBUG | INFO | WARNING | ERROR | CRITICAL
    "log_lines": 500,        # default lines shown in the UI log viewer
}

def load_config_overrides() -> dict:
    """Load config from DB; returns defaults if no row exists yet."""
    try:
        with read_db() as conn:
            row = conn.execute(
                "SELECT value FROM config WHERE key = 'main'"
            ).fetchone()
        if row:
            return json.loads(row["value"])
    except Exception as exc:
        logger.warning("Could not load config from DB: %s", exc)
    return dict(_DEFAULT_OVERRIDES)


def save_config_overrides(data: dict) -> None:
    """Persist config to DB as a JSON blob (atomic upsert)."""
    with write_db() as conn:
        conn.execute("""
            INSERT INTO config (key, value) VALUES ('main', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (json.dumps(data),))


def get_default_config() -> dict:
    return dict(_DEFAULT_OVERRIDES)
