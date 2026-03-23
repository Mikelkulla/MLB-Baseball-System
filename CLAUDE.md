# MLB Betting System — Complete Implementation Reference

> Authoritative technical reference for Claude Code sessions.
> Read this file first before making any changes to the codebase.
> Last updated: March 2026 — v1.0.0

---

## 0. Mandatory Rules for Every Change

These rules apply to **every** code change, no exceptions.

1. **Wire everything.** When a formula, field, or feature changes, update it in
   every place it is referenced: model dataclass, pipeline `_apply_impacts()`,
   prediction engine, API router, Jinja2 template, frontend JS, CSV export.
   A partial update is a bug. Trace the full chain before closing a task.

2. **Keep `/help` in sync.** Every change that affects a formula, column,
   adjustment, data source, API endpoint, or UI page must be reflected in the
   corresponding page under `help/`. If the formula reference page
   (`help/reference/index.html`) is affected, update it too.

3. **Update this file.** After every change, update CLAUDE.md to reflect the
   new state. The goal is that CLAUDE.md is always accurate to the live code —
   never stale.

---

## 1. What This System Is

A Python-based MLB moneyline betting prediction system that replicates and
extends the logic from a V8.0 Google Apps Script system (NBA/NFL/MLB).

The system:
- Fetches live MLB odds, injuries, weather, DraftKings sharp splits, pitcher data, and bullpen data
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
│   ├── pitcher_client.py     # MLB Stats API probable starters
│   └── bullpen_client.py     # MLB Stats API team pitching (bullpen depth)
│
├── engine/                   # Calculation modules (Phase 2)
│   ├── probability.py        # Vig removal, injury adj, pitcher adj
│   ├── ev_calculator.py      # EV% from probability + american odds
│   ├── confidence.py         # V8.0 confidence formula + tier assignment
│   ├── prediction_engine.py  # Orchestrates all engine modules per game
│   ├── injury_impact.py      # Probability delta from injury reports
│   ├── weather_impact.py     # O/U adjustment from wind/temp/precip
│   ├── pitcher_impact.py     # Pitcher score (0-100) from stats
│   └── bullpen_impact.py     # Bullpen depth score (0-100) from team pitching stats
│
├── output/
│   ├── predictions.py        # LivePredictions — in-memory + JSON/CSV save
│   ├── clv_tracker.py        # Closing Line Value tracking
│   └── bet_logger.py         # Manual bet logging
│
├── mlb/
│   ├── teams.py              # Team name normalisation
│   ├── stadiums.py           # Stadium → city/dome mapping
│   └── ballpark_factors.py   # Park run factors + O/U adjustments
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
│   │   ├── base.html         # Sidebar layout + help button (v1.0.0)
│   │   ├── index.html        # Dashboard
│   │   ├── predictions.html  # Live Picks page
│   │   ├── model.html        # MLB Model page (all games, 28 columns)
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
├── help/                     # Static HTML documentation (served at /help)
│   ├── index.html            # Documentation hub
│   ├── assets/style.css      # Dark-theme doc styles
│   ├── overview/index.html   # Architecture & data flow
│   ├── pipeline/index.html   # Pipeline phases & scheduler
│   ├── engine/               # probability.html, ev.html, confidence.html
│   ├── adjustments/          # pitcher, bullpen, injuries, weather, park-factors
│   ├── data-sources/index.html
│   ├── web/index.html        # Pages, API endpoints, model columns
│   └── reference/index.html  # All formulas on one page
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
│  bullpen_client   → BullpenStats{}  (MLB Stats API)         │
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
│  bullpen_engine   → game.away/home_bullpen_score (0-100)    │
│  park_factors     → game.park_factor                        │
│                  → game.park_ou_adj                         │
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
│  3. pitcher probability adjustment (±10pp max)             │
│  4. bullpen probability adjustment (±4pp max)              │
│  5. EV for both sides                                       │
│  6. Pick by highest EV                                      │
│  7. Soft EV gate: EV<0 + prob≥55% → GOLD at 1.0u (EV-CAP) │
│     EV<0 + prob<55% → PASS                                  │
│  8. CLV delta (opening vs current spread)                   │
│  9. SharpSplit = ourHandle% - ourBets%  (signed)            │
│  10. WPI = 50 + (ourHandle - 50) × 1.5                     │
│  11. Confidence = evNorm×0.5 + SharpScore×0.5              │
│  12. Steam-against safety cap (≥1.5pts → cap 74%)          │
│  13. Steam auto-pass (≥2pts → 0 units)                     │
│  14. LineFlip cap (sign change + SharpScore<70 → cap 74%)  │
│  15. WPI tier gating                                        │
│  16. SP gate (SP blocked → 0 units)                        │
│  17. Assign tier → Prediction                              │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  OUTPUT                                                     │
│                                                             │
│  qualified picks (non-PASS) → live_predictions_YYYYMMDD.json│
│  all games (incl. PASS)     → mlb_model_YYYYMMDD.json       │
│  both                       → CSV (31 fields)               │
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
prob_shift = (edge / 50.0) * 5.0 * park_scaling  # max ±10pp
# Re-normalise to 100% after shift
```
With all pitchers = 50 (spring training): no effect.
With real season stats (ERA 2.1 vs 5.8): meaningful probability divergence.

### Bullpen Probability Adjustment
```python
edge = away_bullpen_score - home_bullpen_score   # -100 to +100
prob_shift = (edge / 50.0) * 2.0 * park_scaling  # max ±4pp
# Re-normalise to 100% after shift
```

### Park Pitcher Scaling
```python
park_scaling = CLAMP(2.0 - park_factor, 0.60, 1.25)
# High run-environment parks → pitcher edge matters less
```

### Park O/U Adjustment
```python
park_ou_adj = (park_factor - 1.0) * 5.3
# Colorado Rockies excluded — altitude handled by weather engine to prevent double-count
```

### EV Calculation
```python
decimal_odds = 1 + american / 100      # if positive
decimal_odds = 1 + 100 / abs(american) # if negative
ev_pct = (prob/100 * (decimal - 1)) - ((1 - prob/100) * 1)  # × 100
```
EV gate: ±400 (covers all realistic MLB lines).
Probability always comes from ML vig-removal. EV is calculated against the best
available ML price across all books — same event, same market, correct comparison.
Run line prices are NOT used for probability (the run line is a different event:
win by 2+, ≈72% of ML wins due to 28% of MLB games ending by exactly 1 run).
Using run line prices for both probability AND EV is circular and always yields
EV = -(vig%), making every game PASS.

### Pick Selection (V8.0: by EV, not probability)
```python
# Calculate EV for both sides, pick the higher one
# Soft EV gate (EV_SOFT_GATE_PROB_MIN = 55.0):
#   EV < 0  AND  prob >= 55% → force tier=GOLD, safe_units=1.0u  ("EV-CAP")
#                              (overrides 0u from PASS tier; higher tiers capped DOWN to 1.0u)
#   EV < 0  AND  prob <  55% → PASS (0 units)
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
ELITE      confidence ≥ 85%  AND  WPI ≥ 75   →  3.0u
STRONGEST  confidence ≥ 75%  AND  WPI ≥ 65   →  2.5u
BEST BET   confidence ≥ 68%  AND  WPI ≥ 55   →  1.75u
GOLD       confidence ≥ 60%  AND  WPI ≥ 0    →  1.0u
PASS       everything else                    →  0u
```
Note: GOLD minimum is **60%** (not 55%) — confirmed in `config/settings.py`.

### Safety Layers
```
Steam-against cap:   CLV adverse ≥ 1.5pts → cap confidence at 74%
Steam auto-pass:     CLV adverse ≥ 2.0pts → 0 units (tier kept)
LineFlip cap:        spread sign changed + SharpScore < 70 → cap at 74%
SP gate:             sp_gate_blocked = True → 0 units
Soft EV gate:        EV < 0 AND prob ≥ 55% → force GOLD at 1.0u ("EV-CAP")
                     EV < 0 AND prob < 55% → PASS (0 units)
