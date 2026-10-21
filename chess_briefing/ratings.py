"""Elo-Verlauf von ratings.fide.com (Chart-Daten) und Trendkennzahlen."""
from __future__ import annotations

import datetime as dt
import json

from .util import session

_MON = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def fide_history(fide_id: int) -> list[dict]:
    from .config import CACHE_DIR
    path = CACHE_DIR / "fide" / f"{fide_id}.json"
    import time
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        s = session()
        ref = f"https://ratings.fide.com/profile/{fide_id}/chart"
        try:
            s.get(ref, timeout=30)
            r = s.post(f"https://ratings.fide.com/a_chart_data.phtml?event={fide_id}&period=0",
                       headers={"Referer": ref, "X-Requested-With": "XMLHttpRequest"}, timeout=30)
            raw = json.loads(r.content.decode("utf-8-sig"))
        except Exception:
            return []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw), encoding="utf-8")
    out = []
    for e in raw:
        try:
            y, m = e["date_2"].split("-")
            d = dt.date(int(y), _MON[m], 1)
        except (KeyError, ValueError):
            continue
        out.append({
            "date": d.isoformat(),
            "standard": int(e["rating"]) if e.get("rating") else None,
            "rapid": int(e["rapid_rtng"]) if e.get("rapid_rtng") else None,
            "blitz": int(e["blitz_rtng"]) if e.get("blitz_rtng") else None,
            "games": int(e.get("period_games") or 0),
        })
    out.sort(key=lambda x: x["date"])
    return out


def trend(history: list[dict], months: int = 24) -> dict:
    pts = [(dt.date.fromisoformat(h["date"]), h["standard"]) for h in history if h["standard"]]
    if len(pts) < 2:
        return {}
    last_d, last_v = pts[-1]
    cut = last_d.replace(year=last_d.year - months // 12)
    older = [v for d, v in pts if d <= cut]
    base = older[-1] if older else pts[0][1]
    peak = max(v for _, v in pts)
    return {"current": last_v, "first": pts[0][1], "first_date": pts[0][0].isoformat(),
            "change_window": last_v - base, "window_months": months, "peak": peak,
            "rated_games_window": sum(h["games"] for h in history
                                      if dt.date.fromisoformat(h["date"]) > cut)}


def rating_at(history: list[dict], date_iso: str) -> int | None:
    if not date_iso or not history:
        return None
    best = None
    for h in history:
        if h["date"] <= date_iso and h["standard"]:
            best = h["standard"]
    return best
