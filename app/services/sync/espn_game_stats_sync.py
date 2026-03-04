"""
Sync per-game player stats using ESPN's free public summary API.
No API key required — uses site.api.espn.com directly.

ESPN endpoint: GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}
"""
import logging
import time
from typing import Any

import requests

from app.extensions import db
from app.models.game import Game
from app.models.player import Player
from app.models.stat import PlayerStat

logger = logging.getLogger("nfl.sync.game_stats")

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

# Map ESPN category names → our stat_category values
CATEGORY_MAP = {
    "passing":        "passing",
    "rushing":        "rushing",
    "receiving":      "receiving",
    "fumbles":        "fumbles",
    "defensive":      "defensive",
    "defensivetotals": "defensive",
    "interceptions":  "interceptions",
    "kickreturns":    "kickreturns",
    "puntreturns":    "puntreturns",
    "kicking":        "kicking",
    "punting":        "punting",
}

# Labels that are composite (e.g. "C/ATT") — split into separate stats
COMPOSITE_SPLITS = {
    "C/ATT": ("CMP", "ATT"),
    "SACKS": ("SACK", "SYL"),   # "2-15" → sacks, yards lost
    "3DW-3DA": None,            # skip entirely
}


def sync_game_stats(client=None) -> tuple[int, int, int]:
    """
    Sync per-game player stats for all completed games.
    `client` is accepted but unused — ESPN API is free.
    """
    inserted = updated = skipped = 0

    games = (Game.query
             .filter(Game.api_id.isnot(None))
             .filter(Game.status.ilike("%final%"))
             .order_by(Game.game_date.desc())
             .all())

    logger.info("ESPN game stats sync starting", extra={"game_count": len(games)})

    # Build player lookup: api_id → db id, and name → db id (fallback)
    all_players = Player.query.with_entities(Player.id, Player.api_id, Player.name).all()
    by_api_id = {p.api_id: p.id for p in all_players if p.api_id}
    by_name   = {p.name.lower(): p.id for p in all_players if p.name}

    for game in games:
        try:
            i, u, s = _sync_one_game(game, by_api_id, by_name)
            inserted += i
            updated  += u
            skipped  += s
            time.sleep(0.15)  # be polite to ESPN's free API
        except Exception as exc:
            logger.warning("Game stats sync failed",
                           extra={"game_id": game.id, "api_id": game.api_id, "error": str(exc)})
            skipped += 1

    db.session.commit()
    logger.info("ESPN game stats sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _sync_one_game(game: Game, by_api_id: dict, by_name: dict) -> tuple[int, int, int]:
    inserted = updated = skipped = 0

    # Strip "espn_" prefix — our DB stores "espn_401671789" but ESPN expects "401671789"
    raw_event_id = game.api_id.removeprefix("espn_") if game.api_id else game.api_id
    resp = requests.get(ESPN_SUMMARY, params={"event": raw_event_id}, timeout=10,
                        headers={"User-Agent": "NFL-Parlay-Tracker/1.0"})
    resp.raise_for_status()
    data = resp.json()

    players_data = _safe(data, ["boxscore", "players"]) or []

    for team_block in players_data:
        for stat_group in team_block.get("statistics", []):
            raw_cat = (stat_group.get("name") or "").lower()
            category = CATEGORY_MAP.get(raw_cat)
            if not category:
                continue

            labels = stat_group.get("labels", [])
            athletes = stat_group.get("athletes", [])

            for athlete_entry in athletes:
                athlete = athlete_entry.get("athlete", {})
                espn_id = str(athlete.get("id") or "")
                name    = (athlete.get("displayName") or athlete.get("fullName") or "").strip()

                # ESPN returns raw numeric IDs; our DB prefixes them with "espn_"
                player_db_id = by_api_id.get(f"espn_{espn_id}") or by_name.get(name.lower())
                if not player_db_id:
                    skipped += 1
                    continue

                stats_vals = athlete_entry.get("stats", [])
                for label, raw_val in zip(labels, stats_vals):
                    label_up = label.upper()

                    # Handle composites
                    if label_up in COMPOSITE_SPLITS:
                        split = COMPOSITE_SPLITS[label_up]
                        if split is None:
                            continue
                        parts = str(raw_val).split("-")
                        for key, part in zip(split, parts):
                            val = _to_float(part)
                            if val is not None:
                                i, u, s = _upsert(player_db_id, game.id, category, key, val)
                                inserted += i; updated += u; skipped += s
                        continue

                    val = _to_float(raw_val)
                    if val is None:
                        continue

                    i, u, s = _upsert(player_db_id, game.id, category, label_up, val)
                    inserted += i; updated += u; skipped += s

    return inserted, updated, skipped


def sync_single_game(game_id: int) -> tuple[int, int, int]:
    """
    Fetch and store ESPN game stats for a single game by DB game_id.
    Used by the per-game "Fetch Stats" button — no API key needed.
    """
    game = Game.query.get(game_id)
    if not game or not game.api_id:
        raise ValueError(f"Game {game_id} not found or has no ESPN event ID")

    all_players = Player.query.with_entities(Player.id, Player.api_id, Player.name).all()
    by_api_id = {p.api_id: p.id for p in all_players if p.api_id}
    by_name   = {p.name.lower(): p.id for p in all_players if p.name}

    i, u, s = _sync_one_game(game, by_api_id, by_name)
    db.session.commit()
    logger.info("Single game stats synced",
                extra={"game_id": game_id, "inserted": i, "updated": u, "skipped": s})
    return i, u, s


def _upsert(player_id: int, game_id: int, category: str, stat_type: str,
            value: float) -> tuple[int, int, int]:
    existing = PlayerStat.query.filter_by(
        player_id=player_id, game_id=game_id,
        stat_category=category, stat_type=stat_type
    ).first()
    if existing:
        existing.value = value
        return 0, 1, 0
    db.session.add(PlayerStat(
        player_id=player_id, game_id=game_id,
        stat_category=category, stat_type=stat_type, value=value,
    ))
    return 1, 0, 0


def _safe(d: Any, path: list) -> Any:
    cur = d
    for key in path:
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _to_float(val: Any) -> float | None:
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None
