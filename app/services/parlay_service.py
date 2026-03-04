"""
Parlay service — CRUD, analytics, win/loss record, ROI, P&L.
All data from local DB only.
"""
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, case
from app.extensions import db
from app.models.parlay import Parlay, ParlayLeg, ParlayStatus, LegResult
from app.models.game import Game
from app.exceptions import ValidationException, DatabaseException
from app.utils.helpers import calculate_parlay_payout, roi

logger = logging.getLogger("nfl.parlays")


# ── Private helpers ────────────────────────────────────────────────────────────

def _resolved_parlays(user_id: int):
    """Resolved (non-pending) parlays for a user, unordered."""
    return Parlay.query.filter(
        Parlay.user_id == user_id,
        Parlay.status != ParlayStatus.PENDING,
    ).all()


def _resolved_parlays_dated(user_id: int):
    """Resolved parlays that have a bet_date, ordered chronologically."""
    return Parlay.query.filter(
        Parlay.user_id == user_id,
        Parlay.status != ParlayStatus.PENDING,
        Parlay.bet_date.isnot(None),
    ).order_by(Parlay.bet_date).all()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_parlay(user_id: int, data: dict) -> Parlay:
    logger.info("Creating parlay", extra={"user_id": user_id, "data": str(data)[:200]})
    bet_amount = Decimal(str(data.get("bet_amount", 0)))
    if bet_amount <= 0:
        raise ValidationException("Bet amount must be greater than zero",
                                  detail={"bet_amount": str(bet_amount)})

    parlay = Parlay(
        user_id=user_id,
        name=data.get("name"),
        bet_date=data.get("bet_date") or datetime.now(timezone.utc),
        bet_amount=bet_amount,
        sportsbook=data.get("sportsbook"),
        notes=data.get("notes"),
        status=ParlayStatus.PENDING,
    )
    db.session.add(parlay)
    db.session.flush()  # Get parlay.id before adding legs

    legs_data = data.get("legs", [])
    for leg_data in legs_data:
        leg = ParlayLeg(
            parlay_id=parlay.id,
            game_id=leg_data.get("game_id"),
            player_id=leg_data.get("player_id"),
            team_id=leg_data.get("team_id"),
            leg_type=leg_data["leg_type"],
            pick=leg_data["pick"],
            odds=leg_data.get("odds"),
            description=leg_data.get("description"),
        )
        db.session.add(leg)

    # Calculate potential payout
    leg_odds = [l.get("odds") for l in legs_data if l.get("odds")]
    if leg_odds:
        parlay.potential_payout = calculate_parlay_payout(bet_amount, leg_odds)

    try:
        db.session.commit()
        logger.info("Parlay created", extra={"parlay_id": parlay.id, "legs": len(legs_data)})
    except Exception as exc:
        db.session.rollback()
        raise DatabaseException("Failed to save parlay", detail={"error": str(exc)}) from exc
    return parlay


def update_parlay(parlay_id: int, user_id: int, data: dict) -> Parlay:
    parlay = _get_parlay_for_user(parlay_id, user_id)
    for field in ["name", "sportsbook", "notes", "bet_date"]:
        if field in data:
            setattr(parlay, field, data[field])
    if "status" in data:
        parlay.status = ParlayStatus(data["status"])
    if "actual_payout" in data:
        parlay.actual_payout = Decimal(str(data["actual_payout"]))
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise DatabaseException("Failed to update parlay", detail={"error": str(exc)}) from exc
    return parlay


def update_leg_result(leg_id: int, result: str) -> ParlayLeg:
    leg = ParlayLeg.query.get_or_404(leg_id)
    leg.result = LegResult(result)
    # Auto-update parlay status if all legs are resolved
    parlay = leg.parlay
    _recalculate_parlay_status(parlay)
    db.session.commit()
    return leg


def delete_parlay(parlay_id: int, user_id: int) -> None:
    parlay = _get_parlay_for_user(parlay_id, user_id)
    db.session.delete(parlay)
    db.session.commit()
    logger.info("Parlay deleted", extra={"parlay_id": parlay_id})


def get_parlay(parlay_id: int, user_id: int) -> Parlay:
    return _get_parlay_for_user(parlay_id, user_id)


