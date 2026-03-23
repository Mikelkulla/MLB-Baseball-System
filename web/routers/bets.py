from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from web.state import get_pipeline

router = APIRouter(prefix="/api/bets", tags=["bets"])


def _get_logger():
    return get_pipeline().bet_logger


class LogBetRequest(BaseModel):
    game_id: str
    notes: str = ""


class SettleBetRequest(BaseModel):
    bet_id: str
    result: str   # WON, LOST, PUSH, VOID
    final_price: int | None = None


class RefreshCLVRequest(BaseModel):
    bet_id: str
    current_price: int


@router.get("/logged-matchups")
def logged_matchups():
    """
    Return logged bets for upcoming games (±1/+14 day window), keyed by matchup.
    Used by Live Picks to highlight rows and show a diff when double-logging.
    """
    bl = _get_logger()
    return {"bets": bl.logged_matchups_recent()}


@router.get("")
def get_bets(status: str | None = None):
    bl = _get_logger()
    bets = bl.get_all()
    if status and status.upper() != "ALL":
        bets = [b for b in bets if b.result.value == status.upper()]
    return {
        "bets": [b.to_dict() for b in bets],
        "count": len(bets),
        "record": bl.record(),
        "total_pnl": bl.total_pnl(),
    }


@router.post("/log")
def log_bet(req: LogBetRequest):
    """Log a bet from a qualified prediction by game_id (looked up from DB)."""
    from output.predictions import LivePredictions
    from models.prediction import Prediction
    from datetime import datetime as dt

    pred_raw = LivePredictions.query_by_game_id(req.game_id)
    if not pred_raw:
        raise HTTPException(status_code=404, detail=f"Prediction {req.game_id} not found")

    # Rebuild a lightweight Prediction object from the DB dict
    pred = Prediction(game_id=pred_raw["game_id"])
    for k, v in pred_raw.items():
        if hasattr(pred, k):
            try:
                setattr(pred, k, v)
            except Exception:
                pass
    if pred_raw.get("game_date"):
        try:
            pred.game_date = dt.fromisoformat(pred_raw["game_date"])
        except Exception:
            pass

    bet = _get_logger().log_bet(pred, notes=req.notes)
    return {"success": True, "bet": bet.to_dict()}


@router.post("/settle")
def settle_bet(req: SettleBetRequest):
    from models.bet import BetResult
    try:
        result_enum = BetResult(req.result.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid result: {req.result}")
    bet = _get_logger().settle(req.bet_id, result_enum, req.final_price)
    if not bet:
        raise HTTPException(status_code=404, detail=f"Bet {req.bet_id} not found")
    return {"success": True, "bet": bet.to_dict()}


@router.post("/refresh-clv")
def refresh_clv(req: RefreshCLVRequest):
    bet = _get_logger().refresh_clv(req.bet_id, req.current_price)
    if not bet:
        raise HTTPException(status_code=404, detail=f"Bet {req.bet_id} not found")
    return {"success": True, "bet": bet.to_dict()}


@router.get("/export")
def export_csv():
    from fastapi.responses import FileResponse
    path = _get_logger().export_csv()
    return FileResponse(str(path), media_type="text/csv", filename="mlb_bets.csv")
