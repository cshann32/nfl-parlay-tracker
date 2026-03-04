"""
Sync NFL games/events into the local DB.
Depends on teams and seasons being synced first.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.models.game import Game
from app.models.team import Team
from app.models.season import Season
from app.exceptions import DataMappingException
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.games")

EVENTS_PATHS = [
    "/nfl-events/v1/data",
    "/events",
    "/v1/events",
    "/games",
]


def sync_games(client: NFLApiClient, season_year: int | None = None) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    params = {}
    if season_year:
        params["season"] = season_year

    raw = _fetch_events(client, params)
    events = _extract_events(raw)
    logger.info("Syncing games", extra={"count": len(events), "season_year": season_year})

    team_cache: dict[str, int] = {t.api_id: t.id for t in Team.query.all() if t.api_id}
    season_cache: dict[int, int] = {s.year: s.id for s in Season.query.all()}

    for raw_event in events:
        try:
            i, u, s = _upsert_game(raw_event, team_cache, season_cache)
            inserted += i
            updated += u
            skipped += s
        except Exception as exc:
            logger.error(
                "Failed to upsert game",
                extra={"raw": str(raw_event)[:300], "error": str(exc)},
                exc_info=True,
            )
            skipped += 1

    db.session.commit()
    logger.info("Games sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _fetch_events(client: NFLApiClient, params: dict) -> Any:
    for path in EVENTS_PATHS:
        try:
            return client.get(path, params=params)
        except Exception:
            continue
    raise DataMappingException("Could not fetch events from any known path",
                               detail={"tried": EVENTS_PATHS})


def _upsert_game(raw: dict, team_cache: dict, season_cache: dict) -> tuple[int, int, int]:
    api_id = str(raw.get("id") or raw.get("eventId") or raw.get("uid") or "")
    if not api_id:
        return 0, 0, 1

    game = Game.query.filter_by(api_id=api_id).first()
    is_new = game is None
    if is_new:
        game = Game(api_id=api_id)
        db.session.add(game)

    # Season
    season_year = _to_int(_safe_nested(raw, ["season", "year"]) or raw.get("seasonYear") or raw.get("year"))
    game.season_year = season_year
    game.season_id = season_cache.get(season_year) if season_year else game.season_id
    game.season_type = _safe_nested(raw, ["seasonType", "name"]) or raw.get("seasonType") or game.season_type
    game.week = _to_int(_safe_nested(raw, ["week", "number"]) or raw.get("week"))

    # Teams — competitions[0].competitors
    comps = _safe_nested(raw, ["competitions", 0, "competitors"]) or []
    for comp in comps:
        is_home = str(comp.get("homeAway", "")).lower() == "home"
        team_api_id = str(_safe_nested(comp, ["team", "id"]) or "")
        team_db_id = team_cache.get(team_api_id)
        score = _to_int(comp.get("score"))
        if is_home:
            game.home_team_id = team_db_id
            game.home_score = score
        else:
            game.away_team_id = team_db_id
            game.away_score = score

    # Date / status
    date_str = raw.get("date") or _safe_nested(raw, ["competitions", 0, "date"])
    if date_str:
        game.game_date = _parse_date(date_str)
    game.status = _safe_nested(raw, ["status", "type", "name"]) or raw.get("status") or game.status
    game.broadcast = _safe_nested(raw, ["competitions", 0, "broadcasts", 0, "names", 0]) or game.broadcast
    game.neutral_site = bool(_safe_nested(raw, ["competitions", 0, "neutralSite"]))

    return (1, 0, 0) if is_new else (0, 1, 0)


def _extract_events(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ["events", "games", "data", "results", "body"]:
            if isinstance(data.get(k), list):
                return data[k]
    return []


def _parse_date(date_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _safe_nested(d, path):
    cur = d
    for key in path:
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _to_int(val) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
