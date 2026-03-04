"""
Sync NFL betting odds from ESPN's free public summary API.
No API key required — uses the same endpoint as espn_game_stats_sync.

ESPN endpoint: GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}

The response includes a "pickcenter" array with odds from DraftKings, FanDuel, etc.
Covers both pre-game lines and historical closing odds.

Targets: 2024 and 2025 season games (configurable via TARGET_SEASONS).
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from app.extensions import db
from app.models.game import Game
from app.models.odds import Odds

logger = logging.getLogger("nfl.sync.espn_odds")

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
TARGET_SEASONS = {2024, 2025}


def sync_espn_odds(client=None) -> tuple[int, int, int]:
    """
    Sync betting odds from ESPN's free API for TARGET_SEASONS games.
    `client` is accepted but unused — ESPN API is free.
    """
    inserted = updated = skipped = 0

    games = (
        Game.query
        .filter(Game.api_id.isnot(None))
        .filter(Game.season_year.in_(TARGET_SEASONS))
        .order_by(Game.season_year.desc(), Game.game_date)
        .all()
    )

    logger.info("ESPN odds sync starting", extra={"game_count": len(games)})

    for game in games:
        try:
            i, u, s = _sync_game_odds(game)
            inserted += i
            updated += u
            skipped += s
            time.sleep(0.15)  # be polite to ESPN's free API
        except Exception as exc:
            logger.warning(
                "ESPN odds sync failed for game",
                extra={"game_id": game.id, "api_id": game.api_id, "error": str(exc)},
            )
            skipped += 1

    db.session.commit()
    logger.info(
        "ESPN odds sync complete",
        extra={"inserted": inserted, "updated": updated, "skipped": skipped},
    )
    return inserted, updated, skipped


def sync_single_game_odds(game_id: int) -> tuple[int, int, int]:
    """Fetch and store ESPN odds for a single game by DB game_id."""
    game = Game.query.get(game_id)
    if not game or not game.api_id:
        raise ValueError(f"Game {game_id} not found or has no ESPN event ID")

    i, u, s = _sync_game_odds(game)
    db.session.commit()
    logger.info(
        "Single game odds synced",
        extra={"game_id": game_id, "inserted": i, "updated": u, "skipped": s},
    )
    return i, u, s


def _sync_game_odds(game: Game) -> tuple[int, int, int]:
    # Strip "espn_" prefix — our DB stores "espn_401671789" but ESPN expects "401671789"
    raw_event_id = game.api_id.removeprefix("espn_") if game.api_id else game.api_id

    resp = requests.get(
        ESPN_SUMMARY,
        params={"event": raw_event_id},
        timeout=10,
        headers={"User-Agent": "NFL-Parlay-Tracker/1.0"},
    )
    resp.raise_for_status()
    data = resp.json()

    pickcenter = data.get("pickcenter") or []
    if not pickcenter:
        logger.debug("No pickcenter data", extra={"game_id": game.id, "api_id": game.api_id})
        return 0, 0, 1  # skipped

    inserted = updated = skipped = 0
    for entry in pickcenter:
        # Skip $ref-only entries (unresolved links)
        if "$ref" in entry and len(entry) == 1:
            skipped += 1
            continue
        i, u, s = _upsert_odds(entry, game.id)
        inserted += i
        updated += u
        skipped += s

    return inserted, updated, skipped


def _upsert_odds(raw: dict, game_id: int) -> tuple[int, int, int]:
    provider = raw.get("provider") or {}
    source = provider.get("name") or "ESPN"
    market_type = "general"

    existing = Odds.query.filter_by(
        game_id=game_id, source=source, market_type=market_type
    ).first()
    is_new = existing is None

    if is_new:
        existing = Odds(game_id=game_id, source=source, market_type=market_type)
        db.session.add(existing)

    away_odds = raw.get("awayTeamOdds") or {}
    home_odds = raw.get("homeTeamOdds") or {}

    # Spread — ESPN "spread" is always the magnitude; sign flips based on who's favored
    spread_val = _to_float(raw.get("spread"))
    if spread_val is not None:
        if home_odds.get("favorite"):
            existing.home_spread = -spread_val
            existing.away_spread = spread_val
        else:
            existing.away_spread = -spread_val
            existing.home_spread = spread_val
    else:
        # Fallback: parse "details" string e.g. "-3.5"
        details = str(raw.get("details") or "")
        parsed = _to_float(details.replace("PK", "0"))
        if parsed is not None:
            existing.home_spread = parsed
            existing.away_spread = -parsed

    # Moneyline
    existing.home_moneyline = _to_int(home_odds.get("moneyLine"))
    existing.away_moneyline = _to_int(away_odds.get("moneyLine"))

    # Spread juice (odds on the spread bet)
    existing.spread_juice_home = _to_int(home_odds.get("spreadOdds"))
    existing.spread_juice_away = _to_int(away_odds.get("spreadOdds"))

    # Over/Under
    existing.over_under = _to_float(raw.get("overUnder"))

    existing.synced_at = datetime.now(timezone.utc)

    return (1, 0, 0) if is_new else (0, 1, 0)


def _to_int(val: Any) -> int | None:
    try:
        return int(float(str(val)))
    except (TypeError, ValueError):
        return None


def _to_float(val: Any) -> float | None:
    try:
        return float(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return None
