"""Query and aggregate player/team stats from the local DB."""
import logging
from sqlalchemy import func
from app.extensions import db
from app.models.stat import PlayerStat, TeamStat
from app.models.player import Player
from app.models.team import Team
from app.models.game import Game

logger = logging.getLogger("nfl.stats")


def get_player_stats(player_id: int, season_year: int | None = None,
                     category: str | None = None) -> list[dict]:
    q = PlayerStat.query.filter_by(player_id=player_id)
    if season_year:
        q = q.filter_by(season_year=season_year)
    if category:
        q = q.filter_by(stat_category=category)
    stats = q.all()
    return [{"stat_type": s.stat_type, "category": s.stat_category,
             "value": float(s.value or 0), "week": s.week, "game_id": s.game_id}
            for s in stats]


def get_team_stats(team_id: int, season_year: int | None = None,
                   category: str | None = None) -> list[dict]:
    q = TeamStat.query.filter_by(team_id=team_id)
    if season_year:
        q = q.filter_by(season_year=season_year)
    if category:
        q = q.filter_by(stat_category=category)
    stats = q.all()
    return [{"stat_type": s.stat_type, "category": s.stat_category,
             "value": float(s.value or 0), "week": s.week, "game_id": s.game_id}
            for s in stats]


def get_stat_leaders(stat_category: str, stat_type: str,
                     season_year: int | None = None, limit: int = 20) -> list[dict]:
    """Return top players for a given stat type."""
    q = db.session.query(
        Player.id.label("player_id"),
        Player.name,
        Player.image_url,
        Team.abbreviation.label("team"),
        Team.logo_url.label("team_logo"),
        Team.primary_color.label("team_color"),
        func.sum(PlayerStat.value).label("total"),
    ).join(PlayerStat, PlayerStat.player_id == Player.id) \
     .join(Team, Player.team_id == Team.id, isouter=True) \
     .filter(PlayerStat.stat_category == stat_category, PlayerStat.stat_type == stat_type,
             PlayerStat.game_id.is_(None))
    if season_year:
        q = q.filter(PlayerStat.season_year == season_year)
    q = q.group_by(Player.id, Player.name, Player.image_url,
                   Team.abbreviation, Team.logo_url, Team.primary_color) \
         .order_by(func.sum(PlayerStat.value).desc()) \
         .limit(limit)
    return [{"player_id": r.player_id, "player": r.name, "image_url": r.image_url,
             "team": r.team, "team_logo": r.team_logo, "team_color": r.team_color or "#6c757d",
             "total": float(r.total or 0)} for r in q.all()]


def get_team_stat_leaders(stat_category: str, stat_type: str,
                          season_year: int | None = None, limit: int = 32) -> list[dict]:
    q = db.session.query(
        Team.name,
        Team.abbreviation,
        func.sum(TeamStat.value).label("total"),
    ).join(TeamStat, TeamStat.team_id == Team.id) \
     .filter(TeamStat.stat_category == stat_category, TeamStat.stat_type == stat_type)
    if season_year:
        q = q.filter(TeamStat.season_year == season_year)
    q = q.group_by(Team.id, Team.name, Team.abbreviation) \
         .order_by(func.sum(TeamStat.value).desc()) \
         .limit(limit)
    return [{"team": r.name, "abbrev": r.abbreviation, "total": float(r.total or 0)} for r in q.all()]


def get_team_rankings_for_chart(stat_category: str, stat_type: str,
                               season_year: int | None = None, limit: int = 32) -> list[dict]:
    """Like get_team_stat_leaders but includes logo_url and primary_color for Chart.js."""
    q = db.session.query(
        Team.name,
        Team.abbreviation,
        Team.logo_url,
        Team.primary_color,
        func.sum(TeamStat.value).label("total"),
    ).join(TeamStat, TeamStat.team_id == Team.id) \
     .filter(TeamStat.stat_category == stat_category, TeamStat.stat_type == stat_type)
    if season_year:
        q = q.filter(TeamStat.season_year == season_year)
    q = q.group_by(Team.id, Team.name, Team.abbreviation, Team.logo_url, Team.primary_color) \
         .order_by(func.sum(TeamStat.value).desc()) \
         .limit(limit)
    return [{"team": r.name, "abbrev": r.abbreviation, "logo_url": r.logo_url,
             "color": r.primary_color or "#6c757d", "total": float(r.total or 0)} for r in q.all()]


