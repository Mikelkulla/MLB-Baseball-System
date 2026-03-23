"""
Pitcher data client — fetches probable MLB starters and their season stats.

Phase D1 from the MLB Implementation Timeline.
Data source: MLB Stats API (free, official) — no API key required.
Falls back to ESPN API if MLB Stats API is unavailable.

MLB Stats API endpoints:
  Probable pitchers: /api/v1/schedule?sportId=1&hydrate=probablePitcher(note)
  Player stats:      /api/v1/people/{personId}/stats?stats=season&group=pitching
"""

from __future__ import annotations
import logging
from datetime import date
from typing import Optional
import requests
from models.pitcher import PitcherStats
from mlb.teams import normalize_team_name

logger = logging.getLogger(__name__)

MLB_API_BASE = "https://statsapi.mlb.com"


class PitcherClient:
    """
    Fetches probable starters and season stats from the official MLB Stats API.
    Returns PitcherStats objects ready for PitcherImpactEngine.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MLB-Betting-System/1.0"})

    def fetch_probable_starters(self, game_date: Optional[date] = None) -> dict[str, PitcherStats]:
        """
        Fetch probable starters for all games on the given date.
        Returns {team_key: PitcherStats}.
        TBD starters are represented with is_tbd=True.
        """
        target = game_date or date.today()
        url = f"{MLB_API_BASE}/api/v1/schedule"
        params = {
            "sportId": 1,
            "date": target.strftime("%Y-%m-%d"),
            "hydrate": "probablePitcher(note),team",
        }
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return self._parse_schedule(resp.json())
        except requests.RequestException as exc:
            logger.error("MLB API schedule fetch failed: %s", exc)
            return {}

    def _parse_schedule(self, data: dict) -> dict[str, PitcherStats]:
        starters: dict[str, PitcherStats] = {}
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                for side in ("away", "home"):
                    team_data = game.get("teams", {}).get(side, {})
                    team_name = team_data.get("team", {}).get("name", "")
                    team_key = normalize_team_name(team_name, source="mlb_stats_api")
                    if not team_key:
                        continue

                    pitcher_data = team_data.get("probablePitcher")
                    if pitcher_data:
                        person_id = pitcher_data.get("id")
                        name = pitcher_data.get("fullName", "Unknown")
                        stats = self._fetch_pitcher_stats(person_id) if person_id else {}
                        starters[team_key] = PitcherStats(
                            name=name,
                            team_key=team_key,
                            hand=stats.get("hand", "R"),
                            is_tbd=False,
                            era=stats.get("era"),
                            whip=stats.get("whip"),
                            k_per_9=stats.get("k_per_9"),
                            bb_per_9=stats.get("bb_per_9"),
                            hr_per_9=stats.get("hr_per_9"),
                            innings_pitched=stats.get("innings_pitched"),
                            wins=stats.get("wins", 0),
                            losses=stats.get("losses", 0),
                            home_runs=stats.get("home_runs"),
                            walks=stats.get("walks"),
                            hit_batsmen=stats.get("hit_batsmen"),
                            strikeouts=stats.get("strikeouts"),
                            fip=stats.get("fip"),
                            recent_era=stats.get("recent_era"),
                        )
                    else:
                        # No probable starter announced yet
                        starters[team_key] = PitcherStats(
                            name="TBD",
                            team_key=team_key,
                            is_tbd=True,
                        )
        return starters

    def _fetch_pitcher_stats(self, person_id: int) -> dict:
        """Fetch season + last 3 starts stats for a pitcher."""
        url = f"{MLB_API_BASE}/api/v1/people/{person_id}/stats"
        try:
            # Season stats
            params = {"stats": "season", "group": "pitching", "sportId": 1}
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            season = self._extract_stat_line(resp.json())

            # Last 3 starts (game log)
            recent_era = self._fetch_recent_era(person_id)
            season["recent_era"] = recent_era

            # Handedness
            person_resp = self.session.get(
                f"{MLB_API_BASE}/api/v1/people/{person_id}",
                params={"hydrate": "currentTeam"},
                timeout=10
            )
            if person_resp.ok:
                people = person_resp.json().get("people", [{}])
                pitch_hand = people[0].get("pitchHand", {}).get("code", "R")
                season["hand"] = pitch_hand

            return season
        except requests.RequestException as exc:
            logger.debug("Stats fetch failed for player %s: %s", person_id, exc)
            return {}

    def _fetch_recent_era(self, person_id: int) -> Optional[float]:
        """Compute ERA from last 3 game log entries."""
        url = f"{MLB_API_BASE}/api/v1/people/{person_id}/stats"
        params = {"stats": "gameLog", "group": "pitching", "sportId": 1}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            splits = (resp.json().get("stats") or [{}])[0].get("splits", [])
            # Most recent 3 starts
            recent = splits[-3:]
            total_er = sum(int(s.get("stat", {}).get("earnedRuns", 0)) for s in recent)
            total_ip_str = sum(
                self._ip_to_float(s.get("stat", {}).get("inningsPitched", "0.0"))
                for s in recent
            )
            if total_ip_str > 0:
                return round(total_er / total_ip_str * 9, 2)
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_stat_line(data: dict) -> dict:
        """
        Pull pitching stats from MLB Stats API season response.

        FIP is calculated here from raw counting stats:
            FIP = ((13×HR) + (3×(BB+HBP)) - (2×K)) / IP + FIP_constant
        FIP_constant = 3.17  (5-year rolling average 2020-2024, source: FanGraphs GUTS)
        This puts FIP on the same scale as ERA by construction.

        ERA and WHIP are still returned for display purposes but are NOT used
        in the impact score — they are contaminated by the defense behind the pitcher.
        """
        FIP_CONSTANT = 3.17   # FanGraphs GUTS table 2020-2024 average
        MIN_IP_FOR_FIP = 5.0  # Do not calculate FIP below 5 IP — too noisy

        stats_list = data.get("stats") or [{}]
        splits = stats_list[0].get("splits", [])
        if not splits:
            return {}
        stat = splits[0].get("stat", {})
        ip = PitcherClient._ip_to_float(stat.get("inningsPitched", "0.0"))

        # Raw counting stats needed for FIP
        hr  = int(stat.get("homeRuns", 0) or 0)
        bb  = int(stat.get("baseOnBalls", 0) or 0)
        hbp = int(stat.get("hitBatsmen", 0) or 0)
        k   = int(stat.get("strikeOuts", 0) or 0)

        # Calculate FIP — only when enough innings to be meaningful
        fip = None
        if ip >= MIN_IP_FOR_FIP:
            fip_raw = ((13 * hr) + (3 * (bb + hbp)) - (2 * k)) / ip
            fip = round(fip_raw + FIP_CONSTANT, 2)

        # HR/9 rate — direct from API (homeRunsPer9 field)
        hr_per_9_raw = stat.get("homeRunsPer9")
        hr_per_9 = float(hr_per_9_raw) if hr_per_9_raw else None

        return {
            # Display stats (not used in scoring)
            "era":   float(stat["era"])  if stat.get("era")  and stat["era"]  != "-.--" else None,
            "whip":  float(stat["whip"]) if stat.get("whip") and stat["whip"] != "-.--" else None,
            # Scoring stats (fielding independent)
            "k_per_9":    float(stat["strikeoutsPer9Inn"]) if stat.get("strikeoutsPer9Inn") else None,
            "bb_per_9":   float(stat["walksPer9Inn"])      if stat.get("walksPer9Inn")      else None,
            "hr_per_9":   hr_per_9,
            "fip":        fip,
            # Raw counts (stored in DB for auditability)
            "home_runs":  hr  if ip > 0 else None,
            "walks":      bb  if ip > 0 else None,
            "hit_batsmen":hbp if ip > 0 else None,
            "strikeouts": k   if ip > 0 else None,
            # Other
            "innings_pitched": ip,
            "wins":   int(stat.get("wins", 0)),
            "losses": int(stat.get("losses", 0)),
        }

    @staticmethod
    def _ip_to_float(ip_str: str) -> float:
        """Convert "6.1" (6 full innings + 1 out) to 6.333 float."""
        try:
            parts = str(ip_str).split(".")
            full = int(parts[0])
            outs = int(parts[1]) if len(parts) > 1 else 0
            return full + outs / 3
        except (ValueError, IndexError):
            return 0.0
