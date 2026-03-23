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

    # Season stats — raw (used for FIP calculation and display)
    era: Optional[float] = None          # ERA — kept for display only; NOT used in scoring
    whip: Optional[float] = None         # WHIP — kept for display only; NOT used in scoring
    k_per_9: Optional[float] = None      # K/9 — fielding independent, used in scoring
    bb_per_9: Optional[float] = None     # BB/9 — fielding independent, used in scoring
    hr_per_9: Optional[float] = None     # HR/9 — directly from API (homeRunsPer9 field)
    innings_pitched: Optional[float] = None
    wins: int = 0
    losses: int = 0

    # Raw counting stats (fetched to calculate FIP)
    home_runs: Optional[int] = None      # HR allowed (for FIP formula)
    walks: Optional[int] = None          # BB (for FIP formula)
    hit_batsmen: Optional[int] = None    # HBP (for FIP formula)
    strikeouts: Optional[int] = None     # K (for FIP formula)

    # Computed FIP (Fielding Independent Pitching) — calculated in pitcher_client
    # FIP = ((13×HR) + (3×(BB+HBP)) - (2×K)) / IP + FIP_constant
    # Same scale as ERA by construction. Lower = better.
    fip: Optional[float] = None

    # Last 3 starts ERA (recent form signal — small sample, low weight)
    recent_era: Optional[float] = None

    # Computed impact score (0–100) set by PitcherImpactEngine
    impact_score: float = 50.0   # 50 = league average baseline
