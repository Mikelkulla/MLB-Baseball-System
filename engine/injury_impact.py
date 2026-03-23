"""
Injury impact engine for MLB.

Computes a probability delta for each team based on injured players,
their positions, injury status severity, and diminishing returns
when multiple players at the same position are affected.

SP gate logic: if the probable starting pitcher (SP) is Out or Doubtful,
the sp_gate_blocked flag is set → units zeroed by ConfidenceEngine.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
from config.mlb_config import (
    MLB_POSITION_WEIGHTS,
    INJURY_STATUS_MULTIPLIERS,
    SP_GATE_STATUSES,
)

logger = logging.getLogger(__name__)


@dataclass
class InjuredPlayer:
    name: str
    team_key: str
    position: str       # e.g. "SP", "SS", "3B"
    status: str         # e.g. "out", "questionable"
    is_probable_starter: bool = False   # True if this player is today's SP


@dataclass
class InjuryImpactResult:
    away_impact: float         # probability delta for away team (negative = disadvantage)
    home_impact: float
    away_sp_blocked: bool
    home_sp_blocked: bool


class InjuryImpactEngine:
    """
    Mirrors the position-weight + status-multiplier + diminishing-returns
    model from V8.0 utils_injury_impact.js, adapted for MLB.
    """

    # Diminishing returns for multiple players at the same position
    DIMINISHING_FACTORS = [1.0, 0.5, 0.25, 0.125]

    # Maximum cumulative impact cap per team (probability %)
    MAX_TEAM_IMPACT = 12.0

    def _player_delta(self, player: InjuredPlayer) -> float:
        pos = player.position.upper()
        pos_weight = MLB_POSITION_WEIGHTS.get(pos, 0.5)
        status_mult = INJURY_STATUS_MULTIPLIERS.get(player.status.lower(), 0.0)
        delta = pos_weight * status_mult
        logger.debug(
            "  player_delta: %s (%s/%s) — pos_weight=%.2f  status_mult=%.2f  delta=%.4f",
            player.name, pos, player.status, pos_weight, status_mult, delta,
        )
        return delta

    def calculate(
        self,
        away_injured: list[InjuredPlayer],
        home_injured: list[InjuredPlayer],
        away_sp: Optional[InjuredPlayer] = None,
        home_sp: Optional[InjuredPlayer] = None,
    ) -> InjuryImpactResult:
        """
        Compute injury impact for both teams.

        Positive impact = good for the team (opponent has injuries).
        Negative impact = bad for the team (they have injuries).
        We report the team's own injury delta (negative = they are hurt).
        """
        logger.debug(
            "InjuryImpactEngine.calculate — away: %d injured  home: %d injured  "
            "away_sp=%s  home_sp=%s",
            len(away_injured), len(home_injured),
            f"{away_sp.name}/{away_sp.status}" if away_sp else "None",
            f"{home_sp.name}/{home_sp.status}" if home_sp else "None",
        )

        if away_injured:
            logger.debug("Away injured players:")
            away_impact_raw = self._team_impact(away_injured, "away")
        else:
            logger.debug("Away: no injured players")
            away_impact_raw = 0.0

        if home_injured:
            logger.debug("Home injured players:")
            home_impact_raw = self._team_impact(home_injured, "home")
        else:
            logger.debug("Home: no injured players")
            home_impact_raw = 0.0

        # SP gate check
        away_sp_blocked = (
            away_sp is not None
            and away_sp.status.lower() in SP_GATE_STATUSES
        )
        home_sp_blocked = (
            home_sp is not None
            and home_sp.status.lower() in SP_GATE_STATUSES
        )

        if away_sp_blocked:
            logger.warning(
                "SP GATE: away starter %s is '%s' → sp_gate_blocked",
                away_sp.name, away_sp.status,
            )
        if home_sp_blocked:
            logger.warning(
                "SP GATE: home starter %s is '%s' → sp_gate_blocked",
                home_sp.name, home_sp.status,
            )

        result = InjuryImpactResult(
            away_impact=-away_impact_raw,   # negative = away team is hurt
            home_impact=-home_impact_raw,
            away_sp_blocked=away_sp_blocked,
            home_sp_blocked=home_sp_blocked,
        )
        logger.debug(
            "InjuryImpactEngine result — away_impact=%+.4f  home_impact=%+.4f  "
            "away_sp_blocked=%s  home_sp_blocked=%s",
            result.away_impact, result.home_impact,
            result.away_sp_blocked, result.home_sp_blocked,
        )
        return result

    def _team_impact(self, injured: list[InjuredPlayer], side_label: str = "") -> float:
        """
        Sum position-weighted impact with diminishing returns per position.
        Cap at MAX_TEAM_IMPACT.
        """
        position_counts: dict[str, int] = {}
        total = 0.0

        for player in injured:
            pos = player.position.upper()
            count = position_counts.get(pos, 0)
            factor = self.DIMINISHING_FACTORS[min(count, len(self.DIMINISHING_FACTORS) - 1)]
            base_delta = self._player_delta(player)
            contribution = base_delta * factor
            total += contribution
            position_counts[pos] = count + 1
            if factor < 1.0:
                logger.debug(
                    "  diminishing returns at pos %s (count=%d) — factor=%.3f  "
                    "contribution=%.4f (base=%.4f)",
                    pos, count + 1, factor, contribution, base_delta,
                )

        capped = round(min(total, self.MAX_TEAM_IMPACT), 4)
        if total > self.MAX_TEAM_IMPACT:
            logger.debug(
                "  %s team impact capped: raw=%.4f → %.4f (MAX_TEAM_IMPACT=%.1f)",
                side_label, total, capped, self.MAX_TEAM_IMPACT,
            )
        else:
            logger.debug(
                "  %s team impact total: %.4f (no cap applied)",
                side_label, capped,
            )
        return capped
