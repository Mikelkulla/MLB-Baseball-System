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
# MLB Position Weights for injury impact (analogous to V8.0 NFL weights)
# SP is weighted like QB (8.0) — dominant impact on game outcome
# ---------------------------------------------------------------------------
MLB_POSITION_WEIGHTS: Dict[str, float] = {
    "SP":  8.0,   # Starting Pitcher — game-defining like QB in NFL
    "CP":  2.5,   # Closer
    "RP":  1.5,   # Relief Pitcher
    "C":   2.0,   # Catcher
    "SS":  1.5,   # Shortstop
    "3B":  1.2,
    "2B":  1.0,
    "1B":  0.8,
    "CF":  1.0,
    "LF":  0.8,
    "RF":  0.8,
    "DH":  1.0,
    "MR":  1.2,   # Middle Reliever (setup man)
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
