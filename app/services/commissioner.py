"""
The Commissioner — automated database integrity, health, and cleanup service.

Behavior:
  - Runs every check, immediately applies safe fixes, logs everything.
  - Issues that require human action are surfaced as warnings or errors with
    a clear recommended action — The Commissioner never guesses on those.
  - A full run record is stored in AppSetting("commissioner_last_run") so the
    admin page always shows what happened most recently.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Literal

from app.extensions import db
from app.models.app_setting import AppSetting

logger = logging.getLogger("nfl.commissioner")

Status = Literal["fixed", "clean", "warning", "error"]


@dataclass
class CheckResult:
    key: str
    name: str
    description: str
    status: Status = "clean"
    found: int = 0           # issues found before any fix
    fixed: int = 0           # rows auto-fixed
    detail: list[dict] = field(default_factory=list)
    human_action: str = ""   # what to do when status is warning/error
    fix_error: str = ""      # set if the auto-fix itself failed


# ── Config helpers ─────────────────────────────────────────────────────────────

def _cfg(key: str, default: str) -> str:
    return AppSetting.get(f"commissioner_{key}", default)

def _cfg_int(key: str, default: int) -> int:
    return int(_cfg(key, str(default)))

def seed_settings() -> None:
    defaults = [
        ("commissioner_stuck_hours",     "24",    "Hours after game is Final before pending legs are flagged"),
        ("commissioner_odds_stale_hours","48",    "Hours before upcoming-game odds are flagged as stale"),
        ("commissioner_score_max",       "100",   "Max believable combined score — higher scores are flagged"),
    ]
    created = 0
    for key, value, desc in defaults:
        if not AppSetting.query.filter_by(key=key).first():
            db.session.add(AppSetting(key=key, value=value, description=desc))
            created += 1
    if created:
        db.session.commit()


# ── Shared auto-fix wrapper ────────────────────────────────────────────────────

def _auto_fix(r: CheckResult, fix_fn, name: str) -> CheckResult:
    """Run fix_fn(), commit, and populate r.fixed/status/fix_error."""
    try:
        r.fixed = fix_fn()
        db.session.commit()
        r.status = "fixed"
        logger.info("[Commissioner] %s — fixed %d rows", name, r.fixed)
    except Exception as exc:
        db.session.rollback()
        r.status = "error"
        r.fix_error = str(exc)
        logger.error("[Commissioner] %s fix failed: %s", name, exc)
    return r


# ── Auto-fix checks (Commissioner handles these fully) ─────────────────────────

def _check_and_fix_orphaned_stats() -> CheckResult:
    from sqlalchemy import text
    r = CheckResult(
        key="orphaned_stats",
        name="Orphaned Player Stats",
        description="Stat rows referencing deleted games or players",
    )
    bad_game = db.session.execute(text("""
        SELECT COUNT(*) FROM player_stats ps
        WHERE ps.game_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM games g WHERE g.id = ps.game_id)
    """)).scalar()
    bad_player = db.session.execute(text("""
        SELECT COUNT(*) FROM player_stats ps
        WHERE NOT EXISTS (SELECT 1 FROM players p WHERE p.id = ps.player_id)
    """)).scalar()
    r.found = bad_game + bad_player
    if r.found == 0:
        return r

    def _fix():
        d1 = db.session.execute(text("""
            DELETE FROM player_stats
            WHERE game_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM games g WHERE g.id = player_stats.game_id)
        """)).rowcount
        d2 = db.session.execute(text("""
            DELETE FROM player_stats
            WHERE NOT EXISTS (SELECT 1 FROM players p WHERE p.id = player_stats.player_id)
        """)).rowcount
        return d1 + d2

    return _auto_fix(r, _fix, "Orphaned stats")


def _check_and_fix_orphaned_odds() -> CheckResult:
    from sqlalchemy import text
    r = CheckResult(
        key="orphaned_odds",
        name="Orphaned Odds",
        description="Odds rows referencing deleted games",
    )
    r.found = db.session.execute(text("""
        SELECT COUNT(*) FROM odds o
        WHERE NOT EXISTS (SELECT 1 FROM games g WHERE g.id = o.game_id)
    """)).scalar()
    if r.found == 0:
        return r
    return _auto_fix(r,
        lambda: db.session.execute(text(
            "DELETE FROM odds WHERE NOT EXISTS (SELECT 1 FROM games g WHERE g.id = odds.game_id)"
        )).rowcount,
        "Orphaned odds")


def _check_and_fix_duplicate_games() -> CheckResult:
    from sqlalchemy import text

    r = CheckResult(
        key="duplicate_games",
        name="Duplicate Games",
        description="Multiple records for the same matchup — merges child records into the canonical game",
    )
    groups = db.session.execute(text("""
        SELECT array_agg(id ORDER BY id) AS ids
        FROM games
        WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL
        GROUP BY home_team_id, away_team_id, season_year, week
        HAVING COUNT(*) > 1
    """)).fetchall()
    r.found = sum(len(g[0]) - 1 for g in groups)  # extra copies beyond the survivor
    if r.found == 0:
        return r

    deleted = 0
    try:
        for (ids,) in groups:
            # Survivor = game with the most stats; fall back to lowest id
            stat_row = db.session.execute(text("""
                SELECT game_id FROM player_stats
                WHERE game_id = ANY(:ids)
                GROUP BY game_id ORDER BY COUNT(*) DESC LIMIT 1
            """), {"ids": ids}).fetchone()
            survivor = stat_row[0] if stat_row else ids[0]
            losers = [i for i in ids if i != survivor]

            for lid in losers:
                # Delete loser's stats that would conflict with survivor's (unique constraint)
                db.session.execute(text("""
                    DELETE FROM player_stats
                    WHERE game_id = :lid
                      AND (player_id, stat_category, stat_type) IN (
                          SELECT player_id, stat_category, stat_type
                          FROM player_stats WHERE game_id = :sid
                      )
                """), {"sid": survivor, "lid": lid})
                db.session.execute(text("""
                    DELETE FROM team_stats
                    WHERE game_id = :lid
                      AND (team_id, stat_category, stat_type) IN (
                          SELECT team_id, stat_category, stat_type
                          FROM team_stats WHERE game_id = :sid
                      )
                """), {"sid": survivor, "lid": lid})
                # Reassign remaining child rows to survivor
                for child_tbl, child_col in [
                    ("player_stats", "game_id"),
                    ("team_stats",   "game_id"),
                    ("odds",         "game_id"),
                    ("plays",        "game_id"),
                ]:
                    db.session.execute(text(
                        f"UPDATE {child_tbl} SET {child_col}=:sid WHERE {child_col}=:lid"
                    ), {"sid": survivor, "lid": lid})
                db.session.execute(text("DELETE FROM boxscores WHERE game_id=:lid"), {"lid": lid})
                db.session.execute(text("DELETE FROM games WHERE id=:lid"), {"lid": lid})
                deleted += 1

            db.session.commit()

        r.fixed = deleted
        r.status = "fixed"
        logger.info("[Commissioner] Duplicate games — merged and removed %d extra records", deleted)
    except Exception as exc:
        db.session.rollback()
        r.status = "error"
        r.fix_error = str(exc)
        logger.error("[Commissioner] Duplicate game fix failed: %s", exc)
    return r


def _check_and_fix_duplicate_players() -> CheckResult:
    """Players sharing the same name and team — reassigns stats to the ESPN-linked record."""
    from sqlalchemy import text

    r = CheckResult(
        key="duplicate_players",
        name="Duplicate Players",
        description="Multiple player records with the same name and team — keeps the ESPN-linked one",
    )
    groups = db.session.execute(text("""
        SELECT array_agg(id ORDER BY
            CASE WHEN api_id LIKE 'espn_%' THEN 0 ELSE 1 END, id) AS ids
        FROM players
        GROUP BY name, team_id
        HAVING COUNT(*) > 1
    """)).fetchall()
    r.found = sum(len(g[0]) - 1 for g in groups)
    if r.found == 0:
        return r

    deleted = 0
    try:
        for (ids,) in groups:
            survivor, losers = ids[0], ids[1:]
            for lid in losers:
                for tbl, col in [("player_stats", "player_id"), ("injuries", "player_id"),
                                  ("depth_charts", "player_id")]:
                    db.session.execute(text(
                        f"UPDATE {tbl} SET {col}=:sid WHERE {col}=:lid"
                    ), {"sid": survivor, "lid": lid})
                db.session.execute(text("DELETE FROM players WHERE id=:lid"), {"lid": lid})
                deleted += 1
        db.session.commit()
        r.fixed = deleted
        r.status = "fixed"
        logger.info("[Commissioner] Duplicate players — merged and removed %d records", deleted)
    except Exception as exc:
        db.session.rollback()
        r.status = "error"
        r.fix_error = str(exc)
        logger.error("[Commissioner] Duplicate player fix failed: %s", exc)
    return r


def _check_and_fix_duplicate_odds() -> CheckResult:
    """Odds rows with the same (game_id, source, market_type) — keeps the most recently synced."""
    from sqlalchemy import text

    r = CheckResult(
        key="duplicate_odds",
        name="Duplicate Odds Rows",
        description="Multiple odds rows per game/source/market — keeps the freshest one",
    )
    count = db.session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT game_id, COALESCE(source,''), COALESCE(market_type,'')
            FROM odds
            GROUP BY game_id, COALESCE(source,''), COALESCE(market_type,'')
            HAVING COUNT(*) > 1
        ) x
    """)).scalar()
    r.found = count
    if r.found == 0:
        return r

    try:
        result = db.session.execute(text("""
            DELETE FROM odds
            WHERE id NOT IN (
                SELECT DISTINCT ON (game_id, COALESCE(source,''), COALESCE(market_type,'')) id
                FROM odds
                ORDER BY game_id, COALESCE(source,''), COALESCE(market_type,''),
                         synced_at DESC NULLS LAST
            )
        """))
        db.session.commit()
        r.fixed = result.rowcount
        r.status = "fixed"
        logger.info("[Commissioner] Duplicate odds — deleted %d stale rows", r.fixed)
    except Exception as exc:
        db.session.rollback()
        r.status = "error"
        r.fix_error = str(exc)
        logger.error("[Commissioner] Duplicate odds fix failed: %s", exc)
    return r


