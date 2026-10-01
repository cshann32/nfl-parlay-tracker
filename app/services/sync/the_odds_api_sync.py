"""
Sync live NFL odds from The Odds API into the local `odds` table.
Matches events to DB games by team names + kickoff window.

Credit cost: 3 credits per sync (h2h + spreads + totals, us region).
Free plan: 500 credits/month → ~166 syncs/month max.
A 4-hour cooldown is enforced to prevent accidental quota exhaustion.
"""
import logging
from datetime import datetime, timezone, timedelta

from app.extensions import db
from app.models.game import Game
from app.models.odds import Odds

logger = logging.getLogger("nfl.sync.the_odds_api")

_CREDITS_PER_SYNC = 3  # h2h + spreads + totals × 1 region


def _cooldown_hours() -> int:
    from app.models.app_setting import AppSetting
    return int(AppSetting.get("the_odds_api_cooldown_hours", "4"))


def _minutes_since_last_sync() -> float | None:
    """Return minutes elapsed since the last successful the_odds_api sync."""
    from app.models.sync_log import SyncLog, SyncStatus
    last = (
        SyncLog.query
        .filter_by(category="the_odds_api", status=SyncStatus.SUCCESS)
        .order_by(SyncLog.finished_at.desc())
        .first()
    )
    if not last or not last.finished_at:
        return None
    elapsed = datetime.now(timezone.utc) - last.finished_at
    return elapsed.total_seconds() / 60


def sync_the_odds_api(api_key: str) -> tuple[int, int, int]:
    """Fetch current NFL odds and upsert into the odds table.

    Returns (inserted, updated, skipped).
    """
    from app.services.the_odds_api import (
        OddsApiClient, _build_team_map, _find_team_id, _find_game, _parse_bookmaker,
    )

    if not api_key:
        logger.warning("THE_ODDS_API_KEY not set — skipping the-odds-api sync")
        return 0, 0, 0

    # Enforce cooldown to protect free-plan credits (500/month, 3 per call)
    cooldown = _cooldown_hours()
    mins_ago = _minutes_since_last_sync()
    cooldown_mins = cooldown * 60
    if mins_ago is not None and mins_ago < cooldown_mins:
        remaining = cooldown_mins - mins_ago
        logger.warning(
            "The Odds API cooldown active — last sync was %.0f min ago, "
            "next allowed in %.0f min (cooldown=%dh, cost=%d credits/call)",
            mins_ago, remaining, cooldown, _CREDITS_PER_SYNC,
        )
        raise RuntimeError(
            f"Odds API sync blocked: last run {mins_ago:.0f} min ago. "
            f"Cooldown is {cooldown}h to protect your 500-credit free plan. "
            f"Next sync allowed in {remaining:.0f} min."
        )

    logger.info(
        "Starting The Odds API sync (cost: %d credits, free plan: 500/month)",
        _CREDITS_PER_SYNC,
    )
    client = OddsApiClient(api_key)
    events = client.get_odds()

    team_map = _build_team_map()

    # Only load games within a relevant window — the API returns upcoming games only
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=3)
    window_end   = now + timedelta(days=14)
    games = Game.query.filter(
        Game.game_date >= window_start,
        Game.game_date <= window_end,
    ).all()
    games_by_teams: dict = {}
    for g in games:
        games_by_teams.setdefault((g.home_team_id, g.away_team_id), []).append(g)

    # Pre-load existing odds for these games to avoid N+1 inside the bookmaker loop
    relevant_ids = {g.id for gs in games_by_teams.values() for g in gs}
    existing_odds: dict[tuple, Odds] = {}
    if relevant_ids:
        for o in Odds.query.filter(Odds.game_id.in_(relevant_ids)).all():
            existing_odds[(o.game_id, o.source)] = o

    inserted = updated = skipped = 0
    synced_at = datetime.now(timezone.utc)

    for event in events:
        home_name = event.get("home_team", "")
        away_name = event.get("away_team", "")
        commence_str = event.get("commence_time", "")

        home_id = _find_team_id(home_name, team_map)
        away_id = _find_team_id(away_name, team_map)
        if not home_id or not away_id:
            logger.debug("Team not found in DB: '%s' vs '%s'", away_name, home_name)
            skipped += 1
            continue

        try:
            commence_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            skipped += 1
            continue

        game = _find_game(home_id, away_id, commence_dt, games_by_teams)
        if not game:
            game = _create_game_stub(home_id, away_id, commence_dt, games_by_teams)
            logger.debug("Created game stub: %s @ %s on %s", away_name, home_name, commence_str[:10])

        for bookmaker in event.get("bookmakers", []):
            odds_data = _parse_bookmaker(home_name, bookmaker)
            odds_data["synced_at"] = synced_at
            source = bookmaker.get("title")
            existing = existing_odds.get((game.id, source))
            if existing:
                for k, v in odds_data.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                new_row = Odds(game_id=game.id, **odds_data)
                db.session.add(new_row)
                existing_odds[(game.id, source)] = new_row
                inserted += 1

    db.session.commit()
    logger.info(
        "The Odds API sync complete — inserted=%d updated=%d skipped=%d",
        inserted, updated, skipped,
    )
    return inserted, updated, skipped


def _estimate_nfl_week(game_dt: datetime, season_year: int) -> int | None:
    """Estimate NFL regular-season week number from a game's kickoff datetime."""
    import calendar as _cal
    month_cal = _cal.monthcalendar(season_year, 9)
    labor_day = next(w[_cal.MONDAY] for w in month_cal if w[_cal.MONDAY] != 0)
    # Kickoff night is Thursday after Labor Day (Monday + 3 days)
    kickoff = datetime(season_year, 9, labor_day + 3, tzinfo=timezone.utc)
    if game_dt < kickoff:
        return None  # preseason
    week = (game_dt - kickoff).days // 7 + 1
    return min(week, 18)


def _create_game_stub(home_id: int, away_id: int, commence_dt: datetime,
                      games_by_teams: dict) -> Game:
    """Insert a minimal Game record from Odds API event data and return it."""
    season_year = commence_dt.year
    week = _estimate_nfl_week(commence_dt, season_year)
    game = Game(
        home_team_id=home_id,
        away_team_id=away_id,
        game_date=commence_dt,
        season_year=season_year,
        week=week,
        status="Scheduled",
        season_type="Regular Season",
    )
    db.session.add(game)
    db.session.flush()  # get game.id before inserting odds
    games_by_teams.setdefault((home_id, away_id), []).append(game)
    return game
