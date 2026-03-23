# MLB Betting System — Complete Implementation Reference

> Authoritative technical reference for Claude Code sessions.
> Read this file first before making any changes to the codebase.
> Last updated: March 2026 — V8.0 formula alignment complete.

---

## 1. What This System Is

A Python-based MLB moneyline betting prediction system that replicates and
extends the logic from a V8.0 Google Apps Script system (NBA/NFL/MLB).

The system:
- Fetches live MLB odds, injuries, weather, DraftKings sharp splits, and pitcher data
- Runs a multi-layer prediction engine (probability → EV → confidence → tier)
- Serves a browser dashboard (FastAPI + Jinja2) with Live Picks and MLB Model pages
- Saves output as JSON/CSV files in `output_data/`

**How to run:**
```bash
uvicorn app:app --reload --port 8000
# Open: http://localhost:8000
```

---

## 2. Directory Structure

```
MLB Baseball System/
├── app.py                    # FastAPI app entry point
├── main.py                   # CLI entry point (manual refresh)
├── pipeline.py               # MLBPipeline — orchestrates all phases
│
├── config/
│   ├── settings.py           # API keys, tier thresholds, weights, intervals
│   └── mlb_config.py         # Team definitions, TEAM_BY_KEY lookup
│
├── models/
│   ├── game.py               # Game, GameOdds, OddsLine dataclasses
│   ├── prediction.py         # Prediction dataclass + to_dict()
│   ├── pitcher.py            # PitcherStats dataclass
│   └── bet.py                # BetLog dataclass
│
├── data/                     # External data clients (Phase 1)
│   ├── odds_client.py        # The Odds API → Game objects
│   ├── injury_scraper.py     # Covers.com MLB injury scraper
│   ├── weather_client.py     # WeatherAPI.com
│   ├── draftking_scraper.py  # DK Network betting splits
│   └── pitcher_client.py     # MLB Stats API probable starters
│
├── engine/                   # Calculation modules (Phase 2)
│   ├── probability.py        # Vig removal, injury adj, pitcher adj
│   ├── ev_calculator.py      # EV% from probability + american odds
│   ├── confidence.py         # V8.0 confidence formula + tier assignment
│   ├── prediction_engine.py  # Orchestrates all engine modules per game
│   ├── injury_impact.py      # Probability delta from injury reports
│   ├── weather_impact.py     # O/U adjustment from wind/temp/precip
│   └── pitcher_impact.py     # Pitcher score (0-100) from stats
│
├── output/
│   ├── predictions.py        # LivePredictions — in-memory + JSON/CSV save
│   ├── clv_tracker.py        # Closing Line Value tracking
│   └── bet_logger.py         # Manual bet logging
│
├── mlb/
│   ├── teams.py              # Team name normalisation
│   ├── stadiums.py           # Stadium → city/dome mapping
│   └── ballpark_factors.py   # Park run factors (future use)
│
├── scheduler/
│   └── runner.py             # APScheduler background refresh jobs
│
├── web/
│   ├── routers/              # FastAPI route handlers
│   │   ├── predictions.py    # /api/predictions, /api/predictions/model
│   │   ├── bets.py           # /api/bets
│   │   ├── health.py         # /api/health, feed status
│   │   ├── config_router.py  # /api/config
│   │   └── scheduler_api.py  # /api/scheduler
│   ├── templates/            # Jinja2 HTML pages
│   │   ├── base.html         # Sidebar layout
│   │   ├── index.html        # Dashboard
│   │   ├── predictions.html  # Live Picks page
│   │   ├── model.html        # MLB Model page (all games)
│   │   ├── bets.html         # Bet logger
│   │   ├── analytics.html    # Analytics
│   │   └── config.html       # Config page
│   └── static/
│       ├── css/main.css
│       └── js/
│           ├── api.js        # API.get() / API.post() helpers
│           ├── utils.js      # fmtOdds, fmtPct, tierBadge, countdown
│           ├── predictions.js
│           └── model.js
│
├── output_data/              # Runtime JSON/CSV output (gitignored)
│   ├── live_predictions_YYYYMMDD.json
│   └── mlb_model_YYYYMMDD.json
│
├── CLAUDE.md                 # This file
└── CLAUDE_NOTES.md           # Future enhancement roadmap
```