def _check_and_fix_season_type_labels() -> CheckResult:
    from sqlalchemy import text
    r = CheckResult(
        key="season_type_labels",
        name="Season Type Labels",
        description='Inconsistent labels (e.g. "Regular" vs "Regular Season")',
    )
    canonical = {"Preseason", "Regular Season", "Postseason"}
    rows = db.session.execute(text(
        "SELECT season_type, COUNT(*) FROM games GROUP BY season_type ORDER BY COUNT(*) DESC"
    )).fetchall()
    non_canonical = [(row[0], row[1]) for row in rows if row[0] and row[0] not in canonical]
    r.found = len(non_canonical)
    if r.found == 0:
        return r

    mappings = {
        "Regular":        "Regular Season",
        "regular season": "Regular Season",
        "Post Season":    "Postseason",
        "postseason":     "Postseason",
        "Pre Season":     "Preseason",
        "preseason":      "Preseason",
    }
    total = 0
    for old_label, _ in non_canonical:
        new_label = mappings.get(old_label)
        if new_label:
            n = db.session.execute(
                text("UPDATE games SET season_type = :new WHERE season_type = :old"),
                {"new": new_label, "old": old_label},
            ).rowcount
            total += n
            logger.info('[Commissioner] Season type "%s" → "%s" (%d games)', old_label, new_label, n)
        else:
            logger.warning('[Commissioner] Unknown season_type label "%s" — skipping', old_label)
    r.detail = [{"old": lbl, "count": cnt} for lbl, cnt in non_canonical]
    return _auto_fix(r, lambda: total, "Season type labels")


