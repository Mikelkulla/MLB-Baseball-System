"""
Stadium orientation and roof type for all 30 MLB parks.

Orientation angle = compass direction the batter faces (degrees from north).
Wind impact is computed as the angle between wind direction and stadium axis.

  0/360 = batter faces North  → wind from S = blowing out to CF
  90    = batter faces East   → wind from W = blowing out to CF
  180   = batter faces South  → wind from N = blowing out to CF

RoofType:
  "open"         - fully open-air (weather impacts fully apply)
  "retractable"  - roof can open; assume closed when rain/cold → no impact
  "fixed_dome"   - always climate-controlled → zero weather impact
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class RoofType(str, Enum):
    OPEN        = "open"
    RETRACTABLE = "retractable"
    FIXED_DOME  = "fixed_dome"


@dataclass(frozen=True)
class Stadium:
    name: str
    team_key: str
    city: str
    state: str
    orientation_deg: int      # compass degrees batter faces
    roof_type: RoofType
    altitude_ft: int = 0      # elevation above sea level
    # Coordinates for weather API lookup
    latitude: float = 0.0
    longitude: float = 0.0


STADIUMS: list[Stadium] = [
    # AL East
    Stadium("Oriole Park at Camden Yards", "baltimore_orioles",    "Baltimore",     "MD", 100, RoofType.OPEN,        20,  39.2839, -76.6218),
    Stadium("Fenway Park",                 "boston_red_sox",       "Boston",        "MA",  95, RoofType.OPEN,        19,  42.3467, -71.0972),
    Stadium("Yankee Stadium",              "new_york_yankees",     "New York",      "NY",  55, RoofType.OPEN,        55,  40.8296, -73.9262),
    Stadium("Tropicana Field",             "tampa_bay_rays",       "St. Petersburg","FL",   0, RoofType.FIXED_DOME,   9,  27.7683, -82.6534),
    Stadium("Rogers Centre",               "toronto_blue_jays",    "Toronto",       "ON",  90, RoofType.RETRACTABLE, 249, 43.6414, -79.3892),
    # AL Central
    Stadium("Guaranteed Rate Field",       "chicago_white_sox",    "Chicago",       "IL",  85, RoofType.OPEN,       594,  41.8300, -87.6338),
    Stadium("Progressive Field",           "cleveland_guardians",  "Cleveland",     "OH",  95, RoofType.OPEN,       777,  41.4962, -81.6852),
    Stadium("Comerica Park",               "detroit_tigers",       "Detroit",       "MI",  95, RoofType.OPEN,       600,  42.3390, -83.0485),
    Stadium("Kauffman Stadium",            "kansas_city_royals",   "Kansas City",   "MO",  90, RoofType.OPEN,       906,  39.0517, -94.4803),
    Stadium("Target Field",                "minnesota_twins",      "Minneapolis",   "MN",  75, RoofType.OPEN,       830,  44.9817, -93.2781),
    # AL West
    Stadium("Minute Maid Park",            "houston_astros",       "Houston",       "TX",  65, RoofType.RETRACTABLE,  43, 29.7572, -95.3551),
    Stadium("Angel Stadium",               "los_angeles_angels",   "Anaheim",       "CA", 185, RoofType.OPEN,       160,  33.8003, -117.8827),
    Stadium("Oakland Coliseum",            "athletics",            "Oakland",       "CA", 150, RoofType.OPEN,        22,  37.7516, -122.2005),
    Stadium("T-Mobile Park",               "seattle_mariners",     "Seattle",       "WA", 100, RoofType.RETRACTABLE, 17,  47.5913, -122.3325),
    Stadium("Globe Life Field",            "texas_rangers",        "Arlington",     "TX",  80, RoofType.RETRACTABLE, 617, 32.7473, -97.0836),
    # NL East
    Stadium("Truist Park",                 "atlanta_braves",       "Cumberland",    "GA",  90, RoofType.OPEN,       976,  33.8907, -84.4678),
    Stadium("loanDepot park",              "miami_marlins",        "Miami",         "FL",   0, RoofType.RETRACTABLE,   7,  25.7782, -80.2196),
    Stadium("Citi Field",                  "new_york_mets",        "Queens",        "NY",  65, RoofType.OPEN,        23,  40.7571, -73.8458),
    Stadium("Citizens Bank Park",          "philadelphia_phillies","Philadelphia",  "PA",  80, RoofType.OPEN,        20,  39.9057, -75.1665),
    Stadium("Nationals Park",              "washington_nationals", "Washington",    "DC",  90, RoofType.OPEN,        24,  38.8730, -77.0074),
    # NL Central
    Stadium("Wrigley Field",               "chicago_cubs",         "Chicago",       "IL",  90, RoofType.OPEN,       594,  41.9484, -87.6553),
    Stadium("Great American Ball Park",    "cincinnati_reds",      "Cincinnati",    "OH",  80, RoofType.OPEN,       489,  39.0978, -84.5082),
    Stadium("American Family Field",       "milwaukee_brewers",    "Milwaukee",     "WI",  85, RoofType.RETRACTABLE, 673, 43.0280, -87.9712),
    Stadium("PNC Park",                    "pittsburgh_pirates",   "Pittsburgh",    "PA", 100, RoofType.OPEN,       745,  40.4469, -80.0057),
    Stadium("Busch Stadium",               "st_louis_cardinals",   "St. Louis",     "MO",  85, RoofType.OPEN,       465,  38.6226, -90.1928),
    # NL West
    Stadium("Chase Field",                 "arizona_diamondbacks", "Phoenix",       "AZ",  45, RoofType.RETRACTABLE,1082,  33.4453, -112.0667),
    Stadium("Coors Field",                 "colorado_rockies",     "Denver",        "CO",  90, RoofType.OPEN,       5197, 39.7559, -104.9942),
    Stadium("Dodger Stadium",              "los_angeles_dodgers",  "Los Angeles",   "CA", 180, RoofType.OPEN,        512, 34.0739, -118.2400),
    Stadium("Petco Park",                  "san_diego_padres",     "San Diego",     "CA", 135, RoofType.OPEN,          9, 32.7076, -117.1570),
    Stadium("Oracle Park",                 "san_francisco_giants", "San Francisco", "CA", 305, RoofType.OPEN,          0, 37.7786, -122.3893),
]

STADIUM_BY_TEAM: Dict[str, Stadium] = {s.team_key: s for s in STADIUMS}

# Fixed-dome and permanently closed retractable stadiums → no weather impact
WEATHER_IMMUNE_TEAMS: set[str] = {
    s.team_key for s in STADIUMS if s.roof_type == RoofType.FIXED_DOME
}


def get_wind_direction_impact(
    wind_direction_deg: float,
    stadium: Stadium,
) -> str:
    """
    Returns "out" | "in" | "cross" based on stadium orientation and wind bearing.

    Wind blowing OUT to CF increases scoring (over-friendly).
    Wind blowing IN from CF suppresses scoring (under-friendly).
    Cross wind has a smaller mixed effect.
    """
    if stadium.roof_type == RoofType.FIXED_DOME:
        return "none"

    # Angle between wind bearing and the direction from home plate to CF
    # CF direction ≈ stadium orientation + 180 (batter faces orientation → CF is behind)
    cf_bearing = (stadium.orientation_deg + 180) % 360
    diff = abs(wind_direction_deg - cf_bearing) % 360
    if diff > 180:
        diff = 360 - diff

    if diff <= 45:
        return "out"     # wind blowing toward CF = blowing out
    if diff >= 135:
        return "in"      # wind blowing from CF = blowing in
    return "cross"
