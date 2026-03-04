"""
Sync NFL game schedule and scores from ESPN's free public site API.
No API key required.

Endpoint: GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
          ?seasontype={2|3}&week={n}&dates={year}

Syncs the last 2 NFL seasons (regular season weeks 1-18 + postseason weeks 1-4).
All games are upserted into the games table. Scores are updated for completed games.
"""
import logging
import time
from datetime import datetime, timezone

import requests

from app.extensions import db
from app.models.game import Game
from app.models.team import Team

logger = logging.getLogger("nfl.sync.espn_schedule")

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
_HEADERS    = {"User-Agent": "NFL-Parlay-Tracker/1.0"}
_RATE_SLEEP = 0.2   # seconds between requests

# (season_type_int, max_weeks, display_name)
_SEASON_PHASES = [
    (2, 18, "Regular Season"),
    (3,  4, "Postseason"),
]


def sync_espn_schedule(client=None) -> tuple[int, int, int]:
    """
    Fetch NFL game schedule for the last 2 seasons from ESPN scoreboard.
    Returns (inserted, updated, skipped).
    """
    inserted = updated = skipped = 0

    # Build ESPN team id → DB team id lookup
    teams = Team.query.filter(Team.api_id.like("espn_%")).all()
    team_map: dict[str, int] = {}
    for t in teams:
        espn_id = t.api_id.replace("espn_", "")
        team_map[espn_id] = t.id

    if not team_map:
        logger.warning("No ESPN-linked teams found — run espn_teams sync first")
        return 0, 0, 0

    # Current NFL season year: season that started in (current_year - 1) if we're in Jan-Aug,
    # or current_year if Sept-Dec. Since we're in March 2026, last completed = 2025.
    now = datetime.now(timezone.utc)
    nfl_year = now.year - 1 if now.month < 9 else now.year
    years_to_sync = [nfl_year - 1, nfl_year]   # last 2 completed seasons

    for year in years_to_sync:
        for season_type, max_weeks, season_type_name in _SEASON_PHASES:
            for week in range(1, max_weeks + 1):
                try:
                    resp = requests.get(
                        ESPN_SCOREBOARD_URL,
                        params={"seasontype": season_type, "week": week, "dates": str(year)},
                        timeout=15,
                        headers=_HEADERS,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.warning(
                        "Scoreboard fetch failed",
                        extra={"year": year, "seasontype": season_type, "week": week, "error": str(exc)},
                    )
                    skipped += 1
                    time.sleep(_RATE_SLEEP)
                    continue

                events = data.get("events", [])
                if not events:
                    time.sleep(_RATE_SLEEP)
                    continue

                for event in events:
                    i, u, s = _upsert_game(event, year, season_type_name, week, team_map)
                    inserted += i
                    updated  += u
                    skipped  += s

                db.session.commit()
                time.sleep(_RATE_SLEEP)

        logger.info(
            "ESPN schedule year done",
            extra={"year": year, "inserted": inserted, "updated": updated},
        )

    logger.info(
        "ESPN schedule sync complete",
        extra={"inserted": inserted, "updated": updated, "skipped": skipped},
    )
    return inserted, updated, skipped


def _upsert_game(
    event: dict,
    year: int,
    season_type_name: str,
    fallback_week: int,
    team_map: dict[str, int],
) -> tuple[int, int, int]:
    espn_event_id = str(event.get("id", "")).strip()
    if not espn_event_id:
        return 0, 0, 1

    api_id = f"espn_{espn_event_id}"

    competitions = event.get("competitions", [])
    if not competitions:
        return 0, 0, 1

    comp        = competitions[0]
    competitors = comp.get("competitors", [])

    home_team_id = away_team_id = None
    home_score   = away_score   = None

    for competitor in competitors:
        team_data = competitor.get("team", {})
        espn_tid  = str(team_data.get("id", "")).strip()
        db_tid    = team_map.get(espn_tid)

        score_str = str(competitor.get("score", "")).strip()
        score = int(score_str) if score_str.isdigit() else None

        if competitor.get("homeAway") == "home":
            home_team_id = db_tid
            home_score   = score
        else:
            away_team_id = db_tid
            away_score   = score

    # Game date
    date_str  = event.get("date", "")
    game_date = None
    if date_str:
        try:
            game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            pass

    # Status
    status_block = event.get("status", {})
    status = (status_block.get("type", {}) or {}).get("description", "Scheduled")

    # Week number (prefer from event, fall back to loop counter)
    week_block = event.get("week") or {}
    week_num   = week_block.get("number", fallback_week)

    # Broadcast
    broadcasts  = comp.get("broadcasts", [])
    broadcast   = broadcasts[0].get("market") if broadcasts else None

    existing = Game.query.filter_by(api_id=api_id).first()
    if existing:
        existing.status = status
        if home_team_id:           existing.home_team_id = home_team_id
        if away_team_id:           existing.away_team_id = away_team_id
        if home_score is not None: existing.home_score   = home_score
        if away_score is not None: existing.away_score   = away_score
        if game_date:              existing.game_date    = game_date
        existing.synced_at = datetime.now(timezone.utc)
        return 0, 1, 0

    db.session.add(Game(
        api_id=api_id,
        season_year=year,
        season_type=season_type_name,
        week=week_num,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
        status=status,
        game_date=game_date,
        broadcast=broadcast,
    ))
    return 1, 0, 0
