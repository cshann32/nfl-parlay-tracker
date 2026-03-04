"""
Link neutral site games (international games, Super Bowl) to their venues.
Run: .venv/bin/python3 seed_neutral_venues.py
"""
import requests
import time
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.game import Game
from app.models.venue import Venue

app = create_app()
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NFLTracker/1.0)"}


def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def seed():
    neutral_games = Game.query.filter(
        Game.venue_id.is_(None), Game.neutral_site == True
    ).all()
    print(f"Fetching venue for {len(neutral_games)} neutral site games...")

    linked = 0
    for game in neutral_games:
        event_id = game.api_id.replace("espn_", "")
        url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"
        data = get_json(url)
        if not data:
            time.sleep(0.2)
            continue

        gi = data.get("gameInfo", {})
        v_data = gi.get("venue", {})
        vid = str(v_data.get("id", ""))
        if not vid:
            time.sleep(0.2)
            continue

        v_api_id = f"espn_{vid}"
        venue = Venue.query.filter_by(api_id=v_api_id).first()
        if not venue:
            addr = v_data.get("address", {})
            grass = v_data.get("grass")
            indoor = v_data.get("indoor")
            venue = Venue(
                name=v_data.get("fullName", "Unknown"),
                city=addr.get("city"),
                state=addr.get("state"),
                country=addr.get("country", "USA"),
                surface="Grass" if grass else "Turf",
                roof_type="Dome" if indoor else "Open",
                api_id=v_api_id,
            )
            db.session.add(venue)
            db.session.flush()
            print(f"  Created: {venue.name} ({venue.city}, {venue.country})")

        game.venue_id = venue.id
        linked += 1
        print(f"  Linked: {game.api_id} → {venue.name}")
        time.sleep(0.3)

    db.session.commit()
    print(f"\nDone. Linked {linked} neutral site games.")


if __name__ == "__main__":
    with app.app_context():
        seed()
