"""Reels: where each one is, and how it fits the route.

Flow for each row of the Reels tab that isn't placed yet:
  0. Watch  - download the reel and take 4 frames (or its cover image if Instagram won't give the video);
              the first frame becomes the map photo.
  1. Place  - read from the caption and frames by Claude, plus a one-line "About" for the map card (Claude Code on your subscription,
              CLAUDE_CODE_OAUTH_TOKEN), unless you've typed the Place yourself.
  2. Where  - coordinates from OpenStreetMap (Nominatim), unless Lat/Lon are filled.
  3. Photo  - if the reel gave no image: the place's Wikipedia image (shown in the sheet with =IMAGE and kept
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
    about: str = ""
    media: list = field(default_factory=list)   # frame / cover image paths (not saved)
    # filled by classify()
    colour: str = ""
    fits: str = ""
    anchor: Stop | None = None
    between: tuple[Stop, Stop] | None = None
    km: float | None = None
    hours: float | None = None
    changed: bool = False
    new: bool = False
    spots: list = field(default_factory=list)   # the reel's other places (ReelRow objects with row = -1)
    dup: bool = False                            # a second row for a reel that's already in the sheet: cleared


def _spot(parent: "ReelRow", place: str, country: str = "", **kw) -> "ReelRow":
    s = ReelRow(-1, parent.received, parent.sender, parent.link, "", parent.rating, place, country or parent.country,
                kw.get("lat"), kw.get("lon"), "")
    s.about, s.photo_data, s.colour, s.fits = parent.about, parent.photo_data, kw.get("colour", ""), kw.get("fits", "")
    return s


def all_spots(rows: list["ReelRow"]):
    """Every place on the map: each reel's main place, then its other spots."""
    for r in rows:
        if r.dup:
            continue
        yield r
        for s in r.spots:
            s.sender, s.rating, s.link, s.about, s.photo_data = r.sender, r.rating, r.link, r.about, r.photo_data
            yield s


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
         "status": col("status"), "photo_data": col("photo data"), "about": col("about"),
         "other": col("other spots"), "spots_data": col("spots data")}
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
                           _num(get("lat")), _num(get("lon")), get("status"), get("photo"), get("photo_data"),
                           get("about")))
        try:
            for d in json.loads(get("spots_data") or "[]"):
                out[-1].spots.append(_spot(out[-1], d.get("place", ""), d.get("country", ""), lat=d.get("lat"),
                                           lon=d.get("lon"), colour=d.get("colour", ""), fits=d.get("fits", "")))
        except (ValueError, AttributeError):
            pass
    merge_duplicates(out)
    return out, c


def merge_duplicates(rows: list[ReelRow]) -> int:
    """One row per reel: a later row with the same link becomes one of the first row's other spots
    (if it names a different place) and is cleared from the sheet."""
    first: dict[str, ReelRow] = {}
    n = 0
    for r in rows:
        key = re.sub(r"[?#].*$", "", r.link).rstrip("/").lower()
        if not key:
            continue
        if key not in first:
            first[key] = r
            continue
        keep = first[key]
        known = {keep.place.lower()} | {s.place.lower() for s in keep.spots}
        if r.place and r.place.lower() not in known:
            keep.spots.append(_spot(keep, r.place, r.country, lat=r.lat, lon=r.lon, colour=r.colour, fits=r.fits))
        if r.rating and not keep.rating:
            keep.rating = r.rating
        r.dup = keep.changed = True
        n += 1
    return n


# ---------- 1. read the place from the caption ----------

PROMPT = """You help plan a trip (Japan, Thailand, Indonesia, Vietnam) from Instagram reels a couple has saved.
For each reel below you get its caption and, when available, a few frames from the video (image files in the
current folder: open them with the Read tool and look at landmarks, signs and on-screen text).
For each reel:
- "places": every specific spot the reel shows or names: attractions, viewpoints, beaches, islands, parks, towns,
  and also restaurants, cafés, bars, markets and shops. Most important first, at most 6, each with its country.
  Name each one as a map would know it; for a venue or a small spot, add its town or district in brackets so it
  can be found exactly, e.g. "Afuri (Ebisu, Tokyo)" or "Fushimi Inari Taisha (Kyoto)". Skip vague regions when
  a specific spot is named. Use [] if you can't tell.
- "about": one short sentence (max 20 words) on what the reel shows and why it's worth going, for a map card.
Answer with JSON only, no prose:
[{"i": <number>, "places": [{"place": "<name as a map would know it>", "country": "<country>"}], "about": "<sentence>"}]

Reels:
"""