def list_parlays(user_id: int, status: str | None = None,
                 page: int = 1, per_page: int = 20) -> Any:
    q = Parlay.query.filter_by(user_id=user_id).order_by(Parlay.bet_date.desc())
    if status:
        q = q.filter_by(status=ParlayStatus(status))
    return q.paginate(page=page, per_page=per_page, error_out=False)


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_analytics(user_id: int) -> dict:
    """Return comprehensive parlay analytics for a user."""
    parlays = Parlay.query.filter(
        Parlay.user_id == user_id,
        Parlay.status != ParlayStatus.PENDING,
    ).all()

    total = len(parlays)
    won = sum(1 for p in parlays if p.status == ParlayStatus.WON)
    lost = sum(1 for p in parlays if p.status == ParlayStatus.LOST)
    push = sum(1 for p in parlays if p.status == ParlayStatus.PUSH)

    total_wagered = sum(float(p.bet_amount) for p in parlays)
    total_payout = sum(float(p.actual_payout or 0) for p in parlays if p.status == ParlayStatus.WON)
    net_pl = total_payout - total_wagered

    win_rate = (won / total * 100) if total > 0 else 0
    current_roi = roi(Decimal(str(total_wagered)), Decimal(str(total_payout + (total_wagered - sum(float(p.bet_amount) for p in parlays if p.status == ParlayStatus.WON)))))

    # Streak
    streak = _calculate_streak(parlays)

    return {
        "total": total,
        "won": won,
        "lost": lost,
        "push": push,
        "win_rate": round(win_rate, 1),
        "total_wagered": round(total_wagered, 2),
        "total_payout": round(total_payout, 2),
        "net_pl": round(net_pl, 2),
        "roi": round(current_roi, 1),
        "streak": streak,
        "avg_bet": round(total_wagered / total, 2) if total > 0 else 0,
    }


def get_pl_over_time(user_id: int) -> list[dict]:
    """Return cumulative P&L data points for charting."""
    parlays = _resolved_parlays_dated(user_id)

    cumulative = 0.0
    data = []
    for p in parlays:
        cumulative += p.profit_loss
        data.append({
            "date": p.bet_date.strftime("%Y-%m-%d") if p.bet_date else None,
            "cumulative_pl": round(cumulative, 2),
            "parlay_pl": round(p.profit_loss, 2),
            "status": p.status.value,
        })
    return data


def get_bet_type_breakdown(user_id: int) -> list[dict]:
    """Return win/loss counts and win rate per leg type for all resolved legs."""
    from app.models.parlay import LegType
    legs = (
        db.session.query(ParlayLeg)
        .join(Parlay)
        .filter(
            Parlay.user_id == user_id,
            ParlayLeg.result.in_([LegResult.WON.value, LegResult.LOST.value]),
        )
        .all()
    )
    counts: dict[str, dict] = {}
    for leg in legs:
        key = leg.leg_type.value if hasattr(leg.leg_type, "value") else str(leg.leg_type)
        if key not in counts:
            counts[key] = {"type": key, "won": 0, "lost": 0}
        if leg.result == LegResult.WON or leg.result == LegResult.WON.value:
            counts[key]["won"] += 1
        else:
            counts[key]["lost"] += 1

    result = []
    for v in counts.values():
        total = v["won"] + v["lost"]
        result.append({
            **v,
            "total": total,
            "win_rate": round(v["won"] / total * 100, 1) if total > 0 else 0,
        })
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


def get_win_rate_by_week(user_id: int) -> list[dict]:
    """Return win rate per week for charting."""
    results: dict[str, dict] = {}
    parlays = _resolved_parlays_dated(user_id)

    for p in parlays:
        week_key = p.bet_date.strftime("%Y-W%W") if p.bet_date else "Unknown"
        if week_key not in results:
            results[week_key] = {"week": week_key, "won": 0, "total": 0}
        results[week_key]["total"] += 1
        if p.status == ParlayStatus.WON:
            results[week_key]["won"] += 1

    return [
        {**v, "win_rate": round(v["won"] / v["total"] * 100, 1) if v["total"] > 0 else 0}
        for v in results.values()
    ]


def get_monthly_pl(user_id: int) -> list[dict]:
    """Return P&L grouped by calendar month for charting."""
    parlays = _resolved_parlays_dated(user_id)

    monthly: dict[str, dict] = {}
    for p in parlays:
        key = p.bet_date.strftime("%Y-%m") if p.bet_date else None
        if not key:
            continue
        if key not in monthly:
            monthly[key] = {"month": key, "won": 0, "lost": 0, "total": 0, "pl": 0.0, "wagered": 0.0}
        monthly[key]["total"] += 1
        monthly[key]["wagered"] += float(p.bet_amount)
        monthly[key]["pl"] += p.profit_loss
        if p.status == ParlayStatus.WON:
            monthly[key]["won"] += 1
        elif p.status == ParlayStatus.LOST:
            monthly[key]["lost"] += 1

    result = list(monthly.values())
    for r in result:
        total = r["total"]
        r["win_rate"] = round(r["won"] / total * 100, 1) if total > 0 else 0
        r["pl"] = round(r["pl"], 2)
        r["wagered"] = round(r["wagered"], 2)
    return result


