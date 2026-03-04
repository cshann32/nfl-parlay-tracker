"""
Sync NFL teams from the API into the local DB.
Handles: team listing, team detail, logos.
"""
import logging
from typing import Any

from app.extensions import db
from app.models.team import Team
from app.exceptions import DataMappingException
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.teams")

# Candidate endpoint paths — client will try primary host then fallback
TEAMS_LIST_PATHS = ["/nfl-team-listing/v1/data", "/teams", "/v1/teams"]
TEAM_DETAIL_PATHS = ["/nfl-team-info/v1/data", "/teams/{id}", "/v1/teams/{id}"]


def sync_teams(client: NFLApiClient) -> tuple[int, int, int]:
    """
    Fetch all NFL teams and upsert into DB.
    Returns (inserted, updated, skipped).
    """
    inserted = updated = skipped = 0
    raw = _fetch_teams_list(client)
    teams_data = _extract_list(raw, ["teams", "data", "results"])

    logger.info("Syncing teams", extra={"count": len(teams_data)})

    for raw_team in teams_data:
        try:
            i, u, s = _upsert_team(raw_team)
            inserted += i
            updated += u
            skipped += s
        except Exception as exc:
            logger.error(
                "Failed to upsert team",
                extra={"raw": str(raw_team)[:200], "error": str(exc)},
                exc_info=True,
            )
            skipped += 1

    db.session.commit()
    logger.info("Teams sync complete", extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _fetch_teams_list(client: NFLApiClient) -> Any:
    for path in TEAMS_LIST_PATHS:
        try:
            return client.get(path)
        except Exception:
            continue
    raise DataMappingException("Could not fetch teams from any known endpoint path",
                               detail={"tried": TEAMS_LIST_PATHS})


def _upsert_team(raw: dict) -> tuple[int, int, int]:
    api_id = str(raw.get("id") or raw.get("teamId") or raw.get("uid") or "")
    if not api_id:
        logger.warning("Team missing api_id, skipping", extra={"raw": str(raw)[:200]})
        return 0, 0, 1

    team = Team.query.filter_by(api_id=api_id).first()
    is_new = team is None
    if is_new:
        team = Team(api_id=api_id)
        db.session.add(team)

    # Map common field names from the API response
    team.name = _get(raw, ["name", "teamName", "shortName"], team.name)
    team.full_name = _get(raw, ["displayName", "fullName", "longName"], team.full_name)
    team.abbreviation = _get(raw, ["abbreviation", "abbrev", "teamAbbrev"], team.abbreviation)
    team.city = _get(raw, ["location", "city", "teamCity"], team.city)
    team.conference = _safe_nested(raw, ["conference", "name"]) or _get(raw, ["conference"], team.conference)
    team.division = _safe_nested(raw, ["division", "name"]) or _get(raw, ["division"], team.division)
    team.logo_url = _safe_nested(raw, ["logos", 0, "href"]) or _get(raw, ["logo", "logoUrl"], team.logo_url)
    team.primary_color = _safe_nested(raw, ["color"]) or team.primary_color
    team.secondary_color = _safe_nested(raw, ["alternateColor"]) or team.secondary_color

    return (1, 0, 0) if is_new else (0, 1, 0)


def _get(d: dict, keys: list[str], default=None):
    """Try multiple key names, return first match."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _safe_nested(d: dict, path: list) -> Any:
    """Navigate nested dict/list path safely."""
    cur = d
    for key in path:
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _extract_list(data: Any, keys: list[str]) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return data[k]
    return []