def _claude(prompt: str, cwd: str | None = None) -> str:
    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": os.environ["CLAUDE_CODE_OAUTH_TOKEN"].strip()}
    cmd = ["claude", "-p", prompt, "--output-format", "json"] + (["--allowedTools", "Read"] if cwd else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env, cwd=cwd)
    try:
        res = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"Claude Code gave no answer (exit {p.returncode}): {(p.stderr or p.stdout).strip()[:300]}")
    if res.get("is_error"):
        raise RuntimeError(f"Claude Code error: {str(res.get('result'))[:300]}")
    return res.get("result", "")


def extract_places(rows: list[ReelRow], batch: int = 5) -> int:
    """Fill .place/.country/.about with Claude Code from each new reel's caption and video frames.
    A Place you typed yourself is kept; Claude then only writes the 'About' line."""
    todo = [r for r in rows if r.lat is None and (not r.place or not r.about) and (r.caption or r.media)]
    if not todo or not shutil.which("claude") or not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return 0
    n = 0
    for k in range(0, len(todo), batch):
        part = todo[k:k + batch]
        lines, cwd = [], None
        for i, r in enumerate(part):
            imgs = [os.path.basename(m) for m in r.media]
            if imgs:
                cwd = os.path.dirname(r.media[0])
            lines.append(f"{i}. Caption: {r.caption[:600] or '(none)'}" + (f"\n   Frames: {', '.join(imgs)}" if imgs else ""))
        try:
            text = _claude(PROMPT + "\n".join(lines), cwd)
            m = re.search(r"\[.*\]", text, re.S)
            if not m:
                raise RuntimeError(f"no JSON in Claude's reply: {text.strip()[:300]}")
            answer = json.loads(m.group())
        except Exception as e:  # never sink the run over this
            print(f"  ! reading reels failed: {e}")
            continue
        for a in answer:
            i = a.get("i")
            if not (isinstance(i, int) and 0 <= i < len(part)):
                continue
            r = part[i]
            if a.get("about") and not r.about:
                r.about, r.changed = str(a["about"]).strip()[:200], True
            found = [p for p in (a.get("places") or []) if isinstance(p, dict) and p.get("place")]
            if found and not r.place:
                r.place = str(found[0]["place"]).strip()
                r.country = found[0].get("country") or ""
                known = {r.place.lower()}
                for p in found[1:6]:
                    name = str(p["place"]).strip()
                    if name.lower() not in known:
                        r.spots.append(_spot(r, name, p.get("country") or r.country))
                        known.add(name.lower())
                r.changed = True
                n += 1
    return n


# ---------- 0. watch the reel: a few frames + its cover ----------

MEDIA_DIR = os.environ.get("REELS_MEDIA_DIR", "/tmp/reels-media")


def _og_image(html: str) -> str | None:
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html)
    return m.group(1).replace("&amp;", "&") if m else None


def _frames(video: str, out_prefix: str, n: int = 4) -> list[str]:
    """n evenly spaced frames, 480 px wide."""
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                                   capture_output=True, text=True, timeout=60).stdout.strip() or 0)
    except Exception:
        dur = 0
    paths = []
    for j in range(n):
        t = dur * (j + 0.5) / n if dur else j * 3
        path = f"{out_prefix}_{j + 1}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                        "-vf", "scale=480:-2", path], capture_output=True, timeout=60)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            paths.append(path)
    return paths


def thumb_data_url(path: str, width: int = 360, limit: int = 45000) -> str:
    """A small JPEG as a data: URL that fits in one sheet cell (the dashboard can't load web images)."""
    from io import BytesIO
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((width, width * 2))
    for q in (72, 60, 48, 36):
        buf = BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        if len(b64) < limit:
            return "data:image/jpeg;base64," + b64
        im.thumbnail((int(im.width * 0.8), int(im.height * 0.8)))
    return ""


