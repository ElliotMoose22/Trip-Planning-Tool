# Asia Trip Tool ✈️

Planning tool for our June–July 2027 trip: Japan → Thailand → Indonesia → Vietnam.

**What it does now:** every Sunday it checks flight and hotel prices for each leg of the trip,
saves the history, and writes a report that says **BUY / WATCH / WAIT** for each item.

**Coming next:** paste Instagram reel links → places get pulled out and suggested for the itinerary.

## Try it (no API key needed)

```bash
pip install -r requirements.txt
python -m triptool demo        # fake price history → reports/demo/latest.html
python -m pytest -q
```

## Track real prices

1. Get a key at [serpapi.com](https://serpapi.com) (Google Flights + Google Hotels data).
2. Locally: `SERPAPI_KEY=... python -m triptool run` → `reports/latest.html`
3. On GitHub: **Settings → Secrets and variables → Actions → New secret** named `SERPAPI_KEY`.
   The **Weekly price report** workflow then runs every Sunday morning, commits the updated
   history and report, and shows a summary table on the workflow run page.
   Run it any time from the **Actions** tab → *Run workflow*.

Each weekly run uses about one search per flight date + one per city (≈26 with the default `trip.yaml`).

## Change the plan

Everything lives in [`trip.yaml`](trip.yaml): legs, dates, how many days of flexibility to search,
hotel areas and nightly budgets. Set `booked: true` on anything you've bought to stop tracking it.

## How the BUY / WAIT call works

See [`triptool/signals.py`](triptool/signals.py). Short version: wait until the usual booking window
(≈2–6 months out for long-haul, 3–14 weeks for flights within Asia), then buy when the price is at
or below what we've typically seen. Unusually cheap prices trigger a BUY early. These are rules of
thumb, not predictions.

## Layout

```
trip.yaml                 the plan
triptool/providers.py     where prices come from (demo, SerpApi)
triptool/store.py         SQLite price history (data/prices.db)
triptool/signals.py       BUY / WATCH / WAIT rules
triptool/report.py        HTML + Markdown report
.github/workflows/        weekly schedule
```
