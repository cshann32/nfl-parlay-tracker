"""
Sync NFL teams from ESPN's free public site API.
No API key required.

Endpoint: GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams
Covers: name, abbreviation, city, full_name, logo_url, primary_color, secondary_color
"""
import logging
import time
from datetime import datetime, timezone

import requests

from app.extensions import db
from app.models.team import Team

logger = logging.getLogger("nfl.sync.espn_teams")

ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"

# Stable ESPN team ID → (conference, division) mapping.
# These IDs are fixed — NFL realignment would require an update here.
_CONF_DIV: dict[str, tuple[str, str]] = {
    # AFC East
    "2":  ("AFC", "East"),   # Buffalo Bills
    "15": ("AFC", "East"),   # Miami Dolphins
    "17": ("AFC", "East"),   # New England Patriots
    "20": ("AFC", "East"),   # New York Jets
    # AFC North
    "33": ("AFC", "North"),  # Baltimore Ravens
    "4":  ("AFC", "North"),  # Cincinnati Bengals
    "5":  ("AFC", "North"),  # Cleveland Browns
    "23": ("AFC", "North"),  # Pittsburgh Steelers
    # AFC South
    "34": ("AFC", "South"),  # Houston Texans
    "11": ("AFC", "South"),  # Indianapolis Colts
    "30": ("AFC", "South"),  # Jacksonville Jaguars
    "10": ("AFC", "South"),  # Tennessee Titans
    # AFC West
    "7":  ("AFC", "West"),   # Denver Broncos
    "12": ("AFC", "West"),   # Kansas City Chiefs
    "13": ("AFC", "West"),   # Las Vegas Raiders
    "24": ("AFC", "West"),   # Los Angeles Chargers
    # NFC East
    "6":  ("NFC", "East"),   # Dallas Cowboys
    "19": ("NFC", "East"),   # New York Giants
    "21": ("NFC", "East"),   # Philadelphia Eagles
    "28": ("NFC", "East"),   # Washington Commanders
    # NFC North
    "3":  ("NFC", "North"),  # Chicago Bears
    "8":  ("NFC", "North"),  # Detroit Lions
    "9":  ("NFC", "North"),  # Green Bay Packers
    "16": ("NFC", "North"),  # Minnesota Vikings
    # NFC South
    "1":  ("NFC", "South"),  # Atlanta Falcons
    "29": ("NFC", "South"),  # Carolina Panthers
    "18": ("NFC", "South"),  # New Orleans Saints
    "27": ("NFC", "South"),  # Tampa Bay Buccaneers
    # NFC West
    "22": ("NFC", "West"),   # Arizona Cardinals
    "14": ("NFC", "West"),   # Los Angeles Rams
    "25": ("NFC", "West"),   # San Francisco 49ers
    "26": ("NFC", "West"),   # Seattle Seahawks
}


def sync_espn_teams(client=None) -> tuple[int, int, int]:
    """
    Fetch all 32 NFL teams from ESPN and upsert into the teams table.
    Returns (inserted, updated, skipped).
    """
    inserted = updated = skipped = 0

    resp = requests.get(
        ESPN_TEAMS_URL,
        params={"limit": 50},
        timeout=15,
        headers={"User-Agent": "NFL-Parlay-Tracker/1.0"},
    )
    resp.raise_for_status()
    data = resp.json()

    # ESPN structure: sports[0].leagues[0].teams[].team
    teams_raw = (
        data.get("sports", [{}])[0]
            .get("leagues", [{}])[0]
            .get("teams", [])
    )

    if not teams_raw:
        logger.warning("ESPN teams API returned no teams")
        return 0, 0, 0

    for entry in teams_raw:
        t = entry.get("team", {})
        espn_id = str(t.get("id", "")).strip()
        if not espn_id:
            skipped += 1
            continue

        api_id       = f"espn_{espn_id}"
        abbreviation = t.get("abbreviation", "").strip()
        display_name = t.get("displayName", "").strip()   # e.g. "Kansas City Chiefs"
        location     = t.get("location", "").strip()      # e.g. "Kansas City"
        color        = t.get("color", "").strip()
        alt_color    = t.get("alternateColor", "").strip()
        logos        = t.get("logos", [])
        logo_url     = logos[0].get("href") if logos else None

        primary_color   = f"#{color}"     if color     else None
        secondary_color = f"#{alt_color}" if alt_color else None
        conference, division = _CONF_DIV.get(espn_id, (None, None))

        # Match existing record by api_id first, then abbreviation fallback
        team = Team.query.filter_by(api_id=api_id).first()
        if not team and abbreviation:
            team = Team.query.filter_by(abbreviation=abbreviation).first()

        if team:
            team.api_id = api_id
            if display_name:  team.name          = display_name
            if display_name:  team.full_name      = display_name
            if abbreviation:  team.abbreviation   = abbreviation
            if location:      team.city           = location
            if logo_url:      team.logo_url       = logo_url
            if primary_color: team.primary_color  = primary_color
            if secondary_color: team.secondary_color = secondary_color
            if conference:    team.conference     = conference
            if division:      team.division       = division
            team.synced_at = datetime.now(timezone.utc)
            updated += 1
        else:
            db.session.add(Team(
                api_id=api_id,
                name=display_name or abbreviation,
                full_name=display_name,
                abbreviation=abbreviation,
                city=location,
                logo_url=logo_url,
                primary_color=primary_color,
                secondary_color=secondary_color,
                conference=conference,
                division=division,
            ))
            inserted += 1

    db.session.commit()
    logger.info(
        "ESPN teams sync complete",
        extra={"inserted": inserted, "updated": updated, "skipped": skipped},
    )
    return inserted, updated, skipped
