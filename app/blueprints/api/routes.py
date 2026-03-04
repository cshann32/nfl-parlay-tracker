"""
API blueprint — JSON endpoints for Chart.js and AJAX calls.
All data served from local DB only.
"""
import logging
from flask import jsonify, request
from flask_login import login_required, current_user
from app.blueprints.api import api_bp
from app.services import parlay_service, stats_service
from app.models.game import Game
from app.models.team import Team
from app.models.player import Player
from app.models.odds import Odds

logger = logging.getLogger("nfl.api")


@api_bp.route("/parlay/pl-over-time")
@login_required
def parlay_pl_over_time():
    data = parlay_service.get_pl_over_time(current_user.id)
    return jsonify(data)


@api_bp.route("/parlay/win-rate-by-week")
@login_required
def parlay_win_rate_by_week():
    data = parlay_service.get_win_rate_by_week(current_user.id)
    return jsonify(data)


@api_bp.route("/parlay/analytics")
@login_required
def parlay_analytics():
    return jsonify(parlay_service.get_analytics(current_user.id))


@api_bp.route("/parlay/bet-type-breakdown")
@login_required
def parlay_bet_type_breakdown():
    return jsonify(parlay_service.get_bet_type_breakdown(current_user.id))


@api_bp.route("/stats/player/<int:player_id>/gamelog")
@login_required
def player_gamelog_chart(player_id):
    season_year = request.args.get("season", type=int)
    data = stats_service.get_player_gamelog_chart(player_id, season_year=season_year)
    return jsonify(data)


@api_bp.route("/stats/player/<int:player_id>/context")
@login_required
def player_stat_context(player_id):
    """Return a player's recent per-game stats for the parlay builder context panel."""
    season_year = request.args.get("season", 2025, type=int)
    player = Player.query.get_or_404(player_id)
    chart_data = stats_service.get_player_gamelog_chart(player_id, season_year=season_year)

    # Build spotlight stats (season totals) for key props
    from app.models.stat import PlayerStat
    pos = player.position or ""
    SPOTLIGHT_CATS = {
        "QB":  [("passing","YDS"),("passing","TD"),("passing","INT"),("passing","CMP")],
        "RB":  [("rushing","YDS"),("rushing","TD"),("rushing","CAR"),("receiving","REC")],
        "WR":  [("receiving","YDS"),("receiving","REC"),("receiving","TD"),("receiving","TGTS")],
        "TE":  [("receiving","YDS"),("receiving","REC"),("receiving","TD"),("receiving","TGTS")],
    }
    cats = SPOTLIGHT_CATS.get(pos, [("rushing","YDS"),("receiving","YDS"),("passing","YDS")])
    season_stats = {}
    for cat, stat_type in cats:
        row = PlayerStat.query.filter_by(
            player_id=player_id, stat_category=cat, stat_type=stat_type,
            game_id=None, season_year=season_year
        ).first()
        if row:
            season_stats[f"{cat}.{stat_type}"] = float(row.value or 0)

    return jsonify({
        "player_id": player_id,
        "name": player.name,
        "position": player.position,
        "team": player.team.abbreviation if player.team else "",
        "team_color": player.team.primary_color if player.team and player.team.primary_color else "#69BE28",
        "image_url": player.image_url,
        "season": season_year,
        "weeks": chart_data.get("weeks", []),
        "stats": chart_data.get("stats", {}),
        "season_totals": season_stats,
    })


@api_bp.route("/stats/leaders")
@login_required
def stat_leaders():
    category = request.args.get("category", "passing")
    stat_type = request.args.get("stat_type", "passingYards")
    season_year = request.args.get("season", type=int)
    limit = min(request.args.get("limit", 20, type=int), 50)
    data = stats_service.get_stat_leaders(category, stat_type, season_year=season_year, limit=limit)
    return jsonify(data)


@api_bp.route("/reports/stat-leaders")
@login_required
def reports_stat_leaders():
    """Player stat leaders for the analytics dashboard charts."""
    category = request.args.get("category", "passing")
    stat_type = request.args.get("stat_type", "YDS")
    season_year = request.args.get("season", type=int)
    limit = min(request.args.get("limit", 12, type=int), 25)
    data = stats_service.get_stat_leaders(category, stat_type, season_year=season_year, limit=limit)
    return jsonify(data)


