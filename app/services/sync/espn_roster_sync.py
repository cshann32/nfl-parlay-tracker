"""
Sync NFL player rosters from ESPN's free public site API.
No API key required.

Endpoint: GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster
Loops over all teams that have an ESPN api_id, fetches full roster, upserts players.
"""
import logging
import time
from datetime import datetime, timezone

import requests

from app.extensions import db
from app.models.player import Player
from app.models.team import Team

logger = logging.getLogger("nfl.sync.espn_roster")

ESPN_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
_HEADERS = {"User-Agent": "NFL-Parlay-Tracker/1.0"}
_RATE_SLEEP = 0.2   # seconds between team requests


def sync_espn_roster(client=None) -> tuple[int, int, int]:
    """
    Fetch rosters for all teams that have an ESPN api_id and upsert players.
    Returns (inserted, updated, skipped).
    """
    inserted = updated = skipped = 0

    teams = Team.query.filter(Team.api_id.like("espn_%")).order_by(Team.name).all()
    if not teams:
        logger.warning("No ESPN-linked teams found — run espn_teams sync first")
        return 0, 0, 0

    for team in teams:
        espn_team_id = team.api_id.replace("espn_", "")
        url = ESPN_ROSTER_URL.format(team_id=espn_team_id)

        try:
            resp = requests.get(url, timeout=15, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(
                "Roster fetch failed",
                extra={"team": team.abbreviation, "espn_id": espn_team_id, "error": str(exc)},
            )
            skipped += 1
            time.sleep(_RATE_SLEEP)
            continue

        # ESPN groups athletes by position group: athletes[].items[]
        for group in data.get("athletes", []):
            for p in group.get("items", []):
                i, u, s = _upsert_player(p, team.id)
                inserted += i
                updated  += u
                skipped  += s

        db.session.commit()
        logger.debug("Roster synced", extra={"team": team.abbreviation, "inserted": inserted})
        time.sleep(_RATE_SLEEP)

    logger.info(
        "ESPN roster sync complete",
        extra={"teams": len(teams), "inserted": inserted, "updated": updated, "skipped": skipped},
    )
    return inserted, updated, skipped


def _upsert_player(p: dict, team_id: int) -> tuple[int, int, int]:
    """Upsert a single player dict from the ESPN roster response."""
    espn_pid = str(p.get("id", "")).strip()
    if not espn_pid:
        return 0, 0, 1

    api_id    = f"espn_{espn_pid}"
    full_name = (p.get("fullName") or p.get("displayName") or "").strip()
    if not full_name:
        return 0, 0, 1

    first_name = p.get("firstName", "").strip() or None
    last_name  = p.get("lastName",  "").strip() or None

    pos_data = p.get("position", {}) or {}
    position = pos_data.get("abbreviation", "").strip() or None

    jersey_str    = p.get("jersey", "")
    jersey_number = int(jersey_str) if jersey_str and str(jersey_str).isdigit() else None

    # Height: ESPN gives total inches (e.g. 74 → 6'2")
    height_inches = p.get("height")
    if height_inches:
        ft  = int(height_inches) // 12
        ins = int(height_inches) % 12
        height_str = f"{ft}'{ins}\""
    else:
        height_str = None

    weight_raw = p.get("weight")
    weight = int(weight_raw) if weight_raw else None

    # Age from dateOfBirth
    dob_str = p.get("dateOfBirth", "")
    age = None
    if dob_str:
        try:
            dob = datetime.fromisoformat(dob_str.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dob).days // 365
        except Exception:
            pass

    exp_raw    = p.get("experience") or {}
    experience = exp_raw.get("years") if isinstance(exp_raw, dict) else None

    headshot  = p.get("headshot") or {}
    image_url = headshot.get("href") or None

    college_data = p.get("college") or {}
    college = (college_data.get("shortName") or college_data.get("name") or "").strip() or None

    status_data = p.get("status") or {}
    status = (status_data.get("name") or "Active").strip()

    existing = Player.query.filter_by(api_id=api_id).first()
    if existing:
        existing.team_id      = team_id
        existing.name         = full_name
        existing.first_name   = first_name or existing.first_name
        existing.last_name    = last_name  or existing.last_name
        existing.position     = position   or existing.position
        existing.jersey_number = jersey_number
        existing.height       = height_str or existing.height
        existing.weight       = weight     or existing.weight
        existing.age          = age        or existing.age
        existing.experience   = experience if experience is not None else existing.experience
        existing.image_url    = image_url  or existing.image_url
        existing.college      = college    or existing.college
        existing.status       = status
        existing.synced_at    = datetime.now(timezone.utc)
        return 0, 1, 0

    db.session.add(Player(
        api_id=api_id,
        team_id=team_id,
        name=full_name,
        first_name=first_name,
        last_name=last_name,
        position=position,
        jersey_number=jersey_number,
        height=height_str,
        weight=weight,
        age=age,
        experience=experience,
        image_url=image_url,
        college=college,
        status=status,
    ))
    return 1, 0, 0
