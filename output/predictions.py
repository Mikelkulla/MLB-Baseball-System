"""
Live Predictions output — filters and persists qualified picks.
Equivalent to V8.0 get_live_predictions.js.

Persistence: SQLite (output_data/mlb.db), predictions table.
Each pipeline refresh UPSERTs all games so the table always reflects
the latest engine output; stale games from prior days are NOT deleted
(they remain queryable for analytics).
"""

from __future__ import annotations
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.prediction import Prediction
from db.database import read_db, write_db

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output_data"

# Columns in DB insertion order — keeps upsert statement readable
_COLUMNS = [
    "game_id", "sport", "game_date", "matchup",
    "picked_team", "picked_team_name", "bet_type",
    "away_ml", "home_ml", "away_spread", "home_spread", "total_line",
    "open_spread", "current_spread", "bet_price", "best_book", "book_count",
    "away_prob_pct", "home_prob_pct", "away_ev_pct", "home_ev_pct",
    "prob_pct", "ev_pct", "confidence_pct", "units", "status", "safe_units",
    "clv_delta", "sharp_split_score",
    "away_pitcher_name", "away_pitcher_score",
    "home_pitcher_name", "home_pitcher_score",
    "away_injury_impact", "home_injury_impact",
    "weather_over_adj", "weather_under_adj",
    "sp_gate_blocked", "prediction_text", "generated_at",
]

_PLACEHOLDERS = ", ".join("?" * len(_COLUMNS))
_COL_LIST = ", ".join(_COLUMNS)

_UPSERT_SQL = (
    f"INSERT OR REPLACE INTO predictions ({_COL_LIST}) VALUES ({_PLACEHOLDERS})"
)


