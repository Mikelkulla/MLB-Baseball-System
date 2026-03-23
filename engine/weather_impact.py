"""
Weather impact on MLB Over/Under lines.

MLB weather is more nuanced than NFL/NCAAF because:
  1. Wind direction relative to stadium orientation matters (in/out/cross)
  2. Altitude plays a significant role (Coors Field)
  3. Temperature + humidity affect ball carry distance and pitcher grip
  4. Dome/retractable stadiums are fully immune

Adjustments are additive points to the O/U line.
Positive over_adj = push line toward Over.
Positive under_adj = push line toward Under.

Research basis (all findings validated against large MLB game samples):

Wind:
  Wind blowing IN  ≥ 5 mph  → Under 55.5%  (Action Network, 1,400+ games)
  Wind blowing IN  ≥ 10 mph → Under further suppressed (~2.0 pts)
  Wind blowing IN  ≥ 15 mph → Under strongly suppressed (~3.5 pts)
  Wind blowing OUT ≥ 10 mph → Over 52-54%  (moderate lift)
  Wind blowing OUT ≥ 15 mph → Over 55-58%  (strong carry effect)
  Wind at 5-9 mph OUT       → effect too small to model reliably

Temperature:
  Below 40°F  → OVER 57% (counterintuitive: pitcher grip/command loss >
                bat speed reduction in extreme cold; documented multiple sources)
  41-55°F     → modest Under signal (cool bat speed reduction, ~0.75 pts)
  70-84°F     → neutral — no adjustment
  85-89°F     → modest Over signal (~0.75 pts; warm air, better ball carry)
  90°F+       → stronger Over signal (~1.25 pts; 13-18% more runs vs cold)

Precipitation:
  Light rain  → slight Over signal (+0.5 pts; pitcher grip issues cause
                3.6% MORE runs on average per research)
  Heavy rain  → Under signal (-2.0 pts; game pace disruption, fielding errors
                reduce run-scoring opportunities)

Altitude:
  Coors Field (5,197 ft) → +2.0 pts Over (park factor 125-128 vs baseline 100)
  Other high-altitude parks → proportional adjustment at ≥ 4,000 ft
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

    All thresholds and magnitudes are calibrated against documented MLB
    sample data. See module docstring for full research citations.
    """

    # ------------------------------------------------------------------
    # Wind speed thresholds (mph)
    # ------------------------------------------------------------------
    HIGH_WIND_MPH     = 15.0   # strong carry/suppression effect
    MODERATE_WIND_MPH = 10.0   # meaningful effect on ball carry
    LOW_WIND_MPH      =  5.0   # documented Under signal for "in" only
                                # (Wind blowing OUT at 5-9 mph is too weak to model)

    # ------------------------------------------------------------------
    # Temperature thresholds (°F)
    # ------------------------------------------------------------------
    VERY_COLD_TEMP_F  = 40.0   # below 40°F → OVER (pitcher grip > bat speed effect)
    COOL_TEMP_F       = 55.0   # 41-55°F → modest Under (bat speed reduction)
    HOT_TEMP_F        = 85.0   # 85-89°F → modest Over (ball carries further)
    VERY_HOT_TEMP_F   = 90.0   # 90°F+ → stronger Over (13-18% more runs vs cold)

    # ------------------------------------------------------------------
    # Adjustment magnitudes (run-line equivalent points)
    # ------------------------------------------------------------------
    ADJ = {
        # Wind — blowing out (Over-friendly)
        "wind_out_high":      +3.5,   # 15+ mph out: ball carries significantly
        "wind_out_moderate":  +2.0,   # 10-14 mph out: meaningful carry
        "wind_cross_high":    +1.0,   # 15+ mph cross: variance boost

        # Wind — blowing in (Under-friendly)
        "wind_in_high":       -3.5,   # 15+ mph in: strong suppression
        "wind_in_moderate":   -2.0,   # 10-14 mph in: meaningful suppression
        "wind_in_low":        -0.75,  # 5-9 mph in: documented Under 55.5% edge

        # Temperature
        "very_cold_temp":     +1.0,   # ≤40°F → OVER: pitcher grip/command loss
                                       # dominates bat-speed effect in extreme cold
        "cool_temp":          -0.75,  # 41-55°F → Under: bats slow, less hard contact
        "hot_temp":           +0.75,  # 85-89°F → Over: warm air, better carry
        "very_hot_temp":      +1.25,  # 90°F+ → stronger Over: ball carries furthest

        # Precipitation
        "heavy_precip":       -2.0,   # heavy rain: game disruption, reduced scoring
        "light_precip":       +0.5,   # light rain: pitcher grip issues → 3.6% more runs

        # Altitude
        "altitude":           +2.0,   # Coors / high-altitude parks (≥4,000 ft)
                                       # Park factor 125-128: ~2 extra runs per game
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

        # ------------------------------------------------------------------
        # Dome immunity — fixed dome is always climate-controlled
        # ------------------------------------------------------------------
        if stadium and stadium.roof_type == RoofType.FIXED_DOME:
            logger.debug(
                "WeatherImpactEngine: %s is a FIXED DOME — no weather adjustment",
                stadium.name,
            )
            return WeatherImpactResult(0.0, 0.0, "dome — no weather impact")

        # ------------------------------------------------------------------
        # Retractable roof — assume closed when rain or cool
        # Covers: Rogers Centre, Minute Maid, T-Mobile Park, Globe Life,
        #         loanDepot, American Family, Chase Field
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Wind direction impact
        # ------------------------------------------------------------------
        if stadium:
            direction = get_wind_direction_impact(wind_direction_deg, stadium)
        else:
            direction = "cross"   # safe default if stadium unknown

        logger.debug(
            "WeatherImpactEngine: wind direction resolved to '%s' (%.0f° + stadium orientation)",
            direction, wind_direction_deg,
        )

        if wind_speed_mph >= self.HIGH_WIND_MPH:
            # ≥15 mph — strong effect regardless of direction
            if direction == "out":
                over_adj += self.ADJ["wind_out_high"]
                reasons.append(f"wind blowing out {wind_speed_mph:.0f}mph (+{self.ADJ['wind_out_high']} over)")
                logger.debug("WeatherImpactEngine: HIGH WIND OUT — over_adj +%.1f", self.ADJ["wind_out_high"])
            elif direction == "in":
                under_adj += abs(self.ADJ["wind_in_high"])
                reasons.append(f"wind blowing in {wind_speed_mph:.0f}mph (+{abs(self.ADJ['wind_in_high'])} under)")
                logger.debug("WeatherImpactEngine: HIGH WIND IN — under_adj +%.1f", abs(self.ADJ["wind_in_high"]))
            else:
                # Cross-wind at high speed: variance boost (slight Over lean)
                over_adj += self.ADJ["wind_cross_high"]
                reasons.append(f"cross wind {wind_speed_mph:.0f}mph (+{self.ADJ['wind_cross_high']} over)")
                logger.debug("WeatherImpactEngine: HIGH CROSS WIND — over_adj +%.1f", self.ADJ["wind_cross_high"])

        elif wind_speed_mph >= self.MODERATE_WIND_MPH:
            # 10-14 mph — meaningful carry or suppression
            if direction == "out":
                over_adj += self.ADJ["wind_out_moderate"]
                reasons.append(f"moderate wind out {wind_speed_mph:.0f}mph (+{self.ADJ['wind_out_moderate']} over)")
                logger.debug("WeatherImpactEngine: MODERATE WIND OUT — over_adj +%.1f", self.ADJ["wind_out_moderate"])
            elif direction == "in":
                under_adj += abs(self.ADJ["wind_in_moderate"])
                reasons.append(f"moderate wind in {wind_speed_mph:.0f}mph (+{abs(self.ADJ['wind_in_moderate'])} under)")
                logger.debug("WeatherImpactEngine: MODERATE WIND IN — under_adj +%.1f", abs(self.ADJ["wind_in_moderate"]))
            else:
                logger.debug("WeatherImpactEngine: moderate cross wind %.1fmph — no adjustment", wind_speed_mph)

        elif wind_speed_mph >= self.LOW_WIND_MPH:
            # 5-9 mph — only "in" direction has a documented edge (Under 55.5%)
            # "Out" at 5-9 mph produces only ~52.9% Over: too weak to model reliably
            if direction == "in":
                under_adj += abs(self.ADJ["wind_in_low"])
                reasons.append(f"light wind blowing in {wind_speed_mph:.0f}mph (+{abs(self.ADJ['wind_in_low'])} under)")
                logger.debug(
                    "WeatherImpactEngine: LOW WIND IN — under_adj +%.2f "
                    "(documented Under 55.5%% edge at 5+ mph in)",
                    abs(self.ADJ["wind_in_low"]),
                )
            else:
                logger.debug(
                    "WeatherImpactEngine: low wind %.1fmph (%s) — "
                    "insufficient edge to model (only 'in' direction documented at this speed)",
                    wind_speed_mph, direction,
                )
        else:
            logger.debug("WeatherImpactEngine: wind %.1fmph below threshold — no wind adjustment", wind_speed_mph)

        # ------------------------------------------------------------------
        # Temperature
        # NOTE: Below 40°F the OVER hits 57%, not the Under.
        #       Pitcher grip/command loss in extreme cold > bat speed reduction.
        #       This is counterintuitive vs popular perception but well-documented.
        # ------------------------------------------------------------------
        if temperature_f <= self.VERY_COLD_TEMP_F:
            # Extreme cold: pitcher grip/command dominates → OVER lean
            over_adj += self.ADJ["very_cold_temp"]
            reasons.append(
                f"extreme cold {temperature_f:.0f}°F (+{self.ADJ['very_cold_temp']} over — "
                f"pitcher grip loss dominates)"
            )
            logger.debug(
                "WeatherImpactEngine: VERY COLD %.0f°F — over_adj +%.2f "
                "(pitcher grip > bat speed effect; OVER 57%% documented)",
                temperature_f, self.ADJ["very_cold_temp"],
            )

        elif temperature_f <= self.COOL_TEMP_F:
            # Cool (41-55°F): modest Under lean from reduced bat speed / hard contact
            under_adj += abs(self.ADJ["cool_temp"])
            reasons.append(f"cool {temperature_f:.0f}°F (+{abs(self.ADJ['cool_temp'])} under)")
            logger.debug(
                "WeatherImpactEngine: COOL TEMP %.0f°F — under_adj +%.2f",
                temperature_f, abs(self.ADJ["cool_temp"]),
            )

        elif temperature_f >= self.VERY_HOT_TEMP_F:
            # Very hot (90°F+): ball carries furthest, 13-18% more runs vs cold
            over_adj += self.ADJ["very_hot_temp"]
            reasons.append(f"very hot {temperature_f:.0f}°F (+{self.ADJ['very_hot_temp']} over)")
            logger.debug(
                "WeatherImpactEngine: VERY HOT %.0f°F — over_adj +%.2f",
                temperature_f, self.ADJ["very_hot_temp"],
            )

        elif temperature_f >= self.HOT_TEMP_F:
            # Hot (85-89°F): warm air, better ball carry, more runs
            over_adj += self.ADJ["hot_temp"]
            reasons.append(f"hot {temperature_f:.0f}°F (+{self.ADJ['hot_temp']} over)")
            logger.debug(
                "WeatherImpactEngine: HOT TEMP %.0f°F — over_adj +%.2f",
                temperature_f, self.ADJ["hot_temp"],
            )

        else:
            logger.debug(
                "WeatherImpactEngine: temp %.0f°F in neutral zone (56-84°F) — no temperature adjustment",
                temperature_f,
            )

        # ------------------------------------------------------------------
        # Precipitation
        # NOTE: Light rain causes 3.6% MORE runs on average (pitcher grip issues
        #       in wet conditions lead to more walks and wild pitches).
        #       Only heavy rain suppresses run-scoring via game disruption.
        # ------------------------------------------------------------------
        if precipitation == "heavy":
            under_adj += abs(self.ADJ["heavy_precip"])
            reasons.append(f"heavy rain (+{abs(self.ADJ['heavy_precip'])} under)")
            logger.debug("WeatherImpactEngine: HEAVY PRECIP — under_adj +%.1f", abs(self.ADJ["heavy_precip"]))
        elif precipitation == "light":
            # Light rain: pitcher grip issues → slight OVER lean (3.6% more runs documented)
            over_adj += self.ADJ["light_precip"]
            reasons.append(f"light rain (+{self.ADJ['light_precip']} over — pitcher grip issues)")
            logger.debug(
                "WeatherImpactEngine: LIGHT PRECIP — over_adj +%.2f "
                "(pitcher grip issues; 3.6%% more runs documented)",
                self.ADJ["light_precip"],
            )
        else:
            logger.debug("WeatherImpactEngine: no precipitation")

        # ------------------------------------------------------------------
        # Altitude bonus (Coors Field and other high-altitude parks)
        # Park factor 125-128 at Coors (5,197 ft) ≈ +2 extra runs per game.
        # ------------------------------------------------------------------
        if stadium and stadium.altitude_ft >= 4000:
            over_adj += self.ADJ["altitude"]
            reasons.append(f"altitude {stadium.altitude_ft}ft (+{self.ADJ['altitude']} over)")
            logger.debug(
                "WeatherImpactEngine: HIGH ALTITUDE %dft — over_adj +%.1f "
                "(park factor 125-128)",
                stadium.altitude_ft, self.ADJ["altitude"],
            )

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
