"""
Enrich venue data: roof_type, surface, capacity from ESPN API + hardcoded capacities.
Run with: .venv/bin/python3 seed_venues.py
"""
import requests
import time
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models.venue import Venue

app = create_app()
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NFLTracker/1.0)"}

# Hardcoded 2025 NFL stadium capacities (ESPN API doesn't expose this)
CAPACITIES = {
    "GEHA Field at Arrowhead Stadium": 76416,
    "Mercedes-Benz Stadium": 71000,
    "Highmark Stadium": 71608,
    "Soldier Field": 61500,
    "Paycor Stadium": 65515,
    "Cleveland Browns Stadium": 67431,
    "AT&T Stadium": 80000,
    "Empower Field at Mile High": 76125,
    "Ford Field": 65000,
    "Lambeau Field": 81441,
    "NRG Stadium": 72220,
    "Lucas Oil Stadium": 67000,
    "EverBank Stadium": 67814,
    "TIAA Bank Stadium": 67814,
    "Allegiant Stadium": 65000,
    "SoFi Stadium": 70240,
    "Lumen Field": 68740,
    "Hard Rock Stadium": 64767,
    "U.S. Bank Stadium": 66860,
    "Gillette Stadium": 65878,
    "Caesars Superdome": 73208,
    "MetLife Stadium": 82500,
    "Lincoln Financial Field": 69796,
    "Acrisure Stadium": 68400,
    "Raymond James Stadium": 65890,
    "Nissan Stadium": 69143,
    "Northwest Stadium": 67617,
    "FedExField": 67617,
    "State Farm Stadium": 63400,
    "Levi's Stadium": 68500,
    "Bank of America Stadium": 74867,
    "M&T Bank Stadium": 71008,
    "Huntington Bank Field": 67431,
    "Rocket Mortgage FieldHouse": 67431,  # placeholder
}


def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def seed_venues():
    venues = Venue.query.filter(Venue.api_id.isnot(None)).all()
    print(f"Updating {len(venues)} venues from ESPN API...\n")

    updated = 0
    for v in venues:
        espn_id = v.api_id.replace("espn_", "")
        url = f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/venues/{espn_id}"
        data = get_json(url)

        changed = False
        if data:
            indoor = data.get("indoor")
            grass = data.get("grass")

            if indoor is not None and v.roof_type is None:
                v.roof_type = "Dome" if indoor else "Open"
                changed = True

            if grass is not None and (v.surface is None or v.surface == "Unknown"):
                v.surface = "Grass" if grass else "FieldTurf"
                changed = True

        # Capacity from hardcoded table
        if v.capacity is None:
            cap = CAPACITIES.get(v.name)
            if cap:
                v.capacity = cap
                changed = True

        if changed:
            updated += 1
            print(f"  {v.name}: roof={v.roof_type}, surface={v.surface}, capacity={v.capacity}")

        time.sleep(0.15)

    db.session.commit()
    print(f"\nDone. Updated {updated} venues.")


if __name__ == "__main__":
    with app.app_context():
        seed_venues()
