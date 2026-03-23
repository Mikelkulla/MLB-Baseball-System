"""
PredictionEngine — orchestrates all calculation modules for a single game.
V8.0 Phase 2 equivalent.

Key alignments:
- Probability always from ML vig-removal (consensus across books when available).
  Run line prices are NOT used for probability — the run line is a different event
  (win by 2+, ~72% of ML wins) and using it circularly guarantees EV = -(vig%).
- EV calculated against best available ML prices across all books.
- Pick by highest EV side (not highest probability)
- Soft EV gate: EV<0 + prob≥55% → GOLD at 1.0u (EV-CAP); EV<0 + prob<55% → PASS
- SharpSplit = ourHandle% - ourBets%  (signed)
- WPI        = 50 + (ourHandle - 50) * 1.5
- SharpScore = 50 + SharpSplit*0.5 + (WPI-50)*0.4
- Confidence = evNorm*0.50 + SharpScore*0.50
- Steam-against cap: line moved ≥1.5pts adverse → cap conf at 74%
- Steam auto-pass:   line moved ≥2.0pts adverse → 0 units
- LineFlip cap:      spread sign changed + SharpScore<70 → cap conf at 74%
- WPI tier gating via ConfidenceEngine.assign_tier()
- Spread data retained for CLV tracking, LineFlip, and display columns only
"""

from __future__ import annotations
import logging
from models.game import Game
from models.prediction import Prediction
from engine.probability import ProbabilityEngine
from engine.ev_calculator import EVCalculator
from engine.confidence import ConfidenceEngine
from engine.pitcher_impact import PitcherImpactEngine
from mlb.ballpark_factors import park_pitcher_scaling
from config.mlb_config import TEAM_BY_KEY


logger = logging.getLogger(__name__)

# Steam thresholds (V8.0)
STEAM_AGAINST_CAP_PTS  = 1.5   # cap confidence at 74 if line moved this many pts against us
STEAM_AUTO_PASS_PTS    = 2.0   # 0 units if line moved this many pts against us

# Spread limit gate (V8.0 BETTING_CONFIG.spreadLimit)
# Any |spread| >= this → PASS regardless of EV/confidence. In MLB (run line ±1.5) never fires,
# but required for V8.0 alignment.
SPREAD_LIMIT = 9


