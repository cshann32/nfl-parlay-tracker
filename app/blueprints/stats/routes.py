import logging
from flask import render_template, request
from flask_login import login_required, current_user
from app.blueprints.stats import stats_bp
from app.models.player import Player
from app.models.team import Team
from app.services import stats_service

logger = logging.getLogger("nfl.stats")


@stats_bp.route("/")
@login_required
def index():
    teams = Team.query.order_by(Team.name).all()
    return render_template("stats/index.html", teams=teams)


@stats_bp.route("/players")
@login_required
def players():
    team_id = request.args.get("team_id", type=int)
    q = Player.query
    if team_id:
        q = q.filter_by(team_id=team_id)
    players_list = q.order_by(Player.position, Player.name).all()
    teams = Team.query.order_by(Team.name).all()
    return render_template("stats/players.html", players=players_list,
                           teams=teams, current_team=team_id)


@stats_bp.route("/players/<int:player_id>")
@login_required
def player_detail(player_id):
    player = Player.query.get_or_404(player_id)
    requested_year = request.args.get("season", type=int)
    if requested_year:
        season_year = requested_year
        stats = stats_service.get_player_stats(player_id, season_year=season_year)
    else:
        # Default to 2025; if no stats exist, fall back to 2024
        stats = stats_service.get_player_stats(player_id, season_year=2025)
        if stats:
            season_year = 2025
        else:
            season_year = 2024
            stats = stats_service.get_player_stats(player_id, season_year=2024)
    gamelog = stats_service.get_player_gamelog(player_id, season_year=season_year)
    return render_template("stats/player_detail.html", player=player,
                           stats=stats, gamelog=gamelog, season_year=season_year)


@stats_bp.route("/teams")
@login_required
def teams():
    all_teams = Team.query.order_by(Team.conference, Team.division, Team.name).all()
    return render_template("stats/teams.html", teams=all_teams)


@stats_bp.route("/teams/<int:team_id>")
@login_required
def team_detail(team_id):
    team = Team.query.get_or_404(team_id)
    season_year = request.args.get("season", type=int)
    stats = stats_service.get_team_stats(team_id, season_year=season_year)
    roster = Player.query.filter_by(team_id=team_id).order_by(Player.position, Player.name).all()
    return render_template("stats/team_detail.html", team=team, stats=stats,
                           roster=roster, season_year=season_year)


@stats_bp.route("/leaders")
@login_required
def leaders():
    season_year = request.args.get("season", 2025, type=int)
    passing = stats_service.get_stat_leaders("passing", "YDS", season_year=season_year)
    rushing = stats_service.get_stat_leaders("rushing", "YDS", season_year=season_year)
    receiving = stats_service.get_stat_leaders("receiving", "YDS", season_year=season_year)
    return render_template("stats/leaders.html", passing=passing, rushing=rushing,
                           receiving=receiving, season_year=season_year)


@stats_bp.route("/predictions")
@login_required
def predictions():
    from app.services import prediction_service

    home_id = request.args.get("home_id", type=int)
    away_id = request.args.get("away_id", type=int)
    season = request.args.get("season", 2025, type=int)

    teams = Team.query.order_by(Team.name).all()
    prediction = None
    if home_id and away_id and home_id != away_id:
        prediction = prediction_service.predict_game_outcome(home_id, away_id, season_year=season)

    power_rankings = prediction_service.get_power_rankings(season_year=season)
    betting_insights = prediction_service.get_user_betting_insights(current_user.id)

    return render_template(
        "stats/predictions.html",
        teams=teams,
        prediction=prediction,
        power_rankings=power_rankings,
        betting_insights=betting_insights,
        home_id=home_id,
        away_id=away_id,
        season=season,
    )


@stats_bp.route("/prop-analyzer")
@login_required
def prop_analyzer():
    player_id  = request.args.get("player_id", type=int)
    stat_cat   = request.args.get("stat_cat", "")
    stat_type  = request.args.get("stat_type", "")
    line       = request.args.get("line", type=float)
    season     = request.args.get("season", 2025, type=int)

    player = Player.query.get(player_id) if player_id else None
    analysis = None
    if player and stat_cat and stat_type and line is not None:
        analysis = stats_service.get_prop_analysis(
            player_id, stat_cat, stat_type, line, season_year=season
        )

    return render_template("stats/prop_analyzer.html",
                           player=player, analysis=analysis,
                           stat_cat=stat_cat, stat_type=stat_type,
                           line=line, season=season)
