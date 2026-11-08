"""Decide what to search, then turn results into suggestions.

Searches are ranked so the most useful ones happen first when the weekly
budget (`max_searches_per_run`) runs out:
  0  each flight exactly as planned          1  ±1 day, and each hotel
  2  routes the plan checks flagged           3  ±2 days
  4  nearby alternative airports
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from . import places as P
from .config import Settings
from .plan import Leg, Plan, Stop


@dataclass
class Search:
    kind: str                 # flight | stay
    item_id: str
    priority: int
    date: dt.date
    leg: Leg | None = None
    origin: P.Place | None = None
    dest: P.Place | None = None
    stop: Stop | None = None
    why: str = ""             # plan | date | calendar | nearby


def stay_id(stop: Stop) -> str:
    return f"stay-{stop.place.airports[0]}-{stop.check_in:%m%d}"


def hotel_stops(plan: Plan, s: Settings) -> list[Stop]:
    return [st for st in plan.stops
            if st.nights >= s.hotel_min_nights and st.place.name.lower() not in s.hotel_skip]


def plan_searches(plan: Plan, s: Settings, today: dt.date) -> list[Search]:
    out: list[Search] = []
    for leg in plan.legs:
        f = leg.flight
        if f.booked or f.date < today:
            continue
        o, d = leg.origin, leg.destination
        out.append(Search("flight", leg.id, 0, f.date, leg, o, d, why="plan"))
        for k in range(1, s.flex_days + 1):
            for sign in (-1, 1):
                day = f.date + dt.timedelta(days=sign * k)
                if day > today:
                    out.append(Search("flight", leg.id, 1 if k == 1 else 3, day, leg, o, d, why="date"))
        tried = {(o, d)}
        for alt in leg.alt_origins:
            out.append(Search("flight", f"{leg.id}@{alt.airports[0]}-{d.airports[0]}", 2, f.date, leg, alt, d,
                              why="calendar"))
            tried.add((alt, d))
        for oo, dd in [(a, d) for a in P.alternates(o)] + [(o, a) for a in P.alternates(d)]:
            if (oo, dd) not in tried and oo != dd:
                tried.add((oo, dd))
                out.append(Search("flight", f"{leg.id}@{oo.airports[0]}-{dd.airports[0]}", 4, f.date, leg, oo, dd,
                                  why="nearby"))
    for st in hotel_stops(plan, s):
        if st.check_in > today:
            out.append(Search("stay", stay_id(st), 1, st.check_in, stop=st, why="plan"))
    out.sort(key=lambda x: (x.priority, x.date))
    return out[: s.max_searches]


# ---------- after searching ----------

@dataclass
class Suggestion:
    text: str
    price: float
    saves: float | None
    kind: str               # date | calendar | nearby


@dataclass
class LegResult:
    leg: Leg
    plan_price: float | None = None
    plan_detail: str = ""
    plan_link: str = ""
    by_date: dict[dt.date, float] = field(default_factory=dict)
    suggestions: list[Suggestion] = field(default_factory=list)


def km(a: P.Place, b: P.Place) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def summarize(plan: Plan, results: dict[tuple[str, dt.date], "object"], s: Settings) -> list[LegResult]:
    """`results` maps (item_id, date) -> Quote for this week's searches."""
    out = []
    for leg in plan.legs:
        r = LegResult(leg)
        f = leg.flight
        for (iid, day), q in results.items():
            if iid == leg.id:
                r.by_date[day] = q.price
                if day == f.date:
                    r.plan_price, r.plan_detail, r.plan_link = q.price, q.detail, q.link
        ref = r.plan_price if r.plan_price is not None else f.cost
        threshold = max(s.suggest_if_saves, 0.1 * ref) if ref else s.suggest_if_saves

        if r.by_date:
            day, price = min(r.by_date.items(), key=lambda kv: kv[1])
            if day != f.date and ref and ref - price >= threshold:
                shift = (day - f.date).days
                r.suggestions.append(Suggestion(
                    f"Fly {day:%a %b %-d} instead ({shift:+d} day{'s' if abs(shift) > 1 else ''})",
                    price, ref - price, "date"))
        for (iid, day), q in results.items():
            if not iid.startswith(leg.id + "@"):
                continue
            oc, dc = iid.split("@", 1)[1].split("-")
            o = next((p for p in P.PLACES.values() if p.airports[0] == oc), None)
            d = next((p for p in P.PLACES.values() if p.airports[0] == dc), None)
            if not o or not d:
                continue
            saves = ref - q.price if ref else None
            if o in leg.alt_origins:
                text = f"Fly {o.name} → {d.name} instead — matches your calendar"
                r.suggestions.append(Suggestion(text, q.price, saves, "calendar"))
            elif saves is not None and saves >= threshold:
                r.suggestions.append(Suggestion(f"Fly {o.name} → {d.name} instead", q.price, saves, "nearby"))
        r.suggestions.sort(key=lambda x: (x.kind != "calendar", -(x.saves or 0)))
        out.append(r)
    return out


def option_comparison(plan: Plan, legs: list[LegResult]) -> dict | None:
    """Compare the sheet's alternative (option B) flights with the option A legs they replace."""
    b = [lr for lr in legs if lr.leg.flight.option == "B"]
    if not b:
        return None
    a_all = [lr for lr in legs if lr.leg.flight.option == "A"]
    start, end_dest = b[0].leg, b[-1].leg.destination
    seg: list[LegResult] = []
    for lr in a_all:
        if lr.leg.flight.date >= start.flight.date and (seg or lr.leg.origin == start.origin):
            seg.append(lr)
            if lr.leg.destination == end_dest:
                break
    if not seg or seg[-1].leg.destination != end_dest:
        return None

    def total(xs, live):
        vals = [(x.plan_price if live else None) or x.leg.flight.cost for x in xs]
        return sum(v for v in vals if v) if all(vals) else None

    return {
        "a": [x.leg for x in seg], "b": [x.leg for x in b],
        "a_sheet": total(seg, False), "b_sheet": total(b, False),
        "a_now": total(seg, True), "b_now": total(b, True),
    }
