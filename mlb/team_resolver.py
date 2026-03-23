"""
MLB Team Name Resolver — multi-source, self-learning.

Resolution pipeline (in order):
  1. Exact lookup in the combined alias map  (O(1), case-insensitive)
  2. Nickname-only lookup (last word of input)
  3. Token-scan (any individual word is a unique-enough key)
  4. Fuzzy match via difflib against all canonical strings (threshold 0.82)
  5. On failure: persist to team_aliases DB table for manual review

Alias map sources covered:
  • The Odds API         — full official names  ("New York Yankees")
  • DraftKings Network   — city-abbr + nickname ("NY Yankees", "LA Dodgers")
  • Covers.com           — full / partial names  ("Yankees", "New York")
  • MLB Stats API        — official full names   ("New York Yankees")
  • Common abbreviations — NYY, BOS, LAD, CWS …
  • Legacy / alternate   — "Athletics", "Oakland Athletics" …

Runtime learning:
  At startup the resolver loads user-added aliases from the team_aliases DB
  table (rows with a confirmed resolved_key).  New unknowns are appended to
  that table automatically so an operator can review and confirm them.
"""

from __future__ import annotations

import difflib
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. STATIC ALIAS MAP
#    Maps every known variant (lower-cased, stripped) → canonical team key.
#    Canonical keys match MLBTeam.key in config/mlb_config.py.
# ---------------------------------------------------------------------------