def get_prop_analysis(player_id: int, stat_category: str, stat_type: str,
                      line: float, season_year: int | None = None) -> dict:
    """Analyze how often a player hits over/under a prop line."""
    q = (
        db.session.query(PlayerStat, Game)
        .join(Game, PlayerStat.game_id == Game.id)
        .filter(
            PlayerStat.player_id == player_id,
            PlayerStat.stat_category == stat_category,
            PlayerStat.stat_type == stat_type,
            PlayerStat.game_id.isnot(None),
        )
    )
    if season_year:
        q = q.filter(PlayerStat.season_year == season_year)
    rows = q.order_by(Game.game_date).all()

    games = []
    for stat, game in rows:
        val = float(stat.value or 0)
        games.append({"week": stat.week, "date": game.game_date, "value": val, "over": val > line})

    values = [g["value"] for g in games]
    total = len(values)
    over_count = sum(1 for v in values if v > line)
    hit_rate = round(over_count / total * 100, 1) if total else 0
    avg = round(sum(values) / total, 1) if total else 0

    return {
        "games": games,
        "total": total,
        "over": over_count,
        "under": total - over_count,
        "hit_rate": hit_rate,
        "avg": avg,
        "recent5": games[-5:],
        "recent5_over": sum(1 for g in games[-5:] if g["over"]),
        "line": line,
    }


def get_player_gamelog_chart(player_id: int, season_year: int | None = None) -> dict:
    """Return week-by-week stats pivoted for Chart.js, keyed by category → stat_type → [weekly values]."""
    from app.models.stat import PlayerStat
    q = PlayerStat.query.filter(
        PlayerStat.player_id == player_id,
        PlayerStat.game_id.isnot(None),
    )
    if season_year:
        q = q.filter_by(season_year=season_year)
    rows = q.order_by(PlayerStat.week).all()

    # Build week list and pivot table
    # week_data[week][(category, stat_type)] = value
    week_data: dict[int, dict] = {}
    for r in rows:
        if r.week is None:
            continue
        if r.week not in week_data:
            week_data[r.week] = {}
        week_data[r.week][(r.stat_category, r.stat_type)] = float(r.value or 0)

    weeks_sorted = sorted(week_data.keys())

    # Collect unique (category, stat_type) pairs
    all_keys: set[tuple] = set()
    for wd in week_data.values():
        all_keys.update(wd.keys())

    # Organize by category
    result: dict[str, dict] = {}
    for cat, stat_type in sorted(all_keys):
        if cat not in result:
            result[cat] = {}
        result[cat][stat_type] = [week_data.get(w, {}).get((cat, stat_type), None) for w in weeks_sorted]

    return {"weeks": weeks_sorted, "stats": result}


def get_player_gamelog(player_id: int, season_year: int | None = None) -> list[dict]:
    """Return per-game stats for a player."""
    q = db.session.query(
        Game.game_date,
        Game.week,
        Team.abbreviation.label("opponent"),
        PlayerStat.stat_category,
        PlayerStat.stat_type,
        PlayerStat.value,
    ).join(PlayerStat, PlayerStat.game_id == Game.id) \
     .join(Team, (Team.id == Game.home_team_id) | (Team.id == Game.away_team_id), isouter=True) \
     .filter(PlayerStat.player_id == player_id)
    if season_year:
        q = q.filter(PlayerStat.season_year == season_year)
    q = q.order_by(Game.game_date)
    return [{"date": r.game_date, "week": r.week, "category": r.stat_category,
             "stat": r.stat_type, "value": float(r.value or 0)} for r in q.all()]


# ── Team-derived Rankings (PlayerStat fallback) ───────────────────────────────

