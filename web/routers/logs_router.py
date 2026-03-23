"""
Log viewer API — serves log file contents and runtime level control.
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from utils.logger import read_log_tail, get_log_files, set_log_level, get_log_level
from web.state import load_config_overrides, save_config_overrides

router = APIRouter(prefix="/api/logs", tags=["logs"])


class LevelRequest(BaseModel):
    level: str  # DEBUG | INFO | WARNING | ERROR | CRITICAL


@router.get("")
def get_logs(
    lines: int = Query(default=500, ge=1, le=5000),
    level: str = Query(default="DEBUG"),
    file: str = Query(default=""),
):
    """
    Return the last N log lines, optionally filtered by minimum level.
    level: minimum severity to include (DEBUG=all, INFO=info+, WARNING=warnings+, ERROR=errors only)
    file: specific log filename to read (empty = today's active file)
    """
    entries = read_log_tail(lines=lines, level_filter=level, filename=file)
    return {
        "entries": entries,
        "count": len(entries),
        "current_level": get_log_level(),
    }


@router.get("/files")
def list_log_files():
    """List all available log files with metadata."""
    return {"files": get_log_files()}


@router.get("/level")
def get_current_level():
    """Return the current runtime log level."""
    return {"level": get_log_level()}


@router.post("/level")
def update_level(body: LevelRequest):
    """
    Change the runtime log level immediately.
    Also persists to the config table in SQLite so it survives restarts.
    """
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    lvl = body.level.upper()
    if lvl not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid level. Valid: {sorted(valid)}")

    set_log_level(lvl)

    # Persist in config overrides
    cfg = load_config_overrides()
    cfg["log_level"] = lvl
    save_config_overrides(cfg)

    return {"success": True, "level": lvl}
