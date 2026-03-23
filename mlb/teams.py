"""
Team name normalisation — public API shim.

All resolution logic lives in mlb/team_resolver.py.
This module preserves the legacy API so every import of
  from mlb.teams import normalize_team_name
continues to work unchanged.
"""

from __future__ import annotations
from typing import Optional

from config.mlb_config import MLB_TEAMS, TEAM_BY_KEY, TEAM_BY_ABBR, MLBTeam  # re-exported
from mlb import team_resolver


def normalize_team_name(raw: str, source: str = "unknown") -> Optional[str]:
    """
    Resolve any raw team name or abbreviation to its canonical team key.

    Resolution order:
      1. Exact alias lookup
      2. Nickname-only / token-scan
      3. Fuzzy match (difflib, threshold 0.82)
      4. Log unknown to DB if unresolved

    Returns None if no confident match is found.
    """
    return team_resolver.resolve(raw, source=source)


def get_team(raw: str) -> Optional[MLBTeam]:
    """Convenience: normalize + return full MLBTeam object."""
    key = normalize_team_name(raw)
    return TEAM_BY_KEY.get(key) if key else None


def get_unmapped_names() -> list[str]:
    """Return all names that could not be resolved (from DB, for diagnostics)."""
    return [r["raw_name"] for r in team_resolver.get_unresolved()]


def add_alias(raw: str, canonical_key: str) -> None:
    """Manually confirm or add a team name alias (persisted to DB)."""
    team_resolver.add_alias(raw, canonical_key)


def reload_aliases() -> None:
    """Hot-reload DB aliases into the runtime map after bulk manual edits."""
    team_resolver.reload_from_db()
