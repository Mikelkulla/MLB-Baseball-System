"""
TeamRegistry — persistent per-source team name mappings.

One row per canonical MLB team (30 rows).  Each row records the exact name
string that every data source uses for that team, plus a `locked` flag that
prevents programmatic overwrites when the operator has manually verified a row.

Public API
──────────
  seed_from_config()          → called once at startup; inserts the 30 teams
                                 if they don't already exist.

  record_seen_name(raw, source, team_key)
                              → auto-populates the source column for a team
                                 the first time we see it.  Respects `locked`.

  get_all()                   → list of all 30 rows as dicts (for the UI).

  patch(team_key, updates)    → UI-driven update; always writes, sets locked=1.

  set_locked(team_key, locked) → toggle lock without changing names.

Source column mapping
─────────────────────
  "odds_api"      → odds_api_name
  "draftkings"    → dk_name
  "mlb_stats_api" → mlb_stats_name
  "covers"        → covers_name
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from db.database import read_db, write_db
from config.mlb_config import MLB_TEAMS

logger = logging.getLogger(__name__)

# Maps the source string (as used by team_resolver) to the DB column name
SOURCE_COLUMN: dict[str, str] = {
    "odds_api":      "odds_api_name",
    "draftkings":    "dk_name",
    "mlb_stats_api": "mlb_stats_name",
    "covers":        "covers_name",
}

VALID_PATCH_FIELDS = {
    "odds_api_name", "dk_name", "mlb_stats_name", "covers_name", "notes",
}


# ---------------------------------------------------------------------------
# Startup seed
# ---------------------------------------------------------------------------

def seed_from_config() -> None:
    """
    Insert all 30 canonical teams into team_registry if they don't exist yet.
    Pre-fills the odds_api_name and mlb_stats_name with the full official name
    since those sources always use "City Nickname" format.
    Safe to call on every startup — INSERT OR IGNORE preserves existing rows.
    """
    now = datetime.utcnow().isoformat()
    rows = []
    for t in MLB_TEAMS:
        full_name = f"{t.city} {t.name}"
        rows.append((
            t.key,
            t.city,
            t.name,
            t.abbreviation,
            t.division,
            full_name,    # odds_api_name  — official full name
            "",           # dk_name        — learned from first DK scrape
            full_name,    # mlb_stats_name — same official full name
            "",           # covers_name    — learned from first Covers scrape
            0,            # locked
            "",           # locked_at
            "",           # notes
            now,          # created_at
            now,          # updated_at
        ))

    try:
        with write_db() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO team_registry (
                    team_key, display_city, display_name, abbreviation, division,
                    odds_api_name, dk_name, mlb_stats_name, covers_name,
                    locked, locked_at, notes, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
        logger.info("TeamRegistry: seeded %d teams", len(rows))
    except Exception as exc:
        logger.error("TeamRegistry.seed_from_config failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Auto-population (called from team_resolver after a successful resolution)
# ---------------------------------------------------------------------------

def record_seen_name(raw: str, source: str, team_key: str) -> None:
    """
    Auto-populate the source-specific name column for a team the first time
    a name is observed from that source.

    Rules:
    - Only runs for known sources (odds_api / draftkings / mlb_stats_api / covers).
    - If the row is locked, nothing is written.
    - If the column is already non-empty, nothing is written (first-seen wins).
    - If team_key doesn't exist in the registry, nothing is written.
    """
    col = SOURCE_COLUMN.get(source)
    if not col:
        return  # weather / unknown source — no column for it

    raw_stripped = raw.strip()
    if not raw_stripped or not team_key:
        return

    try:
        with write_db() as conn:
            conn.execute(
                f"""
                UPDATE team_registry
                   SET {col} = ?,
                       updated_at = ?
                 WHERE team_key = ?
                   AND locked = 0
                   AND ({col} = '' OR {col} IS NULL)
                """,
                (raw_stripped, datetime.utcnow().isoformat(), team_key),
            )
    except Exception as exc:
        logger.debug("TeamRegistry.record_seen_name failed for '%s': %s", raw, exc)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_all() -> list[dict]:
    """Return all 30 team rows ordered by division then team name."""
    try:
        with read_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM team_registry
                 ORDER BY division, display_city, display_name
                """
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("TeamRegistry.get_all failed: %s", exc)
        return []