```

### Pitcher Score (0–100)
```python
# FIP-based formula (fielding-independent — ERA and WHIP intentionally excluded)
# FIP calculated from raw counts: ((13×HR) + (3×(BB+HBP)) - (2×K)) / IP + 3.17
composite = (
    fip_score    * 0.40 +   # FIP: best single predictor of future ERA (FanGraphs)
    k9_score     * 0.25 +   # K/9: most durable and consistent pitcher skill
    bb9_score    * 0.20 +   # BB/9: highly consistent year-to-year
    hr9_score    * 0.10 +   # HR/9: real but partly park/luck noise
    recent_era   * 0.05     # last-3-starts ERA: small form signal, low weight
)
# League averages (2024): FIP 4.20, K/9 8.80, BB/9 3.10, HR/9 1.15
# ERA and WHIP stored for display only — NOT used in scoring (defense-contaminated)
# TBD pitcher = 50 (neutral)
```

### Bullpen Score (0–100)
```python
composite = (
    fip_score    * 0.45 +   # FIP: primary signal for pen quality
    k9_score     * 0.30 +   # K/9: bullpen strikeout rate
    bb9_score    * 0.25     # BB/9: command under pressure
)
# Same league-average normalisation as pitcher score
# Teams with fewer than 10 games played → return 50.0 (neutral, spring training)
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
| Tier | Min Confidence | Min WPI | Units |
|---|---|---|---|
| ELITE | 85% | 75 | 3.0u |
| STRONGEST | 75% | 65 | 2.5u |
| BEST BET | 68% | 55 | 1.75u |
| GOLD | 60% | 0 | 1.0u |
| PASS | — | — | 0u |

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
- **File:** `data/pitcher_client.py`
- **Fetches:** Probable starters for today's games
- **Stats:** ERA, WHIP, K/9, BB/9, recent form ERA (last 3 starts)
- **Spring training caveat:** Returns empty 2026 stats until regular season
  → all pitchers default to score 50 (neutral) → no probability adjustment