def _check_and_fix_career_stat_dupes() -> CheckResult:
    from sqlalchemy import text
    r = CheckResult(
        key="career_stat_dupes",
        name="Duplicate Career Stats",
        description="Repeated career/season stat rows with no game reference",
    )
    r.found = db.session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT player_id, season_id, stat_category, stat_type
            FROM player_stats WHERE game_id IS NULL
            GROUP BY player_id, season_id, stat_category, stat_type
            HAVING COUNT(*) > 1
        ) x
    """)).scalar()
    if r.found == 0:
        return r
    return _auto_fix(r,
        lambda: db.session.execute(text("""
            DELETE FROM player_stats
            WHERE id NOT IN (
                SELECT MIN(id) FROM player_stats WHERE game_id IS NULL
                GROUP BY player_id, season_id, stat_category, stat_type
            ) AND game_id IS NULL
        """)).rowcount,
        "Career stat dupes")


def _check_and_fix_stuck_legs() -> CheckResult:
    hours = _cfg_int("stuck_hours", 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    r = CheckResult(
        key="stuck_legs",
        name="Stuck Pending Legs",
        description=f"Parlay legs still PENDING on games Final >{hours}h ago",
    )
    from sqlalchemy import text
    rows = db.session.execute(text("""
        SELECT pl.id, pl.pick, g.game_date,
               ht.abbreviation AS home, at2.abbreviation AS away
        FROM parlay_legs pl
        JOIN games g ON g.id = pl.game_id
        LEFT JOIN teams ht  ON ht.id  = g.home_team_id
        LEFT JOIN teams at2 ON at2.id = g.away_team_id
        WHERE pl.result = 'pending'
          AND g.status ILIKE '%final%'
          AND g.game_date < :cutoff
        ORDER BY g.game_date DESC LIMIT 50
    """), {"cutoff": cutoff}).fetchall()
    r.found = len(rows)
    if r.found == 0:
        return r
    r.detail = [{"pick": row[1], "game": f"{row[3] or '?'} vs {row[4] or '?'}",
                 "date": row[2].strftime("%b %-d") if row[2] else "?"} for row in rows]
    try:
        from app.services.parlay_service import auto_settle_all_pending
        r.fixed = auto_settle_all_pending()
        r.status = "fixed" if r.fixed > 0 else "warning"
        if r.fixed < r.found:
            r.human_action = f"{r.found - r.fixed} legs could not be auto-settled (player props or unparseable pick text — update manually)"
        logger.info("[Commissioner] Stuck legs — auto-settled %d of %d", r.fixed, r.found)
    except Exception as exc:
        r.status = "error"
        r.fix_error = str(exc)
        logger.error("[Commissioner] Stuck legs fix failed: %s", exc)
    return r


def _check_and_fix_parlay_statuses() -> CheckResult:
    """Parlays whose status doesn't match their resolved legs."""
    from app.models.parlay import Parlay, ParlayStatus, ParlayLeg, LegResult
    r = CheckResult(
        key="parlay_statuses",
        name="Parlay Status Mismatch",
        description="Parlays stuck in PENDING when all legs are already resolved",
    )
    pending_parlays = Parlay.query.filter_by(status=ParlayStatus.PENDING).all()
    mismatched = [p for p in pending_parlays
                  if p.legs and LegResult.PENDING not in [l.result for l in p.legs]]
    r.found = len(mismatched)
    if r.found == 0:
        return r
    from app.services.parlay_service import _recalculate_parlay_status

    def _fix():
        for p in mismatched:
            _recalculate_parlay_status(p)
        return len(mismatched)

    return _auto_fix(r, _fix, "Parlay status mismatch")


