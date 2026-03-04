"""
Sync NFL players (per team roster) into the local DB.
Depends on teams being synced first.
"""
import logging
from typing import Any

from app.extensions import db
from app.models.team import Team
from app.models.player import Player
from app.exceptions import DataMappingException
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.players")

ROSTER_PATHS = [
    "/nfl-team-players/v1/data",   # nfl-api-data host
    "/teams/{id}/roster",
    "/v1/teams/{id}/athletes",
]
PLAYER_DETAIL_PATHS = [
    "/nfl-player-full-info/v1/data",
    "/players/{id}",
]


def sync_players(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    teams = Team.query.all()
    logger.info("Syncing players for all teams", extra={"team_count": len(teams)})

    for team in teams:
        if not team.api_id:
            continue
        try:
            i, u, s = _sync_team_roster(client, team)
            inserted += i
            updated += u
            skipped += s
        except Exception as exc:
            logger.error(
                "Failed to sync roster",
                extra={"team": team.abbreviation, "error": str(exc)},
                exc_info=True,
            )
            skipped += 1

    db.session.commit()
    logger.info("Players sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _sync_team_roster(client: NFLApiClient, team: Team) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    raw = _fetch_roster(client, team.api_id)
    players_data = _extract_players(raw)

    for raw_player in players_data:
        try:
            i, u, s = _upsert_player(raw_player, team.id)
            inserted += i
            updated += u
            skipped += s
        except Exception as exc:
            logger.error(
                "Failed to upsert player",
                extra={"team": team.abbreviation, "raw": str(raw_player)[:200], "error": str(exc)},
            )
            skipped += 1
    return inserted, updated, skipped


def _fetch_roster(client: NFLApiClient, team_api_id: str) -> Any:
    for path_tpl in ROSTER_PATHS:
        path = path_tpl.replace("{id}", team_api_id)
        try:
            return client.get(path, params={"id": team_api_id})
        except Exception:
            continue
    raise DataMappingException(f"Could not fetch roster for team {team_api_id}",
                               detail={"team_api_id": team_api_id})


def _extract_players(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ["athletes", "players", "roster", "data", "results"]:
            v = data.get(k)
            if isinstance(v, list):
                return v
            # Nested: {offense: [{...}], defense: [...]}
            if isinstance(v, dict):
                players = []
                for group in v.values():
                    if isinstance(group, list):
                        players.extend(group)
                if players:
                    return players
    return []


def _upsert_player(raw: dict, team_id: int) -> tuple[int, int, int]:
    api_id = str(raw.get("id") or raw.get("playerId") or raw.get("uid") or "")
    if not api_id:
        return 0, 0, 1

    player = Player.query.filter_by(api_id=api_id).first()
    is_new = player is None
    if is_new:
        player = Player(api_id=api_id)
        db.session.add(player)

    player.team_id = team_id
    player.first_name = raw.get("firstName") or raw.get("first_name") or player.first_name
    player.last_name = raw.get("lastName") or raw.get("last_name") or player.last_name
    player.name = (
        raw.get("fullName") or raw.get("displayName") or
        f"{player.first_name or ''} {player.last_name or ''}".strip() or
        player.name or "Unknown"
    )
    player.position = _safe_nested(raw, ["position", "abbreviation"]) or raw.get("position") or player.position
    player.jersey_number = _to_int(raw.get("jersey") or raw.get("jerseyNumber"))
    player.status = _safe_nested(raw, ["status", "name"]) or raw.get("status") or player.status
    player.height = raw.get("displayHeight") or raw.get("height") or player.height
    player.weight = _to_int(raw.get("displayWeight") or raw.get("weight"))
    player.age = _to_int(raw.get("age"))
    player.experience = _to_int(raw.get("experience") or _safe_nested(raw, ["experience", "years"]))
    player.college = _safe_nested(raw, ["college", "name"]) or raw.get("college") or player.college
    player.image_url = _safe_nested(raw, ["headshot", "href"]) or raw.get("imageUrl") or player.image_url

    return (1, 0, 0) if is_new else (0, 1, 0)


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
