import calendar as _calendar
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from flask import render_template
from flask_login import login_required, current_user
from app.blueprints.dashboard import dashboard_bp
from app.extensions import db
from app.services.parlay_service import get_analytics

logger = logging.getLogger("nfl.dashboard")

# Simple in-process cache (key → (timestamp, articles))
_news_cache: dict = {}
_NEWS_TTL = 900  # 15 minutes

_ESPN_JSON_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
_ESPN_RSS_URL  = "https://www.espn.com/espn/rss/nfl/news"


def _fetch_espn_json(limit: int = 25) -> list[dict]:
    """Fetch NFL news from ESPN's public JSON API (has real thumbnails, no key needed)."""
    cached = _news_cache.get("espn_json")
    if cached and (time.time() - cached[0]) < _NEWS_TTL:
        return cached[1]
    try:
        import requests
        resp = requests.get(_ESPN_JSON_URL, timeout=5, params={"limit": limit},
                            headers={"User-Agent": "NFL-Parlay-Tracker/1.0"})
        resp.raise_for_status()
        data = resp.json()
        items = []
        for a in data.get("articles", []):
            imgs = a.get("images", [])
            # Prefer 'header' type image, fall back to first available
            img = next((i for i in imgs if i.get("type") == "header"), imgs[0] if imgs else None)
            pub = a.get("published") or ""
            try:
                from datetime import datetime, timezone
                published_at = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None
            except (ValueError, TypeError):
                published_at = None
            items.append({
                "title":        a.get("headline") or "",
                "link":         (a.get("links") or {}).get("web", {}).get("href") or "#",
                "description":  a.get("description") or "",
                "pub_date":     pub[:25] if pub else "",
                "thumbnail":    img.get("url") if img else None,
                "published_at": published_at,
            })
        _news_cache["espn_json"] = (time.time(), items)
        return items
    except Exception as exc:
        logger.warning("ESPN JSON fetch failed", extra={"error": str(exc)})
        return cached[1] if cached else []


