"""
MLBPipeline — orchestrates all phases for a full system refresh.
This is the Python equivalent of V8.0 Phase1.js + Phase2.js combined.

Phase 1:  Data collection (odds, injuries, weather, DK splits, pitchers)
Phase 1B: Impact calculations (injury, weather, pitcher)
Phase 2:  Prediction engine (probability, EV, confidence, tier)
Output:   Live predictions + persistent storage
"""

from __future__ import annotations
import logging
import time
from datetime import date, datetime
from typing import Optional

from data.odds_client import OddsClient
from data.injury_scraper import InjuryScraper, RawInjury
from data.weather_client import WeatherClient
from data.draftking_scraper import DraftKingsScraper, SplitEntry
from data.pitcher_client import PitcherClient
from data.bullpen_client import BullpenClient
from mlb.ballpark_factors import get_park_factor, park_ou_adjustment_display

from engine.injury_impact import InjuryImpactEngine, InjuredPlayer
from engine.weather_impact import WeatherImpactEngine
from engine.pitcher_impact import PitcherImpactEngine
from engine.bullpen_impact import BullpenImpactEngine
from engine.prediction_engine import PredictionEngine

from output.predictions import LivePredictions
from output.clv_tracker import CLVTracker
from output.bet_logger import BetLogger

from models.game import Game
from models.prediction import Prediction
from models.pitcher import PitcherStats
from models.bullpen import BullpenStats

from db.raw_store import RawStore

from utils.logger import FeedHealthMonitor, ScheduleLogger, FeedStatus

logger = logging.getLogger(__name__)


