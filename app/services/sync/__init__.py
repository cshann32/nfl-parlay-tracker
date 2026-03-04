"""
NFL Sync Orchestrator.
Runs all sync categories in FK-dependency order.
Each category is independently runnable.
Writes a SyncLog record with full detail.
"""
import logging
from datetime import datetime, timezone
from typing import Callable

from flask import Flask

from app.extensions import db
from app.models.sync_log import SyncLog, SyncStatus
from app.models.app_setting import AppSetting
from app.exceptions import SyncException
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync")

# Ordered by FK dependency — do not reorder
SYNC_ORDER = [
    "seasons",
    "teams",
    "coaches",
    "players",
    "games",
    "scoreboard",
    "boxscores",
    "plays",
    "stats",
    "game_stats",
    "odds",
    "espn_odds",
    "news",
    "draft",
]


def _get_client(app: Flask) -> NFLApiClient:
    return NFLApiClient(
        api_key=app.config["NFL_API_KEY"],
        primary_host=app.config["NFL_API_HOST_PRIMARY"],
        fallback_host=app.config["NFL_API_HOST_FALLBACK"],
        timeout=app.config["NFL_API_TIMEOUT"],
        max_retries=app.config["NFL_API_RETRY_COUNT"],
    )


# Categories that use their own HTTP client (ESPN free API) — no NFL_API_KEY required
_ESPN_ONLY_CATEGORIES = {
    "game_stats",
    "espn_odds",
    "espn_teams",
    "espn_roster",
    "espn_schedule",
    "espn_news",
}


def run_sync(category: str, app: Flask, triggered_by: str = "manual") -> SyncLog:
    """Run a single sync category. Returns the SyncLog record."""
    with app.app_context():
        log = SyncLog(category=category, triggered_by=triggered_by,
                      started_at=datetime.now(timezone.utc))
        db.session.add(log)
        db.session.commit()

        # ESPN-only categories don't need the RapidAPI client
        client = None
        if category not in _ESPN_ONLY_CATEGORIES:
            try:
                client = _get_client(app)
            except ValueError as exc:
                logger.error("Cannot create API client: %s", exc)
                log.status = SyncStatus.FAILED
                log.finished_at = datetime.now(timezone.utc)
                log.errors = [{"error": str(exc)}]
                db.session.commit()
                return log

        errors = []
        inserted = updated = skipped = 0

        try:
            i, u, s = _dispatch(category, client, app)
            inserted, updated, skipped = i, u, s
            log.status = SyncStatus.SUCCESS
        except SyncException as exc:
            logger.error("Sync failed: %s", exc.message, extra=exc.detail, exc_info=True)
            errors.append({"category": category, "error": exc.message, "detail": exc.detail})
            log.status = SyncStatus.FAILED
        except Exception as exc:
            logger.critical("Unexpected sync error", extra={"category": category}, exc_info=True)
            errors.append({"category": category, "error": str(exc)})
            log.status = SyncStatus.FAILED

        log.finished_at = datetime.now(timezone.utc)
        log.records_inserted = inserted
        log.records_updated = updated
        log.records_skipped = skipped
        log.errors = errors or None
        db.session.commit()

        logger.info(
            "Sync finished",
            extra={
                "category": category,
                "status": log.status.value,
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "duration_s": log.duration_seconds,
            },
        )
        return log


def run_full_sync(app: Flask, triggered_by: str = "scheduler") -> list[SyncLog]:
    """Run all sync categories in dependency order."""
    logs = []
    for category in SYNC_ORDER:
        try:
            log = run_sync(category, app, triggered_by=triggered_by)
            logs.append(log)
            if log.status == SyncStatus.FAILED:
                logger.warning(
                    "Category failed — continuing with remaining",
                    extra={"category": category},
                )
        except Exception as exc:
            logger.critical("Full sync aborted at category",
                            extra={"category": category, "error": str(exc)}, exc_info=True)
    return logs


def _dispatch(category: str, client: NFLApiClient, app: Flask) -> tuple[int, int, int]:
    """Route a category string to its sync function."""
    from .season_sync import sync_seasons
    from .teams_sync import sync_teams
    from .coaches_sync import sync_coaches
    from .players_sync import sync_players
    from .games_sync import sync_games
    from .scoreboard_sync import sync_scoreboard
    from .boxscore_sync import sync_boxscores
    from .plays_sync import sync_plays
    from .stats_sync import sync_stats
    from .espn_game_stats_sync import sync_game_stats
    from .odds_sync import sync_odds
    from .espn_odds_sync import sync_espn_odds
    from .news_sync import sync_news
    from .draft_sync import sync_draft
    # ESPN free API syncs (no API key required)
    from .espn_teams_sync import sync_espn_teams
    from .espn_roster_sync import sync_espn_roster
    from .espn_schedule_sync import sync_espn_schedule
    from .espn_news_sync import sync_espn_news

    dispatch: dict[str, Callable] = {
        # ── Paid RapidAPI syncs ──
        "seasons":    lambda: sync_seasons(client),
        "teams":      lambda: sync_teams(client),
        "coaches":    lambda: sync_coaches(client),
        "players":    lambda: sync_players(client),
        "games":      lambda: sync_games(client),
        "scoreboard": lambda: sync_scoreboard(client),
        "boxscores":  lambda: sync_boxscores(client),
        "plays":      lambda: sync_plays(client),
        "stats":      lambda: sync_stats(client),
        "odds":       lambda: sync_odds(client),
        "draft":      lambda: sync_draft(client),
        "news":       lambda: sync_news(client),
        # ── ESPN free API syncs (no key needed) ──
        "game_stats":    lambda: sync_game_stats(client),
        "espn_odds":     lambda: sync_espn_odds(client),
        "espn_teams":    lambda: sync_espn_teams(client),
        "espn_roster":   lambda: sync_espn_roster(client),
        "espn_schedule": lambda: sync_espn_schedule(client),
        "espn_news":     lambda: sync_espn_news(client),
    }

    if category not in dispatch:
        raise SyncException(
            f"Unknown sync category: {category}",
            detail={"category": category, "available": list(dispatch.keys())},
        )
    return dispatch[category]()
