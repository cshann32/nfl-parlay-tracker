"""Sync NFL play-by-play data."""
import logging
from typing import Any
from app.extensions import db
from app.models.play import Play
from app.models.game import Game
from app.models.team import Team
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.plays")

PLAYS_PATHS = ["/nfl-play-by-play/v1/data", "/events/{id}/playbyplay", "/games/{id}/plays"]


def sync_plays(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    games = Game.query.filter(Game.api_id.isnot(None),
                              Game.status.in_(["Final", "STATUS_FINAL", "Completed"])).all()
    team_cache = {t.api_id: t.id for t in Team.query.all() if t.api_id}

    for game in games:
        # Skip if already has plays
        if Play.query.filter_by(game_id=game.id).first():
            skipped += 1
            continue
        try:
            i, u, s = _sync_game_plays(client, game, team_cache)
            inserted += i; updated += u; skipped += s
        except Exception as exc:
            logger.error("Plays sync failed",
                         extra={"game_api_id": game.api_id, "error": str(exc)})
            skipped += 1

    db.session.commit()
    logger.info("Plays sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _sync_game_plays(client: NFLApiClient, game: Game, team_cache: dict) -> tuple[int, int, int]:
    inserted = 0
    for path_tpl in PLAYS_PATHS:
        try:
            path = path_tpl.replace("{id}", game.api_id)
            raw = client.get(path, params={"id": game.api_id})
            plays_data = _extract_plays(raw)
            for seq, raw_play in enumerate(plays_data):
                play = _build_play(raw_play, game.id, seq, team_cache)
                db.session.add(play)
                inserted += 1
            return inserted, 0, 0
        except Exception:
            continue
    return 0, 0, 1


def _build_play(raw: dict, game_id: int, seq: int, team_cache: dict) -> Play:
    team_api_id = str(_safe(raw, ["team", "id"]) or "")
    return Play(
        game_id=game_id,
        team_id=team_cache.get(team_api_id),
        sequence=raw.get("sequenceNumber") or seq,
        quarter=_to_int(_safe(raw, ["period", "number"]) or raw.get("period")),
        clock=_safe(raw, ["clock", "displayValue"]) or raw.get("clock"),
        play_type=_safe(raw, ["type", "text"]) or raw.get("playType"),
        description=raw.get("text") or raw.get("description"),
        yards_gained=_to_int(raw.get("yardsGained") or raw.get("yards")),
        down=_to_int(raw.get("down")),
        distance=_to_int(raw.get("distance")),
        is_scoring=bool(raw.get("scoringPlay")),
        score_type=raw.get("scoreType"),
    )


def _extract_plays(data: Any) -> list:
    if isinstance(data, list): return data
    for k in ["plays", "playByPlay", "data", "results"]:
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
