"""
Odds API client for MLB — fetches live moneyline, spread, and total odds.

V8.0 alignment (utils_odds.js v2.0):
  - DraftKings is the PREFERRED bookmaker for all markets (ML, spread, totals).
  - If DraftKings doesn't have a particular market (e.g. run line during spring training),
    fall back to scanning ALL bookmakers to find that market. This keeps the V8.0 spirit
    (DK-primary) while handling MLB's reality that run lines may not exist on DK during
    spring training.
  - Outcomes matched by team name; index fallback ([0]=away, [1]=home) if name not found.
  - Three odds consistency rules (V8.0 Fix #1):
      Rule 1: away_spread + home_spread must sum to ~0  (|sum| < 0.1)
      Rule 2: Favorite (negative spread) must have negative ML (and vice versa)
      Rule 3: Exactly one team must be the favorite (unless pick'em at 0)
    → Games failing any rule are skipped with a warning.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
import requests
from config.settings import ODDS_API_KEY, ODDS_API_BASE_URL, MLB_SPORT_KEY, ODDS_REGIONS, ODDS_MARKETS, ODDS_FORMAT
from models.game import Game, GameOdds, OddsLine
from mlb.teams import normalize_team_name

logger = logging.getLogger(__name__)

PREFERRED_BOOKMAKER = "draftkings"


class OddsClient:
    """Fetches live MLB odds from The Odds API using the V8.0 bookmaker strategy."""

    def __init__(self, api_key: str = ODDS_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MLB-Betting-System/1.0"})

    def fetch_games(self) -> list[Game]:
        """
        Fetch all upcoming MLB games with odds.
        Returns a list of Game objects with odds populated.
        """
        url = f"{ODDS_API_BASE_URL}/sports/{MLB_SPORT_KEY}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": ODDS_REGIONS,
            "markets": ODDS_MARKETS,
            "oddsFormat": ODDS_FORMAT,
        }
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Fetched %d MLB games from Odds API", len(data))
            games = []
            skipped = 0
            for raw in data:
                g = self._parse_game(raw)
                if g is None:
                    skipped += 1
                else:
                    games.append(g)
            if skipped:
                logger.warning(
                    "OddsClient: %d/%d games skipped (odds validation failed)",
                    skipped, len(data),
                )
            return games
        except requests.RequestException as exc:
            logger.error("Odds API request failed: %s", exc)
            return []

    def _parse_game(self, raw: dict) -> Optional[Game]:
        raw_away = raw.get("away_team", "")
        raw_home = raw.get("home_team", "")
        bookmakers = raw.get("bookmakers", [])

        game = Game(
            game_id=raw.get("id", ""),
            away_team=normalize_team_name(raw_away, source="odds_api") or raw_away,
            home_team=normalize_team_name(raw_home, source="odds_api") or raw_home,
            commence_time=self._parse_time(raw.get("commence_time")),
        )

        if not bookmakers:
            logger.debug(
                "[%s vs %s] No bookmakers in response — odds unavailable",
                raw_away, raw_home,
            )
            return game

        # ── V8.0: DraftKings preferred bookmaker ──
        dk_book = next((b for b in bookmakers if b.get("key") == PREFERRED_BOOKMAKER), None)
        primary_book = dk_book or bookmakers[0]   # first bookmaker fallback

        # Build market maps per bookmaker for fast lookup
        def get_markets(book: dict) -> dict:
            return {m["key"]: m for m in book.get("markets", [])}

        primary_markets = get_markets(primary_book)

        # ── ML: always from primary book (DK or first) ──
        h2h_market = primary_markets.get("h2h")
        away_ml: Optional[int] = None
        home_ml: Optional[int] = None
        ml_book_key = primary_book.get("key", "")

        if h2h_market:
            outcomes = h2h_market.get("outcomes", [])
            away_ml_o = next((o for o in outcomes if o.get("name") == raw_away), None) or (outcomes[0] if outcomes else None)
            home_ml_o = next((o for o in outcomes if o.get("name") == raw_home), None) or (outcomes[1] if len(outcomes) > 1 else None)
            if away_ml_o:
                away_ml = int(away_ml_o["price"])
            if home_ml_o:
                home_ml = int(home_ml_o["price"])

        # ── Spreads: DK first; if DK has no run line, scan ALL books ──
        # MLB spring training: DraftKings often does not post run lines for spring training games.
        # Regular season: DK always has spreads (same as V8.0 NFL/NBA). So DK is tried first,
        # but we scan all books as a fallback to maintain data coverage during spring.
        away_spread_point: Optional[float] = None
        away_spread_price: Optional[int] = None
        home_spread_point: Optional[float] = None
        home_spread_price: Optional[int] = None
        spread_book_key = ""

        spread_market_src = primary_markets.get("spreads")
        spread_book_key = primary_book.get("key", "")

        if not spread_market_src:
            # DK / primary book has no run line → scan all books
            for book in bookmakers:
                m = get_markets(book).get("spreads")
                if m:
                    spread_market_src = m
                    spread_book_key = book.get("key", "")
                    logger.debug(
                        "[%s vs %s] Spread fallback — found run line from: %s",
                        raw_away, raw_home, spread_book_key,
                    )
                    break

        if spread_market_src:
            outcomes = spread_market_src.get("outcomes", [])
            away_sp = next((o for o in outcomes if o.get("name") == raw_away), None) or (outcomes[0] if outcomes else None)
            home_sp = next((o for o in outcomes if o.get("name") == raw_home), None) or (outcomes[1] if len(outcomes) > 1 else None)
            if away_sp:
                away_spread_point = float(away_sp.get("point", 0))
                away_spread_price = int(away_sp["price"])
            if home_sp:
                home_spread_point = float(home_sp.get("point", 0))
                home_spread_price = int(home_sp["price"])

        # ── Totals: DK first; scan all books if DK has none ──
        over_price: Optional[int] = None
        under_price: Optional[int] = None
        total_point: Optional[float] = None
        totals_book_key = ""

        totals_market_src = primary_markets.get("totals")
        totals_book_key = primary_book.get("key", "")

        if not totals_market_src:
            for book in bookmakers:
                m = get_markets(book).get("totals")
                if m:
                    totals_market_src = m
                    totals_book_key = book.get("key", "")
                    logger.debug(
                        "[%s vs %s] Totals fallback — found O/U from: %s",
                        raw_away, raw_home, totals_book_key,
                    )
                    break

        if totals_market_src:
            outcomes = totals_market_src.get("outcomes", [])
            over_o  = next((o for o in outcomes if o.get("name") == "Over"),  None)
            under_o = next((o for o in outcomes if o.get("name") == "Under"), None)
            if over_o:
                over_price = int(over_o["price"])
                total_point = float(over_o.get("point", 0))
            if under_o:
                under_price = int(under_o["price"])

        # ── V8.0 Fix #1: Validate odds consistency ──
        validation = self._validate_odds(
            raw_away, raw_home,
            away_spread_point, away_ml,
            home_spread_point, home_ml,
        )
        if not validation["valid"]:
            logger.warning(
                "[%s vs %s] SKIPPING — odds validation failed: %s",
                raw_away, raw_home, validation["reason"],
            )
            return None

        # ── Populate GameOdds ──
        odds = GameOdds()
        odds.book_count = len(bookmakers)
        odds.ml_bookmaker     = ml_book_key
        odds.spread_bookmaker = spread_book_key
        odds.total_bookmaker  = totals_book_key

        if away_ml is not None:
            odds.away_ml = OddsLine(price=away_ml)
            odds.best_away_ml = OddsLine(price=away_ml)
            odds.best_away_book = ml_book_key
        if home_ml is not None:
            odds.home_ml = OddsLine(price=home_ml)
            odds.best_home_ml = OddsLine(price=home_ml)
            odds.best_home_book = ml_book_key

        if away_spread_point is not None and away_spread_price is not None:
            odds.away_spread = OddsLine(price=away_spread_price, point=away_spread_point)
        if home_spread_point is not None and home_spread_price is not None:
            odds.home_spread = OddsLine(price=home_spread_price, point=home_spread_point)

        if over_price is not None and total_point is not None:
            odds.over = OddsLine(price=over_price, point=total_point)
        if under_price is not None and total_point is not None:
            odds.under = OddsLine(price=under_price, point=total_point)

        # ML consensus probability (single-book vig removal — fallback for no-spread path)
        if away_ml is not None and home_ml is not None:
            raw_a = abs(away_ml) / (abs(away_ml) + 100) if away_ml < 0 else 100.0 / (away_ml + 100)
            raw_h = abs(home_ml) / (abs(home_ml) + 100) if home_ml < 0 else 100.0 / (home_ml + 100)
            total = raw_a + raw_h
            odds.consensus_away_prob = round(raw_a / total * 100, 2)
            odds.consensus_home_prob = round(raw_h / total * 100, 2)

        game.odds = odds

        logger.debug(
            "[%s vs %s] Odds parsed — ML book=%s  Spread book=%s  Total book=%s | "
            "ML: away=%s home=%s | Spread: away=%s/%s home=%s/%s | Total: %s | books=%d",
            raw_away, raw_home,
            ml_book_key or "N/A",
            spread_book_key or "N/A",
            totals_book_key or "N/A",
            f"{away_ml:+d}" if away_ml is not None else "N/A",
            f"{home_ml:+d}" if home_ml is not None else "N/A",
            f"{away_spread_point:+.1f}" if away_spread_point is not None else "N/A",
            f"{away_spread_price:+d}" if away_spread_price is not None else "N/A",
            f"{home_spread_point:+.1f}" if home_spread_point is not None else "N/A",
            f"{home_spread_price:+d}" if home_spread_price is not None else "N/A",
            f"{total_point}" if total_point is not None else "N/A",
            len(bookmakers),
        )

        return game

    @staticmethod
    def _validate_odds(
        away_team: str,
        home_team: str,
        away_spread: Optional[float],
        away_ml: Optional[int],
        home_spread: Optional[float],
        home_ml: Optional[int],
    ) -> dict:
        """
        V8.0 Fix #1 adapted for MLB — two data-integrity rules.
        Returns {"valid": bool, "reason": str}.
        Skips validation entirely if any spread value is missing.

        V8.0 originally had three rules, but Rule 2 ("run-line favourite must
        also be the ML favourite") is WRONG for MLB and has been removed:

          MLB run lines are always ±1.5 (fixed).  It is routine for the ML
          favourite to be the run-line UNDERDOG — e.g. NY Yankees -117 ML but
          +1.5 on the run line at +149 because laying 1.5 runs is hard.
          Both teams can carry negative ML prices simultaneously.
          Keeping Rule 2 silently drops a large number of valid MLB games.

        Rules kept:
          Rule 1 — Run-line points must offset to ~0 (data-mapping sanity check).
          Rule 2 — Exactly one team must be the run-line favourite (no duplicates).
        """
        # Skip if spread data is incomplete — ML-only games are fine
        if None in (away_spread, home_spread):
            return {"valid": True, "reason": "No spread data — skipping validation"}

        # Rule 1: Spreads must be exact opposites (sum to ~0)
        spread_sum = abs(away_spread + home_spread)
        if spread_sum > 0.1:
            return {
                "valid": False,
                "reason": (
                    f"Spreads don't offset: away={away_spread:+.1f} home={home_spread:+.1f} "
                    f"(sum={away_spread + home_spread:.2f}) — likely data-mapping error"
                ),
            }

        # Rule 2: Exactly one team must be the run-line favourite (unless pick'em at 0)
        if away_spread != 0 and home_spread != 0:
            away_is_fav = away_spread < 0
            home_is_fav = home_spread < 0
            if away_is_fav == home_is_fav:
                label = "favorites" if away_is_fav else "underdogs"
                return {
                    "valid": False,
                    "reason": f"Both teams are run-line {label}: away={away_spread:+.1f} home={home_spread:+.1f}",
                }

        return {"valid": True, "reason": "All validations passed"}

    @staticmethod
    def _parse_time(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
