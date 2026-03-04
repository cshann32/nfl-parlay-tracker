"""
DB Audit Service — detects duplicates and orphaned records.
All checks run read-only unless a cleanup function is called.
"""
import logging
from sqlalchemy import text
from app.extensions import db

logger = logging.getLogger("nfl.db.audit")


# ── Audit (read-only) ─────────────────────────────────────────────────────────

def run_audit() -> dict:
    """
    Run all integrity checks.
    Returns a dict with findings; each value is a list of dicts or a scalar count.
    """
    return {
        "duplicate_teams":   _duplicate_teams(),
        "duplicate_players": _duplicate_players(),
        "duplicate_games":   _duplicate_games(),
        "duplicate_odds":    _duplicate_odds(),
        "duplicate_news":    _duplicate_news(),
        "null_api_ids":      _null_api_ids(),
        "games_missing_teams": _games_missing_teams(),
        "players_no_team":   _players_no_team(),
    }


def _q(sql: str, **params) -> list[dict]:
    """Execute a SELECT and return list of dicts."""
    rows = db.session.execute(text(sql), params).fetchall()
    return [dict(r._mapping) for r in rows]


def _scalar(sql: str, **params) -> int:
    return db.session.execute(text(sql), params).scalar() or 0


def _duplicate_teams() -> list[dict]:
    """Teams sharing the same abbreviation (should be unique)."""
    return _q("""
        SELECT
            abbreviation,
            COUNT(*)               AS cnt,
            array_agg(id ORDER BY id)      AS ids,
            array_agg(COALESCE(api_id,'—') ORDER BY id) AS api_ids,
            array_agg(name ORDER BY id)    AS names
        FROM teams
        WHERE abbreviation IS NOT NULL
        GROUP BY abbreviation
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
    """)


def _duplicate_players() -> list[dict]:
    """Players sharing the same name and team_id."""
    return _q("""
        SELECT
            p.name,
            p.team_id,
            t.abbreviation AS team_abbr,
            COUNT(*)                        AS cnt,
            array_agg(p.id ORDER BY p.id)   AS ids,
            array_agg(COALESCE(p.api_id,'—') ORDER BY p.id) AS api_ids
        FROM players p
        LEFT JOIN teams t ON t.id = p.team_id
        GROUP BY p.name, p.team_id, t.abbreviation
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 100
    """)


def _duplicate_games() -> list[dict]:
    """Games representing the same real-world match (same teams + week + season)."""
    return _q("""
        SELECT
            g.home_team_id,
            g.away_team_id,
            ht.abbreviation AS home_abbr,
            at.abbreviation AS away_abbr,
            g.season_year,
            g.week,
            COUNT(*)                         AS cnt,
            array_agg(g.id ORDER BY g.id)    AS ids,
            array_agg(COALESCE(g.api_id,'—') ORDER BY g.id) AS api_ids,
            array_agg(
                (SELECT COUNT(*) FROM player_stats ps WHERE ps.game_id = g.id)
                ORDER BY g.id
            ) AS stat_counts
        FROM games g
        LEFT JOIN teams ht ON ht.id = g.home_team_id
        LEFT JOIN teams at ON at.id = g.away_team_id
        WHERE g.home_team_id IS NOT NULL AND g.away_team_id IS NOT NULL
        GROUP BY g.home_team_id, g.away_team_id, g.season_year, g.week,
                 ht.abbreviation, at.abbreviation
        HAVING COUNT(*) > 1
        ORDER BY g.season_year DESC, g.week DESC
        LIMIT 200
    """)


def _duplicate_odds() -> list[dict]:
    """Odds rows sharing (game_id, source, market_type) — indicates repeated syncs."""
    return _q("""
        SELECT
            game_id,
            COALESCE(source, '(none)')      AS source,
            COALESCE(market_type, '(none)') AS market_type,
            COUNT(*)                         AS cnt,
            array_agg(id ORDER BY synced_at DESC) AS ids
        FROM odds
        GROUP BY game_id, source, market_type
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 200
    """)


def _duplicate_news() -> list[dict]:
    """News articles sharing the same headline (potential cross-API duplicates)."""
    return _q("""
        SELECT
            headline,
            COUNT(*)                            AS cnt,
            array_agg(id ORDER BY id)           AS ids,
            array_agg(COALESCE(api_id,'—') ORDER BY id) AS api_ids
        FROM news
        GROUP BY headline
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 50
    """)


def _null_api_ids() -> dict:
    return {
        "teams":   _scalar("SELECT COUNT(*) FROM teams   WHERE api_id IS NULL"),
        "players": _scalar("SELECT COUNT(*) FROM players WHERE api_id IS NULL"),
        "games":   _scalar("SELECT COUNT(*) FROM games   WHERE api_id IS NULL"),
    }


def _games_missing_teams() -> int:
    return _scalar(
        "SELECT COUNT(*) FROM games WHERE home_team_id IS NULL OR away_team_id IS NULL"
    )


def _players_no_team() -> int:
    return _scalar("SELECT COUNT(*) FROM players WHERE team_id IS NULL")


# ── Cleanup actions ───────────────────────────────────────────────────────────

def fix_duplicate_odds() -> int:
    """
    Delete duplicate odds rows.
    Keeps the most-recently-synced row per (game_id, source, market_type).
    Returns the number of rows deleted.
    """
    result = db.session.execute(text("""
        DELETE FROM odds
        WHERE id NOT IN (
            SELECT DISTINCT ON (game_id, COALESCE(source,''), COALESCE(market_type,''))
                id
            FROM odds
            ORDER BY game_id,
                     COALESCE(source,''),
                     COALESCE(market_type,''),
                     synced_at DESC NULLS LAST
        )
    """))
    db.session.commit()
    deleted = result.rowcount
    logger.info("Duplicate odds removed", extra={"deleted": deleted})
    return deleted


