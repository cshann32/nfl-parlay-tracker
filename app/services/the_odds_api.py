"""
Client for The Odds API (the-odds-api.com).
Fetches live NFL odds and recent scores.
"""
import logging
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("nfl.the_odds_api")

_BASE = "https://api.the-odds-api.com/v4"
_SPORT = "americanfootball_nfl"


class OddsApiClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _get(self, path: str, **params) -> list | dict:
        params["apiKey"] = self.api_key
        resp = requests.get(f"{_BASE}{path}", params=params, timeout=15)
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
        logger.info("Odds API quota — used: %s  remaining: %s", used, remaining)
        return resp.json()

    def get_odds(self, regions: str = "us", markets: str = "h2h,spreads,totals") -> list:
        return self._get(
            f"/sports/{_SPORT}/odds",
            regions=regions,
            markets=markets,
            oddsFormat="american",
        )

    def get_scores(self, days_from: int = 3) -> list:
        return self._get(f"/sports/{_SPORT}/scores", daysFrom=days_from)


# ── Team + game matching ───────────────────────────────────────────────────────

def _build_team_map() -> dict[str, int]:
    """Return {normalized_team_name: team_id} for all teams in the DB."""
    from app.models.team import Team
    teams = Team.query.all()
    return {t.name.lower().strip(): t.id for t in teams if t.name}


def _find_team_id(api_name: str, team_map: dict[str, int]) -> int | None:
    name = api_name.lower().strip()
    if name in team_map:
        return team_map[name]
    # Fall back to mascot word (last word of the name)
    mascot = name.split()[-1]
    for key, tid in team_map.items():
        if key.split()[-1] == mascot:
            return tid
    return None


def _find_game(home_id: int, away_id: int, commence_dt: datetime,
               games_by_teams: dict):
    """Return the DB Game whose teams and date best match the API event."""
    window = timedelta(hours=36)
    for game in games_by_teams.get((home_id, away_id), []):
        if game.game_date and abs(game.game_date - commence_dt) <= window:
            return game
    return None


def _parse_bookmaker(home_team_name: str, bookmaker: dict) -> dict:
    """Flatten all markets from one bookmaker entry into a single Odds dict."""
    row: dict = {
        "source": bookmaker.get("title"),
        "market_type": None,
        "home_moneyline": None, "away_moneyline": None,
        "home_spread": None, "away_spread": None,
        "spread_juice_home": None, "spread_juice_away": None,
        "over_under": None, "over_juice": None, "under_juice": None,
    }
    home = home_team_name.lower()

    for market in bookmaker.get("markets", []):
        key = market.get("key")
        outcomes = market.get("outcomes", [])

        if key == "h2h":
            for o in outcomes:
                price = int(o["price"])
                if o["name"].lower() == home:
                    row["home_moneyline"] = price
                else:
                    row["away_moneyline"] = price

        elif key == "spreads":
            for o in outcomes:
                price = int(o["price"])
                point = float(o.get("point", 0))
                if o["name"].lower() == home:
                    row["home_spread"] = point
                    row["spread_juice_home"] = price
                else:
                    row["away_spread"] = point
                    row["spread_juice_away"] = price

        elif key == "totals":
            for o in outcomes:
                price = int(o["price"])
                point = float(o.get("point", 0))
                if o["name"] == "Over":
                    row["over_under"] = point
                    row["over_juice"] = price
                elif o["name"] == "Under":
                    row["under_juice"] = price

    return row
