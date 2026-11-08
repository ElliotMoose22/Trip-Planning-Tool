"""Build the weekly report as HTML (to open/share) and Markdown (for GitHub)."""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .config import Trip
from .signals import Signal, cheapest_per_check, evaluate
from .store import Store

COLORS = {"BUY": "#1a7f4b", "WATCH": "#b26b00", "WAIT": "#5b6170", "BOOKED": "#3a5bd9"}


def _category(leg) -> str:
    return "long_haul" if "YYZ" in (leg.origin + leg.destination) else "regional"


def build_rows(trip: Trip, store: Store, source: str, today: dt.date) -> list[dict]:
    rows = []
    for leg in trip.flights:
        hist = store.history(leg.id, source)
        series = cheapest_per_check(hist)
        sig = evaluate(series, (leg.date - today).days, _category(leg), leg.booked)
        latest = store.latest(leg.id, source)
        rows.append({"kind": "Flight", "label": leg.label, "when": leg.date, "signal": sig, "series": series,
                     "dates": [(r["travel_date"], r["price"], r["detail"], r["link"]) for r in latest],
                     "best": latest[0] if latest else None})
    for stay in trip.stays:
        series = cheapest_per_check(store.history(stay.id, source))
        sig = evaluate(series, (stay.check_in - today).days, "stay", stay.booked, stay.max_price_per_night)
        latest = store.latest(stay.id, source)
        rows.append({"kind": "Stay", "label": f"{stay.label} · {stay.nights} nights", "when": stay.check_in,
                     "signal": sig, "series": series, "dates": [], "best": latest[0] if latest else None})
    return rows


def _spark(series: list[float], w=140, h=34) -> str:
    if len(series) < 2:
        return '<span class="muted">–</span>'
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(series) - 1):.1f},{h - 3 - (v - lo) / span * (h - 6):.1f}"
                   for i, v in enumerate(series))
    lx, ly = pts.split()[-1].split(",")
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline points="{pts}" fill="none" '
            f'stroke="currentColor" stroke-width="1.6"/><circle cx="{lx}" cy="{ly}" r="2.6" fill="currentColor"/></svg>')


def _money(v, cur) -> str:
    return "–" if v is None else f"${v:,.0f} {cur}"