def _prediction_to_row(p: Prediction) -> tuple:
    """Convert a Prediction dataclass to a tuple matching _COLUMNS order."""
    d = p.to_dict()
    return (
        d["game_id"], d["sport"],
        d["game_date"],  # already ISO string from to_dict()
        d["matchup"],
        d["picked_team"], d["picked_team_name"], d["bet_type"],
        d["away_ml"], d["home_ml"],
        d["away_spread"], d["home_spread"], d["total_line"],
        d.get("open_spread"), d.get("current_spread"),
        d["bet_price"], d["best_book"], d["book_count"],
        d["away_prob_pct"], d["home_prob_pct"],
        d["away_ev_pct"], d["home_ev_pct"],
        d["prob_pct"], d["ev_pct"], d["confidence_pct"],
        d["units"], d["status"], d["safe_units"],
        d["clv_delta"], d["sharp_split_score"],
        d["away_pitcher_name"], d["away_pitcher_score"],
        d["home_pitcher_name"], d["home_pitcher_score"],
        d["away_injury_impact"], d["home_injury_impact"],
        d["weather_over_adj"], d["weather_under_adj"],
        1 if d["sp_gate_blocked"] else 0,
        d["prediction_text"], d["generated_at"],
    )


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict with proper Python types."""
    d = dict(row)
    d["sp_gate_blocked"] = bool(d["sp_gate_blocked"])
    return d


class LivePredictions:
    """
    Manages the current set of qualified predictions and the full model.
    In-memory state is used by the pipeline during a refresh cycle;
    the DB is the authoritative persistent store queried by the API.
    """

    def __init__(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        self._predictions: list[Prediction] = []  # qualified picks only
        self._model: list[Prediction] = []         # all games (incl. PASS)

    # ------------------------------------------------------------------
    # In-memory updates (called during pipeline refresh)
    # ------------------------------------------------------------------

    def update(self, predictions: list[Prediction]) -> None:
        """Replace in-memory qualified picks (non-PASS)."""
        self._predictions = [p for p in predictions if p.is_qualified()]
        logger.info(
            "Live predictions updated: %d picks (%s)",
            len(self._predictions),
            ", ".join(p.status for p in self._predictions),
        )

    def get_all(self) -> list[Prediction]:
        return list(self._predictions)

    def get_by_tier(self, tier: str) -> list[Prediction]:
        return [p for p in self._predictions if p.status == tier]

    def get_model(self) -> list[Prediction]:
        """Return all games including PASS (the full model view)."""
        return list(self._model)

    # ------------------------------------------------------------------
    # DB persistence (replaces JSON/CSV file writes)
    # ------------------------------------------------------------------

    def save_to_db(self) -> None:
        """Persist qualified picks to DB (called after update())."""
        if not self._predictions:
            return
        rows = [_prediction_to_row(p) for p in self._predictions]
        with write_db() as conn:
            conn.executemany(_UPSERT_SQL, rows)
        logger.info("Saved %d qualified picks to DB", len(rows))

    def save_model_to_db(self, all_predictions: list[Prediction]) -> None:
        """
        Persist ALL game predictions (all tiers including PASS) to DB.
        This is the equivalent of the old mlb_model_YYYYMMDD.json file.
        """
        self._model = all_predictions
        if not all_predictions:
            return
        rows = [_prediction_to_row(p) for p in all_predictions]
        with write_db() as conn:
            conn.executemany(_UPSERT_SQL, rows)
        logger.info("Saved %d model rows to DB", len(rows))

    # ------------------------------------------------------------------
    # CSV export (optional convenience; not called by pipeline by default)
    # ------------------------------------------------------------------

    def export_csv(self, path: Optional[Path] = None) -> Path:
        """Export today's qualified picks to CSV from in-memory state."""
        target = path or OUTPUT_DIR / f"live_predictions_{_today()}.csv"
        if not self._predictions:
            target.write_text("", encoding="utf-8")
            return target
        rows = [p.to_dict() for p in self._predictions]
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Exported %d predictions to %s", len(rows), target)
        return target

    # ------------------------------------------------------------------
    # DB queries (used by API routers)
    # ------------------------------------------------------------------

    @staticmethod
    def query_today_qualified(tier: Optional[str] = None) -> list[dict]:
        """Return the most recent pipeline run's qualified (non-PASS) picks from DB."""
        sql = """
            SELECT * FROM predictions
            WHERE DATE(generated_at) = (
                SELECT DATE(MAX(generated_at)) FROM predictions
            )
              AND status != 'PASS'
              AND sp_gate_blocked = 0
        """
        params: list = []
        if tier:
            sql += " AND status = ?"
            params.append(tier.upper())
        sql += " ORDER BY confidence_pct DESC"
        with read_db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    @staticmethod
    def query_today_model(
        tier: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict]:
        """Return ALL game predictions from the most recent pipeline run (all tiers)."""
        sql = """
            SELECT * FROM predictions
            WHERE DATE(generated_at) = (
                SELECT DATE(MAX(generated_at)) FROM predictions
            )
        """
        params: list = []
        if tier:
            sql += " AND status = ?"
            params.append(tier.upper())
        if search:
            sql += " AND (LOWER(matchup) LIKE ? OR LOWER(picked_team_name) LIKE ?)"
            s = f"%{search.lower()}%"
            params += [s, s]
        sql += " ORDER BY confidence_pct DESC"
        with read_db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    @staticmethod
    def query_by_game_id(game_id: str) -> Optional[dict]:
        """Look up a single prediction by game_id (used by bet logger)."""
        with read_db() as conn:
            row = conn.execute(
                "SELECT * FROM predictions WHERE game_id = ?", (game_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Console summary (unchanged)
    # ------------------------------------------------------------------

    def print_summary(self) -> None:
        if not self._predictions:
            print("No qualified picks at this time.")
            return
        print(f"\n{'='*60}")
        print(f"  MLB LIVE PREDICTIONS — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*60}")
        for p in self._predictions:
            print(
                f"  [{p.status:10s}] {p.matchup:<35} "
                f"{p.picked_team_name:<25} ML {p.bet_price:+d}  "
                f"Conf: {p.confidence_pct:.1f}%  "
                f"EV: {p.ev_pct:+.1f}%  "
                f"Units: {p.safe_units}"
            )
        print(f"{'='*60}\n")


def _today() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def _today_date() -> str:
    """Return UTC date as YYYY-MM-DD for SQL DATE() comparison."""
    return datetime.utcnow().strftime("%Y-%m-%d")
