"""
Ballpark run factors for all 30 MLB parks.

A factor > 1.0 means the park inflates scoring relative to league average.
A factor < 1.0 means the park suppresses scoring.
Factor = 1.00 is league average.

Source: multi-year composite park factors (2021-2024 average).
These affect the O/U confidence weight. A high-factor park at Coors (1.38)
adds weight to the Over; a pitcher's park like Petco (0.88) adds weight
to the Under — independent of the weather adjustments.

Scale: 1.00 = neutral. Range in MLB is roughly 0.85 – 1.40.
"""

from __future__ import annotations
from typing import Dict


# team_key → run factor
BALLPARK_RUN_FACTORS: Dict[str, float] = {
    "baltimore_orioles":     1.02,
    "boston_red_sox":        1.10,   # Fenway — Green Monster boosts doubles/HR
    "new_york_yankees":      1.04,
    "tampa_bay_rays":        0.94,
    "toronto_blue_jays":     1.01,

    "chicago_white_sox":     1.03,
    "cleveland_guardians":   0.97,
    "detroit_tigers":        0.95,
    "kansas_city_royals":    0.99,
    "minnesota_twins":       1.01,

    "houston_astros":        0.96,
    "los_angeles_angels":    1.05,
    "athletics":             0.92,   # Oakland Coliseum — deep gaps suppress HR
    "seattle_mariners":      0.93,
    "texas_rangers":         1.07,   # Globe Life Field — hitter-friendly

    "atlanta_braves":        1.00,
    "miami_marlins":         0.94,
    "new_york_mets":         0.96,
    "philadelphia_phillies": 1.08,   # Citizens Bank — notorious HR park
    "washington_nationals":  1.00,

    "chicago_cubs":          1.06,   # Wrigley — wind-sensitive
    "cincinnati_reds":       1.07,   # Great American — short porch
    "milwaukee_brewers":     1.01,
    "pittsburgh_pirates":    0.98,
    "st_louis_cardinals":    0.97,

    "arizona_diamondbacks":  1.04,   # Chase Field — altitude + dry air
    "colorado_rockies":      1.38,   # Coors Field — extreme altitude
    "los_angeles_dodgers":   0.96,
    "san_diego_padres":      0.88,   # Petco — most pitcher-friendly in NL
    "san_francisco_giants":  0.91,   # Oracle — wind off bay suppresses scoring
}

LEAGUE_AVERAGE_FACTOR = 1.00


def get_park_factor(team_key: str) -> float:
    """Return run factor for a team's home park; defaults to 1.00 if unknown."""
    return BALLPARK_RUN_FACTORS.get(team_key, LEAGUE_AVERAGE_FACTOR)


def park_ou_adjustment(home_team_key: str) -> float:
    """
    Returns a points adjustment to the O/U line based on park factor.
    Coors Field (+1.38) → +2.0 pts toward Over; Petco (0.88) → -1.5 pts.

    Formula: (factor - 1.0) * SENSITIVITY
    SENSITIVITY is calibrated so Coors ~= +2.0 and Petco ~= -1.5.
    """
    SENSITIVITY = 5.3
    factor = get_park_factor(home_team_key)
    return round((factor - LEAGUE_AVERAGE_FACTOR) * SENSITIVITY, 2)


# Teams whose altitude effect is already handled by WeatherImpactEngine
# (stadium.altitude_ft >= 4000 → +2.0 Over in weather_impact.py).
# Excluding them here prevents double-counting the Coors altitude signal.
_ALTITUDE_HANDLED_TEAMS = frozenset({"colorado_rockies"})


def park_ou_adjustment_display(home_team_key: str) -> float:
    """
    Park O/U adjustment for display in the model table, excluding altitude parks.

    Altitude parks (Coors Field) are already covered by WeatherImpactEngine's
    altitude adjustment (+2.0 Over). Adding park_ou_adjustment on top would
    double-count the same effect.

    For all other parks this is a pure park-factor signal independent of weather:
      Fenway  (1.10) → +0.53 pts Over
      Petco   (0.88) → -0.64 pts Under
      Neutral (1.00) →  0.00 pts

    Returns 0.0 for altitude parks (Coors) since the weather engine already applies it.
    """
    if home_team_key in _ALTITUDE_HANDLED_TEAMS:
        return 0.0
    return park_ou_adjustment(home_team_key)


def park_pitcher_scaling(home_team_key: str) -> float:
    """
    Returns a scaling multiplier for pitcher/bullpen probability adjustments
    based on the park's run environment.

    In a hitter-friendly park (high factor), pitcher quality edges are diluted —
    the park's run inflation reduces the impact of a good/bad starter matchup.
    In a pitcher-friendly park (low factor), pitching edges are amplified.

    Formula: 2.0 - factor, clamped to [0.60, 1.25]
    Examples:
      Coors  (1.38) → 0.62  — pitcher edge reduced by 38%
      Petco  (0.88) → 1.12  — pitcher edge amplified by 12%
      Fenway (1.10) → 0.90  — slight dampening
      Neutral(1.00) → 1.00  — no change
    """
    factor = get_park_factor(home_team_key)
    scaling = 2.0 - factor
    return round(min(1.25, max(0.60, scaling)), 4)
