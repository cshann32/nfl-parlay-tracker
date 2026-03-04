"""
Seed NFL teams and players from ESPN's free public API.
Run with: python seed_nfl_data.py
"""
import time
import requests
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models.team import Team
from app.models.player import Player

app = create_app()

ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams?limit=32"
ESPN_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{espn_id}/roster"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NFLTracker/1.0)"}

# Conference + division lookup by ESPN team abbreviation
TEAM_INFO = {
    "ARI": ("NFC", "West"),   "ATL": ("NFC", "South"),
    "BAL": ("AFC", "North"),  "BUF": ("AFC", "East"),
    "CAR": ("NFC", "South"),  "CHI": ("NFC", "North"),
    "CIN": ("AFC", "North"),  "CLE": ("AFC", "North"),
    "DAL": ("NFC", "East"),   "DEN": ("AFC", "West"),
    "DET": ("NFC", "North"),  "GB":  ("NFC", "North"),
    "HOU": ("AFC", "South"),  "IND": ("AFC", "South"),
    "JAX": ("AFC", "South"),  "KC":  ("AFC", "West"),
    "LV":  ("AFC", "West"),   "LAC": ("AFC", "West"),
    "LAR": ("NFC", "West"),   "MIA": ("AFC", "East"),
    "MIN": ("NFC", "North"),  "NE":  ("AFC", "East"),
    "NO":  ("NFC", "South"),  "NYG": ("NFC", "East"),
    "NYJ": ("AFC", "East"),   "PHI": ("NFC", "East"),
    "PIT": ("AFC", "North"),  "SF":  ("NFC", "West"),
    "SEA": ("NFC", "West"),   "TB":  ("NFC", "South"),
    "TEN": ("AFC", "South"),  "WSH": ("NFC", "East"),
}


def get_json(url, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retries - 1:
                print(f"  ERROR fetching {url}: {e}")
                return None
            time.sleep(2 ** i)


def seed_teams():
    print("=== Seeding Teams ===")
    data = get_json(ESPN_TEAMS_URL)
    if not data:
        print("Failed to fetch teams.")
        return {}

    team_map = {}  # espn_id -> DB team id
    teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])

    inserted = updated = 0
    for entry in teams:
        t = entry.get("team", {})
        espn_id = str(t.get("id", ""))
        abbr = t.get("abbreviation", "")
        display = t.get("displayName", "")
        short = t.get("shortDisplayName", "")
        location = t.get("location", "")
        color = t.get("color", "")
        alt_color = t.get("alternateColor", "")

        conf, div = TEAM_INFO.get(abbr, ("", ""))

        existing = Team.query.filter_by(api_id=f"espn_{espn_id}").first()
        if existing:
            existing.name = short
            existing.abbreviation = abbr
            existing.city = location
            existing.full_name = display
            existing.conference = conf
            existing.division = div
            existing.primary_color = f"#{color}" if color else None
            existing.secondary_color = f"#{alt_color}" if alt_color else None
            team_map[espn_id] = existing.id
            updated += 1
        else:
            team = Team(
                name=short,
                abbreviation=abbr,
                city=location,
                full_name=display,
                conference=conf,
                division=div,
                primary_color=f"#{color}" if color else None,
                secondary_color=f"#{alt_color}" if alt_color else None,
                api_id=f"espn_{espn_id}",
            )
            db.session.add(team)
            db.session.flush()
            team_map[espn_id] = team.id
            inserted += 1

        print(f"  {'[NEW]' if not existing else '[UPD]'} {abbr} - {display}")

    db.session.commit()
    print(f"Teams: {inserted} inserted, {updated} updated\n")
    return team_map


def seed_players(team_map):
    print("=== Seeding Players ===")
    # Get espn_id -> team_db_id mapping via abbr
    data = get_json(ESPN_TEAMS_URL)
    if not data:
        return

    teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
    total_inserted = total_updated = 0

    for entry in teams:
        t = entry.get("team", {})
        espn_id = str(t.get("id", ""))
        abbr = t.get("abbreviation", "")
        team_db_id = team_map.get(espn_id)

        print(f"  Fetching roster: {abbr}...", end=" ", flush=True)
        roster_data = get_json(ESPN_ROSTER_URL.format(espn_id=espn_id))
        if not roster_data:
            print("FAILED")
            continue

        inserted = updated = 0
        # ESPN roster has athletes grouped by position group
        athlete_groups = roster_data.get("athletes", [])
        for group in athlete_groups:
            athletes = group.get("items", [])
            for athlete in athletes:
                pid = str(athlete.get("id", ""))
                api_id = f"espn_{pid}"

                full_name = athlete.get("fullName", "")
                first_name = athlete.get("firstName", "")
                last_name = athlete.get("lastName", "")
                position = athlete.get("position", {}).get("abbreviation", "")
                jersey = athlete.get("jersey")
                status_obj = athlete.get("status", "Active")
                if isinstance(status_obj, dict):
                    status = status_obj.get("type", {}).get("description", "Active") if isinstance(status_obj.get("type"), dict) else status_obj.get("name", "Active")
                else:
                    status = str(status_obj) if status_obj else "Active"

                # Physical info
                display_height = athlete.get("displayHeight", "")
                display_weight = athlete.get("displayWeight", "")
                weight = None
                if display_weight:
                    try:
                        weight = int(display_weight.replace(" lbs", "").strip())
                    except ValueError:
                        pass

                age = athlete.get("age")
                exp = athlete.get("experience", {}).get("years") if isinstance(athlete.get("experience"), dict) else None
                college_obj = athlete.get("college", {})
                college = college_obj.get("name", "") if isinstance(college_obj, dict) else ""
                headshot = athlete.get("headshot", {}).get("href", "") if isinstance(athlete.get("headshot"), dict) else ""

                jersey_num = None
                if jersey:
                    try:
                        jersey_num = int(jersey)
                    except ValueError:
                        pass

                existing = Player.query.filter_by(api_id=api_id).first()
                if existing:
                    existing.team_id = team_db_id
                    existing.name = full_name
                    existing.first_name = first_name
                    existing.last_name = last_name
                    existing.position = position
                    existing.jersey_number = jersey_num
                    existing.status = status
                    existing.height = display_height
                    existing.weight = weight
                    existing.age = age
                    existing.experience = exp
                    existing.college = college
                    existing.image_url = headshot or None
                    updated += 1
                else:
                    player = Player(
                        team_id=team_db_id,
                        name=full_name,
                        first_name=first_name,
                        last_name=last_name,
                        position=position,
                        jersey_number=jersey_num,
                        status=status,
                        height=display_height,
                        weight=weight,
                        age=age,
                        experience=exp,
                        college=college,
                        image_url=headshot or None,
                        api_id=api_id,
                    )
                    db.session.add(player)
                    inserted += 1

        db.session.commit()
        total_inserted += inserted
        total_updated += updated
        print(f"{inserted} new, {updated} updated")
        time.sleep(0.3)  # be polite

    print(f"\nPlayers total: {total_inserted} inserted, {total_updated} updated")


if __name__ == "__main__":
    with app.app_context():
        team_map = seed_teams()
        if team_map:
            seed_players(team_map)
        print("\nDone!")
