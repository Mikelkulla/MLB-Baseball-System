"""
DraftKings Network betting splits scraper for MLB.
Equivalent to V8.0 utils_draftking.js.

URL: https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/
     ?tb_eg=84240&tb_edate=n7days&tb_emt=0

V8.0 HTML STRUCTURE (server-side rendered — no Playwright needed):
  Container:  wrap-for-export"> ... <div class="tb_pagination"
  Games:      split by <div class="tb-se">
  Title:      <div class="tb-se-title..."><h5><a>AWAY @ HOME</a>
  Markets:    split by <div class="tb-se-head">  (Moneyline / Spread / Total)
  Option:     <div class="tb-sodd">
                <div class="tb-slipline">team</div>        ← selection
                <div><a class="tb-odd-s">+245</a></div>    ← odds
                <div>5%<div class="tb-progress">…</div>    ← Handle% (3rd direct child)
                <div>18%<div class="tb-progress">…</div>   ← Bets%   (4th direct child)
              </div>

CRITICAL (from V8.0 comments):
  Percentages appear TWICE — in text AND in CSS width style.
  We extract only the TEXT node directly inside the div (before nested divs).
  BeautifulSoup direct-children iteration handles this correctly.

SSS = max(|Bets% - Handle%|) across spread + total markets (ML excluded per V8.0).
"""

from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup, NavigableString

from mlb.teams import normalize_team_name

logger = logging.getLogger(__name__)

MLB_SPORT_ID   = "84240"
DK_NETWORK_BASE = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/"
MAX_PAGES      = 3
PAGE_DELAY_S   = 2


@dataclass
class SplitEntry:
    game_id_raw: str
    away_team_key: Optional[str]
    home_team_key: Optional[str]
    # Moneyline splits
    away_ml_bets_pct: float = 0.0
    home_ml_bets_pct: float = 0.0
    away_ml_handle_pct: float = 0.0
    home_ml_handle_pct: float = 0.0
    # Spread splits
    away_spread_bets_pct: float = 0.0
    home_spread_bets_pct: float = 0.0
    away_spread_handle_pct: float = 0.0
    home_spread_handle_pct: float = 0.0
    # Total splits
    over_bets_pct: float = 0.0
    under_bets_pct: float = 0.0
    over_handle_pct: float = 0.0
    under_handle_pct: float = 0.0

    @property
    def sharp_split_score(self) -> float:
        """Max gap between Bets% and Handle% across spread + total (ML excluded per V8.0)."""
        gaps = [
            abs(self.away_spread_bets_pct  - self.away_spread_handle_pct),
            abs(self.home_spread_bets_pct  - self.home_spread_handle_pct),
            abs(self.over_bets_pct         - self.over_handle_pct),
            abs(self.under_bets_pct        - self.under_handle_pct),
        ]
        return round(max(gaps), 2)

    @property
    def away_handle_pct(self) -> float:
        return max(self.away_ml_handle_pct, self.away_spread_handle_pct)

    @property
    def home_handle_pct(self) -> float:
        return max(self.home_ml_handle_pct, self.home_spread_handle_pct)