def get_team_rankings_player_derived(stat_category: str, stat_type: str,
                                     season_year: int | None = None,
                                     limit: int = 32) -> list[dict]:
    """
    Team rankings summed from player_stats grouped by team.
    Used as fallback when team_stats table is empty.
    """
    from app.models.stat import PlayerStat
    q = db.session.query(
        Team.name,
        Team.abbreviation,
        Team.logo_url,
        Team.primary_color,
        func.sum(PlayerStat.value).label("total"),
    ).join(Player, Player.team_id == Team.id) \
     .join(PlayerStat, PlayerStat.player_id == Player.id) \
     .filter(
         PlayerStat.stat_category == stat_category,
         PlayerStat.stat_type == stat_type,
         PlayerStat.game_id.is_(None),
     )
    if season_year:
        q = q.filter(PlayerStat.season_year == season_year)
    q = (
        q.group_by(Team.id, Team.name, Team.abbreviation, Team.logo_url, Team.primary_color)
         .order_by(func.sum(PlayerStat.value).desc())
         .limit(limit)
    )
    return [{"team": r.name, "abbrev": r.abbreviation, "logo_url": r.logo_url,
             "color": r.primary_color or "#6c757d", "total": float(r.total or 0)}
            for r in q.all()]


# ── NFL Standings (from games table) ─────────────────────────────────────────

def get_standings(season_year: int | None = None) -> dict:
    """
    Compute W-L-T records from the games table.
    Returns {conference: {division: [team_record, ...]}} sorted by wins desc.
    """
    from collections import defaultdict
    q = Game.query.filter(
        Game.home_score.isnot(None),
        Game.away_score.isnot(None),
        Game.home_team_id.isnot(None),
        Game.away_team_id.isnot(None),
        db.or_(
            Game.status.ilike("%final%"),
            Game.status.ilike("%complete%"),
        ),
    )
    if season_year:
        q = q.filter(Game.season_year == season_year)
    games = q.all()

    records: dict = defaultdict(lambda: dict(w=0, l=0, t=0, pf=0, pa=0,
                                              hw=0, hl=0, aw=0, al=0))
    for g in games:
        hs = g.home_score or 0
        as_ = g.away_score or 0
        home = records[g.home_team_id]
        away = records[g.away_team_id]
        if hs > as_:
            home["w"] += 1; home["hw"] += 1
            away["l"] += 1; away["al"] += 1
        elif as_ > hs:
            away["w"] += 1; away["aw"] += 1
            home["l"] += 1; home["hl"] += 1
        else:
            home["t"] += 1; away["t"] += 1
        home["pf"] += hs; home["pa"] += as_
        away["pf"] += as_; away["pa"] += hs

    all_teams = Team.query.all()
    team_map = {t.id: t for t in all_teams}

    grouped: dict = {}
    for tid, rec in records.items():
        team = team_map.get(tid)
        if not team:
            continue
        total = rec["w"] + rec["l"] + rec["t"]
        conf = team.conference or "Other"
        div = team.division or "Unknown"
        grouped.setdefault(conf, {}).setdefault(div, []).append({
            "team_id": tid,
            "name": team.name,
            "abbreviation": team.abbreviation,
            "color": team.primary_color or "#6c757d",
            "logo_url": team.logo_url,
            "wins": rec["w"], "losses": rec["l"], "ties": rec["t"],
            "pct": round(rec["w"] / total, 3) if total else 0.0,
            "pf": rec["pf"], "pa": rec["pa"],
            "diff": rec["pf"] - rec["pa"],
            "home": f"{rec['hw']}-{rec['hl']}",
            "away": f"{rec['aw']}-{rec['al']}",
            "games_played": total,
        })

    # Sort each division by wins desc, then pct desc
    for conf in grouped:
        for div in grouped[conf]:
            grouped[conf][div].sort(key=lambda x: (-x["wins"], -x["pct"]))

    return grouped


# ── Team Season Performance ───────────────────────────────────────────────────

