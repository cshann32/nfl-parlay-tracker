"""Sync NFL boxscores and play-by-play data."""
import logging
from datetime import datetime, timezone
from typing import Any
from app.extensions import db
from app.models.boxscore import Boxscore
from app.models.play import Play
from app.models.game import Game
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.boxscore")

BOXSCORE_PATHS = ["/nfl-boxscore/v1/data", "/events/{id}/boxscore", "/games/{id}/boxscore"]


def sync_boxscores(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    # Only sync completed games
    games = Game.query.filter(Game.api_id.isnot(None),
                              Game.status.in_(["Final", "STATUS_FINAL", "Completed"])).all()
    logger.info("Syncing boxscores", extra={"game_count": len(games)})

    for game in games:
        try:
            i, u, s = _sync_game_boxscore(client, game)
            inserted += i; updated += u; skipped += s
        except Exception as exc:
            logger.error("Boxscore sync failed",
                         extra={"game_api_id": game.api_id, "error": str(exc)})
            skipped += 1

    db.session.commit()
    logger.info("Boxscore sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _sync_game_boxscore(client: NFLApiClient, game: Game) -> tuple[int, int, int]:
    for path_tpl in BOXSCORE_PATHS:
        try:
            path = path_tpl.replace("{id}", game.api_id)
            raw = client.get(path, params={"id": game.api_id})
            bs = Boxscore.query.filter_by(game_id=game.id).first()
            is_new = bs is None
            if is_new:
                bs = Boxscore(game_id=game.id)
                db.session.add(bs)
            bs.raw_data = raw
            bs.synced_at = datetime.now(timezone.utc)
            _parse_linescores(bs, raw)
            return (1, 0, 0) if is_new else (0, 1, 0)
        except Exception:
            continue
    return 0, 0, 1


def _parse_linescores(bs: Boxscore, raw: dict) -> None:
    teams = _safe(raw, ["teams"]) or []
    for team_data in teams:
        is_home = str(_safe(team_data, ["homeAway"]) or "").lower() == "home"
        linescores = _safe(team_data, ["statistics"]) or _safe(team_data, ["linescores"]) or []
        periods = []
        for item in linescores:
            periods.append(_to_int(item.get("value") or item.get("score") or 0))
        if is_home:
            bs.home_q1, bs.home_q2, bs.home_q3, bs.home_q4 = _pad(periods)
            bs.home_ot = periods[4] if len(periods) > 4 else None
        else:
            bs.away_q1, bs.away_q2, bs.away_q3, bs.away_q4 = _pad(periods)
            bs.away_ot = periods[4] if len(periods) > 4 else None


def _safe(d, path):
    cur = d
    for key in path:
        try: cur = cur[key]
        except (KeyError, IndexError, TypeError): return None
    return cur


def _pad(lst: list, length=4):
    padded = list(lst) + [None] * length
    return padded[0], padded[1], padded[2], padded[3]


def _to_int(val) -> int | None:
    try: return int(val)
    except (TypeError, ValueError): return None
