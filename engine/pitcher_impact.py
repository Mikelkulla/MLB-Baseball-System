"""
Pitcher Impact Engine — scores a probable starting pitcher on a 0–100 scale.

  50 = league-average pitcher (neutral — no probability shift)
  > 50 = above average (advantage for their team)
  < 50 = below average (disadvantage)

Formula (all components are fielding-independent):
    score = FIP   × 0.40   ← primary metric; best single predictor of future ERA
          + K/9   × 0.25   ← strikeout rate; most durable and talent-consistent skill
          + BB/9  × 0.20   ← walk control; highly consistent year-to-year
          + HR/9  × 0.10   ← home run tendency; real but partly park/luck noise
          + recent ERA × 0.05  ← last-3-starts form signal; small sample, low weight

ERA and WHIP are intentionally excluded:
  ERA  — contaminated by the defense behind the pitcher (hits-in-play results)
  WHIP — same issue: H/(BB+H) inflates/deflates based on defensive quality
  Both are stored and displayed for reference only.

Research basis:
  FanGraphs (2024): FIP is a better predictor of next-season ERA than ERA itself.
  FanGraphs (2024): xFIP > FIP > ERA as future-performance predictors.
  FanGraphs: Standalone K/9 and BB/9 have additional predictive value beyond FIP.
  We use FIP (not xFIP) because fly-ball data is not available from MLB Stats API.
"""

from __future__ import annotations
import logging
from typing import Optional
from config.settings import PITCHER_SCORING, PitcherScoringConfig
from models.pitcher import PitcherStats

logger = logging.getLogger(__name__)


