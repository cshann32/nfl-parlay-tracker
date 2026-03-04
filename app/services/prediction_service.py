"""
Prediction engine — uses historical game scores and parlay history
to surface predictions and betting insights.

All math is rule-based (no ML library required):
- Team strength = points scored/allowed per game
- Game outcome = expected point margin → sigmoid → win probability
- Home-field advantage = +3 points (NFL historical average)
"""
import math
import logging
from collections import defaultdict
from sqlalchemy import func
from app.extensions import db
from app.models.game import Game
from app.models.team import Team
from app.models.parlay import Parlay, ParlayLeg, ParlayStatus, LegResult, LegType

logger = logging.getLogger("nfl.prediction")

HOME_FIELD_ADVANTAGE = 3.0   # points
SIGMOID_SCALE = 7.0          # points per unit of probability; ≈ 1 score = 50% → 73%


# ── Internal helpers ──────────────────────────────────────────────────────────

def _team_scoring(team_id: int, season_year: int | None, last_n: int | None = None):
    """Return avg points scored and allowed for a team. Returns None if no data."""
    q = Game.query.filter(
        Game.status.ilike("%final%"),
        Game.home_score.isnot(None),
        ((Game.home_team_id == team_id) | (Game.away_team_id == team_id)),
    )
    if season_year:
        q = q.filter(Game.season_year == season_year)
    if last_n:
        q = q.order_by(Game.game_date.desc()).limit(last_n)
    games = q.all()
    if not games:
        return None
    scored, allowed = [], []
    for g in games:
        if g.home_team_id == team_id:
            scored.append(g.home_score)
            allowed.append(g.away_score)
        else:
            scored.append(g.away_score)
            allowed.append(g.home_score)
    return {
        "ppg": round(sum(scored) / len(scored), 1),
        "papg": round(sum(allowed) / len(allowed), 1),
        "games": len(games),
    }


def _sigmoid_prob(margin: float) -> float:
    """Convert expected point margin to win probability [0..1] using logistic curve."""
    return round(1 / (1 + math.exp(-margin / SIGMOID_SCALE)), 3)


def _margin_label(margin: float) -> str:
    if abs(margin) < 1:
        return "Pick 'em"
    side = "home" if margin > 0 else "away"
    return f"{side} by {abs(margin):.1f}"


# ── Public API ────────────────────────────────────────────────────────────────

def predict_game_outcome(home_team_id: int, away_team_id: int,
                         season_year: int = 2025) -> dict:
    """
    Predict the likely winner and score for a head-to-head matchup.

    Uses a weighted blend of full-season and last-5-game averages:
      - 60% season average, 40% recent form
    Home-field advantage adds +3 to the home team's expected margin.
    Win probability is derived from a sigmoid on the expected margin.
    """
    home_season = _team_scoring(home_team_id, season_year)
    away_season = _team_scoring(away_team_id, season_year)
    home_recent = _team_scoring(home_team_id, season_year, last_n=5)
    away_recent = _team_scoring(away_team_id, season_year, last_n=5)

    # Fallback to previous year if current season has < 4 games
    if home_season is None or home_season["games"] < 4:
        home_season = _team_scoring(home_team_id, season_year - 1) or home_season
    if away_season is None or away_season["games"] < 4:
        away_season = _team_scoring(away_team_id, season_year - 1) or away_season

    if not home_season or not away_season:
        return {"error": "Insufficient game data to generate a prediction."}

    # Blend season (60%) + recent (40%)
    def blend(season_val, recent_val, key):
        if recent_val and recent_val["games"] >= 3:
            return season_val[key] * 0.6 + recent_val[key] * 0.4
        return season_val[key]

    home_off = blend(home_season, home_recent, "ppg")
    home_def = blend(home_season, home_recent, "papg")
    away_off = blend(away_season, away_recent, "ppg")
    away_def = blend(away_season, away_recent, "papg")

    # Expected scores
    home_exp = round((home_off + away_def) / 2 + HOME_FIELD_ADVANTAGE, 1)
    away_exp = round((away_off + home_def) / 2, 1)
    margin = round(home_exp - away_exp, 1)
    home_win_prob = _sigmoid_prob(margin)

    home_team = Team.query.get(home_team_id)
    away_team = Team.query.get(away_team_id)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_exp": home_exp,
        "away_exp": away_exp,
        "margin": margin,
        "margin_label": _margin_label(margin),
        "home_win_prob": home_win_prob,
        "away_win_prob": round(1 - home_win_prob, 3),
        "home_season": home_season,
        "away_season": away_season,
        "home_recent": home_recent,
        "away_recent": away_recent,
        "confidence": _confidence_label(home_win_prob),
        "season_year": season_year,
    }


