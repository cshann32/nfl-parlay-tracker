"""Sync NFL seasons into the local DB."""
import logging
from typing import Any
from app.extensions import db
from app.models.season import Season
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.seasons")

SEASON_PATHS = ["/nfl-season/v1/data", "/seasons", "/v1/seasons"]


def sync_seasons(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    for path in SEASON_PATHS:
        try:
            raw = client.get(path)
            seasons_data = _extract(raw)
            break
        except Exception:
            continue
    else:
        logger.warning("Could not fetch seasons — skipping")
        return 0, 0, 0

    for item in seasons_data:
        try:
            i, u, s = _upsert_season(item)
            inserted += i; updated += u; skipped += s
        except Exception as exc:
            logger.error("Failed to upsert season", extra={"error": str(exc)}, exc_info=True)
            skipped += 1

    db.session.commit()
    logger.info("Seasons sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _upsert_season(raw: dict) -> tuple[int, int, int]:
    api_id = str(raw.get("id") or raw.get("seasonId") or "")
    year = _to_int(raw.get("year") or raw.get("season"))
    if not year:
        return 0, 0, 1
    season = Season.query.filter_by(api_id=api_id).first() if api_id else \
             Season.query.filter_by(year=year).first()
    is_new = season is None
    if is_new:
        season = Season(api_id=api_id or None); db.session.add(season)
    season.year = year
    season.season_type = raw.get("type") or raw.get("seasonType") or season.season_type
    season.name = raw.get("displayName") or raw.get("name") or season.name
    return (1, 0, 0) if is_new else (0, 1, 0)


def _extract(data: Any) -> list:
    if isinstance(data, list): return data
    for k in ["seasons", "data", "results"]:
        if isinstance(data.get(k) if isinstance(data, dict) else None, list):
            return data[k]
    return []


def _to_int(val) -> int | None:
    try: return int(val)
    except (TypeError, ValueError): return None