def _fetch_rss(url: str, limit: int = 25) -> list[dict]:
    """Fetch and parse an RSS feed (fallback — ESPN RSS has no images)."""
    cached = _news_cache.get(url)
    if cached and (time.time() - cached[0]) < _NEWS_TTL:
        return cached[1]
    try:
        import requests
        resp = requests.get(url, timeout=5,
                            headers={"User-Agent": "NFL-Parlay-Tracker/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"media": "http://search.yahoo.com/mrss/"}
        items = []
        for item in root.findall(".//item")[:limit]:
            thumb = None
            mt = item.find("media:thumbnail", ns)
            if mt is not None: thumb = mt.get("url")
            if not thumb:
                mc = item.find("media:content", ns)
                if mc is not None: thumb = mc.get("url")
            pub = item.findtext("pubDate") or ""
            items.append({
                "title":       item.findtext("title") or "",
                "link":        item.findtext("link") or "",
                "description": item.findtext("description") or "",
                "pub_date":    pub[:25] if pub else "",
                "thumbnail":   thumb,
            })
        _news_cache[url] = (time.time(), items)
        return items
    except Exception as exc:
        logger.warning("RSS fetch failed", extra={"url": url, "error": str(exc)})
        return cached[1] if cached else []


def _next_season_kickoff() -> str:
    """Return an ISO-8601 datetime string for the next NFL regular season kickoff.

    NFL Kickoff Night is always the Thursday evening after Labor Day
    (first Monday of September).  Game time: 8:20 PM ET (EDT = UTC-4).
    """
    from datetime import date
    today = date.today()
    kickoff_year = today.year if today.month < 9 else today.year + 1
    # Find the first Monday of September
    month_cal = _calendar.monthcalendar(kickoff_year, 9)
    first_monday = next(w[_calendar.MONDAY] for w in month_cal if w[_calendar.MONDAY] != 0)
    kickoff_thursday = first_monday + 3  # Thursday = Monday + 3
    EDT = timezone(timedelta(hours=-4))
    return datetime(kickoff_year, 9, kickoff_thursday, 20, 20, 0, tzinfo=EDT).isoformat()


def _recent_odds(limit: int = 6):
    """Return up to `limit` Odds records for the most recently completed games."""
    from app.models.game import Game
    from app.models.odds import Odds
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload

    # Pick one odds row per game (the earliest-inserted one)
    first_odds_sq = (
        db.session.query(func.min(Odds.id).label("odds_id"), Odds.game_id)
        .group_by(Odds.game_id)
        .subquery()
    )
    return (
        db.session.query(Odds)
        .join(first_odds_sq, Odds.id == first_odds_sq.c.odds_id)
        .join(Game, Game.id == Odds.game_id)
        .options(
            joinedload(Odds.game).joinedload(Game.home_team),
            joinedload(Odds.game).joinedload(Game.away_team),
        )
        .filter(Game.status.ilike("%final%"), Game.home_score.isnot(None))
        .order_by(Game.game_date.desc())
        .limit(limit)
        .all()
    )


SEA_TEAM_ID = 29  # Seattle Seahawks DB id


def _seahawks_record():
    """Return {season: {wins, losses}} for 2024 and 2025."""
    from app.models.game import Game
    from sqlalchemy import func
    records = {}
    for year in (2024, 2025):
        games = Game.query.filter(
            Game.season_year == year,
            Game.status.ilike("%final%"),
            Game.home_score.isnot(None),
            ((Game.home_team_id == SEA_TEAM_ID) | (Game.away_team_id == SEA_TEAM_ID))
        ).all()
        wins = sum(
            1 for g in games
            if (g.home_team_id == SEA_TEAM_ID and g.home_score > g.away_score) or
               (g.away_team_id == SEA_TEAM_ID and g.away_score > g.home_score)
        )
        losses = sum(
            1 for g in games
            if (g.home_team_id == SEA_TEAM_ID and g.home_score < g.away_score) or
               (g.away_team_id == SEA_TEAM_ID and g.away_score < g.home_score)
        )
        records[year] = {"wins": wins, "losses": losses, "total": len(games)}
    return records


def _recent_games(limit=5):
    """Return the most recently completed games."""
    from app.models.game import Game
    from sqlalchemy.orm import joinedload
    return (Game.query
            .options(joinedload(Game.home_team), joinedload(Game.away_team))
            .filter(Game.status.ilike("%final%"), Game.home_score.isnot(None))
            .order_by(Game.game_date.desc())
            .limit(limit).all())


def _game_predictions_for_dashboard(limit=6, season_year=2025):
    """
    Return game prediction data for the dashboard.
    - Upcoming games exist → predict those (in-season view).
    - Season complete → run predictions on the most recent games and compare
      to actual results (post-season accuracy view).
    Also returns the top-5 power-ranked teams.
    """
    from app.models.game import Game
    from sqlalchemy.orm import joinedload
    from app.services.prediction_service import predict_game_outcome, get_power_rankings

    base_q = (Game.query
              .options(joinedload(Game.home_team), joinedload(Game.away_team))
              .filter(
                  Game.home_team_id.isnot(None),
                  Game.away_team_id.isnot(None),
                  Game.season_year == season_year,
              ))

    # Check for upcoming games first
    upcoming = (base_q
                .filter(~Game.status.ilike("%final%"))
                .order_by(Game.game_date.asc())
                .limit(limit)
                .all())

    is_upcoming = bool(upcoming)
    games_to_predict = upcoming if is_upcoming else (
        base_q
        .filter(Game.status.ilike("%final%"), Game.home_score.isnot(None))
        .order_by(Game.game_date.desc())
        .limit(limit)
        .all()
    )

    # For completed-season view use prior year stats so prediction is "blind"
    pred_season = season_year - 1 if not is_upcoming else season_year

    predictions = []
    for g in games_to_predict:
        try:
            pred = predict_game_outcome(g.home_team_id, g.away_team_id,
                                        season_year=pred_season)
            if pred.get("error"):
                continue
            entry = {"game": g, "pred": pred, "is_upcoming": is_upcoming}
            if not is_upcoming and g.home_score is not None and g.away_score is not None:
                actual_home_won = g.home_score > g.away_score
                predicted_home_won = pred["margin"] >= 0
                entry["actual_home_won"] = actual_home_won
                entry["actual_score"] = f"{g.away_score}–{g.home_score}"
                entry["correct"] = actual_home_won == predicted_home_won
            predictions.append(entry)
        except Exception:
            pass

    top_teams = get_power_rankings(season_year=season_year)[:5]
    return predictions, top_teams, is_upcoming


@dashboard_bp.route("/")
@login_required
def index():
    from app.services.prediction_service import (
        get_season_predictions, detect_season_state
    )
    analytics = get_analytics(current_user.id)
    sea_record = _seahawks_record()
    recent_games = _recent_games()

    # Detect what phase of the NFL calendar we're in
    season_state = detect_season_state()
    active_season = season_state["season_year"]

    # Game predictions are always shown; in-season = upcoming picks, offseason = accuracy report
    game_preds, top_teams, is_upcoming = _game_predictions_for_dashboard(season_year=active_season)

    # Season-prediction carousel — always shown
    # During offseason we project the NEXT season; during regular season we show current-season accolades
    carousel_season = active_season if season_state["state"] == "offseason" else active_season
    season_predictions = get_season_predictions(season_year=carousel_season)

    # Fetch a handful of headlines for the dashboard news strip
    articles = _fetch_espn_json(limit=6)

    # Offseason extras: closing lines from the DB + countdown to next kickoff
    is_offseason = season_state["state"] == "offseason"
    recent_odds = _recent_odds() if is_offseason else []
    kickoff_iso = _next_season_kickoff()

    logger.info("Dashboard loaded", extra={"user_id": current_user.id,
                                           "season_state": season_state["state"]})
    return render_template(
        "dashboard/index.html",
        analytics=analytics,
        sea_record=sea_record,
        recent_games=recent_games,
        game_preds=game_preds,
        top_teams=top_teams,
        is_upcoming=is_upcoming,
        season_predictions=season_predictions,
        season_state=season_state,
        articles=articles,
        recent_odds=recent_odds,
        kickoff_iso=kickoff_iso,
        is_offseason=is_offseason,
    )


@dashboard_bp.route("/news")
@login_required
def news():
    # Primary: ESPN JSON API (has real cover images, free, no key)
    # Fallback: ESPN RSS (no images, but still current news)
    espn = _fetch_espn_json(limit=25)
    if espn:
        articles = espn
        source = "rss"  # display as "Live" since it's real-time ESPN data
    else:
        articles = _fetch_rss(_ESPN_RSS_URL)
        source = "rss"

    return render_template("dashboard/news.html", articles=articles, source=source)
