"""
Database schema — CREATE TABLE statements for every persistent entity.
Call init_db() exactly once at application startup (safe to call repeatedly;
all statements use IF NOT EXISTS).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from db.database import DB_PATH

# ---------------------------------------------------------------------------
# DDL — one executescript call, which SQLite processes atomically
# ---------------------------------------------------------------------------
_DDL = """
-- ── Predictions ────────────────────────────────────────────────────────────
-- One row per game_id; UPSERTed on every pipeline refresh.
-- game_date is the game commence time (ISO 8601 text).
CREATE TABLE IF NOT EXISTS predictions (
    game_id             TEXT    NOT NULL PRIMARY KEY,
    sport               TEXT    NOT NULL DEFAULT 'baseball_mlb',
    game_date           TEXT,
    matchup             TEXT    NOT NULL DEFAULT '',
    picked_team         TEXT    NOT NULL DEFAULT '',
    picked_team_name    TEXT    NOT NULL DEFAULT '',
    bet_type            TEXT    NOT NULL DEFAULT 'MONEYLINE',
    -- Raw odds (both sides for Model page)
    away_ml             INTEGER,
    home_ml             INTEGER,
    away_spread         REAL,
    home_spread         REAL,
    total_line          REAL,
    open_spread         REAL,
    current_spread      REAL,
    bet_price           INTEGER,
    best_book           TEXT    NOT NULL DEFAULT '',
    book_count          INTEGER NOT NULL DEFAULT 0,
    -- Both-side metrics
    away_prob_pct       REAL    NOT NULL DEFAULT 0.0,
    home_prob_pct       REAL    NOT NULL DEFAULT 0.0,
    away_ev_pct         REAL,
    home_ev_pct         REAL,
    -- Picked-side metrics
    prob_pct            REAL    NOT NULL DEFAULT 0.0,
    ev_pct              REAL    NOT NULL DEFAULT 0.0,
    confidence_pct      REAL    NOT NULL DEFAULT 0.0,
    units               REAL    NOT NULL DEFAULT 0.0,
    status              TEXT    NOT NULL DEFAULT 'PASS',
    safe_units          REAL    NOT NULL DEFAULT 0.0,
    clv_delta           REAL    NOT NULL DEFAULT 0.0,
    sharp_split_score   REAL    NOT NULL DEFAULT 0.0,
    -- Pitchers
    away_pitcher_name   TEXT    NOT NULL DEFAULT 'TBD',
    away_pitcher_score  REAL    NOT NULL DEFAULT 50.0,
    home_pitcher_name   TEXT    NOT NULL DEFAULT 'TBD',
    home_pitcher_score  REAL    NOT NULL DEFAULT 50.0,
    -- Impact scores
    away_injury_impact  REAL    NOT NULL DEFAULT 0.0,
    home_injury_impact  REAL    NOT NULL DEFAULT 0.0,
    weather_over_adj    REAL    NOT NULL DEFAULT 0.0,
    weather_under_adj   REAL    NOT NULL DEFAULT 0.0,
    -- Gate flags (stored as 0/1)
    sp_gate_blocked     INTEGER NOT NULL DEFAULT 0,
    prediction_text     TEXT    NOT NULL DEFAULT '',
    generated_at        TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_predictions_game_date
    ON predictions (game_date);
CREATE INDEX IF NOT EXISTS idx_predictions_generated_at
    ON predictions (generated_at);
CREATE INDEX IF NOT EXISTS idx_predictions_status
    ON predictions (status);

-- ── Bets ───────────────────────────────────────────────────────────────────
-- One row per logged bet; settled in-place via UPDATE.
CREATE TABLE IF NOT EXISTS bets (
    bet_id              TEXT    NOT NULL PRIMARY KEY,
    sport               TEXT    NOT NULL DEFAULT 'baseball_mlb',
    game_date           TEXT,
    matchup             TEXT    NOT NULL DEFAULT '',
    picked_team         TEXT    NOT NULL DEFAULT '',
    picked_team_name    TEXT    NOT NULL DEFAULT '',
    bet_type            TEXT    NOT NULL DEFAULT 'MONEYLINE',
    units               REAL    NOT NULL DEFAULT 0.0,
    prediction_text     TEXT    NOT NULL DEFAULT '',
    status_tier         TEXT    NOT NULL DEFAULT 'GOLD',
    ev_pct              REAL    NOT NULL DEFAULT 0.0,
    confidence_pct      REAL    NOT NULL DEFAULT 0.0,
    prob_pct            REAL    NOT NULL DEFAULT 0.0,
    open_spread         REAL,
    open_price          INTEGER,
    bet_spread          REAL,
    bet_price           INTEGER,
    current_price       INTEGER,
    clv_pct             REAL    NOT NULL DEFAULT 0.0,
    adj_units           REAL    NOT NULL DEFAULT 0.0,
    clv_band            TEXT    NOT NULL DEFAULT 'GOOD',
    key_number_crossed  INTEGER NOT NULL DEFAULT 0,
    placed_at           TEXT    NOT NULL DEFAULT '',
    result              TEXT    NOT NULL DEFAULT 'ACTIVE',
    pnl                 REAL    NOT NULL DEFAULT 0.0,
    notes               TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_bets_result
    ON bets (result);
CREATE INDEX IF NOT EXISTS idx_bets_game_date
    ON bets (game_date);

-- ── CLV History ────────────────────────────────────────────────────────────
-- One row per game_id; updated in-place as lines move.
CREATE TABLE IF NOT EXISTS clv_history (
    game_id             TEXT    NOT NULL PRIMARY KEY,
    matchup             TEXT    NOT NULL DEFAULT '',
    sport               TEXT    NOT NULL DEFAULT 'baseball_mlb',
    away_spread_open    REAL,
    away_spread_current REAL,
    away_spread_delta   REAL,
    home_spread_open    REAL,
    home_spread_current REAL,
    home_spread_delta   REAL,
    away_ml_open        INTEGER,
    away_ml_current     INTEGER,
    home_ml_open        INTEGER,
    home_ml_current     INTEGER,
    recorded_at         TEXT    NOT NULL DEFAULT '',
    closed_at           TEXT    NOT NULL DEFAULT '',
    is_closed           INTEGER NOT NULL DEFAULT 0
);

-- ── Feed Health ────────────────────────────────────────────────────────────
-- One row per named feed; UPSERTed on every refresh phase.
CREATE TABLE IF NOT EXISTS feed_health (
    feed            TEXT    NOT NULL PRIMARY KEY,
    status          TEXT    NOT NULL DEFAULT 'UNKNOWN',
    detail          TEXT    NOT NULL DEFAULT '',
    record_count    INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT    NOT NULL DEFAULT ''
);

-- ── Schedule Log ───────────────────────────────────────────────────────────
-- Append-only execution history; trimmed to 500 rows automatically.
CREATE TABLE IF NOT EXISTS schedule_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task        TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT '',
    detail      TEXT    NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    timestamp   TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_schedule_log_timestamp
    ON schedule_log (timestamp);

-- ── Config ─────────────────────────────────────────────────────────────────
-- Single row keyed "main"; value is JSON-serialised config dict.
CREATE TABLE IF NOT EXISTS config (
    key     TEXT NOT NULL PRIMARY KEY,
    value   TEXT NOT NULL DEFAULT '{}'
);

-- ── Team Aliases ────────────────────────────────────────────────────────────
-- Learning table for team name normalisation.
-- auto_matched=1 means the resolver used fuzzy matching.
-- resolved_key=NULL means the name is still unresolved and needs manual review.
-- Once an operator sets resolved_key, it is loaded into the runtime alias map.
CREATE TABLE IF NOT EXISTS team_aliases (
    raw_name        TEXT    NOT NULL PRIMARY KEY,
    source          TEXT    NOT NULL DEFAULT 'unknown',
    resolved_key    TEXT,               -- NULL = unresolved
    auto_matched    INTEGER NOT NULL DEFAULT 0,
    fuzzy_score     REAL    NOT NULL DEFAULT 0.0,
    first_seen      TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_team_aliases_resolved
    ON team_aliases (resolved_key);

-- ══════════════════════════════════════════════════════════════════════════════
-- RAW DATA TABLES
-- One row per record per refresh_id.  refresh_id = UTC ISO timestamp of the
-- pipeline run that produced the data.  All rows are append-only — nothing
-- is ever updated or deleted here — so every refresh is fully auditable.
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Team Registry ───────────────────────────────────────────────────────────
-- One row per canonical MLB team (30 rows total).
-- Stores the exact name string that each data source uses for this team.
-- Used by the UI to show and manually correct all source→team mappings.
--
-- locked = 1  → programmatic updates (team_resolver auto-learn) cannot change
--              source name columns.  Only the UI can write to a locked row.
--              Flipped to 1 automatically whenever the UI saves a change.
-- locked = 0  → team_resolver will write the first observed name for each
--              source column (auto-population on first fetch).
CREATE TABLE IF NOT EXISTS team_registry (
    team_key        TEXT NOT NULL PRIMARY KEY,  -- e.g. "new_york_yankees"
    display_city    TEXT NOT NULL DEFAULT '',   -- e.g. "New York"
    display_name    TEXT NOT NULL DEFAULT '',   -- e.g. "Yankees"
    abbreviation    TEXT NOT NULL DEFAULT '',   -- e.g. "NYY"
    division        TEXT NOT NULL DEFAULT '',   -- e.g. "AL East"
    -- Exact name string observed from each data source
    -- Empty string = never seen from that source yet
    odds_api_name   TEXT NOT NULL DEFAULT '',   -- e.g. "New York Yankees"
    dk_name         TEXT NOT NULL DEFAULT '',   -- e.g. "NY Yankees"
    mlb_stats_name  TEXT NOT NULL DEFAULT '',   -- e.g. "New York Yankees"
    covers_name     TEXT NOT NULL DEFAULT '',   -- e.g. "Yankees"
    -- Lock control
    locked          INTEGER NOT NULL DEFAULT 0,  -- 1 = UI-only, no programmatic writes
    locked_at       TEXT    NOT NULL DEFAULT '',
    -- Free-text notes from the operator
    notes           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT '',
    updated_at      TEXT    NOT NULL DEFAULT ''
);

-- ── Raw Odds ─────────────────────────────────────────────────────────────────
-- One row per game per odds refresh.
-- Stores exactly what was returned by The Odds API for each game,
-- including which bookmaker was used per market.
CREATE TABLE IF NOT EXISTS raw_odds (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_id       TEXT    NOT NULL,      -- UTC ISO timestamp of the refresh run
    game_id          TEXT    NOT NULL,      -- Odds API game ID
    commence_time    TEXT,                  -- game start time (ISO 8601)
    away_team_raw    TEXT    NOT NULL DEFAULT '',   -- exact API team string
    home_team_raw    TEXT    NOT NULL DEFAULT '',
    away_team_key    TEXT    NOT NULL DEFAULT '',   -- normalized key
    home_team_key    TEXT    NOT NULL DEFAULT '',
    ml_bookmaker     TEXT    NOT NULL DEFAULT '',   -- book used for moneyline
    spread_bookmaker TEXT    NOT NULL DEFAULT '',   -- book used for spread (may differ from ML)
    total_bookmaker  TEXT    NOT NULL DEFAULT '',   -- book used for totals
    books_available  INTEGER NOT NULL DEFAULT 0,   -- total bookmakers in API response
    away_ml          INTEGER,
    home_ml          INTEGER,
    away_spread_pt   REAL,                  -- spread point  e.g. +1.5
    away_spread_px   INTEGER,              -- spread price  e.g. -115
    home_spread_pt   REAL,
    home_spread_px   INTEGER,
    total_point      REAL,                  -- O/U line      e.g. 8.5
    over_price       INTEGER,
    under_price      INTEGER,
    validation_ok    INTEGER NOT NULL DEFAULT 1,   -- 0 = failed V8.0 consistency rules
    recorded_at      TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_raw_odds_refresh
    ON raw_odds (refresh_id);
CREATE INDEX IF NOT EXISTS idx_raw_odds_game
    ON raw_odds (game_id);

-- ── Raw DraftKings Splits ────────────────────────────────────────────────────
-- One row per game per DK splits refresh.
-- Stores every bets% and handle% scraped from DK Network for debugging
-- and tracing which numbers went into SSS / WPI / SharpSplit.
CREATE TABLE IF NOT EXISTS raw_dk_splits (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_id              TEXT    NOT NULL,
    game_id_raw             TEXT    NOT NULL DEFAULT '',   -- e.g. "Yankees @ Red Sox"
    away_team_key           TEXT    NOT NULL DEFAULT '',
    home_team_key           TEXT    NOT NULL DEFAULT '',
    -- Moneyline splits
    away_ml_bets_pct        REAL    NOT NULL DEFAULT 0.0,
    home_ml_bets_pct        REAL    NOT NULL DEFAULT 0.0,
    away_ml_handle_pct      REAL    NOT NULL DEFAULT 0.0,
    home_ml_handle_pct      REAL    NOT NULL DEFAULT 0.0,
    -- Spread splits
    away_spread_bets_pct    REAL    NOT NULL DEFAULT 0.0,
    home_spread_bets_pct    REAL    NOT NULL DEFAULT 0.0,
    away_spread_handle_pct  REAL    NOT NULL DEFAULT 0.0,
    home_spread_handle_pct  REAL    NOT NULL DEFAULT 0.0,
    -- Total splits
    over_bets_pct           REAL    NOT NULL DEFAULT 0.0,
    under_bets_pct          REAL    NOT NULL DEFAULT 0.0,
    over_handle_pct         REAL    NOT NULL DEFAULT 0.0,
    under_handle_pct        REAL    NOT NULL DEFAULT 0.0,
    -- Computed
    sharp_split_score       REAL    NOT NULL DEFAULT 0.0,
    recorded_at             TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_raw_dk_splits_refresh
    ON raw_dk_splits (refresh_id);

-- ── Raw Injuries ─────────────────────────────────────────────────────────────
-- One row per injured player per injury refresh.
-- Stores the full Covers.com scrape so you can check exactly which players
-- were reported as Out/Doubtful and whether the SP gate was triggered correctly.
CREATE TABLE IF NOT EXISTS raw_injuries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_id      TEXT    NOT NULL,
    player_name     TEXT    NOT NULL DEFAULT '',
    team_raw        TEXT    NOT NULL DEFAULT '',   -- exact scraped team string
    team_key        TEXT    NOT NULL DEFAULT '',   -- normalized key ('' if unresolved)
    position        TEXT    NOT NULL DEFAULT '',   -- SP, RP, C, 1B, etc.
    status          TEXT    NOT NULL DEFAULT '',   -- Out, Doubtful, Questionable, D2D
    description     TEXT    NOT NULL DEFAULT '',   -- injury description from Covers
    recorded_at     TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_raw_injuries_refresh
    ON raw_injuries (refresh_id);
CREATE INDEX IF NOT EXISTS idx_raw_injuries_team
    ON raw_injuries (team_key);

-- ── Raw Weather ──────────────────────────────────────────────────────────────
-- One row per stadium per weather refresh.
-- Stores the raw WeatherAPI.com response fields plus the computed
-- over/under adjustments so you can audit why a game got a weather impact.
CREATE TABLE IF NOT EXISTS raw_weather (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_id       TEXT    NOT NULL,
    team_key         TEXT    NOT NULL DEFAULT '',   -- home team
    stadium_name     TEXT    NOT NULL DEFAULT '',
    city             TEXT    NOT NULL DEFAULT '',
    temperature_f    REAL,
    wind_speed_mph   REAL,
    wind_direction   TEXT    NOT NULL DEFAULT '',
    condition        TEXT    NOT NULL DEFAULT '',   -- "Sunny", "Rain", etc.
    precipitation_mm REAL,                          -- mm in last hour (raw API value)
    precipitation    TEXT    NOT NULL DEFAULT '',   -- category: none / light / heavy
    humidity_pct     REAL,
    is_dome          INTEGER NOT NULL DEFAULT 0,
    over_adj         REAL    NOT NULL DEFAULT 0.0,  -- computed O/U adjustment (engine output)
    under_adj        REAL    NOT NULL DEFAULT 0.0,
    recorded_at      TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_raw_weather_refresh
    ON raw_weather (refresh_id);

-- ── Raw Pitchers ─────────────────────────────────────────────────────────────
-- One row per team per pitcher refresh.
-- Stores every pitcher stat returned by MLB Stats API plus the computed
-- impact_score so you can trace exactly how probability shifts were computed.
CREATE TABLE IF NOT EXISTS raw_pitchers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_id       TEXT    NOT NULL,
    team_key         TEXT    NOT NULL DEFAULT '',
    pitcher_name     TEXT    NOT NULL DEFAULT 'TBD',
    pitcher_id       INTEGER,                        -- MLB Stats API player ID
    hand             TEXT    NOT NULL DEFAULT '',    -- R or L
    is_tbd           INTEGER NOT NULL DEFAULT 1,     -- 1 = starter not yet announced
    -- Season stats (NULL when is_tbd=1 or no stats yet)
    era              REAL,
    whip             REAL,
    k_per_9          REAL,
    bb_per_9         REAL,
    innings_pitched  REAL,
    wins             INTEGER,
    losses           INTEGER,
    recent_era       REAL,                           -- last 3 starts ERA
    -- Computed
    impact_score     REAL    NOT NULL DEFAULT 50.0,  -- 0-100 (50 = league average)
    recorded_at      TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_raw_pitchers_refresh
    ON raw_pitchers (refresh_id);
CREATE INDEX IF NOT EXISTS idx_raw_pitchers_team
    ON raw_pitchers (team_key);
"""


def init_db() -> None:
    """
    Create all tables and indexes if they do not already exist.
    Safe to call on every startup — IF NOT EXISTS guards every statement.
    Uses a direct sqlite3 connection (bypass the write_db context manager)
    because executescript issues its own implicit transaction.
    """
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(_DDL)
    finally:
        conn.close()
