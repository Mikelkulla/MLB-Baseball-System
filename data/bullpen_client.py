"""
BullpenClient — fetches team aggregate pitching stats from MLB Stats API.

Used to score overall pitching depth / bullpen quality per team.
Data source: MLB Stats API (free, official) — no API key required.

Strategy:
  1. Fetch today's schedule to identify which teams are playing + their MLB team IDs.
  2. For each team, call /api/v1/teams/{teamId}/stats?stats=season&group=pitching
     to get the team's full-season aggregate pitching stats.
  3. Return {team_key: BullpenStats} for use by BullpenImpactEngine.

Note: These are whole-staff aggregate stats (starters + relievers combined).
The probable starter is scored separately via PitcherClient — together they
give a fuller picture of pitching quality for both sides of each game.

MLB Stats API endpoints used:
  Schedule (team IDs): /api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=team
  Team stats:          /api/v1/teams/{teamId}/stats?stats=season&group=pitching&season=YYYY
"""

from __future__ import annotations
import logging
from datetime import date
from typing import Optional
import requests

from models.bullpen import BullpenStats
from mlb.teams import normalize_team_name

logger = logging.getLogger(__name__)

MLB_API_BASE = "https://statsapi.mlb.com"
FIP_CONSTANT = 3.17      # FanGraphs GUTS table 2020-2024 average
MIN_IP_FOR_FIP = 30.0    # minimum innings pitched before FIP is meaningful at team level
MIN_GAMES = 10           # gate: ignore teams with fewer games (pre-season noise)


