"""Reels: where each one is, and how it fits the route.

Flow for each row of the Reels tab that isn't placed yet:
  1. Place  - read from the caption by Claude (Claude Code on your subscription,
              CLAUDE_CODE_OAUTH_TOKEN), unless you've typed the Place yourself.
  2. Where  - coordinates from OpenStreetMap (Nominatim), unless Lat/Lon are filled.
  3. Photo  - the place's Wikipedia image (shown in the sheet with =IMAGE and kept
              as a small embedded copy for the dashboard, which can't load web images).
  4. Fit    - Green: day trip from a stop. Yellow: on the way between two stops, or
              an overnight trip from one. Red: doesn't fit the route.
Then the Ideas tab is rebuilt and "Idea" recommendations are added.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from .plan import Stop
from .tables import Rec
from .sheet import Grid, _at, _month_day

UA = "trip-planning-tool/1.0 (+https://github.com/ElliotMoose22/Trip-Planning-Tool)"
ROAD = 1.3            # road km per straight-line km
SPEED = 60            # door-to-door km/h for day trips


@dataclass
class ReelRow:
    row: int
    received: str
    sender: str
    link: str
    caption: str
    rating: int | None
    place: str
    country: str
    lat: float | None
    lon: float | None
    status: str
    photo: str = ""
    photo_data: str = ""
    # filled by classify()
    colour: str = ""
    fits: str = ""
    anchor: Stop | None = None
    between: tuple[Stop, Stop] | None = None
    km: float | None = None
    hours: float | None = None
    changed: bool = False


def _num(v: str) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def parse_reels(grid: Grid) -> tuple[list[ReelRow], dict[str, int]] | None:
    hr = next((r for r, row in enumerate(grid[:10]) if any(v.strip().lower() == "reel link" for v in row)), None)
    if hr is None:
        return None
    low = [v.strip().lower() for v in grid[hr]]
    col = lambda *names: next((i for i, v in enumerate(low) if any(v.startswith(n) for n in names)), None)
    c = {"received": col("received"), "from": col("from"), "link": col("reel link"), "caption": col("caption"),
         "rating": col("rating"), "place": col("place"), "country": col("country"), "lat": col("lat"),
         "lon": col("lon"), "fits": col("fits"), "colour": col("colour", "color"), "photo": col("photo"),
         "status": col("status"), "photo_data": col("photo data")}
    if c["photo"] == c["photo_data"]:
        c["photo"] = next((i for i, v in enumerate(low) if v == "photo"), None)
    out = []
    for r in range(hr + 1, len(grid)):
        get = lambda k: _at(grid, r, c[k]).strip() if c[k] is not None else ""
        if not (get("link") or get("caption") or get("place")):
            continue
        m = re.search(r"\d+", get("rating"))
        out.append(ReelRow(r, get("received"), get("from"), get("link"), get("caption"),
                           min(10, int(m.group())) if m else None, get("place"), get("country"),
                           _num(get("lat")), _num(get("lon")), get("status"), get("photo"), get("photo_data")))
    return out, c


# ---------- 1. read the place from the caption ----------

PROMPT = """You read Instagram reel captions for a trip planner. The trip covers Japan, Thailand, Indonesia and Vietnam.
For each caption, name the single most specific place someone could travel to (an attraction, beach, island, park or town),
plus its country. If a caption doesn't name a real place, use null. Answer with JSON only, no prose:
[{"i": <number>, "place": "<name as a map would know it>" or null, "country": "<country>" or null}]