@api_bp.route("/reports/team-rankings")
@login_required
def reports_team_rankings():
    """Team stat rankings for the analytics dashboard charts.
    Falls back to player-derived totals when team_stats table is empty."""
    category = request.args.get("category", "passing")
    stat_type = request.args.get("stat_type", "YDS")
    season_year = request.args.get("season", type=int)
    data = stats_service.get_team_rankings_for_chart(category, stat_type, season_year=season_year)
    if not data:
        data = stats_service.get_team_rankings_player_derived(
            category, stat_type, season_year=season_year
        )
    return jsonify(data)


@api_bp.route("/parlay/monthly-pl")
@login_required
def parlay_monthly_pl():
    return jsonify(parlay_service.get_monthly_pl(current_user.id))


@api_bp.route("/parlay/sportsbook-breakdown")
@login_required
def parlay_sportsbook_breakdown():
    return jsonify(parlay_service.get_sportsbook_breakdown(current_user.id))


@api_bp.route("/parlay/leg-count-breakdown")
@login_required
def parlay_leg_count_breakdown():
    return jsonify(parlay_service.get_leg_count_breakdown(current_user.id))


@api_bp.route("/games/head-to-head")
@login_required
def games_head_to_head():
    """Return all games between two teams."""
    from sqlalchemy.orm import joinedload
    team1_id = request.args.get("team1_id", type=int)
    team2_id = request.args.get("team2_id", type=int)
    if not team1_id or not team2_id:
        return jsonify({"error": "team1_id and team2_id are required"}), 400

    games = (
        Game.query
        .options(joinedload(Game.home_team), joinedload(Game.away_team))
        .filter(
            Game.home_score.isnot(None),
            Game.status.ilike("%final%"),
            (
                ((Game.home_team_id == team1_id) & (Game.away_team_id == team2_id)) |
                ((Game.home_team_id == team2_id) & (Game.away_team_id == team1_id))
            )
        )
        .order_by(Game.game_date.desc())
        .all()
    )

    t1_wins = t2_wins = ties = 0
    result = []
    for g in games:
        t1_home = g.home_team_id == team1_id
        t1_score = g.home_score if t1_home else g.away_score
        t2_score = g.away_score if t1_home else g.home_score
        if t1_score > t2_score:
            winner = "team1"
            t1_wins += 1
        elif t2_score > t1_score:
            winner = "team2"
            t2_wins += 1
        else:
            winner = "tie"
            ties += 1
        result.append({
            "game_id": g.id,
            "date": g.game_date.isoformat() if g.game_date else None,
            "date_fmt": g.game_date.strftime("%b %-d, %Y") if g.game_date else "—",
            "season_year": g.season_year,
            "week": g.week,
            "home_team": g.home_team.abbreviation if g.home_team else "?",
            "away_team": g.away_team.abbreviation if g.away_team else "?",
            "home_score": g.home_score,
            "away_score": g.away_score,
            "t1_score": t1_score,
            "t2_score": t2_score,
            "winner": winner,
            "total_pts": (g.home_score or 0) + (g.away_score or 0),
        })

    team1 = Team.query.get(team1_id)
    team2 = Team.query.get(team2_id)
    return jsonify({
        "team1": {"id": team1_id, "name": team1.name if team1 else "", "abbrev": team1.abbreviation if team1 else "", "color": team1.primary_color if team1 else "#69BE28"},
        "team2": {"id": team2_id, "name": team2.name if team2 else "", "abbrev": team2.abbreviation if team2 else "", "color": team2.primary_color if team2 else "#002244"},
        "record": {"team1_wins": t1_wins, "team2_wins": t2_wins, "ties": ties, "total": len(result)},
        "games": result,
    })


