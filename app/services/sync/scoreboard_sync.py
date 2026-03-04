"""Sync NFL scoreboard data."""
import logging
from datetime import datetime, timezone
from app.extensions import db
from app.models.scoreboard import Scoreboard
from app.models.game import Game
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.scoreboard")

SCOREBOARD_PATHS = ["/nfl-scoreboard/v1/data", "/scoreboard", "/v1/scoreboard"]


def sync_scoreboard(client: NFLApiClient, week: int | None = None,
                    year: int | None = None) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    params = {}
    if week: params["week"] = week
    if year: params["year"] = year

    for path in SCOREBOARD_PATHS:
        try:
            raw = client.get(path, params=params)
            events = _extract(raw)
            for event in events:
                i, u, s = _upsert(event)
                inserted += i; updated += u; skipped += s
            break
        except Exception:
            continue

    db.session.commit()
    logger.info("Scoreboard sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _upsert(raw: dict) -> tuple[int, int, int]:
    game_api_id = str(raw.get("id") or raw.get("eventId") or "")
    if not game_api_id:
        return 0, 0, 1
    game = Game.query.filter_by(api_id=game_api_id).first()
    if not game:
        return 0, 0, 1

    sb = Scoreboard.query.filter_by(game_id=game.id).first()
    is_new = sb is None
    if is_new:
        sb = Scoreboard(game_id=game.id); db.session.add(sb)
    sb.raw_data = raw
    sb.synced_at = datetime.now(timezone.utc)

    # Parse scores
    comps = _safe(raw, ["competitions", 0, "competitors"]) or []
    for comp in comps:
        if str(comp.get("homeAway", "")).lower() == "home":
            sb.home_score = _to_int(comp.get("score"))
        else:
            sb.away_score = _to_int(comp.get("score"))
    sb.period = _to_int(_safe(raw, ["status", "period"]))
    sb.time_remaining = _safe(raw, ["status", "displayClock"])

    return (1, 0, 0) if is_new else (0, 1, 0)


def _extract(data) -> list:
    if isinstance(data, list): return data
    for k in ["events", "games", "data", "results"]:
        if isinstance(data.get(k) if isinstance(data, dict) else None, list):
            return data[k]
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
