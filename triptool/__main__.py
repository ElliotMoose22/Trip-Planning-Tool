"""CLI.

  python -m triptool run                     # read the sheet, check prices, write the report
  python -m triptool plan                    # just show how the sheet was read + the checks
  python -m triptool demo --weeks 10         # fake price history, so the report has something to show

Where the trip comes from (first that's set):
  --sheet-json FILE      a saved copy of the sheet (for testing)
  TRIP_SHEET_URL         the Google Sheet share link (GitHub secret)
  sheet.url in trip.yaml
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import sys

from .config import Settings, load_settings
from .plan import Check, Plan, build_plan
from .providers import DemoProvider, get_provider
from .recommend import km, plan_searches, summarize
from .report import build_stays, write_report
from .sheet import FlightTable, download, find_tab, hidden_years, parse_calendar, parse_flight_table
from .store import Store


def load_plan(s: Settings, sheet_json: str | None, today: dt.date) -> tuple[Plan, FlightTable | None, str]:
    """Returns the plan, your flights table (if the sheet has one) and the flights tab's name."""
    if sheet_json:
        grids = json.load(open(sheet_json))
    elif s.sheet_url:
        grids = download(s.sheet_url)
    else:
        sys.exit("No sheet configured. Set TRIP_SHEET_URL (or sheet.url in trip.yaml), or pass --sheet-json.")
    names = {t.strip().lower(): t for t in grids}
    cal = find_tab(grids, "calendar")
    days = parse_calendar(cal, today=today)
    year = s.start.year if s.start else (days[0].date.year if days else today.year + 1)

    # Preferred: the structured Places + Legs tabs.
    if "legs" in names:
        from .tables import build_from_tables, parse_legs, parse_places
        legs_parsed = parse_legs(grids[names["legs"]], year)
        places_parsed = parse_places(grids[names["places"]], year) if "places" in names else None
        if legs_parsed:
            leg_rows, table = legs_parsed
            place_rows = places_parsed[0] if places_parsed else []
            plan = build_from_tables(place_rows, leg_rows, s.start, s.end)
            plan.places = places_parsed
            from .tables import recommend
            plan.recs = recommend(place_rows, leg_rows, s.start, s.end)
            plan.place_rows = place_rows
            if "reels" in names:
                from .reels import parse_reels
                plan.reels = parse_reels(grids[names["reels"]])
            return plan, table, names["legs"]

    # Fallback: the calendar + a flights table.
    fl = find_tab(grids, "flights")
    tab = next(t for t, g in grids.items() if g is fl)

    # Your own table wins; otherwise fall back to the first table in the tab.
    mine = parse_flight_table(fl, year, s.my_table) if s.my_table else None
    table = mine or parse_flight_table(fl, year)
    flights = table.flights if table else []
    if mine:
        for f in flights:
            f.source = "my table"

    # Only plan inside the trip window
    inside = lambda d: (not s.start or d >= s.start) and (not s.end or d <= s.end)
    days = [d for d in days if inside(d.date) and (not s.end or d.date < s.end)]   # last day = travel day
    flights = [f for f in flights if inside(f.date)]
    plan = build_plan(days, flights, s.home)
    wrong = sorted((hidden_years(cal) | hidden_years(fl)) - {year})
    if wrong:
        plan.checks.append(Check("heads-up", f"Your date cells are stored as {', '.join(map(str, wrong))} dates "
                                 f"(the year is hidden by the formatting), but the weekday columns only line up "
                                 f"with {year}, so I'm reading the trip as {year}. Nothing to do unless you add "
                                 f"formulas that use those dates."))
    return plan, mine, tab


def handle_reels(plan: Plan, s: Settings, online: bool) -> None:
    """Place every reel, sort it into the trip, and add 'Idea' recommendations."""
    parsed = getattr(plan, "reels", None)
    if not parsed:
        return
    from .reels import idea_recs, process
    rows, _cols = parsed
    flown = {(l.origin.name, l.destination.name) for l in plan.legs}
    stats = process(rows, plan.stops, s.daytrip_hours, online=online, flown=flown)
    plan.recs = getattr(plan, "recs", []) + idea_recs(rows, plan.stops, getattr(plan, "place_rows", None))
    placed = sum(1 for r in rows if r.colour)
    print(f"Reels: {len(rows)} in the sheet, {placed} placed"
          + (f" ({stats['watched']} watched, {stats['read']} read, {stats['located']} located, {stats['photos']} Wikipedia photos)" if online else ""))


def run_searches(plan: Plan, s: Settings, store: Store, provider, today: dt.date, verbose=True) -> dict:
    results = {}
    searches = plan_searches(plan, s, today)
    for x in searches:
        try:
            if x.kind == "flight":
                ref = x.leg.flight.cost or round(70 + 0.09 * km(x.origin, x.dest))   # demo fallback by distance
                q = provider.flight_price(x.item_id, x.origin.codes, x.dest.codes, x.date, 1, s.currency, ref)
                label = f"{x.origin.name} → {x.dest.name}"
            else:
                st = x.stop
                query = s.hotel_areas.get(st.place.name.lower(), st.place.name)
                ref = s.hotel_typical.get(st.place.country.lower())
                q = provider.stay_price(x.item_id, query, st.check_in, st.check_out, s.hotel_adults,
                                        s.hotel_max_price.get(st.place.country.lower()), s.currency, ref)
                label = f"Hotel {st.place.name}"
        except Exception as e:   # one failed search shouldn't sink the run
            print(f"  ! {x.item_id} {x.date}: {e}", file=sys.stderr)
            continue
        if q:
            store.add(q, today)
            results[(x.item_id, x.date)] = q
            if verbose:
                print(f"  [{x.why:8}] {label:34} {x.date:%b %d}  ${q.price:,.0f}  {q.detail}")
    if verbose:
        print(f"{len(results)}/{len(searches)} searches returned prices (cap {s.max_searches}).")
    return results