def get_sportsbook_breakdown(user_id: int) -> list[dict]:
    """Return win/loss/ROI grouped by sportsbook."""
    parlays = _resolved_parlays(user_id)

    books: dict[str, dict] = {}
    for p in parlays:
        key = p.sportsbook or "Unknown"
        if key not in books:
            books[key] = {"sportsbook": key, "won": 0, "lost": 0, "total": 0,
                          "wagered": 0.0, "payout": 0.0}
        books[key]["total"] += 1
        books[key]["wagered"] += float(p.bet_amount)
        if p.status == ParlayStatus.WON:
            books[key]["won"] += 1
            books[key]["payout"] += float(p.actual_payout or 0)
        elif p.status == ParlayStatus.LOST:
            books[key]["lost"] += 1

    result = list(books.values())
    for r in result:
        total = r["total"]
        r["win_rate"] = round(r["won"] / total * 100, 1) if total > 0 else 0
        r["net_pl"] = round(r["payout"] - r["wagered"], 2)
        r["roi"] = round((r["payout"] - r["wagered"]) / r["wagered"] * 100, 1) if r["wagered"] > 0 else 0
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


def get_leg_count_breakdown(user_id: int) -> list[dict]:
    """Return win rate, ROI and avg payout grouped by number of legs (2-leg, 3-leg, etc.)."""
    parlays = _resolved_parlays(user_id)

    by_legs: dict[int, dict] = {}
    for p in parlays:
        lc = p.leg_count or 0
        if lc < 2:
            continue
        bucket = lc if lc <= 6 else 7  # cap at "7+"
        if bucket not in by_legs:
            by_legs[bucket] = {"legs": bucket, "label": f"{bucket}+" if bucket == 7 else str(bucket),
                               "won": 0, "lost": 0, "push": 0, "total": 0,
                               "wagered": 0.0, "payout": 0.0}
        by_legs[bucket]["total"] += 1
        by_legs[bucket]["wagered"] += float(p.bet_amount)
        if p.status == ParlayStatus.WON:
            by_legs[bucket]["won"] += 1
            by_legs[bucket]["payout"] += float(p.actual_payout or 0)
        elif p.status == ParlayStatus.LOST:
            by_legs[bucket]["lost"] += 1
        else:
            by_legs[bucket]["push"] += 1

    result = sorted(by_legs.values(), key=lambda r: r["legs"])
    for r in result:
        t = r["total"]
        r["win_rate"] = round(r["won"] / t * 100, 1) if t else 0
        r["net_pl"]   = round(r["payout"] - r["wagered"], 2)
        r["roi"]      = round((r["payout"] - r["wagered"]) / r["wagered"] * 100, 1) if r["wagered"] else 0
        r["avg_payout"] = round(r["payout"] / r["won"], 2) if r["won"] else 0
    return result


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_parlay_for_user(parlay_id: int, user_id: int) -> Parlay:
    parlay = Parlay.query.filter_by(id=parlay_id, user_id=user_id).first()
    if not parlay:
        raise ValidationException(f"Parlay {parlay_id} not found",
                                  detail={"parlay_id": parlay_id, "user_id": user_id})
    return parlay


def _recalculate_parlay_status(parlay: Parlay) -> None:
    if not parlay.legs:
        return
    results = [leg.result for leg in parlay.legs]
    if LegResult.PENDING in results:
        parlay.status = ParlayStatus.PENDING
    elif all(r == LegResult.WON for r in results):
        parlay.status = ParlayStatus.WON
    elif any(r == LegResult.LOST for r in results):
        parlay.status = ParlayStatus.LOST
    elif all(r in (LegResult.WON, LegResult.PUSH) for r in results):
        parlay.status = ParlayStatus.PARTIAL


def _calculate_streak(parlays: list[Parlay]) -> dict:
    sorted_parlays = sorted(
        [p for p in parlays if p.status in (ParlayStatus.WON, ParlayStatus.LOST)],
        key=lambda p: p.bet_date or datetime.min,
        reverse=True,
    )
    if not sorted_parlays:
        return {"type": None, "count": 0}
    streak_type = sorted_parlays[0].status.value
    count = 0
    for p in sorted_parlays:
        if p.status.value == streak_type:
            count += 1
        else:
            break
    return {"type": streak_type, "count": count}