---

## 3. Data Flow — Start to Finish

```
┌─────────────────────────────────────────────────────────────┐
│  PHASE 1 — Data Collection  (pipeline.py)                   │
│                                                             │
│  odds_client      → Game[]  (ML, spread, total, open lines) │
│  injury_scraper   → RawInjury[]  (Covers.com)               │
│  weather_client   → WeatherData{}  (WeatherAPI.com)         │
│  draftking_scraper→ SplitEntry[]  (DK Network page)         │
│  pitcher_client   → PitcherStats{}  (MLB Stats API)         │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  PHASE 1B — Apply Impacts  (_apply_impacts)                  │
│                                                             │
│  injury_engine    → game.away/home_injury_impact            │
│                  → game.sp_gate_blocked                     │
│  weather_engine   → game.weather_over/under_adj             │
│  pitcher_engine   → game.away/home_pitcher_score (0-100)    │
│                  → game.away/home_pitcher_name              │
│  dk splits        → game.away/home_handle_pct               │
│                  → game.away/home_bets_pct                  │
│                  → game.sharp_split_score (SSS)             │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  PHASE 2 — Prediction Engine  (prediction_engine.py)        │
│                                                             │
│  Per game:                                                  │
│  1. vig-free ML probability                                 │
│  2. injury probability adjustment                           │
│  3. pitcher probability adjustment (±10% max)              │
│  4. EV for both sides                                       │
│  5. Pick by highest EV                                      │
│  6. Negative EV gate → PASS                                 │
│  7. CLV delta (opening vs current spread)                   │
│  8. SharpSplit = ourHandle% - ourBets%  (signed)            │
│  9. WPI = 50 + (ourHandle - 50) × 1.5                      │
│  10. Confidence = evNorm×0.5 + SharpScore×0.5              │
│  11. Steam-against safety cap (≥1.5pts → cap 74%)          │
│  12. Steam auto-pass (≥2pts → 0 units)                     │
│  13. LineFlip cap (sign change + SharpScore<70 → cap 74%)  │
│  14. WPI tier gating                                        │
│  15. SP gate (SP blocked → 0 units)                        │
│  16. Assign tier → Prediction                              │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  OUTPUT                                                     │
│                                                             │
│  qualified picks (non-PASS) → live_predictions_YYYYMMDD.json│
│  all games (incl. PASS)     → mlb_model_YYYYMMDD.json       │
│  both                       → CSV                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Core Formulas (V8.0 Aligned)

### Vig-Free Probability
```python
raw_away = abs(away_odds) / (abs(away_odds) + 100)  # if negative
raw_away = 100 / (away_odds + 100)                   # if positive
total = raw_away + raw_home
true_away = raw_away / total * 100
true_home = raw_home / total * 100
```

### Pitcher Probability Adjustment
```python
edge = away_pitcher_score - home_pitcher_score   # -100 to +100
prob_shift = (edge / 50.0) * 5.0                 # max ±10pp
# Re-normalise to 100% after shift
```
With all pitchers = 50 (spring training): no effect.
With real season stats (ERA 2.1 vs 5.8): meaningful probability divergence.

### EV Calculation
```python
decimal_odds = 1 + american / 100     # if positive
decimal_odds = 1 + 100 / abs(american) # if negative
ev_pct = (prob/100 * (decimal - 1)) - ((1 - prob/100) * 1)  # × 100
```
EV gate: ±400 (covers all realistic MLB lines).
EV = -(vig%) when prob = market-implied (no adjustments active).
EV diverges when pitcher/injury adjustments shift prob away from market.

### Pick Selection (V8.0: by EV, not probability)
```python
# Calculate EV for both sides, pick the higher one
# If best EV < 0 → PASS immediately (negative EV gate)
```

### SharpSplit and WPI (V8.0)
```python
sharp_split = our_handle_pct - our_bets_pct   # signed
wpi = min(100, max(0, 50 + (our_handle_pct - 50) * 1.5))
sharp_score = min(100, max(0, 50 + sharp_split * 0.5 + (wpi - 50) * 0.4))
```

### Confidence Formula (V8.0 exact)
```python
ev_norm     = min(80, max(0, 50 + ev_pct * 2))
sharp_score = 50 + sharp_split * 0.5 + (wpi - 50) * 0.4
confidence  = min(95, max(25, ev_norm * 0.50 + sharp_score * 0.50))
```

### Tier Assignment with WPI Gating
```
ELITE      confidence ≥ 85%  AND  WPI ≥ 75
STRONGEST  confidence ≥ 75%  AND  WPI ≥ 65
BEST BET   confidence ≥ 68%  AND  WPI ≥ 55
GOLD       confidence ≥ 55%  AND  WPI ≥ 0
PASS       everything else
```

### Safety Layers
```
Steam-against cap:   CLV adverse ≥ 1.5pts → cap confidence at 74%
Steam auto-pass:     CLV adverse ≥ 2.0pts → 0 units (tier kept)
LineFlip cap:        spread sign changed + SharpScore < 70 → cap at 74%
SP gate:             sp_gate_blocked = True → 0 units
```

### Pitcher Score (0–100)
```python
composite = (
    era_score  * 0.30 +
    whip_score * 0.25 +
    k9_score   * 0.20 +
    bb9_score  * 0.15 +
    recent_era * 0.10
)
# Each stat scored 0-100 relative to league average (ERA 4.20, WHIP 1.30, K/9 8.80, BB/9 3.10)
# TBD pitcher = 50 (neutral)
```

### SSS (Sharp Split Score)
```python
# Max gap between Bets% and Handle% across spread + total only
# Moneyline EXCLUDED per V8.0 spec
sss = max(
    abs(away_spread_bets - away_spread_handle),
    abs(home_spread_bets - home_spread_handle),
    abs(over_bets - over_handle),
    abs(under_bets - under_handle),
)
```

### Units by Tier
| Tier | Min Confidence | Units |
|---|---|---|
| ELITE | 85% | 3.0u |
| STRONGEST | 75% | 2.5u |
| BEST BET | 68% | 1.75u |
| GOLD | 55% | 1.0u |
| PASS | 0% | 0u |

---

## 5. External Data Sources

### The Odds API
- **URL:** `https://api.the-odds-api.com/v4`
- **Markets:** `h2h,spreads,totals`
- **Key:** `ODDS_API_KEY` in `config/settings.py`
- **Returns:** Away/Home ML, spread, total for each game
- **Also stores:** Opening spread in `GameOdds.away_spread_open / home_spread_open`

