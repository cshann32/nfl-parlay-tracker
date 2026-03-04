import logging
from flask import render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timezone
from app.blueprints.reports import reports_bp
from app.extensions import db
from app.models.report import Report
from app.services import report_service
from app.models.team import Team
from app.models.player import Player

logger = logging.getLogger("nfl.reports")


@reports_bp.route("/")
@login_required
def index():
    reports = Report.query.filter_by(user_id=current_user.id).order_by(Report.created_at.desc()).all()
    return render_template("reports/index.html", reports=reports)


@reports_bp.route("/analytics")
@login_required
def analytics():
    from sqlalchemy import distinct
    from app.models.stat import PlayerStat
    from app.extensions import db as _db
    seasons = [
        r[0] for r in _db.session.query(distinct(PlayerStat.season_year))
        .filter(PlayerStat.season_year.isnot(None))
        .order_by(PlayerStat.season_year.desc())
        .limit(5).all()
    ]
    return render_template("reports/analytics.html", seasons=seasons)


@reports_bp.route("/leaders")
@login_required
def leaders():
    from sqlalchemy import distinct
    from app.models.stat import PlayerStat
    from app.extensions import db as _db
    seasons = [
        r[0] for r in _db.session.query(distinct(PlayerStat.season_year))
        .filter(PlayerStat.season_year.isnot(None))
        .order_by(PlayerStat.season_year.desc()).limit(5).all()
    ]
    positions = ["QB", "WR", "TE", "RB", "K", "LB", "DE", "DT", "CB", "S"]
    return render_template("reports/leaders.html", seasons=seasons, positions=positions)


@reports_bp.route("/player-research")
@login_required
def player_research():
    from sqlalchemy import distinct
    from app.models.stat import PlayerStat
    from app.extensions import db as _db
    seasons = [
        r[0] for r in _db.session.query(distinct(PlayerStat.season_year))
        .filter(PlayerStat.season_year.isnot(None))
        .order_by(PlayerStat.season_year.desc()).limit(5).all()
    ]
    player_id = request.args.get("player_id", type=int)
    season = request.args.get("season", seasons[0] if seasons else None, type=int)
    player = Player.query.get(player_id) if player_id else None
    return render_template("reports/player_research.html",
                           seasons=seasons, player=player, season=season)


@reports_bp.route("/parlay-breakdown")
@login_required
def parlay_breakdown():
    from app.models.parlay import Parlay, ParlayStatus
    from sqlalchemy import distinct
    date_from = request.args.get("date_from", "")
    date_to   = request.args.get("date_to", "")
    sportsbook = request.args.get("sportsbook", "")
    status_filter = request.args.get("status", "")

    q = Parlay.query.filter_by(user_id=current_user.id)
    if date_from:
        q = q.filter(Parlay.bet_date >= date_from)
    if date_to:
        q = q.filter(Parlay.bet_date <= date_to)
    if sportsbook:
        q = q.filter(Parlay.sportsbook.ilike(f"%{sportsbook}%"))
    if status_filter:
        try:
            q = q.filter_by(status=ParlayStatus(status_filter))
        except ValueError:
            pass

    parlays = q.order_by(Parlay.bet_date.desc()).all()
    sportsbooks = [r[0] for r in db.session.query(distinct(Parlay.sportsbook))
                   .filter(Parlay.user_id == current_user.id, Parlay.sportsbook.isnot(None)).all()]

    return render_template("reports/parlay_breakdown.html",
                           parlays=parlays, sportsbooks=sportsbooks,
                           date_from=date_from, date_to=date_to,
                           sportsbook=sportsbook, status_filter=status_filter)


@reports_bp.route("/leg-count")
@login_required
def leg_count():
    """Parlay ROI by number of legs."""
    return render_template("reports/leg_count.html")


@reports_bp.route("/standings")
@login_required
def standings():
    """NFL standings computed from the games table."""
    from app.models.game import Game as GameModel
    seasons = [
        r[0] for r in db.session.query(GameModel.season_year)
        .filter(GameModel.season_year.isnot(None))
        .distinct()
        .order_by(GameModel.season_year.desc()).limit(5).all()
    ]
    teams = Team.query.order_by(Team.name).all()
    return render_template("reports/standings.html", seasons=seasons, teams=teams)