class PredictionEngine:

    def __init__(self):
        self._prob = ProbabilityEngine()
        self._ev = EVCalculator()
        self._conf = ConfidenceEngine()
        self._pitcher = PitcherImpactEngine()

    def evaluate(self, game: Game) -> Prediction:
        """Full V8.0 evaluation pipeline for one game."""
        odds = game.odds
        matchup_label = f"{game.away_team} vs {game.home_team}"

        logger.debug("── EVALUATING: %s (game_id=%s) ──", matchup_label, game.game_id)

        # --- 1. Guard: need at minimum ML odds ---
        if odds.away_ml is None or odds.home_ml is None:
            logger.warning(
                "[%s] SKIPPED — missing ML odds (away_ml=%s, home_ml=%s)",
                matchup_label, odds.away_ml, odds.home_ml,
            )
            return self._empty_prediction(game)

        # --- 1b. Detect available markets ---
        # bet_type is always MONEYLINE. ML odds represent true win probability.
        # Run line prices reflect "win by 2+" (~72% of ML wins due to 28% of MLB
        # games ending by exactly 1 run) — a different event. Using run line prices
        # for probability creates circular EV that is always negative (= -(vig%)).
        # Spread data is still collected for CLV tracking, LineFlip, and display.
        has_spread = odds.away_spread is not None and odds.home_spread is not None
        bet_type = "MONEYLINE"
        logger.debug(
            "[%s] Market: MONEYLINE  Away: %+d  Home: %+d  Books: %d  Spread available: %s",
            matchup_label,
            odds.away_ml.price, odds.home_ml.price,
            odds.book_count, has_spread,
        )

        # --- 2. Probability estimate (always from ML odds) ---
        # Prefer consensus across all available books — removes single-book bias.
        # Falls back to single-book vig removal when only one book is available.
        if odds.consensus_away_prob is not None:
            away_prob = odds.consensus_away_prob
            home_prob = odds.consensus_home_prob
            logger.debug(
                "[%s] Probability source: ML CONSENSUS (%d books) — Away: %.2f%%  Home: %.2f%%",
                matchup_label, odds.book_count, away_prob, home_prob,
            )
        else:
            away_prob, home_prob = self._prob.remove_vig(odds.away_ml.price, odds.home_ml.price)
            logger.debug(
                "[%s] Probability source: ML VIG-REMOVAL (single book) — Away: %.2f%%  Home: %.2f%%",
                matchup_label, away_prob, home_prob,
            )

        # --- 3. Apply injury adjustments ---
        pre_inj_away, pre_inj_home = away_prob, home_prob
        away_prob, home_prob = self._prob.apply_injury_adjustment(
            away_prob, home_prob,
            game.away_injury_impact,
            game.home_injury_impact,
        )
        if game.away_injury_impact != 0 or game.home_injury_impact != 0:
            logger.debug(
                "[%s] Injury adj — Away delta: %+.3f  Home delta: %+.3f  "
                "Prob before: Away %.2f%% Home %.2f%%  After: Away %.2f%% Home %.2f%%",
                matchup_label,
                game.away_injury_impact, game.home_injury_impact,
                pre_inj_away, pre_inj_home, away_prob, home_prob,
            )
        else:
            logger.debug("[%s] Injury adj — no injuries affecting probability", matchup_label)

        # --- 3b. Pitcher probability adjustment ---
        # Park scaling: hitter parks (Coors 0.62×) dilute pitcher edges;
        # pitcher parks (Petco 1.12×) amplify them.
        park_scaling = park_pitcher_scaling(game.home_team)
        pre_pitch_away, pre_pitch_home = away_prob, home_prob
        away_prob, home_prob = self._prob.apply_pitcher_adjustment(
            away_prob, home_prob,
            game.away_pitcher_score,
            game.home_pitcher_score,
            park_scaling=park_scaling,
        )
        pitcher_edge = game.away_pitcher_score - game.home_pitcher_score
        logger.debug(
            "[%s] Pitcher adj — Away SP: %s (%.0f/100)  Home SP: %s (%.0f/100)  "
            "Edge: %+.1f  Park scaling: %.2f (factor=%.2f)  "
            "Prob shift: %+.2f%%  After: Away %.2f%% Home %.2f%%",
            matchup_label,
            game.away_pitcher_name, game.away_pitcher_score,
            game.home_pitcher_name, game.home_pitcher_score,
            pitcher_edge, park_scaling, game.park_factor,
            away_prob - pre_pitch_away,
            away_prob, home_prob,
        )

        # --- 3c. Bullpen probability adjustment ---
        pre_bull_away, pre_bull_home = away_prob, home_prob
        away_prob, home_prob = self._prob.apply_bullpen_adjustment(
            away_prob, home_prob,
            game.away_bullpen_score,
            game.home_bullpen_score,
            park_scaling=park_scaling,
        )
        bullpen_edge = game.away_bullpen_score - game.home_bullpen_score
        logger.debug(
            "[%s] Bullpen adj — Away BP: %.0f/100  Home BP: %.0f/100  "
            "Edge: %+.1f  Prob shift: %+.2f%%  After: Away %.2f%% Home %.2f%%",
            matchup_label,
            game.away_bullpen_score, game.home_bullpen_score,
            bullpen_edge, away_prob - pre_bull_away,
            away_prob, home_prob,
        )

        # --- 4. EV for BOTH sides (against best available ML prices) ---
        # Probability comes from ML vig-removal; EV is calculated against the best
        # ML price available across all books. This is the correct pairing:
        # same event (win the game) for both probability and EV target.
        best_away_ml = odds.best_away_ml or odds.away_ml
        best_home_ml = odds.best_home_ml or odds.home_ml

        away_ev_raw = self._ev.calculate(away_prob, best_away_ml.price)
        home_ev_raw = self._ev.calculate(home_prob, best_home_ml.price)
        ev_away_price = best_away_ml.price
        ev_home_price = best_home_ml.price

        away_ev_cmp = away_ev_raw if away_ev_raw is not None else -999.0
        home_ev_cmp = home_ev_raw if home_ev_raw is not None else -999.0

        logger.debug(
            "[%s] EV (ML) — Away: %s at %+d  Home: %s at %+d",
            matchup_label,
            f"{away_ev_raw:+.2f}%" if away_ev_raw is not None else "N/A",
            ev_away_price,
            f"{home_ev_raw:+.2f}%" if home_ev_raw is not None else "N/A",
            ev_home_price,
        )

        # --- 5. Pick the side with higher EV ---
        # V8.0: PICKED_TEAM = IF(AwayEV > HomeEV, "away", IF(HomeEV > AwayEV, "home",
        #                        IF(AwaySpread > 0, "away", "home")))  ← tiebreaker = underdog
        if away_ev_cmp > home_ev_cmp:
            picked_side = "away"
        elif home_ev_cmp > away_ev_cmp:
            picked_side = "home"
        else:
            # Tiebreaker: underdog (positive ML = underdog)
            picked_side = "away" if odds.away_ml.price > 0 else "home"

        prob_pct = away_prob if picked_side == "away" else home_prob
        ev_pct_raw = away_ev_raw if picked_side == "away" else home_ev_raw
        ev_pct = ev_pct_raw if ev_pct_raw is not None else (away_ev_cmp if picked_side == "away" else home_ev_cmp)

        # bet_price: best available ML price for the picked side
        bet_price = best_away_ml.price if picked_side == "away" else best_home_ml.price

        logger.debug(
            "[%s] Pick: %s  Prob: %.2f%%  EV: %+.2f%%  Price: %+d",
            matchup_label, picked_side.upper(), prob_pct, ev_pct, bet_price,
        )

        # --- 6. Negative EV flag (V8.0: EV < 0 → 0 units; confidence still computed) ---
        # V8.0 always computes confidence for every game — PASS comes from EV gate or tier.
        # We no longer short-circuit here; units/status are overridden at the end if negative.
        ev_negative = ev_pct < 0
        if ev_negative:
            logger.debug(
                "[%s] EV gate: NEGATIVE (Away EV: %s  Home EV: %s) — continuing pipeline for confidence",
                matchup_label,
                f"{away_ev_raw:+.2f}%" if away_ev_raw is not None else "N/A",
                f"{home_ev_raw:+.2f}%" if home_ev_raw is not None else "N/A",
            )

        # --- 7. CLV delta (spread line movement) ---
        clv_delta = self._compute_clv(game, picked_side)
        logger.debug(
            "[%s] CLV delta (%s side): %+.2f pts  (open=%s  current=%s)",
            matchup_label, picked_side,
            clv_delta,
            game.odds.away_spread_open if picked_side == "away" else game.odds.home_spread_open,
            game.odds.away_spread.point if picked_side == "away" and game.odds.away_spread else
            game.odds.home_spread.point if game.odds.home_spread else "N/A",
        )

        # --- 8. SharpSplit (V8.0 signed: ourHandle - ourBets) ---
        if picked_side == "away":
            our_handle = game.away_handle_pct
            our_bets   = game.away_bets_pct
        else:
            our_handle = game.home_handle_pct
            our_bets   = game.home_bets_pct

        sharp_split = our_handle - our_bets   # positive = sharp money on our side

        # --- 9. WPI (WhaleIndex) = 50 + (ourHandle - 50) * 1.5 ---
        wpi = min(100.0, max(0.0, 50.0 + (our_handle - 50.0) * 1.5))

        logger.debug(
            "[%s] Sharp data — Handle: %.1f%%  Bets: %.1f%%  SharpSplit: %+.1f  WPI: %.1f  SSS: %.1f",
            matchup_label, our_handle, our_bets, sharp_split, wpi, game.sharp_split_score,
        )

        # --- 10. Steam-against safety (line movement against our pick) ---
        steam_cap, steam_auto_pass = self._steam_check(game, picked_side)
        if steam_cap or steam_auto_pass:
            adverse_pts = -clv_delta
            logger.warning(
                "[%s] STEAM ALERT — line moved %.2f pts AGAINST %s pick  "
                "(cap=%s  auto_pass=%s)",
                matchup_label, adverse_pts, picked_side.upper(),
                steam_cap, steam_auto_pass,
            )
        else:
            logger.debug("[%s] Steam check — OK (no adverse line movement)", matchup_label)

        # --- 11. LineFlip check ---
        sharp_score_val = self._conf.sharp_score(sharp_split, wpi)
        line_flip_cap = self._lineflip_check(game, picked_side, sharp_score_val)
        if line_flip_cap:
            logger.warning(
                "[%s] LINE FLIP detected — spread sign changed + SharpScore %.1f < 70 → cap at 74%%",
                matchup_label, sharp_score_val,
            )
        else:
            logger.debug(
                "[%s] Line flip check — OK  (SharpScore=%.1f)", matchup_label, sharp_score_val,
            )

        apply_cap = steam_cap or line_flip_cap

        # --- 12. SP gate ---
        sp_blocked = game.sp_gate_blocked
        if sp_blocked:
            logger.warning(
                "[%s] SP GATE BLOCKED — probable starter is Out/Doubtful → units=0",
                matchup_label,
            )

        # --- 13. Confidence + tier (V8.0 formula) ---
        confidence_pct, tier_name, safe_units = self._conf.evaluate(
            ev_pct=ev_pct,
            sharp_split=sharp_split,
            wpi=wpi,
            sp_gate_blocked=sp_blocked,
            steam_cap=apply_cap,
        )

        logger.debug(
            "[%s] Confidence — evNorm=%.1f  SharpScore=%.1f  raw_conf=%.2f%%  "
            "cap=%s  final_conf=%.2f%%  tier=%s  units=%.2f  safe_units=%.2f",
            matchup_label,
            self._conf.ev_norm(ev_pct),
            sharp_score_val,
            self._conf.score(ev_pct, sharp_split, wpi),
            apply_cap,
            confidence_pct,
            tier_name,
            self._conf.assign_tier(confidence_pct, wpi).units,
            safe_units,
        )

        # --- 14. Steam auto-pass: 0 units even if tier qualifies ---
        if steam_auto_pass:
            safe_units = 0.0
            logger.warning(
                "[%s] Steam auto-pass applied — units zeroed (tier=%s kept for display)",
                matchup_label, tier_name,
            )

        # --- 14b. Negative EV gate ---
        # If EV is negative AND probability is high enough (≥55%), allow the pick
        # through but cap units at 1.0u — covers spring training / data-sparse periods
        # where no independent probability edge exists yet but the model has some signal.
        # If EV is negative AND probability is below threshold → hard PASS (0 units).
        #
        # Important: safe_units is FORCED to 1.0 (not min(safe_units, 1.0)) because
        # when the confidence engine returns PASS (safe_units=0), min(0, 1.0)=0 and
        # the cap would do nothing. We also override tier_name to GOLD if it was PASS
        # so the pick is visible in Live Picks.
        EV_SOFT_GATE_PROB_MIN = 55.0
        if ev_negative:
            if prob_pct >= EV_SOFT_GATE_PROB_MIN:
                safe_units = 1.0   # force 1.0u — overrides 0 from PASS tier
                if tier_name == "PASS":
                    tier_name = "GOLD"  # minimum qualifying tier for EV-CAP picks
                logger.info(
                    "[%s] EV-CAP — negative EV but prob=%.1f%% >= %.0f%% threshold "
                    "(EV=%+.2f%%)  units forced to 1.0u  tier=%s  Conf=%.1f%%  WPI=%.0f",
                    matchup_label, prob_pct, EV_SOFT_GATE_PROB_MIN,
                    ev_pct, tier_name, confidence_pct, wpi,
                )
            else:
                safe_units = 0.0
                tier_name = "PASS"
                logger.info(
                    "[%s] PASS — negative EV gate (EV=%+.2f%%)  prob=%.1f%% < %.0f%%  "
                    "Conf=%.1f%%  WPI=%.0f",
                    matchup_label, ev_pct, prob_pct, EV_SOFT_GATE_PROB_MIN,
                    confidence_pct, wpi,
                )

        # --- 14c. Spread limit gate (V8.0 BETTING_CONFIG.spreadLimit = 9) ---
        # If the picked side's spread is >= SPREAD_LIMIT in absolute value → PASS.
        # In MLB (run line ±1.5) this never fires, but required for V8.0 alignment.
        if has_spread:
            picked_spread_point = (
                odds.away_spread.point if picked_side == "away" else odds.home_spread.point
            )
            if abs(picked_spread_point) >= SPREAD_LIMIT:
                safe_units = 0.0
                tier_name = "PASS"
                logger.warning(
                    "[%s] PASS — spread limit gate: |%.1f| >= %d",
                    matchup_label, picked_spread_point, SPREAD_LIMIT,
                )

        # --- 15. Team name resolution ---
        away_team_obj = TEAM_BY_KEY.get(game.away_team)
        home_team_obj = TEAM_BY_KEY.get(game.home_team)
        away_name = (
            f"{away_team_obj.city} {away_team_obj.name}" if away_team_obj
            else game.away_team
        )
        home_name = (
            f"{home_team_obj.city} {home_team_obj.name}" if home_team_obj
            else game.home_team
        )
        picked_name = away_name if picked_side == "away" else home_name

        # --- 16. Build prediction text ---
        picked_best_book = odds.best_away_book if picked_side == "away" else odds.best_home_book
        prediction_text = self._build_text(
            picked_name, tier_name, prob_pct, ev_pct,
            game, picked_side, sharp_split, wpi,
            best_book=picked_best_book, book_count=odds.book_count,
            bet_type=bet_type, bet_price=bet_price,
        )

        logger.info(
            "[%s] RESULT: [%s] %s %s %+d | Prob=%.1f%%  EV=%+.2f%%  "
            "Conf=%.1f%%  WPI=%.0f  Units=%.2f%s",
            matchup_label, tier_name, picked_name, bet_type, bet_price,
            prob_pct, ev_pct, confidence_pct, wpi, safe_units,
            "  [SP-GATE]" if sp_blocked else "",
        )

        return Prediction(
            game_id=game.game_id,
            sport=game.sport,
            game_date=game.commence_time,
            matchup=f"{away_name} vs {home_name}",
            # Best available ML odds for display
            away_ml=best_away_ml.price if best_away_ml else odds.away_ml.price if odds.away_ml else None,
            home_ml=best_home_ml.price if best_home_ml else odds.home_ml.price if odds.home_ml else None,
            # Spread point (±1.5) and total
            away_spread=odds.away_spread.point if odds.away_spread else None,
            home_spread=odds.home_spread.point if odds.home_spread else None,
            total_line=odds.over.point if odds.over else None,
            # Both-side metrics (V8.0 shows Away + Home separately)
            away_prob_pct=round(away_prob, 2),
            home_prob_pct=round(home_prob, 2),
            away_ev_pct=round(away_ev_raw, 2) if away_ev_raw is not None else None,
            home_ev_pct=round(home_ev_raw, 2) if home_ev_raw is not None else None,
            # Picked side
            picked_team=picked_side,
            picked_team_name=picked_name,
            bet_type=bet_type,
            bet_price=bet_price,
            best_book=odds.best_away_book if picked_side == "away" else odds.best_home_book,
            book_count=odds.book_count,
            # open_spread / current_spread = picked team's spread POINT (for CLV tracking)
            open_spread=odds.away_spread_open if picked_side == "away" else odds.home_spread_open,
            current_spread=(
                odds.away_spread.point if picked_side == "away" and odds.away_spread else
                odds.home_spread.point if odds.home_spread else None
            ),
            prob_pct=round(prob_pct, 2),
            ev_pct=round(ev_pct, 2),
            confidence_pct=round(confidence_pct, 2),
            units=self._conf.assign_tier(confidence_pct, wpi).units,
            status=tier_name,
            safe_units=safe_units,
            clv_delta=clv_delta,
            sharp_split_score=game.sharp_split_score,
            away_pitcher_name=game.away_pitcher_name,
            away_pitcher_score=game.away_pitcher_score,
            home_pitcher_name=game.home_pitcher_name,
            home_pitcher_score=game.home_pitcher_score,
            away_bullpen_score=game.away_bullpen_score,
            home_bullpen_score=game.home_bullpen_score,
            park_factor=game.park_factor,
            park_ou_adj=game.park_ou_adj,
            away_injury_impact=game.away_injury_impact,
            home_injury_impact=game.home_injury_impact,
            weather_over_adj=game.weather_over_adj,
            weather_under_adj=game.weather_under_adj,
            sp_gate_blocked=sp_blocked,
            prediction_text=prediction_text,
        )

    def evaluate_all(self, games: list[Game]) -> list[Prediction]:
        """Evaluate all games; returns only qualified predictions."""
        logger.info("PredictionEngine.evaluate_all — processing %d games", len(games))
        predictions = [self.evaluate(g) for g in games]
        qualified = [p for p in predictions if p.is_qualified()]
        tier_counts = {}
        for p in predictions:
            tier_counts[p.status] = tier_counts.get(p.status, 0) + 1
        logger.info(
            "evaluate_all complete — %d games → %d qualified picks  Tier breakdown: %s",
            len(games), len(qualified),
            "  ".join(f"{t}:{c}" for t, c in sorted(tier_counts.items())),
        )
        return qualified

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_clv(self, game: Game, picked_side: str) -> float:
        odds = game.odds
        if picked_side == "away":
            current = odds.away_spread.point if odds.away_spread else None
            opening = odds.away_spread_open
        else:
            current = odds.home_spread.point if odds.home_spread else None
            opening = odds.home_spread_open
        if current is None or opening is None:
            return 0.0
        return round(opening - current, 2)   # positive = line moved in our favour

    def _steam_check(self, game: Game, picked_side: str) -> tuple[bool, bool]:
        """
        V8.0 steam-against check.
        Returns (cap_at_74, auto_pass_units).
        """
        clv = self._compute_clv(game, picked_side)
        # Negative CLV means line moved AGAINST us (spread got worse for our pick)
        adverse_pts = -clv
        cap = adverse_pts >= STEAM_AGAINST_CAP_PTS
        auto_pass = adverse_pts >= STEAM_AUTO_PASS_PTS
        return cap, auto_pass

    @staticmethod
    def _lineflip_check(game: Game, picked_side: str, sharp_score_val: float) -> bool:
        """
        V8.0 LineFlip: if spread sign changed AND SharpScore < 70, cap confidence at 74.
        """
        odds = game.odds
        if picked_side == "away":
            current = odds.away_spread.point if odds.away_spread else None
            opening = odds.away_spread_open
        else:
            current = odds.home_spread.point if odds.home_spread else None
            opening = odds.home_spread_open
        if current is None or opening is None:
            return False
        # Sign change: e.g. -1.5 → +0.5 means the team flipped from fav to dog
        sign_changed = (current * opening < 0)
        return sign_changed and sharp_score_val < 70.0

    @staticmethod
    def _build_text(
        team_name: str,
        tier: str,
        prob: float,
        ev: float,
        game: Game,
        side: str,
        sharp_split: float,
        wpi: float,
        best_book: str = "",
        book_count: int = 0,
        bet_type: str = "SPREAD",
        bet_price: int = 0,
    ) -> str:
        odds = game.odds
        sp_name  = game.away_pitcher_name  if side == "away" else game.home_pitcher_name
        sp_score = game.away_pitcher_score if side == "away" else game.home_pitcher_score

        # Bet label: "SPREAD -1.5 (-110)" or "ML +135"
        if bet_type == "SPREAD":
            spread_line = odds.away_spread if side == "away" else odds.home_spread
            if spread_line:
                market_label = f"SPREAD {spread_line.point:+.1f} ({bet_price:+d})"
            else:
                market_label = f"SPREAD ({bet_price:+d})"
        else:
            market_label = f"ML {bet_price:+d}"

        parts = [
            f"[{tier}] {team_name} {market_label}",
            f"Prob: {prob:.1f}%",
            f"EV: {ev:+.1f}%",
            f"Split: {sharp_split:+.1f} WPI: {wpi:.0f}",
            f"SP: {sp_name} ({sp_score:.0f}/100)",
        ]
        if best_book:
            parts.append(f"Best: {best_book} ({book_count} books)")
        if game.weather_over_adj != 0 or game.weather_under_adj != 0:
            parts.append(f"Weather O/U adj: {game.weather_over_adj:+.1f}/{game.weather_under_adj:+.1f}")
        return " | ".join(parts)

    @staticmethod
    def _empty_prediction(game: Game) -> Prediction:
        return Prediction(
            game_id=game.game_id,
            matchup=f"{game.away_team} vs {game.home_team}",
            status="PASS",
            prediction_text="No odds available",
        )

    # _pass_prediction removed: pipeline no longer short-circuits on negative EV.
    # EV < 0 sets ev_negative=True; units/status are overridden at the end (step 14b).
