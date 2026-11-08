"""Price sources.

- DemoProvider: deterministic fake prices so everything runs with no API key.
- SerpApiProvider: real Google Flights / Google Hotels results via serpapi.com.
  Set SERPAPI_KEY to use it. (Amadeus Self-Service, the old free default,
  was shut down in July 2026.)

Flight prices are per person. Hotel prices are per night for the room.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import os
from dataclasses import dataclass


@dataclass
class Quote:
    item_id: str
    kind: str              # "flight" | "stay"
    travel_date: dt.date   # departure date / check-in
    price: float
    currency: str
    detail: str = ""
    link: str = ""
    source: str = ""


def _hash(key: str) -> float:
    """Stable number in [-1, 1) for a key."""
    return (int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 2000) / 1000 - 1


class DemoProvider:
    """Plausible, repeatable prices that drift week to week. Clearly labelled as demo."""

    name = "demo"

    def __init__(self, today: dt.date | None = None):
        self.today = today or dt.date.today()
        self.week = "%d-%d" % self.today.isocalendar()[:2]

    def flight_price(self, item_id, origin, dest, date, adults, currency, ref=None) -> Quote | None:
        base = ref or 300
        days_out = (date - self.today).days
        curve = 1 + 0.12 * math.tanh((days_out - 220) / 90) + 0.35 * max(0, (60 - days_out) / 60)
        route = 1 + 0.15 * _hash(f"{origin}{dest}") if "@" in item_id else 1
        noise = 0.07 * _hash(f"{item_id}{date}{self.week}")
        weekday = 1.06 if date.weekday() in (4, 6) else 1.0
        return Quote(item_id, "flight", date, round(base * curve * route * weekday * (1 + noise)), currency,
                     detail="Demo Air · 1 stop", source=self.name)

    def stay_price(self, item_id, query, check_in, check_out, adults, max_price, currency, ref=None) -> Quote | None:
        base = ref or 120
        return Quote(item_id, "stay", check_in, round(base * (1 + 0.12 * _hash(f"{item_id}{self.week}"))),
                     currency, detail="Demo Hotel (4.5★)", source=self.name)


class SerpApiProvider:
    name = "serpapi"
    URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str | None = None):
        import requests
        self.requests = requests
        self.key = api_key or os.environ["SERPAPI_KEY"]

    def _get(self, params: dict) -> dict:
        r = self.requests.get(self.URL, params={**params, "api_key": self.key}, timeout=60)
        r.raise_for_status()
        return r.json()

    def flight_price(self, item_id, origin, dest, date, adults, currency, ref=None) -> Quote | None:
        data = self._get({
            "engine": "google_flights", "type": 2,  # one-way
            "departure_id": origin, "arrival_id": dest, "outbound_date": date.isoformat(),
            "adults": adults, "currency": currency, "hl": "en",
        })
        options = [o for o in (data.get("best_flights") or []) + (data.get("other_flights") or []) if o.get("price")]
        if not options:
            return None
        best = min(options, key=lambda o: o["price"])
        segs = best.get("flights", [])
        airlines = ", ".join(sorted({s.get("airline", "?") for s in segs}))
        stops = max(0, len(segs) - 1)
        hours = best.get("total_duration", 0) / 60
        return Quote(item_id, "flight", date, float(best["price"]) / adults, currency,
                     detail=f"{airlines} · {'nonstop' if not stops else f'{stops} stop' + ('s' if stops > 1 else '')} · {hours:.0f}h",
                     link=data.get("search_metadata", {}).get("google_flights_url", ""), source=self.name)

    def stay_price(self, item_id, query, check_in, check_out, adults, max_price, currency, ref=None) -> Quote | None:
        params = {"engine": "google_hotels", "q": query, "check_in_date": check_in.isoformat(),
                  "check_out_date": check_out.isoformat(), "adults": adults, "currency": currency,
                  "hl": "en", "sort_by": 8, "rating": 8}   # highest rated, 4.0+
        if max_price:
            params["max_price"] = int(max_price)
        props = [p for p in self._get(params).get("properties", [])
                 if p.get("rate_per_night", {}).get("extracted_lowest")]
        if not props:
            return None
        best = min(props[:10], key=lambda p: p["rate_per_night"]["extracted_lowest"])
        return Quote(item_id, "stay", check_in, float(best["rate_per_night"]["extracted_lowest"]), currency,
                     detail=f"{best.get('name', '?')} ({best.get('overall_rating', '–')}★)",
                     link=best.get("link", ""), source=self.name)


def get_provider(name: str | None = None):
    name = name or ("serpapi" if os.environ.get("SERPAPI_KEY") else "demo")
    return SerpApiProvider() if name == "serpapi" else DemoProvider()