### MLB Stats API (Bullpen/Team Pitching)
- **Free, no key required**
- **File:** `data/bullpen_client.py`
- **Fetches:** Team season pitching stats (bullpen depth)
- **Stats:** FIP (calculated from HR, BB, HBP, K, IP), K/9, BB/9
- **Gate:** Teams with fewer than 10 games → score 50 (neutral)
- **Refresh interval:** 120 min

---

## 6. Key Models

### Game (`models/game.py`)
Primary input flowing through the entire pipeline.
```python
game_id, sport, away_team, home_team, commence_time, venue, city
odds: GameOdds              # ML, spread, total + opening lines
away_injury_impact          # probability delta from injuries (away)
home_injury_impact          # probability delta from injuries (home)
weather_over_adj            # O/U line over adjustment
weather_under_adj           # O/U line under adjustment
sp_gate_blocked             # True if probable SP is Out/Doubtful
sharp_split_score           # SSS (default 50 = neutral)
away_handle_pct             # DK handle% (default 50)
home_handle_pct
over_handle_pct
under_handle_pct
away_bets_pct               # DK bets% (default 50)
home_bets_pct
away_pitcher_score          # 0-100 (default 50 = neutral)
home_pitcher_score
away_pitcher_name           # "TBD" if unknown
home_pitcher_name
away_bullpen_score          # 0-100 team pitching depth (default 50)
home_bullpen_score
park_factor                 # Home ballpark run factor (default 1.00)
park_ou_adj                 # Park O/U adjustment in points (Coors = 0)
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
away_pitcher_name, away_pitcher_score
home_pitcher_name, home_pitcher_score
away_bullpen_score, home_bullpen_score
park_factor, park_ou_adj
away_injury_impact, home_injury_impact
weather_over_adj, weather_under_adj
sp_gate_blocked
prediction_text                 # human-readable summary
```

---

## 7. Pipeline Scheduling

`scheduler/runner.py` runs APScheduler background jobs:

| Job | Default interval | What it does |
|---|---|---|
| `full_refresh` | 360 min | All phases in sequence |
| `refresh_odds` | 30 min | Odds API only |
| `refresh_injuries` | 120 min | Covers.com scrape |
| `refresh_weather` | 240 min | WeatherAPI fetch |
| `refresh_dk_splits` | 180 min | DK Network scrape |
| `refresh_pitchers` | 60 min | MLB Stats API probable starters |
| `refresh_bullpens` | 120 min | MLB Stats API team pitching |
| `live_predictions` | 10 min | Re-run engine with cached data |

