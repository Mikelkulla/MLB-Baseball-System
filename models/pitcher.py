"""
Pitcher — probable starter stats fetched from an external source.
Used exclusively by the pitcher impact engine.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class PitcherStats:
    """
    Season and recent stats for a probable starting pitcher.
    All rate stats are per 9 innings unless noted.
    """
    name: str
    team_key: str
    hand: str = "R"           # "R" or "L"
    is_tbd: bool = False      # True when starter is not yet announced

    # Season stats
    era: Optional[float] = None
    whip: Optional[float] = None
    k_per_9: Optional[float] = None
    bb_per_9: Optional[float] = None
    innings_pitched: Optional[float] = None
    wins: int = 0
    losses: int = 0

    # Last 3 starts ERA (recent form)
    recent_era: Optional[float] = None

    # Computed impact score (0–100) set by PitcherImpactEngine
    impact_score: float = 50.0   # 50 = league average baseline
