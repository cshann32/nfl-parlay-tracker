import logging
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.orm import joinedload
from app.blueprints.schedules import schedules_bp
from app.models.game import Game
from app.models.team import Team
from app.models.stat import PlayerStat, TeamStat

logger = logging.getLogger("nfl.schedules")

# Column order per category for box score display
BOXSCORE_COLS = {
    "passing":   ["CMP", "ATT", "YDS", "TD", "INT", "RTG"],
    "rushing":   ["CAR", "YDS", "AVG", "TD", "LNG"],
    "receiving": ["REC", "TGTS", "YDS", "AVG", "TD", "LNG"],
    "defensive": ["TOT", "SOLO", "SCK", "TFL", "PD", "FF", "FR"],
    "kicking":   ["FGM", "FGA", "PCT", "LK", "XPM", "XPA"],
    "punting":   ["NO", "YDS", "AVG", "NET", "LNG", "IN20"],
    "fumbles":   ["FUM", "LST"],
    "scoring":   ["PTS", "OFTD", "DFTD", "XPM", "FGM"],
    "interceptions": ["INT", "YDS", "TD"],
    "returning": ["KR", "YDS", "TD"],
}
_KEY_STAT = {
    "passing": "YDS", "rushing": "YDS", "receiving": "YDS",
    "defensive": "TOT", "kicking": "FGM", "punting": "YDS",
}
_SKIP_CATS = {"ngs_passing", "ngs_rushing", "ngs_receiving",
              "adv_passing", "adv_rushing", "adv_receiving", "general"}

_CAT_ORDER = ["passing", "rushing", "receiving", "defensive",
              "kicking", "punting", "fumbles", "scoring",
              "interceptions", "returning"]


def _game_summary(home_bs: dict, away_bs: dict) -> list[dict]:
    """Derive key team-level game stats from pivoted player stats."""
    def s(bs, cat, key):
        return sum(float(row["vals"].get(key) or 0) for row in bs.get(cat, []))

    rows = []

    # Yards
    h_pass = s(home_bs, "passing", "YDS")
    a_pass = s(away_bs, "passing", "YDS")
    h_rush = s(home_bs, "rushing", "YDS")
    a_rush = s(away_bs, "rushing", "YDS")

    if h_pass or a_pass or h_rush or a_rush:
        rows.append({"label": "Total Yards",  "home": int(h_pass + h_rush), "away": int(a_pass + a_rush), "more_is_better": True})
        rows.append({"label": "Pass Yards",   "home": int(h_pass),          "away": int(a_pass),          "more_is_better": True})
        rows.append({"label": "Rush Yards",   "home": int(h_rush),          "away": int(a_rush),          "more_is_better": True})

    # Comp / Att
    h_cmp = s(home_bs, "passing", "CMP");  a_cmp = s(away_bs, "passing", "CMP")
    h_att = s(home_bs, "passing", "ATT");  a_att = s(away_bs, "passing", "ATT")
    if h_cmp or a_cmp:
        rows.append({"label": "Comp/Att", "home": f"{int(h_cmp)}/{int(h_att)}", "away": f"{int(a_cmp)}/{int(a_att)}", "text_only": True})

    # Touchdowns (pass + rush only — receiving TDs would double-count)
    h_td = s(home_bs, "passing", "TD") + s(home_bs, "rushing", "TD")
    a_td = s(away_bs, "passing", "TD") + s(away_bs, "rushing", "TD")
    if h_td or a_td:
        rows.append({"label": "Touchdowns", "home": int(h_td), "away": int(a_td), "more_is_better": True})

    # Turnovers = INTs thrown + fumbles lost
    h_int = s(home_bs, "passing", "INT");  a_int = s(away_bs, "passing", "INT")
    h_fum = s(home_bs, "fumbles",  "LST"); a_fum = s(away_bs, "fumbles",  "LST")
    if h_int or a_int or h_fum or a_fum:
        rows.append({"label": "Turnovers", "home": int(h_int + h_fum), "away": int(a_int + a_fum), "more_is_better": False})

    # Sacks taken (SACK is saved in passing category from composite "SACKS" field)
    h_sck = s(home_bs, "passing", "SACK"); a_sck = s(away_bs, "passing", "SACK")
    if h_sck or a_sck:
        rows.append({"label": "Sacks Taken", "home": int(h_sck), "away": int(a_sck), "more_is_better": False})

    # Defensive sacks (how many the defense recorded)
    h_dsck = s(home_bs, "defensive", "SCK"); a_dsck = s(away_bs, "defensive", "SCK")
    if h_dsck or a_dsck:
        rows.append({"label": "Sacks", "home": int(h_dsck), "away": int(a_dsck), "more_is_better": True})

    return rows


def _pivot_stats(stats_list: list) -> dict:
    """Return {category: [{"player": Player, "vals": {stat_type: float}}, ...]} sorted by key stat."""
    raw: dict = {}
    for s in stats_list:
        cat = s.stat_category
        if cat in _SKIP_CATS:
            continue
        pid = s.player_id
        if cat not in raw:
            raw[cat] = {}
        if pid not in raw[cat]:
            raw[cat][pid] = {"player": s.player, "vals": {}}
        raw[cat][pid]["vals"][s.stat_type] = float(s.value or 0)

    result = {}
    for cat in _CAT_ORDER:
        if cat not in raw:
            continue
        key = _KEY_STAT.get(cat, "YDS")
        result[cat] = sorted(
            raw[cat].values(),
            key=lambda x: x["vals"].get(key, 0),
            reverse=True,
        )
    # Append any remaining categories not in _CAT_ORDER
    for cat, players in raw.items():
        if cat not in result:
            result[cat] = list(players.values())
    return result