class PitcherImpactEngine:
    """
    Converts raw pitcher stats into a normalised 0–100 impact score.

    Each stat is scored independently (0–100 relative to league average),
    then combined using the weights in settings.PITCHER_SCORING.
    """

    def __init__(self, config: PitcherScoringConfig = PITCHER_SCORING):
        self.cfg = config

    # ------------------------------------------------------------------
    # Individual stat scorers
    # Each returns 0–100 where 100 = best possible, 50 = league average
    # ------------------------------------------------------------------

    def _score_fip(self, fip: Optional[float]) -> float:
        """
        Score FIP (Fielding Independent Pitching).
        FIP is on the ERA scale (lower = better).
        League avg FIP ≈ 4.20 (calibrated to match ERA scale by the FIP constant).
        Scale: FIP 0.00 → 100,  FIP = 2×league_avg → 0.
        """
        if fip is None:
            logger.debug("  _score_fip: None → 50.0 (neutral)")
            return 50.0
        # Identical normalisation to ERA: lower is better, scaled around 2× league avg
        normalized = (self.cfg.league_avg_fip * 2 - fip) / (self.cfg.league_avg_fip * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_fip: FIP=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            fip, self.cfg.league_avg_fip, normalized, result,
        )
        return result

    def _score_k9(self, k9: Optional[float]) -> float:
        """
        Score K/9 (Strikeouts per 9 innings).
        Higher is better. League avg ≈ 8.80.
        Scale: K/9 0 → 0,  K/9 = 2×league_avg → 100.
        """
        if k9 is None:
            logger.debug("  _score_k9: None → 50.0 (neutral)")
            return 50.0
        normalized = k9 / (self.cfg.league_avg_k9 * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_k9: K/9=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            k9, self.cfg.league_avg_k9, normalized, result,
        )
        return result

    def _score_bb9(self, bb9: Optional[float]) -> float:
        """
        Score BB/9 (Walks per 9 innings).
        Lower is better. League avg ≈ 3.10.
        Scale: BB/9 0.00 → 100,  BB/9 = 2×league_avg → 0.
        """
        if bb9 is None:
            logger.debug("  _score_bb9: None → 50.0 (neutral)")
            return 50.0
        normalized = (self.cfg.league_avg_bb9 * 2 - bb9) / (self.cfg.league_avg_bb9 * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_bb9: BB/9=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            bb9, self.cfg.league_avg_bb9, normalized, result,
        )
        return result

    def _score_hr9(self, hr9: Optional[float]) -> float:
        """
        Score HR/9 (Home Runs per 9 innings).
        Lower is better. League avg ≈ 1.15 (Baseball-Reference 2024).
        Scale: HR/9 0.00 → 100,  HR/9 = 2×league_avg → 0.
        """
        if hr9 is None:
            logger.debug("  _score_hr9: None → 50.0 (neutral)")
            return 50.0
        normalized = (self.cfg.league_avg_hr9 * 2 - hr9) / (self.cfg.league_avg_hr9 * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_hr9: HR/9=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            hr9, self.cfg.league_avg_hr9, normalized, result,
        )
        return result

    def _score_recent_era(self, recent_era: Optional[float]) -> float:
        """
        Score last-3-starts ERA as a form signal.
        Uses the same normalisation as FIP (same scale).
        Small sample (~15-18 IP) → used only for recency signal at 5% weight.
        """
        if recent_era is None:
            logger.debug("  _score_recent_era: None → 50.0 (neutral)")
            return 50.0
        # Normalise against FIP league average (same ERA scale)
        normalized = (self.cfg.league_avg_fip * 2 - recent_era) / (self.cfg.league_avg_fip * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug("  _score_recent_era: recent_ERA=%.2f → score=%.2f", recent_era, result)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, pitcher: PitcherStats) -> float:
        """
        Compute a 0–100 impact score for a pitcher.
        Returns 50.0 (neutral) for TBD starters or when stats unavailable.
        """
        if pitcher.is_tbd:
            logger.debug("PitcherImpactEngine.score: %s is TBD → 50.0 (neutral)", pitcher.name)
            return 50.0

        logger.debug(
            "PitcherImpactEngine.score: %s — "
            "FIP=%s  K/9=%s  BB/9=%s  HR/9=%s  recent_ERA=%s  "
            "(ERA=%s WHIP=%s — display only, not scored)",
            pitcher.name,
            f"{pitcher.fip:.2f}"       if pitcher.fip      is not None else "N/A",
            f"{pitcher.k_per_9:.2f}"   if pitcher.k_per_9  is not None else "N/A",
            f"{pitcher.bb_per_9:.2f}"  if pitcher.bb_per_9 is not None else "N/A",
            f"{pitcher.hr_per_9:.2f}"  if pitcher.hr_per_9 is not None else "N/A",
            f"{pitcher.recent_era:.2f}" if pitcher.recent_era is not None else "N/A",
            f"{pitcher.era:.2f}"       if pitcher.era       is not None else "N/A",
            f"{pitcher.whip:.2f}"      if pitcher.whip      is not None else "N/A",
        )

        cfg = self.cfg
        fip_s    = self._score_fip(pitcher.fip)
        k9_s     = self._score_k9(pitcher.k_per_9)
        bb9_s    = self._score_bb9(pitcher.bb_per_9)
        hr9_s    = self._score_hr9(pitcher.hr_per_9)
        recent_s = self._score_recent_era(pitcher.recent_era)

        composite = (
            fip_s    * cfg.fip_weight         +
            k9_s     * cfg.k9_weight          +
            bb9_s    * cfg.bb9_weight         +
            hr9_s    * cfg.hr9_weight         +
            recent_s * cfg.recent_form_weight
        )
        result = round(max(0.0, min(100.0, composite)), 2)

        logger.debug(
            "PitcherImpactEngine.score: %s — "
            "FIP=%.2f×%.2f  K9=%.2f×%.2f  BB9=%.2f×%.2f  HR9=%.2f×%.2f  "
            "Rec=%.2f×%.2f  composite=%.4f  final=%.2f",
            pitcher.name,
            fip_s,    cfg.fip_weight,
            k9_s,     cfg.k9_weight,
            bb9_s,    cfg.bb9_weight,
            hr9_s,    cfg.hr9_weight,
            recent_s, cfg.recent_form_weight,
            composite, result,
        )
        return result

    def score_and_attach(self, pitcher: PitcherStats) -> PitcherStats:
        """Score and write the result back onto the PitcherStats object."""
        pitcher.impact_score = self.score(pitcher)
        logger.info(
            "Pitcher scored: %s — score=%.2f/100  FIP=%s  K/9=%s  BB/9=%s  HR/9=%s  "
            "(ERA=%s WHIP=%s — display only)",
            pitcher.name,
            pitcher.impact_score,
            f"{pitcher.fip:.2f}"      if pitcher.fip      is not None else "N/A",
            f"{pitcher.k_per_9:.1f}"  if pitcher.k_per_9  is not None else "N/A",
            f"{pitcher.bb_per_9:.1f}" if pitcher.bb_per_9 is not None else "N/A",
            f"{pitcher.hr_per_9:.2f}" if pitcher.hr_per_9 is not None else "N/A",
            f"{pitcher.era:.2f}"      if pitcher.era       is not None else "N/A",
            f"{pitcher.whip:.2f}"     if pitcher.whip      is not None else "N/A",
        )
        return pitcher

    def pitcher_ou_adjustment(
        self,
        away_score: float,
        home_score: float,
    ) -> float:
        """
        Combined O/U adjustment from the pitching matchup.
        Average pitcher score > 50 → better pitching → push toward Under.
        Returns negative value = adjustment toward Under.

        Scale: at 100/100 both pitchers → -2.5 pts (very strong matchup).
        """
        avg_score = (away_score + home_score) / 2
        edge = avg_score - 50.0     # positive = above average pitching
        # 50-point edge = -2.5 pts Under adjustment
        adj = -(edge / 50.0) * 2.5
        result = round(adj, 2)
        logger.debug(
            "pitcher_ou_adjustment: away=%.2f  home=%.2f  avg=%.2f  edge=%+.2f  adj=%+.2f pts",
            away_score, home_score, avg_score, edge, result,
        )
        return result

    def confidence_adjustment(
        self,
        picked_side: str,
        away_score: float,
        home_score: float,
    ) -> float:
        """
        Confidence delta based on pitching advantage for the picked side.
        Picked team has better SP → positive boost.
        Opponent has better SP → negative penalty.
        Returns delta in confidence percentage points (max ±8).
        """
        if picked_side == "away":
            edge = away_score - home_score
        else:
            edge = home_score - away_score
        # 50-point edge → ±8 confidence pts
        result = round((edge / 50.0) * 8.0, 2)
        logger.debug(
            "confidence_adjustment: side=%s  away=%.2f  home=%.2f  edge=%+.2f  adj=%+.2f pts",
            picked_side, away_score, home_score, edge, result,
        )
        return result
