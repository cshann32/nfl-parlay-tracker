"""
Link venues to teams and games.
1. Fetch each team's home venue from ESPN → set venues.team_id
2. For each game, set venue_id = home_team's home venue
   (except neutral site games which are handled separately)
Run: .venv/bin/python3 seed_link_venues.py
"""
import requests
import time
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.team import Team
from app.models.venue import Venue
from app.models.game import Game

app = create_app()
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NFLTracker/1.0)"}
ESPN_TEAM_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2025/teams/{espn_id}"


def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def link_teams_to_venues():
    """Fetch home venue from ESPN for each team and update venues.team_id."""
    teams = Team.query.filter(Team.api_id.isnot(None)).all()
    print(f"Linking home venues for {len(teams)} teams...\n")

    team_to_venue_id = {}  # team DB id → venue DB id
    updated = 0

    for team in teams:
        espn_id = team.api_id.replace("espn_", "")
        data = get_json(ESPN_TEAM_URL.format(espn_id=espn_id))
        if not data:
            print(f"  {team.abbreviation}: could not fetch")
            time.sleep(0.1)
            continue

        venue_data = data.get("venue", {})
        venue_espn_id = venue_data.get("id")
        if not venue_espn_id:
            time.sleep(0.1)
            continue

        v_api_id = f"espn_{venue_espn_id}"
        venue = Venue.query.filter_by(api_id=v_api_id).first()
        if venue:
            venue.team_id = team.id
            team_to_venue_id[team.id] = venue.id
            updated += 1
            print(f"  {team.abbreviation} → {venue.name}")
        else:
            print(f"  {team.abbreviation}: venue espn_{venue_espn_id} not found in DB")

        time.sleep(0.15)

    db.session.commit()
    print(f"\n  Linked {updated} teams to their home venues.\n")
    return team_to_venue_id


def link_games_to_venues(team_to_venue_id):
    """Set venue_id on games using the home team's home venue."""
    games = Game.query.filter(Game.venue_id.is_(None)).all()
    print(f"Setting venue_id for {len(games)} games...")

    linked = skipped = 0
    for game in games:
        if game.neutral_site:
            skipped += 1
            continue
        venue_id = team_to_venue_id.get(game.home_team_id)
        if venue_id:
            game.venue_id = venue_id
            linked += 1

    db.session.commit()
    print(f"  Linked: {linked} games | Skipped (neutral site): {skipped}")


if __name__ == "__main__":
    with app.app_context():
        team_to_venue_id = link_teams_to_venues()
        link_games_to_venues(team_to_venue_id)
        print("\nDone.")