@reports_bp.route("/team-performance")
@login_required
def team_performance():
    """Full season breakdown for a selected team."""
    from app.models.game import Game as GameModel
    team_id = request.args.get("team_id", type=int)
    season = request.args.get("season", type=int)
    seasons = [
        r[0] for r in db.session.query(GameModel.season_year)
        .filter(GameModel.season_year.isnot(None))
        .distinct()
        .order_by(GameModel.season_year.desc()).limit(5).all()
    ]
    if not seasons:
        from app.config import CURRENT_SEASON
        seasons = [CURRENT_SEASON, CURRENT_SEASON - 1]
    if not season:
        season = seasons[0]
    teams = Team.query.order_by(Team.name).all()
    team = Team.query.get(team_id) if team_id else None
    return render_template("reports/team_performance.html",
                           seasons=seasons, teams=teams, team=team,
                           season=season, team_id=team_id)


@reports_bp.route("/head-to-head")
@login_required
def head_to_head():
    """Head-to-head matchup explorer — pick two teams."""
    team1_id = request.args.get("team1_id", type=int)
    team2_id = request.args.get("team2_id", type=int)
    teams = Team.query.order_by(Team.name).all()
    return render_template("reports/head_to_head.html",
                           teams=teams, team1_id=team1_id, team2_id=team2_id)


@reports_bp.route("/score-distribution")
@login_required
def score_distribution():
    """Score and totals distribution across all games."""
    from sqlalchemy import distinct
    from app.models.stat import PlayerStat
    seasons = [
        r[0] for r in db.session.query(distinct(PlayerStat.season_year))
        .filter(PlayerStat.season_year.isnot(None))
        .order_by(PlayerStat.season_year.desc()).limit(5).all()
    ]
    return render_template("reports/score_distribution.html", seasons=seasons)


@reports_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        config = _build_config(request.form)
        report = Report(user_id=current_user.id, name=request.form.get("name", "Report"), config=config)
        db.session.add(report)
        db.session.commit()
        flash("Report saved.", "success")
        return redirect(url_for("reports.run", report_id=report.id))
    teams = Team.query.order_by(Team.name).all()
    players = Player.query.order_by(Player.name).limit(200).all()
    return render_template("reports/form.html", report=None, teams=teams, players=players)


@reports_bp.route("/<int:report_id>/run")
@login_required
def run(report_id):
    report = Report.query.filter_by(id=report_id, user_id=current_user.id).first_or_404()
    data = report_service.run_report(report.config, current_user.id)
    report.last_run_at = datetime.now(timezone.utc)
    db.session.commit()
    return render_template("reports/results.html", report=report, data=data)


@reports_bp.route("/<int:report_id>/export/csv")
@login_required
def export_csv(report_id):
    report = Report.query.filter_by(id=report_id, user_id=current_user.id).first_or_404()
    data = report_service.run_report(report.config, current_user.id)
    buf = report_service.export_csv(data)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name=f"{report.name.replace(' ', '_')}.csv")


@reports_bp.route("/<int:report_id>/export/pdf")
@login_required
def export_pdf(report_id):
    report = Report.query.filter_by(id=report_id, user_id=current_user.id).first_or_404()
    data = report_service.run_report(report.config, current_user.id)
    buf = report_service.export_pdf(data, title=report.name)
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{report.name.replace(' ', '_')}.pdf")


@reports_bp.route("/<int:report_id>/delete", methods=["POST"])
@login_required
def delete(report_id):
    report = Report.query.filter_by(id=report_id, user_id=current_user.id).first_or_404()
    db.session.delete(report)
    db.session.commit()
    flash("Report deleted.", "info")
    return redirect(url_for("reports.index"))


def _build_config(form) -> dict:
    return {
        "type": form.get("type", "parlays"),
        "status": form.get("status"),
        "date_from": form.get("date_from"),
        "date_to": form.get("date_to"),
        "team_id": int(form.get("team_id", 0)) or None,
        "player_id": int(form.get("player_id", 0)) or None,
        "season_year": int(form.get("season_year", 0)) or None,
        "stat_category": form.get("stat_category"),
        "sportsbook": form.get("sportsbook"),
    }
