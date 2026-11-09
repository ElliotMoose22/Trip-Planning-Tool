import datetime as dt

from triptool.reels import classify, idea_recs, ideas_rows, parse_reels
from triptool.tables import build_from_tables, parse_legs, parse_places
from tests.test_tables import LEGS

PLACES = [["Places"], ["hint"],
          ["Country", "City", "Priority", "Min nights", "Max nights", "Fixed dates / must-do", "Arrive", "Leave", "Nights", "Notes (yours)", "Trip tool says (weekly)"],
          ["Japan", "Tokyo", "Must", "2", "5", "", "Mon Jun 7", "Fri Jun 11"],
          ["Thailand", "Bangkok", "Want", "2", "4", "", "Fri Jun 11", "Tue Jun 15"],
          ["Thailand", "Phuket", "Must", "3", "5", "", "Tue Jun 15", "Sun Jun 20"],
          ["Vietnam", "Hanoi", "Want", "3", "5", "", "Sun Jun 20", "Thu Jun 24"]]
REELS = [["Reels"], ["hint"],
         ["Received", "From", "Reel link", "Caption", "Rating (/10)", "Place", "Country", "Lat", "Lon", "Fits the route", "Colour", "Photo", "Status", "Photo data"],
         ["Nov 8", "Cat", "https://instagram.com/reel/a", "Kamakura day trip!", "9", "Kamakura", "Japan", "35.32", "139.55"],
         ["Nov 8", "Elliot", "https://instagram.com/reel/b", "Hua Hin night market", "8/10", "Hua Hin", "Thailand", "12.57", "99.96"],
         ["Nov 8", "Cat", "https://instagram.com/reel/c", "Ha Long Bay cruise", "10", "Ha Long Bay", "Vietnam", "20.91", "107.18"],
         ["Nov 8", "Elliot", "https://instagram.com/reel/d", "Chiang Mai temples", "6", "Chiang Mai", "Thailand", "18.79", "98.98"],
         ["Nov 8", "Cat", "https://instagram.com/reel/e", "no idea where this is", "7"]]


def test_reels_are_coloured_and_sorted():
    places, _ = parse_places(PLACES, 2027)
    legs, _ = parse_legs(LEGS, 2027)
    plan = build_from_tables(places, legs, dt.date(2027, 6, 6), dt.date(2027, 6, 24))
    rows, cols = parse_reels(REELS)
    assert cols["photo"] == 11 and cols["photo_data"] == 13
    for r in rows:
        classify(r, plan.stops)
    col = {r.place or r.caption: r.colour for r in rows}
    assert col == {"Kamakura": "Green", "Hua Hin": "Yellow", "Ha Long Bay": "Yellow", "Chiang Mai": "Red",
                   "no idea where this is": ""}
    hua = next(r for r in rows if r.place == "Hua Hin")
    assert hua.between[0].place.name == "Bangkok" and hua.rating == 8
    ideas = ideas_rows(rows, plan.stops)
    names = [x[1] for x in ideas if x[1]]
    assert names[:4] == ["Tokyo", "Bangkok", "Bangkok → Phuket", "Phuket"]
    assert "Doesn't fit yet" in names and "Not placed yet" in names
    recs = idea_recs(rows, plan.stops, places)
    titles = [r.title for r in recs]
    assert "Add a night in Hua Hin between Bangkok and Phuket" in titles
    assert "Ha Long Bay: an overnight trip from Hanoi" in titles
    assert any("Chiang Mai doesn't fit" in t for t in titles)


def test_multi_place_reels_stay_one_row():
    from triptool.reels import all_spots, merge_duplicates, split_places, write_back
    rows, cols = parse_reels(REELS[:3] + [["Nov 8", "Elliot", "https://instagram.com/reel/m", "Kyushu loop", "9",
                                           "Kumamoto Castle; Mount Aso, Ubud (Bali)"]])
    assert split_places(rows) == 2
    m = [r for r in rows if r.link.endswith("/m")]
    assert len(m) == 1 and m[0].place == "Kumamoto Castle"
    assert [s.place for s in m[0].spots] == ["Mount Aso", "Ubud (Bali)"]
    spots = [s for s in all_spots(rows) if s.link.endswith("/m")]
    assert len(spots) == 3 and all(s.rating == 9 and s.sender == "Elliot" for s in spots)


