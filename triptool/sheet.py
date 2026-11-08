"""Read the trip Google Sheet.

The sheet is downloaded through its share link ("Anyone with the link can
view"), so the weekly job always sees the latest edits. Two tabs are used:

- Calendar: weekly blocks. A row of dates ("June 6"), the row below is where
  you are ("JAPAN - TOKYO", "THAILAND to INDONESIA"), the row below that is
  notes. Columns are headed SUNDAY ... SATURDAY.
- flights: a table with Date / Depart / Arrive / Cost / ... / Booked. A second
  table to the right (after an "OR") is read as an alternative option.

The year isn't written in the sheet, so it's worked out from which weekday
column each date sits in (June 6 under SUNDAY -> 2027).
"""
from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass, field

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DATE_RE = re.compile(r"^\s*([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*$")

Grid = list[list[str]]


# ---------- loading ----------

def export_url(share_url: str) -> str:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", share_url)
    if not m:
        raise ValueError(f"Not a Google Sheets link: {share_url}")
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=xlsx"


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        d = v.date() if isinstance(v, dt.datetime) else v
        return f"{d:%B} {d.day}|{d.year}"   # keep the year if the sheet had real dates
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def grids_from_xlsx(data: bytes) -> dict[str, Grid]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    out = {}
    for ws in wb.worksheets:
        out[ws.title] = [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
    return out


def download(share_url: str) -> dict[str, Grid]:
    import requests
    r = requests.get(export_url(share_url), timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"PK"):
        raise RuntimeError("Couldn't download the sheet — is it shared as 'Anyone with the link can view'?")
    return grids_from_xlsx(r.content)


def find_tab(grids: dict[str, Grid], *names: str) -> Grid:
    for title, grid in grids.items():
        if title.strip().lower() in names:
            return grid
    raise KeyError(f"No tab named {' / '.join(names)} (found: {', '.join(grids)})")


# ---------- calendar ----------

@dataclass
class Day:
    date: dt.date
    where: str          # raw text, e.g. "JAPAN - TOKYO"
    notes: str
    side_notes: list[str] = field(default_factory=list)  # text written beside that week


def _month_day(text: str) -> tuple[int, int, int | None] | None:
    text = text.strip()
    year = None
    if "|" in text:
        text, y = text.split("|", 1)
        year = int(y)
    m = DATE_RE.match(text)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return MONTHS[m.group(1).lower()], int(m.group(2)), year


def _at(grid: Grid, r: int, c: int) -> str:
    return grid[r][c] if r < len(grid) and c < len(grid[r]) else ""


def parse_calendar(grid: Grid, year: int | None = None, today: dt.date | None = None) -> list[Day]:
    today = today or dt.date.today()
    col_weekday: dict[int, int] = {}
    for row in grid[:10]:
        for c, v in enumerate(row):
            if v.strip().lower() in WEEKDAYS:
                col_weekday[c] = WEEKDAYS.index(v.strip().lower())
        if col_weekday:
            break
    last_day_col = max(col_weekday) if col_weekday else 99

    raw = []  # (month, day, year?, col, where, notes, side)
    for r, row in enumerate(grid):
        side = [v.strip() for c, v in enumerate(row) if c > last_day_col and v.strip()]
        for c, v in enumerate(row):
            md = _month_day(v)
            if not md:
                continue
            notes = _at(grid, r + 2, c)
            if _month_day(notes):
                notes = ""
            raw.append((*md, c, _at(grid, r + 1, c).strip(), notes.strip(), side))

    if year is None:
        year = infer_year(raw, col_weekday, today)
    # Ignore any year hidden inside date cells: Google Sheets fills in the year you typed
    # them, which is often wrong. The weekday columns decide.
    days = [Day(dt.date(year, m, d), where, notes, side) for m, d, y, c, where, notes, side in raw]
    return sorted(days, key=lambda d: d.date)


def hidden_years(grid: Grid) -> set[int]:
    """Years stored inside real date cells (invisible with a "mmmm d" format)."""
    return {md[2] for row in grid for v in row if (md := _month_day(v)) and md[2]}


def infer_year(raw, col_weekday, today: dt.date) -> int:
    for y in range(today.year, today.year + 4):
        ok = all(dt.date(y, m, d).weekday() == col_weekday[c]
                 for m, d, _y, c, *_ in raw if c in col_weekday)
        if ok:
            return y
    return today.year + 1


# ---------- flights ----------

@dataclass
class PlannedFlight:
    date: dt.date
    origin: str
    destination: str
    cost: float | None
    duration: str = ""
    flight_no: str = ""
    booked: bool = False
    note: str = ""
    option: str = "A"          # "B" = the alternative table
    source: str = "flights tab"
    row: int | None = None     # 0-based row in the tab (for writing back)


def _money(v: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", v or "")
    return float(m.group().replace(",", "")) if m else None


@dataclass
class FlightTable:
    flights: list[PlannedFlight]
    title_row: int | None
    header_row: int
    cols: dict[str, int]       # date/from/to/cost/len/no/booked/notes -> column index


def parse_flights(grid: Grid, year: int) -> list[PlannedFlight]:
    t = parse_flight_table(grid, year)
    return t.flights if t else []


def parse_flight_table(grid: Grid, year: int, title: str | None = None) -> FlightTable | None:
    """The first Date/Depart/Arrive table, or the first one under a cell containing `title`."""
    start, title_row = 0, None
    if title:
        title_row = next((r for r, row in enumerate(grid)
                          if any(title.lower() in v.lower() for v in row)), None)
        if title_row is None:
            return None
        start = title_row + 1
    hdr_row, cols = None, {}
    for r, row in enumerate(grid[start:], start):
        low = [v.strip().lower() for v in row]
        if "date" in low and ("depart" in low or "from" in low):
            hdr_row = r
            for c, v in enumerate(low):
                for key, names in {"date": ["date"], "from": ["depart", "from"], "to": ["arrive", "to"],
                                   "cost": ["cost", "price"], "len": ["length (hrs)", "length", "duration"],
                                   "no": ["flight number", "flight", "flight #"], "booked": ["booked"]}.items():
                    if v in names and key not in cols:
                        cols[key] = c
                if v.startswith("notes") and "notes" not in cols:
                    cols["notes"] = c
            break
    if hdr_row is None:
        return None
    notes_col = cols.pop("notes", None)
    last = max(cols.values())
    flights: list[PlannedFlight] = []

    def mk(row, base, colmap, option):
        get = lambda k: _at([row], 0, base + colmap[k]) if k in colmap else ""
        md = _month_day(get("date"))
        if not md or not get("from").strip():
            return None
        m, d, _hidden_year = md
        return PlannedFlight(
            date=dt.date(year, m, d), origin=get("from").strip(), destination=get("to").strip(),
            cost=_money(get("cost")), duration=get("len").strip(), flight_no=get("no").strip(),
            booked=get("booked").strip().upper() == "TRUE", option=option)

    rel = {k: v - cols["date"] for k, v in cols.items()}
    rel_b = {k: v for k, v in rel.items() if k != "booked"}   # right-hand table has no Booked column
    for r, row in enumerate(grid[hdr_row + 1:], hdr_row + 1):
        if _at([row], 0, cols["date"]).strip().lower() == "total":
            break
        if not any(v.strip() for v in row):
            break
        f = mk(row, cols["date"], rel, "A")
        if f:
            f.row = r
            extra = [v.strip() for c, v in enumerate(row) if c > last and v.strip()]
            # a second date further right starts the alternative ("OR") table
            for c in range(last + 1, len(row)):
                if _month_day(row[c]):
                    b = mk(row, c, rel_b, "B")
                    if b:
                        flights.append(b)
                    extra = [v.strip() for cc, v in enumerate(row) if last < cc < c and v.strip()]
                    break
            f.note = " ".join(e for e in extra if e.upper() != "OR")
            flights.append(f)
    # Rows that appear in both options are the same flight
    a_keys = {(f.date, f.origin.lower(), f.destination.lower()) for f in flights if f.option == "A"}
    flights = [f for f in flights if f.option == "A" or (f.date, f.origin.lower(), f.destination.lower()) not in a_keys]
    if notes_col is None:
        notes_col = cols.get("booked", last) + 1
    return FlightTable(flights, title_row, hdr_row, {**cols, "notes": notes_col})
