"""
Team alias management + team registry API.

Alias endpoints:
  GET  /api/teams/aliases            — all DB alias entries (resolved + unresolved)
  GET  /api/teams/aliases/unresolved — names that failed resolution and need review
  POST /api/teams/aliases            — manually confirm or add an alias
  POST /api/teams/aliases/reload     — hot-reload DB aliases into runtime map
  GET  /api/teams/resolve?name=X     — test-resolve a raw name string

Registry endpoints (team_registry table — one row per canonical team):
  GET   /api/teams/registry                      — all 30 team rows
  PATCH /api/teams/registry/{team_key}           — update source name columns, sets locked=1
  POST  /api/teams/registry/{team_key}/lock      — toggle lock flag (body: {"locked": true/false})
  POST  /api/teams/registry/reload               — hot-reload resolver from registry values
"""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mlb import team_resolver
from config.mlb_config import TEAM_BY_KEY
import db.team_registry as team_registry_db

router = APIRouter(prefix="/api/teams", tags=["teams"])


class AliasRequest(BaseModel):
    raw_name: str
    canonical_key: str


@router.get("/aliases")
def get_all_aliases(limit: int = 500):
    """All logged alias entries, most recent first."""
    return {
        "aliases": team_resolver.get_all_aliases(limit=limit),
        "total_canonical_teams": len(TEAM_BY_KEY),
    }


@router.get("/aliases/unresolved")
def get_unresolved(limit: int = 100):
    """Names that could not be resolved — need manual review."""
    items = team_resolver.get_unresolved(limit=limit)
    return {
        "unresolved": items,
        "count": len(items),
        "hint": "POST /api/teams/aliases with raw_name + canonical_key to fix",
    }


@router.post("/aliases")
def add_alias(req: AliasRequest):
    """Manually confirm an alias mapping (persisted to DB, hot-reloaded immediately)."""
    if req.canonical_key not in TEAM_BY_KEY:
        valid = sorted(TEAM_BY_KEY.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Unknown canonical key '{req.canonical_key}'. Valid keys: {valid}",
        )
    team_resolver.add_alias(req.raw_name, req.canonical_key)
    return {
        "success": True,
        "raw_name": req.raw_name,
        "canonical_key": req.canonical_key,
        "team": TEAM_BY_KEY[req.canonical_key].city + " " + TEAM_BY_KEY[req.canonical_key].name,
    }


@router.post("/aliases/reload")
def reload_aliases():
    """Hot-reload all DB aliases into the runtime map (useful after bulk DB edits)."""
    team_resolver.reload_from_db()
    return {"success": True, "message": "Runtime alias map reloaded from DB"}


@router.get("/resolve")
def test_resolve(name: str):
    """Test-resolve a raw team name string and show what it maps to."""
    key = team_resolver.resolve(name, source="api_test")
    team = TEAM_BY_KEY.get(key) if key else None
    return {
        "raw_name": name,
        "resolved_key": key,
        "team": f"{team.city} {team.name}" if team else None,
        "resolved": key is not None,
    }


# ── Registry endpoints ────────────────────────────────────────────────────────

class RegistryPatchRequest(BaseModel):
    odds_api_name: Optional[str] = None
    dk_name: Optional[str] = None
    mlb_stats_name: Optional[str] = None
    covers_name: Optional[str] = None
    notes: Optional[str] = None


class LockRequest(BaseModel):
    locked: bool


@router.get("/registry")
def get_registry():
    """All 30 canonical team rows, ordered by division then city."""
    rows = team_registry_db.get_all()
    return {"teams": rows, "count": len(rows)}


@router.patch("/registry/{team_key}")
def patch_registry(team_key: str, req: RegistryPatchRequest):
    """
    Update one or more source-name columns for a team.
    Always sets locked=1 so the row is protected from programmatic overwrites.
    Hot-reloads the resolver immediately.
    """
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    try:
        updated = team_registry_db.patch(team_key, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "team": updated}


@router.post("/registry/{team_key}/lock")
def set_lock(team_key: str, req: LockRequest):
    """
    Toggle the lock flag for a team row.
    locked=true  → only UI can change source names.
    locked=false → programmatic auto-population is re-enabled.
    """
    try:
        updated = team_registry_db.set_locked(team_key, req.locked)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "team": updated}


@router.post("/registry/reload")
def reload_registry():
    """
    Inject all non-empty registry source names into the runtime resolver map.
    Equivalent to the hot-reload that happens automatically after a PATCH.
    """
    from db.team_registry import _reload_resolver
    _reload_resolver()
    return {"success": True, "message": "Resolver reloaded from team_registry"}