def _confidence_label(prob: float) -> str:
    p = max(prob, 1 - prob)  # always the higher side
    if p >= 0.75:
        return "High"
    if p >= 0.62:
        return "Medium"
    return "Low"


def get_power_rankings(season_year: int = 2025) -> list[dict]:
    """
    Rank all teams by point differential per game (PPG scored − allowed).
    Returns a list of dicts sorted best → worst.
    """
    teams = Team.query.order_by(Team.name).all()
    rows = []
    for team in teams:
        data = _team_scoring(team.id, season_year)
        if not data or data["games"] < 2:
            # Try prior season
            data = _team_scoring(team.id, season_year - 1)
        if not data or data["games"] < 2:
            continue
        rows.append({
            "team": team,
            "ppg": data["ppg"],
            "papg": data["papg"],
            "diff": round(data["ppg"] - data["papg"], 1),
            "games": data["games"],
        })
    rows.sort(key=lambda r: r["diff"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def get_user_betting_insights(user_id: int) -> dict:
    """
    Analyse a user's parlay history and return structured insights:
    - Overall win rate and ROI
    - Breakdown by leg count, bet type, and sportsbook
    - Current win/loss streak
    """
    parlays = (
        Parlay.query
        .filter_by(user_id=user_id)
        .filter(Parlay.status != ParlayStatus.PENDING)
        .order_by(Parlay.bet_date.asc())
        .all()
    )

    if not parlays:
        return {"no_data": True}

    # ── Overall ───────────────────────────────────────────────────────────────
    total = len(parlays)
    won = sum(1 for p in parlays if p.status == ParlayStatus.WON)
    lost = sum(1 for p in parlays if p.status == ParlayStatus.LOST)
    push = total - won - lost
    total_wagered = sum(float(p.bet_amount) for p in parlays)
    total_returned = sum(
        float(p.actual_payout or 0) if p.status == ParlayStatus.WON else float(p.bet_amount) if p.status == ParlayStatus.PUSH else 0
        for p in parlays
    )
    profit = round(total_returned - total_wagered, 2)
    roi = round(profit / total_wagered * 100, 1) if total_wagered else 0
    win_rate = round(won / total * 100, 1) if total else 0

    # ── By leg count ──────────────────────────────────────────────────────────
    by_legs: dict[int, dict] = defaultdict(lambda: {"won": 0, "total": 0, "wagered": 0.0, "returned": 0.0})
    for p in parlays:
        lc = p.leg_count
        by_legs[lc]["total"] += 1
        by_legs[lc]["wagered"] += float(p.bet_amount)
        if p.status == ParlayStatus.WON:
            by_legs[lc]["won"] += 1
            by_legs[lc]["returned"] += float(p.actual_payout or 0)
        elif p.status == ParlayStatus.PUSH:
            by_legs[lc]["returned"] += float(p.bet_amount)
    by_legs_list = sorted(
        [{"legs": k, **v,
          "win_rate": round(v["won"] / v["total"] * 100, 1) if v["total"] else 0,
          "roi": round((v["returned"] - v["wagered"]) / v["wagered"] * 100, 1) if v["wagered"] else 0}
         for k, v in by_legs.items()],
        key=lambda x: x["legs"]
    )

    # ── By sportsbook ─────────────────────────────────────────────────────────
    by_book: dict[str, dict] = defaultdict(lambda: {"won": 0, "total": 0, "wagered": 0.0, "returned": 0.0})
    for p in parlays:
        book = p.sportsbook or "Unknown"
        by_book[book]["total"] += 1
        by_book[book]["wagered"] += float(p.bet_amount)
        if p.status == ParlayStatus.WON:
            by_book[book]["won"] += 1
            by_book[book]["returned"] += float(p.actual_payout or 0)
        elif p.status == ParlayStatus.PUSH:
            by_book[book]["returned"] += float(p.bet_amount)
    by_book_list = sorted(
        [{"book": k, **v,
          "win_rate": round(v["won"] / v["total"] * 100, 1) if v["total"] else 0,
          "roi": round((v["returned"] - v["wagered"]) / v["wagered"] * 100, 1) if v["wagered"] else 0}
         for k, v in by_book.items()],
        key=lambda x: -x["total"]
    )

    # ── By leg type ───────────────────────────────────────────────────────────
    by_type: dict[str, dict] = defaultdict(lambda: {"won": 0, "total": 0})
    for p in parlays:
        for leg in p.legs:
            lt = leg.leg_type.value if leg.leg_type else "unknown"
            by_type[lt]["total"] += 1
            if leg.result == LegResult.WON:
                by_type[lt]["won"] += 1
    by_type_list = sorted(
        [{"leg_type": k, **v,
          "win_rate": round(v["won"] / v["total"] * 100, 1) if v["total"] else 0}
         for k, v in by_type.items()],
        key=lambda x: -x["total"]
    )

    # ── Streak ────────────────────────────────────────────────────────────────
    streak = 0
    streak_type = None
    for p in reversed(parlays):
        if p.status == ParlayStatus.WON:
            result = "W"
        elif p.status == ParlayStatus.LOST:
            result = "L"
        else:
            break  # push breaks streak counting
        if streak_type is None:
            streak_type = result
        if result == streak_type:
            streak += 1
        else:
            break

    # ── Recent 10 results for sparkline ───────────────────────────────────────
    recent = []
    for p in parlays[-10:]:
        if p.status == ParlayStatus.WON:
            recent.append("W")
        elif p.status == ParlayStatus.LOST:
            recent.append("L")
        else:
            recent.append("P")

    return {
        "no_data": False,
        "total": total,
        "won": won,
        "lost": lost,
        "push": push,
        "win_rate": win_rate,
        "total_wagered": total_wagered,
        "profit": profit,
        "roi": roi,
        "by_legs": by_legs_list,
        "by_book": by_book_list,
        "by_type": by_type_list,
        "streak": streak,
        "streak_type": streak_type,
        "recent": recent,
    }


# ── Season state detection ────────────────────────────────────────────────────

def detect_season_state(season_year: int | None = None) -> dict:
    """
    Determine the current NFL season state from the game database.

    Returns a dict:
      state         : "offseason" | "regular_season" | "playoffs"
      season_year   : int  — the season being examined
      upcoming_count: int  — non-final games remaining
      completed_count: int — final games played
      current_week  : int | None — lowest upcoming week number (None if offseason)
      label         : str  — human-readable phase label
    """
    from datetime import date
    from sqlalchemy import func as sqlfunc

    today = date.today()

    # Pick season year: Jan–Mar belongs to the *previous* calendar year's season
    if season_year is None:
        season_year = today.year - 1 if today.month <= 3 else today.year

    upcoming_count = (
        Game.query
        .filter(
            Game.season_year == season_year,
            Game.home_team_id.isnot(None),
            Game.away_team_id.isnot(None),
            ~Game.status.ilike("%final%"),
            ~Game.status.ilike("%cancelled%"),
        )
        .count()
    )

    completed_count = (
        Game.query
        .filter(Game.season_year == season_year, Game.status.ilike("%final%"))
        .count()
    )

    if upcoming_count > 0:
        # Find the earliest upcoming week
        current_week = (
            db.session.query(sqlfunc.min(Game.week))
            .filter(
                Game.season_year == season_year,
                ~Game.status.ilike("%final%"),
                Game.week.isnot(None),
            )
            .scalar()
        )
        max_week = (
            db.session.query(sqlfunc.max(Game.week))
            .filter(
                Game.season_year == season_year,
                ~Game.status.ilike("%final%"),
                Game.week.isnot(None),
            )
            .scalar()
        )
        # NFL regular season = weeks 1–18; playoffs start week 19+
        if max_week and max_week > 18:
            state = "playoffs"
            label = f"NFL Playoffs · {season_year}–{season_year + 1}"
        else:
            state = "regular_season"
            wk_str = f"Week {current_week}" if current_week else "In Progress"
            label = f"Regular Season · {wk_str} · {season_year}"
    else:
        state = "offseason"
        current_week = None
        if today.month in (2, 3):
            label = f"Off-Season · {season_year} · Free Agency & Draft Prep"
        elif today.month in (4, 5, 6, 7):
            label = f"Off-Season · {season_year} · OTAs & Draft"
        elif today.month in (8, 9):
            label = f"Pre-Season · {season_year + 1} Season Approaching"
        else:
            label = f"Off-Season · {season_year}"

    return {
        "state": state,
        "season_year": season_year,
        "upcoming_count": upcoming_count,
        "completed_count": completed_count,
        "current_week": current_week,
        "label": label,
    }


# ── Season prediction cards ───────────────────────────────────────────────────

def get_season_predictions(season_year: int = 2025) -> list[dict]:
    """
    Generate fun, data-driven prediction cards for the NEXT season based on
    the most recently completed season's stats.
    Returns a list of card dicts, each with:
      category, headline, subtext, stat, confidence, icon, logo, color,
      player_img (optional), next_season
    """
    from app.models.player import Player
    from app.models.stat import PlayerStat

    next_year = season_year + 1
    cards: list[dict] = []

    # ── Helper: top player by a stat ──────────────────────────────────────────
    def _top_player(cat: str, stype: str):
        row = (
            db.session.query(Player, PlayerStat.value)
            .join(PlayerStat, PlayerStat.player_id == Player.id)
            .filter(
                PlayerStat.stat_category == cat,
                PlayerStat.stat_type == stype,
                PlayerStat.season_year == season_year,
                PlayerStat.game_id.is_(None),
            )
            .order_by(PlayerStat.value.desc())
            .first()
        )
        return row  # (Player, value) or None

    # ── Team-based picks ──────────────────────────────────────────────────────
    rankings = get_power_rankings(season_year=season_year)
    if not rankings:
        rankings = get_power_rankings(season_year=season_year - 1)

    if rankings:
        top = rankings[0]
        cards.append({
            "category": f"{next_year} SUPER BOWL PICK",
            "headline": top["team"].name,
            "subtext": f"Best team in {season_year} · built to win in {next_year}",
            "stat": f"{top['ppg']} PPG scored · {top['papg']} PPG allowed in {season_year}",
            "confidence": _confidence_label(0.5 + min(abs(top["diff"]) / 28, 0.45)),
            "icon": "bi-trophy-fill",
            "logo": top["team"].logo_url,
            "color": top["team"].primary_color or "#69BE28",
        })

        # AFC / NFC champions
        afc = [r for r in rankings if r["team"].conference == "AFC"]
        nfc = [r for r in rankings if r["team"].conference == "NFC"]
        for conf_label, conf_list in [("AFC", afc), ("NFC", nfc)]:
            if conf_list:
                t = conf_list[0]
                cards.append({
                    "category": f"{next_year} {conf_label} CHAMPION PICK",
                    "headline": t["team"].name,
                    "subtext": f"Top {conf_label} team in {season_year} · primed for {next_year}",
                    "stat": f"+{t['diff']} pt/gm differential · {t['ppg']} PPG in {season_year}",
                    "confidence": "Medium",
                    "icon": "bi-shield-fill-check",
                    "logo": t["team"].logo_url,
                    "color": t["team"].primary_color or "#69BE28",
                })

        # Best offense
        best_off = max(rankings, key=lambda r: r["ppg"])
        cards.append({
            "category": f"{next_year} BEST OFFENSE",
            "headline": best_off["team"].name,
            "subtext": f"Highest-scoring offense in {season_year} · should carry over",
            "stat": f"{best_off['ppg']} points per game in {season_year}",
            "confidence": "High",
            "icon": "bi-fire",
            "logo": best_off["team"].logo_url,
            "color": best_off["team"].primary_color or "#69BE28",
        })

        # Best defense
        best_def = min(rankings, key=lambda r: r["papg"])
        cards.append({
            "category": f"{next_year} BEST DEFENSE",
            "headline": best_def["team"].name,
            "subtext": f"Locked down opponents in {season_year} · watch out in {next_year}",
            "stat": f"Allowed only {best_def['papg']} PPG in {season_year}",
            "confidence": "High",
            "icon": "bi-shield-lock-fill",
            "logo": best_def["team"].logo_url,
            "color": best_def["team"].primary_color or "#69BE28",
        })

        # Most improved (year over year)
        prior = get_power_rankings(season_year=season_year - 1)
        if prior:
            prior_map = {r["team"].id: r["diff"] for r in prior}
            deltas = [(round(r["diff"] - prior_map.get(r["team"].id, r["diff"]), 1), r)
                      for r in rankings if r["team"].id in prior_map]
            deltas.sort(key=lambda x: -x[0])
            if deltas and deltas[0][0] > 1:
                delta, t = deltas[0]
                cards.append({
                    "category": f"{next_year} MOST IMPROVED",
                    "headline": t["team"].name,
                    "subtext": f"Biggest turnaround from {season_year - 1} → {season_year} · trending up",
                    "stat": f"+{delta} pt/gm swing · could be a {next_year} contender",
                    "confidence": "Medium",
                    "icon": "bi-graph-up-arrow",
                    "logo": t["team"].logo_url,
                    "color": t["team"].primary_color or "#69BE28",
                })
            # Sleeper pick — strong differential but not top overall
            if len(rankings) >= 5:
                sleeper = rankings[4]  # #5 team — good but overlooked
                cards.append({
                    "category": f"{next_year} SLEEPER PICK",
                    "headline": sleeper["team"].name,
                    "subtext": f"#{sleeper['rank']} in {season_year} · flying under the radar for {next_year}",
                    "stat": f"+{sleeper['diff']} pt/gm · {sleeper['ppg']} PPG in {season_year}",
                    "confidence": "Low",
                    "icon": "bi-eye-slash-fill",
                    "logo": sleeper["team"].logo_url,
                    "color": sleeper["team"].primary_color or "#69BE28",
                })

    # ── Player award picks ─────────────────────────────────────────────────────
    # (cat, stat_type, category, subtext_tmpl, icon, unit)
    # {next} and {season} are replaced below
    _player_cards = [
        ("passing",   "YDS",  "MVP CANDIDATE",     "Led the league in passing in {season} · {next} MVP favorite",    "bi-person-fill-up",    "passing yards"),
        ("rushing",   "YDS",  "RUSHING CROWN",     "Top rusher in {season} · can he repeat in {next}?",              "bi-lightning-fill",    "rushing yards"),
        ("receiving", "YDS",  "RECEIVING TITLE",   "Most receiving yards in {season} · {next} title contender",      "bi-bullseye",          "receiving yards"),
        ("passing",   "TD",   "PASSING TD LEADER", "Most TD passes in {season} · watch out in {next}",               "bi-star-fill",         "passing TDs"),
        ("rushing",   "TD",   "RUSHING TD LEADER", "Best red zone rusher in {season} · {next} TD machine",           "bi-record-circle-fill","rushing TDs"),
    ]
    for cat, stype, category, subtext_tmpl, icon, unit in _player_cards:
        row = _top_player(cat, stype)
        if not row:
            continue
        player, value = row
        team = player.team
        val_int = int(float(value))
        val_fmt = f"{val_int:,}" if val_int >= 1000 else str(val_int)
        subtext = subtext_tmpl.replace("{season}", str(season_year)).replace("{next}", str(next_year))
        cards.append({
            "category": f"{next_year} {category}",
            "headline": player.name,
            "subtext": subtext,
            "stat": f"{val_fmt} {unit} in {season_year} · projected {next_year} leader",
            "confidence": "Medium",
            "icon": icon,
            "logo": team.logo_url if team else None,
            "color": (team.primary_color if team else None) or "#69BE28",
            "player_img": player.image_url,
            "team_abbr": team.abbreviation if team else "",
        })

    return cards
