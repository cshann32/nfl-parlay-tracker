"""Sync NFL betting odds into the local DB."""
import logging
from typing import Any
from datetime import datetime, timezone
from app.extensions import db
from app.models.odds import Odds, OddsHistory
from app.models.game import Game
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.odds")

ODDS_PATHS = ["/nfl-betting-odds/v1/data", "/odds", "/v1/odds"]
GAME_ODDS_PATHS = ["/nfl-event-odds/v1/data", "/events/{id}/odds"]


def sync_odds(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    games = Game.query.filter(Game.api_id.isnot(None)).all()
    logger.info("Syncing odds for games", extra={"game_count": len(games)})

    for game in games:
        try:
            i, u, s = _sync_game_odds(client, game)
            inserted += i; updated += u; skipped += s
        except Exception as exc:
            logger.error("Failed odds sync for game",
                         extra={"game_api_id": game.api_id, "error": str(exc)})
            skipped += 1

    db.session.commit()
    logger.info("Odds sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _sync_game_odds(client: NFLApiClient, game: Game) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    for path_tpl in GAME_ODDS_PATHS:
        try:
            path = path_tpl.replace("{id}", game.api_id)
            raw = client.get(path, params={"id": game.api_id})
            odds_list = _extract_odds(raw)
            for raw_odds in odds_list:
                i, u, s = _upsert_odds(raw_odds, game.id)
                inserted += i; updated += u; skipped += s
            break
        except Exception:
            continue
    return inserted, updated, skipped


def _upsert_odds(raw: dict, game_id: int) -> tuple[int, int, int]:
    source = raw.get("provider", {}).get("name") or raw.get("source") or raw.get("bookmaker") or "unknown"
    market = raw.get("type") or raw.get("marketType") or "general"

    existing = Odds.query.filter_by(game_id=game_id, source=source, market_type=market).first()
    is_new = existing is None
    if is_new:
        existing = Odds(game_id=game_id, source=source, market_type=market)
        db.session.add(existing)

    existing.home_moneyline = _to_int(raw.get("homeMoneyline") or raw.get("moneylineHome"))
    existing.away_moneyline = _to_int(raw.get("awayMoneyline") or raw.get("moneylineAway"))
    existing.home_spread = _to_float(raw.get("homeSpread") or raw.get("spread"))
    existing.away_spread = _to_float(raw.get("awaySpread"))
    existing.over_under = _to_float(raw.get("overUnder") or raw.get("total"))
    existing.synced_at = datetime.now(timezone.utc)

    return (1, 0, 0) if is_new else (0, 1, 0)


def _extract_odds(data: Any) -> list:
    if isinstance(data, list): return data
    for k in ["items", "odds", "data", "results"]:
        if isinstance(data.get(k) if isinstance(data, dict) else None, list):
            return data[k]
    return []


def _to_int(val) -> int | None:
    try: return int(val)
    except (TypeError, ValueError): return None


def _to_float(val) -> float | None:
    try: return float(val)
    except (TypeError, ValueError): return None