def fix_duplicate_games() -> int:
    """
    For each set of games representing the same real match, keep the one with
    the most player stats and reassign all children to the survivor, then
    delete the duplicates.
    Returns the number of game rows deleted.
    """
    # Fetch all duplicate groups
    groups = _q("""
        SELECT
            array_agg(id ORDER BY id) AS ids
        FROM games
        WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL
        GROUP BY home_team_id, away_team_id, season_year, week
        HAVING COUNT(*) > 1
    """)

    deleted = 0
    for group in groups:
        ids = group["ids"]

        # Pick the survivor: the game_id with the most player_stats,
        # falling back to the lowest id (oldest).
        stat_rows = _q(
            """
            SELECT game_id, COUNT(*) AS cnt
            FROM player_stats
            WHERE game_id = ANY(:ids)
            GROUP BY game_id
            ORDER BY cnt DESC
            LIMIT 1
            """,
            ids=ids,
        )
        survivor_id = stat_rows[0]["game_id"] if stat_rows else ids[0]
        loser_ids = [i for i in ids if i != survivor_id]

        for lid in loser_ids:
            # ── player_stats: skip conflicts (survivor already has them) ──
            db.session.execute(text("""
                DELETE FROM player_stats
                WHERE game_id = :lid
                  AND (player_id, stat_category, stat_type) IN (
                      SELECT player_id, stat_category, stat_type
                      FROM player_stats WHERE game_id = :sid
                  )
            """), {"lid": lid, "sid": survivor_id})
            db.session.execute(text(
                "UPDATE player_stats SET game_id=:sid WHERE game_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            # ── team_stats ──
            db.session.execute(text("""
                DELETE FROM team_stats
                WHERE game_id = :lid
                  AND (team_id, stat_category, stat_type) IN (
                      SELECT team_id, stat_category, stat_type
                      FROM team_stats WHERE game_id = :sid
                  )
            """), {"lid": lid, "sid": survivor_id})
            db.session.execute(text(
                "UPDATE team_stats SET game_id=:sid WHERE game_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            # ── odds (no unique constraint, just reassign all) ──
            db.session.execute(text(
                "UPDATE odds SET game_id=:sid WHERE game_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            # ── boxscore: can't have two per game — keep survivor's, drop loser's ──
            db.session.execute(text(
                "DELETE FROM boxscores WHERE game_id=:lid"
            ), {"lid": lid})

            # ── plays ──
            db.session.execute(text(
                "UPDATE plays SET game_id=:sid WHERE game_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            # ── scoreboard ──
            db.session.execute(text(
                "UPDATE scoreboard SET game_id=:sid WHERE game_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            # ── finally delete the duplicate game ──
            db.session.execute(text(
                "DELETE FROM games WHERE id=:lid"
            ), {"lid": lid})
            deleted += 1

        db.session.commit()

    logger.info("Duplicate games merged and removed", extra={"deleted": deleted})
    return deleted


def fix_duplicate_news() -> int:
    """
    For headline duplicates, keep the article that has an api_id (or the
    lowest id if both/neither have one), delete the rest.
    Returns the number of rows deleted.
    """
    groups = _q("""
        SELECT array_agg(id ORDER BY
                   CASE WHEN api_id IS NOT NULL THEN 0 ELSE 1 END,
                   id
               ) AS ids
        FROM news
        GROUP BY headline
        HAVING COUNT(*) > 1
    """)

    deleted = 0
    for group in groups:
        ids = group["ids"]
        survivor_id = ids[0]
        for lid in ids[1:]:
            db.session.execute(text("DELETE FROM news WHERE id=:lid"), {"lid": lid})
            deleted += 1

    db.session.commit()
    logger.info("Duplicate news removed", extra={"deleted": deleted})
    return deleted


def fix_duplicate_players() -> int:
    """
    For players sharing (name, team_id), keep the one with an ESPN api_id
    (most complete data), reassign their stats, delete duplicates.
    Returns the number of player rows deleted.
    """
    groups = _q("""
        SELECT
            array_agg(id ORDER BY
                CASE WHEN api_id LIKE 'espn_%' THEN 0 ELSE 1 END,
                id
            ) AS ids
        FROM players
        GROUP BY name, team_id
        HAVING COUNT(*) > 1
    """)

    deleted = 0
    for group in groups:
        ids = group["ids"]
        survivor_id = ids[0]
        for lid in ids[1:]:
            # Reassign stats (skip conflicts)
            db.session.execute(text("""
                DELETE FROM player_stats
                WHERE player_id = :lid
                  AND (game_id, stat_category, stat_type) IN (
                      SELECT game_id, stat_category, stat_type
                      FROM player_stats WHERE player_id = :sid
                  )
            """), {"lid": lid, "sid": survivor_id})
            db.session.execute(text(
                "UPDATE player_stats SET player_id=:sid WHERE player_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            # Reassign injuries
            db.session.execute(text(
                "UPDATE injuries SET player_id=:sid WHERE player_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            # Reassign depth chart
            db.session.execute(text(
                "UPDATE depth_chart SET player_id=:sid WHERE player_id=:lid"
            ), {"sid": survivor_id, "lid": lid})

            db.session.execute(text("DELETE FROM players WHERE id=:lid"), {"lid": lid})
            deleted += 1

        db.session.commit()

    logger.info("Duplicate players merged and removed", extra={"deleted": deleted})
    return deleted
