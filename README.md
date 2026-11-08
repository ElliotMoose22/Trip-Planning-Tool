# Trip Planning Tool ✈️

Planning tool for Elliot's part of our 2027 trip, **June 6 – July 12**: Japan → Thailand → Indonesia →
Vietnam, then home to Toronto (Cat carries on to Greece and Croatia). Change the window in `trip.yaml`.

**Our Google Sheet is the plan**, in two tabs:

- **Places**: every stop with its country, priority (Must / Want / Maybe), min–max nights, fixed
  dates, and the planned Arrive / Leave. Countries go in order: Japan → Thailand → Indonesia → Vietnam.
- **Legs**: every bookable trip (flight, train, bus, ferry, car) with its mode, date or search window
  (Earliest / Latest), status (Idea → Planned → Booked), price and booking ref.

Rows are colour-coded by country to match the calendar. Every Sunday the tool reads the latest version of the sheet,
prices every flight and hotel in it, and writes a report that says:

- **BUY / WATCH / WAIT** for each flight and stay, with price history
- **Cheaper swaps**: the same flight a day or two earlier or later, or from a nearby airport
- **Things to fix in the sheet**: flights in the calendar but not the flights tab, days where the
  calendar has you in a different city from where the flight leaves, vague stops ("THAILAND"), notes
  that don't match where you'll be
- **Option A vs B** when the flights tab lists an alternative (the "OR" table)

**The Legs tab is the weekly tracker.** Every Sunday the tool fills in each unbooked flight's Price,
Length and Flight no. with the best current price for that date and route (searching its Earliest /
Latest window), and writes a Notes line: BUY / WATCH / WAIT, the change since last week, and up to two
better options. It also writes each stop's checks into the Places tab's Notes column (nights outside
your range, a Must without dates, gaps or overlaps, a move with no leg).
It never changes Date / Depart / Arrive (to take a suggestion, edit the row yourself, and the next
run tracks the new flight), and it leaves Booked rows alone. Demo prices are never written to the sheet.

Dates and cities are treated loosely: anything the sheet doesn't spell out is filled in with a best
guess, marked *assumed*, and listed so you can fix it in the sheet.

**Also:** a 3D globe of the route ([live map](https://elliotmoose22.github.io/Trip-Planning-Tool/)) and an Instagram reels inbox (below).

## Setup (GitHub secrets)

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | What |
|---|---|
| `TRIP_SHEET_URL` | The Google Sheet link. The sheet must be shared as *Anyone with the link → Viewer*. |
| `SERPAPI_KEY` | From [serpapi.com](https://serpapi.com), for real Google Flights / Hotels prices. Without it you get demo prices. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Lets the job write prices into your table. See below. |
| `CLAUDE_CODE_OAUTH_TOKEN` | Optional. From `claude setup-token`; lets the reels job read captions on your Claude plan. |

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

## Instagram reels → trip ideas

DM reels to the trip Instagram account and send a rating (1–10) after each one. An Apps Script in the
sheet (`instagram/Code.gs`) adds each reel to the **Reels** tab. Every evening `daily-reels.yml` runs
`python -m triptool reels`, which:

1. reads the caption with Claude to work out every place it names (or uses the places you sent after the
   rating, like `8 Kamakura, Enoshima`); a reel with several places becomes one row and pin per place,
2. finds it on the map and grabs a photo from Wikipedia,
3. sorts it against your stops: **green** = day trip (≤ 2.5 hrs, about 115 km) from a stop,
   **yellow** = needs a night (on the way between two stops, or a short overnight from one),
   **red** = off the route,
4. lists it under its country and stop in the **Ideas** tab, and adds an *Idea* recommendation when a
   yellow reel deserves a night in between (e.g. Hua Hin between Bangkok and Phuket).

The dashboard shows each reel as a small diamond pin with the day-trip rings around your stops; click
one for the name, rating, who sent it and the photo. Setup: [instagram/SETUP.md](instagram/SETUP.md).
Change the day-trip limit with `reels: daytrip_hours` in `trip.yaml`.

## How the sheet is read

- **Places + Legs tabs** (preferred): read as-is. If they're missing, the tool falls back to:
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
triptool/reels.py       reels → place, map colour, photo, Ideas tab
instagram/              Apps Script inbox + setup steps


 ## OVERVIEW + IDEAS

Current set up is using the Google Sheets calendar as a reference to determine flight path and search for best flights and possible alternatives.
Need to find a clear way to determine how Claude can best search for other flights and options, without making the scope too large.
Should create a "key cities" log, that has places that we want included in the trip no matter what. Can also define the amount of time we are willing to schange for each flight, I am thinking +/- two days to give best price reccomendation. Also want it to suggest alternative routes and options of travel, can do this by allowing Claude to pick amongst other travel hubs that are on route, whihc we may not mention in the Google Sheets.

```
