"""
Confidence scoring and tier assignment — V8.0 formula.

V8.0 formula (Phase2_formulas.js):
  evNorm     = MIN(80, MAX(0, 50 + EV*2))
  SharpScore = MIN(100, MAX(0, 50 + SharpSplit*0.5 + (WPI-50)*0.4))
  Confidence = MIN(95, MAX(25, evNorm*0.50 + SharpScore*0.50))

Where:
  SharpSplit = ourHandle% - ourBets%  (signed; positive = handle>bets = sharp money on our side)
  WPI        = MIN(100, MAX(0, 50 + (ourHandle-50)*1.5))

SafeUnits rules (V8.0 SAFE_UNITS / v8.2 WPI-gate-with-downgrade):
  1. WPI < 50                            → 0 units (PASS)
  2. WPI < 60 AND baseUnits >= 2.5       → downgrade to 1.75u
  3. Steam/LineFlip safety triggered     → cap units at MAX_UNITS_SAFETY = 1.0u
  4. SP gate blocked                     → 0 units
  5. Otherwise                           → keep tier units

SafeStatus extra label (V8.0):
  "ACTION ONLY" — when 0 units due to WPI<50 but not a full PASS (tier had qualified)
"""

from __future__ import annotations
import logging
from typing import Optional
from config.settings import TIERS, TierConfig

logger = logging.getLogger(__name__)

# V8.0 SafeUnits constants
WPI_ZERO_UNITS_THRESHOLD   = 50.0   # WPI < 50 → 0 units
WPI_HIGH_UNIT_MIN          = 60.0   # WPI < 60 + units ≥ 2.5 → downgrade to 1.75u
HIGH_UNIT_THRESHOLD        = 2.5    # units at or above this get downgraded when WPI is insufficient
DOWNGRADE_UNITS            = 1.75   # downgrade target
MAX_UNITS_SAFETY           = 1.0    # unit cap when steam or lineflip fires