def get_by_key(team_key: str) -> Optional[dict]:
    """Return a single team row or None."""
    try:
        with read_db() as conn:
            row = conn.execute(
                "SELECT * FROM team_registry WHERE team_key = ?",
                (team_key,),
            ).fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.error("TeamRegistry.get_by_key failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Writes (UI-driven)
# ---------------------------------------------------------------------------

def patch(team_key: str, updates: dict) -> dict:
    """
    UI-driven update — always writes regardless of locked state, then sets
    locked = 1 so the row is never overwritten programmatically afterwards.

    `updates` may contain any subset of VALID_PATCH_FIELDS.
    Returns the updated row as a dict.
    Raises ValueError for unknown fields or unknown team_key.
    """
    bad = set(updates) - VALID_PATCH_FIELDS
    if bad:
        raise ValueError(f"Unknown fields: {bad}. Allowed: {VALID_PATCH_FIELDS}")

    row = get_by_key(team_key)
    if row is None:
        raise ValueError(f"Unknown team_key: {team_key!r}")

    if not updates:
        return row

    now = datetime.utcnow().isoformat()
    set_clauses = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [now, now, team_key]

    try:
        with write_db() as conn:
            conn.execute(
                f"""
                UPDATE team_registry
                   SET {set_clauses},
                       locked = 1,
                       locked_at = ?,
                       updated_at = ?
                 WHERE team_key = ?
                """,
                values,
            )
    except Exception as exc:
        logger.error("TeamRegistry.patch failed for '%s': %s", team_key, exc)
        raise

    # Hot-reload the resolver so new names are picked up immediately
    _reload_resolver()

    updated = get_by_key(team_key)
    logger.info(
        "TeamRegistry: patched %s — locked=1  fields=%s",
        team_key, list(updates.keys()),
    )
    return updated


def set_locked(team_key: str, locked: bool) -> dict:
    """
    Toggle the lock flag without changing any name columns.
    Returns the updated row.
    """
    row = get_by_key(team_key)
    if row is None:
        raise ValueError(f"Unknown team_key: {team_key!r}")

    now = datetime.utcnow().isoformat()
    try:
        with write_db() as conn:
            conn.execute(
                """
                UPDATE team_registry
                   SET locked = ?,
                       locked_at = ?,
                       updated_at = ?
                 WHERE team_key = ?
                """,
                (1 if locked else 0, now if locked else "", now, team_key),
            )
    except Exception as exc:
        logger.error("TeamRegistry.set_locked failed for '%s': %s", team_key, exc)
        raise

    logger.info("TeamRegistry: %s locked=%s", team_key, locked)
    return get_by_key(team_key)


# ---------------------------------------------------------------------------
# Resolver hot-reload helper
# ---------------------------------------------------------------------------

def _reload_resolver() -> None:
    """
    After a UI patch, rebuild the team_resolver runtime map so the new
    source names take effect immediately without restarting the server.
    Reads all non-empty source columns from team_registry and injects them.
    """
    try:
        from mlb import team_resolver
        rows = get_all()
        for row in rows:
            key = row["team_key"]
            for col, source in [
                ("odds_api_name",   "odds_api"),
                ("dk_name",         "draftkings"),
                ("mlb_stats_name",  "mlb_stats_api"),
                ("covers_name",     "covers"),
            ]:
                name = (row.get(col) or "").strip()
                if name:
                    team_resolver._runtime_map[name.lower()] = key
        logger.debug("TeamRegistry: resolver map hot-reloaded (%d teams)", len(rows))
    except Exception as exc:
        logger.warning("TeamRegistry._reload_resolver failed: %s", exc)