_STATIC: dict[str, str] = {

    # ── Full official names (Odds API / MLB Stats API) ─────────────────────
    "new york yankees":         "new_york_yankees",
    "new york mets":            "new_york_mets",
    "los angeles dodgers":      "los_angeles_dodgers",
    "los angeles angels":       "los_angeles_angels",
    "chicago cubs":             "chicago_cubs",
    "chicago white sox":        "chicago_white_sox",
    "san francisco giants":     "san_francisco_giants",
    "san diego padres":         "san_diego_padres",
    "st. louis cardinals":      "st_louis_cardinals",
    "st louis cardinals":       "st_louis_cardinals",
    "kansas city royals":       "kansas_city_royals",
    "tampa bay rays":           "tampa_bay_rays",
    "cleveland guardians":      "cleveland_guardians",
    "toronto blue jays":        "toronto_blue_jays",
    "pittsburgh pirates":       "pittsburgh_pirates",
    "milwaukee brewers":        "milwaukee_brewers",
    "minnesota twins":          "minnesota_twins",
    "detroit tigers":           "detroit_tigers",
    "cincinnati reds":          "cincinnati_reds",
    "colorado rockies":         "colorado_rockies",
    "arizona diamondbacks":     "arizona_diamondbacks",
    "washington nationals":     "washington_nationals",
    "miami marlins":            "miami_marlins",
    "philadelphia phillies":    "philadelphia_phillies",
    "atlanta braves":           "atlanta_braves",
    "seattle mariners":         "seattle_mariners",
    "houston astros":           "houston_astros",
    "texas rangers":            "texas_rangers",
    "baltimore orioles":        "baltimore_orioles",
    "boston red sox":           "boston_red_sox",
    "athletics":                "athletics",
    "oakland athletics":        "athletics",

    # ── DraftKings Network: "CITY_ABBR Nickname" format ───────────────────
    # (observed directly from DK HTML logs)
    "ny yankees":               "new_york_yankees",
    "ny mets":                  "new_york_mets",
    "la dodgers":               "los_angeles_dodgers",
    "la angels":                "los_angeles_angels",
    "chi cubs":                 "chicago_cubs",
    "chi white sox":            "chicago_white_sox",
    "sf giants":                "san_francisco_giants",
    "sd padres":                "san_diego_padres",
    "stl cardinals":            "st_louis_cardinals",
    "kc royals":                "kansas_city_royals",
    "tb rays":                  "tampa_bay_rays",
    "cle guardians":            "cleveland_guardians",
    "tor blue jays":            "toronto_blue_jays",
    "pit pirates":              "pittsburgh_pirates",
    "mil brewers":              "milwaukee_brewers",
    "min twins":                "minnesota_twins",
    "det tigers":               "detroit_tigers",
    "cin reds":                 "cincinnati_reds",
    "col rockies":              "colorado_rockies",
    "ari diamondbacks":         "arizona_diamondbacks",
    "was nationals":            "washington_nationals",
    "wsh nationals":            "washington_nationals",
    "mia marlins":              "miami_marlins",
    "phi phillies":             "philadelphia_phillies",
    "atl braves":               "atlanta_braves",
    "sea mariners":             "seattle_mariners",
    "hou astros":               "houston_astros",
    "tex rangers":              "texas_rangers",
    "bal orioles":              "baltimore_orioles",
    "bos red sox":              "boston_red_sox",

    # ── DraftKings: alternate city abbrs seen in the wild ──────────────────
    "new york yankees":         "new_york_yankees",   # DK sometimes uses full
    "nyy yankees":              "new_york_yankees",
    "nym mets":                 "new_york_mets",
    "lad dodgers":              "los_angeles_dodgers",
    "laa angels":               "los_angeles_angels",
    "chc cubs":                 "chicago_cubs",
    "cws white sox":            "chicago_white_sox",
    "chw white sox":            "chicago_white_sox",
    "sfg giants":               "san_francisco_giants",
    "sdp padres":               "san_diego_padres",
    "sd padres":                "san_diego_padres",
    "oak athletics":            "athletics",
    "oak a's":                  "athletics",
    "a's":                      "athletics",

    # ── Nickname-only (Covers.com / ESPN short form) ───────────────────────
    "yankees":                  "new_york_yankees",
    "mets":                     "new_york_mets",
    "dodgers":                  "los_angeles_dodgers",
    "angels":                   "los_angeles_angels",
    "cubs":                     "chicago_cubs",
    "white sox":                "chicago_white_sox",
    "giants":                   "san_francisco_giants",
    "padres":                   "san_diego_padres",
    "cardinals":                "st_louis_cardinals",
    "royals":                   "kansas_city_royals",
    "rays":                     "tampa_bay_rays",
    "guardians":                "cleveland_guardians",
    "blue jays":                "toronto_blue_jays",
    "pirates":                  "pittsburgh_pirates",
    "brewers":                  "milwaukee_brewers",
    "twins":                    "minnesota_twins",
    "tigers":                   "detroit_tigers",
    "reds":                     "cincinnati_reds",
    "rockies":                  "colorado_rockies",
    "diamondbacks":             "arizona_diamondbacks",
    "d-backs":                  "arizona_diamondbacks",
    "dbacks":                   "arizona_diamondbacks",
    "nationals":                "washington_nationals",
    "marlins":                  "miami_marlins",
    "phillies":                 "philadelphia_phillies",
    "braves":                   "atlanta_braves",
    "mariners":                 "seattle_mariners",
    "astros":                   "houston_astros",
    "rangers":                  "texas_rangers",
    "orioles":                  "baltimore_orioles",
    "red sox":                  "boston_red_sox",

    # ── Standard 3-letter abbreviations ───────────────────────────────────
    "nyy":  "new_york_yankees",
    "nym":  "new_york_mets",
    "lad":  "los_angeles_dodgers",
    "laa":  "los_angeles_angels",
    "chc":  "chicago_cubs",
    "cws":  "chicago_white_sox",
    "chw":  "chicago_white_sox",
    "sfg":  "san_francisco_giants",
    "sdp":  "san_diego_padres",
    "stl":  "st_louis_cardinals",
    "kcr":  "kansas_city_royals",
    "kc":   "kansas_city_royals",
    "tbr":  "tampa_bay_rays",
    "tb":   "tampa_bay_rays",
    "cle":  "cleveland_guardians",
    "tor":  "toronto_blue_jays",
    "pit":  "pittsburgh_pirates",
    "mil":  "milwaukee_brewers",
    "min":  "minnesota_twins",
    "det":  "detroit_tigers",
    "cin":  "cincinnati_reds",
    "col":  "colorado_rockies",
    "ari":  "arizona_diamondbacks",
    "wsh":  "washington_nationals",
    "was":  "washington_nationals",
    "mia":  "miami_marlins",
    "phi":  "philadelphia_phillies",
    "atl":  "atlanta_braves",
    "sea":  "seattle_mariners",
    "hou":  "houston_astros",
    "tex":  "texas_rangers",
    "bal":  "baltimore_orioles",
    "bos":  "boston_red_sox",
    "oak":  "athletics",
    "ath":  "athletics",
    "sf":   "san_francisco_giants",
    "sd":   "san_diego_padres",
    "la":   None,   # ambiguous — resolved contextually below

    # ── Canonical keys (self-map) ──────────────────────────────────────────
    "new_york_yankees":         "new_york_yankees",
    "new_york_mets":            "new_york_mets",
    "los_angeles_dodgers":      "los_angeles_dodgers",
    "los_angeles_angels":       "los_angeles_angels",
    "chicago_cubs":             "chicago_cubs",
    "chicago_white_sox":        "chicago_white_sox",
    "san_francisco_giants":     "san_francisco_giants",
    "san_diego_padres":         "san_diego_padres",
    "st_louis_cardinals":       "st_louis_cardinals",
    "kansas_city_royals":       "kansas_city_royals",
    "tampa_bay_rays":           "tampa_bay_rays",
    "cleveland_guardians":      "cleveland_guardians",
    "toronto_blue_jays":        "toronto_blue_jays",
    "pittsburgh_pirates":       "pittsburgh_pirates",
    "milwaukee_brewers":        "milwaukee_brewers",
    "minnesota_twins":          "minnesota_twins",
    "detroit_tigers":           "detroit_tigers",
    "cincinnati_reds":          "cincinnati_reds",
    "colorado_rockies":         "colorado_rockies",
    "arizona_diamondbacks":     "arizona_diamondbacks",
    "washington_nationals":     "washington_nationals",
    "miami_marlins":            "miami_marlins",
    "philadelphia_phillies":    "philadelphia_phillies",
    "atlanta_braves":           "atlanta_braves",
    "seattle_mariners":         "seattle_mariners",
    "houston_astros":           "houston_astros",
    "texas_rangers":            "texas_rangers",
    "baltimore_orioles":        "baltimore_orioles",
    "boston_red_sox":           "boston_red_sox",
    "athletics":                "athletics",
}