def _check_and_fix_game_week_numbers() -> CheckResult:
    """Scheduled 2026+ games with null week numbers — calculate from kickoff date."""
    r = CheckResult(
        key="game_week_numbers",
        name="Missing Week Numbers",
        description="Scheduled games with no week number — calculated from kickoff date",
    )
    from app.models.game import Game
    games = Game.query.filter(
        Game.week.is_(None),
        Game.game_date.isnot(None),
        Game.season_year >= 2026,
    ).all()
    r.found = len(games)
    if r.found == 0:
        return r
    from app.services.sync.the_odds_api_sync import _estimate_nfl_week

    def _fix():
        count = 0
        for g in games:
            year = g.season_year or g.game_date.year
            week = _estimate_nfl_week(g.game_date, year)
            if week:
                g.week = week
                count += 1
        return count

    result = _auto_fix(r, _fix, "Missing week numbers")
    if result.status == "fixed" and result.fixed == 0:
        result.status = "clean"
    return result


# ── Human-required checks (warn only, no auto-fix) ─────────────────────────────

def _check_final_no_scores() -> CheckResult:
    from sqlalchemy import text
    r = CheckResult(
        key="final_no_scores",
        name="Final Games Missing Scores",
        description="Games marked Final with no score recorded",
        human_action="Run Admin → Sync → espn_schedule to pull the latest scores",
    )
    rows = db.session.execute(text("""
        SELECT g.id, g.season_year, g.week, g.season_type,
               ht.abbreviation AS home, at2.abbreviation AS away
        FROM games g
        LEFT JOIN teams ht  ON ht.id  = g.home_team_id
        LEFT JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.status ILIKE '%final%'
          AND (g.home_score IS NULL OR g.away_score IS NULL)
          AND g.home_team_id IS NOT NULL
        ORDER BY g.game_date DESC LIMIT 20
    """)).fetchall()
    r.found = len(rows)
    if rows:
        r.status = "warning"
        r.detail = [{"game": f"{row[4] or '?'} vs {row[5] or '?'}",
                     "season": f"{row[1]} {row[3]} W{row[2]}"} for row in rows]
    return r