class DraftKingsScraper:
    """
    Scrapes DraftKings Network for MLB betting percentages.
    Plain HTTP only (server-side rendered — no headless browser needed).
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.draftkings.com/",
        "Connection": "keep-alive",
    }

    def __init__(self, sport_id: str = MLB_SPORT_ID, date_filter: str = "n7days"):
        self.sport_id   = sport_id
        self.date_filter = date_filter
        self.session    = requests.Session()
        self.session.headers.update(self.HEADERS)

    # ── Public ────────────────────────────────────────────────────────────────

    def fetch(self) -> list[SplitEntry]:
        """Fetch MLB splits across up to MAX_PAGES. Returns [] on failure."""
        all_entries: list[SplitEntry] = []
        seen: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            url = (
                f"{DK_NETWORK_BASE}"
                f"?tb_eg={self.sport_id}"
                f"&tb_edate={self.date_filter}"
                f"&tb_emt=0"
            )
            if page > 1:
                url += f"&tb_page={page}"

            logger.debug("DK splits fetch page %d: %s", page, url)

            try:
                resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
                html = resp.text

                if len(html) < 1000:
                    logger.warning("DK page %d response too short (%d chars)", page, len(html))
                    break

                if "No events match your current selections" in html:
                    logger.debug("DK: no events on page %d", page)
                    break

                games = self._parse_all_games(html)
                added = 0
                for entry in games:
                    if entry.game_id_raw not in seen:
                        seen.add(entry.game_id_raw)
                        all_entries.append(entry)
                        added += 1

                logger.info("DK page %d: %d games (%d new)", page, len(games), added)

                if added == 0 and games:
                    break   # duplicate page — stop early

                if page < MAX_PAGES:
                    time.sleep(PAGE_DELAY_S)

            except requests.RequestException as exc:
                logger.warning("DraftKings scrape failed on page %d: %s", page, exc)
                break

        if not all_entries:
            logger.warning("DK: no splits found — all games will use default SSS=50")

        return all_entries

    # ── Container + game splitting (mirrors V8.0 parseAllGames) ───────────────

    def _parse_all_games(self, html: str) -> list[SplitEntry]:
        """Extract data container and split into per-game blocks."""
        container = ""

        # Same 4 patterns as V8.0 parseAllGames
        for pattern in [
            r'wrap-for-export">([\s\S]*?)<div class="tb_pagination"',
            r'wrap-for-export">([\s\S]*?)<!-- </div> -->',
            r'<div class="tbtw" id="tbsedid">([\s\S]*?)<div class="tb_pagination"',
            r'<div class="tbtw" id="tbsedid">([\s\S]*?)<!-- </div> -->',
        ]:
            m = re.search(pattern, html)
            if m:
                container = m.group(1)
                break

        if not container:
            logger.warning("DK: could not find main data container in HTML (%d chars)", len(html))
            return []

        entries: list[SplitEntry] = []
        blocks = container.split('<div class="tb-se">')

        for block in blocks[1:]:   # first element is before the first game
            try:
                entry = self._parse_game(block)
                if entry:
                    entries.append(entry)
            except Exception as exc:
                logger.debug("DK: error parsing game block: %s", exc)

        logger.debug("DK: parsed %d game entries from container", len(entries))
        return entries

    # ── Game parsing (mirrors V8.0 parseGame) ─────────────────────────────────

    def _parse_game(self, game_html: str) -> Optional[SplitEntry]:
        """Parse one <div class="tb-se"> block into a SplitEntry."""
        # Title: same regex as V8.0
        title_m = re.search(
            r'<div class="tb-se-title(?:-new)?"[\s\S]*?<h5[\s\S]*?<a[^>]*>([\s\S]*?)</a>',
            game_html,
        )
        if not title_m:
            return None

        # Clean title (remove img tags + collapse whitespace) — same as V8.0
        title_text = re.sub(r"<img[^>]*>", "", title_m.group(1))
        title_text = re.sub(r"\s+", " ", title_text).strip()

        at_idx = title_text.find(" @ ")
        if at_idx == -1:
            return None

        away_raw = title_text[:at_idx].strip()
        home_raw = title_text[at_idx + 3:].strip()

        if not away_raw or not home_raw:
            return None

        entry = SplitEntry(
            game_id_raw=f"{away_raw}@{home_raw}",
            away_team_key=normalize_team_name(away_raw, source="draftkings"),
            home_team_key=normalize_team_name(home_raw, source="draftkings"),
        )

        # Extract markets and populate entry
        markets = self._extract_markets(game_html)
        for market in markets:
            self._apply_market(entry, market, away_raw, home_raw)

        logger.debug(
            "DK parsed: %s | ML(A/H)=%.0f%%/%.0f%% | SSS=%.1f",
            entry.game_id_raw,
            entry.away_ml_bets_pct, entry.home_ml_bets_pct,
            entry.sharp_split_score,
        )
        return entry

    def _apply_market(
        self, entry: SplitEntry, market: dict, away_raw: str, home_raw: str
    ) -> None:
        """Populate SplitEntry fields from a parsed market dict."""
        mtype   = market["type"].lower()
        options = market["options"]
        away_lo = away_raw.lower()
        home_lo = home_raw.lower()

        if mtype == "moneyline":
            for opt in options:
                sel = opt["selection"].lower()
                if self._matches_team(sel, away_lo):
                    entry.away_ml_bets_pct   = opt["bets_pct"]
                    entry.away_ml_handle_pct = opt["handle_pct"]
                elif self._matches_team(sel, home_lo):
                    entry.home_ml_bets_pct   = opt["bets_pct"]
                    entry.home_ml_handle_pct = opt["handle_pct"]

        elif mtype in ("spread", "run line"):
            # V8.0 uses "Spread" (NFL/NBA); MLB DraftKings labels this market "Run Line"
            for opt in options:
                sel = opt["selection"].lower()
                if self._matches_team(sel, away_lo):
                    entry.away_spread_bets_pct   = opt["bets_pct"]
                    entry.away_spread_handle_pct = opt["handle_pct"]
                elif self._matches_team(sel, home_lo):
                    entry.home_spread_bets_pct   = opt["bets_pct"]
                    entry.home_spread_handle_pct = opt["handle_pct"]

        elif mtype == "total":
            for opt in options:
                sel = opt["selection"].lower()
                if "over" in sel:
                    entry.over_bets_pct   = opt["bets_pct"]
                    entry.over_handle_pct = opt["handle_pct"]
                elif "under" in sel:
                    entry.under_bets_pct   = opt["bets_pct"]
                    entry.under_handle_pct = opt["handle_pct"]

    @staticmethod
    def _matches_team(selection: str, team_lower: str) -> bool:
        """
        Check if a scraped selection string belongs to a team.
        Mirrors V8.0: match by first word in either direction.
        """
        team_first = team_lower.split()[0] if team_lower else ""
        sel_first  = selection.split()[0]  if selection  else ""
        return (
            bool(team_first) and (
                team_first in selection or
                sel_first in team_lower
            )
        )

    # ── Market extraction (mirrors V8.0 extractMarkets) ──────────────────────

    def _extract_markets(self, game_html: str) -> list[dict]:
        """
        Find <div class="tb-market-wrap"> and split by <div class="tb-se-head">.
        Identical split strategy to V8.0.
        """
        markets: list[dict] = []

        wrap_m = re.search(r'<div class="tb-market-wrap">([\s\S]*?)$', game_html)
        if not wrap_m:
            return markets

        wrap_html = wrap_m.group(1)
        blocks    = wrap_html.split('<div class="tb-se-head">')

        for block in blocks[1:]:
            try:
                market = self._parse_market(block)
                if market and market["options"]:
                    markets.append(market)
            except Exception as exc:
                logger.debug("DK: error parsing market: %s", exc)

        return markets

    def _parse_market(self, market_html: str) -> Optional[dict]:
        """
        Parse one market block.
        Type: first plain <div>text</div> (same as V8.0).
        Options: parsed with BeautifulSoup to avoid fragile nested-div regex.
        """
        # Market type from first bare <div>text</div> — V8.0 identical
        type_m = re.search(r"<div>([^<]+)</div>", market_html)
        market_type = type_m.group(1).strip() if type_m else "Unknown"

        # Use BeautifulSoup to find all tb-sodd divs reliably
        # (avoids fragile [\s\S]*? stopping inside nested tb-progress divs)
        soup = BeautifulSoup(market_html, "html.parser")
        options: list[dict] = []

        for sodd in soup.find_all("div", class_="tb-sodd"):
            opt = self._parse_option(sodd)
            if opt:
                options.append(opt)

        return {"type": market_type, "options": options}

    @staticmethod
    def _parse_option(sodd_tag) -> Optional[dict]:
        """
        Parse one <div class="tb-sodd"> BeautifulSoup tag.

        HTML layout (V8.0 spec):
          Direct child 0 (div.tb-slipline): team name (selection)
          Direct child 1 (bare div + <a>):  odds
          Direct child 2 (bare div):        HANDLE% text node + tb-progress nested div
          Direct child 3 (bare div):        BETS%   text node + tb-progress nested div

        We read the raw NavigableString inside children 2 and 3 to avoid
        picking up the CSS 'width:X%' value inside the nested tb-progress div.
        """
        # Selection
        slipline = sodd_tag.find("div", class_="tb-slipline")
        selection = slipline.get_text(strip=True) if slipline else ""

        # Direct div children only
        direct_divs = [c for c in sodd_tag.children if getattr(c, "name", None) == "div"]

        def _text_pct(div_tag) -> float:
            """Extract the % number from the raw text nodes (ignores CSS inside nested divs)."""
            if div_tag is None:
                return 0.0
            # Iterate direct children — NavigableString = text node, Tag = nested div
            for child in div_tag.children:
                if isinstance(child, NavigableString):
                    m = re.search(r"(\d+)%", str(child))
                    if m:
                        return float(m.group(1))
            return 0.0

        handle_pct = _text_pct(direct_divs[2]) if len(direct_divs) > 2 else 0.0
        bets_pct   = _text_pct(direct_divs[3]) if len(direct_divs) > 3 else 0.0

        if not selection:
            return None

        return {
            "selection": selection,
            "handle_pct": handle_pct,
            "bets_pct":   bets_pct,
        }
