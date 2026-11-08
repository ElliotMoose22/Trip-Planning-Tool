# Trip Planning Tool ✈️

Planning tool for our June–August 2027 trip: Japan → Thailand → Indonesia → Vietnam → Greece → Croatia.

**Our Google Sheet is the plan.** Every Sunday the tool reads the latest version of the sheet,
prices every flight and hotel in it, and writes a report that says:

- **BUY / WATCH / WAIT** for each flight and stay, with price history
- **Cheaper swaps**: the same flight a day or two earlier or later, or from a nearby airport
- **Things to fix in the sheet**: flights in the calendar but not the flights tab, days where the
  calendar has you in a different city from where the flight leaves, vague stops ("THAILAND"), notes
  that don't match where you'll be
- **Option A vs B** when the flights tab lists an alternative (the "OR" table)

Dates and cities are treated loosely: anything the sheet doesn't spell out is filled in with a best
guess, marked *assumed*, and listed so you can fix it in the sheet.

**Coming next:** a 3D globe of the route and suggestions, then Instagram reels → place ideas.

## Setup (GitHub secrets)

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | What |
|---|---|
| `TRIP_SHEET_URL` | The Google Sheet link. The sheet must be shared as *Anyone with the link → Viewer*. |
| `SERPAPI_KEY` | From [serpapi.com](https://serpapi.com), for real Google Flights / Hotels prices. Without it you get demo prices. |

Then **Actions → Weekly price report → Run workflow** to run it now. After that it runs every Sunday
morning and saves `reports/latest.html` (the report) and `reports/plan.json` (data for the globe).

## How the sheet is read

- **Calendar tab**: weekly blocks. A row of dates, then *where you are* ("JAPAN - TOKYO",
  "THAILAND to INDONESIA"), then notes. City names in the notes count too ("Fukuoka to Kagoshima"
  = you end the day in Kagoshima). The year comes from which weekday column the dates are in.
- **flights tab**: Date / Depart / Arrive / Cost / Length / Flight Number / Booked. Mark `Booked`
  TRUE to stop tracking a flight. A second table to the right (after "OR") is option B.
- New city? Add it to `triptool/places.py` (airports + coordinates).

## Settings

[`trip.yaml`](trip.yaml): how many days of flexibility to search, the weekly search cap (fit it to
your SerpApi plan), hotel budgets by country, and which neighbourhood to look in for each city.

## Run locally

```bash
pip install -r requirements.txt
export TRIP_SHEET_URL="https://docs.google.com/spreadsheets/d/…"
python -m triptool plan     # how the sheet was read + the checks, no searches
python -m triptool demo     # full report with fake prices → reports/demo/latest.html
python -m triptool run      # real thing (needs SERPAPI_KEY)
python -m pytest -q
```

## Layout

```
triptool/sheet.py       download + read the Google Sheet
triptool/plan.py        nights, stops, legs, checks
triptool/places.py      city → airports + coordinates, nearby alternatives
triptool/recommend.py   what to search each week, and the swaps worth suggesting
triptool/providers.py   prices (demo, SerpApi)
triptool/signals.py     BUY / WATCH / WAIT rules
triptool/report.py      HTML / Markdown report + plan.json
```