def _check_suspicious_scores() -> CheckResult:
    threshold = _cfg_int("score_max", 100)
    r = CheckResult(
        key="suspicious_scores",
        name="Suspicious Scores",
        description=f"Games with combined score >{threshold} — likely Pro Bowl or data error",
        human_action="Review each game. Pro Bowl scores are expected. Delete via Admin → DB Health SQL if it's bad data.",
    )
    from sqlalchemy import text
    rows = db.session.execute(text(f"""
        SELECT g.id, g.season_year, g.week, g.season_type,
               g.home_score, g.away_score,
               ht.abbreviation AS home, at2.abbreviation AS away
        FROM games g
        LEFT JOIN teams ht  ON ht.id  = g.home_team_id
        LEFT JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.home_score IS NOT NULL AND (g.home_score + g.away_score) > {threshold}
        ORDER BY (g.home_score + g.away_score) DESC LIMIT 20
    """)).fetchall()
    r.found = len(rows)
    if rows:
        r.status = "warning"
        r.detail = [{"game": f"{row[6] or '?'} {row[4]}–{row[7] or '?'} {row[5]}",
                     "total": row[4] + row[5],
                     "season": f"{row[1]} {row[3]} W{row[2]}"} for row in rows]
    return r


def _check_won_no_payout() -> CheckResult:
    from app.models.parlay import Parlay, ParlayStatus
    r = CheckResult(
        key="won_no_payout",
        name="Won Parlays Missing Payout",
        description="Parlays marked WON but actual_payout is 0 or null",
        human_action="Open each parlay and enter the actual payout amount you received.",
    )
    rows = Parlay.query.filter(
        Parlay.status == ParlayStatus.WON,
        db.or_(Parlay.actual_payout == 0, Parlay.actual_payout.is_(None)),
    ).all()
    r.found = len(rows)
    if rows:
        r.status = "warning"
        r.detail = [{"parlay": p.name or f"#{p.id}", "bet": f"${float(p.bet_amount):.2f}",
                     "id": p.id} for p in rows[:20]]
    return r


