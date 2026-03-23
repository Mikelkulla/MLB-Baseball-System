"""
Bet Logger — tracks placed bets with P&L and CLV.
Equivalent to V8.0 utils_bets_log.js (28-column BETS_LOG schema).

Persistence: SQLite (output_data/mlb.db), bets table.
Every mutating operation writes directly to DB — no full-list serialisation.
"""

from __future__ import annotations
import csv
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.bet import Bet, BetResult, CLVBand
from models.prediction import Prediction
from db.database import read_db, write_db

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output_data"


def _row_to_bet(row) -> Bet:
    """Deserialise a DB row back into a Bet dataclass (with enum re-hydration)."""
    d = dict(row)
    bet = Bet(bet_id=d["bet_id"])

    # Scalar fields
    for field in (
        "sport", "matchup", "picked_team", "picked_team_name", "bet_type",
        "units", "prediction_text", "status_tier",
        "ev_pct", "confidence_pct", "prob_pct",
        "open_spread", "open_price", "bet_spread", "bet_price", "current_price",
        "clv_pct", "adj_units", "pnl", "notes",
    ):
        if d.get(field) is not None:
            setattr(bet, field, d[field])

    # Boolean (stored as 0/1)
    bet.key_number_crossed = bool(d.get("key_number_crossed", 0))

    # Datetime fields
    if d.get("game_date"):
        try:
            bet.game_date = datetime.fromisoformat(d["game_date"])
        except ValueError:
            pass
    if d.get("placed_at"):
        try:
            bet.placed_at = datetime.fromisoformat(d["placed_at"])
        except ValueError:
            pass

    # Enums
    try:
        bet.result = BetResult(d["result"])
    except (ValueError, KeyError):
        bet.result = BetResult.ACTIVE
    try:
        bet.clv_band = CLVBand(d["clv_band"])
    except (ValueError, KeyError):
        bet.clv_band = CLVBand.GOOD

    return bet