# Remove the ambiguous "la" key — it would match both Dodgers and Angels
del _STATIC["la"]

# ── All canonical keys (for fuzzy matching candidates) ─────────────────────
_ALL_CANONICAL_KEYS: list[str] = list({v for v in _STATIC.values() if v})

# Build list of (display_string, canonical_key) for fuzzy matching
# Includes all aliases as candidates so fuzzy works on partial inputs too
_FUZZY_CANDIDATES: list[tuple[str, str]] = [
    (k, v) for k, v in _STATIC.items() if v is not None
]

# Runtime map starts as a copy of static — DB overrides are merged at startup
_runtime_map: dict[str, str] = dict(_STATIC)

_FUZZY_THRESHOLD = 0.82   # SequenceMatcher ratio; 0.82 is aggressive but safe for MLB


# ---------------------------------------------------------------------------
# 2. DB integration — load overrides and log unknowns
# ---------------------------------------------------------------------------

def _load_db_aliases() -> None:
    """
    Load confirmed user aliases from the team_aliases DB table into the
    runtime map.  Called once at startup (after init_db).
    """
    try:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT raw_name, resolved_key FROM team_aliases "
                "WHERE resolved_key IS NOT NULL"
            ).fetchall()
        for row in rows:
            key = row["raw_name"].strip().lower()
            _runtime_map[key] = row["resolved_key"]
        if rows:
            logger.debug("TeamResolver: loaded %d DB alias overrides", len(rows))
    except Exception as exc:
        # DB may not be initialised yet (e.g. first import before init_db)
        logger.debug("TeamResolver: could not load DB aliases: %s", exc)


def _log_unknown(raw: str, source: str, fuzzy_key: Optional[str], score: float) -> None:
    """Persist an unresolved (or fuzzy-matched) team name to the DB for review."""
    try:
        from db.database import write_db
        now = datetime.utcnow().isoformat()
        with write_db() as conn:
            conn.execute("""
                INSERT INTO team_aliases
                    (raw_name, source, resolved_key, auto_matched, fuzzy_score, first_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_name) DO UPDATE SET
                    source       = excluded.source,
                    auto_matched = excluded.auto_matched,
                    fuzzy_score  = excluded.fuzzy_score
                WHERE team_aliases.resolved_key IS NULL
            """, (raw, source, fuzzy_key, 1 if fuzzy_key else 0, score, now))
    except Exception as exc:
        logger.debug("TeamResolver: could not log unknown '%s': %s", raw, exc)


# ---------------------------------------------------------------------------
# 3. Core resolution logic
# ---------------------------------------------------------------------------

