"""
Vig-free probability calculation — identical method to V8.0 Phase2_formulas.js v10.1.

Removes the bookmaker margin before any further analysis, ensuring all
downstream calculations work with true probabilities.
"""

from __future__ import annotations
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ProbabilityEngine:
    """Converts American odds to vig-free true probabilities."""

    @staticmethod
    def american_to_implied(american_odds: int) -> float:
        """
        Raw implied probability from American odds.
        Result is NOT vig-free — the two sides will sum to > 100%.
        """
        if american_odds >= 0:
            return 100 / (american_odds + 100)
        return abs(american_odds) / (abs(american_odds) + 100)

    @staticmethod
    def remove_vig(away_odds: int, home_odds: int) -> Tuple[float, float]:
        """
        Remove bookmaker margin and return true (vig-free) probabilities.

        Example: -150 / -130
          raw_away = 0.600, raw_home = 0.565 → total = 1.165 (16.5% vig)
          true_away = 0.600 / 1.165 = 0.515 → 51.5%
          true_home = 0.565 / 1.165 = 0.485 → 48.5%

        Returns:
            (away_true_prob_pct, home_true_prob_pct) — each 0–100
        """
        raw_away = ProbabilityEngine.american_to_implied(away_odds)
        raw_home = ProbabilityEngine.american_to_implied(home_odds)
        total = raw_away + raw_home
        if total == 0:
            logger.warning("remove_vig: total implied prob is 0 — odds=%d/%d, returning 50/50", away_odds, home_odds)
            return 50.0, 50.0
        overround = total - 1.0
        true_away = round(raw_away / total * 100, 4)
        true_home = round(raw_home / total * 100, 4)
        logger.debug(
            "remove_vig: odds=%+d/%+d  raw=%.4f/%.4f  overround=%.2f%%  "
            "true=%.4f%%/%.4f%%",
            away_odds, home_odds, raw_away, raw_home,
            overround * 100, true_away, true_home,
        )
        return true_away, true_home

    @staticmethod
    def apply_injury_adjustment(
        away_prob: float,
        home_prob: float,
        away_injury_delta: float,
        home_injury_delta: float,
    ) -> Tuple[float, float]:
        """
        Adjust probabilities using injury impact deltas.

        Injury delta is expressed as a probability percentage point change.
        Positive delta for a team = their probability increases.
        The opposing team's probability is adjusted symmetrically.
        """
        if away_injury_delta == 0 and home_injury_delta == 0:
            logger.debug("apply_injury_adjustment: no injuries — probabilities unchanged")
            return away_prob, home_prob

        # Net effect: home injuries hurt home → boost away
        net = home_injury_delta - away_injury_delta
        new_away = away_prob + net / 2
        new_home = home_prob - net / 2

        # Re-normalise to ensure sum = 100
        total = new_away + new_home
        if total <= 0:
            logger.warning("apply_injury_adjustment: total prob <= 0 after adjustment — returning 50/50")
            return 50.0, 50.0
        result_away = round(new_away / total * 100, 4)
        result_home = round(new_home / total * 100, 4)
        logger.debug(
            "apply_injury_adjustment: away_delta=%+.3f  home_delta=%+.3f  net=%+.3f  "
            "before=%.4f%%/%.4f%%  after=%.4f%%/%.4f%%  shift=%+.4f%%",
            away_injury_delta, home_injury_delta, net,
            away_prob, home_prob,
            result_away, result_home,
            result_away - away_prob,
        )
        return result_away, result_home

    @staticmethod
    def apply_pitcher_adjustment(
        away_prob: float,
        home_prob: float,
        away_pitcher_score: float,
        home_pitcher_score: float,
    ) -> Tuple[float, float]:
        """
        Shift probabilities based on pitcher quality differential.

        When an ace (high score) faces a weak starter (low score), the model
        adjusts the true probability INDEPENDENTLY from the market's implied odds.
        This creates the possibility of positive EV when the market under-adjusts.

        Scale: 50-point pitcher edge → ±5% probability shift (max ±10%).
        With all pitchers at 50 (spring training / TBD): no adjustment.
        """
        edge = away_pitcher_score - home_pitcher_score  # −100 to +100
        prob_shift = (edge / 50.0) * 5.0               # −10 to +10 percentage points
        new_away = away_prob + prob_shift
        new_home = home_prob - prob_shift

        # Re-normalise to ensure sum = 100
        total = new_away + new_home
        if total <= 0:
            logger.warning("apply_pitcher_adjustment: total prob <= 0 — returning 50/50")
            return 50.0, 50.0
        result_away = round(new_away / total * 100, 4)
        result_home = round(new_home / total * 100, 4)

        if prob_shift != 0:
            logger.debug(
                "apply_pitcher_adjustment: away_score=%.1f  home_score=%.1f  "
                "edge=%+.1f  prob_shift=%+.2f%%  "
                "before=%.4f%%/%.4f%%  after=%.4f%%/%.4f%%",
                away_pitcher_score, home_pitcher_score, edge, prob_shift,
                away_prob, home_prob, result_away, result_home,
            )
        else:
            logger.debug(
                "apply_pitcher_adjustment: both pitchers at %.1f/%.1f — no shift",
                away_pitcher_score, home_pitcher_score,
            )
        return result_away, result_home

    @staticmethod
    def apply_bullpen_adjustment(
        away_prob: float,
        home_prob: float,
        away_bullpen_score: float,
        home_bullpen_score: float,
    ) -> Tuple[float, float]:
        """
        Shift probabilities based on team pitching depth differential.

        Bullpen handles ~40% of innings; starters get ±10pp for ~60% of innings.
        Proportional scale: max ±4pp for bullpen (10 × 40/60 ≈ 6.67, capped lower
        to reflect pre-game uncertainty about reliever usage patterns).

        With both teams at 50 (spring training / no data): no adjustment.
        With real season stats: a 20-point quality gap → ~1.6pp probability shift.
        """
        edge = away_bullpen_score - home_bullpen_score  # -100 to +100
        prob_shift = (edge / 50.0) * 2.0               # max ±4pp at 100-point edge

        new_away = away_prob + prob_shift
        new_home = home_prob - prob_shift

        total = new_away + new_home
        if total <= 0:
            logger.warning("apply_bullpen_adjustment: total prob <= 0 — returning 50/50")
            return 50.0, 50.0

        result_away = round(new_away / total * 100, 4)
        result_home = round(new_home / total * 100, 4)

        if prob_shift != 0:
            logger.debug(
                "apply_bullpen_adjustment: away_score=%.1f  home_score=%.1f  "
                "edge=%+.1f  prob_shift=%+.2f%%  "
                "before=%.4f%%/%.4f%%  after=%.4f%%/%.4f%%",
                away_bullpen_score, home_bullpen_score, edge, prob_shift,
                away_prob, home_prob, result_away, result_home,
            )
        else:
            logger.debug(
                "apply_bullpen_adjustment: both teams at %.1f/%.1f — no shift",
                away_bullpen_score, home_bullpen_score,
            )
        return result_away, result_home

    @staticmethod
    def best_side(
        away_prob: float,
        home_prob: float,
    ) -> Tuple[str, float]:
        """
        Return which side has the edge and its true probability.
        Returns ("away"|"home", probability_pct).
        """
        if away_prob >= home_prob:
            logger.debug("best_side: away (%.4f%% > %.4f%%)", away_prob, home_prob)
            return "away", away_prob
        logger.debug("best_side: home (%.4f%% > %.4f%%)", home_prob, away_prob)
        return "home", home_prob