Captions:
"""


def extract_places(rows: list[ReelRow]) -> int:
    """Fill .place/.country from captions with Claude Code. Returns how many were filled."""
    todo = [r for r in rows if not r.place and r.caption]
    if not todo or not shutil.which("claude") or not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return 0
    prompt = PROMPT + "\n".join(f"{i}. {r.caption[:600]}" for i, r in enumerate(todo))
    try:
        out = subprocess.run(["claude", "-p", prompt, "--output-format", "json"], capture_output=True,
                             text=True, timeout=300).stdout
        text = json.loads(out).get("result", "")
        answer = json.loads(re.search(r"\[.*\]", text, re.S).group())
    except Exception as e:  # never sink the weekly run over this
        print(f"  ! reading captions failed: {e}")
        return 0
    n = 0
    for a in answer:
        i = a.get("i")
        if isinstance(i, int) and 0 <= i < len(todo) and a.get("place"):
            todo[i].place, todo[i].country, todo[i].changed = a["place"], a.get("country") or "", True
            n += 1
    return n


# ---------- 2. coordinates ----------

def geocode(rows: list[ReelRow], session=None) -> int:
    import requests
    s = session or requests.Session()
    n = 0
    for r in rows:
        if r.place and (r.lat is None or r.lon is None):
            q = f"{r.place}, {r.country}" if r.country else r.place
            try:
                res = s.get("https://nominatim.openstreetmap.org/search", params={"q": q, "format": "json", "limit": 1,
                            "accept-language": "en", "addressdetails": 1}, headers={"User-Agent": UA}, timeout=30).json()
            except Exception as e:
                print(f"  ! geocoding {q}: {e}")
                continue
            time.sleep(1.1)   # Nominatim asks for at most one request a second
            if res:
                r.lat, r.lon = float(res[0]["lat"]), float(res[0]["lon"])
                r.country = r.country or res[0].get("address", {}).get("country", "")
                r.changed = True
                n += 1
            else:
                r.status = "Couldn't find this place — type a clearer name in Place"
                r.changed = True
    return n


# ---------- 3. photo ----------

def fetch_photos(rows: list[ReelRow], session=None) -> int:
    import requests
    s = session or requests.Session()
    n = 0
    for r in rows:
        if not r.place or r.photo_data:
            continue
        try:
            data = s.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "generator": "search", "gsrsearch": f"{r.place} {r.country}".strip(), "gsrlimit": 1,
                "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 220, "format": "json"},
                headers={"User-Agent": UA}, timeout=30).json()
            pages = list((data.get("query") or {}).get("pages", {}).values())
            url = pages[0].get("thumbnail", {}).get("source") if pages else None
            if not url:
                continue
            img = s.get(url, headers={"User-Agent": UA}, timeout=30)
            b64 = base64.b64encode(img.content).decode()
            mime = img.headers.get("content-type", "image/jpeg").split(";")[0]
            if len(b64) < 45000:          # a Google Sheets cell holds up to 50,000 characters
                r.photo_data = f"data:{mime};base64,{b64}"
            r.photo = f'=IMAGE("{url}")'
            r.changed = True
            n += 1
        except Exception as e:
            print(f"  ! photo for {r.place}: {e}")
    return n


# ---------- 4. how it fits ----------

def km(a_lat, a_lon, b_lat, b_lon) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a_lat, a_lon, b_lat, b_lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def daytrip_km(hours: float) -> float:
    return hours * SPEED / ROAD


def classify(r: ReelRow, stops: list[Stop], daytrip_hours: float = 2.5) -> None:
    if r.lat is None or r.lon is None or not stops:
        r.colour, r.fits = "", ""
        return
    radius = daytrip_km(daytrip_hours)
    d = [(km(s.place.lat, s.place.lon, r.lat, r.lon), s) for s in stops]
    near_km, near = min(d, key=lambda x: x[0])
    hours = near_km * ROAD / SPEED
    r.km, r.hours, r.anchor = near_km, hours, near
    if near_km <= radius:
        r.colour = "Green"
        r.fits = f"Day trip from {near.place.name} (~{hours:.1f} hrs each way)"
        return
    # between two consecutive stops (by order of the trip)?
    best = None
    for a, b in zip(stops, stops[1:]):
        # only overland stretches: two stops in the same country, not a long flight between countries
        if a.place == b.place or a.place.country != b.place.country:
            continue
        ab = km(a.place.lat, a.place.lon, b.place.lat, b.place.lon)
        ax = km(a.place.lat, a.place.lon, r.lat, r.lon)
        xb = km(r.lat, r.lon, b.place.lat, b.place.lon)
        detour = ax + xb - ab
        if detour <= min(250, max(120, 0.3 * ab)) and (best is None or detour < best[0]):
            best = (detour, a, b, ax)
    if best:
        _, a, b, ax = best
        r.colour, r.between = "Yellow", (a, b)
        r.fits = f"On the way from {a.place.name} to {b.place.name} (~{ax * ROAD / SPEED:.1f} hrs from {a.place.name}) — worth a night"
        return
    if near_km <= radius * 2.2:
        r.colour = "Yellow"
        r.fits = f"Overnight trip from {near.place.name} (~{hours:.1f} hrs each way)"
        return
    r.colour = "Red"
    r.fits = f"Doesn't fit the route — ~{near_km:,.0f} km from {near.place.name}"


# ---------- 5. Ideas tab + recommendations ----------

def ideas_rows(rows: list[ReelRow], stops: list[Stop]) -> list[list]:
    """Country | Stop | Idea | Rating | Sent by | How it fits | Distance | Reel"""
    placed = [r for r in rows if r.colour]
    by_rating = lambda r: -(r.rating or 0)
    line = lambda r: ["", "", r.place, r.rating or "", r.sender, r.fits,
                      f"~{r.km:,.0f} km" if r.km is not None else "", r.link]
    out: list[list] = []
    seen_stops = []
    for i, s in enumerate(stops):
        if s.place in seen_stops:
            continue
        seen_stops.append(s.place)
        here = sorted([r for r in placed if r.anchor and r.anchor.place == s.place and r.colour == "Green"
                       or (r.colour == "Yellow" and not r.between and r.anchor and r.anchor.place == s.place)], key=by_rating)
        out.append([s.place.country, s.place.name, "", "", "", "", "", ""])
        out += [line(r) for r in here] or [["", "", "", "", "", "No reels near here yet", "", ""]]
        nxt = next((t for t in stops[i + 1:] if t.place != s.place), None)
        if nxt:
            between = sorted([r for r in placed if r.between and r.between[0].place == s.place
                              and r.between[1].place == nxt.place], key=by_rating)
            if between:
                out.append(["", f"{s.place.name} → {nxt.place.name}", "", "", "", "", "", ""])
                out += [line(r) for r in between]
    red = sorted([r for r in placed if r.colour == "Red"], key=by_rating)
    if red:
        out.append(["", "Doesn't fit yet", "", "", "", "", "", ""])
        out += [line(r) for r in red]
    pending = [r for r in rows if not r.colour]
    if pending:
        out.append(["", "Not placed yet", "", "", "", "", "", ""])
        out += [["", "", r.place or (r.caption[:60] + "…" if len(r.caption) > 60 else r.caption) or r.link,
                 r.rating or "", r.sender, r.status or "Waiting for the next check", "", r.link] for r in pending]
    return out


def idea_recs(rows: list[ReelRow], stops: list[Stop], places=None) -> list[Rec]:
    """Recommendations for reels that need a change to the plan."""
    nights = {}
    mins = {}
    for pr in (places or []):
        if pr.place:
            nights[pr.place.name] = pr.nights
            mins[pr.place.name] = pr.min_n
    who = lambda r: f"Rated {r.rating}/10 by {r.sender}" if r.rating else f"Sent by {r.sender or 'one of you'}"
    recs = []
    for r in sorted([r for r in rows if r.colour in ("Yellow", "Red")], key=lambda r: -(r.rating or 0)):
        if r.between:
            a, b = r.between
            slack = lambda s: (nights.get(s.place.name) or 0) - (mins.get(s.place.name) or 1)
            donor = max((a, b), key=slack)
            take = (f" Take the night from {donor.place.name} ({nights.get(donor.place.name)} nights, your min is "
                    f"{mins.get(donor.place.name)})." if slack(donor) > 0 else
                    f" {a.place.name} and {b.place.name} are both at their minimum, so this means one more trip day.")
            recs.append(Rec("Idea", f"Add a night in {r.place} between {a.place.name} and {b.place.name}",
                            f"{who(r)}. {r.fits.split(' — ')[0]}.{take} Then split the {a.place.name} → {b.place.name} "
                            f"leg into {a.place.name} → {r.place} → {b.place.name}.",
                            [a.place.name, r.place, b.place.name], [f"{a.place.name} → {b.place.name}"]))
        elif r.colour == "Yellow" and r.anchor:
            recs.append(Rec("Idea", f"{r.place}: an overnight trip from {r.anchor.place.name}",
                            f"{who(r)}. About {r.hours:.1f} hrs each way, too far for a day trip. Spend one of your "
                            f"{nights.get(r.anchor.place.name) or ''} nights in {r.anchor.place.name} there instead.".replace("  ", " "),
                            [r.anchor.place.name, r.place]))
        elif r.colour == "Red" and r.anchor:
            recs.append(Rec("Idea", f"{r.place} doesn't fit the current route",
                            f"{who(r)}. About {r.km:,.0f} km from the nearest stop ({r.anchor.place.name}). It would need "
                            f"its own legs — worth it if it beats one of your Maybe stops.", [r.place]))
    return recs


def write_back(rows: list[ReelRow], cols: dict[str, int], tab: str = "Reels") -> list[dict]:
    from .writeback import col_letter
    data = []
    for r in rows:
        if not (r.changed or r.colour):
            continue
        vals = {"place": r.place, "country": r.country, "lat": r.lat if r.lat is not None else "",
                "lon": r.lon if r.lon is not None else "", "fits": r.fits, "colour": r.colour,
                "photo": r.photo, "photo_data": r.photo_data,
                "status": r.status if r.status and not r.colour else ("Placed" if r.colour else r.status)}
        for k, v in vals.items():
            if cols.get(k) is not None and (v != "" or k in ("fits", "colour", "status")):
                data.append({"range": f"'{tab}'!{col_letter(cols[k])}{r.row + 1}", "values": [[v]]})
    return data


def ideas_update(rows: list[list], tab: str = "Ideas", max_rows: int = 190) -> list[dict]:
    values = rows[:max_rows] + [[""] * 8 for _ in range(max_rows - min(len(rows), max_rows))]
    return [{"range": f"'{tab}'!A4:H{3 + max_rows}", "values": values}]


def process(rows: list[ReelRow], stops: list[Stop], daytrip_hours: float = 2.5, online: bool = True) -> dict:
    stats = {"read": 0, "located": 0, "photos": 0}
    if online:
        stats["read"] = extract_places(rows)
        stats["located"] = geocode(rows)
        stats["photos"] = fetch_photos(rows)
    for r in rows:
        classify(r, stops, daytrip_hours)
    return stats