def get_team_record(team_id: int, season_year: int | None = None) -> dict:
    """
    Full season record for a single team: W-L-T, home/away splits,
    PPG / PAPG, and week-by-week game log.
    """
    q = Game.query.filter(
        db.or_(Game.home_team_id == team_id, Game.away_team_id == team_id),
        Game.home_score.isnot(None),
        Game.away_score.isnot(None),
        db.or_(
            Game.status.ilike("%final%"),
            Game.status.ilike("%complete%"),
        ),
    )
    if season_year:
        q = q.filter(Game.season_year == season_year)
    games = q.order_by(Game.game_date).all()

    w = l = t = hw = hl = aw = al = pf = pa = 0
    game_log = []

    for g in games:
        is_home = g.home_team_id == team_id
        my_score = (g.home_score if is_home else g.away_score) or 0
        opp_score = (g.away_score if is_home else g.home_score) or 0
        opp_id = g.away_team_id if is_home else g.home_team_id
        opp = team_map_single(opp_id)

        if my_score > opp_score:
            w += 1
            if is_home:
                hw += 1
            else:
                aw += 1
            result = "W"
        elif opp_score > my_score:
            l += 1
            if is_home:
                hl += 1
            else:
                al += 1
            result = "L"
        else:
            t += 1
            result = "T"

        pf += my_score
        pa += opp_score
        game_log.append({
            "week": g.week,
            "date": g.game_date.strftime("%b %-d") if g.game_date else None,
            "home": is_home,
            "opponent": opp["abbreviation"],
            "opponent_color": opp["color"],
            "pf": my_score,
            "pa": opp_score,
            "result": result,
        })

    team = Team.query.get(team_id) or Team()
    total = w + l + t
    n = len(game_log)
    return {
        "team_id": team_id,
        "name": getattr(team, "name", ""),
        "abbreviation": getattr(team, "abbreviation", ""),
        "color": getattr(team, "primary_color", None) or "#69BE28",
        "logo_url": getattr(team, "logo_url", None),
        "conference": getattr(team, "conference", ""),
        "division": getattr(team, "division", ""),
        "wins": w, "losses": l, "ties": t,
        "pct": round(w / total, 3) if total else 0.0,
        "pf": pf, "pa": pa, "diff": pf - pa,
        "ppg": round(pf / n, 1) if n else 0.0,
        "papg": round(pa / n, 1) if n else 0.0,
        "home_record": f"{hw}-{hl}",
        "away_record": f"{aw}-{al}",
        "games": game_log,
        "total_games": n,
    }


def team_map_single(team_id) -> dict:
    """Quick team lookup returning a safe dict even if not found."""
    if not team_id:
        return {"abbreviation": "?", "color": "#6c757d"}
    team = Team.query.get(team_id)
    if not team:
        return {"abbreviation": "?", "color": "#6c757d"}
    return {"abbreviation": team.abbreviation or "?",
            "color": team.primary_color or "#6c757d"}


# ── Weekly Scoring Trends ─────────────────────────────────────────────────────

def get_weekly_scoring(season_year: int | None = None) -> list[dict]:
    """Average combined score + home/away PPG by week."""
    from collections import defaultdict
    q = Game.query.filter(
        Game.home_score.isnot(None),
        Game.away_score.isnot(None),
        Game.week.isnot(None),
        db.or_(
            Game.status.ilike("%final%"),
            Game.status.ilike("%complete%"),
        ),
    )
    if season_year:
        q = q.filter(Game.season_year == season_year)
    games = q.all()

    week_totals: dict = defaultdict(list)
    week_home: dict = defaultdict(list)
    week_away: dict = defaultdict(list)
    for g in games:
        hs = g.home_score or 0
        as_ = g.away_score or 0
        week_totals[g.week].append(hs + as_)
        week_home[g.week].append(hs)
        week_away[g.week].append(as_)

    result = []
    for wk in sorted(week_totals):
        tots = week_totals[wk]
        n = len(tots)
        result.append({
            "week": wk,
            "label": f"Wk {wk}",
            "avg_total": round(sum(tots) / n, 1),
            "avg_home": round(sum(week_home[wk]) / n, 1),
            "avg_away": round(sum(week_away[wk]) / n, 1),
            "games": n,
        })
    return result
