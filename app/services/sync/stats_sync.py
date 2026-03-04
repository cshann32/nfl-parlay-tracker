"""Sync NFL player and team statistics into the local DB."""
import logging
from typing import Any
from app.extensions import db
from app.models.stat import PlayerStat, TeamStat
from app.models.player import Player
from app.models.team import Team
from app.models.game import Game
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.stats")

PLAYER_STATS_PATHS = ["/nfl-player-statistics/v1/data", "/players/{id}/statistics", "/v1/statistics/players"]
TEAM_STATS_PATHS = ["/nfl-team-statistics/v1/data", "/teams/{id}/statistics", "/v1/statistics/teams"]


def sync_stats(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0

    # Sync player stats per player
    players = Player.query.filter(Player.api_id.isnot(None)).all()
    logger.info("Syncing player stats", extra={"player_count": len(players)})
    for player in players:
        try:
            i, u, s = _sync_player_stats(client, player)
            inserted += i; updated += u; skipped += s
        except Exception as exc:
            logger.error("Failed player stats", extra={"player_id": player.api_id, "error": str(exc)})
            skipped += 1

    # Sync team stats per team
    teams = Team.query.filter(Team.api_id.isnot(None)).all()
    logger.info("Syncing team stats", extra={"team_count": len(teams)})
    for team in teams:
        try:
            i, u, s = _sync_team_stats(client, team)
            inserted += i; updated += u; skipped += s
        except Exception as exc:
            logger.error("Failed team stats", extra={"team_id": team.api_id, "error": str(exc)})
            skipped += 1

    db.session.commit()
    logger.info("Stats sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _sync_player_stats(client: NFLApiClient, player: Player) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    for path_tpl in PLAYER_STATS_PATHS:
        try:
            path = path_tpl.replace("{id}", player.api_id)
            raw = client.get(path, params={"id": player.api_id})
            stat_groups = _extract_stat_groups(raw)
            for category, stat_type, value, game_api_id in _flatten_stats(stat_groups):
                game_id = _resolve_game_id(game_api_id)
                i, u, s = _upsert_player_stat(player.id, game_id, category, stat_type, value)
                inserted += i; updated += u; skipped += s
            break
        except Exception:
            continue
    return inserted, updated, skipped


def _sync_team_stats(client: NFLApiClient, team: Team) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    for path_tpl in TEAM_STATS_PATHS:
        try:
            path = path_tpl.replace("{id}", team.api_id)
            raw = client.get(path, params={"id": team.api_id})
            stat_groups = _extract_stat_groups(raw)
            for category, stat_type, value, game_api_id in _flatten_stats(stat_groups):
                game_id = _resolve_game_id(game_api_id)
                i, u, s = _upsert_team_stat(team.id, game_id, category, stat_type, value)
                inserted += i; updated += u; skipped += s
            break
        except Exception:
            continue
    return inserted, updated, skipped


def _upsert_player_stat(player_id, game_id, category, stat_type, value) -> tuple[int, int, int]:
    existing = PlayerStat.query.filter_by(
        player_id=player_id, game_id=game_id,
        stat_category=category, stat_type=stat_type
    ).first()
    if existing:
        existing.value = value
        return 0, 1, 0
    db.session.add(PlayerStat(player_id=player_id, game_id=game_id,
                               stat_category=category, stat_type=stat_type, value=value))
    return 1, 0, 0


def _upsert_team_stat(team_id, game_id, category, stat_type, value) -> tuple[int, int, int]:
    existing = TeamStat.query.filter_by(
        team_id=team_id, game_id=game_id,
        stat_category=category, stat_type=stat_type
    ).first()
    if existing:
        existing.value = value
        return 0, 1, 0
    db.session.add(TeamStat(team_id=team_id, game_id=game_id,
                             stat_category=category, stat_type=stat_type, value=value))
    return 1, 0, 0


def _extract_stat_groups(data: Any) -> list[dict]:
    if isinstance(data, list): return data
    for k in ["statistics", "stats", "data", "results", "splits"]:
        if isinstance(data.get(k) if isinstance(data, dict) else None, list):
            return data[k]
    return []


def _flatten_stats(groups: list[dict]):
    """Yield (category, stat_type, value, game_api_id) tuples."""
    for group in groups:
        category = group.get("name") or group.get("category") or "general"
        game_api_id = str(group.get("gameId") or group.get("eventId") or "")
        for stat in group.get("stats", group.get("statistics", [])):
            stat_type = stat.get("name") or stat.get("abbreviation") or stat.get("label")
            value = stat.get("value") or stat.get("displayValue")
            if stat_type and value is not None:
                try:
                    yield category, str(stat_type), float(value), game_api_id
                except (ValueError, TypeError):
                    continue


def _resolve_game_id(game_api_id: str) -> int | None:
    if not game_api_id:
        return None
    g = Game.query.filter_by(api_id=game_api_id).first()
    return g.id if g else None
