"""Price sources.

- DemoProvider: deterministic fake prices so everything runs with no API key.
- SerpApiProvider: real Google Flights / Google Hotels results via serpapi.com.
  Set SERPAPI_KEY to use it. (Amadeus Self-Service, the old free default,
  was shut down in July 2026, so it isn't an option.)

Add another provider by implementing `flight_price` and `stay_price`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import os
from dataclasses import dataclass

from .config import FlightLeg, Stay


@dataclass
class Quote:
    item_id: str
    kind: str              # "flight" | "stay"
    travel_date: dt.date   # departure date / check-in
    price: float           # total for the whole party (flight) or per night (stay)
    currency: str
    detail: str = ""       # airline / hotel name
    link: str = ""
    source: str = ""


class DemoProvider:
    """Plausible, repeatable prices that drift over time. Clearly labelled as demo."""

    name = "demo"
    BASE = {"yyz-tyo": 1150, "tyo-bkk": 260, "bkk-dps": 190, "dps-sgn": 170, "han-yyz": 1050}
    STAY_BASE = {"tokyo": 210, "bangkok": 95, "bali": 120, "hcmc": 70}

    def __init__(self, today: dt.date | None = None):
        self.today = today or dt.date.today()

    def _wiggle(self, key: str, amp: float) -> float:
        h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
        return ((h % 1000) / 1000 - 0.5) * 2 * amp

    def flight_price(self, leg: FlightLeg, date: dt.date, travelers: int, currency: str) -> Quote | None:
        base = self.BASE.get(leg.id, 300)
        days_out = (date - self.today).days
        # cheapest ~2-4 months out, pricier far out and very close in
        curve = 1 + 0.12 * math.tanh((days_out - 220) / 90) + 0.35 * max(0, (60 - days_out) / 60)
        noise = self._wiggle(f"{leg.id}{date}{self.today.isocalendar()[:2]}", 0.08)
        weekday = 1.06 if date.weekday() in (4, 6) else 1.0
        per_person = round(base * curve * weekday * (1 + noise))
        return Quote(leg.id, "flight", date, per_person * travelers, currency,
                     detail="Demo Air", source=self.name)

    def stay_price(self, stay: Stay, currency: str) -> Quote | None:
        base = self.STAY_BASE.get(stay.id, 100)
        noise = self._wiggle(f"{stay.id}{self.today.isocalendar()[:2]}", 0.12)
        return Quote(stay.id, "stay", stay.check_in, round(base * (1 + noise)), currency,
                     detail="Demo Hotel", source=self.name)


class SerpApiProvider:
    name = "serpapi"
    URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str | None = None):
        import requests  # local import so demo mode needs nothing extra
        self.requests = requests
        self.key = api_key or os.environ["SERPAPI_KEY"]

    def _get(self, params: dict) -> dict:
        r = self.requests.get(self.URL, params={**params, "api_key": self.key}, timeout=60)
        r.raise_for_status()
        return r.json()

    def flight_price(self, leg: FlightLeg, date: dt.date, travelers: int, currency: str) -> Quote | None:
        data = self._get({
            "engine": "google_flights", "type": 2,  # one-way
            "departure_id": leg.origin, "arrival_id": leg.destination,
            "outbound_date": date.isoformat(), "adults": travelers, "currency": currency, "hl": "en",
        })
        options = (data.get("best_flights") or []) + (data.get("other_flights") or [])
        options = [o for o in options if o.get("price")]
        if not options:
            return None
        best = min(options, key=lambda o: o["price"])
        airlines = ", ".join(sorted({seg.get("airline", "?") for seg in best.get("flights", [])}))
        stops = max(0, len(best.get("flights", [])) - 1)
        return Quote(leg.id, "flight", date, float(best["price"]), currency,
                     detail=f"{airlines} · {stops} stop{'s' if stops != 1 else ''}",
                     link=data.get("search_metadata", {}).get("google_flights_url", ""), source=self.name)

    def stay_price(self, stay: Stay, currency: str) -> Quote | None:
        params = {
            "engine": "google_hotels", "q": stay.query, "check_in_date": stay.check_in.isoformat(),
            "check_out_date": stay.check_out.isoformat(), "adults": 2, "currency": currency,
            "hl": "en", "sort_by": 8, "rating": 8,  # highest rated, 4.0+
        }
        if stay.max_price_per_night:
            params["max_price"] = int(stay.max_price_per_night)
        data = self._get(params)
        props = [p for p in data.get("properties", []) if p.get("rate_per_night", {}).get("extracted_lowest")]
        if not props:
            return None
        best = min(props[:10], key=lambda p: p["rate_per_night"]["extracted_lowest"])
        return Quote(stay.id, "stay", stay.check_in, float(best["rate_per_night"]["extracted_lowest"]), currency,
                     detail=f"{best.get('name', '?')} ({best.get('overall_rating', '–')}★)",
                     link=best.get("link", ""), source=self.name)


def get_provider(name: str | None = None):
    name = name or ("serpapi" if os.environ.get("SERPAPI_KEY") else "demo")
    return SerpApiProvider() if name == "serpapi" else DemoProvider()
