# Trip Planning Tool ✈️

Planning tool for Elliot's part of our 2027 trip, **June 6 – July 12**: Japan → Thailand → Indonesia →
Vietnam, then home to Toronto (Cat carries on to Greece and Croatia). Change the window in `trip.yaml`.

**Our Google Sheet is the plan.** Every Sunday the tool reads the latest version of the sheet,
prices every flight and hotel in it, and writes a report that says:

- **BUY / WATCH / WAIT** for each flight and stay, with price history
- **Cheaper swaps**: the same flight a day or two earlier or later, or from a nearby airport
- **Things to fix in the sheet**: flights in the calendar but not the flights tab, days where the
  calendar has you in a different city from where the flight leaves, vague stops ("THAILAND"), notes
  that don't match where you'll be
- **Option A vs B** when the flights tab lists an alternative (the "OR" table)

**Your table in the sheet is the weekly tracker.** The tool tracks the flights in the table titled
**"Elliot Flights - Current Recommendation"** (in the flights tab). Every Sunday it fills in each
unbooked row's Cost, Length and Flight Number with the best current price for that date and route,
and writes a Notes line: BUY / WATCH / WAIT, the change since last week, and up to two better options.
It never changes Date / Depart / Arrive (to take a suggestion, edit the row yourself, and the next
run tracks the new flight), and it leaves Booked rows alone. Demo prices are never written to the sheet.

Dates and cities are treated loosely: anything the sheet doesn't spell out is filled in with a best
guess, marked *assumed*, and listed so you can fix it in the sheet.

**Coming next:** a 3D globe of the route and suggestions, then Instagram reels → place ideas.

## Setup (GitHub secrets)

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | What |
|---|---|
| `TRIP_SHEET_URL` | The Google Sheet link. The sheet must be shared as *Anyone with the link → Viewer*. |
| `SERPAPI_KEY` | From [serpapi.com](https://serpapi.com), for real Google Flights / Hotels prices. Without it you get demo prices. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Lets the job write prices into your table. See below. |

### Letting the weekly job edit the sheet

1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project (any name).
2. **APIs & Services → Library → Google Sheets API → Enable.**
3. **IAM & Admin → Service Accounts → Create service account** (any name, no roles needed).
4. Open it → **Keys → Add key → Create new key → JSON**. A `.json` file downloads.
5. In the Google Sheet: **Share** → paste the service account's email (`…@….iam.gserviceaccount.com`)
   → **Editor**.
6. In GitHub, add a secret `GOOGLE_SERVICE_ACCOUNT_JSON` and paste the whole contents of the JSON file.
   Then delete the file from your computer.

Then **Actions → Weekly price report → Run workflow** to run it now. After that it runs every Sunday
morning and saves `reports/latest.html` (the report) and `reports/plan.json` (data for the globe).

## How the sheet is read

- **Calendar tab**: weekly blocks. A row of dates, then *where you are* ("JAPAN - TOKYO",
  "THAILAND to INDONESIA"), then notes. City names in the notes count too ("Fukuoka to Kagoshima"
  = you end the day in Kagoshima). The year comes from which weekday column the dates are in.
- **flights tab**: tables of Date / Depart / Arrive / Cost / Length / Flight Number / Booked. The tool
  uses the one titled "Elliot Flights" (set in `trip.yaml`); if it's missing it falls back to the first
  table. Tick `Booked` to stop tracking a flight.
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
triptool/writeback.py   write prices + notes into your table in the sheet
```
