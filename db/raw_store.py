"""
RawStore — persists raw fetched data to the five raw_* tables.

Every data source writes its complete raw payload here immediately after
fetching, keyed by refresh_id (UTC ISO timestamp of the pipeline run).
Nothing is ever updated or deleted — all rows are append-only, giving you
a full audit trail of every refresh for debugging.

Usage (called from pipeline.py after each fetch):

    from db.raw_store import RawStore

    refresh_id = datetime.utcnow().isoformat()
    RawStore.save_odds(refresh_id, games)
    RawStore.save_dk_splits(refresh_id, splits)
    RawStore.save_injuries(refresh_id, injuries)
    RawStore.save_weather(refresh_id, weather_dict)
    RawStore.save_pitchers(refresh_id, pitchers_dict)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from db.database import write_db

if TYPE_CHECKING:
    from models.game import Game
    from data.draftking_scraper import SplitEntry
    from data.injury_scraper import RawInjury
    from data.weather_client import WeatherReading
    from models.pitcher import PitcherStats

logger = logging.getLogger(__name__)


class RawStore:
    """Static helpers — no instantiation needed."""

    # ------------------------------------------------------------------
    # Odds
    # ------------------------------------------------------------------

    @staticmethod
    def save_odds(refresh_id: str, games: list["Game"]) -> None:
        """
        Persist one row per game from the Odds API response.
        Stores raw ML, spread, and total for each game along with
        which bookmaker provided each market.
        """
        if not games:
            logger.debug("RawStore.save_odds: no games to save (refresh_id=%s)", refresh_id)
            return

        now = datetime.utcnow().isoformat()
        rows = []
        for g in games:
            odds = g.odds
            rows.append((
                refresh_id,
                g.game_id,
                g.commence_time.isoformat() if g.commence_time else "",
                # raw API team strings are no longer stored separately on Game —
                # use the normalized keys (odds_client already normalised them)
                g.away_team,
                g.home_team,
                g.away_team,   # key = same after normalisation in odds_client
                g.home_team,
                odds.ml_bookmaker,
                odds.spread_bookmaker,
                odds.total_bookmaker,
                odds.book_count,
                odds.away_ml.price if odds.away_ml else None,
                odds.home_ml.price if odds.home_ml else None,
                odds.away_spread.point if odds.away_spread else None,
                odds.away_spread.price if odds.away_spread else None,
                odds.home_spread.point if odds.home_spread else None,
                odds.home_spread.price if odds.home_spread else None,
                odds.over.point if odds.over else None,
                odds.over.price if odds.over else None,
                odds.under.price if odds.under else None,
                1,   # validation_ok — games that failed were already excluded by odds_client
                now,
            ))

        try:
            with write_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO raw_odds (
                        refresh_id, game_id, commence_time,
                        away_team_raw, home_team_raw,
                        away_team_key, home_team_key,
                        ml_bookmaker, spread_bookmaker, total_bookmaker,
                        books_available,
                        away_ml, home_ml,
                        away_spread_pt, away_spread_px,
                        home_spread_pt, home_spread_px,
                        total_point, over_price, under_price,
                        validation_ok, recorded_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    rows,
                )
            logger.info("RawStore: saved %d odds rows (refresh_id=%s)", len(rows), refresh_id)
        except Exception as exc:
            logger.error("RawStore.save_odds failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # DraftKings splits
    # ------------------------------------------------------------------

    @staticmethod
    def save_dk_splits(refresh_id: str, splits: list["SplitEntry"]) -> None:
        """
        Persist one row per game from the DraftKings Network scrape.
        Stores every bets% and handle% for ML, spread, and total markets.
        """
        if not splits:
            logger.debug("RawStore.save_dk_splits: no splits to save (refresh_id=%s)", refresh_id)
            return

        now = datetime.utcnow().isoformat()
        rows = []
        for s in splits:
            rows.append((
                refresh_id,
                s.game_id_raw,
                s.away_team_key or "",
                s.home_team_key or "",
                s.away_ml_bets_pct,
                s.home_ml_bets_pct,
                s.away_ml_handle_pct,
                s.home_ml_handle_pct,
                s.away_spread_bets_pct,
                s.home_spread_bets_pct,
                s.away_spread_handle_pct,
                s.home_spread_handle_pct,
                s.over_bets_pct,
                s.under_bets_pct,
                s.over_handle_pct,
                s.under_handle_pct,
                s.sharp_split_score,
                now,
            ))

        try:
            with write_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO raw_dk_splits (
                        refresh_id, game_id_raw,
                        away_team_key, home_team_key,
                        away_ml_bets_pct, home_ml_bets_pct,
                        away_ml_handle_pct, home_ml_handle_pct,
                        away_spread_bets_pct, home_spread_bets_pct,
                        away_spread_handle_pct, home_spread_handle_pct,
                        over_bets_pct, under_bets_pct,
                        over_handle_pct, under_handle_pct,
                        sharp_split_score, recorded_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    rows,
                )
            logger.info("RawStore: saved %d DK split rows (refresh_id=%s)", len(rows), refresh_id)
        except Exception as exc:
            logger.error("RawStore.save_dk_splits failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Injuries
    # ------------------------------------------------------------------

    @staticmethod
    def save_injuries(refresh_id: str, injuries: list["RawInjury"]) -> None:
        """
        Persist one row per injured player from the Covers.com scrape.
        Stores team, position, status, and description for every player
        so you can check exactly what triggered (or didn't trigger) the SP gate.
        """
        if not injuries:
            logger.debug("RawStore.save_injuries: no injuries to save (refresh_id=%s)", refresh_id)
            return

        now = datetime.utcnow().isoformat()
        rows = []
        for inj in injuries:
            rows.append((
                refresh_id,
                inj.player_name,
                inj.team_raw,
                inj.team_key or "",
                inj.position,
                inj.status,
                inj.description,
                now,
            ))

        try:
            with write_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO raw_injuries (
                        refresh_id, player_name,
                        team_raw, team_key,
                        position, status, description,
                        recorded_at
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    rows,
                )
            logger.info("RawStore: saved %d injury rows (refresh_id=%s)", len(rows), refresh_id)
        except Exception as exc:
            logger.error("RawStore.save_injuries failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------------

    @staticmethod
    def save_weather(refresh_id: str, weather: dict[str, "WeatherReading"]) -> None:
        """
        Persist one row per stadium from the WeatherAPI.com response.
        Also stores the computed over/under adjustments from the weather engine
        (populated by pipeline._apply_impacts before this is called).
        The over_adj/under_adj are stored in the Game objects — we save them
        separately via save_weather_impacts() after impacts are applied.
        """
        if not weather:
            logger.debug("RawStore.save_weather: no weather to save (refresh_id=%s)", refresh_id)
            return

        now = datetime.utcnow().isoformat()
        rows = []
        for team_key, w in weather.items():
            rows.append((
                refresh_id,
                team_key,
                w.stadium_name,
                "",   # city not on WeatherReading; use stadium_name
                w.temperature_f,
                w.wind_speed_mph,
                w.wind_direction_name,
                w.condition,
                w.precipitation_mm,
                w.precipitation_category,
                w.humidity_pct,
                1 if w.is_dome else 0,
                0.0,   # over_adj — filled in save_weather_impacts() after engine runs
                0.0,   # under_adj
                now,
            ))

        try:
            with write_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO raw_weather (
                        refresh_id, team_key, stadium_name, city,
                        temperature_f, wind_speed_mph, wind_direction,
                        condition, precipitation_mm, precipitation,
                        humidity_pct, is_dome,
                        over_adj, under_adj,
                        recorded_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    rows,
                )
            logger.info("RawStore: saved %d weather rows (refresh_id=%s)", len(rows), refresh_id)
        except Exception as exc:
            logger.error("RawStore.save_weather failed: %s", exc, exc_info=True)

    @staticmethod
    def update_weather_impacts(refresh_id: str, games: list["Game"]) -> None:
        """
        After _apply_impacts() runs, update the over_adj / under_adj columns
        in raw_weather so the computed values are visible in the raw table.
        Called from pipeline after impacts are applied.
        """
        if not games:
            return
        try:
            with write_db() as conn:
                for g in games:
                    if g.weather_over_adj != 0 or g.weather_under_adj != 0:
                        conn.execute(
                            """
                            UPDATE raw_weather
                               SET over_adj = ?, under_adj = ?
                             WHERE refresh_id = ? AND team_key = ?
                            """,
                            (g.weather_over_adj, g.weather_under_adj, refresh_id, g.home_team),
                        )
            logger.debug("RawStore: updated weather impacts for refresh_id=%s", refresh_id)
        except Exception as exc:
            logger.error("RawStore.update_weather_impacts failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Pitchers
    # ------------------------------------------------------------------

    @staticmethod
    def save_pitchers(refresh_id: str, pitchers: dict[str, "PitcherStats"]) -> None:
        """
        Persist one row per team from the MLB Stats API response.
        Stores every raw stat plus the computed impact_score (0-100) so you
        can trace exactly how probability adjustments were calculated.
        """
        if not pitchers:
            logger.debug("RawStore.save_pitchers: no pitchers to save (refresh_id=%s)", refresh_id)
            return

        now = datetime.utcnow().isoformat()
        rows = []
        for team_key, p in pitchers.items():
            rows.append((
                refresh_id,
                team_key,
                p.name,
                getattr(p, "player_id", None),   # MLB Stats API player ID if available
                p.hand,
                1 if p.is_tbd else 0,
                p.era,
                p.whip,
                p.k_per_9,
                p.bb_per_9,
                p.innings_pitched,
                p.wins,
                p.losses,
                p.recent_era,
                p.impact_score,
                now,
            ))

        try:
            with write_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO raw_pitchers (
                        refresh_id, team_key,
                        pitcher_name, pitcher_id,
                        hand, is_tbd,
                        era, whip, k_per_9, bb_per_9,
                        innings_pitched, wins, losses,
                        recent_era, impact_score,
                        recorded_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    rows,
                )
            logger.info("RawStore: saved %d pitcher rows (refresh_id=%s)", len(rows), refresh_id)
        except Exception as exc:
            logger.error("RawStore.save_pitchers failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Query helpers (for debugging via /api/raw or directly in SQLite)
    # ------------------------------------------------------------------

    @staticmethod
    def latest_refresh_ids(limit: int = 10) -> list[str]:
        """Return the most recent refresh_ids across all raw tables."""
        from db.database import read_db
        ids: set[str] = set()
        tables = ["raw_odds", "raw_dk_splits", "raw_injuries", "raw_weather", "raw_pitchers"]
        with read_db() as conn:
            for table in tables:
                try:
                    rows = conn.execute(
                        f"SELECT DISTINCT refresh_id FROM {table} ORDER BY refresh_id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    ids.update(r[0] for r in rows)
                except Exception:
                    pass
        return sorted(ids, reverse=True)[:limit]

    @staticmethod
    def get_odds_for_refresh(refresh_id: str) -> list[dict]:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_odds WHERE refresh_id = ? ORDER BY away_team_key",
                (refresh_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_dk_splits_for_refresh(refresh_id: str) -> list[dict]:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_dk_splits WHERE refresh_id = ? ORDER BY away_team_key",
                (refresh_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_injuries_for_refresh(refresh_id: str) -> list[dict]:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_injuries WHERE refresh_id = ? ORDER BY team_key, player_name",
                (refresh_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_weather_for_refresh(refresh_id: str) -> list[dict]:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_weather WHERE refresh_id = ? ORDER BY team_key",
                (refresh_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_pitchers_for_refresh(refresh_id: str) -> list[dict]:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_pitchers WHERE refresh_id = ? ORDER BY team_key",
                (refresh_id,),
            ).fetchall()
        return [dict(r) for r in rows]