def fetch_media(rows: list[ReelRow], session=None) -> int:
    """For each new reel: download it and grab a few frames (yt-dlp + ffmpeg); if Instagram won't hand over
    the video, fall back to the reel's cover image. The first frame / cover becomes the map photo."""
    import requests
    s = session or requests.Session()
    os.makedirs(MEDIA_DIR, exist_ok=True)
    n = 0
    for idx, r in enumerate(rows):
        if r.lat is not None or not r.link.startswith("http") or "/reel/sample" in r.link or r.link.endswith("/test"):
            continue
        prefix = os.path.join(MEDIA_DIR, f"reel{r.row}")
        try:
            import yt_dlp
            opts = {"outtmpl": prefix + ".%(ext)s", "format": "worst[ext=mp4]/worst", "quiet": True,
                    "no_warnings": True, "max_filesize": 60_000_000, "socket_timeout": 30}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(r.link, download=True)
                video = ydl.prepare_filename(info)
            r.media = _frames(video, prefix)
            if not r.caption and info.get("description"):
                r.caption, r.changed = info["description"][:1500], True
        except Exception as e:
            print(f"  · video for row {r.row + 1} not available ({str(e)[:80]}); trying its cover image")
        if not r.media:
            try:
                html = s.get(r.link, headers={"User-Agent": "facebookexternalhit/1.1"}, timeout=30).text
                url = _og_image(html)
                if url:
                    path = prefix + "_cover.jpg"
                    with open(path, "wb") as f:
                        f.write(s.get(url, headers={"User-Agent": UA}, timeout=30).content)
                    r.media = [path]
            except Exception as e:
                print(f"  · cover for row {r.row + 1} not available: {e}")
        if r.media and not r.photo_data:
            try:
                r.photo_data = thumb_data_url(r.media[0])
                if r.photo_data:
                    r.photo, r.changed = "From the reel", True
            except Exception as e:
                print(f"  · couldn't shrink the photo for row {r.row + 1}: {e}")
        n += bool(r.media)
    return n


# ---------- 1b. one row per place ----------

SPLIT = re.compile(r"\s*(?:[,;\n]|\s\+\s)\s*")


REGION_TYPES = {"state", "province", "region", "county", "prefecture", "country", "state_district", "archipelago"}


def is_region(name: str, session=None) -> bool:
    """True for a prefecture / province / country name ("Kagawa", "Bali"), which qualifies a place
    rather than being a second place."""
    import requests
    s = session or requests.Session()
    try:
        res = s.get("https://nominatim.openstreetmap.org/search", params={"q": name, "format": "json", "limit": 1,
                    "accept-language": "en"}, headers={"User-Agent": UA}, timeout=30).json()
        time.sleep(1.1)
    except Exception:
        return False
    return bool(res) and (res[0].get("addresstype") in REGION_TYPES or
                          (res[0].get("class") == "boundary" and res[0].get("type") == "administrative"
                           and res[0].get("addresstype") not in ("city", "town", "village", "municipality")))


def split_places(rows: list[ReelRow], online: bool = False) -> int:
    """A reel naming several places ("Kamakura, Enoshima") stays one row: the first place goes in Place,
    the rest become its other spots (each still gets its own pin on the map).
    Write a region in brackets to keep it with its place: "Ubud (Bali)"."""
    n = 0
    for r in rows:
        if r.dup or r.lat is not None or not r.place:
            continue
        names = [x for x in SPLIT.split(r.place) if x]
        if len(names) < 2:
            continue
        if online:   # "Teshima, Kagawa": the prefecture belongs to the place before it
            merged = []
            for x in names:
                if merged and is_region(x):
                    merged[-1] = f"{merged[-1]} ({x})" if "(" not in merged[-1] else merged[-1]
                else:
                    merged.append(x)
            names = merged
        r.place, r.changed = names[0], True
        known = {r.place.lower()} | {sp.place.lower() for sp in r.spots}
        for x in names[1:]:
            if x.lower() not in known:
                r.spots.append(_spot(r, x))
                known.add(x.lower())
                n += 1
    return n


def _clean_date(v: str) -> str:
    """'November 8|2026' (a sheet date read with its hidden year) -> '2026-11-08'."""
    if "|" in v:
        md, _, y = v.partition("|")
        try:
            return dt.datetime.strptime(f"{md.strip()} {y.strip()}", "%B %d %Y").date().isoformat()
        except ValueError:
            return md.strip()
    return v


# ---------- 2. coordinates ----------

