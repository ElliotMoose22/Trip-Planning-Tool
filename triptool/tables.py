"""Read the Places and Legs tabs: the structured plan.

Places: Country | City | Priority | Min nights | Max nights | Fixed dates | Arrive | Leave | Nights | Notes
Legs:   From | To | Mode | Earliest | Latest | Date | Status | Price | Length | Flight / service no. | Booking ref | Notes

When these tabs exist they replace the calendar as the tool's input, so
nothing has to be guessed. Every check is tied to the row it's about, so the
tool can write it back into that row's Notes.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import places as P
from .plan import Check, GroundLeg, Leg, Plan, Stop
from .sheet import FlightTable, Grid, PlannedFlight, _at, _money, _month_day

COUNTRY_ORDER = ["Japan", "Thailand", "Indonesia", "Vietnam"]


def _header(grid: Grid, must: set[str]) -> tuple[int, dict[str, int]] | None:
    for r, row in enumerate(grid[:15]):
        low = [v.strip().lower() for v in row]
        if must <= set(low):
            return r, {v: c for c, v in enumerate(low) if v}
    return None


def _col(cols: dict[str, int], *starts: str) -> int | None:
    for s in starts:
        for name, c in cols.items():
            if name.startswith(s):
                return c
    return None


def _date(v: str, year: int) -> dt.date | None:
    md = _month_day(v)
    return dt.date(year, md[0], md[1]) if md else None


def _int(v: str) -> int | None:
    m = re.search(r"\d+", v or "")
    return int(m.group()) if m else None


@dataclass
class PlaceRow:
    row: int
    country: str
    city: str
    priority: str
    min_n: int | None
    max_n: int | None
    fixed: str
    arrive: dt.date | None
    leave: dt.date | None
    place: P.Place | None
    notes: list[str] = field(default_factory=list)

    @property
    def nights(self) -> int | None:
        return (self.leave - self.arrive).days if self.arrive and self.leave else None


def parse_places(grid: Grid, year: int) -> tuple[list[PlaceRow], dict[str, int]] | None:
    h = _header(grid, {"city", "priority"})
    if not h:
        return None
    hr, cols = h
    c = {k: _col(cols, *v) for k, v in {"country": ["country"], "city": ["city"], "priority": ["priority"],
                                          "min": ["min"], "max": ["max"], "fixed": ["fixed"], "arrive": ["arrive"],
                                          "leave": ["leave"], "notes": ["notes"]}.items()}
    out = []
    for r in range(hr + 1, len(grid)):
        city = _at(grid, r, c["city"]).strip()
        if not city:
            if not any(v.strip() for v in grid[r][:c["city"] + 1]):
                break
            continue
        get = lambda k: _at(grid, r, c[k]).strip() if c[k] is not None else ""
        out.append(PlaceRow(r, get("country"), city, get("priority").title(), _int(get("min")), _int(get("max")),
                            get("fixed"), _date(get("arrive"), year), _date(get("leave"), year), P.lookup(city)))
    return out, c


@dataclass
class LegRow:
    flight: PlannedFlight
    mode: str
    status: str
    earliest: dt.date | None
    latest: dt.date | None
    origin: P.Place | None
    destination: P.Place | None


def parse_legs(grid: Grid, year: int) -> tuple[list[LegRow], FlightTable] | None:
    h = _header(grid, {"from", "to", "mode"})
    if not h:
        return None
    hr, cols = h
    c = {k: _col(cols, *v) for k, v in {"from": ["from"], "to": ["to"], "mode": ["mode"], "earliest": ["earliest"],
                                          "latest": ["latest"], "date": ["date"], "status": ["status"],
                                          "price": ["price", "cost"], "len": ["length"], "no": ["flight", "service"],
                                          "notes": ["notes"]}.items()}
    rows = []
    for r in range(hr + 1, len(grid)):
        get = lambda k: _at(grid, r, c[k]).strip() if c[k] is not None else ""
        if not get("from"):
            break
        earliest, latest, date = _date(get("earliest"), year), _date(get("latest"), year), _date(get("date"), year)
        status = get("status").title() or "Planned"
        f = PlannedFlight(date=date or latest or earliest or dt.date(year, 1, 1), origin=get("from"),
                          destination=get("to"), cost=_money(get("price")), duration=get("len"),
                          flight_no=get("no"), booked=status == "Booked", note=get("notes"),
                          source="my table", row=r)
        f.dated = date is not None or latest is not None or earliest is not None
        rows.append(LegRow(f, get("mode") or "Flight", status, earliest, latest,
                           P.lookup(get("from")), P.lookup(get("to"))))
    table = FlightTable([lr.flight for lr in rows], 0, hr,
                        {"cost": c["price"], "len": c["len"], "no": c["no"], "notes": c["notes"],
                         "stamp": max(v for v in c.values() if v is not None) + 1})
    return rows, table


def build_from_tables(places: list[PlaceRow], legs: list[LegRow], start: dt.date | None,
                      end: dt.date | None) -> Plan:
    checks: list[Check] = []

    def note(pr: PlaceRow | None, level: str, text: str):
        checks.append(Check(level, text))
        if pr is not None:
            t = text.split(": ", 1)[-1] if text.startswith(pr.city) else text
            pr.notes.append(t[:1].upper() + t[1:])

    # ---- stops ----
    stops: list[Stop] = []
    for pr in places:
        if pr.place is None:
            note(pr, "fix", f"{pr.city}: I can't place this on the map — use a town or airport city name.")
        if pr.priority == "Must" and not (pr.arrive and pr.leave):
            note(pr, "fix", f"{pr.city}: it's a Must, but it has no Arrive / Leave dates yet.")
        elif not pr.arrive or not pr.leave:
            missing = " and ".join(x for x, v in (("Arrive", pr.arrive), ("Leave", pr.leave)) if not v)
            note(pr, "fix", f"{pr.city}: needs a{'n' if missing[0] == 'A' else ''} {missing} date.")
        n = pr.nights
        if n is not None:
            if n < 0:
                note(pr, "fix", f"{pr.city}: Leave is before Arrive.")
            elif pr.min_n is not None and n < pr.min_n:
                note(pr, "fix", f"{pr.city}: {n} night{'s' if n != 1 else ''} planned, but you want at least {pr.min_n}.")
            elif pr.max_n is not None and n > pr.max_n:
                note(pr, "fix", f"{pr.city}: {n} nights planned, but you want at most {pr.max_n}.")
            elif pr.min_n is not None or pr.max_n is not None:
                pr.notes.append(f"✔ {n} nights fits your range")
        if pr.place and pr.arrive and pr.leave and n and n > 0:
            stops.append(Stop(pr.place, pr.arrive, pr.leave, False, [pr.city]))
        if pr.priority == "" and pr.place:
            pr.notes.append("Set a priority (Must / Want / Maybe)")
        if pr.min_n is None and pr.max_n is None and pr.place and (n or 0) > 0:
            pr.notes.append("Add Min / Max nights so I can check the length")

    # ---- the order of things ----
    dated = sorted([p for p in places if p.arrive or p.leave], key=lambda p: (p.arrive or p.leave, p.leave or p.arrive))
    for a, b in zip(dated, dated[1:]):
        if a.leave and b.arrive:
            gap = (b.arrive - a.leave).days
            if gap > 0:
                note(b, "fix", f"{a.city} → {b.city}: {gap} night{'s' if gap > 1 else ''} not planned between "
                               f"{a.leave:%b %-d} and {b.arrive:%b %-d}.")
            elif gap < 0:
                note(b, "fix", f"{a.city} → {b.city}: dates overlap by {-gap} night{'s' if gap < -1 else ''}.")
    seen_countries = [p.country.title() for p in dated if p.country]
    order = [c for c in COUNTRY_ORDER if c in seen_countries]
    firsts = sorted(set(seen_countries), key=seen_countries.index)
    if [c for c in firsts if c in COUNTRY_ORDER] != order:
        checks.append(Check("fix", f"The countries are out of order ({' → '.join(firsts)}); "
                                   f"the plan is {' → '.join(COUNTRY_ORDER)}."))
    if start and end and dated:
        if dated[0].arrive and (dated[0].arrive - start).days > 1:
            note(dated[0], "heads-up", f"The trip starts {start:%b %-d} but the first stop begins {dated[0].arrive:%b %-d}.")
        if dated[-1].leave and dated[-1].leave < end:
            note(dated[-1], "heads-up", f"{(end - dated[-1].leave).days} nights before {end:%b %-d} aren't planned yet.")

    # ---- legs ----
    plan_legs: list[Leg] = []
    ground: list[GroundLeg] = []
    seen: set[str] = set()
    for lr in legs:
        f = lr.flight
        if not lr.origin or not lr.destination:
            bad = f.origin if not lr.origin else f.destination
            checks.append(Check("fix", f"Legs: I can't place “{bad}” — use a town or airport city name."))
            continue
        if not getattr(f, "dated", True):
            checks.append(Check("heads-up", f"{lr.origin.name} → {lr.destination.name}: no date or window yet."))
        if lr.mode.lower() == "flight":
            lid = f"{lr.origin.airports[0]}-{lr.destination.airports[0]}"
            if lid in seen:
                lid = f"{lid}-{f.date:%m%d}"
            seen.add(lid)
            leg = Leg(lid, f, lr.origin, lr.destination)
            leg.window = (lr.earliest, lr.latest)
            plan_legs.append(leg)
        else:
            mode, road, hours = P.ground_trip(lr.origin, lr.destination)
            ground.append(GroundLeg(lr.origin, lr.destination, f.date, lr.mode, road, hours))
    # an overland trip right before a flight -> also price flying from where the overland trip starts
    for leg in plan_legs:
        for g in ground:
            if (g.destination == leg.origin and abs((leg.flight.date - g.by).days) <= 2
                    and g.origin != leg.destination and g.origin not in leg.alt_origins):
                leg.alt_origins.append(g.origin)

    # every move between consecutive stops needs a leg
    allmoves = [(l.origin.name, l.destination.name) for l in plan_legs] + [(g.origin.name, g.destination.name) for g in ground]
    stop_seq = [p for p in dated if p.place]
    for a, b in zip(stop_seq, stop_seq[1:]):
        if a.place != b.place and (a.place.name, b.place.name) not in allmoves:
            note(b, "fix", f"No leg from {a.place.name} to {b.place.name} yet — add one to the Legs tab.")

    year = (start or (dated[0].arrive if dated else dt.date.today())).year
    return Plan(year, [], stops, sorted(plan_legs, key=lambda l: l.flight.date), checks, [],
                sorted(ground, key=lambda g: g.by))
