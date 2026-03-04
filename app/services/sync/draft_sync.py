"""Sync NFL draft data."""
import logging
from app.extensions import db
from app.models.draft import Draft
from app.models.team import Team
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.draft")

DRAFT_PATHS = ["/nfl-draft/v1/data", "/draft", "/v1/draft"]


def sync_draft(client: NFLApiClient, year: int | None = None) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    params = {"year": year} if year else {}
    team_cache = {t.api_id: t.id for t in Team.query.all() if t.api_id}

    for path in DRAFT_PATHS:
        try:
            raw = client.get(path, params=params)
            picks = _extract(raw)
            for pick in picks:
                i, u, s = _upsert(pick, team_cache)
                inserted += i; updated += u; skipped += s
            break
        except Exception:
            continue

    db.session.commit()
    logger.info("Draft sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _upsert(raw: dict, team_cache: dict) -> tuple[int, int, int]:
    api_id = str(raw.get("id") or raw.get("pickId") or "")
    if not api_id:
        return 0, 0, 1
    d = Draft.query.filter_by(api_id=api_id).first()
    is_new = d is None
    if is_new:
        d = Draft(api_id=api_id); db.session.add(d)
    d.year = _to_int(raw.get("year"))
    d.round = _to_int(raw.get("round") or _safe(raw, ["roundNumber"]))
    d.pick = _to_int(raw.get("pick") or raw.get("pickNumber"))
    d.overall_pick = _to_int(raw.get("overallPick") or raw.get("overall"))
    team_api_id = str(_safe(raw, ["team", "id"]) or "")
    d.team_id = team_cache.get(team_api_id)
    d.player_name = _safe(raw, ["athlete", "displayName"]) or raw.get("playerName")
    d.position = _safe(raw, ["athlete", "position", "abbreviation"]) or raw.get("position")
    d.college = _safe(raw, ["athlete", "college", "name"]) or raw.get("college")
    return (1, 0, 0) if is_new else (0, 1, 0)


def _extract(data) -> list:
    if isinstance(data, list): return data
    for k in ["picks", "rounds", "athletes", "data", "results"]:
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, list): return v
    return []


def _safe(d, path):
    cur = d
    for key in path:
        try: cur = cur[key]
        except (KeyError, IndexError, TypeError): return None
    return cur


def _to_int(val) -> int | None:
    try: return int(val)
    except (TypeError, ValueError): return None