def geocode_queries(place: str, country: str = "") -> list[str]:
    """Most specific first: 'Oikawa Falls (Kinko, Kagoshima)' -> full, 'Oikawa Falls, Kagoshima',
    'Oikawa Falls', then the area alone as a last resort is NOT used (it would pin the wrong spot)."""
    place = re.sub(r"\s{2,}", ", ", place.strip())
    base = re.sub(r"\s*\(.*?\)", "", place).strip()
    inside = [x.strip() for x in ",".join(re.findall(r"\((.*?)\)", place)).split(",") if x.strip()]
    latin = re.sub(r"[^\x00-\x7F]+", " ", base).strip()
    native = re.sub(r"[\x00-\x7F]+", " ", base).strip()
    tail = f", {country}" if country else ""
    qs = [", ".join([base] + inside) + tail]
    if inside:
        qs += [f"{base}, {inside[-1]}{tail}", f"{base}, {inside[0]}{tail}"]
    qs += [base + tail]
    if latin and latin != base:
        qs += [", ".join([latin] + inside[-1:]) + tail]
    if native and native != base:
        qs += [", ".join([native] + inside[-1:]) + tail]
    out = []
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip(" ,")
        if q and q not in out:
            out.append(q)
    return out


def geocode(rows: list[ReelRow], session=None) -> int:
    import requests
    s = session or requests.Session()
    n = 0
    for r in list(all_spots(rows)):
        if r.place and (r.lat is None or r.lon is None):
            res = None
            for q in geocode_queries(r.place, r.country):
                try:
                    res = s.get("https://nominatim.openstreetmap.org/search", params={"q": q, "format": "json", "limit": 1,
                                "accept-language": "en", "addressdetails": 1}, headers={"User-Agent": UA}, timeout=30).json()
                except Exception as e:
                    print(f"  ! geocoding {q}: {e}")
                    res = None
                time.sleep(1.1)   # Nominatim asks for at most one request a second
                if res:
                    break
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
            r.photo = "From Wikipedia"
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


def classify(r: ReelRow, stops: list[Stop], daytrip_hours: float = 2.5, flown: set | None = None) -> None:
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
        if flown and (a.place.name, b.place.name) in flown:     # you fly this hop: nothing is "on the way"
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
    rows = list(all_spots(rows))
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
    rows = list(all_spots(rows))
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
    put = lambda k, r, v: data.append({"range": f"'{tab}'!{col_letter(cols[k])}{r.row + 1}", "values": [[v]]}) \
        if cols.get(k) is not None else None
    for r in rows:
        if r.dup:                      # second copy of a reel already in the sheet: empty the row
            for k in cols:
                put(k, r, "")
            continue
        if not (r.changed or r.colour):
            continue
        vals = {"place": r.place, "country": r.country, "lat": r.lat if r.lat is not None else "",
                "lon": r.lon if r.lon is not None else "", "fits": r.fits, "colour": r.colour,
                "photo": r.photo, "photo_data": r.photo_data, "about": r.about,
                "status": r.status if r.status and not r.colour else ("Placed" if r.colour else r.status),
                "rating": r.rating or "",
                "other": "\n".join(f"{sp.place} — {sp.colour or 'not placed'}" for sp in r.spots),
                "spots_data": json.dumps([{"place": sp.place, "country": sp.country, "lat": sp.lat, "lon": sp.lon,
                                           "colour": sp.colour, "fits": sp.fits} for sp in r.spots],
                                         ensure_ascii=False) if r.spots else ""}
        for k, v in vals.items():
            if v != "" or k in ("fits", "colour", "status", "other", "spots_data"):
                put(k, r, v)
    return data


def ideas_update(rows: list[list], tab: str = "Ideas", max_rows: int = 190) -> list[dict]:
    values = rows[:max_rows] + [[""] * 8 for _ in range(max_rows - min(len(rows), max_rows))]
    return [{"range": f"'{tab}'!A4:H{3 + max_rows}", "values": values}]


def process(rows: list[ReelRow], stops: list[Stop], daytrip_hours: float = 2.5, online: bool = True,
            flown: set | None = None) -> dict:
    stats = {"read": 0, "located": 0, "photos": 0, "watched": 0}
    if online:
        stats["watched"] = fetch_media(rows)
        stats["read"] = extract_places(rows)
    stats["split"] = split_places(rows, online)
    if online:
        stats["located"] = geocode(rows)
        stats["photos"] = fetch_photos(rows)
    for r in all_spots(rows):
        classify(r, stops, daytrip_hours, flown)
    return stats
