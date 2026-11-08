"""Turn a price history into a plain-English BUY / WATCH / WAIT call.

These are heuristics, not predictions. The rules, in order:
1. Very close to travel  -> BUY (fares rarely fall in the last few weeks).
2. Inside the usual booking sweet spot: at/below the typical (median)
   price -> BUY, above it -> WATCH.
3. Before the sweet spot -> WAIT, unless today's price is the lowest
   we've recorded AND at least 10% under typical (a real deal) -> BUY.
4. Past the sweet spot -> BUY (waiting is a gamble).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from statistics import median

# (earliest, latest) days before departure where fares are typically lowest
SWEET_SPOT = {
    "long_haul": (60, 200),
    "regional": (21, 100),
    "stay": (30, 120),
}


@dataclass
class Signal:
    verdict: str        # BUY | WATCH | WAIT | BOOKED
    reason: str
    current: float | None = None
    low: float | None = None
    high: float | None = None
    median: float | None = None
    change_pct: float | None = None   # vs previous check
    days_out: int | None = None


def percentile_rank(value: float, values: list[float]) -> float:
    if not values:
        return 0.5
    return sum(v <= value for v in values) / len(values)


def evaluate(series: list[float], days_out: int, category: str, booked: bool = False,
             budget: float | None = None) -> Signal:
    """`series` = cheapest price at each weekly check, oldest first (latest last)."""
    if booked:
        return Signal("BOOKED", "Already booked.", days_out=days_out)
    if not series:
        return Signal("WATCH", "No prices yet.", days_out=days_out)

    cur = series[-1]
    prev = series[-2] if len(series) > 1 else None
    s = Signal("WATCH", "", current=cur, low=min(series), high=max(series), median=median(series),
               change_pct=round((cur - prev) / prev * 100, 1) if prev else None, days_out=days_out)
    early, late = SWEET_SPOT[category]
    over_budget = budget is not None and cur > budget

    if days_out <= 21:
        s.verdict, s.reason = "BUY", f"Only {days_out} days out — prices usually climb from here."
    elif early <= days_out <= late:
        if len(series) < 3:
            s.verdict, s.reason = "WATCH", "In the booking window, but still building price history."
        elif cur <= s.median and not over_budget:
            s.verdict, s.reason = "BUY", "In the booking window and at or below the typical price."
        else:
            s.verdict, s.reason = "WATCH", "In the booking window but above the typical price — check again next week."
    elif days_out > late:
        is_deal = len(series) >= 4 and cur <= min(series[:-1]) and cur <= 0.9 * s.median
        if is_deal and not over_budget:
            pct = round((1 - cur / s.median) * 100)
            s.verdict, s.reason = "BUY", f"Unusually cheap — lowest in {len(series)} checks, {pct}% under typical."
        else:
            weeks = max(1, (days_out - late) // 7)
            s.verdict, s.reason = "WAIT", f"Early — the usual sweet spot opens in about {weeks} week{'s' if weeks != 1 else ''}."
    else:  # between 21 days and the start of the sweet spot
        s.verdict, s.reason = "BUY", "Past the usual sweet spot — waiting longer is a gamble."

    if over_budget and s.verdict != "BUY":
        s.reason += " (Currently over your budget.)"
    if category == "stay" and s.verdict == "BUY":
        s.reason += " Pick a free-cancellation rate so you can rebook if it drops."
    return s


def cheapest_per_check(rows: list[tuple[dt.date, dt.date, float]]) -> list[float]:
    """Collapse (checked_on, travel_date, price) rows to the min price per check."""
    by_check: dict[dt.date, float] = {}
    for checked_on, _travel, price in rows:
        by_check[checked_on] = min(price, by_check.get(checked_on, price))
    return [by_check[k] for k in sorted(by_check)]
