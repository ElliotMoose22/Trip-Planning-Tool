"""Settings from trip.yaml. The trip itself comes from the Google Sheet."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Settings:
    name: str = "Asia 2027"
    sheet_url: str = ""
    start: dt.date | None = None       # only plan inside this window
    end: dt.date | None = None
    home: str = "Toronto"
    my_table: str = "Elliot Flights"  # title of the table the tool tracks and updates
    currency: str = "CAD"
    flex_days: int = 2
    max_searches: int = 45
    suggest_if_saves: float = 30
    hotel_min_nights: int = 2
    hotel_adults: int = 2
    hotel_skip: list[str] = field(default_factory=list)
    hotel_max_price: dict[str, float] = field(default_factory=dict)   # by country
    hotel_areas: dict[str, str] = field(default_factory=dict)         # city -> search text
    hotel_typical: dict[str, float] = field(default_factory=dict)     # demo prices by country
    daytrip_hours: float = 2.5                                         # one way, for reels


def load_settings(path: str | Path = "trip.yaml") -> Settings:
    raw = yaml.safe_load(Path(path).read_text()) if Path(path).exists() else {}
    s, search, hotels = raw.get("trip", {}), raw.get("search", {}), raw.get("hotels", {})
    return Settings(
        name=s.get("name", "Asia 2027"),
        sheet_url=os.environ.get("TRIP_SHEET_URL") or raw.get("sheet", {}).get("url", ""),
        start=_date(s.get("start")), end=_date(s.get("end")), home=s.get("home", "Toronto"),
        my_table=raw.get("sheet", {}).get("my_flights_table", "Elliot Flights"),
        currency=s.get("currency", "CAD"),
        flex_days=int(search.get("flex_days", 2)),
        max_searches=int(search.get("max_searches_per_run", 45)),
        suggest_if_saves=float(search.get("suggest_if_saves", 30)),
        hotel_min_nights=int(hotels.get("min_nights", 2)),
        hotel_adults=int(hotels.get("adults", 2)),
        hotel_skip=[x.lower() for x in hotels.get("skip", [])],
        hotel_max_price={k.lower(): float(v) for k, v in (hotels.get("max_price_per_night") or {}).items()},
        hotel_areas={k.lower(): v for k, v in (hotels.get("areas") or {}).items()},
        hotel_typical={k.lower(): float(v) for k, v in (hotels.get("typical_price") or {}).items()},
        daytrip_hours=float((raw.get("reels") or {}).get("daytrip_hours", 2.5)),
    )


def _date(v) -> dt.date | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))
