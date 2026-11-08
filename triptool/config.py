"""Load trip.yaml into simple dataclasses and expand flexible date windows."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class FlightLeg:
    id: str
    label: str
    origin: str
    destination: str
    date: dt.date
    flex_days: int = 0
    booked: bool = False

    def search_dates(self) -> list[dt.date]:
        return [self.date + dt.timedelta(days=d) for d in range(-self.flex_days, self.flex_days + 1)]


@dataclass
class Stay:
    id: str
    label: str
    query: str
    check_in: dt.date
    check_out: dt.date
    max_price_per_night: float | None = None
    booked: bool = False

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


@dataclass
class Trip:
    name: str
    travelers: int
    currency: str
    start: dt.date
    end: dt.date
    flights: list[FlightLeg] = field(default_factory=list)
    stays: list[Stay] = field(default_factory=list)


def _date(v) -> dt.date:
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


def load_trip(path: str | Path = "trip.yaml") -> Trip:
    raw = yaml.safe_load(Path(path).read_text())
    t = raw["trip"]
    flights = [
        FlightLeg(
            id=f["id"], label=f["label"], origin=f["origin"], destination=f["destination"],
            date=_date(f["date"]), flex_days=int(f.get("flex_days", 0)), booked=bool(f.get("booked", False)),
        )
        for f in raw.get("flights", [])
    ]
    stays = [
        Stay(
            id=s["id"], label=s["label"], query=s["query"],
            check_in=_date(s["check_in"]), check_out=_date(s["check_out"]),
            max_price_per_night=s.get("max_price_per_night"), booked=bool(s.get("booked", False)),
        )
        for s in raw.get("stays", [])
    ]
    return Trip(
        name=t["name"], travelers=int(t.get("travelers", 1)), currency=t.get("currency", "CAD"),
        start=_date(t["start"]), end=_date(t["end"]), flights=flights, stays=stays,
    )
