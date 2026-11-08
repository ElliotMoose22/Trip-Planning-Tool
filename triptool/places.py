"""Place lookup: names as you'd write them in the sheet -> airports + coordinates.

Add a row here when the sheet mentions somewhere new. `ALTERNATES` lists
realistic swaps the tool may suggest (nearby airports / cities).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    airports: tuple[str, ...]
    lat: float
    lon: float

    @property
    def codes(self) -> str:
        return ",".join(self.airports)


_P = [
    # name, country, airports, lat, lon
    ("Toronto", "Canada", ("YYZ",), 43.65, -79.38),
    ("Vancouver", "Canada", ("YVR",), 49.28, -123.12),
    ("Manila", "Philippines", ("MNL",), 14.60, 120.98),
    ("Tokyo", "Japan", ("HND", "NRT"), 35.68, 139.69),
    ("Osaka", "Japan", ("KIX", "ITM"), 34.69, 135.50),
    ("Fukuoka", "Japan", ("FUK",), 33.59, 130.40),
    ("Kagoshima", "Japan", ("KOJ",), 31.60, 130.56),
    ("Kumamoto", "Japan", ("KMJ",), 32.80, 130.71),
    ("Okinawa", "Japan", ("OKA",), 26.21, 127.68),
    ("Bangkok", "Thailand", ("BKK", "DMK"), 13.76, 100.50),
    ("Phuket", "Thailand", ("HKT",), 7.88, 98.39),
    ("Krabi", "Thailand", ("KBV",), 8.09, 98.91),
    ("Chiang Mai", "Thailand", ("CNX",), 18.79, 98.98),
    ("Koh Samui", "Thailand", ("USM",), 9.51, 100.01),
    ("Bali", "Indonesia", ("DPS",), -8.65, 115.22),
    ("Jakarta", "Indonesia", ("CGK",), -6.21, 106.85),
    ("Lombok", "Indonesia", ("LOP",), -8.58, 116.10),
    ("Yogyakarta", "Indonesia", ("YIA",), -7.80, 110.36),
    ("Labuan Bajo", "Indonesia", ("LBJ",), -8.49, 119.89),
    ("Singapore", "Singapore", ("SIN",), 1.35, 103.82),
    ("Kuala Lumpur", "Malaysia", ("KUL",), 3.14, 101.69),
    ("Hanoi", "Vietnam", ("HAN",), 21.03, 105.85),
    ("Ho Chi Minh City", "Vietnam", ("SGN",), 10.82, 106.63),
    ("Da Nang", "Vietnam", ("DAD",), 16.05, 108.20),
    ("Doha", "Qatar", ("DOH",), 25.29, 51.53),
    ("Athens", "Greece", ("ATH",), 37.98, 23.73),
    ("Crete", "Greece", ("HER", "CHQ"), 35.34, 25.13),
    ("Santorini", "Greece", ("JTR",), 36.39, 25.46),
    ("Split", "Croatia", ("SPU",), 43.51, 16.44),
    ("Dubrovnik", "Croatia", ("DBV",), 42.65, 18.09),
    ("Zagreb", "Croatia", ("ZAG",), 45.81, 15.98),
]
PLACES: dict[str, Place] = {p[0].lower(): Place(*p) for p in _P}

ALIASES = {
    "naha": "okinawa", "hcmc": "ho chi minh city", "saigon": "ho chi minh city",
    "ho chi minh": "ho chi minh city", "denpasar": "bali", "heraklion": "crete",
    "her": "crete", "chania": "crete", "komodo": "labuan bajo",
}

# Country written alone in the sheet ("THAILAND") -> the default city to use.
COUNTRY_DEFAULT = {
    "japan": "Tokyo", "thailand": "Bangkok", "indonesia": "Bali", "vietnam": "Hanoi",
    "greece": "Athens", "croatia": "Split", "canada": "Toronto",
}

ALTERNATES = {
    "fukuoka": ["Kagoshima"], "kagoshima": ["Fukuoka"],
    "phuket": ["Krabi", "Bangkok"], "bangkok": ["Phuket"],
    "jakarta": ["Bali"], "bali": ["Jakarta", "Lombok"],
    "hanoi": ["Ho Chi Minh City", "Da Nang"], "ho chi minh city": ["Hanoi"],
    "split": ["Dubrovnik", "Zagreb"], "dubrovnik": ["Split"],
}

_WORD = re.compile(r"[^a-z ]+")


def clean(text: str) -> str:
    text = re.sub(r"\(.*?\)", " ", text.lower())   # "Phuket (Thailand)" -> "phuket"
    text = text.replace("airport", " ")
    return " ".join(_WORD.sub(" ", text).split())


def lookup(name: str) -> Place | None:
    key = clean(name)
    key = ALIASES.get(key, key)
    if key in PLACES:
        return PLACES[key]
    for word in sorted(set(ALIASES) | set(PLACES), key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", key):
            return PLACES[ALIASES.get(word, word)]
    return None


def country_of(name: str) -> str | None:
    key = clean(name)
    for c in COUNTRY_DEFAULT:
        if re.search(rf"\b{c}\b", key):
            return c.title()
    return None


def mentioned(text: str) -> list[Place]:
    """All known places mentioned in free text, in the order they appear."""
    key = f" {clean(text)} "
    hits = []
    for word in set(ALIASES) | set(PLACES):
        for m in re.finditer(rf"\b{re.escape(word)}\b", key):
            hits.append((m.start(), PLACES[ALIASES.get(word, word)]))
    hits.sort(key=lambda h: h[0])
    out: list[Place] = []
    for _, p in hits:
        if not out or out[-1] != p:
            out.append(p)
    return out


def alternates(place: Place) -> list[Place]:
    return [PLACES[n.lower()] for n in ALTERNATES.get(place.name.lower(), [])]
