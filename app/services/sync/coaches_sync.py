"""Sync NFL coaches per team."""
import logging
from app.extensions import db
from app.models.coach import Coach
from app.models.team import Team
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.coaches")

COACHES_PATHS = ["/nfl-coaches/v1/data", "/teams/{id}/coaches", "/coaches"]


def sync_coaches(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    teams = Team.query.filter(Team.api_id.isnot(None)).all()

    for team in teams:
        for path_tpl in COACHES_PATHS:
            try:
                path = path_tpl.replace("{id}", team.api_id)
                raw = client.get(path, params={"id": team.api_id})
                coaches = _extract(raw)
                for c in coaches:
                    i, u, s = _upsert(c, team.id)
                    inserted += i; updated += u; skipped += s
                break
            except Exception:
                continue

    db.session.commit()
    logger.info("Coaches sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _upsert(raw: dict, team_id: int) -> tuple[int, int, int]:
    api_id = str(raw.get("id") or raw.get("coachId") or "")
    if not api_id:
        return 0, 0, 1
    c = Coach.query.filter_by(api_id=api_id).first()
    is_new = c is None
    if is_new:
        c = Coach(api_id=api_id); db.session.add(c)
    c.team_id = team_id
    c.name = raw.get("firstName", "") + " " + raw.get("lastName", "")
    c.name = c.name.strip() or raw.get("displayName") or raw.get("name") or c.name
    c.title = raw.get("position") or raw.get("title") or c.title
    c.experience = raw.get("experience") or c.experience
    return (1, 0, 0) if is_new else (0, 1, 0)


def _extract(data) -> list:
    if isinstance(data, list): return data
    for k in ["coaches", "data", "results"]:
        if isinstance(data.get(k) if isinstance(data, dict) else None, list):
            return data[k]
    return []