@schedules_bp.route("/")
@login_required
def index():
    week = request.args.get("week", type=int)
    season_year = request.args.get("season", type=int)
    team_id = request.args.get("team_id", type=int)

    q = Game.query.order_by(Game.game_date)
    if week:
        q = q.filter_by(week=week)
    if season_year:
        q = q.filter_by(season_year=season_year)
    if team_id:
        q = q.filter((Game.home_team_id == team_id) | (Game.away_team_id == team_id))

    games = q.limit(200).all()
    teams = Team.query.order_by(Team.name).all()

    from sqlalchemy import distinct
    weeks = [r[0] for r in Game.query.with_entities(distinct(Game.week)).filter(
        Game.week.isnot(None)).order_by(Game.week).all()]
    seasons = [r[0] for r in Game.query.with_entities(distinct(Game.season_year)).filter(
        Game.season_year.isnot(None)).order_by(Game.season_year.desc()).all()]

    return render_template("schedules/index.html", games=games, teams=teams,
                           weeks=weeks, seasons=seasons, current_week=week,
                           current_season=season_year, current_team=team_id)


@schedules_bp.route("/<int:game_id>")
@login_required
def game_detail(game_id):
    game = Game.query.options(
        joinedload(Game.home_team),
        joinedload(Game.away_team),
    ).get_or_404(game_id)

    boxscore = game.boxscore

    # Player stats for this game with player+team eagerly loaded
    from app.models.player import Player
    all_player_stats = (
        PlayerStat.query
        .filter(PlayerStat.game_id == game_id)
        .join(Player, PlayerStat.player_id == Player.id)
        .options(joinedload(PlayerStat.player).joinedload(Player.team))
        .order_by(PlayerStat.stat_category, Player.name, PlayerStat.stat_type)
        .all()
    )

    home_id = game.home_team_id
    away_id = game.away_team_id

    home_player_stats = [s for s in all_player_stats if s.player.team_id == home_id]
    away_player_stats = [s for s in all_player_stats if s.player.team_id == away_id]

    # Pivoted boxscore data for redesigned layout
    home_boxscore = _pivot_stats(home_player_stats)
    away_boxscore = _pivot_stats(away_player_stats)
    # All categories that appear in either team (union, in order)
    all_cats = list(dict.fromkeys(
        [c for c in _CAT_ORDER if c in home_boxscore or c in away_boxscore]
        + [c for c in home_boxscore if c not in _CAT_ORDER]
        + [c for c in away_boxscore if c not in _CAT_ORDER]
    ))

    # Team stats — build side-by-side comparison rows
    all_team_stats = TeamStat.query.filter_by(game_id=game_id).all()
    home_ts = {(s.stat_category, s.stat_type): s.value for s in all_team_stats if s.team_id == home_id}
    away_ts = {(s.stat_category, s.stat_type): s.value for s in all_team_stats if s.team_id == away_id}
    all_keys = sorted(set(home_ts.keys()) | set(away_ts.keys()))
    team_comparison = [
        {"category": cat, "stat_type": typ,
         "home_value": home_ts.get((cat, typ)), "away_value": away_ts.get((cat, typ))}
        for cat, typ in all_keys
    ]

    has_any_stats = bool(all_player_stats or team_comparison)
    game_summary = _game_summary(home_boxscore, away_boxscore)

    # Injuries for both teams this week/season
    from app.models.injury import Injury
    injury_q = Injury.query.filter(Injury.team_id.in_([home_id, away_id]))
    if game.week:
        injury_q = injury_q.filter_by(week=game.week)
    if game.season_year:
        injury_q = injury_q.filter_by(season_year=game.season_year)
    injuries = injury_q.order_by(Injury.team_id, Injury.status).all()
    home_injuries = [i for i in injuries if i.team_id == home_id]
    away_injuries = [i for i in injuries if i.team_id == away_id]

    return render_template(
        "schedules/game_detail.html",
        game=game,
        boxscore=boxscore,
        home_player_stats=home_player_stats,
        away_player_stats=away_player_stats,
        home_boxscore=home_boxscore,
        away_boxscore=away_boxscore,
        all_cats=all_cats,
        boxscore_cols=BOXSCORE_COLS,
        team_comparison=team_comparison,
        game_summary=game_summary,
        has_any_stats=has_any_stats,
        home_injuries=home_injuries,
        away_injuries=away_injuries,
    )


@schedules_bp.route("/<int:game_id>/fetch-stats", methods=["POST"])
@login_required
def fetch_game_stats(game_id):
    """Fetch per-game player stats from ESPN's free API for a single game."""
    from app.services.sync.espn_game_stats_sync import sync_single_game
    try:
        inserted, updated, skipped = sync_single_game(game_id)
        if inserted + updated > 0:
            flash(f"Stats loaded: {inserted} new, {updated} updated.", "success")
        else:
            flash("No stats found for this game — the ESPN event ID may not match.", "warning")
    except Exception as exc:
        logger.warning("fetch_game_stats failed", extra={"game_id": game_id, "error": str(exc)})
        flash(f"Could not fetch stats: {exc}", "danger")
    return redirect(url_for("schedules.game_detail", game_id=game_id))
