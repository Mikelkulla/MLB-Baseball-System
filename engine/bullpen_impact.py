"""
BullpenImpactEngine — scores team aggregate pitching depth (0–100).

50 = league average (neutral, no adjustment).
> 50 = above-average pitching staff (quality bullpen signal).
< 50 = below-average pitching staff.

Scoring formula (FIP-heavy, fielding-independent):
    score = fip_weight × score_fip  +  k9_weight × score_k9  +  bb9_weight × score_bb9

Component weights (BullpenScoringConfig):
    FIP:  0.45 — best single predictor of true pitching quality; normalised to 0–100 scale
    K/9:  0.30 — strikeout rate; most durable pitcher skill, strong carry into bullpen
    BB/9: 0.25 — walk rate; walk control is highly consistent and predictive

ERA is excluded: contaminated by defense behind the pitcher (same rationale as starter scoring).
HR/9 is excluded at team level: noisy in small game samples, park-factor-dependent.

Sample size gate: teams with < 10 games played return 50.0 (neutral) — prevents
spring training / early-season noise from distorting probability adjustments.
"""

from __future__ import annotations
import logging
from models.bullpen import BullpenStats
from config.settings import BULLPEN_SCORING

logger = logging.getLogger(__name__)

MIN_GAMES_FOR_SCORE = 10   # gate: require meaningful sample before scoring


class BullpenImpactEngine:
    """
    Computes a 0–100 bullpen quality score from team aggregate pitching stats.
    Higher = better pitching depth.  50 = league average.
    """

    def score_and_attach(self, stats: BullpenStats) -> None:
        """Compute and store impact_score in-place on the BullpenStats object."""
        stats.impact_score = self._compute(stats)

    def _compute(self, stats: BullpenStats) -> float:
        cfg = BULLPEN_SCORING

        # Sample size gate — too few games means pre-season / early-season noise
        if stats.games < MIN_GAMES_FOR_SCORE:
            logger.debug(
                "BullpenImpact [%s]: games=%d < %d — returning neutral 50.0",
                stats.team_key, stats.games, MIN_GAMES_FOR_SCORE,
            )
            return 50.0

        components: dict[str, tuple[float, float]] = {}   # {name: (score, weight)}

        # --- FIP (lower is better → invert the scale) ---
        # league_avg_fip × 2 is the "worst acceptable" ceiling before clamping to 0
        if stats.fip is not None:
            league_avg = cfg.league_avg_fip
            raw = (league_avg * 2 - stats.fip) / (league_avg * 2) * 100
            components["fip"] = (min(100.0, max(0.0, raw)), cfg.fip_weight)

        # --- K/9 (higher is better → direct scale) ---
        if stats.k_per_9 is not None:
            league_avg = cfg.league_avg_k9
            raw = stats.k_per_9 / (league_avg * 2) * 100
            components["k9"] = (min(100.0, max(0.0, raw)), cfg.k9_weight)

        # --- BB/9 (lower is better → invert the scale) ---
        if stats.bb_per_9 is not None:
            league_avg = cfg.league_avg_bb9
            raw = (league_avg * 2 - stats.bb_per_9) / (league_avg * 2) * 100
            components["bb9"] = (min(100.0, max(0.0, raw)), cfg.bb9_weight)

        if not components:
            logger.debug(
                "BullpenImpact [%s]: no scoreable stats — returning neutral 50.0",
                stats.team_key,
            )
            return 50.0

        # Weighted average — normalise weights to what's actually available
        total_weight = sum(w for _, w in components.values())
        if total_weight == 0:
            return 50.0

        weighted_sum = sum(score * weight for score, weight in components.values())
        result = weighted_sum / total_weight
        result = round(min(100.0, max(0.0, result)), 1)

        logger.debug(
            "BullpenImpact [%s]: FIP=%s(→%.1f)  K/9=%s(→%.1f)  BB/9=%s(→%.1f)  "
            "games=%d  final_score=%.1f/100",
            stats.team_key,
            f"{stats.fip:.2f}" if stats.fip is not None else "N/A",
            components["fip"][0] if "fip" in components else 0,
            f"{stats.k_per_9:.1f}" if stats.k_per_9 is not None else "N/A",
            components["k9"][0] if "k9" in components else 0,
            f"{stats.bb_per_9:.1f}" if stats.bb_per_9 is not None else "N/A",
            components["bb9"][0] if "bb9" in components else 0,
            stats.games,
            result,
        )
        return result