def _check_stale_odds() -> CheckResult:
    hours = _cfg_int("odds_stale_hours", 48)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    now = datetime.now(timezone.utc)
    r = CheckResult(
        key="stale_odds",
        name="Stale Odds",
        description=f"Upcoming games with odds not refreshed in >{hours}h",
        human_action="Run Admin → Sync → the_odds_api (costs 3 credits, 4h cooldown applies).",
    )
    from sqlalchemy import text
    rows = db.session.execute(text("""
        SELECT g.id, ht.abbreviation AS home, at2.abbreviation AS away,
               g.game_date, MAX(o.synced_at) AS last_sync
        FROM games g
        JOIN odds o ON o.game_id = g.id
        LEFT JOIN teams ht  ON ht.id  = g.home_team_id
        LEFT JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.status = 'Scheduled' AND g.game_date > :now
        GROUP BY g.id, ht.abbreviation, at2.abbreviation, g.game_date
        HAVING MAX(o.synced_at) < :cutoff
        ORDER BY g.game_date LIMIT 20
    """), {"now": now, "cutoff": cutoff}).fetchall()
    r.found = len(rows)
    if rows:
        r.status = "warning"
        r.detail = [{"game": f"{row[2] or '?'} @ {row[1] or '?'}",
                     "kickoff": row[3].strftime("%b %-d") if row[3] else "?",
                     "last_sync": row[4].strftime("%b %-d %H:%M") if row[4] else "never"} for row in rows]
    return r


def _check_api_endpoints() -> CheckResult:
    """Hit every JSON API endpoint with an authenticated test client and verify the response."""
    from flask import current_app
    from app.models.user import User

    r = CheckResult(
        key="api_endpoints",
        name="API Endpoint Health",
        description="Authenticated test of every /api/* route — checks for 200 and valid JSON",
        human_action="Check Admin → Logs for the failing endpoint's traceback",
    )

    admin = User.query.filter(User.is_active.is_(True)).order_by(User.id).first()
    if not admin:
        r.status = "warning"
        r.human_action = "No active user found to authenticate test requests"
        return r

    # All GET endpoints to validate. Parameterised ones use safe defaults.
    endpoints = [
        "/api/parlay/pl-over-time",
        "/api/parlay/win-rate-by-week",
        "/api/parlay/analytics",
        "/api/parlay/bet-type-breakdown",
        "/api/parlay/monthly-pl",
        "/api/parlay/sportsbook-breakdown",
        "/api/parlay/leg-count-breakdown",
        "/api/stats/leaders",
        "/api/reports/stat-leaders",
        "/api/reports/team-rankings",
        "/api/games/score-distribution",
        "/api/games/standings",
        "/api/games/weekly-scoring",
        "/api/games/search",
        "/api/teams/search?q=sea",
        "/api/players/search?q=geno",
        "/api/odds/suggestions?game_id=1",
    ]

    app = current_app._get_current_object()
    failed = []

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = str(admin.id)
            sess["_fresh"] = True

        for path in endpoints:
            try:
                resp = client.get(path)
                if resp.status_code != 200:
                    failed.append({
                        "endpoint": path,
                        "status": resp.status_code,
                        "issue": "Non-200 response",
                    })
                    logger.warning("[Commissioner] API %s → %d", path, resp.status_code)
                else:
                    data = resp.get_json(silent=True)
                    if data is None:
                        failed.append({
                            "endpoint": path,
                            "status": 200,
                            "issue": "Response is not valid JSON",
                        })
                        logger.warning("[Commissioner] API %s → invalid JSON", path)
                    else:
                        logger.debug("[Commissioner] API %s → OK", path)
            except Exception as exc:
                failed.append({"endpoint": path, "status": "ERR", "issue": str(exc)[:100]})
                logger.error("[Commissioner] API %s → exception: %s", path, exc)

    r.found = len(failed)
    if failed:
        r.status = "error"
        r.detail = failed
    return r