@api_bp.route("/games/score-distribution")
@login_required
def games_score_distribution():
    """Return combined score histogram and over/under bucket data."""
    season_year = request.args.get("season", type=int)
    q = Game.query.filter(Game.home_score.isnot(None), Game.status.ilike("%final%"))
    if season_year:
        q = q.filter(Game.season_year == season_year)
    games = q.all()

    if not games:
        return jsonify({"buckets": [], "avg_total": 0, "median_total": 0, "games": 0})

    totals = sorted((g.home_score + g.away_score) for g in games)
    avg_total = round(sum(totals) / len(totals), 1)
    mid = len(totals) // 2
    median_total = (totals[mid] + totals[mid - 1]) / 2 if len(totals) % 2 == 0 else totals[mid]

    # Build 5-point buckets (30-34, 35-39, ..., 75+)
    from collections import Counter
    bucket_counts: Counter = Counter()
    for t in totals:
        b = (t // 5) * 5
        b = max(25, min(b, 75))  # clamp
        bucket_counts[b] += 1

    all_buckets = list(range(25, 80, 5))
    buckets = [{"range": f"{b}–{b+4}", "min": b, "count": bucket_counts.get(b, 0)} for b in all_buckets]

    # Home/away scoring averages
    home_ppg = round(sum(g.home_score for g in games) / len(games), 1)
    away_ppg = round(sum(g.away_score for g in games) / len(games), 1)

    return jsonify({
        "buckets": buckets,
        "avg_total": avg_total,
        "median_total": round(median_total, 1),
        "home_ppg": home_ppg,
        "away_ppg": away_ppg,
        "games": len(games),
    })


@api_bp.route("/games/standings")
@login_required
def games_standings():
    """W-L-T records grouped by conference/division, computed from games table."""
    season_year = request.args.get("season", type=int)
    data = stats_service.get_standings(season_year=season_year)
    return jsonify(data)


@api_bp.route("/games/weekly-scoring")
@login_required
def games_weekly_scoring():
    """Average combined score + home/away PPG per week."""
    season_year = request.args.get("season", type=int)
    data = stats_service.get_weekly_scoring(season_year=season_year)
    return jsonify(data)


@api_bp.route("/games/team-record")
@login_required
def games_team_record():
    """Season record + game log for a single team."""
    team_id = request.args.get("team_id", type=int)
    season_year = request.args.get("season", type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400
    data = stats_service.get_team_record(team_id, season_year=season_year)
    return jsonify(data)


@api_bp.route("/teams/search")
@login_required
def teams_search():
    q = request.args.get("q", "")
    teams = Team.query.filter(Team.name.ilike(f"%{q}%")).limit(20).all()
    return jsonify([{"id": t.id, "name": t.name, "abbreviation": t.abbreviation} for t in teams])


@api_bp.route("/players/search")
@login_required
def players_search():
    q = request.args.get("q", "")
    team_id = request.args.get("team_id", type=int)
    query = Player.query.filter(Player.name.ilike(f"%{q}%"))
    if team_id:
        query = query.filter_by(team_id=team_id)
    players = query.limit(30).all()
    return jsonify([{"id": p.id, "name": p.name, "position": p.position,
                     "team": p.team.abbreviation if p.team else ""} for p in players])


@api_bp.route("/games/search")
@login_required
def games_search():
    q = request.args.get("q", "")
    week = request.args.get("week", type=int)
    season = request.args.get("season", type=int)
    query = Game.query
    if week:
        query = query.filter_by(week=week)
    if season:
        query = query.filter_by(season_year=season)
    games = query.order_by(Game.game_date.desc()).limit(50).all()
    result = []
    for g in games:
        home = g.home_team.abbreviation if g.home_team else "?"
        away = g.away_team.abbreviation if g.away_team else "?"
        result.append({
            "id": g.id,
            "label": f"{away} @ {home} — W{g.week} {g.season_year}",
            "week": g.week,
            "date": g.game_date.isoformat() if g.game_date else None,
        })
    return jsonify(result)


@api_bp.route("/games/<int:game_id>/odds")
@login_required
def game_odds(game_id):
    odds = Odds.query.filter_by(game_id=game_id).all()
    return jsonify([{
        "source": o.source,
        "market_type": o.market_type,
        "home_moneyline": o.home_moneyline,
        "away_moneyline": o.away_moneyline,
        "home_spread": float(o.home_spread) if o.home_spread else None,
        "away_spread": float(o.away_spread) if o.away_spread else None,
        "over_under": float(o.over_under) if o.over_under else None,
    } for o in odds])