class BullpenClient:
    """
    Fetches and parses team aggregate pitching stats from the official MLB Stats API.
    Returns BullpenStats objects ready for BullpenImpactEngine scoring.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MLB-Betting-System/1.0"})

    def fetch_team_pitching(self, game_date: Optional[date] = None) -> dict[str, BullpenStats]:
        """
        Fetch aggregate pitching stats for all teams playing on game_date.

        Returns:
            {team_key: BullpenStats}  — one entry per team in today's schedule.
            Teams with no usable data return BullpenStats with impact_score=50.0 (neutral).
        """
        target = game_date or date.today()

        # Step 1: discover which teams are playing today and their MLB team IDs
        team_ids = self._get_team_ids(target)
        if not team_ids:
            logger.warning("BullpenClient: no teams found for %s", target)
            return {}

        logger.debug(
            "BullpenClient: found %d teams for %s: %s",
            len(team_ids), target, list(team_ids.keys()),
        )

        # Step 2: fetch pitching stats per team (one API call each)
        result: dict[str, BullpenStats] = {}
        for team_key, team_id in team_ids.items():
            raw = self._fetch_team_stats(team_id, target.year)
            result[team_key] = BullpenStats(
                team_key=team_key,
                era=raw.get("era"),
                k_per_9=raw.get("k_per_9"),
                bb_per_9=raw.get("bb_per_9"),
                hr_per_9=raw.get("hr_per_9"),
                fip=raw.get("fip"),
                games=raw.get("games", 0),
            )
            logger.debug(
                "BullpenClient [%s]: ERA=%s  FIP=%s  K/9=%s  BB/9=%s  games=%d",
                team_key,
                f"{result[team_key].era:.2f}" if result[team_key].era else "N/A",
                f"{result[team_key].fip:.2f}" if result[team_key].fip else "N/A",
                f"{result[team_key].k_per_9:.1f}" if result[team_key].k_per_9 else "N/A",
                f"{result[team_key].bb_per_9:.1f}" if result[team_key].bb_per_9 else "N/A",
                result[team_key].games,
            )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_team_ids(self, target: date) -> dict[str, int]:
        """
        Parse today's schedule to get {team_key: mlb_team_id} for all teams playing.
        """
        url = f"{MLB_API_BASE}/api/v1/schedule"
        params = {
            "sportId": 1,
            "date": target.strftime("%Y-%m-%d"),
            "hydrate": "team",
        }
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            team_ids: dict[str, int] = {}
            for date_entry in resp.json().get("dates", []):
                for game in date_entry.get("games", []):
                    for side in ("away", "home"):
                        team_data = game.get("teams", {}).get(side, {}).get("team", {})
                        team_name = team_data.get("name", "")
                        team_id = team_data.get("id")
                        if not team_name or not team_id:
                            continue
                        team_key = normalize_team_name(team_name, source="mlb_stats_api")
                        if team_key:
                            team_ids[team_key] = int(team_id)
            return team_ids
        except requests.RequestException as exc:
            logger.error("BullpenClient: schedule fetch failed: %s", exc)
            return {}

    def _fetch_team_stats(self, team_id: int, season: int) -> dict:
        """
        Fetch aggregate pitching stats for one team from:
          /api/v1/teams/{teamId}/stats?stats=season&group=pitching&season=YYYY
        Returns a flat dict of parsed values (era, k_per_9, fip, …).
        Returns {} on any error — caller defaults to neutral 50.
        """
        url = f"{MLB_API_BASE}/api/v1/teams/{team_id}/stats"
        params = {
            "stats": "season",
            "group": "pitching",
            "season": season,
            "sportId": 1,
        }
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return self._parse_team_stats(resp.json())
        except requests.RequestException as exc:
            logger.debug("BullpenClient: team %d stats fetch failed: %s", team_id, exc)
            return {}

    @staticmethod
    def _parse_team_stats(data: dict) -> dict:
        """
        Extract aggregate pitching stats from the /teams/{id}/stats response.

        Expected structure:
          {"stats": [{"group": {"displayName": "pitching"}, "splits": [{"stat": {...}}]}]}

        FIP is re-calculated from raw counts (same formula as pitcher_client.py):
          FIP = ((13×HR) + (3×(BB+HBP)) - (2×K)) / IP + 3.17
        """
        stats_list = data.get("stats") or []

        # Find the pitching group — there may also be fielding or hitting groups
        pitching_group = None
        for s in stats_list:
            group_name = (s.get("group") or {}).get("displayName", "")
            if group_name.lower() == "pitching":
                pitching_group = s
                break

        if not pitching_group:
            # Some endpoints return splits directly without a group wrapper
            # Try the first available stats block
            if stats_list and "splits" in stats_list[0]:
                pitching_group = stats_list[0]
            else:
                return {}

        splits = pitching_group.get("splits", [])
        if not splits:
            return {}

        stat = splits[0].get("stat", {})

        ip = BullpenClient._ip_to_float(stat.get("inningsPitched", "0.0"))
        hr  = int(stat.get("homeRuns", 0) or 0)
        bb  = int(stat.get("baseOnBalls", 0) or 0)
        hbp = int(stat.get("hitBatsmen", 0) or 0)
        k   = int(stat.get("strikeOuts", 0) or 0)

        # FIP — only valid with sufficient innings
        fip = None
        if ip >= MIN_IP_FOR_FIP:
            fip_raw = ((13 * hr) + (3 * (bb + hbp)) - (2 * k)) / ip
            fip = round(fip_raw + FIP_CONSTANT, 2)

        # ERA
        era_raw = stat.get("era")
        era = None
        if era_raw and str(era_raw) not in ("-.--", "0.00", ""):
            try:
                era = float(era_raw)
            except (ValueError, TypeError):
                pass

        # K/9
        k9_raw = stat.get("strikeoutsPer9Inn")
        k9 = float(k9_raw) if k9_raw else None

        # BB/9
        bb9_raw = stat.get("walksPer9Inn")
        bb9 = float(bb9_raw) if bb9_raw else None

        # HR/9
        hr9_raw = stat.get("homeRunsPer9")
        hr9 = float(hr9_raw) if hr9_raw else None

        # Games played — used as sample size gate
        games = int(stat.get("gamesPlayed") or stat.get("wins", 0) or 0)
        # Some responses use gamesTotal or wins+losses as a proxy
        if games == 0:
            wins   = int(stat.get("wins", 0) or 0)
            losses = int(stat.get("losses", 0) or 0)
            games = wins + losses

        return {
            "era":    era,
            "k_per_9": k9,
            "bb_per_9": bb9,
            "hr_per_9": hr9,
            "fip":    fip,
            "games":  games,
        }

    @staticmethod
    def _ip_to_float(ip_str: str) -> float:
        """Convert '162.2' (162 full innings + 2 outs) to 162.667 float."""
        try:
            parts = str(ip_str).split(".")
            full = int(parts[0])
            outs = int(parts[1]) if len(parts) > 1 else 0
            return full + outs / 3
        except (ValueError, IndexError):
            return 0.0
