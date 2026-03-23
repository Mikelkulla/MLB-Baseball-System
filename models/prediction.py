"""
Prediction — the output object produced by the engine for each game.
One Prediction per game; contains all metrics needed for display and logging.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Prediction:
    """
    Final pick produced by the engine for a single MLB game.
    Mirrors the NFL_Model / NBA_Model column structure from V8.0.
    """
    game_id: str
    sport: str = "baseball_mlb"
    game_date: Optional[datetime] = None
    matchup: str = ""              # "Away vs Home"

    # Picked side
    picked_team: str = ""          # "away" or "home"
    picked_team_name: str = ""     # e.g. "New York Yankees"
    bet_type: str = "MONEYLINE"    # MLB primary is ML, not spread

    # Raw odds (all sides — for Model page display)
    away_ml: Optional[int] = None          # Away moneyline odds
    home_ml: Optional[int] = None          # Home moneyline odds
    away_spread: Optional[float] = None    # Away spread point
    home_spread: Optional[float] = None    # Home spread point
    total_line: Optional[float] = None     # O/U total

    # Picked side
    open_spread: Optional[float] = None
    current_spread: Optional[float] = None
    bet_price: Optional[int] = None        # American odds of picked side ML (best available book)
    best_book: str = ""                    # Bookmaker offering the best price
    book_count: int = 0                    # Number of books used for consensus probability

    # Both-side metrics (V8.0 shows Away and Home separately)
    away_prob_pct: float = 0.0     # Vig-free + pitcher-adjusted probability for away
    home_prob_pct: float = 0.0     # Vig-free + pitcher-adjusted probability for home
    away_ev_pct: Optional[float] = None  # EV% for away side (None = outside odds gate)
    home_ev_pct: Optional[float] = None  # EV% for home side

    # Core metrics (picked side)
    prob_pct: float = 0.0          # Picked side probability %
    ev_pct: float = 0.0            # Picked side expected value %
    confidence_pct: float = 0.0    # Weighted confidence score
    units: float = 0.0             # Recommended unit size

    # Tier classification
    status: str = "PASS"           # ELITE / STRONGEST / BEST BET / GOLD / PASS
    safe_units: float = 0.0        # Units after all gates applied

    # CLV
    clv_delta: float = 0.0         # Current spread vs opening spread

    # Component scores (for transparency)
    sharp_split_score: float = 0.0
    away_pitcher_name: str = "TBD"
    away_pitcher_score: float = 50.0
    home_pitcher_name: str = "TBD"
    home_pitcher_score: float = 50.0
    away_injury_impact: float = 0.0
    home_injury_impact: float = 0.0
    weather_over_adj: float = 0.0
    weather_under_adj: float = 0.0

    # Gate flags
    sp_gate_blocked: bool = False

    # Human-readable summary
    prediction_text: str = ""

    # Timestamp
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def is_qualified(self) -> bool:
        """Returns True if this pick should appear in Live Predictions."""
        return self.status in {"ELITE", "STRONGEST", "BEST BET", "GOLD"} and not self.sp_gate_blocked

    def to_dict(self) -> dict:
        """Serialize to a flat dict for CSV/JSON output."""
        return {
            "game_id": self.game_id,
            "sport": self.sport,
            "game_date": self.game_date.isoformat() if self.game_date else "",
            "matchup": self.matchup,
            # Raw odds
            "away_ml": self.away_ml,
            "home_ml": self.home_ml,
            "away_spread": self.away_spread,
            "home_spread": self.home_spread,
            "total_line": self.total_line,
            # Picked side
            "picked_team": self.picked_team,
            "picked_team_name": self.picked_team_name,
            "bet_type": self.bet_type,
            "bet_price": self.bet_price,
            "best_book": self.best_book,
            "book_count": self.book_count,
            # Both-side metrics
            "away_prob_pct": round(self.away_prob_pct, 2),
            "home_prob_pct": round(self.home_prob_pct, 2),
            "away_ev_pct": round(self.away_ev_pct, 2) if self.away_ev_pct is not None else None,
            "home_ev_pct": round(self.home_ev_pct, 2) if self.home_ev_pct is not None else None,
            # Picked side metrics
            "prob_pct": round(self.prob_pct, 2),
            "ev_pct": round(self.ev_pct, 2),
            "confidence_pct": round(self.confidence_pct, 2),
            "units": self.units,
            "status": self.status,
            "safe_units": self.safe_units,
            "clv_delta": round(self.clv_delta, 2),
            "sharp_split_score": round(self.sharp_split_score, 1),
            # Pitchers
            "away_pitcher_name": self.away_pitcher_name,
            "away_pitcher_score": round(self.away_pitcher_score, 1),
            "home_pitcher_name": self.home_pitcher_name,
            "home_pitcher_score": round(self.home_pitcher_score, 1),
            # Injuries / weather
            "away_injury_impact": round(self.away_injury_impact, 2),
            "home_injury_impact": round(self.home_injury_impact, 2),
            "weather_over_adj": round(self.weather_over_adj, 2),
            "weather_under_adj": round(self.weather_under_adj, 2),
            # Gates
            "sp_gate_blocked": self.sp_gate_blocked,
            "prediction_text": self.prediction_text,
            "generated_at": self.generated_at.isoformat(),
        }