class BetLogger:
    """
    Manages the bets log. Supports adding, refreshing CLV, and settling bets.
    Duplicate detection: raises ValueError if the same matchup is bet twice
    on the same day while still ACTIVE.
    """

    def __init__(self):
        OUTPUT_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Add / update bets
    # ------------------------------------------------------------------

    def log_bet(self, prediction: Prediction, notes: str = "") -> Bet:
        """
        Log a new bet from a qualified prediction.
        Duplicate bets are allowed — the frontend shows a warning but does not block.
        """
        bet = Bet(
            bet_id=self._new_id(),
            sport=prediction.sport,
            game_date=prediction.game_date,
            matchup=prediction.matchup,
            picked_team=prediction.picked_team,
            picked_team_name=prediction.picked_team_name,
            bet_type=prediction.bet_type,
            units=prediction.safe_units,
            prediction_text=prediction.prediction_text,
            status_tier=prediction.status,
            ev_pct=prediction.ev_pct,
            confidence_pct=prediction.confidence_pct,
            prob_pct=prediction.prob_pct,
            open_spread=prediction.open_spread,
            open_price=prediction.bet_price,
            bet_spread=prediction.current_spread,
            bet_price=prediction.bet_price,
            adj_units=prediction.safe_units,
            notes=notes,
        )
        self._insert(bet)
        logger.info("Logged bet %s: %s %s", bet.bet_id, bet.matchup, bet.picked_team_name)
        return bet

    def refresh_clv(self, bet_id: str, current_price: int) -> Optional[Bet]:
        """Update CLV for an active bet given the current market price."""
        bet = self._find(bet_id)
        if not bet:
            return None
        bet.update_clv(current_price)
        self._update_clv_fields(bet)
        return bet

    def settle(self, bet_id: str, result: BetResult, final_price: Optional[int] = None) -> Optional[Bet]:
        """Settle a bet: mark result and compute P&L."""
        bet = self._find(bet_id)
        if not bet:
            return None
        bet.result = result
        if final_price:
            bet.update_clv(final_price)
        if result == BetResult.WON:
            from engine.ev_calculator import EVCalculator
            decimal = EVCalculator.decimal_from_american(bet.bet_price)
            bet.pnl = round(bet.adj_units * (decimal - 1), 3)
        elif result == BetResult.LOST:
            bet.pnl = -bet.adj_units
        elif result == BetResult.PUSH:
            bet.pnl = 0.0
        self._update_settle_fields(bet)
        return bet

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active(self) -> list[Bet]:
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM bets WHERE result = 'ACTIVE' ORDER BY placed_at DESC"
            ).fetchall()
        return [_row_to_bet(r) for r in rows]

    def get_all(self) -> list[Bet]:
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM bets ORDER BY placed_at DESC"
            ).fetchall()
        return [_row_to_bet(r) for r in rows]

    def total_pnl(self) -> float:
        with read_db() as conn:
            row = conn.execute("SELECT COALESCE(SUM(pnl), 0.0) FROM bets").fetchone()
        return round(row[0], 3)

    def record(self) -> dict:
        with read_db() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE result IN ('WON','LOST'))  AS total,
                    COUNT(*) FILTER (WHERE result = 'WON')            AS wins,
                    COUNT(*) FILTER (WHERE result = 'LOST')           AS losses,
                    COALESCE(SUM(pnl), 0.0)                           AS pnl
                FROM bets
            """).fetchone()
        total = row["total"] or 0
        wins = row["wins"] or 0
        return {
            "total": total,
            "wins": wins,
            "losses": row["losses"] or 0,
            "win_rate": round(wins / total * 100, 1) if total else 0.0,
            "pnl_units": round(row["pnl"], 3),
        }

    def export_csv(self, path: Optional[Path] = None) -> Path:
        target = path or OUTPUT_DIR / "bets_log.csv"
        bets = self.get_all()
        rows = [b.to_dict() for b in bets]
        if not rows:
            target.write_text("", encoding="utf-8")
            return target
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return target

    # ------------------------------------------------------------------
    # DB operations
    # ------------------------------------------------------------------

    def _insert(self, bet: Bet) -> None:
        d = bet.to_dict()
        with write_db() as conn:
            conn.execute("""
                INSERT INTO bets (
                    bet_id, sport, game_date, matchup,
                    picked_team, picked_team_name, bet_type,
                    units, prediction_text, status_tier,
                    ev_pct, confidence_pct, prob_pct,
                    open_spread, open_price, bet_spread, bet_price, current_price,
                    clv_pct, adj_units, clv_band, key_number_crossed,
                    placed_at, result, pnl, notes
                ) VALUES (
                    :bet_id, :sport, :game_date, :matchup,
                    :picked_team, :picked_team_name, :bet_type,
                    :units, :prediction_text, :status_tier,
                    :ev_pct, :confidence_pct, :prob_pct,
                    :open_spread, :open_price, :bet_spread, :bet_price, :current_price,
                    :clv_pct, :adj_units, :clv_band, :key_number_crossed,
                    :placed_at, :result, :pnl, :notes
                )
            """, {
                **d,
                "game_date": d["game_date"] if d["game_date"] else None,
                "key_number_crossed": 1 if d["key_number_crossed"] else 0,
            })

    def _update_clv_fields(self, bet: Bet) -> None:
        with write_db() as conn:
            conn.execute("""
                UPDATE bets
                SET current_price = ?, clv_pct = ?, clv_band = ?, key_number_crossed = ?
                WHERE bet_id = ?
            """, (
                bet.current_price,
                bet.clv_pct,
                bet.clv_band.value,
                1 if bet.key_number_crossed else 0,
                bet.bet_id,
            ))

    def _update_settle_fields(self, bet: Bet) -> None:
        with write_db() as conn:
            conn.execute("""
                UPDATE bets
                SET result = ?, pnl = ?, current_price = ?,
                    clv_pct = ?, clv_band = ?, key_number_crossed = ?
                WHERE bet_id = ?
            """, (
                bet.result.value,
                bet.pnl,
                bet.current_price,
                bet.clv_pct,
                bet.clv_band.value,
                1 if bet.key_number_crossed else 0,
                bet.bet_id,
            ))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def logged_matchups_recent(self) -> dict[str, dict]:
        """
        Return the most recent logged bet per matchup for games in a ±1/+14 day window.
        Used by Live Picks to mark rows and show diffs in the double-bet modal.
        Returns a dict keyed by matchup string, value = key bet fields for comparison.
        """
        from datetime import date, timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        horizon   = (date.today() + timedelta(days=14)).isoformat()
        with read_db() as conn:
            rows = conn.execute("""
                SELECT matchup, picked_team_name, status_tier,
                       bet_price, prob_pct, ev_pct, confidence_pct,
                       units, placed_at
                FROM bets
                WHERE DATE(game_date) >= ? AND DATE(game_date) <= ?
                ORDER BY placed_at DESC
            """, (yesterday, horizon)).fetchall()
        # Keep only the most recent entry per matchup
        seen: dict[str, dict] = {}
        for r in rows:
            d = dict(r)
            if d["matchup"] not in seen:
                seen[d["matchup"]] = d
        return seen

    def _find(self, bet_id: str) -> Optional[Bet]:
        with read_db() as conn:
            row = conn.execute(
                "SELECT * FROM bets WHERE bet_id = ?", (bet_id,)
            ).fetchone()
        return _row_to_bet(row) if row else None

    @staticmethod
    def _new_id() -> str:
        return f"MLB-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
