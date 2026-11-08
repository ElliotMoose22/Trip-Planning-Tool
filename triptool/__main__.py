"""CLI.

  python -m triptool run                 # check prices + write report
  python -m triptool check               # just check prices
  python -m triptool report              # just rebuild the report
  python -m triptool demo --weeks 10     # seed fake history so the report has something to show
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from .config import load_trip
from .providers import DemoProvider, get_provider
from .report import write_report
from .store import Store


def check(trip, store, provider, today):
    n = 0
    for leg in trip.flights:
        if leg.booked:
            continue
        for d in leg.search_dates():
            try:
                q = provider.flight_price(leg, d, trip.travelers, trip.currency)
            except Exception as e:  # keep going if one search fails
                print(f"  ! {leg.label} {d}: {e}", file=sys.stderr)
                continue
            if q:
                store.add(q, today)
                n += 1
                print(f"  {leg.label:28} {d}  ${q.price:,.0f}  {q.detail}")
    for stay in trip.stays:
        if stay.booked:
            continue
        try:
            q = provider.stay_price(stay, trip.currency)
        except Exception as e:
            print(f"  ! {stay.label}: {e}", file=sys.stderr)
            continue
        if q:
            store.add(q, today)
            n += 1
            print(f"  {stay.label:28} {stay.check_in}  ${q.price:,.0f}/night  {q.detail}")
    return n


def main(argv=None):
    p = argparse.ArgumentParser(prog="triptool")
    p.add_argument("command", choices=["run", "check", "report", "demo"])
    p.add_argument("--trip", default="trip.yaml")
    p.add_argument("--db", default="data/prices.db")
    p.add_argument("--provider", choices=["demo", "serpapi"], default=None)
    p.add_argument("--weeks", type=int, default=10, help="weeks of history for `demo`")
    a = p.parse_args(argv)

    trip = load_trip(a.trip)
    today = dt.date.today()

    if a.command == "demo":
        store = Store("data/demo.db")
        for w in range(a.weeks, -1, -1):
            day = today - dt.timedelta(weeks=w)
            check(trip, store, DemoProvider(today=day), day) if w == 0 else \
                _quiet(check, trip, store, DemoProvider(today=day), day)
        path = write_report(trip, store, "demo", today, "reports/demo")
        print(f"\nDemo report: {path}")
        return

    store = Store(a.db)
    provider = get_provider(a.provider)
    if a.command in ("run", "check"):
        print(f"Checking prices with {provider.name}…")
        print(f"{check(trip, store, provider, today)} quotes saved.")
    if a.command in ("run", "report"):
        print(f"Report: {write_report(trip, store, provider.name, today)}")


def _quiet(fn, *args):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


if __name__ == "__main__":
    main()
