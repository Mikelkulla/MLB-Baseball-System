"""
Bet — a logged bet entry, mirroring the BETS_LOG sheet from V8.0.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class BetResult(str, Enum):
    ACTIVE   = "ACTIVE"
    WON      = "WON"
    LOST     = "LOST"
    PUSH     = "PUSH"
    VOID     = "VOID"
    PASS_CLV = "PASS_CLV"    # bet skipped due to negative CLV


class CLVBand(str, Enum):
    GOOD      = "GOOD"        # CLV >= 0
    MINUS_05  = "MINUS_0.5"
    MINUS_1   = "MINUS_1"
    MINUS_15  = "MINUS_1.5"
    PASS_2    = "PASS_MINUS_2"


@dataclass
class Bet:
    """
    One logged bet. 28 columns matching V8.0 BETS_LOG schema.
    """
    bet_id: str
    sport: str = "baseball_mlb"
    game_date: Optional[datetime] = None
    matchup: str = ""

    picked_team: str = ""          # "away" or "home"
    picked_team_name: str = ""
    bet_type: str = "MONEYLINE"

    units: float = 0.0             # units at lock time
    prediction_text: str = ""
    status_tier: str = "GOLD"      # ELITE / STRONGEST / BEST BET / GOLD

    ev_pct: float = 0.0
    confidence_pct: float = 0.0
    prob_pct: float = 0.0

    # Odds tracking
    open_spread: Optional[float] = None
    open_price: Optional[int] = None
    bet_spread: Optional[float] = None
    bet_price: Optional[int] = None
    current_price: Optional[int] = None

    # CLV
    clv_pct: float = 0.0
    adj_units: float = 0.0         # units after CLV scaling
    clv_band: CLVBand = CLVBand.GOOD
    key_number_crossed: bool = False   # 3/4/6/7/10 crossed

    # Outcome
    placed_at: datetime = field(default_factory=datetime.utcnow)
    result: BetResult = BetResult.ACTIVE
    pnl: float = 0.0              # profit/loss in units
    notes: str = ""

    def update_clv(self, current_price: int) -> None:
        """Recompute CLV and CLV band given a fresh current price."""
        if self.bet_price is None or current_price is None:
            return
        self.current_price = current_price

        # CLV % = (1/current_price_decimal) - (1/bet_price_decimal)
        def to_decimal(american: int) -> float:
            if american >= 0:
                return 1 + american / 100
            return 1 + 100 / abs(american)

        self.clv_pct = round(
            (1 / to_decimal(self.bet_price) - 1 / to_decimal(current_price)) * 100, 2
        )
        # Classify band
        if self.clv_pct >= 0:
            self.clv_band = CLVBand.GOOD
        elif self.clv_pct >= -0.5:
            self.clv_band = CLVBand.MINUS_05
        elif self.clv_pct >= -1.0:
            self.clv_band = CLVBand.MINUS_1
        elif self.clv_pct >= -1.5:
            self.clv_band = CLVBand.MINUS_15
        else:
            self.clv_band = CLVBand.PASS_2

    def to_dict(self) -> dict:
        return {
            "bet_id": self.bet_id,
            "sport": self.sport,
            "game_date": self.game_date.isoformat() if self.game_date else "",
            "matchup": self.matchup,
            "picked_team": self.picked_team,
            "picked_team_name": self.picked_team_name,
            "bet_type": self.bet_type,
            "units": self.units,
            "prediction_text": self.prediction_text,
            "status_tier": self.status_tier,
            "ev_pct": self.ev_pct,
            "confidence_pct": self.confidence_pct,
            "prob_pct": self.prob_pct,
            "open_spread": self.open_spread,
            "open_price": self.open_price,
            "bet_spread": self.bet_spread,
            "bet_price": self.bet_price,
            "current_price": self.current_price,
            "clv_pct": self.clv_pct,
            "adj_units": self.adj_units,
            "clv_band": self.clv_band.value,
            "key_number_crossed": self.key_number_crossed,
            "placed_at": self.placed_at.isoformat(),
            "result": self.result.value,
            "pnl": self.pnl,
            "notes": self.notes,
        }
