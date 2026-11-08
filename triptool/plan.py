"""Turn the sheet into a plan: where you sleep each night, stops, legs, checks.

The sheet is treated loosely: anything it doesn't say explicitly is filled in
with a best guess and marked `assumed`, and those guesses are listed in the
report so you can fix them in the sheet.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import places as P
from .sheet import Day, PlannedFlight

FLIGHT_NO = re.compile(r"\b([A-Z][A-Z0-9])\s?(\d{2,4})\b")


@dataclass
class Night:
    date: dt.date
    place: P.Place | None
    country: str | None
    label: str
    travel: bool
    assumed: bool
    explicit: bool


@dataclass
class Stop:
    place: P.Place
    check_in: dt.date
    check_out: dt.date
    assumed: bool
    labels: list[str] = field(default_factory=list)
    assumed_nights: int = 0
    vague: str = ""

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


@dataclass
class Leg:
    id: str
    flight: PlannedFlight
    origin: P.Place
    destination: P.Place
    alt_origins: list[P.Place] = field(default_factory=list)   # suggested by plan checks


@dataclass
class Check:
    level: str        # "fix" | "heads-up"
    text: str


@dataclass
class Plan:
    year: int
    nights: list[Night]
    stops: list[Stop]
    legs: list[Leg]
    checks: list[Check]
    unknown_places: list[str]


def _split_travel(text: str) -> tuple[str, str] | None:
    m = re.search(r"(.+?)\s+to\s+(.+)", text, re.I)
    return (m.group(1), m.group(2)) if m else None


def _strip_who(text: str) -> str:
    return re.sub(r"^\s*cat\b\s*", "", text, flags=re.I).strip()


def build_plan(days: list[Day], flights: list[PlannedFlight], home: str | None = None) -> Plan:
    checks: list[Check] = []
    unknown: set[str] = set()
    a_flights = [f for f in flights if f.option == "A"]
    arriving = {f.date: f for f in a_flights}

    # ---- 1. where do you sleep each night? ----
    nights: list[Night] = []
    prev: Night | None = None
    for d in days:
        where = _strip_who(d.where)
        travel = bool(_split_travel(where)) or where.lower() == "travel"
        part = where.split(" - ", 1)[1] if " - " in where else where
        trav = _split_travel(part)
        place, explicit, assumed = None, False, False
        country = P.country_of(where)
        if trav:
            place = P.lookup(trav[1])
            country = P.country_of(trav[1]) or (place.country if place else country)
            explicit = place is not None
        if place is None:  # "Fukuoka to Kagoshima" in the notes = you end the day in Kagoshima
            for line in reversed(d.notes.splitlines()):
                t = _split_travel(line)
                if t and (q := P.lookup(t[1])):
                    place, explicit = q, True
                    break
        if place is None:
            hits = P.mentioned(f"{part}\n{d.notes}")
            if hits:
                place, explicit = hits[-1], True
        if place is None and d.date in arriving and (travel or not country):
            place = P.lookup(arriving[d.date].destination)
        if place is None and country:
            # country only: stay where you already are in that country, else the city you fly into
            if prev and prev.place and prev.place.country == country:
                place, assumed = prev.place, True
            else:
                fl = next((f for f in reversed(a_flights) if f.date <= d.date
                           and (p := P.lookup(f.destination)) and p.country == country), None)
                name = P.lookup(fl.destination).name if fl else P.COUNTRY_DEFAULT.get(country.lower())
                place, assumed = (P.lookup(name) if name else None), True
        if place is None and d.date in arriving:
            place = P.lookup(arriving[d.date].destination)
        if place is None and prev:
            place, assumed = prev.place, True
        if place is None and where and where.lower() != "travel":
            unknown.add(where)
        n = Night(d.date, place, country or (place.country if place else None), where or "–",
                  travel, assumed, explicit)
        nights.append(n)
        prev = n

    # ---- 2. group nights into stops ----
    stops: list[Stop] = []
    for n in nights:
        if n.place is None:
            continue
        if stops and stops[-1].place == n.place and stops[-1].check_out == n.date:
            s = stops[-1]
            s.check_out = n.date + dt.timedelta(days=1)
        else:
            s = Stop(n.place, n.date, n.date + dt.timedelta(days=1), False)
            stops.append(s)
        s.assumed_nights += n.assumed
        if n.assumed and not s.vague:
            s.vague = n.label
        s.assumed = s.assumed_nights * 2 > s.nights
        if n.label not in s.labels:
            s.labels.append(n.label)

    by_date = {n.date: n for n in nights}

    # ---- 3. legs: flights tab + flights only mentioned in the calendar ----
    all_flights = list(flights)
    for d, n in zip(days, nights):
        where = _strip_who(d.where)
        part = where.split(" - ", 1)[1] if " - " in where else where
        trav = _split_travel(part)
        if not trav:
            continue
        a, b = P.lookup(trav[0]), P.lookup(trav[1])
        if not a or not b or a == b:
            continue
        covered = any(abs((f.date - d.date).days) <= 1 and P.lookup(f.destination) == b for f in flights)
        if not covered:
            fn = FLIGHT_NO.search(d.notes)
            pf = PlannedFlight(d.date, a.name, b.name, _first_money(d.notes),
                               flight_no=f"{fn.group(1)}{fn.group(2)}" if fn else "", source="calendar")
            all_flights.append(pf)
            checks.append(Check("fix", f"{d.date:%b %-d}: the calendar has a flight {a.name} → {b.name}"
                                f"{' (' + pf.flight_no + ')' if pf.flight_no else ''} that isn't in the flights tab. "
                                "I'm tracking it anyway — add it to the tab so the totals are right."))

    legs: list[Leg] = []
    seen: set[str] = set()
    for f in sorted(all_flights, key=lambda f: (f.date, f.option)):
        o, dst = P.lookup(f.origin), P.lookup(f.destination)
        if not o or not dst:
            unknown.update(x for x, p in ((f.origin, o), (f.destination, dst)) if not p)
            continue
        lid = f"{o.airports[0]}-{dst.airports[0]}"
        if lid in seen:
            lid = f"{lid}-{f.date:%m%d}"
        seen.add(lid)
        leg = Leg(lid, f, o, dst)
        legs.append(leg)

        # does the calendar have you somewhere else the night before?
        before = by_date.get(f.date - dt.timedelta(days=1))
        if before and before.place and before.place != o and before.place.country == o.country and not f.booked:
            leg.alt_origins.append(before.place)
            if before.explicit:
                checks.append(Check("fix", f"{f.date:%b %-d}: the flights tab flies {o.name} → {dst.name}, but the calendar "
                                    f"has you in {before.place.name} the night before. I'm also pricing "
                                    f"{before.place.name} → {dst.name}."))
            else:
                checks.append(Check("fix", f"{f.date:%b %-d}: you fly out of {o.name}, but the calendar never gets you "
                                    f"there from {before.place.name}. Add that leg, or I can price "
                                    f"{before.place.name} → {dst.name} directly (doing that now)."))

    # ---- 4. other heads-ups ----
    for s in stops:
        if s.assumed_nights >= 3:
            checks.append(Check("heads-up", f"{s.check_in:%b %-d}–{s.check_out:%b %-d}: {s.assumed_nights} nights only say "
                                f"“{s.vague}”, so I've assumed {s.place.name} for hotels. Add a city to change it."))
    seen_notes: set[str] = set()
    for d in days:
        for note in d.side_notes:
            if note in seen_notes:
                continue
            seen_notes.add(note)
            for p in P.mentioned(note):
                week = [n for n in nights if abs((n.date - d.date).days) <= 3]
                there = [s for s in stops if s.place == p]
                if there and all(n.place != p for n in week):
                    when = (f" — the calendar has you there {there[0].check_in:%b %-d}–{there[-1].check_out:%b %-d}"
                            if there else "")
                    checks.append(Check("heads-up", f"Note beside the week of {d.date:%b %-d}: “{note}”, but you're "
                                        f"not in {p.name} that week{when}. Worth checking the event dates."))
    if home and stops and legs:
        last = max(legs, key=lambda l: l.flight.date)
        if last.destination.name.lower() != home.lower():
            checks.append(Check("fix", f"Your last flight lands in {last.destination.name}, not {home} — "
                                f"add your flight home to your table."))
    for u in sorted(unknown):
        checks.append(Check("heads-up", f"I don't know where “{u}” is — add it to triptool/places.py."))

    year = days[0].date.year if days else dt.date.today().year
    return Plan(year, nights, stops, legs, checks, sorted(unknown))


def _first_money(text: str) -> float | None:
    m = re.search(r"\$\s?(\d[\d,]*)", text or "")
    return float(m.group(1).replace(",", "")) if m else None
