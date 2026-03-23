"""
Pitcher Impact Engine — MLB Phase D (new module, no equivalent in V8.0).

Scores a probable starting pitcher on a 0–100 scale.
  50 = league-average pitcher
  > 50 = above average (advantage for their team)
  < 50 = below average (disadvantage)

The pitcher score feeds into the confidence formula as an additional
weighted component, and influences O/U probability (high-quality pitching
matchup pushes toward Under).
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

    def _score_era(self, era: Optional[float]) -> float:
        if era is None:
            logger.debug("  _score_era: None → 50.0 (neutral)")
            return 50.0
        # ERA: lower is better. League avg ~4.20. Scale: 0.00 → 100, 8.40 → 0.
        normalized = (self.cfg.league_avg_era * 2 - era) / (self.cfg.league_avg_era * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_era: ERA=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            era, self.cfg.league_avg_era, normalized, result,
        )
        return result

    def _score_whip(self, whip: Optional[float]) -> float:
        if whip is None:
            logger.debug("  _score_whip: None → 50.0 (neutral)")
            return 50.0
        # WHIP: lower is better. League avg ~1.30. Scale: 0.00 → 100, 2.60 → 0.
        normalized = (self.cfg.league_avg_whip * 2 - whip) / (self.cfg.league_avg_whip * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_whip: WHIP=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            whip, self.cfg.league_avg_whip, normalized, result,
        )
        return result

    def _score_k9(self, k9: Optional[float]) -> float:
        if k9 is None:
            logger.debug("  _score_k9: None → 50.0 (neutral)")
            return 50.0
        # K/9: higher is better. League avg ~8.8. Scale: 0 → 0, 17.6 → 100.
        normalized = k9 / (self.cfg.league_avg_k9 * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_k9: K/9=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            k9, self.cfg.league_avg_k9, normalized, result,
        )
        return result

    def _score_bb9(self, bb9: Optional[float]) -> float:
        if bb9 is None:
            logger.debug("  _score_bb9: None → 50.0 (neutral)")
            return 50.0
        # BB/9: lower is better. League avg ~3.1. Scale: 0.0 → 100, 6.2 → 0.
        normalized = (self.cfg.league_avg_bb9 * 2 - bb9) / (self.cfg.league_avg_bb9 * 2)
        result = round(max(0.0, min(100.0, normalized * 100)), 2)
        logger.debug(
            "  _score_bb9: BB/9=%.2f  league_avg=%.2f  normalized=%.4f  score=%.2f",
            bb9, self.cfg.league_avg_bb9, normalized, result,
        )
        return result

    def _score_recent_era(self, recent_era: Optional[float]) -> float:
        """Score last 3 starts ERA — same formula as season ERA scorer."""
        if recent_era is None:
            logger.debug("  _score_recent_era: None → 50.0 (neutral)")
            return 50.0
        result = self._score_era(recent_era)
        logger.debug("  _score_recent_era: recent_ERA=%.2f → score=%.2f", recent_era, result)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, pitcher: PitcherStats) -> float:
        """
        Compute a 0–100 impact score for a pitcher.
        Returns 50.0 if TBD (unknown starter).
        """
        if pitcher.is_tbd:
            logger.debug("PitcherImpactEngine.score: %s is TBD → 50.0 (neutral)", pitcher.name)
            return 50.0

        logger.debug(
            "PitcherImpactEngine.score: %s — ERA=%.2f  WHIP=%.2f  K/9=%.2f  BB/9=%.2f  "
            "recent_ERA=%s  W=%d  L=%d  IP=%.1f",
            pitcher.name,
            pitcher.era or 0.0,
            pitcher.whip or 0.0,
            pitcher.k_per_9 or 0.0,
            pitcher.bb_per_9 or 0.0,
            f"{pitcher.recent_era:.2f}" if pitcher.recent_era is not None else "N/A",
            pitcher.wins or 0,
            pitcher.losses or 0,
            pitcher.innings_pitched or 0.0,
        )

        cfg = self.cfg
        era_s   = self._score_era(pitcher.era)
        whip_s  = self._score_whip(pitcher.whip)
        k9_s    = self._score_k9(pitcher.k_per_9)
        bb9_s   = self._score_bb9(pitcher.bb_per_9)
        rec_s   = self._score_recent_era(pitcher.recent_era)

        composite = (
            era_s   * cfg.era_weight        +
            whip_s  * cfg.whip_weight       +
            k9_s    * cfg.k9_weight         +
            bb9_s   * cfg.bb9_weight        +
            rec_s   * cfg.recent_form_weight
        )
        result = round(max(0.0, min(100.0, composite)), 2)

        logger.debug(
            "PitcherImpactEngine.score: %s — "
            "ERA=%.2f×%.2f  WHIP=%.2f×%.2f  K9=%.2f×%.2f  BB9=%.2f×%.2f  "
            "RecERA=%.2f×%.2f  composite=%.4f  final=%.2f",
            pitcher.name,
            era_s,  cfg.era_weight,
            whip_s, cfg.whip_weight,
            k9_s,   cfg.k9_weight,
            bb9_s,  cfg.bb9_weight,
            rec_s,  cfg.recent_form_weight,
            composite, result,
        )
        return result

    def score_and_attach(self, pitcher: PitcherStats) -> PitcherStats:
        """Score and write the result back onto the PitcherStats object."""
        pitcher.impact_score = self.score(pitcher)
        logger.info(
            "Pitcher scored: %s — score=%.2f/100  ERA=%s  WHIP=%s  K/9=%s",
            pitcher.name,
            pitcher.impact_score,
            f"{pitcher.era:.2f}" if pitcher.era is not None else "N/A",
            f"{pitcher.whip:.2f}" if pitcher.whip is not None else "N/A",
            f"{pitcher.k_per_9:.1f}" if pitcher.k_per_9 is not None else "N/A",
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