def resolve(raw: str, source: str = "unknown") -> Optional[str]:
    """
    Resolve any raw team name string to a canonical MLB team key.

    Returns the canonical key (e.g. "new_york_yankees") or None if no
    confident match is found.  Unknowns are logged to the DB.
    On any successful resolution the raw name is recorded in team_registry
    (auto-populates the source column the first time that name is observed).
    """
    if not raw or not raw.strip():
        return None

    normalised = raw.strip().lower()

    # ── Tier 1: Exact match ───────────────────────────────────────────────
    result = _runtime_map.get(normalised)
    if result:
        _record_registry(raw, source, result)
        return result

    # ── Tier 2: Strip common punctuation variants ─────────────────────────
    # e.g. "St. Louis Cardinals" → already covered, but handle "St.Louis Cardinals"
    stripped = normalised.replace(".", "").replace("-", " ").replace("_", " ")
    if stripped != normalised:
        result = _runtime_map.get(stripped)
        if result:
            _record_registry(raw, source, result)
            return result

    # ── Tier 3: Nickname-only lookup (last word) ──────────────────────────
    # Handles "San Francisco Giants" → try "giants"
    # Also handles "ARI Diamondbacks" → try "diamondbacks"
    words = normalised.split()
    if len(words) > 1:
        # Try last word
        result = _runtime_map.get(words[-1])
        if result:
            _record_registry(raw, source, result)
            return result
        # Try last two words (e.g. "red sox", "white sox", "blue jays")
        result = _runtime_map.get(" ".join(words[-2:]))
        if result:
            _record_registry(raw, source, result)
            return result

    # ── Tier 4: Token scan (any word is a unique-enough key) ──────────────
    # Handles "NY Yankees" → words = ["ny", "yankees"]; "yankees" maps directly
    for word in words:
        if len(word) > 3:   # skip short abbreviations — too ambiguous
            result = _runtime_map.get(word)
            if result:
                _record_registry(raw, source, result)
                return result

    # ── Tier 5: Fuzzy match ───────────────────────────────────────────────
    best_key, best_score = _fuzzy_match(normalised)
    if best_key and best_score >= _FUZZY_THRESHOLD:
        logger.info(
            "TeamResolver: fuzzy match '%s' → '%s' (score=%.2f, source=%s)",
            raw, best_key, best_score, source,
        )
        # Cache in runtime map for the rest of this session
        _runtime_map[normalised] = best_key
        _log_unknown(raw, source, best_key, best_score)
        _record_registry(raw, source, best_key)
        return best_key

    # ── Tier 6: Unknown — log and return None ─────────────────────────────
    # mlb_stats_api returns AAA/minor-league team names during spring training
    # for optioned pitchers — this is expected and not an error, use INFO.
    if source == "mlb_stats_api":
        logger.info(
            "TeamResolver: UNRESOLVED '%s' (source=%s) — likely minor-league/spring-training team, skipping",
            raw, source,
        )
    else:
        logger.warning(
            "TeamResolver: UNRESOLVED '%s' (source=%s) — added to team_aliases for review",
            raw, source,
        )
    _log_unknown(raw, source, None, best_score)
    return None


def _record_registry(raw: str, source: str, team_key: str) -> None:
    """
    Write the observed raw name into team_registry for the given source column.
    Wrapped in a try/except so resolver never fails due to registry errors.
    Deferred import avoids circular-import at module load time.
    """
    try:
        from db.team_registry import record_seen_name
        record_seen_name(raw, source, team_key)
    except Exception as exc:
        logger.debug("TeamResolver: registry record failed for '%s': %s", raw, exc)


def _fuzzy_match(normalised: str) -> tuple[Optional[str], float]:
    """
    Find the best fuzzy match for a normalised input string.
    Returns (canonical_key, score) where score is 0.0–1.0.
    """
    best_ratio = 0.0
    best_key: Optional[str] = None

    for alias, key in _FUZZY_CANDIDATES:
        ratio = difflib.SequenceMatcher(None, normalised, alias).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_key = key

    return best_key, best_ratio


# ---------------------------------------------------------------------------
# 4. Admin helpers
# ---------------------------------------------------------------------------

def add_alias(raw: str, canonical_key: str) -> None:
    """
    Manually confirm or add a team name alias.
    Updates the DB and hot-reloads the runtime map immediately.
    """
    from db.database import write_db
    now = datetime.utcnow().isoformat()
    norm = raw.strip().lower()
    with write_db() as conn:
        conn.execute("""
            INSERT INTO team_aliases
                (raw_name, source, resolved_key, auto_matched, fuzzy_score, first_seen)
            VALUES (?, 'manual', ?, 0, 1.0, ?)
            ON CONFLICT(raw_name) DO UPDATE SET
                resolved_key = excluded.resolved_key,
                auto_matched = 0,
                fuzzy_score  = 1.0
        """, (raw.strip(), canonical_key, now))
    _runtime_map[norm] = canonical_key
    logger.info("TeamResolver: alias added '%s' → '%s'", raw, canonical_key)


def get_unresolved(limit: int = 100) -> list[dict]:
    """Return recently logged unknown team names that need manual review."""
    try:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM team_aliases WHERE resolved_key IS NULL "
                "ORDER BY first_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_all_aliases(limit: int = 500) -> list[dict]:
    """Return all DB-stored alias entries (resolved and unresolved)."""
    try:
        from db.database import read_db
        with read_db() as conn:
            rows = conn.execute(
                "SELECT * FROM team_aliases ORDER BY first_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def reload_from_db() -> None:
    """Hot-reload confirmed DB aliases into the runtime map (call after bulk edits)."""
    _load_db_aliases()