### Scheduler Presets
| Preset | When to use | Behaviour |
|---|---|---|
| `gameday` | Active game day | Odds every 10min, predictions every 5min |
| `active` | Default normal operation | Odds every 15min, predictions every 5min |
| `low_activity` | Off-day / pre-season | Odds every 120min, predictions every 30min |

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
| GET | `/api/config` | Current scheduler configuration |
| GET | `/api/scheduler` | Scheduler job status |

---

## 9. Web Pages

| URL | Page | Description |
|---|---|---|
| `/dashboard` | Dashboard | Summary cards, feed health |
| `/predictions` | Live Picks | Qualified picks (GOLD+) with Log Bet button |
| `/model` | MLB Model | ALL games, all tiers including PASS, 28 columns |
| `/bets` | Bet Logger | Track logged bets |
| `/analytics` | Analytics | Historical performance |
| `/config` | Config | Scheduler settings |
| `/help` | Documentation | Static HTML docs (served via StaticFiles) |
| `/docs` | API Docs | FastAPI auto-generated OpenAPI explorer |

### MLB Model page — 28 columns (model.html / model.js)
| # | Column | Description |
|---|---|---|
| 1 | Date | Game date (local time) |
| 2 | Matchup | Away @ Home |
| 3 | Away SP | Away starting pitcher name and score (0–100) |
| 4 | Home SP | Home starting pitcher name and score (0–100) |
| 5 | Away BP | Away bullpen depth score (0–100; green >55, red <45) |
| 6 | Home BP | Home bullpen depth score (0–100) |
| 7 | Park | Home park run factor (green >1.05, red <0.95) |
| 8 | Park O/U | Park O/U adjustment in points (Coors excluded) |
| 9 | Away ML | Away moneyline odds |
| 10 | Home ML | Home moneyline odds |
| 11 | Away Spread | Away run line (±1.5) and price |
| 12 | Home Spread | Home run line and price |
| 13 | O/U | Over/Under total and price |
| 14 | Away Prob% | Model win probability for away side |
| 15 | Home Prob% | Model win probability for home side |
| 16 | Away EV% | Expected value for betting away ML ("—" if outside ±400) |
| 17 | Home EV% | Expected value for betting home ML |
| 18 | Conf% | Model confidence (evNorm×0.5 + SharpScore×0.5) |
| 19 | Status | Tier: ELITE / STRONGEST / BEST BET / GOLD / PASS |
| 20 | Units | Recommended bet size after SafeUnits rules |
| 21 | CLV Δ | Closing line value delta (opening vs current spread) |
| 22 | SSS | Sharp Split Score (max bets/handle gap, spread + totals) |
| 23 | Away Inj | Away injury impact (negative = team is hurt) |
| 24 | Home Inj | Home injury impact |
| 25 | W O/U adj | Weather Over/Under adjustment |
| 26 | SP Gate | True if probable SP is Out/Doubtful (units zeroed) |
| 27 | Pick | Picked team name and odds |
| 28 | Prediction | Human-readable summary text |

---

## 10. Configuration (config/settings.py)

```python
ODDS_API_KEY              = "..."      # The Odds API
WEATHER_API_KEY           = "..."      # WeatherAPI.com

# EV gate — covers all realistic MLB lines
EV_ODDS_MIN = -400
EV_ODDS_MAX = +400

# Tier thresholds (with WPI gates)
TIERS = [
    TierConfig("ELITE",     85.0, 3.0),
    TierConfig("STRONGEST", 75.0, 2.5),
    TierConfig("BEST BET",  68.0, 1.75),
    TierConfig("GOLD",      60.0, 1.0),   # 60%, not 55%
    TierConfig("PASS",       0.0, 0.0),
]

# DraftKings Network
DRAFTKINGS_MLB_URL      = "https://dknetwork.draftkings.com/..."
DRAFTKINGS_MLB_SPORT_ID = "84240"
DRAFTKINGS_DATE_FILTER  = "n7days"
```