### DraftKings Network (Betting Splits)
- **URL:** `https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/?tb_eg=84240&tb_edate=n7days&tb_emt=0`
- **Method:** Plain HTTP GET (server-side rendered HTML, NO Playwright needed)
- **Sport ID:** `84240` (MLB)
- **HTML parsing:** Split by `<div class="tb-se">` per game, `<div class="tb-sodd">` per option
- **Handle% is 3rd `<div>`, Bets% is 4th `<div>` after splitting option HTML**
- **Returns:** `SplitEntry` with all bets/handle % for ML, spread, total

### Weather API
- **Provider:** WeatherAPI.com
- **Key:** `WEATHER_API_KEY` in `config/settings.py`
- **Used for:** Temperature, wind speed/direction, precipitation per stadium
- **Dome stadiums** skip weather adjustment automatically

### Injury Scraper
- **Source:** Covers.com (`https://www.covers.com/sport/baseball/mlb/injuries`)
- **Parses:** Player name, team, position, status (Out/Doubtful/Questionable)
- **SP Gate:** If a probable SP is Out/Doubtful → `sp_gate_blocked = True` → 0 units

### MLB Stats API (Pitcher Data)
- **Free, no key required**
- **Fetches:** Probable starters for today's games
- **Stats:** ERA, WHIP, K/9, BB/9, recent form ERA (last 3 starts)
- **Spring training caveat:** Returns empty 2026 stats until regular season
  → all pitchers default to score 50 (neutral) → no probability adjustment

