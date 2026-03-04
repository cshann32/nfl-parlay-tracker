import logging
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.blueprints.parlays import parlays_bp
from app.utils.decorators import role_required
from app.services import parlay_service
from app.models.game import Game
from app.models.team import Team
from app.models.player import Player

logger = logging.getLogger("nfl.parlays")


@parlays_bp.route("/")
@login_required
def index():
    status = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    pagination = parlay_service.list_parlays(current_user.id, status=status, page=page)
    analytics = parlay_service.get_analytics(current_user.id)
    return render_template("parlays/index.html", pagination=pagination,
                           analytics=analytics, current_status=status)


@parlays_bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required("admin", "user")
def create():
    if request.method == "POST":
        data = _parse_parlay_form(request.form)
        try:
            parlay = parlay_service.create_parlay(current_user.id, data)
            flash(f"Parlay '{parlay.name or parlay.id}' created!", "success")
            return redirect(url_for("parlays.detail", parlay_id=parlay.id))
        except Exception as exc:
            flash(str(exc), "danger")
    teams = Team.query.order_by(Team.name).all()
    players = Player.query.order_by(Player.name).limit(500).all()
    upcoming_games = Game.query.filter(Game.status.in_(
        ["Scheduled", "STATUS_SCHEDULED"])).order_by(Game.game_date).limit(100).all()
    games_json = [{"id": g.id, "week": g.week,
                   "away": g.away_team.abbreviation if g.away_team else "?",
                   "home": g.home_team.abbreviation if g.home_team else "?"}
                  for g in upcoming_games]
    return render_template("parlays/form.html", teams=teams, players=players,
                           games=upcoming_games, games_json=games_json, parlay=None)


@parlays_bp.route("/<int:parlay_id>")
@login_required
def detail(parlay_id):
    parlay = parlay_service.get_parlay(parlay_id, current_user.id)
    return render_template("parlays/detail.html", parlay=parlay)


@parlays_bp.route("/<int:parlay_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin", "user")
def edit(parlay_id):
    parlay = parlay_service.get_parlay(parlay_id, current_user.id)
    if request.method == "POST":
        data = _parse_parlay_form(request.form)
        parlay_service.update_parlay(parlay_id, current_user.id, data)
        flash("Parlay updated.", "success")
        return redirect(url_for("parlays.detail", parlay_id=parlay_id))
    teams = Team.query.order_by(Team.name).all()
    players = Player.query.order_by(Player.name).limit(500).all()
    games = Game.query.order_by(Game.game_date.desc()).limit(200).all()
    return render_template("parlays/form.html", parlay=parlay, teams=teams,
                           players=players, games=games)


@parlays_bp.route("/<int:parlay_id>/delete", methods=["POST"])
@login_required
@role_required("admin", "user")
def delete(parlay_id):
    parlay_service.delete_parlay(parlay_id, current_user.id)
    flash("Parlay deleted.", "info")
    return redirect(url_for("parlays.index"))


@parlays_bp.route("/<int:parlay_id>/outcome", methods=["POST"])
@login_required
@role_required("admin", "user")
def set_outcome(parlay_id):
    """Mark parlay status and actual payout."""
    parlay = parlay_service.get_parlay(parlay_id, current_user.id)
    data = {
        "status": request.form.get("status"),
        "actual_payout": request.form.get("actual_payout", 0),
    }
    parlay_service.update_parlay(parlay_id, current_user.id, data)
    flash("Parlay outcome updated.", "success")
    return redirect(url_for("parlays.detail", parlay_id=parlay_id))


@parlays_bp.route("/leg/<int:leg_id>/result", methods=["POST"])
@login_required
@role_required("admin", "user")
def set_leg_result(leg_id):
    result = request.form.get("result")
    parlay_service.update_leg_result(leg_id, result)
    return redirect(request.referrer or url_for("parlays.index"))


def _parse_parlay_form(form) -> dict:
    legs = []
    i = 0
    while f"legs[{i}][pick]" in form:
        legs.append({
            "pick": form.get(f"legs[{i}][pick]"),
            "leg_type": form.get(f"legs[{i}][leg_type]"),
            "odds": int(form.get(f"legs[{i}][odds]", 0)) or None,
            "game_id": int(form.get(f"legs[{i}][game_id]", 0)) or None,
            "player_id": int(form.get(f"legs[{i}][player_id]", 0)) or None,
            "team_id": int(form.get(f"legs[{i}][team_id]", 0)) or None,
            "description": form.get(f"legs[{i}][description]"),
        })
        i += 1
    return {
        "name": form.get("name"),
        "bet_date": form.get("bet_date"),
        "bet_amount": form.get("bet_amount", 0),
        "sportsbook": form.get("sportsbook"),
        "notes": form.get("notes"),
        "legs": legs,
    }