---

## 11. Known Behaviours and Gotchas

### Spring training (March) may show mostly PASS — partially expected
- MLB Stats API returns no 2026 season stats until regular season
- All pitcher and bullpen scores = 50 → no probability adjustment from those sources
- The ML consensus probability will still diverge from any single book's implied odds,
  creating some positive-EV picks on correctly-priced underdogs/favorites
- Will improve further when real pitcher/bullpen stats load in April

### EV is identical for both teams — this is correct mathematics
`EV = 1/overround - 1` when probability = market-implied.
Both sides reduce to the same value. EV only differs when pitcher/injury/bullpen
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

### Coors Field double-count prevention
`weather_impact.py` applies +2.0 Over for altitude ≥ 4,000 ft.
`park_ou_adjustment_display()` returns 0.0 for `colorado_rockies` to prevent
double-counting. Do not change this without adjusting the weather engine too.

### Weather cold logic is counterintuitive by design
Below 40°F the system applies a slight **Over** adjustment, not Under.
Research shows OVER hits ~57% below 40°F because pitcher grip loss creates more
walks/wild pitches, outweighing bat-speed reduction. Temperatures 41–55°F apply
a modest Under adjustment — bat speed reduction dominates at this range.

### Light rain is an Over signal
+0.5 Over for light rain. Light precipitation causes 3.6% more runs on average
(pitcher grip issues → more walks). Only heavy rain suppresses scoring.

### FIP replaces ERA in pitcher scoring
ERA and WHIP are stored and displayed for reference only. The scoring formula uses
FIP (from raw MLB Stats API counts), K/9, BB/9, HR/9, and recent ERA as a form
signal. ERA excluded because it is contaminated by the defense behind the pitcher.

### Bullpen scoring has a 10-game gate
Teams with fewer than 10 games played return score 50 (neutral). Avoids misleading
scores from tiny sample sizes at the start of the season or for incomplete data.

---

## 12. V8.0 Alignment Status

The system is fully aligned to V8.0 Phase2_formulas.js logic, with additional
enhancements (bullpen scoring, park factors) layered on top:

| Feature | Status | File |
|---|---|---|
| evNorm × 0.5 + SharpScore × 0.5 | Done | `engine/confidence.py` |
| SharpSplit = handle - bets (signed) | Done | `engine/prediction_engine.py` |
| WPI = 50 + (handle-50) × 1.5 | Done | `engine/prediction_engine.py` |
| SharpScore = 50 + split×0.5 + (wpi-50)×0.4 | Done | `engine/confidence.py` |
| Pick by EV (not probability) | Done | `engine/prediction_engine.py` |
| Soft EV gate (EV<0+prob≥55% → cap 1u; else PASS) | Done | `engine/prediction_engine.py` |
| Steam-against cap (≥1.5pts) | Done | `engine/prediction_engine.py` |
| Steam auto-pass (≥2pts) | Done | `engine/prediction_engine.py` |
| LineFlip cap | Done | `engine/prediction_engine.py` |
| WPI tier gating | Done | `engine/confidence.py` |
| SP gate | Done | `engine/confidence.py` |
| Both-side EV/Prob columns | Done | `models/prediction.py`, `model.js` |
| Bullpen depth scoring (±4pp) | Done | `engine/bullpen_impact.py` |
| Park factor + O/U adjustment | Done | `mlb/ballpark_factors.py` |
| Park pitcher scaling | Done | `mlb/ballpark_factors.py` |

---

## 13. Future Enhancements (see CLAUDE_NOTES.md for full detail)

1. **Line shopping** — check FanDuel/BetMGM/Caesars for best price per pick
2. **CLV closing line tracking** — fetch odds 5min before game time for true CLV
3. **Team offensive stats** — wRC+, OPS from MLB Stats API for independent probability model
4. **Bullpen availability** — recent pitcher usage (last 3 days) layered on top of depth score
5. **Situational patterns** — road underdogs after blowout, short rest, etc.
6. **Platoon splits** — pitcher handedness vs lineup composition