class MLBPipeline:
    """
    Stateful pipeline that holds the latest data for all modules.
    Each refresh method can run independently (mirrors V8.0 trigger structure).
    """

    def __init__(self):
        # Data clients
        self._odds_client = OddsClient()
        self._injury_scraper = InjuryScraper()
        self._weather_client = WeatherClient()
        self._dk_scraper = DraftKingsScraper()
        self._pitcher_client = PitcherClient()
        self._bullpen_client = BullpenClient()

        # Engines
        self._injury_engine = InjuryImpactEngine()
        self._weather_engine = WeatherImpactEngine()
        self._pitcher_engine = PitcherImpactEngine()
        self._bullpen_engine = BullpenImpactEngine()
        self._prediction_engine = PredictionEngine()

        # Output
        self._live_predictions = LivePredictions()
        self._clv_tracker = CLVTracker()
        self.bet_logger = BetLogger()

        # Monitoring
        self._feed_health = FeedHealthMonitor()
        self._schedule_log = ScheduleLogger()

        # State
        self._games: list[Game] = []
        self._injuries: list[RawInjury] = []
        self._weather: dict = {}
        self._splits: list[SplitEntry] = []
        self._pitchers: dict[str, PitcherStats] = {}
        self._bullpens: dict[str, BullpenStats] = {}

        logger.debug("MLBPipeline initialised — all clients and engines ready")

    # ------------------------------------------------------------------
    # Phase 1 — Data collection
    # ------------------------------------------------------------------

    def refresh_odds(self) -> None:
        logger.info("Phase 1 — Fetching odds from The Odds API...")
        self._feed_health.set_status("OddsAPI", FeedStatus.RUNNING)
        refresh_id = datetime.utcnow().isoformat()
        t0 = time.time()
        try:
            games = self._odds_client.fetch_games()
            logger.info("Odds API returned %d games", len(games))
            for game in games:
                self._clv_tracker.update_current(game)
            self._games = games
            RawStore.save_odds(refresh_id, games)
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("OddsAPI", FeedStatus.OK, f"{len(games)} games", record_count=len(games))
            self._schedule_log.log("refresh_odds", "OK", f"{len(games)} games", ms)
            logger.info("Odds refreshed: %d games in %dms", len(games), ms)
            if games:
                logger.debug(
                    "Games fetched: %s",
                    "  |  ".join(
                        f"{g.away_team} @ {g.home_team} "
                        f"(ML: {g.odds.away_ml.price if g.odds.away_ml else 'N/A'}"
                        f"/{g.odds.home_ml.price if g.odds.home_ml else 'N/A'})"
                        for g in games
                    ),
                )
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("OddsAPI", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_odds", "FAIL", str(exc), ms)
            logger.error("Odds refresh failed after %dms: %s", ms, exc, exc_info=True)

    def refresh_injuries(self) -> None:
        logger.info("Phase 1 — Scraping injuries from Covers.com...")
        self._feed_health.set_status("Injuries", FeedStatus.RUNNING)
        refresh_id = datetime.utcnow().isoformat()
        t0 = time.time()
        try:
            injuries = self._injury_scraper.fetch()
            self._injuries = injuries
            RawStore.save_injuries(refresh_id, injuries)
            ms = int((time.time() - t0) * 1000)

            # Log breakdown by status
            status_counts: dict[str, int] = {}
            team_counts: dict[str, int] = {}
            for inj in injuries:
                status_counts[inj.status] = status_counts.get(inj.status, 0) + 1
                if inj.team_key:
                    team_counts[inj.team_key] = team_counts.get(inj.team_key, 0) + 1

            sp_injuries = [i for i in injuries if i.position == "SP"]
            logger.info(
                "Injuries scraped: %d records in %dms  "
                "(Out: %d  Doubtful: %d  Questionable: %d  D2D: %d  SP injuries: %d)",
                len(injuries), ms,
                status_counts.get("out", 0),
                status_counts.get("doubtful", 0),
                status_counts.get("questionable", 0),
                status_counts.get("day-to-day", 0),
                len(sp_injuries),
            )
            if sp_injuries:
                logger.warning(
                    "SP injuries found: %s",
                    "  |  ".join(
                        f"{i.player_name} ({i.team_key or i.team_raw}) [{i.status}]"
                        for i in sp_injuries
                    ),
                )
            logger.debug(
                "Teams with injuries (%d teams): %s",
                len(team_counts),
                "  ".join(f"{t}:{c}" for t, c in sorted(team_counts.items())),
            )

            self._feed_health.set_status("Injuries", FeedStatus.OK, f"{len(injuries)} records", record_count=len(injuries))
            self._schedule_log.log("refresh_injuries", "OK", f"{len(injuries)} records", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Injuries", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_injuries", "FAIL", str(exc), ms)
            logger.error("Injury refresh failed after %dms: %s", ms, exc, exc_info=True)

    def refresh_weather(self) -> None:
        logger.info("Phase 1 — Fetching weather from WeatherAPI.com...")
        self._feed_health.set_status("Weather", FeedStatus.RUNNING)
        refresh_id = datetime.utcnow().isoformat()
        t0 = time.time()
        try:
            weather = self._weather_client.fetch_all()
            self._weather = weather
            RawStore.save_weather(refresh_id, weather)
            ms = int((time.time() - t0) * 1000)

            dome_count = sum(1 for w in weather.values() if w.is_dome)
            logger.info(
                "Weather fetched: %d stadiums in %dms  (dome: %d  outdoor: %d)",
                len(weather), ms, dome_count, len(weather) - dome_count,
            )
            for team_key, w in weather.items():
                if not w.is_dome:
                    logger.debug(
                        "  Weather [%s]: %.0f°F  wind=%.1fmph @ %s  precip=%s",
                        team_key, w.temperature_f, w.wind_speed_mph,
                        w.wind_direction_name, w.precipitation_category,
                    )

            self._feed_health.set_status("Weather", FeedStatus.OK, f"{len(weather)} stadiums", record_count=len(weather))
            self._schedule_log.log("refresh_weather", "OK", f"{len(weather)} stadiums", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Weather", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_weather", "FAIL", str(exc), ms)
            logger.error("Weather refresh failed after %dms: %s", ms, exc, exc_info=True)

    def refresh_dk_splits(self) -> None:
        logger.info("Phase 1 — Scraping DraftKings betting splits...")
        self._feed_health.set_status("DraftKings", FeedStatus.RUNNING)
        refresh_id = datetime.utcnow().isoformat()
        t0 = time.time()
        try:
            splits = self._dk_scraper.fetch()
            self._splits = splits
            RawStore.save_dk_splits(refresh_id, splits)
            ms = int((time.time() - t0) * 1000)

            logger.info(
                "DK splits scraped: %d games in %dms",
                len(splits), ms,
            )
            for s in splits:
                logger.debug(
                    "  DK split [%s @ %s]: "
                    "ML(Away/Home)=%.0f%%/%.0f%%  Handle(Away/Home)=%.0f%%/%.0f%%  SSS=%.1f",
                    s.away_team_key or s.game_id_raw.split("@")[0],
                    s.home_team_key or s.game_id_raw.split("@")[1],
                    s.away_ml_bets_pct, s.home_ml_bets_pct,
                    s.away_handle_pct, s.home_handle_pct,
                    s.sharp_split_score,
                )

            if not splits:
                logger.warning("DK splits returned 0 games — all games will use neutral SSS=50")

            self._feed_health.set_status(
                "DraftKings",
                FeedStatus.OK if splits else FeedStatus.PARTIAL,
                f"{len(splits)} games",
            )
            self._schedule_log.log("refresh_dk_splits", "OK", f"{len(splits)} games", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("DraftKings", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_dk_splits", "FAIL", str(exc), ms)
            logger.error("DK splits refresh failed after %dms: %s", ms, exc, exc_info=True)

    def refresh_pitchers(self) -> None:
        logger.info("Phase 1 — Fetching probable starters from MLB Stats API...")
        self._feed_health.set_status("Pitchers", FeedStatus.RUNNING)
        refresh_id = datetime.utcnow().isoformat()
        t0 = time.time()
        try:
            pitchers = self._pitcher_client.fetch_probable_starters()
            logger.info("MLB API returned %d probable starters", len(pitchers))

            # Score each pitcher
            for team_key, pitcher in pitchers.items():
                self._pitcher_engine.score_and_attach(pitcher)

            self._pitchers = pitchers
            RawStore.save_pitchers(refresh_id, pitchers)
            ms = int((time.time() - t0) * 1000)

            tbd_count = sum(1 for p in pitchers.values() if p.is_tbd)
            logger.info(
                "Pitchers fetched and scored: %d starters in %dms  (TBD: %d  known: %d)",
                len(pitchers), ms, tbd_count, len(pitchers) - tbd_count,
            )
            for team_key, p in pitchers.items():
                logger.debug(
                    "  Starter [%s]: %s — score=%.1f/100  ERA=%s  WHIP=%s  K/9=%s  "
                    "recent_ERA=%s  hand=%s",
                    team_key, p.name, p.impact_score,
                    f"{p.era:.2f}" if p.era is not None else "N/A",
                    f"{p.whip:.2f}" if p.whip is not None else "N/A",
                    f"{p.k_per_9:.1f}" if p.k_per_9 is not None else "N/A",
                    f"{p.recent_era:.2f}" if p.recent_era is not None else "N/A",
                    p.hand,
                )

            self._feed_health.set_status("Pitchers", FeedStatus.OK, f"{len(pitchers)} starters", record_count=len(pitchers))
            self._schedule_log.log("refresh_pitchers", "OK", f"{len(pitchers)} starters", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Pitchers", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_pitchers", "FAIL", str(exc), ms)
            logger.error("Pitcher refresh failed after %dms: %s", ms, exc, exc_info=True)

    def refresh_bullpens(self) -> None:
        logger.info("Phase 1 — Fetching team pitching stats (bullpen depth) from MLB Stats API...")
        self._feed_health.set_status("Bullpens", FeedStatus.RUNNING)
        refresh_id = datetime.utcnow().isoformat()
        t0 = time.time()
        try:
            bullpens = self._bullpen_client.fetch_team_pitching()
            logger.info("MLB API returned pitching stats for %d teams", len(bullpens))

            # Score each team's pitching depth
            for team_key, bullpen in bullpens.items():
                self._bullpen_engine.score_and_attach(bullpen)

            self._bullpens = bullpens
            ms = int((time.time() - t0) * 1000)

            scored_count = sum(1 for b in bullpens.values() if b.games >= 10)
            logger.info(
                "Bullpen stats fetched and scored: %d teams in %dms  (scored: %d  neutral/pre-season: %d)",
                len(bullpens), ms, scored_count, len(bullpens) - scored_count,
            )
            for team_key, b in bullpens.items():
                logger.debug(
                    "  Bullpen [%s]: score=%.1f/100  ERA=%s  FIP=%s  K/9=%s  BB/9=%s  games=%d",
                    team_key, b.impact_score,
                    f"{b.era:.2f}" if b.era is not None else "N/A",
                    f"{b.fip:.2f}" if b.fip is not None else "N/A",
                    f"{b.k_per_9:.1f}" if b.k_per_9 is not None else "N/A",
                    f"{b.bb_per_9:.1f}" if b.bb_per_9 is not None else "N/A",
                    b.games,
                )

            self._feed_health.set_status("Bullpens", FeedStatus.OK, f"{len(bullpens)} teams", record_count=len(bullpens))
            self._schedule_log.log("refresh_bullpens", "OK", f"{len(bullpens)} teams", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Bullpens", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_bullpens", "FAIL", str(exc), ms)
            logger.error("Bullpen refresh failed after %dms: %s", ms, exc, exc_info=True)

    # ------------------------------------------------------------------
    # Phase 1B — Apply impacts to game objects
    # ------------------------------------------------------------------

    def _apply_impacts(self) -> None:
        """Annotate each Game with computed impact values."""
        logger.info(
            "Phase 1B — Applying impacts to %d games  "
            "(injuries=%d  weather=%d stadiums  splits=%d  pitchers=%d  bullpens=%d)",
            len(self._games), len(self._injuries),
            len(self._weather), len(self._splits), len(self._pitchers), len(self._bullpens),
        )

        # Build injury lookup by team_key
        injury_by_team: dict[str, list[RawInjury]] = {}
        for inj in self._injuries:
            if inj.team_key:
                injury_by_team.setdefault(inj.team_key, []).append(inj)
        logger.debug(
            "Injury lookup built: %d teams with injuries — %s",
            len(injury_by_team),
            list(injury_by_team.keys()),
        )

        # Build splits lookup by (away_key, home_key)
        split_lookup: dict[tuple, SplitEntry] = {}
        for s in self._splits:
            if s.away_team_key and s.home_team_key:
                split_lookup[(s.away_team_key, s.home_team_key)] = s
        logger.debug(
            "DK split lookup built: %d matchups — %s",
            len(split_lookup),
            [f"{k[0]}@{k[1]}" for k in split_lookup.keys()],
        )

        for game in self._games:
            matchup_label = f"{game.away_team} @ {game.home_team}"

            # --- Injuries ---
            away_inj_raw = injury_by_team.get(game.away_team, [])
            home_inj_raw = injury_by_team.get(game.home_team, [])

            away_sp_raw = next((i for i in away_inj_raw if i.position == "SP"), None)
            home_sp_raw = next((i for i in home_inj_raw if i.position == "SP"), None)

            away_injured = [
                InjuredPlayer(i.player_name, i.team_key or "", i.position, i.status)
                for i in away_inj_raw
            ]
            home_injured = [
                InjuredPlayer(i.player_name, i.team_key or "", i.position, i.status)
                for i in home_inj_raw
            ]
            away_sp = InjuredPlayer(away_sp_raw.player_name, game.away_team, "SP", away_sp_raw.status) if away_sp_raw else None
            home_sp = InjuredPlayer(home_sp_raw.player_name, game.home_team, "SP", home_sp_raw.status) if home_sp_raw else None

            if away_inj_raw or home_inj_raw:
                logger.debug(
                    "[%s] Injuries — away: %d players  home: %d players",
                    matchup_label, len(away_inj_raw), len(home_inj_raw),
                )

            inj_result = self._injury_engine.calculate(away_injured, home_injured, away_sp, home_sp)
            game.away_injury_impact = inj_result.away_impact
            game.home_injury_impact = inj_result.home_impact
            game.sp_gate_blocked = inj_result.away_sp_blocked or inj_result.home_sp_blocked

            if inj_result.away_impact != 0 or inj_result.home_impact != 0:
                logger.info(
                    "[%s] Injury impacts applied — away: %+.4f  home: %+.4f  sp_gate: %s",
                    matchup_label,
                    game.away_injury_impact, game.home_injury_impact,
                    game.sp_gate_blocked,
                )

            # --- Weather ---
            weather = self._weather.get(game.home_team)
            if weather and not weather.is_dome:
                game.temperature_f = weather.temperature_f
                game.wind_speed_mph = weather.wind_speed_mph
                game.wind_direction = weather.wind_direction_name
                game.precipitation = weather.precipitation_category
                game.is_dome = weather.is_dome

                w_result = self._weather_engine.calculate(
                    game.home_team,
                    weather.temperature_f,
                    weather.wind_speed_mph,
                    weather.wind_direction_deg,
                    weather.precipitation_category,
                )
                game.weather_over_adj = w_result.over_adj
                game.weather_under_adj = w_result.under_adj

                if w_result.over_adj != 0 or w_result.under_adj != 0:
                    logger.info(
                        "[%s] Weather impacts applied — over: %+.2f  under: %+.2f  reason: %s",
                        matchup_label, game.weather_over_adj, game.weather_under_adj, w_result.reason,
                    )
                else:
                    logger.debug("[%s] Weather — no significant impact (%s)", matchup_label, w_result.reason)
            elif weather and weather.is_dome:
                game.is_dome = True
                logger.debug("[%s] Weather — dome stadium, skipping weather adjustment", matchup_label)
            else:
                logger.debug(
                    "[%s] Weather — no data for home team '%s'", matchup_label, game.home_team,
                )

            # --- Pitchers ---
            away_pitcher = self._pitchers.get(game.away_team)
            home_pitcher = self._pitchers.get(game.home_team)
            if away_pitcher:
                game.away_pitcher_score = away_pitcher.impact_score
                game.away_pitcher_name = away_pitcher.name
                logger.debug(
                    "[%s] Away pitcher: %s  score=%.1f/100",
                    matchup_label, away_pitcher.name, away_pitcher.impact_score,
                )
            else:
                logger.debug(
                    "[%s] Away pitcher: NOT FOUND for team '%s' — using TBD (score=50)",
                    matchup_label, game.away_team,
                )
            if home_pitcher:
                game.home_pitcher_score = home_pitcher.impact_score
                game.home_pitcher_name = home_pitcher.name
                logger.debug(
                    "[%s] Home pitcher: %s  score=%.1f/100",
                    matchup_label, home_pitcher.name, home_pitcher.impact_score,
                )
            else:
                logger.debug(
                    "[%s] Home pitcher: NOT FOUND for team '%s' — using TBD (score=50)",
                    matchup_label, game.home_team,
                )

            # --- Bullpen / Pitching Depth ---
            away_bullpen = self._bullpens.get(game.away_team)
            home_bullpen = self._bullpens.get(game.home_team)
            if away_bullpen:
                game.away_bullpen_score = away_bullpen.impact_score
                logger.debug(
                    "[%s] Away bullpen: score=%.1f/100  (games=%d)",
                    matchup_label, away_bullpen.impact_score, away_bullpen.games,
                )
            else:
                logger.debug(
                    "[%s] Away bullpen: NOT FOUND for '%s' — using neutral 50",
                    matchup_label, game.away_team,
                )
            if home_bullpen:
                game.home_bullpen_score = home_bullpen.impact_score
                logger.debug(
                    "[%s] Home bullpen: score=%.1f/100  (games=%d)",
                    matchup_label, home_bullpen.impact_score, home_bullpen.games,
                )
            else:
                logger.debug(
                    "[%s] Home bullpen: NOT FOUND for '%s' — using neutral 50",
                    matchup_label, game.home_team,
                )

            # --- Park Factors ---
            game.park_factor = get_park_factor(game.home_team)
            game.park_ou_adj = park_ou_adjustment_display(game.home_team)
            logger.debug(
                "[%s] Park factors — factor=%.2f  ou_adj=%+.2f",
                matchup_label, game.park_factor, game.park_ou_adj,
            )

            # --- Sharp Splits ---
            split = split_lookup.get((game.away_team, game.home_team))
            if split:
                game.sharp_split_score = split.sharp_split_score
                game.away_handle_pct = split.away_handle_pct
                game.home_handle_pct = split.home_handle_pct
                game.away_bets_pct = split.away_ml_bets_pct if split.away_ml_bets_pct else 50.0
                game.home_bets_pct = split.home_ml_bets_pct if split.home_ml_bets_pct else 50.0
                logger.info(
                    "[%s] DK splits matched — SSS=%.1f  "
                    "Away(handle=%.0f%%/bets=%.0f%%)  Home(handle=%.0f%%/bets=%.0f%%)",
                    matchup_label, split.sharp_split_score,
                    split.away_handle_pct, split.away_ml_bets_pct,
                    split.home_handle_pct, split.home_ml_bets_pct,
                )
            else:
                logger.warning(
                    "[%s] DK splits NOT MATCHED — using neutral defaults (handle=50, bets=50, SSS=50)  "
                    "[away_key='%s'  home_key='%s'  available_keys=%s]",
                    matchup_label, game.away_team, game.home_team,
                    list(split_lookup.keys())[:10],
                )

    # ------------------------------------------------------------------
    # Phase 2 — Generate predictions
    # ------------------------------------------------------------------

    def update_live_predictions(self, raw_refresh_id: str = "") -> list[Prediction]:
        logger.info("Phase 2 — Running prediction engine on %d games...", len(self._games))
        t0 = time.time()
        self._apply_impacts()
        # Back-fill weather impact values into raw_weather rows now that engine has run
        if raw_refresh_id:
            RawStore.update_weather_impacts(raw_refresh_id, self._games)
        # All predictions (every game including PASS) — for the Model page
        all_predictions = [self._prediction_engine.evaluate(g) for g in self._games]
        # Qualified picks only — for Live Picks page
        qualified = [p for p in all_predictions if p.is_qualified()]
        self._live_predictions.update(qualified)
        self._live_predictions.save_model_to_db(all_predictions)
        ms = int((time.time() - t0) * 1000)

        tier_counts: dict[str, int] = {}
        for p in all_predictions:
            tier_counts[p.status] = tier_counts.get(p.status, 0) + 1

        logger.info(
            "Phase 2 complete in %dms — %d games evaluated  %d qualified picks  "
            "Breakdown: %s",
            ms, len(all_predictions), len(qualified),
            "  ".join(f"{t}:{c}" for t, c in sorted(tier_counts.items())),
        )
        if qualified:
            logger.info(
                "Qualified picks: %s",
                "  |  ".join(
                    f"[{p.status}] {p.picked_team_name} ML{p.bet_price:+d} "
                    f"Conf={p.confidence_pct:.1f}%% EV={p.ev_pct:+.2f}%%"
                    for p in qualified
                ),
            )
        return qualified

    def get_all_predictions(self) -> list[Prediction]:
        """Return the latest full model (all games, all tiers) from in-memory state."""
        return list(self._live_predictions.get_model())

    # ------------------------------------------------------------------
    # Full refresh cycle
    # ------------------------------------------------------------------

    def run_full_refresh(self) -> list[Prediction]:
        """
        Run all Phase 1 data collection then generate predictions.
        This is the equivalent of V8.0 runAllPhases().

        All five data sources share a single refresh_id (the UTC timestamp
        when this full refresh was started), so you can query all five raw_*
        tables with the same refresh_id to see exactly what was fetched in
        one pipeline run.
        """
        t_start = time.time()
        refresh_id = datetime.utcnow().isoformat()
        logger.info("=" * 60)
        logger.info("=== MLB Full Refresh Started  [refresh_id=%s] ===", refresh_id)
        logger.info("=" * 60)

        # Each individual refresh generates its own refresh_id internally
        # when called standalone.  For a full refresh we override that by
        # calling the save functions explicitly here with the shared refresh_id
        # instead of relying on the per-method ids.
        self._run_odds(refresh_id)
        self._run_injuries(refresh_id)
        self._run_weather(refresh_id)
        self._run_dk_splits(refresh_id)
        self._run_pitchers(refresh_id)
        self._run_bullpens(refresh_id)
        predictions = self.update_live_predictions(raw_refresh_id=refresh_id)
        self._live_predictions.print_summary()
        self._feed_health.print_summary()

        total_ms = int((time.time() - t_start) * 1000)
        logger.info("=" * 60)
        logger.info(
            "=== MLB Full Refresh Complete: %d picks in %.1fs  [refresh_id=%s] ===",
            len(predictions), total_ms / 1000, refresh_id,
        )
        logger.info("=" * 60)
        return predictions

    # ------------------------------------------------------------------
    # Internal helpers used by run_full_refresh (shared refresh_id)
    # ------------------------------------------------------------------

    def _run_odds(self, refresh_id: str) -> None:
        """Fetch odds and save raw rows under the given refresh_id."""
        self._feed_health.set_status("OddsAPI", FeedStatus.RUNNING)
        t0 = time.time()
        try:
            games = self._odds_client.fetch_games()
            logger.info("Odds API returned %d games", len(games))
            for game in games:
                self._clv_tracker.update_current(game)
            self._games = games
            RawStore.save_odds(refresh_id, games)
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("OddsAPI", FeedStatus.OK, f"{len(games)} games", record_count=len(games))
            self._schedule_log.log("refresh_odds", "OK", f"{len(games)} games", ms)
            logger.info("Odds refreshed: %d games in %dms", len(games), ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("OddsAPI", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_odds", "FAIL", str(exc), ms)
            logger.error("Odds refresh failed after %dms: %s", ms, exc, exc_info=True)

    def _run_injuries(self, refresh_id: str) -> None:
        self._feed_health.set_status("Injuries", FeedStatus.RUNNING)
        t0 = time.time()
        try:
            injuries = self._injury_scraper.fetch()
            self._injuries = injuries
            RawStore.save_injuries(refresh_id, injuries)
            ms = int((time.time() - t0) * 1000)
            status_counts: dict[str, int] = {}
            for inj in injuries:
                status_counts[inj.status] = status_counts.get(inj.status, 0) + 1
            sp_injuries = [i for i in injuries if i.position == "SP"]
            logger.info(
                "Injuries scraped: %d records in %dms  "
                "(Out:%d Doubtful:%d Questionable:%d D2D:%d SP:%d)",
                len(injuries), ms,
                status_counts.get("out", 0), status_counts.get("doubtful", 0),
                status_counts.get("questionable", 0), status_counts.get("day-to-day", 0),
                len(sp_injuries),
            )
            self._feed_health.set_status("Injuries", FeedStatus.OK, f"{len(injuries)} records", record_count=len(injuries))
            self._schedule_log.log("refresh_injuries", "OK", f"{len(injuries)} records", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Injuries", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_injuries", "FAIL", str(exc), ms)
            logger.error("Injury refresh failed after %dms: %s", ms, exc, exc_info=True)

    def _run_weather(self, refresh_id: str) -> None:
        self._feed_health.set_status("Weather", FeedStatus.RUNNING)
        t0 = time.time()
        try:
            weather = self._weather_client.fetch_all()
            self._weather = weather
            RawStore.save_weather(refresh_id, weather)
            ms = int((time.time() - t0) * 1000)
            dome_count = sum(1 for w in weather.values() if w.is_dome)
            logger.info(
                "Weather fetched: %d stadiums in %dms  (dome:%d outdoor:%d)",
                len(weather), ms, dome_count, len(weather) - dome_count,
            )
            self._feed_health.set_status("Weather", FeedStatus.OK, f"{len(weather)} stadiums", record_count=len(weather))
            self._schedule_log.log("refresh_weather", "OK", f"{len(weather)} stadiums", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Weather", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_weather", "FAIL", str(exc), ms)
            logger.error("Weather refresh failed after %dms: %s", ms, exc, exc_info=True)

    def _run_dk_splits(self, refresh_id: str) -> None:
        self._feed_health.set_status("DraftKings", FeedStatus.RUNNING)
        t0 = time.time()
        try:
            splits = self._dk_scraper.fetch()
            self._splits = splits
            RawStore.save_dk_splits(refresh_id, splits)
            ms = int((time.time() - t0) * 1000)
            logger.info("DK splits scraped: %d games in %dms", len(splits), ms)
            if not splits:
                logger.warning("DK splits returned 0 games — all games will use neutral SSS=50")
            self._feed_health.set_status(
                "DraftKings",
                FeedStatus.OK if splits else FeedStatus.PARTIAL,
                f"{len(splits)} games",
            )
            self._schedule_log.log("refresh_dk_splits", "OK", f"{len(splits)} games", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("DraftKings", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_dk_splits", "FAIL", str(exc), ms)
            logger.error("DK splits refresh failed after %dms: %s", ms, exc, exc_info=True)

    def _run_pitchers(self, refresh_id: str) -> None:
        self._feed_health.set_status("Pitchers", FeedStatus.RUNNING)
        t0 = time.time()
        try:
            pitchers = self._pitcher_client.fetch_probable_starters()
            logger.info("MLB API returned %d probable starters", len(pitchers))
            for team_key, pitcher in pitchers.items():
                self._pitcher_engine.score_and_attach(pitcher)
            self._pitchers = pitchers
            RawStore.save_pitchers(refresh_id, pitchers)
            ms = int((time.time() - t0) * 1000)
            tbd_count = sum(1 for p in pitchers.values() if p.is_tbd)
            logger.info(
                "Pitchers fetched and scored: %d starters in %dms  (TBD:%d known:%d)",
                len(pitchers), ms, tbd_count, len(pitchers) - tbd_count,
            )
            self._feed_health.set_status("Pitchers", FeedStatus.OK, f"{len(pitchers)} starters", record_count=len(pitchers))
            self._schedule_log.log("refresh_pitchers", "OK", f"{len(pitchers)} starters", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Pitchers", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_pitchers", "FAIL", str(exc), ms)
            logger.error("Pitcher refresh failed after %dms: %s", ms, exc, exc_info=True)

    def _run_bullpens(self, refresh_id: str) -> None:
        self._feed_health.set_status("Bullpens", FeedStatus.RUNNING)
        t0 = time.time()
        try:
            bullpens = self._bullpen_client.fetch_team_pitching()
            logger.info("MLB API returned team pitching stats for %d teams", len(bullpens))
            for team_key, bullpen in bullpens.items():
                self._bullpen_engine.score_and_attach(bullpen)
            self._bullpens = bullpens
            ms = int((time.time() - t0) * 1000)
            scored_count = sum(1 for b in bullpens.values() if b.games >= 10)
            logger.info(
                "Bullpen stats fetched and scored: %d teams in %dms  (scored:%d neutral:%d)",
                len(bullpens), ms, scored_count, len(bullpens) - scored_count,
            )
            self._feed_health.set_status("Bullpens", FeedStatus.OK, f"{len(bullpens)} teams", record_count=len(bullpens))
            self._schedule_log.log("refresh_bullpens", "OK", f"{len(bullpens)} teams", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            self._feed_health.set_status("Bullpens", FeedStatus.FAIL, str(exc))
            self._schedule_log.log("refresh_bullpens", "FAIL", str(exc), ms)
            logger.error("Bullpen refresh failed after %dms: %s", ms, exc, exc_info=True)