def render_html(trip: Trip, rows: list[dict], today: dt.date, source: str) -> str:
    cur = trip.currency
    buys = [r for r in rows if r["signal"].verdict == "BUY"]
    cards = []
    for r in rows:
        s: Signal = r["signal"]
        best = r["best"]
        chg = "" if s.change_pct is None else (
            f'<span class="{"up" if s.change_pct > 0 else "down"}">{"▲" if s.change_pct > 0 else "▼"} {abs(s.change_pct)}%</span>')
        unit = "total for 2" if r["kind"] == "Flight" else "per night"
        detail = html.escape(best["detail"]) if best else ""
        link = f' · <a href="{html.escape(best["link"])}">open</a>' if best and best["link"] else ""
        flex = ""
        if len(r["dates"]) > 1:
            cells = "".join(
                f'<td class="{"best" if i == 0 else ""}">{dt.date.fromisoformat(d).strftime("%a %b %-d")}<br>'
                f'<b>${p:,.0f}</b></td>' for i, (d, p, _, _) in enumerate(sorted(r["dates"], key=lambda x: x[1])))
            flex = f'<table class="flex"><tr>{cells}</tr></table>'
        cards.append(f"""
<div class="card">
  <div class="top"><span class="pill" style="background:{COLORS[s.verdict]}">{s.verdict}</span>
    <span class="kind">{r['kind']}</span><span class="days">{s.days_out} days out</span></div>
  <h3>{html.escape(r['label'])}</h3>
  <div class="when">{r['when'].strftime('%a %b %-d, %Y')}</div>
  <div class="price"><b>{_money(s.current, cur)}</b> <span class="muted">{unit}</span> {chg}</div>
  <div class="spark">{_spark(r['series'])}<span class="muted">low {_money(s.low, '')} · high {_money(s.high, '')}</span></div>
  <p class="reason">{html.escape(s.reason)}</p>
  <div class="muted small">{detail}{link}</div>
  {flex}
</div>""")

    demo_banner = ('<div class="banner">Demo data — add a SERPAPI_KEY to track real prices.</div>'
                   if source == "demo" else "")
    summary = (f"<b>{len(buys)}</b> thing{'s' if len(buys) != 1 else ''} worth booking this week: "
               + ", ".join(html.escape(r['label']) for r in buys)) if buys else "Nothing to book this week — hold."
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(trip.name)} — price report {today}</title>
<style>
:root {{ --bg:#f6f4ef; --card:#fff; --ink:#1d1f24; --muted:#6b7080; --line:#e6e2d8; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14161a; --card:#1d2026; --ink:#eceae4; --muted:#9aa0ad; --line:#2c3038; }} }}
* {{ box-sizing:border-box }} body {{ margin:0; font:15px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink) }}
header {{ padding:32px 24px 8px; max-width:1100px; margin:auto }}
h1 {{ font-size:28px; margin:0 0 4px; letter-spacing:-.02em }} h3 {{ margin:6px 0 0; font-size:18px }}
.sub {{ color:var(--muted) }} .summary {{ margin:16px 0 0; font-size:17px }}
.banner {{ margin-top:14px; padding:8px 12px; border:1px dashed var(--muted); border-radius:8px; color:var(--muted); display:inline-block }}
.grid {{ max-width:1100px; margin:auto; padding:16px 24px 48px; display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:14px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px }}
.top {{ display:flex; gap:8px; align-items:center; font-size:12px }} .days {{ margin-left:auto; color:var(--muted) }}
.pill {{ color:#fff; font-weight:700; padding:2px 9px; border-radius:99px; letter-spacing:.04em }}
.kind {{ color:var(--muted); text-transform:uppercase; letter-spacing:.06em }}
.when {{ color:var(--muted); font-size:13px }} .price {{ margin-top:10px; font-size:20px }}
.spark {{ display:flex; align-items:center; gap:10px; margin:6px 0; color:var(--ink); font-size:12px }}
.reason {{ margin:8px 0 6px }} .muted {{ color:var(--muted) }} .small {{ font-size:12px }}
.up {{ color:#c0392b; font-size:13px }} .down {{ color:#1a7f4b; font-size:13px }}
a {{ color:inherit }}
.flex {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:12px; text-align:center }}
.flex td {{ border:1px solid var(--line); padding:5px 2px }} .flex td.best {{ background:rgba(26,127,75,.12) }}
footer {{ max-width:1100px; margin:auto; padding:0 24px 32px; color:var(--muted); font-size:12px }}
</style></head><body>
<header><h1>{html.escape(trip.name)} · weekly price report</h1>
<div class="sub">{today.strftime('%A %B %-d, %Y')} · {trip.travelers} travellers · {trip.start:%b %-d} – {trip.end:%b %-d, %Y}</div>
<div class="summary">{summary}</div>{demo_banner}</header>
<div class="grid">{''.join(cards)}</div>
<footer>BUY / WATCH / WAIT are rules of thumb based on price history and how far out you are — not guarantees.
Flight prices are the cheapest option found for 2 adults; flex-date tables show the latest check.</footer>
</body></html>"""


def render_markdown(trip: Trip, rows: list[dict], today: dt.date, source: str) -> str:
    out = [f"# {trip.name} — price report {today}", ""]
    if source == "demo":
        out += ["> Demo data — add a `SERPAPI_KEY` secret to track real prices.", ""]
    out += ["| | Item | Date | Price | Δ wk | Why |", "|---|---|---|---|---|---|"]
    for r in rows:
        s = r["signal"]
        chg = "" if s.change_pct is None else f"{s.change_pct:+}%"
        out.append(f"| **{s.verdict}** | {r['label']} | {r['when']:%b %-d} | {_money(s.current, trip.currency)} | {chg} | {s.reason} |")
    return "\n".join(out) + "\n"


def write_report(trip: Trip, store: Store, source: str, today: dt.date, out_dir: str | Path = "reports") -> Path:
    rows = build_rows(trip, store, source, today)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_text = render_html(trip, rows, today, source)
    (out / f"{today}.html").write_text(html_text)
    (out / "latest.html").write_text(html_text)
    (out / "latest.md").write_text(render_markdown(trip, rows, today, source))
    return out / "latest.html"