def report(plan, s, store, results, source, today, out_dir):
    legs = summarize(plan, results, s)
    stays = build_stays(plan, s, results, store, source, today)
    return write_report(s, plan, legs, stays, store, source, today, out_dir), legs


def update_sheet(s, plan, table, tab, legs, store, source, today) -> None:
    """Write this week's prices into your table. Real prices only, and only with Google credentials."""
    import os
    from .report import leg_signal
    from .writeback import build_updates, push
    if table is None:
        print("Sheet update skipped: no Legs tab (or table titled", repr(s.my_table) + ")")
        return
    if source == "demo":
        print("Sheet update skipped: demo prices are never written to the sheet.")
        return
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        print("Sheet update skipped: GOOGLE_SERVICE_ACCOUNT_JSON isn't set.")
        return
    from .writeback import build_place_updates, build_recs_updates
    recs = getattr(plan, "recs", [])
    sigs = {lr.leg.id: leg_signal(lr, store, source, today) for lr in legs}
    data = build_updates(table, tab, legs, sigs, today, recs)
    data += build_place_updates(getattr(plan, "places", None), "Places", recs)
    if recs:
        data += build_recs_updates(recs, today)
    if getattr(plan, "reels", None):
        from .reels import ideas_rows, ideas_update, write_back
        rows, cols = plan.reels
        data += write_back(rows, cols) + ideas_update(ideas_rows(rows, plan.stops))
    print(f"Updated {push(s.sheet_url, data)} cells in your sheet.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="triptool")
    p.add_argument("command", choices=["run", "plan", "demo", "reels"])
    p.add_argument("--settings", default="trip.yaml")
    p.add_argument("--sheet-json")
    p.add_argument("--db", default="data/prices.db")
    p.add_argument("--provider", choices=["demo", "serpapi"])
    p.add_argument("--weeks", type=int, default=10)
    a = p.parse_args(argv)

    s = load_settings(a.settings)
    today = dt.date.today()
    plan, table, tab = load_plan(s, a.sheet_json, today)

    handle_reels(plan, s, online=a.command in ("run", "reels"))

    if a.command == "reels":     # daily: place new reels, no price checks
        import os
        if not getattr(plan, "reels", None):
            print("No Reels tab in the sheet yet.")
            return
        from .report import update_plan_reels
        print(f"Map data: {update_plan_reels(plan)} reels in reports/plan.json")
        if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
            print("Reels placed but not saved: GOOGLE_SERVICE_ACCOUNT_JSON isn't set.")
            return
        from .reels import ideas_rows, ideas_update, write_back
        from .writeback import build_recs_updates, push
        rows, cols = plan.reels
        data = write_back(rows, cols) + ideas_update(ideas_rows(rows, plan.stops))
        recs = getattr(plan, "recs", [])
        if recs:
            data += build_recs_updates(recs, today)
        print(f"Updated {push(s.sheet_url, data)} cells in your sheet.")
        return

    if a.command == "plan":
        for r in (getattr(plan, "reels", None) or ([], {}))[0]:
            print(f"  reel [{r.colour or 'not placed'}] {r.place or r.link}: {r.fits}")
        print(f"Trip year: {plan.year}\n\nStops:")
        for st in plan.stops:
            print(f"  {st.check_in:%b %d} → {st.check_out:%b %d}  {st.nights:>2} nights  {st.place.name}"
                  f"{'  (assumed)' if st.assumed else ''}")
        print("\nFlights:")
        for leg in plan.legs:
            f = leg.flight
            print(f"  {f.date:%b %d}  {leg.origin.name} → {leg.destination.name}  ${f.cost or 0:,.0f}"
                  f"{'  BOOKED' if f.booked else ''}{'  (option B)' if f.option == 'B' else ''}"
                  f"{'  (from calendar)' if f.source == 'calendar' else ''}")
        print("\nOn the ground:")
        for g in plan.ground:
            print(f"  by {g.by:%b %d}  {g.origin.name} → {g.destination.name}  {g.mode}  ~{g.km:,.0f} km  ~{g.hours:.0f} hrs")
        print("\nRecommendations:")
        for r in getattr(plan, "recs", []):
            print(f"  [{r.kind}] {r.title}\n      {r.detail}")
        print("\nChecks:")
        for c in plan.checks:
            print(f"  [{c.level}] {c.text}")
        return

    if a.command == "demo":
        store = Store("data/demo.db")
        results = {}
        for w in range(a.weeks, -1, -1):
            day = today - dt.timedelta(weeks=w)
            with contextlib.redirect_stdout(io.StringIO()):
                results = run_searches(plan, s, store, DemoProvider(today=day), day)
        print(f"Demo report: {report(plan, s, store, results, 'demo', today, 'reports/demo')[0]}")
        return

    store = Store(a.db)
    provider = get_provider(a.provider)
    print(f"Checking prices with {provider.name}…")
    results = run_searches(plan, s, store, provider, today)
    path, legs = report(plan, s, store, results, provider.name, today, "reports")
    print(f"Report: {path}")
    try:
        update_sheet(s, plan, table, tab, legs, store, provider.name, today)
    except Exception as e:   # the report is already saved; don't fail the whole run
        print(f"! Couldn't update the sheet: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
