"""
MLB injury scraper — Covers.com MLB injuries page.
Equivalent to V8.0 utils_injury.js adapted for the baseball URL.
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Optional
import requests
from bs4 import BeautifulSoup
from config.settings import COVERS_MLB_URL
from mlb.teams import normalize_team_name

logger = logging.getLogger(__name__)

# Known MLB position abbreviation patterns from Covers.com
_POSITION_PATTERN = re.compile(
    r"\b(SP|RP|CP|MR|C|1B|2B|3B|SS|LF|CF|RF|DH)\b", re.IGNORECASE
)


@dataclass
class RawInjury:
    team_raw: str
    team_key: Optional[str]
    player_name: str
    position: str
    status: str           # "Out", "Questionable", etc.
    description: str = ""


class InjuryScraper:
    """Scrapes MLB injury data from Covers.com."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    def __init__(self, url: str = COVERS_MLB_URL):
        self.url = url

    def fetch(self) -> list[RawInjury]:
        """Scrape and parse the Covers MLB injury page."""
        try:
            resp = requests.get(self.url, headers=self.HEADERS, timeout=20)
            resp.raise_for_status()
            return self._parse(resp.text)
        except requests.RequestException as exc:
            logger.error("Injury scrape failed: %s", exc)
            return []

    def _parse(self, html: str) -> list[RawInjury]:
        soup = BeautifulSoup(html, "html.parser")
        injuries: list[RawInjury] = []

        # Covers.com structure: table rows grouped by team
        # Each row typically: Player | Position | Status | Description
        # Team header rows appear above player rows
        current_team_raw = ""
        current_team_key: Optional[str] = None

        for row in soup.select("tr"):
            # Team header row
            team_header = row.select_one("td.covers-team-name, th.team-name, .team-header")
            if team_header:
                current_team_raw = team_header.get_text(strip=True)
                current_team_key = normalize_team_name(current_team_raw, source="covers_injuries")
                continue

            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            player_name = cells[0].get_text(strip=True)
            position_raw = cells[1].get_text(strip=True).upper()
            status_raw = cells[2].get_text(strip=True)
            desc = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            # Normalise position: keep only known MLB positions
            pos_match = _POSITION_PATTERN.search(position_raw)
            position = pos_match.group(0).upper() if pos_match else position_raw[:3]

            # Normalise status to lower-case canonical form
            status = self._normalise_status(status_raw)

            if player_name and position:
                injuries.append(RawInjury(
                    team_raw=current_team_raw,
                    team_key=current_team_key,
                    player_name=player_name,
                    position=position,
                    status=status,
                    description=desc,
                ))

        logger.info("Scraped %d injury records", len(injuries))
        return injuries

    @staticmethod
    def _normalise_status(raw: str) -> str:
        lower = raw.lower()
        if "out" in lower and "season" in lower:
            return "out for season"
        if "out" in lower:
            return "out"
        if "doubtful" in lower:
            return "doubtful"
        if "questionable" in lower:
            return "questionable"
        if "day-to-day" in lower or "dtd" in lower:
            return "day-to-day"
        if "probable" in lower:
            return "probable"
        return lower
