"""
Global system configuration — API keys, thresholds, betting config.
All environment-sensitive values should be overridden via .env file.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Dict

# ---------------------------------------------------------------------------
# API Keys (override via environment variables or .env)
# ---------------------------------------------------------------------------
ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "8a87f7cfbd471d3d8b756654ac07b368")
WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "b25d44ec6abc4f41b11142954252611")

# ---------------------------------------------------------------------------
# The Odds API
# ---------------------------------------------------------------------------
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
MLB_SPORT_KEY = "baseball_mlb"
ODDS_REGIONS = "us"
ODDS_MARKETS = "h2h,spreads,totals"
ODDS_FORMAT = "american"

# ---------------------------------------------------------------------------
# Weather API (weatherapi.com)
# ---------------------------------------------------------------------------
WEATHER_API_BASE_URL = "https://api.weatherapi.com/v1"

# ---------------------------------------------------------------------------
# Covers.com MLB injury URL
# ---------------------------------------------------------------------------
COVERS_MLB_URL = "https://www.covers.com/sport/baseball/mlb/injuries"

# ---------------------------------------------------------------------------
# DraftKings Network — baseball splits
# Sport event-group ID for MLB = 84240 (from user-provided URL)
# ---------------------------------------------------------------------------
DRAFTKINGS_MLB_URL = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/"
DRAFTKINGS_MLB_SPORT_ID = "84240"
DRAFTKINGS_DATE_FILTER = "n7days"

# ---------------------------------------------------------------------------
# Confidence Tier Thresholds (mirrors V8.0 loosened thresholds)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TierConfig:
    name: str
    min_confidence: float      # inclusive lower bound
    units: float

TIERS: list[TierConfig] = [
    TierConfig("ELITE",     85.0, 3.0),
    TierConfig("STRONGEST", 75.0, 2.5),
    TierConfig("BEST BET",  68.0, 1.75),
    TierConfig("GOLD",      60.0, 1.0),   # V8.0: GOLD = 60-67% (BETTING_CONFIG.tiers.GOLD = 60)
    TierConfig("PASS",       0.0, 0.0),
]

# ---------------------------------------------------------------------------
# Confidence Weights (must sum to 1.0)
# ---------------------------------------------------------------------------
CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "ev":          0.35,
    "probability": 0.25,
    "clv":         0.20,
    "sharp_action":0.20,
}

# ---------------------------------------------------------------------------
# EV Gate — only compute EV for odds within this range
# MLB common: favourites can reach -300. Set wide enough to cover all MLB lines.
# ---------------------------------------------------------------------------
EV_ODDS_MIN = -400
EV_ODDS_MAX = +400

# ---------------------------------------------------------------------------
# MLB-specific betting config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BettingConfig:
    max_ml_odds: int = -200      # ignore heavy favourites beyond this
    min_ev_threshold: float = 2.0
    unit_size_dollars: float = 100.0
    sp_gate_enabled: bool = True  # Block picks when SP is Out/Doubtful

BETTING_CONFIG = BettingConfig()

# ---------------------------------------------------------------------------
# Pitcher Impact Scoring (0–100 scale)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PitcherScoringConfig:
    """
    Weights and league baselines for the pitcher impact score (0–100).

    Formula (all components fielding-independent):
        score = fip_weight  × score_fip(fip)
              + k9_weight   × score_k9(k_per_9)
              + bb9_weight  × score_bb9(bb_per_9)
              + hr9_weight  × score_hr9(hr_per_9)
              + recent_form_weight × score_era(recent_era)   ← form signal only

    ERA and WHIP are intentionally excluded from scoring — both are contaminated
    by the defense behind the pitcher (hits-in-play and unearned runs respectively).
    They are still stored and displayed for reference.

    Weight rationale (research-backed):
      FIP  0.40 — best single fielding-independent predictor of future ERA
      K/9  0.25 — most durable skill; standalone K rate adds signal beyond FIP
      BB/9 0.20 — walk control; among the most year-to-year consistent pitcher metrics
      HR/9 0.10 — HR rate; real but noisy component (partly park/luck), capped low
      Recent 0.05 — last-3-starts ERA; small sample form signal, very low weight

    League averages (MLB 2020-2024 rolling):
      FIP:  4.20  (calibrated to match ERA scale; 2024 actual = 4.07)
      K/9:  8.80  (2024 MLB average)
      BB/9: 3.10  (2024 MLB average)
      HR/9: 1.15  (calculated: 5453 HR / 43116 IP × 9, 2024 Baseball-Reference)

    FIP constant: 3.17 (5-year average from FanGraphs GUTS table 2020-2024)
    """
    # Scoring weights (must sum to 1.0)
    fip_weight:         float = 0.40
    k9_weight:          float = 0.25
    bb9_weight:         float = 0.20
    hr9_weight:         float = 0.10
    recent_form_weight: float = 0.05   # last 3 starts ERA — form signal, low weight

    # League-average baselines for 0-100 normalisation
    league_avg_fip:  float = 4.20   # rolling average; same scale as ERA by FIP construction
    league_avg_k9:   float = 8.80
    league_avg_bb9:  float = 3.10
    league_avg_hr9:  float = 1.15   # HR/9: 5453 HR / 43116 IP × 9 (Baseball-Reference 2024)

    # FIP constant (re-centers FIP onto ERA scale)
    # Source: FanGraphs GUTS table — 5-year average 2020-2024 (3.11-3.26 range)
    fip_constant: float = 3.17

PITCHER_SCORING = PitcherScoringConfig()

# ---------------------------------------------------------------------------
# Automation intervals (minutes)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SchedulerConfig:
    full_refresh_min: int = 360
    odds_min: int = 30
    injuries_min: int = 120
    weather_min: int = 240
    dk_splits_min: int = 180
    pitchers_min: int = 60
    live_predictions_min: int = 10

SCHEDULER_CONFIG = SchedulerConfig()
