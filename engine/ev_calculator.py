"""
Expected Value (EV) calculation.
EV = (probability_of_win × potential_profit) - (probability_of_loss × stake)
Stake is normalised to 1 unit.
"""

from __future__ import annotations
import logging
from typing import Optional
from config.settings import EV_ODDS_MIN, EV_ODDS_MAX

logger = logging.getLogger(__name__)


class EVCalculator:

    @staticmethod
    def decimal_from_american(american_odds: int) -> float:
        """Convert American odds to decimal (European) format."""
        if american_odds >= 0:
            return 1 + american_odds / 100
        return 1 + 100 / abs(american_odds)

    @staticmethod
    def calculate(prob_pct: float, american_odds: int) -> Optional[float]:
        """
        Compute EV% for a bet.

        Args:
            prob_pct:       true probability of winning (0–100)
            american_odds:  the odds you are betting at (e.g. -110, +130)

        Returns:
            EV as a percentage of stake, or None if odds are outside the gate.
        """
        if not (EV_ODDS_MIN <= american_odds <= EV_ODDS_MAX):
            logger.debug(
                "EVCalculator.calculate: odds %+d outside gate [%d, %d] — returning None",
                american_odds, EV_ODDS_MIN, EV_ODDS_MAX,
            )
            return None

        prob = prob_pct / 100
        decimal_odds = EVCalculator.decimal_from_american(american_odds)
        potential_profit = decimal_odds - 1       # profit per 1-unit stake

        ev = (prob * potential_profit) - ((1 - prob) * 1)
        ev_pct = round(ev * 100, 4)

        logger.debug(
            "EVCalculator.calculate: prob=%.4f%%  odds=%+d  decimal=%.4f  "
            "profit_per_unit=%.4f  EV=%.4f%%",
            prob_pct, american_odds, decimal_odds, potential_profit, ev_pct,
        )
        return ev_pct

    @staticmethod
    def is_positive_ev(prob_pct: float, american_odds: int) -> bool:
        ev = EVCalculator.calculate(prob_pct, american_odds)
        result = ev is not None and ev > 0
        logger.debug(
            "EVCalculator.is_positive_ev: prob=%.2f%%  odds=%+d  ev=%s  positive=%s",
            prob_pct, american_odds,
            f"{ev:+.4f}%" if ev is not None else "None",
            result,
        )
        return result
