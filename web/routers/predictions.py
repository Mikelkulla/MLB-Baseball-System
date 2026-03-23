from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, HTTPException
from output.predictions import LivePredictions
from web.state import get_pipeline

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("")
def get_predictions(tier: str | None = None):
    data = LivePredictions.query_today_qualified(tier=tier)
    return {"predictions": data, "count": len(data), "refreshed_at": datetime.utcnow().isoformat()}


@router.get("/model")
def get_model(tier: str | None = None, search: str | None = None):
    """All games with all metrics — equivalent to V8.0 NBA_Model sheet."""
    data = LivePredictions.query_today_model(tier=tier, search=search)
    return {
        "model": data,
        "count": len(data),
        "picks": sum(1 for p in data if p.get("status") != "PASS"),
        "refreshed_at": datetime.utcnow().isoformat(),
    }


@router.post("/refresh")
def refresh_predictions():
    """Trigger a full pipeline refresh."""
    try:
        pipe = get_pipeline()
        picks = pipe.run_full_refresh()
        return {"success": True, "count": len(picks), "refreshed_at": datetime.utcnow().isoformat()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/refresh/odds")
def refresh_odds_only():
    pipe = get_pipeline()
    pipe.refresh_odds()
    pipe.update_live_predictions()
    return {"success": True}


@router.post("/refresh/pitchers")
def refresh_pitchers_only():
    pipe = get_pipeline()
    pipe.refresh_pitchers()
    pipe.update_live_predictions()
    return {"success": True}
