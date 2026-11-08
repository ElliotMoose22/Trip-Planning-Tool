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
