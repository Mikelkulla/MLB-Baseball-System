"""
CLV (Closing Line Value) tracker.
Records opening and current odds for every tracked game, computing line movement.
Equivalent to V8.0 CLV_Tracker + CLV_History sheets.

Persistence: SQLite (output_data/mlb.db), clv_history table.
record_opening() inserts a new row the first time a game_id is seen.
update_current() updates existing rows in-place.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from models.game import Game
from db.database import read_db, write_db

logger = logging.getLogger(__name__)


@dataclass
class CLVRecord:
    game_id: str
    matchup: str
    sport: str = "baseball_mlb"
    # Away spread
    away_spread_open: Optional[float] = None
    away_spread_current: Optional[float] = None
    away_spread_delta: Optional[float] = None
    # Home spread
    home_spread_open: Optional[float] = None
    home_spread_current: Optional[float] = None
    home_spread_delta: Optional[float] = None
    # ML
    away_ml_open: Optional[int] = None
    away_ml_current: Optional[int] = None
    home_ml_open: Optional[int] = None
    home_ml_current: Optional[int] = None
    # Timestamps
    recorded_at: str = ""
    closed_at: str = ""
    is_closed: bool = False


def _row_to_record(row) -> CLVRecord:
    d = dict(row)
    return CLVRecord(
        game_id=d["game_id"],
        matchup=d["matchup"],
        sport=d["sport"],
        away_spread_open=d.get("away_spread_open"),
        away_spread_current=d.get("away_spread_current"),
        away_spread_delta=d.get("away_spread_delta"),
        home_spread_open=d.get("home_spread_open"),
        home_spread_current=d.get("home_spread_current"),
        home_spread_delta=d.get("home_spread_delta"),
        away_ml_open=d.get("away_ml_open"),
        away_ml_current=d.get("away_ml_current"),
        home_ml_open=d.get("home_ml_open"),
        home_ml_current=d.get("home_ml_current"),
        recorded_at=d.get("recorded_at") or "",
        closed_at=d.get("closed_at") or "",
        is_closed=bool(d.get("is_closed", 0)),
    )


class CLVTracker:
    """
    Maintains opening lines and current lines for all tracked games.
    Computes line movement (CLV delta) to feed into ConfidenceEngine.
    All state is persisted in the DB; no in-memory dict is kept between
    pipeline phases (DB queries are fast at the scale of MLB game counts).
    """

    def record_opening(self, game: Game) -> None:
        """Insert opening line for a game if not already tracked."""
        # Check if already exists
        with read_db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM clv_history WHERE game_id = ?", (game.game_id,)
            ).fetchone()
        if exists:
            logger.debug(
                "CLVTracker.record_opening: game_id=%s already tracked — skipping",
                game.game_id,
            )
            return  # Already have opening line; do not overwrite

        away_name = game.away_team
        home_name = game.home_team

        away_spread_open = game.odds.away_spread.point if game.odds.away_spread else None
        home_spread_open = game.odds.home_spread.point if game.odds.home_spread else None
        away_ml_open = game.odds.away_ml.price if game.odds.away_ml else None
        home_ml_open = game.odds.home_ml.price if game.odds.home_ml else None

        logger.info(
            "CLVTracker: NEW game tracked [%s @ %s] game_id=%s  "
            "Opening: away_spread=%s  home_spread=%s  away_ml=%s  home_ml=%s",
            away_name, home_name, game.game_id,
            away_spread_open, home_spread_open, away_ml_open, home_ml_open,
        )

        # Sync opening lines back onto the Game object so the engine can use them
        if away_spread_open is not None:
            game.odds.away_spread_open = away_spread_open
        if home_spread_open is not None:
            game.odds.home_spread_open = home_spread_open
        if away_ml_open is not None:
            game.odds.away_ml_open = away_ml_open
        if home_ml_open is not None:
            game.odds.home_ml_open = home_ml_open

        with write_db() as conn:
            conn.execute("""
                INSERT INTO clv_history (
                    game_id, matchup, sport,
                    away_spread_open, home_spread_open,
                    away_ml_open, home_ml_open,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game.game_id,
                f"{away_name} vs {home_name}",
                "baseball_mlb",
                away_spread_open, home_spread_open,
                away_ml_open, home_ml_open,
                datetime.utcnow().isoformat(),
            ))

    def update_current(self, game: Game) -> None:
        """Update current lines and recompute deltas; inserts opening if first seen."""
        with read_db() as conn:
            row = conn.execute(
                "SELECT * FROM clv_history WHERE game_id = ?", (game.game_id,)
            ).fetchone()

        if not row:
            logger.debug(
                "CLVTracker.update_current: game_id=%s not in DB — recording as new opening",
                game.game_id,
            )
            self.record_opening(game)
            return

        record = _row_to_record(row)

        # Current lines from game object
        away_spread_current = game.odds.away_spread.point if game.odds.away_spread else None
        home_spread_current = game.odds.home_spread.point if game.odds.home_spread else None
        away_ml_current = game.odds.away_ml.price if game.odds.away_ml else None
        home_ml_current = game.odds.home_ml.price if game.odds.home_ml else None

        # Compute deltas (open − current, positive = line moved toward us)
        away_spread_delta = None
        if record.away_spread_open is not None and away_spread_current is not None:
            away_spread_delta = round(record.away_spread_open - away_spread_current, 2)

        home_spread_delta = None
        if record.home_spread_open is not None and home_spread_current is not None:
            home_spread_delta = round(record.home_spread_open - home_spread_current, 2)

        logger.debug(
            "CLVTracker.update_current [%s]: "
            "away_spread open=%s → current=%s Δ=%s  "
            "home_spread open=%s → current=%s Δ=%s  "
            "away_ml open=%s → current=%s  "
            "home_ml open=%s → current=%s",
            game.game_id,
            record.away_spread_open, away_spread_current, away_spread_delta,
            record.home_spread_open, home_spread_current, home_spread_delta,
            record.away_ml_open, away_ml_current,
            record.home_ml_open, home_ml_current,
        )

        if away_spread_delta and abs(away_spread_delta) >= 0.5:
            logger.info(
                "CLVTracker: LINE MOVEMENT [%s] away spread %+.1f → %+.1f (Δ%+.1f)",
                game.game_id,
                record.away_spread_open, away_spread_current, away_spread_delta,
            )
        if home_spread_delta and abs(home_spread_delta) >= 0.5:
            logger.info(
                "CLVTracker: LINE MOVEMENT [%s] home spread %+.1f → %+.1f (Δ%+.1f)",
                game.game_id,
                record.home_spread_open, home_spread_current, home_spread_delta,
            )

        with write_db() as conn:
            conn.execute("""
                UPDATE clv_history SET
                    away_spread_current = ?,
                    away_spread_delta   = ?,
                    home_spread_current = ?,
                    home_spread_delta   = ?,
                    away_ml_current     = ?,
                    home_ml_current     = ?
                WHERE game_id = ?
            """, (
                away_spread_current, away_spread_delta,
                home_spread_current, home_spread_delta,
                away_ml_current, home_ml_current,
                game.game_id,
            ))

        # Sync opening lines back onto Game so the engine can use them
        game.odds.away_spread_open = record.away_spread_open
        game.odds.home_spread_open = record.home_spread_open
        game.odds.away_ml_open = record.away_ml_open
        game.odds.home_ml_open = record.home_ml_open

    def get_clv_delta(self, game_id: str, side: str) -> float:
        """Return the spread delta for a side ('away' or 'home')."""
        with read_db() as conn:
            row = conn.execute(
                "SELECT away_spread_delta, home_spread_delta FROM clv_history WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        if not row:
            logger.debug("CLVTracker.get_clv_delta: game_id=%s not found — returning 0.0", game_id)
            return 0.0
        col = "away_spread_delta" if side == "away" else "home_spread_delta"
        val = row[col]
        result = val if val is not None else 0.0
        logger.debug(
            "CLVTracker.get_clv_delta: game_id=%s  side=%s  delta=%+.2f",
            game_id, side, result,
        )
        return result

    def get_history(self) -> list[CLVRecord]:
        with read_db() as conn:
            rows = conn.execute("SELECT * FROM clv_history ORDER BY recorded_at DESC").fetchall()
        logger.debug("CLVTracker.get_history: returning %d records", len(rows))
        return [_row_to_record(r) for r in rows]