---

## 6. Key Models

### Game (`models/game.py`)
Primary input flowing through the entire pipeline.
```python
game_id, away_team, home_team, commence_time, venue, city
odds: GameOdds              # ML, spread, total + opening lines
away/home_injury_impact     # probability delta from injuries
weather_over/under_adj      # O/U line adjustment
sp_gate_blocked             # True if probable SP is Out/Doubtful
sharp_split_score           # SSS (default 50 = neutral)
away/home_handle_pct        # DK handle% (default 50)
away/home_bets_pct          # DK bets% for SharpSplit calc (default 50)
away/home_pitcher_score     # 0-100 (default 50 = neutral)
away/home_pitcher_name      # "TBD" if unknown
temperature_f, wind_speed_mph, wind_direction, precipitation, is_dome
```
**Important defaults:** All split/score fields default to 50.0 (neutral, not 0).
Using 0 would penalise confidence when data is unavailable.

### Prediction (`models/prediction.py`)
Output of the engine for one game.
```python
game_id, matchup, game_date
away_ml, home_ml, away_spread, home_spread, total_line  # raw odds
away_prob_pct, home_prob_pct    # both-side model probabilities
away_ev_pct, home_ev_pct        # both-side EV (None if outside gate)
picked_team, picked_team_name, bet_type, bet_price
prob_pct, ev_pct                # picked side
confidence_pct, units, status, safe_units
clv_delta, sharp_split_score
away/home_pitcher_name/score
away/home_injury_impact
weather_over/under_adj
sp_gate_blocked
prediction_text                 # human-readable summary
```

---

## 7. Pipeline Scheduling

`scheduler/runner.py` runs APScheduler background jobs:

| Job | Interval | What it does |
|---|---|---|
| `full_refresh` | 360 min | All phases in sequence |
| `refresh_odds` | 30 min | Odds API only |
| `refresh_injuries` | 120 min | Covers.com scrape |
| `refresh_weather` | 240 min | WeatherAPI fetch |
| `refresh_dk_splits` | 180 min | DK Network scrape |
| `refresh_pitchers` | 60 min | MLB Stats API |
| `live_predictions` | 10 min | Re-run engine with cached data |

---

## 8. API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/predictions` | Qualified picks (non-PASS) from today's JSON |
| GET | `/api/predictions/model` | All games including PASS |
| POST | `/api/predictions/refresh` | Trigger full pipeline refresh |
| POST | `/api/predictions/refresh/odds` | Odds only |
| POST | `/api/predictions/refresh/pitchers` | Pitchers only |
| GET | `/api/health` | Feed status per data source |
| GET | `/api/bets` | Logged bets |
| POST | `/api/bets/log` | Log a bet |

---

## 9. Web Pages

| URL | Page | Description |
|---|---|---|
| `/dashboard` | Dashboard | Summary cards, feed health |
| `/predictions` | Live Picks | Qualified picks (GOLD+) with Log Bet button |
| `/model` | MLB Model | ALL games, all tiers including PASS, 24 columns |
| `/bets` | Bet Logger | Track logged bets |
| `/analytics` | Analytics | Historical performance |
| `/config` | Config | Scheduler settings |

### MLB Model page columns (model.html)
Date, Matchup, Away SP, Home SP, Away ML, Home ML, Away Spread, Home Spread,
O/U, **Away Prob%, Home Prob%, Away EV%, Home EV%**, Conf%, Status, Units,
CLV Δ, SSS, Away Inj, Home Inj, W O/U adj, SP Gate, Pick, Prediction

