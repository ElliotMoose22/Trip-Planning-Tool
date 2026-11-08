"""Write this week's prices back into your flights table in the Google Sheet.

Only runs with real prices (never demo data) and only when the
GOOGLE_SERVICE_ACCOUNT_JSON secret is set. For each row that isn't marked
Booked it updates Cost, Length, Flight Number and Notes, and stamps the
time of the check next to the table's title. Date / Depart / Arrive are
never changed: those are your decisions.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import time

from .recommend import LegResult
from .signals import Signal
from .sheet import FlightTable

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_id(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not m:
        raise ValueError("Not a Google Sheets link")
    return m.group(1)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def signed_jwt(sa: dict, now: int | None = None) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    now = now or int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": sa.get("private_key_id", "")}
    claims = {"iss": sa["client_email"], "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}
    msg = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}".encode()
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    return msg.decode() + "." + _b64(key.sign(msg, padding.PKCS1v15(), hashes.SHA256()))


def access_token(sa: dict) -> str:
    import requests
    r = requests.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                       "assertion": signed_jwt(sa)}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _money(v: float) -> str:
    return f"${v:,.0f}"


def row_note(lr: LegResult, sig: Signal) -> str:
    f = lr.leg.flight
    parts = [sig.verdict]
    if lr.plan_price is None:
        parts.append("no price found this week")
    elif f.cost:
        d = round(lr.plan_price - f.cost)
        parts.append("same as last week" if d == 0 else f"{'▼' if d < 0 else '▲'} {_money(abs(d))} vs last week")
    else:
        parts.append("first price check")
    for s in lr.suggestions[:2]:
        if s.kind == "calendar":
            parts.append(f"or fly {s.route} {_money(s.price)} and skip the bus")
        elif s.saves and s.saves > 0:
            what = s.route or s.text.replace("Fly ", "").replace(" instead", "")
            parts.append(f"cheaper: {what} {_money(s.price)} (save {_money(s.saves)})")
    return " · ".join(parts)


def build_updates(table: FlightTable, tab: str, legs: list[LegResult], sigs: dict, today: dt.date,
                  recs: list | None = None) -> list[dict]:
    c = table.cols
    cell = lambda r, k: f"'{tab}'!{col_letter(c[k])}{r + 1}"
    data = []
    for lr in legs:
        f = lr.leg.flight
        if f.source != "my table" or f.row is None or f.booked or f.date < today:
            continue
        if c.get("cost") is None:
            continue
        q = getattr(lr, "plan_quote", None)
        if q is not None:
            data.append({"range": cell(f.row, "cost"), "values": [[round(q.price)]]})
            if q.duration and "len" in c:
                data.append({"range": cell(f.row, "len"), "values": [[q.duration]]})
            if q.flight_no and "no" in c:
                data.append({"range": cell(f.row, "no"), "values": [[q.flight_no]]})
        route = f"{lr.leg.origin.name} → {lr.leg.destination.name}"
        extra = [r.title for r in (recs or []) if route in r.legs and r.kind != "Price"]
        data.append({"range": cell(f.row, "notes"), "values": [[" · ".join([row_note(lr, sigs[lr.leg.id][0]), *extra])]]})
    stamp_col = c.get("stamp", c["notes"])
    if table.title_row is not None:
        data.append({"range": f"'{tab}'!{col_letter(stamp_col)}{table.title_row + 1}",
                     "values": [[f"Last checked {today:%a %b %-d, %Y} by the trip tool"]]})
    return data


def build_place_updates(places, tab: str = "Places", recs: list | None = None) -> list[dict]:
    """Each place's checks and recommendations, written into its "Trip tool says" column (never your Notes)."""
    if not places:
        return []
    rows, cols = places
    if cols.get("tool") is None:
        return []
    return [{"range": f"'{tab}'!{col_letter(cols['tool'])}{pr.row + 1}", "values": [[place_tool_note(pr, recs)]]}
            for pr in rows]


def place_tool_note(pr, recs: list | None) -> str:
    """One readable line per place: its own checks, then recommendations that touch it (no repeats)."""
    lines = list(pr.notes)
    has = lambda word: any(word in x for x in lines)
    for r in recs or []:
        if pr.city not in r.places or r.kind not in ("Dates", "Fix", "Option"):
            continue
        if r.kind == "Dates" and r.title.startswith(pr.city):
            if r.legs:
                lines.append("Suggested fix in Recommendations")
            continue
        if ("isn't a place" in r.title and has("can't place")) or ("has no legs" in r.title and has("No leg")):
            continue
        lines.append(f"Affected by: {r.title}" if r.kind == "Dates" else r.title)
    return " · ".join(lines) or "✔ Looks good"


def build_recs_updates(recs: list, today: dt.date, tab: str = "Recommendations", rows: int = 40) -> list[dict]:
    """Rewrite the Recommendations tab (rows 4+)."""
    values = [r.row(today) for r in recs][:rows]
    values += [[""] * 6 for _ in range(rows - len(values))]
    return [{"range": f"'{tab}'!A4:F{3 + rows}", "values": values}]


def push(sheet_url: str, data: list[dict], creds_json: str | None = None) -> int:
    import requests
    sa = json.loads(creds_json or os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    r = requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id(sheet_url)}/values:batchUpdate",
        headers={"Authorization": f"Bearer {access_token(sa)}"},
        json={"valueInputOption": "USER_ENTERED", "data": data}, timeout=60)
    if r.status_code == 403:
        raise PermissionError(f"Google refused the edit. Share the sheet with {sa['client_email']} as an Editor.")
    r.raise_for_status()
    return r.json().get("totalUpdatedCells", 0)
