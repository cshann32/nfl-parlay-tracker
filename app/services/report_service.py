"""
Report service — build, run, and export custom reports.
Supports CSV (pandas) and PDF (reportlab) export.
"""
import io
import logging
from datetime import datetime
from typing import Any

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from app.extensions import db
from app.models.parlay import Parlay, ParlayStatus
from app.models.stat import PlayerStat, TeamStat
from app.models.player import Player
from app.models.team import Team
from app.exceptions import ReportException

logger = logging.getLogger("nfl.reports")


def run_report(config: dict, user_id: int) -> list[dict]:
    """Execute a report based on its config dict. Returns list of row dicts."""
    report_type = config.get("type", "parlays")
    logger.info("Running report", extra={"type": report_type, "config": str(config)[:200]})

    try:
        if report_type == "parlays":
            return _run_parlay_report(config, user_id)
        elif report_type == "player_stats":
            return _run_player_stats_report(config)
        elif report_type == "team_stats":
            return _run_team_stats_report(config)
        else:
            raise ReportException(f"Unknown report type: {report_type}",
                                  detail={"type": report_type})
    except ReportException:
        raise
    except Exception as exc:
        raise ReportException("Report execution failed",
                              detail={"error": str(exc), "config": config}) from exc


def export_csv(data: list[dict], filename: str = "report") -> io.BytesIO:
    """Convert report data to CSV bytes."""
    if not data:
        raise ReportException("No data to export")
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return buf


def export_pdf(data: list[dict], title: str = "NFL Report") -> io.BytesIO:
    """Convert report data to PDF bytes using reportlab."""
    if not data:
        raise ReportException("No data to export")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    elements.append(Spacer(1, 24))

    cols = list(data[0].keys())
    header = [str(c).replace("_", " ").title() for c in cols]
    rows = [header] + [[str(row.get(c, "")) for c in cols] for row in data]

    t = Table(rows)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    return buf


# ── Report implementations ────────────────────────────────────────────────────

def _run_parlay_report(config: dict, user_id: int) -> list[dict]:
    q = Parlay.query.filter_by(user_id=user_id)
    if config.get("status"):
        q = q.filter_by(status=ParlayStatus(config["status"]))
    if config.get("date_from"):
        q = q.filter(Parlay.bet_date >= config["date_from"])
    if config.get("date_to"):
        q = q.filter(Parlay.bet_date <= config["date_to"])
    if config.get("sportsbook"):
        q = q.filter_by(sportsbook=config["sportsbook"])

    parlays = q.order_by(Parlay.bet_date.desc()).all()
    return [
        {
            "date": p.bet_date.strftime("%Y-%m-%d") if p.bet_date else "",
            "name": p.name or "",
            "sportsbook": p.sportsbook or "",
            "legs": p.leg_count,
            "bet_amount": float(p.bet_amount),
            "potential_payout": float(p.potential_payout or 0),
            "actual_payout": float(p.actual_payout or 0),
            "status": p.status.value,
            "profit_loss": round(p.profit_loss, 2),
        }
        for p in parlays
    ]


def _run_player_stats_report(config: dict) -> list[dict]:
    q = db.session.query(
        Player.name.label("player"),
        Team.abbreviation.label("team"),
        PlayerStat.stat_category,
        PlayerStat.stat_type,
        PlayerStat.value,
        PlayerStat.week,
        PlayerStat.season_year,
    ).join(Player, PlayerStat.player_id == Player.id) \
     .join(Team, Player.team_id == Team.id, isouter=True)

    if config.get("player_id"):
        q = q.filter(PlayerStat.player_id == config["player_id"])
    if config.get("team_id"):
        q = q.filter(Player.team_id == config["team_id"])
    if config.get("season_year"):
        q = q.filter(PlayerStat.season_year == config["season_year"])
    if config.get("stat_category"):
        q = q.filter(PlayerStat.stat_category == config["stat_category"])

    rows = q.order_by(Player.name, PlayerStat.season_year, PlayerStat.week).limit(2000).all()
    return [{"player": r.player, "team": r.team, "category": r.stat_category,
             "stat_type": r.stat_type, "value": float(r.value or 0),
             "week": r.week, "season": r.season_year} for r in rows]


def _run_team_stats_report(config: dict) -> list[dict]:
    q = db.session.query(
        Team.name.label("team"),
        Team.abbreviation,
        TeamStat.stat_category,
        TeamStat.stat_type,
        TeamStat.value,
        TeamStat.week,
        TeamStat.season_year,
    ).join(Team, TeamStat.team_id == Team.id)

    if config.get("team_id"):
        q = q.filter(TeamStat.team_id == config["team_id"])
    if config.get("season_year"):
        q = q.filter(TeamStat.season_year == config["season_year"])
    if config.get("stat_category"):
        q = q.filter(TeamStat.stat_category == config["stat_category"])

    rows = q.order_by(Team.name, TeamStat.season_year, TeamStat.week).limit(2000).all()
    return [{"team": r.team, "abbrev": r.abbreviation, "category": r.stat_category,
             "stat_type": r.stat_type, "value": float(r.value or 0),
             "week": r.week, "season": r.season_year} for r in rows]