---

## 10. Configuration (config/settings.py)

```python
ODDS_API_KEY              = "..."      # The Odds API
WEATHER_API_KEY           = "..."      # WeatherAPI.com

# EV gate — covers all realistic MLB lines
EV_ODDS_MIN = -400
EV_ODDS_MAX = +400

# Tier thresholds
TIERS = [
    TierConfig("ELITE",     85.0, 3.0),
    TierConfig("STRONGEST", 75.0, 2.5),
    TierConfig("BEST BET",  68.0, 1.75),
    TierConfig("GOLD",      55.0, 1.0),
    TierConfig("PASS",       0.0, 0.0),
]

# DraftKings Network
DRAFTKINGS_MLB_URL      = "https://dknetwork.draftkings.com/..."
DRAFTKINGS_MLB_SPORT_ID = "84240"
DRAFTKINGS_DATE_FILTER  = "n7days"
```

---

## 11. Known Behaviours and Gotchas

### Spring training (March) shows all PASS — this is correct
- MLB Stats API returns no 2026 season stats until regular season
- All pitcher scores = 50 → no probability adjustment → EV = -(vig%) always
- Will naturally improve when real stats load in April

### EV is identical for both teams — this is correct mathematics
`EV = 1/overround - 1` when probability = market-implied.
Both sides reduce to the same value. EV only differs when pitcher/injury
adjustments push one side's probability away from market-implied.

### SSS/handle defaults are 50.0, not 0.0
Using 0.0 would penalise confidence when DK data is unavailable.
50.0 = neutral (no sharp signal either way).

### DraftKings scraper uses plain HTTP — no Playwright
The DK Network page is server-side rendered. `requests` + `BeautifulSoup` is sufficient.
The old sportsbook.draftkings.com URL gave 403 errors. Use only the DK Network URL.

### EV shows None / "—" for extreme lines
Lines outside ±400 return None from EVCalculator. Displayed as "—" in the model table.
This is correct — extreme lines (e.g. -800) are not valid betting targets.

### Pick is by EV, not probability (V8.0 alignment)
A 45% underdog at +280 can have better EV than a 55% favourite at -190.
The system picks the highest-EV side. Negative EV → PASS regardless of probability.

---

## 12. V8.0 Alignment Status

The system is fully aligned to V8.0 Phase2_formulas.js logic:

| V8.0 Feature | Status | File |
|---|---|---|
| evNorm × 0.5 + SharpScore × 0.5 | Done | `engine/confidence.py` |
| SharpSplit = handle - bets (signed) | Done | `engine/prediction_engine.py` |
| WPI = 50 + (handle-50) × 1.5 | Done | `engine/prediction_engine.py` |
| SharpScore = 50 + split×0.5 + (wpi-50)×0.4 | Done | `engine/confidence.py` |
| Pick by EV (not probability) | Done | `engine/prediction_engine.py` |
| Negative EV gate → PASS | Done | `engine/prediction_engine.py` |
| Steam-against cap (≥1.5pts) | Done | `engine/prediction_engine.py` |
| Steam auto-pass (≥2pts) | Done | `engine/prediction_engine.py` |
| LineFlip cap | Done | `engine/prediction_engine.py` |
| WPI tier gating | Done | `engine/confidence.py` |
| SP gate | Done | `engine/confidence.py` |
| Both-side EV/Prob columns | Done | `models/prediction.py`, `model.js` |

---

## 13. Future Enhancements (see CLAUDE_NOTES.md for full detail)

1. **Line shopping** — check FanDuel/BetMGM/Caesars for best price per pick
2. **CLV closing line tracking** — fetch odds 5min before game time for true CLV
3. **Team offensive stats** — wRC+, OPS, FIP from MLB Stats API for independent probability model
4. **Bullpen availability** — recent pitcher usage + bullpen ERA
5. **Situational patterns** — road underdogs after blowout, short rest, etc.
6. **Platoon splits** — pitcher handedness vs lineup composition
