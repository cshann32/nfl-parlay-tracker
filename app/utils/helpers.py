"""Utility helpers: odds math, payout calculation, date utilities."""
from decimal import Decimal, ROUND_HALF_UP


def american_to_decimal(american: int) -> Decimal:
    """Convert American odds to decimal odds."""
    if american > 0:
        return Decimal(american) / 100 + 1
    else:
        return Decimal(100) / abs(american) + 1


def calculate_parlay_payout(bet_amount: Decimal, leg_odds: list[int]) -> Decimal:
    """
    Calculate potential parlay payout from a list of American odds.
    Returns total payout (bet + profit).
    """
    multiplier = Decimal("1")
    for odds in leg_odds:
        multiplier *= american_to_decimal(odds)
    return (bet_amount * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_profit(payout: Decimal, bet_amount: Decimal) -> Decimal:
    return (payout - bet_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def implied_probability(american: int) -> float:
    """Convert American odds to implied probability (0-1)."""
    if american > 0:
        return 100 / (american + 100)
    else:
        return abs(american) / (abs(american) + 100)


def format_american_odds(odds: int) -> str:
    """Format American odds with sign: +150, -110."""
    return f"+{odds}" if odds > 0 else str(odds)


def roi(total_wagered: Decimal, total_payout: Decimal) -> float:
    """Return ROI as a percentage."""
    if total_wagered == 0:
        return 0.0
    return float(((total_payout - total_wagered) / total_wagered) * 100)
