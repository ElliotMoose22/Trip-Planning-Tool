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
                                          "leave": ["leave"], "notes": ["notes"], "tool": ["trip tool"]}.items()}
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
    date: dt.date | None = None        # the Date cell itself (window aside)


def parse_legs(grid: Grid, year: int) -> tuple[list[LegRow], FlightTable] | None:
    h = _header(grid, {"from", "to", "mode"})
    if not h:
        return None
    hr, cols = h
    c = {k: _col(cols, *v) for k, v in {"from": ["from"], "to": ["to"], "mode": ["mode"], "earliest": ["earliest"],
                                          "latest": ["latest"], "date": ["date"], "status": ["status"],
                                          "price": ["price", "cost"], "len": ["length"], "no": ["flight", "service"],
                                          "notes": ["notes"], "tool": ["trip tool"]}.items()}
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
                           P.lookup(get("from")), P.lookup(get("to")), date))
    tool = c["tool"] if c["tool"] is not None else c["notes"]
    table = FlightTable([lr.flight for lr in rows], 0, hr,
                        {"cost": c["price"], "len": c["len"], "no": c["no"], "notes": tool,
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
                pr.notes.append(f"✔ {n} night{'s' if n != 1 else ''} fits your range")
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


# ---------------------------------------------------------------------------
# Recommendations: concrete, row-specific suggestions built from the tables.
# ---------------------------------------------------------------------------

@dataclass
class Rec:
    kind: str                 # Dates | Fix | Option | Price | Info
    title: str
    detail: str
    places: list[str] = field(default_factory=list)
    legs: list[str] = field(default_factory=list)      # "From → To"

    def row(self, today: dt.date) -> list:
        return [self.kind, self.title, self.detail, ", ".join(self.places), "; ".join(self.legs), today.isoformat()]


def _leg_between(legs: list[LegRow], a: str, b: str) -> LegRow | None:
    for lr in legs:
        if lr.origin and lr.destination and lr.origin.name == a and lr.destination.name == b:
            return lr
    return None


def recommend(places: list[PlaceRow], legs: list[LegRow], start: dt.date | None, end: dt.date | None) -> list[Rec]:
    recs: list[Rec] = []
    seq = [p for p in sorted([p for p in places if p.arrive and p.leave and p.leave >= p.arrive],
                             key=lambda p: p.arrive)]
    nights = {id(p): p.nights for p in seq}
    fixed = lambda p: bool(re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d", p.fixed, re.I))

    def slack(p, direction):              # +1: room to grow, -1: room to shrink
        n = nights[id(p)]
        if direction > 0:
            return (p.max_n - n) if p.max_n is not None else 0
        return (n - p.min_n) if p.min_n is not None else max(0, n - 1)

    # 1) stops outside their night range -> shift move dates toward a neighbour with room
    for i, p in enumerate(seq):
        n = nights[id(p)]
        over = n - p.max_n if p.max_n is not None and n > p.max_n else 0
        under = p.min_n - n if p.min_n is not None and n < p.min_n else 0
        if not (over or under):
            continue
        need = over or under
        grow = 1 if over else -1          # the neighbour we borrow from grows (over) or shrinks (under)
        best = None
        for step in (-1, 1):              # look back first (moves earlier dates), then forward
            for dist in (1, 2):
                j = i + step * dist
                if not 0 <= j < len(seq) or fixed(seq[j]) or (step > 0 and fixed(p)):
                    continue
                if slack(seq[j], grow) >= need and all(slack(seq[k], 0) >= 0 for k in range(min(i, j) + 1, max(i, j))):
                    best = (j, step)
                    break
            if best:
                break
        if best is None:
            what = "more" if over else "fewer"
            hint = (f" You meet someone there ({p.fixed}), so the simplest fix is to change the range or add a "
                    f"{need}-night stop nearby." if fixed(p) else "")
            recs.append(Rec("Dates", f"{p.city}: {n} nights, your range is {p.min_n or 0}–{p.max_n or '∞'}",
                            f"No neighbouring stop has room for {need} {what} night{'s' if need > 1 else ''}.{hint}",
                            [p.city]))
            continue
        j, step = best
        lo, hi = sorted((i, j))
        # boundaries between lo..hi move by `shift` days
        shift = (need if over else -need) * (1 if step < 0 else -1)
        moves, touched = [], []
        for k in range(lo, hi):
            a, b = seq[k], seq[k + 1]
            new_day = b.arrive + dt.timedelta(days=shift)
            lr = _leg_between(legs, a.place.name if a.place else a.city, b.place.name if b.place else b.city)
            how = f"the {lr.mode.lower()} {a.city} → {b.city}" if lr else f"the move {a.city} → {b.city}"
            moves.append(f"take {how} on {new_day:%a %b %-d} (not {b.arrive:%b %-d})")
            touched.append(f"{a.place.name if a.place else a.city} → {b.place.name if b.place else b.city}")
        nights[id(seq[j])] += need if over else -need
        nights[id(p)] += -need if over else need
        after = ", ".join(f"{seq[k].city} {nights[id(seq[k])]}" for k in range(lo, hi + 1))
        recs.append(Rec("Dates", f"{p.city}: {n} nights is {'over' if over else 'under'} your "
                                 f"{'max' if over else 'min'} of {p.max_n if over else p.min_n}",
                        f"{'; '.join(moves)[:1].upper() + '; '.join(moves)[1:]}. Then: {after} nights — all inside your ranges.",
                        [seq[k].city for k in range(lo, hi + 1)], touched))

    # 2) leg dates that don't match the move dates in Places
    for a, b in zip(seq, seq[1:]):
        if not (a.place and b.place):
            continue
        lr = _leg_between(legs, a.place.name, b.place.name)
        if not lr:
            continue
        day = a.leave
        if lr.date and lr.date != day:
            recs.append(Rec("Fix", f"{a.city} → {b.city} {lr.mode.lower()} is dated {lr.date:%b %-d}",
                            f"Places has you moving on {day:%a %b %-d}. Set the leg's Date to {day:%b %-d} "
                            f"(or change Arrive / Leave in Places).", [a.city, b.city], [f"{a.place.name} → {b.place.name}"]))
        elif not lr.date:
            outside = (lr.earliest and day < lr.earliest) or (lr.latest and day > lr.latest)
            recs.append(Rec("Fix", f"{a.city} → {b.city} {lr.mode.lower()} has no date",
                            f"Places has you moving on {day:%a %b %-d}"
                            + (f", which is outside its Earliest / Latest window" if outside else "")
                            + f". Put {day:%b %-d} in the leg's Date column.", [a.city, b.city],
                            [f"{a.place.name} → {b.place.name}"]))

    # 3) stops with no way in or out, and rows that look abandoned
    for pr in places:
        touching = [lr for lr in legs if pr.place and pr.place in (lr.origin, lr.destination)]
        if pr.priority == "Maybe" and pr.place and not touching:
            recs.append(Rec("Fix", f"{pr.city} has no legs in or out",
                            "If you're skipping it, delete the row in Places so the nights add up; otherwise add legs.",
                            [pr.city]))
        elif pr.place is None:
            recs.append(Rec("Fix", f"“{pr.city}” isn't a place the map knows",
                            "Name the town or island (for example Ubud, Nusa Penida or the Gili Islands) so it shows up "
                            "on the map and its travel can be checked.", [pr.city]))

    # 4) choices still open
    pairs: dict[tuple[str, str], list[LegRow]] = {}
    for lr in legs:
        if lr.origin and lr.destination:
            pairs.setdefault((lr.origin.name, lr.destination.name), []).append(lr)
    for (a, b), rows in pairs.items():
        if len(rows) > 1 and not any(r.status == "Booked" for r in rows):
            modes = " or ".join(r.mode.lower() for r in rows)
            recs.append(Rec("Option", f"Pick how to get from {a} to {b}: {modes}",
                            "Both are in the Legs tab as options. Mark the one you choose as Planned and delete the other.",
                            [a, b], [f"{a} → {b}"]))
    for lr in legs:
        if lr.mode.lower() != "flight" and lr.origin and lr.destination:
            _, road, hours = P.ground_trip(lr.origin, lr.destination)
            if hours >= 10:
                recs.append(Rec("Option", f"{lr.origin.name} → {lr.destination.name} is about {hours:.0f} hrs by {lr.mode.lower()}",
                                f"That's roughly {road:,.0f} km. An overnight service saves a day of the trip; "
                                f"a short flight is the other option.", [lr.origin.name, lr.destination.name],
                                [f"{lr.origin.name} → {lr.destination.name}"]))

    # 5) prices still to come
    unpriced = [lr for lr in legs if lr.mode.lower() == "flight" and lr.status != "Booked" and lr.flight.cost is None]
    if unpriced:
        recs.append(Rec("Price", f"{len(unpriced)} flight{'s' if len(unpriced) > 1 else ''} without a price yet",
                        "The first weekly price check fills these in (needs the SerpApi key on GitHub).",
                        [], [f"{lr.origin.name} → {lr.destination.name}" for lr in unpriced if lr.origin and lr.destination]))

    # 6) the big picture
    if start and end:
        total_max = sum(p.max_n or 0 for p in seq) if all(p.max_n is not None for p in seq) else 0
        avail = (end - (seq[0].arrive if seq else start)).days
        if total_max and total_max == avail:
            recs.append(Rec("Info", f"Your maximum nights add up to exactly {avail}",
                            "Every stop at its maximum fills the trip, so there's no spare night: adding a stop means "
                            "shortening another.", [p.city for p in seq]))
    order = {"Dates": 0, "Fix": 1, "Option": 2, "Price": 3, "Info": 4}
    return sorted(recs, key=lambda r: order[r.kind])
