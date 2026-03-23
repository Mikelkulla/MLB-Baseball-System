"""
Weather impact on MLB Over/Under lines.

MLB weather is more nuanced than NFL/NCAAF because:
  1. Wind direction relative to stadium orientation matters (in/out/cross)
  2. Altitude plays a significant role (Coors Field)
  3. Temperature + humidity affect ball carry distance
  4. Dome/retractable stadiums are fully immune

Adjustments are additive points to the O/U line.
Positive over_adj = push line toward Over.
Positive under_adj = push line toward Under.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from mlb.stadiums import RoofType, get_wind_direction_impact, STADIUM_BY_TEAM

logger = logging.getLogger(__name__)


@dataclass
class WeatherImpactResult:
    over_adj: float    # points adjustment toward Over
    under_adj: float   # points adjustment toward Under
    reason: str        # human-readable explanation


class WeatherImpactEngine:
    """
    Computes O/U adjustments from weather conditions.

    All thresholds match the V8.0 utils_weather_impact.js logic,
    with MLB-specific additions for wind direction and altitude.
    """

    # Wind speed thresholds (mph)
    HIGH_WIND_MPH = 15.0
    MODERATE_WIND_MPH = 10.0

    # Temperature thresholds (°F)
    COLD_TEMP_F = 35.0
    COOL_TEMP_F = 50.0

    # Base adjustments (same scale as V8.0)
    ADJ = {
        "wind_out_high":      +3.5,
        "wind_out_moderate":  +2.0,
        "wind_in_high":       -3.5,
        "wind_in_moderate":   -2.0,
        "wind_cross_high":    +1.0,   # cross-wind adds slight variance
        "cold_temp":          -2.5,
        "cool_temp":          -1.0,
        "heavy_precip":       -2.0,
        "light_precip":       -1.0,
    }

    def calculate(
        self,
        home_team_key: str,
        temperature_f: float,
        wind_speed_mph: float,
        wind_direction_deg: float,
        precipitation: str = "none",    # "none", "light", "heavy"
    ) -> WeatherImpactResult:
        stadium = STADIUM_BY_TEAM.get(home_team_key)
        reasons = []
        over_adj = 0.0
        under_adj = 0.0

        logger.debug(
            "WeatherImpactEngine.calculate: team=%s  stadium=%s  "
            "temp=%.1f°F  wind=%.1fmph @ %.0f°  precip=%s",
            home_team_key,
            stadium.name if stadium else "UNKNOWN",
            temperature_f, wind_speed_mph, wind_direction_deg, precipitation,
        )

        # Dome immunity — fixed dome is always climate-controlled
        if stadium and stadium.roof_type == RoofType.FIXED_DOME:
            logger.debug(
                "WeatherImpactEngine: %s is a FIXED DOME — no weather adjustment",
                stadium.name,
            )
            return WeatherImpactResult(0.0, 0.0, "dome — no weather impact")

        # Retractable roof — assume closed when rain or cold (per stadiums.py design)
        # Rogers Centre, Minute Maid, T-Mobile Park, Globe Life, loanDepot, American Family, Chase Field
        if stadium and stadium.roof_type == RoofType.RETRACTABLE:
            if precipitation != "none" or temperature_f <= self.COOL_TEMP_F:
                logger.debug(
                    "WeatherImpactEngine: %s is RETRACTABLE and conditions are cold/wet "
                    "(temp=%.1f°F, precip=%s) — roof assumed closed, no weather adjustment",
                    stadium.name, temperature_f, precipitation,
                )
                return WeatherImpactResult(
                    0.0, 0.0,
                    f"retractable roof closed (temp={temperature_f:.0f}°F, precip={precipitation}) — no weather impact",
                )
            logger.debug(
                "WeatherImpactEngine: %s is RETRACTABLE but conditions are warm/dry "
                "(temp=%.1f°F, precip=%s) — roof may be open, applying weather",
                stadium.name, temperature_f, precipitation,
            )

        if not stadium:
            logger.warning(
                "WeatherImpactEngine: no stadium data for team '%s' — using cross-wind default",
                home_team_key,
            )

        # --- Wind direction impact ---
        if stadium:
            direction = get_wind_direction_impact(wind_direction_deg, stadium)
        else:
            direction = "cross"   # safe default if stadium unknown

        logger.debug(
            "WeatherImpactEngine: wind direction resolved to '%s' (%.0f° + stadium orientation)",
            direction, wind_direction_deg,
        )

        if wind_speed_mph >= self.HIGH_WIND_MPH:
            if direction == "out":
                over_adj += self.ADJ["wind_out_high"]
                reasons.append(f"wind blowing out {wind_speed_mph:.0f}mph (+{self.ADJ['wind_out_high']})")
                logger.debug("WeatherImpactEngine: HIGH WIND OUT — over_adj +%.1f", self.ADJ["wind_out_high"])
            elif direction == "in":
                under_adj += abs(self.ADJ["wind_in_high"])
                reasons.append(f"wind blowing in {wind_speed_mph:.0f}mph (+{abs(self.ADJ['wind_in_high'])} under)")
                logger.debug("WeatherImpactEngine: HIGH WIND IN — under_adj +%.1f", abs(self.ADJ["wind_in_high"]))
            else:
                over_adj += self.ADJ["wind_cross_high"]
                reasons.append(f"cross wind {wind_speed_mph:.0f}mph (+{self.ADJ['wind_cross_high']})")
                logger.debug("WeatherImpactEngine: HIGH CROSS WIND — over_adj +%.1f", self.ADJ["wind_cross_high"])
        elif wind_speed_mph >= self.MODERATE_WIND_MPH:
            if direction == "out":
                over_adj += self.ADJ["wind_out_moderate"]
                reasons.append(f"moderate wind out {wind_speed_mph:.0f}mph (+{self.ADJ['wind_out_moderate']})")
                logger.debug("WeatherImpactEngine: MODERATE WIND OUT — over_adj +%.1f", self.ADJ["wind_out_moderate"])
            elif direction == "in":
                under_adj += abs(self.ADJ["wind_in_moderate"])
                reasons.append(f"moderate wind in {wind_speed_mph:.0f}mph (+{abs(self.ADJ['wind_in_moderate'])} under)")
                logger.debug("WeatherImpactEngine: MODERATE WIND IN — under_adj +%.1f", abs(self.ADJ["wind_in_moderate"]))
            else:
                logger.debug("WeatherImpactEngine: moderate cross wind %.1fmph — no adjustment", wind_speed_mph)
        else:
            logger.debug("WeatherImpactEngine: wind %.1fmph below threshold — no wind adjustment", wind_speed_mph)

        # --- Temperature ---
        if temperature_f <= self.COLD_TEMP_F:
            under_adj += abs(self.ADJ["cold_temp"])
            reasons.append(f"cold {temperature_f:.0f}°F (+{abs(self.ADJ['cold_temp'])} under)")
            logger.debug("WeatherImpactEngine: COLD TEMP %.0f°F — under_adj +%.1f", temperature_f, abs(self.ADJ["cold_temp"]))
        elif temperature_f <= self.COOL_TEMP_F:
            under_adj += abs(self.ADJ["cool_temp"])
            reasons.append(f"cool {temperature_f:.0f}°F (+{abs(self.ADJ['cool_temp'])} under)")
            logger.debug("WeatherImpactEngine: COOL TEMP %.0f°F — under_adj +%.1f", temperature_f, abs(self.ADJ["cool_temp"]))
        else:
            logger.debug("WeatherImpactEngine: temp %.0f°F — no temperature adjustment", temperature_f)

        # --- Precipitation ---
        if precipitation == "heavy":
            under_adj += abs(self.ADJ["heavy_precip"])
            reasons.append(f"heavy precip (+{abs(self.ADJ['heavy_precip'])} under)")
            logger.debug("WeatherImpactEngine: HEAVY PRECIP — under_adj +%.1f", abs(self.ADJ["heavy_precip"]))
        elif precipitation == "light":
            under_adj += abs(self.ADJ["light_precip"])
            reasons.append(f"light precip (+{abs(self.ADJ['light_precip'])} under)")
            logger.debug("WeatherImpactEngine: LIGHT PRECIP — under_adj +%.1f", abs(self.ADJ["light_precip"]))
        else:
            logger.debug("WeatherImpactEngine: no precipitation")

        # --- Altitude bonus (Coors Field) ---
        if stadium and stadium.altitude_ft >= 4000:
            over_adj += 1.5
            reasons.append(f"altitude {stadium.altitude_ft}ft (+1.5 over)")
            logger.debug("WeatherImpactEngine: HIGH ALTITUDE %dft — over_adj +1.5", stadium.altitude_ft)

        result = WeatherImpactResult(
            over_adj=round(over_adj, 2),
            under_adj=round(under_adj, 2),
            reason="; ".join(reasons) if reasons else "no significant weather impact",
        )
        logger.info(
            "WeatherImpact [%s]: over_adj=%+.2f  under_adj=%+.2f  — %s",
            home_team_key, result.over_adj, result.under_adj, result.reason,
        )
        return result