def test_duplicate_rows_fold_into_one_reel():
    from triptool.reels import merge_duplicates, write_back
    grid = REELS[:2] + [REELS[2] + ["Other spots", "Spots data"]] + [["Nov 8", "Elliot", "https://instagram.com/reel/k/", "Kamakura spots", "8", "Kotoku-in", "Japan", "35.3", "139.5"],
                        ["Nov 8", "Elliot", "https://instagram.com/reel/k", "↳ same reel", "8", "Goryo Shrine", "Japan", "35.31", "139.53"],
                        ["Nov 8", "Elliot", "https://instagram.com/reel/k?igsh=x", "", "8", "Kotoku-in", "Japan", "35.3", "139.5"]]
    rows, cols = parse_reels(grid)
    keep = [r for r in rows if not r.dup]
    assert len(keep) == 1 and [s.place for s in keep[0].spots] == ["Goryo Shrine"]
    data = write_back(rows, cols)
    cleared = {d["range"] for d in data if d["values"] == [[""]] and d["range"].endswith("6")}
    assert cleared                                  # the duplicate rows are emptied
    other = [d for d in data if d["range"].startswith("'Reels'!") and "Goryo Shrine" in str(d["values"])]
    assert other


def test_cover_image_and_frames(tmp_path):
    import shutil, subprocess
    from triptool.reels import _frames, _og_image, thumb_data_url
    html = '<head><meta property="og:image" content="https://cdn.example/x.jpg?a=1&amp;b=2" /></head>'
    assert _og_image(html) == "https://cdn.example/x.jpg?a=1&b=2"
    assert _og_image('<meta content="https://c/y.jpg" property="og:image">') == "https://c/y.jpg"
    if not shutil.which("ffmpeg"):
        return
    video = str(tmp_path / "v.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=8:size=720x1280:rate=10", video], check=True)
    frames = _frames(video, str(tmp_path / "f"))
    assert len(frames) == 4
    url = thumb_data_url(frames[0])
    assert url.startswith("data:image/jpeg;base64,") and len(url) < 45100


def test_flown_hops_have_nothing_on_the_way():
    from triptool.reels import ReelRow, _clean_date
    places, _ = parse_places(PLACES, 2027)
    legs, _ = parse_legs(LEGS, 2027)
    plan = build_from_tables(places, legs, dt.date(2027, 6, 6), dt.date(2027, 6, 24))
    hua = ReelRow(0, "", "Elliot", "x", "", 8, "Hua Hin", "Thailand", 12.57, 99.96, "")
    classify(hua, plan.stops, flown={("Bangkok", "Phuket")})
    assert hua.colour != "Yellow" or not hua.between        # no longer "on the way" if that hop is a flight
    classify(hua, plan.stops)
    assert hua.between
    assert _clean_date("November 8|2026") == "2026-11-08" and _clean_date("Nov 8") == "Nov 8"


def test_unfound_spot_is_pinned_in_its_town():
    from triptool.reels import ReelRow, geocode
    import triptool.reels as R
    R.time.sleep = lambda s: None

    class Resp:
        def __init__(self, data): self.data = data
        def json(self): return self.data

    class Session:
        def get(self, url, params=None, **kw):
            q = (params or {}).get("q", "")
            if "photon" in url:
                return Resp({"features": []})
            if q == "Asakusa, Tokyo, Japan":
                return Resp([{"lat": "35.7148", "lon": "139.7967", "address": {"country": "Japan"}}])
            return Resp([])

    r = ReelRow(3, "", "Elliot", "x", "", 10, "Benitsuru (Asakusa, Tokyo)", "Japan", None, None, "")
    assert geocode([r], Session()) == 1
    assert round(r.lat, 2) == 35.71 and r.status.startswith("Approximate") and "Asakusa" in r.status
