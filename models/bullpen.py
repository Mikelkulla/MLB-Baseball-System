"""
BullpenStats — aggregate pitching quality for one team.
Populated by BullpenClient and scored by BullpenImpactEngine.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class BullpenStats:
    """
    Team-level aggregate pitching stats.
    Used as a proxy for bullpen quality — teams with low team FIP/ERA
    typically have quality bullpens in addition to good starters.
    The probable starter is scored separately; this captures overall staff depth.
    """
    team_key: str

    # Aggregate pitching stats (whole staff, starters + relievers combined)
    era: Optional[float] = None
    k_per_9: Optional[float] = None
    bb_per_9: Optional[float] = None
    hr_per_9: Optional[float] = None
    fip: Optional[float] = None     # calculated from raw counts: ((13×HR)+(3×(BB+HBP))-(2×K))/IP + 3.17
    games: int = 0                  # games played this season (sample size gate)

    # Computed impact score (0–100, 50 = league average neutral)
    impact_score: float = 50.0
