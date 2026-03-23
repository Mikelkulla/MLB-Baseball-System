"""
Game — raw data returned by the Odds API for a single MLB game.
This is the primary input object flowing through the pipeline.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class OddsLine:
    """Spread, moneyline or total for one side of a market."""
    price: int           # American odds (e.g. -110, +130)
    point: Optional[float] = None   # spread or total value


@dataclass
class GameOdds:
    """All odds markets for a single game."""
    away_ml: Optional[OddsLine] = None
    home_ml: Optional[OddsLine] = None
    away_spread: Optional[OddsLine] = None
    home_spread: Optional[OddsLine] = None
    over: Optional[OddsLine] = None
    under: Optional[OddsLine] = None

    # Opening-line snapshots (populated from CLV tracker)
    away_spread_open: Optional[float] = None
    home_spread_open: Optional[float] = None
    away_ml_open: Optional[int] = None
    home_ml_open: Optional[int] = None

    # Which bookmaker supplied each market (for raw_odds audit trail)
    ml_bookmaker: str = ""        # e.g. "draftkings"
    spread_bookmaker: str = ""    # may differ from ML if DK had no run line
    total_bookmaker: str = ""     # may differ from ML if DK had no totals

    # Multi-book consensus + best price (populated when API returns multiple bookmakers)
    # consensus_*_prob = average vig-free probability across all books (0–100)
    # best_*_ml = highest available odds for that side across all books
    consensus_away_prob: Optional[float] = None
    consensus_home_prob: Optional[float] = None
    best_away_ml: Optional[OddsLine] = None
    best_home_ml: Optional[OddsLine] = None
    best_away_book: str = ""
    best_home_book: str = ""
    book_count: int = 0


@dataclass
class Game:
    """
    Single MLB game — the core domain object that moves through every stage
    of the pipeline (data fetch → impact calculation → engine → output).
    """
    game_id: str                   # unique ID from Odds API
    sport: str = "baseball_mlb"
    away_team: str = ""            # canonical team key
    home_team: str = ""
    commence_time: Optional[datetime] = None
    venue: str = ""                # stadium name
    city: str = ""

    odds: GameOdds = field(default_factory=GameOdds)

    # Impact adjustments (populated by engine modules)
    away_injury_impact: float = 0.0    # probability % delta (negative = hurts)
    home_injury_impact: float = 0.0
    weather_over_adj: float = 0.0      # points added/subtracted from O/U line
    weather_under_adj: float = 0.0
    sp_gate_blocked: bool = False      # True if probable SP is Out/Doubtful

    # Sharp splits (from DraftKings)
    # Default 50.0 = neutral (no data available); 0 would penalise, not abstain
    sharp_split_score: float = 50.0
    away_handle_pct: float = 50.0
    home_handle_pct: float = 50.0
    away_bets_pct: float = 50.0       # ML bets% for picked-side SharpSplit calc
    home_bets_pct: float = 50.0
    over_handle_pct: float = 0.0
    under_handle_pct: float = 0.0

    # Pitcher impact scores (0–100 per team)
    away_pitcher_score: float = 50.0
    home_pitcher_score: float = 50.0
    away_pitcher_name: str = "TBD"
    home_pitcher_name: str = "TBD"

    # Bullpen / pitching depth scores (0–100 per team, team aggregate pitching proxy)
    # Default 50.0 = neutral; below 10 games played returns 50 (spring training gate)
    away_bullpen_score: float = 50.0
    home_bullpen_score: float = 50.0

    # Weather snapshot
    temperature_f: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    wind_direction: str = ""
    precipitation: str = ""           # "none", "light", "heavy"
    is_dome: bool = False
