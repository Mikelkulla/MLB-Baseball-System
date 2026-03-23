"""
Weather client — fetches current weather for each MLB stadium.
Uses WeatherAPI.com (same provider as V8.0 utils_weather.js).
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
import requests
from config.settings import WEATHER_API_KEY, WEATHER_API_BASE_URL
from mlb.stadiums import STADIUM_BY_TEAM, Stadium

logger = logging.getLogger(__name__)


@dataclass
class WeatherReading:
    team_key: str
    stadium_name: str
    temperature_f: float
    wind_speed_mph: float
    wind_direction_deg: float
    wind_direction_name: str   # "NW", "SSE", etc.
    condition: str             # "Sunny", "Overcast", etc.
    precipitation_mm: float    # mm in last hour
    humidity_pct: float
    is_dome: bool

    @property
    def precipitation_category(self) -> str:
        if self.precipitation_mm >= 2.5:
            return "heavy"
        if self.precipitation_mm >= 0.5:
            return "light"
        return "none"


# Compass-name to degrees (mid-point of sector)
_COMPASS_TO_DEG: dict[str, float] = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


class WeatherClient:
    """Fetches weather data for MLB stadiums via WeatherAPI.com."""

    def __init__(self, api_key: str = WEATHER_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()

    def fetch_all(self) -> dict[str, WeatherReading]:
        """
        Fetch weather for all 30 stadiums.
        Returns {team_key: WeatherReading}.
        """
        results: dict[str, WeatherReading] = {}
        for team_key, stadium in STADIUM_BY_TEAM.items():
            reading = self._fetch_stadium(stadium)
            if reading:
                results[team_key] = reading
        logger.info("Fetched weather for %d stadiums", len(results))
        return results

    def fetch_for_team(self, team_key: str) -> Optional[WeatherReading]:
        stadium = STADIUM_BY_TEAM.get(team_key)
        if not stadium:
            return None
        return self._fetch_stadium(stadium)

    def _fetch_stadium(self, stadium: Stadium) -> Optional[WeatherReading]:
        coords = f"{stadium.latitude},{stadium.longitude}"
        url = f"{WEATHER_API_BASE_URL}/current.json"
        params = {"key": self.api_key, "q": coords, "aqi": "no"}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return self._parse(stadium, resp.json())
        except requests.RequestException as exc:
            logger.warning("Weather fetch failed for %s: %s", stadium.name, exc)
            return None

    @staticmethod
    def _parse(stadium: Stadium, data: dict) -> WeatherReading:
        current = data.get("current", {})
        wind_dir_name = current.get("wind_dir", "N")
        wind_dir_deg = _COMPASS_TO_DEG.get(wind_dir_name.upper(), 0.0)

        return WeatherReading(
            team_key=stadium.team_key,
            stadium_name=stadium.name,
            temperature_f=float(current.get("temp_f", 70.0)),
            wind_speed_mph=float(current.get("wind_mph", 0.0)),
            wind_direction_deg=wind_dir_deg,
            wind_direction_name=wind_dir_name,
            condition=current.get("condition", {}).get("text", "Unknown"),
            precipitation_mm=float(current.get("precip_mm", 0.0)),
            humidity_pct=float(current.get("humidity", 50.0)),
            is_dome=(stadium.roof_type.value == "fixed_dome"),
        )
