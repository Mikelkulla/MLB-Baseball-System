"""
MLB-specific static configuration:
  - 30 teams with keys, city, abbreviation
  - Position weights (injury impact)
  - SP gate settings (analogous to NFL QB1 gate)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict

# ---------------------------------------------------------------------------
# MLB Position Weights for injury impact
#
# Calibrated against FanGraphs positional adjustments (runs/162g) and
# MLB-specific WAR research. See research/Q3_injury_position_weights.md.
#
# FanGraphs positional adjustment hierarchy (runs per 162 games):
#   C: +12.5  SS: +7.5  CF/2B/3B: +2.5  LF/RF: -7.5  1B: -12.5  DH: -17.5
#
# Key design decisions:
#   SP=8.0 — market evidence shows 10-15pp shift for ace scratch; 8.0 is
#             appropriate for average-case (not ace, not replacement-level).
#             SP gate handles the extreme Out/Doubtful case separately.
#
#   C=3.0  — highest positional adjustment (+12.5 runs); framing value
#             (30-50 runs/season for top framers) is NOT captured in FIP-based
#             pitcher scoring, so the full effect must be here.
#
#   SS=2.0 — second hardest infield position (+7.5 runs); meaningfully above
#             3B/2B (+2.5 each). Replacement SS scarcity is well-documented.
#
#   CF=1.5 — +2.5 run positional adjustment (hardest OF position). Previously
#             equated to DH at 1.0, which was analytically wrong; CF has real
#             defensive scarcity that DH does not.
#
#   CP=2.0 — reduced from 2.5 to account for bullpen chaining: when closer is
#             injured, setup man shifts up, net loss is 1.0-1.5 WAR, not 2.5.
#             Still above SS/RP to reflect high-leverage usage.
#
#   DH=0.6 — -17.5 run positional adjustment; no defensive scarcity premium;
#             purely offensive replacement (backup hitter is always available).
#             Star DH differentiation belongs in future WAR-based per-player
#             scoring, not in the flat position weight.
#
# Not implemented (future enhancement):
#   Player-quality multiplier (0.5x-2.0x based on prior-season WAR):
#   A 7-WAR SS injury vs a 1.5-WAR SS injury creates fundamentally different
#   win probability shifts that position weights alone cannot capture.
#   Requires per-player WAR lookup from Baseball-Reference or FanGraphs API.
# ---------------------------------------------------------------------------
MLB_POSITION_WEIGHTS: Dict[str, float] = {
    "SP":  8.0,   # Starting Pitcher — game-defining; market confirms ~10-15pp for ace
    "C":   3.0,   # Catcher — highest positional adj (+12.5 runs); framing uncaptured elsewhere
    "SS":  2.0,   # Shortstop — second hardest infield position (+7.5 runs)
    "CP":  2.0,   # Closer — LI ~1.8; chaining effect limits net loss to ~1.0-1.5 WAR
    "CF":  1.5,   # Center Field — +2.5 run positional adj; harder than corner OF
    "3B":  1.2,   # Third Base — +2.5 run positional adj (same tier as 2B analytically)
    "MR":  1.2,   # Middle Reliever (setup man) — high-leverage bridge to closer
    "RP":  1.5,   # Relief Pitcher (8th inning / high-leverage) — LI 1.2-1.5
    "2B":  1.0,   # Second Base — +2.5 run positional adj
    "DH":  0.6,   # Designated Hitter — -17.5 run adj; no defensive scarcity
    "1B":  0.8,   # First Base — -12.5 run adj; easiest infield position to fill
    "LF":  0.8,   # Left Field — -7.5 run adj; corner OF
    "RF":  0.8,   # Right Field — -7.5 run adj; corner OF
}

# ---------------------------------------------------------------------------
# Injury status multipliers (same system as V8.0)
# ---------------------------------------------------------------------------
INJURY_STATUS_MULTIPLIERS: Dict[str, float] = {
    "out":              1.0,
    "out for season":   1.0,
    "doubtful":         0.85,
    "questionable":     0.40,
    "day-to-day":       0.30,
    "probable":         0.10,
    "healthy":          0.0,
}

# ---------------------------------------------------------------------------
# SP Gate — if probable starter is Out or Doubtful, suppress the pick
# Mirrors NFL QB1 gate logic
# ---------------------------------------------------------------------------
SP_GATE_STATUSES = {"out", "out for season", "doubtful"}

# ---------------------------------------------------------------------------
# 30 MLB Teams
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MLBTeam:
    key: str           # canonical key used across data sources
    city: str
    name: str
    abbreviation: str
    division: str      # "AL East", "NL West", etc.
    stadium: str       # stadium name for weather/park lookup

MLB_TEAMS: list[MLBTeam] = [
    # AL East
    MLBTeam("baltimore_orioles",     "Baltimore",     "Orioles",      "BAL", "AL East",    "Oriole Park at Camden Yards"),
    MLBTeam("boston_red_sox",        "Boston",        "Red Sox",      "BOS", "AL East",    "Fenway Park"),
    MLBTeam("new_york_yankees",      "New York",      "Yankees",      "NYY", "AL East",    "Yankee Stadium"),
    MLBTeam("tampa_bay_rays",        "Tampa Bay",     "Rays",         "TB",  "AL East",    "Tropicana Field"),
    MLBTeam("toronto_blue_jays",     "Toronto",       "Blue Jays",    "TOR", "AL East",    "Rogers Centre"),
    # AL Central
    MLBTeam("chicago_white_sox",     "Chicago",       "White Sox",    "CWS", "AL Central", "Guaranteed Rate Field"),
    MLBTeam("cleveland_guardians",   "Cleveland",     "Guardians",    "CLE", "AL Central", "Progressive Field"),
    MLBTeam("detroit_tigers",        "Detroit",       "Tigers",       "DET", "AL Central", "Comerica Park"),
    MLBTeam("kansas_city_royals",    "Kansas City",   "Royals",       "KC",  "AL Central", "Kauffman Stadium"),
    MLBTeam("minnesota_twins",       "Minnesota",     "Twins",        "MIN", "AL Central", "Target Field"),
    # AL West
    MLBTeam("houston_astros",        "Houston",       "Astros",       "HOU", "AL West",    "Minute Maid Park"),
    MLBTeam("los_angeles_angels",    "Los Angeles",   "Angels",       "LAA", "AL West",    "Angel Stadium"),
    MLBTeam("athletics",             "Oakland",       "Athletics",    "OAK", "AL West",    "Oakland Coliseum"),
    MLBTeam("seattle_mariners",      "Seattle",       "Mariners",     "SEA", "AL West",    "T-Mobile Park"),
    MLBTeam("texas_rangers",         "Texas",         "Rangers",      "TEX", "AL West",    "Globe Life Field"),
    # NL East
    MLBTeam("atlanta_braves",        "Atlanta",       "Braves",       "ATL", "NL East",    "Truist Park"),
    MLBTeam("miami_marlins",         "Miami",         "Marlins",      "MIA", "NL East",    "loanDepot park"),
    MLBTeam("new_york_mets",         "New York",      "Mets",         "NYM", "NL East",    "Citi Field"),
    MLBTeam("philadelphia_phillies", "Philadelphia",  "Phillies",     "PHI", "NL East",    "Citizens Bank Park"),
    MLBTeam("washington_nationals",  "Washington",    "Nationals",    "WSH", "NL East",    "Nationals Park"),
    # NL Central
    MLBTeam("chicago_cubs",          "Chicago",       "Cubs",         "CHC", "NL Central", "Wrigley Field"),
    MLBTeam("cincinnati_reds",       "Cincinnati",    "Reds",         "CIN", "NL Central", "Great American Ball Park"),
    MLBTeam("milwaukee_brewers",     "Milwaukee",     "Brewers",      "MIL", "NL Central", "American Family Field"),
    MLBTeam("pittsburgh_pirates",    "Pittsburgh",    "Pirates",      "PIT", "NL Central", "PNC Park"),
    MLBTeam("st_louis_cardinals",    "St. Louis",     "Cardinals",    "STL", "NL Central", "Busch Stadium"),
    # NL West
    MLBTeam("arizona_diamondbacks",  "Arizona",       "Diamondbacks", "ARI", "NL West",    "Chase Field"),
    MLBTeam("colorado_rockies",      "Colorado",      "Rockies",      "COL", "NL West",    "Coors Field"),
    MLBTeam("los_angeles_dodgers",   "Los Angeles",   "Dodgers",      "LAD", "NL West",    "Dodger Stadium"),
    MLBTeam("san_diego_padres",      "San Diego",     "Padres",       "SD",  "NL West",    "Petco Park"),
    MLBTeam("san_francisco_giants",  "San Francisco", "Giants",       "SF",  "NL West",    "Oracle Park"),
]

# Fast lookup: abbreviation → MLBTeam
TEAM_BY_ABBR: Dict[str, MLBTeam] = {t.abbreviation: t for t in MLB_TEAMS}
TEAM_BY_KEY: Dict[str, MLBTeam] = {t.key: t for t in MLB_TEAMS}