# ── Ordered check list ─────────────────────────────────────────────────────────

_AUTO_FIX_CHECKS = [
    _check_and_fix_orphaned_stats,
    _check_and_fix_orphaned_odds,
    _check_and_fix_duplicate_games,
    _check_and_fix_duplicate_players,
    _check_and_fix_duplicate_odds,
    _check_and_fix_season_type_labels,
    _check_and_fix_career_stat_dupes,
    _check_and_fix_game_week_numbers,
    _check_and_fix_stuck_legs,
    _check_and_fix_parlay_statuses,
]

_HUMAN_CHECKS = [
    _check_final_no_scores,
    _check_suspicious_scores,
    _check_won_no_payout,
    _check_stale_odds,
    _check_api_endpoints,
]


# ── Main entry point ───────────────────────────────────────────────────────────

def run_commissioner(triggered_by: str = "admin") -> dict:
    """
    Run all checks. Auto-fix what's safe. Flag what needs a human.
    Returns a run record dict and stores it in AppSetting for the admin page.
    """
    seed_settings()
    started = datetime.now(timezone.utc)
    logger.info("[Commissioner] Run started — triggered_by=%s", triggered_by)

    results: list[CheckResult] = []

    for fn in _AUTO_FIX_CHECKS + _HUMAN_CHECKS:
        try:
            result = fn()
            results.append(result)
            if result.status == "fixed":
                logger.info("[Commissioner] ✓ %s — found %d, fixed %d",
                            result.name, result.found, result.fixed)
            elif result.status == "clean":
                logger.debug("[Commissioner] ✓ %s — clean", result.name)
            elif result.status == "warning":
                logger.warning("[Commissioner] ⚠ %s — %d issue(s). Action: %s",
                               result.name, result.found, result.human_action)
            elif result.status == "error":
                logger.error("[Commissioner] ✗ %s — %d issue(s). %s",
                             result.name, result.found,
                             result.fix_error or result.human_action)
        except Exception as exc:
            logger.error("[Commissioner] Check crashed: %s — %s", fn.__name__, exc, exc_info=True)
            results.append(CheckResult(
                key=fn.__name__, name=fn.__name__,
                description="Check crashed with an unexpected error",
                status="error", fix_error=str(exc),
            ))

    finished = datetime.now(timezone.utc)
    duration = round((finished - started).total_seconds(), 2)

    total_fixed   = sum(r.fixed  for r in results)
    total_found   = sum(r.found  for r in results)
    warnings      = sum(1 for r in results if r.status == "warning")
    errors        = sum(1 for r in results if r.status == "error")
    fixed_checks  = sum(1 for r in results if r.status == "fixed")
    clean_checks  = sum(1 for r in results if r.status == "clean")

    run = {
        "run_at":       started.isoformat(),
        "triggered_by": triggered_by,
        "duration_s":   duration,
        "total_found":  total_found,
        "total_fixed":  total_fixed,
        "fixed_checks": fixed_checks,
        "clean_checks": clean_checks,
        "warnings":     warnings,
        "errors":       errors,
        "results":      [asdict(r) for r in results],
    }

    AppSetting.set(
        "commissioner_last_run",
        json.dumps(run),
        "Last Commissioner run result (JSON)",
    )

    logger.info(
        "[Commissioner] Run complete in %.1fs — found=%d fixed=%d warnings=%d errors=%d",
        duration, total_found, total_fixed, warnings, errors,
    )
    return run