class ConfidenceEngine:
    """
    Produces a 0–100 confidence score using the V8.0 two-component formula,
    then assigns a tier (ELITE / STRONGEST / BEST BET / GOLD / PASS).
    """

    @staticmethod
    def ev_norm(ev_pct: Optional[float]) -> float:
        """Scale EV to 0–80 component. Neutral (50) when EV is None."""
        if ev_pct is None:
            logger.debug("ev_norm: ev_pct is None — returning neutral 50.0")
            return 50.0
        result = min(80.0, max(0.0, 50.0 + ev_pct * 2.0))
        logger.debug("ev_norm: ev_pct=%+.4f%%  evNorm=%.2f", ev_pct, result)
        return result

    @staticmethod
    def sharp_score(sharp_split: float, wpi: float) -> float:
        """
        V8.0 SharpScore.
        sharp_split = ourHandle% - ourBets%  (signed)
        wpi         = WhaleIndex (0–100, default 50)
        """
        result = min(100.0, max(0.0, 50.0 + sharp_split * 0.5 + (wpi - 50.0) * 0.4))
        logger.debug(
            "sharp_score: split=%+.2f  wpi=%.2f  "
            "formula=50 + %.2f*0.5 + %.2f*0.4 = %.2f",
            sharp_split, wpi,
            sharp_split, wpi - 50.0,
            result,
        )
        return result

    def score(
        self,
        ev_pct: Optional[float],
        sharp_split: float = 0.0,
        wpi: float = 50.0,
    ) -> float:
        """
        V8.0 confidence formula.
        Returns 25–95.
        """
        en = self.ev_norm(ev_pct)
        ss = self.sharp_score(sharp_split, wpi)
        raw = en * 0.50 + ss * 0.50
        result = round(min(95.0, max(25.0, raw)), 2)
        logger.debug(
            "confidence.score: evNorm=%.2f  SharpScore=%.2f  raw=%.2f  "
            "clamped[25,95]=%.2f",
            en, ss, raw, result,
        )
        return result

    @staticmethod
    def assign_tier(confidence_pct: float, wpi: float = 50.0) -> TierConfig:
        """
        Return the TierConfig matching confidence, with V8.0 WPI tier gating.

        WPI gates (V8.0 BETTING_CONFIG.wpiGates):
          ELITE      requires WPI >= 75
          STRONGEST  requires WPI >= 65
          BEST BET   requires WPI >= 55
          GOLD       requires WPI >= 0  (always allowed — SafeUnits handles WPI<50 separately)
        """
        wpi_min = {"ELITE": 75.0, "STRONGEST": 65.0, "BEST BET": 55.0, "GOLD": 0.0}
        for tier in TIERS:
            if confidence_pct >= tier.min_confidence:
                wpi_required = wpi_min.get(tier.name, 0.0)
                if wpi >= wpi_required:
                    logger.debug(
                        "assign_tier: conf=%.2f%%  wpi=%.2f  → %s (%.2fu)  "
                        "[required_wpi=%.0f ✓]",
                        confidence_pct, wpi, tier.name, tier.units, wpi_required,
                    )
                    return tier
                else:
                    logger.debug(
                        "assign_tier: conf=%.2f%% qualifies for %s but WPI %.2f < %.0f — downgrade",
                        confidence_pct, tier.name, wpi, wpi_required,
                    )
        logger.debug(
            "assign_tier: conf=%.2f%%  wpi=%.2f  → PASS (no tier threshold met)",
            confidence_pct, wpi,
        )
        return TIERS[-1]  # PASS

    @staticmethod
    def apply_safe_units(
        base_units: float,
        wpi: float,
        sp_blocked: bool,
        safety_triggered: bool,
    ) -> tuple[float, str]:
        """
        V8.0 SafeUnits rules (applied in order):
          1. SP gate                          → 0u, status unchanged
          2. WPI < 50                         → 0u, status = "ACTION ONLY"
          3. Steam/LineFlip triggered         → cap at 1.0u
          4. WPI < 60 AND base units >= 2.5   → downgrade to 1.75u
          5. No rule fired                    → keep base_units

        Returns (safe_units, override_status_or_empty).
        override_status is non-empty only when it should replace the tier label.
        """
        # SP gate always takes priority
        if sp_blocked:
            logger.debug("apply_safe_units: SP gate BLOCKED — units %.2f → 0.0", base_units)
            return 0.0, ""

        # WPI < 50 → 0 units, display "ACTION ONLY" (V8.0 SafeStatus)
        if wpi < WPI_ZERO_UNITS_THRESHOLD:
            logger.debug(
                "apply_safe_units: WPI %.2f < %.0f — units %.2f → 0.0 (ACTION ONLY)",
                wpi, WPI_ZERO_UNITS_THRESHOLD, base_units,
            )
            return 0.0, "ACTION ONLY"

        # Safety triggered (steam or lineflip) → cap at 1.0u
        if safety_triggered:
            capped = min(base_units, MAX_UNITS_SAFETY)
            if capped < base_units:
                logger.debug(
                    "apply_safe_units: safety triggered — units %.2f → %.2f (cap %.2fu)",
                    base_units, capped, MAX_UNITS_SAFETY,
                )
            return capped, ""

        # WPI < 60 with high unit bet → downgrade (V8.0 v8.2)
        if wpi < WPI_HIGH_UNIT_MIN and base_units >= HIGH_UNIT_THRESHOLD:
            logger.debug(
                "apply_safe_units: WPI %.2f < %.0f with %.2fu — downgrade to %.2fu",
                wpi, WPI_HIGH_UNIT_MIN, base_units, DOWNGRADE_UNITS,
            )
            return DOWNGRADE_UNITS, ""

        return base_units, ""

    def evaluate(
        self,
        ev_pct: Optional[float],
        sharp_split: float = 0.0,
        wpi: float = 50.0,
        sp_gate_blocked: bool = False,
        steam_cap: bool = False,
    ) -> tuple[float, str, float]:
        """
        Full evaluation pipeline.

        steam_cap: True when steam-against (≥1.5pts) OR lineflip safety fires.
                   Caps confidence at 74% AND caps units at 1.0u (V8.0 SafeUnits).
        Returns:
            (confidence_pct, tier_name, safe_units)
        """
        confidence = self.score(ev_pct, sharp_split, wpi)

        # Steam-against / LineFlip: cap confidence at 74% (V8.0 CONF_CAP_STEAM/LINEFLIP = 74)
        if steam_cap:
            pre_cap = confidence
            confidence = min(74.0, confidence)
            if confidence < pre_cap:
                logger.debug(
                    "evaluate: steam/lineflip cap applied — confidence %.2f%% → %.2f%%",
                    pre_cap, confidence,
                )

        tier = self.assign_tier(confidence, wpi)

        # V8.0 SafeUnits: WPI gates + safety unit cap
        safe_units, status_override = self.apply_safe_units(
            base_units=tier.units,
            wpi=wpi,
            sp_blocked=sp_gate_blocked,
            safety_triggered=steam_cap,
        )

        # Status override (e.g. "ACTION ONLY" when WPI<50 zeroed units)
        tier_name = status_override if status_override else tier.name

        logger.debug(
            "ConfidenceEngine.evaluate: ev=%s  split=%+.2f  wpi=%.2f  "
            "steam_cap=%s  sp_blocked=%s  → conf=%.2f%%  tier=%s  safe_units=%.2f",
            f"{ev_pct:+.4f}%" if ev_pct is not None else "None",
            sharp_split, wpi, steam_cap, sp_gate_blocked,
            confidence, tier_name, safe_units,
        )
        return confidence, tier_name, safe_units
