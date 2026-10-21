"""Spielerprofil: 8 Achsen, Teil-Elo je Stellungsart, Typ-Etikett, Zielkorridor mit Eigenprofil.

Grundsaetze:
  * Vorliebe (welche Stellungen er ansteuert) und Koennen (wo er Fehler macht) werden getrennt gemessen.
  * Vorliebe nur an Stellungsmerkmalen, die nicht von Fehlern abhaengen (entgegengesetzte Rochaden, Damen bei
    Zug 25, ausgeglichenes Materialungleichgewicht, offenes Zentrum).
  * Koennen als Teil-Elo: seine Fehlerquote je Stellungsart, ueber Vergleichskurven (data/elo_curves.json,
    `briefing.py calibrate`) in eine Elo uebersetzt und zu seiner Elo gezogen (wenige Zuege -> nahe seiner Elo).
  * "scharf" = Stellung mit nur einem guten Zug: der zweitbeste Zug (MultiPV 2) ist >= ONLY_MOVE_GAP schlechter.
  * Jede Achse: 5 Stufen, n, Konfidenz, Halbierungsprobe (gerade/ungerade Partien), unter der Mindestmenge "offen".
Belege: P... (Profil, aus seinen Partien) und M... (aus den Angaben des Nutzers, nur mit me.json).
"""
from __future__ import annotations

import json
import math
import statistics as st

import chess

from . import config
from .metrics import PHASES, trouble_threshold
from .online.rating_map import dwz_to_elo, reference
from .util import read_json

CLASSES = ("scharf", "ruhig", "endspiel")
CLASS_DE = {"scharf": "scharf", "ruhig": "ruhig", "endspiel": "Endspiel"}
CURVES_FILE = config.DATA_DIR / "elo_curves.json"
ME_FIELDS = ("Eröffnung", "Mittelspiel", "Endspiel", "Taktik", "Strategie", "Verteidigung", "Verwertung", "Zeit")
ME_CLASS = {"taktik": ("scharf",), "rechnen": ("scharf",), "strategie": ("ruhig",), "positionsspiel": ("ruhig",),
            "mittelspiel": ("scharf", "ruhig"), "endspiel": ("endspiel",)}
TYPES = {("Angreifer", "rechenstark"): "Aktivist", ("Stratege", "rechenschwach"): "Reflektor/Theoretiker",
         ("Stratege", "rechenstark"): "Pragmatiker"}


# ---------------------------------------------------------------- Messgroessen je Partie
def _exp(wdl) -> float:
    w, d, l = wdl
    return (w + 0.5 * d) / ((w + d + l) or 1)


def _boards_at(ucis: list[str], plies: set[int]) -> dict[int, chess.Board]:
    b, out = chess.Board(), {}
    for i in range(len(ucis) + 1):
        if i in plies:
            out[i] = b.copy(stack=False)
        if i < len(ucis):
            b.push(chess.Move.from_uci(ucis[i]))
    return out


def _signature(b: chess.Board, color: bool) -> tuple[int, int, int]:
    return (len(b.pieces(chess.QUEEN, color)), len(b.pieces(chess.ROOK, color)),
            len(b.pieces(chess.BISHOP, color)) + len(b.pieces(chess.KNIGHT, color)))


def _material(b: chess.Board, color: bool) -> float:
    q, r, m = _signature(b, color)
    return 9 * q + 5 * r + 3 * m + len(b.pieces(chess.PAWN, color))


def game_markers(g: dict) -> dict[str, bool]:
    """Schaerfe-Merkmale einer Partie (unabhaengig davon, wer Fehler macht)."""
    n = len(g["ucis"])
    plies = {p for p in (30, 40, 50) if p <= n} | {min(40, n), min(50, n), min(30, n)}
    bs = _boards_at(g["ucis"], plies)
    b40 = bs[min(40, n)]
    wk, bk = b40.king(chess.WHITE), b40.king(chess.BLACK)
    fw, fb = chess.square_file(wk), chess.square_file(bk)
    opp = n >= 24 and abs(fw - fb) >= 3 and fw not in (3, 4) and fb not in (3, 4)
    b50 = bs[min(50, n)]
    queens = bool(b50.pieces(chess.QUEEN, chess.WHITE)) and bool(b50.pieces(chess.QUEEN, chess.BLACK))
    imb = any(_signature(bs[p], True) != _signature(bs[p], False)
              and abs(_material(bs[p], True) - _material(bs[p], False)) <= 1.5 for p in (30, 40, 50) if p <= n)
    b30 = bs[min(30, n)]
    center = sum(1 for sq in chess.SquareSet(chess.BB_FILE_D | chess.BB_FILE_E)
                 if (p := b30.piece_at(sq)) and p.piece_type == chess.PAWN)
    return {"opposite_castling": opp, "queens_25": queens, "imbalance": imb, "open_center": center <= 2}


MARKER_DE = {"opposite_castling": "entgegengesetzte Rochaden", "queens_25": "Damen bei Zug 25",
             "imbalance": "ausgeglichenes Materialungleichgewicht", "open_center": "offenes Zentrum"}


def move_class(m: dict, pos_before: dict | None) -> str | None:
    """Stellungsart eines eigenen Zuges: endspiel | scharf | ruhig (None = nicht gezaehlt)."""
    if m["phase"] == "Endspiel":
        return "endspiel"
    if m["move_no"] < config.PROFILE_MIN_MOVE:
        return None
    alt = (pos_before or {}).get("alt")
    if not alt:   # aeltere Analyse ohne zweitbesten Zug: grober Ersatz
        return "scharf" if m.get("best_san") and ("x" in m["best_san"] or "+" in m["best_san"]) else "ruhig"
    if alt.get("wdl2") is None:
        return None   # nur ein legaler Zug: keine Entscheidung
    e1, e2 = _exp(alt["wdl"]), _exp(alt["wdl2"])
    gap = (e1 - e2) if m["white"] else (e2 - e1)
    return "scharf" if gap >= config.ONLY_MOVE_GAP else "ruhig"


def side_stats(g: dict, a: dict, pos: list[dict]) -> dict:
    """Alle Rohzahlen einer Partie aus Sicht der Seite g['is_white'] (fuer Gegner und Kalibrierung gleich)."""
    cls = {c: [0, 0] for c in CLASSES}
    ph = {p: [0, 0] for p in PHASES}
    proxy = 0
    for m in a["moves"]:
        if not m["own"] or not m["live"]:
            continue
        bad = m["level"] in ("mistake", "blunder")
        ph[m["phase"]][0] += 1
        ph[m["phase"]][1] += bad
        pb = pos[m["ply"] - 1] if m["ply"] - 1 < len(pos) else None
        c = move_class(m, pb)
        if c:
            cls[c][0] += 1
            cls[c][1] += bad
            proxy += c != "endspiel" and not (pb or {}).get("alt")
    # Gegnerfehler sofort bestraft?
    mv = a["moves"]
    opp_err = punished = 0
    for k, m in enumerate(mv):
        if not m["own"] and m["level"] in ("mistake", "blunder") and k + 1 < len(mv):
            opp_err += 1
            punished += mv[k + 1]["loss"] <= config.EXP_INACCURACY
    own_clk = [m for m in mv if m["own"] and m["clock"] is not None]
    first = own_clk[0]["clock"] if own_clk else None
    c30 = next((m["clock"] for m in own_clk if m["move_no"] == 30), None)
    thr = trouble_threshold(g)
    return {
        "classes": cls, "phases": ph, "proxy_moves": proxy,
        "markers": game_markers(g),
        "score": g.get("player_score"), "plies": len(g["ucis"]),
        "winning": (a["max_exp"] or 0) >= 0.80, "losing": (a["min_exp"] if a["min_exp"] is not None else 1) <= 0.20,
        "opp_errors": opp_err, "punished": punished,
        "clock30_share": (c30 / first) if c30 is not None and first else None,
        "trouble": any(m["clock"] < thr and m["move_no"] <= 40 for m in own_clk) if own_clk else None,
        "base_min": round(first / 60) if first else None,
        "family": a.get("family") or "Unbekannt", "is_white": g["is_white"],
        "elo": g.get("player_elo") or g.get("player_elo_est"),   # Wertung zum Spielzeitpunkt
    }


# ---------------------------------------------------------------- Vergleichskurven
def load_curves() -> dict | None:
    return read_json(CURVES_FILE)


def _fit(rows: list[dict]) -> dict | None:
    """ln(Fehlerquote) linear in der Elo, gewichtet mit der Fehlerzahl; nur fallend sinnvoll."""
    pts = [(r["elo"], math.log((r["x"] + 0.5) / r["n"]), r["x"] + 0.5) for r in rows if r["n"] >= 30]
    if len(pts) < 3:
        return None
    sw = sum(w for *_, w in pts)
    mx = sum(x * w for x, _, w in pts) / sw
    my = sum(y * w for _, y, w in pts) / sw
    sxx = sum(w * (x - mx) ** 2 for x, _, w in pts)
    if not sxx:
        return None
    b = sum(w * (x - mx) * (y - my) for x, y, w in pts) / sxx * 100     # je 100 Elo
    a = my + b * (2000 - mx) / 100
    return {"a": round(a, 4), "b": round(b, 4)} if b < -0.01 else None


def rate_at(fit: dict, elo: float) -> float:
    return math.exp(fit["a"] + fit["b"] * (elo - 2000) / 100)


def elo_at(fit: dict, rate: float) -> float:
    return max(1000.0, min(2900.0, 2000 + 100 * (math.log(max(rate, 1e-6)) - fit["a"]) / fit["b"]))


REF_N = {"conversion": "conversion_n", "resilience": "resilience_n", "punish": "punish_n",
         "clock30_mean": "clock_n", "clock30_sd": "clock_n"}


def ref(curves: dict | None, key: str, elo: float):
    """Vergleichswert fuer eine Elo: gewichtete Gerade ueber alle Baender (glaettet das Rauschen einzelner Baender
    mit ~100 Faellen), Elo auf den Bereich der Bandmitten begrenzt, Quoten auf 0..1."""
    if not curves:
        return None
    pts = [(b["elo"], b[key], b.get(REF_N.get(key, "sides")) or b.get("sides") or 1)
           for b in curves["bands"] if b.get(key) is not None]
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0][1]
    sw = sum(w for *_, w in pts)
    mx = sum(x * w for x, _, w in pts) / sw
    my = sum(y * w for _, y, w in pts) / sw
    sxx = sum(w * (x - mx) ** 2 for x, _, w in pts)
    slope = sum(w * (x - mx) * (y - my) for x, y, w in pts) / sxx if sxx else 0.0
    e = max(pts[0][0], min(pts[-1][0], elo))
    v = my + slope * (e - mx)
    return max(0.0, min(1.0, v)) if key not in ("markers_mean", "markers_sd") else max(0.0, v)


def teil_elo(fit: dict | None, n: int, x: int, elo: float, x0: float | None = None) -> dict:
    """Teil-Elo = heutige Elo + Abstand seiner Fehler zu den erwarteten Fehlern.
    x0 = erwartete Fehlerzahl nach der Wertung zum Spielzeitpunkt jeder Partie (sonst n * Quote der heutigen Elo).
    Die Kurve ist exponentiell, daher entspricht der Faktor beobachtet/erwartet einem festen Elo-Abstand. Vorher werden
    PROFILE_SHRINK_MOVES Zuege mit erwarteter Quote dazugerechnet (wenige Zuege -> Abstand nahe 0)."""
    out = {"n": n, "x": x, "elo": None, "span": None, "open": n < config.PROFILE_MIN_CLASS_MOVES or fit is None}
    if fit is None or not n:
        return out
    k = config.PROFILE_SHRINK_MOVES
    x0 = n * rate_at(fit, elo) if x0 is None else x0
    rbar = x0 / n

    def est(xx):
        delta = 100 * math.log((max(0.0, xx) + k * rbar) / (x0 + k * rbar)) / fit["b"]
        return max(1000.0, min(2900.0, elo + delta))
    sd = config.PROFILE_SPAN_FACTOR * math.sqrt(x + 1)
    mid, lo, hi = est(x), est(x + sd), est(x - sd)
    out.update(elo=round(mid), span=round((hi - lo) / 2))
    return out


def expected_errors(fit: dict | None, rows: list[dict], key: str, name: str, elo_now: float) -> float | None:
    """Erwartete Fehler einer Klasse/Phase, jede Partie mit der Wertung zum Spielzeitpunkt."""
    if fit is None:
        return None
    return sum(r[key][name][0] * rate_at(fit, r.get("elo") or elo_now) for r in rows)


# ---------------------------------------------------------------- Achsen
def _step(v: float, t1: float, t2: float) -> int:
    return -2 if v <= -t2 else -1 if v <= -t1 else 2 if v >= t2 else 1 if v >= t1 else 0


def _conf(n: int, minimum: int) -> int:
    return 0 if n < minimum else 1 if n < 2 * minimum else 2 if n < 4 * minimum else 3


def _shrunk_rate(hits: int, n: int, p0: float, k: float) -> float:
    return (hits + k * p0) / (n + k)


def _axis(key, title, labels, step, value, n, unit, minimum, half=None):
    conf = _conf(n, minimum)
    unsure = half is not None and None not in half and abs(half[0] - half[1]) >= 2
    if conf == 0:
        step = None
    return {"key": key, "title": title, "labels": labels, "step": step, "value": value, "n": n, "unit": unit,
            "conf": min(conf, 1) if unsure else conf, "unsure": unsure,
            "label": "offen" if step is None else labels[step + 2]}


def _split(rows: list) -> tuple[list, list]:
    return rows[0::2], rows[1::2]


def _class_counts(rows):
    out = {c: [0, 0] for c in CLASSES}
    for r in rows:
        for c in CLASSES:
            out[c][0] += r["classes"][c][0]
            out[c][1] += r["classes"][c][1]
    return out


def _phase_counts(rows):
    out = {p: [0, 0] for p in PHASES}
    for r in rows:
        for p in PHASES:
            out[p][0] += r["phases"][p][0]
            out[p][1] += r["phases"][p][1]
    return out


def axis_character(rows, curves, elo):
    def mean_score(rr):
        return st.mean(sum(r["markers"].values()) for r in rr) if rr else None
    mu, sd = ref(curves, "markers_mean", elo), ref(curves, "markers_sd", elo)

    def step_of(rr):
        m = mean_score(rr)
        if m is None or mu is None or not sd:
            return None
        e = (m - mu) / sd * len(rr) / (len(rr) + config.PROFILE_SHRINK_GAMES)
        return _step(e, 0.2, 0.5)
    m = mean_score(rows)
    counts = {k: sum(r["markers"][k] for r in rows) for k in MARKER_DE}
    ax = _axis("charakter", "Partie-Charakter",
               ["deutlich ruhig", "eher ruhig", "ausgeglichen", "eher scharf", "deutlich scharf"],
               step_of(rows), m, len(rows), "Partien", config.PROFILE_MIN_GAMES, [step_of(h) for h in _split(rows)])
    ax["detail"] = {"mean": m, "ref": mu, "counts": counts}
    # Lage auf der Stil-Karte: gezogene Effektstaerke (Merkmale gegenueber gleich Starken, in Streuungen) und 1-sigma
    n = len(rows)
    if m is not None and mu is not None and sd:
        w = n / (n + config.PROFILE_SHRINK_GAMES)
        ax["detail"].update(x=(m - mu) / sd * w, sx=w / math.sqrt(n))
    return ax


def axis_skill(te: dict):
    s, r = te["scharf"], te["ruhig"]
    n = min(s["n"], r["n"])
    if s["elo"] is None or r["elo"] is None or s["open"] or r["open"]:
        ax = _axis("koennen", "Können", ["deutlich stärker scharf", "eher stärker scharf", "ausgeglichen",
                                         "eher stärker ruhig", "deutlich stärker ruhig"], None, None, n, "Züge",
                   config.PROFILE_MIN_CLASS_MOVES)
        ax["diff"] = None
        return ax
    diff = s["elo"] - r["elo"]
    ax = _axis("koennen", "Können", ["deutlich stärker scharf", "eher stärker scharf", "ausgeglichen",
                                     "eher stärker ruhig", "deutlich stärker ruhig"],
               -_step(diff, config.PROFILE_SKILL_DIFF / 2, config.PROFILE_SKILL_DIFF * 1.5), diff, n, "Züge",
               config.PROFILE_MIN_CLASS_MOVES)
    ax["diff"] = diff
    ax["significant"] = abs(diff) >= config.PROFILE_SKILL_DIFF and abs(diff) > (s["span"] + r["span"])
    return ax


def axis_ambition(rows, team_rows, curves, elo):
    scores = [r["score"] for r in rows if r["score"] is not None]
    seen = {(r.get("date"), r.get("opp")) for r in rows}
    team = [t for t in team_rows or [] if t["result"] in ("1", "0", "½") and (t.get("date"), t.get("opp")) not in seen]
    scores += [{"1": 1.0, "0": 0.0, "½": 0.5}[t["result"]] for t in team]
    n, d = len(scores), sum(1 for s in scores if s == 0.5)
    p0 = ref(curves, "draw_rate", elo)
    short = sum(1 for r in rows if r["score"] == 0.5 and r["plies"] < 50)

    def step_of(ss):
        if p0 is None or not ss:
            return None
        dd = sum(1 for s in ss if s == 0.5)
        return -_step(_shrunk_rate(dd, len(ss), p0, config.PROFILE_SHRINK_GAMES) - p0, 0.05, 0.12)
    ax = _axis("ambition", "Ambition", ["deutlich remisfreudig", "eher remisfreudig", "ausgeglichen", "eher kämpferisch",
                                        "deutlich kämpferisch"], step_of(scores), d / n if n else None, n, "Ergebnisse",
               config.PROFILE_MIN_RESULTS, [step_of(h) for h in _split(scores)])
    ax["detail"] = {"draws": d, "short_draws": short, "ref": p0, "team": len(team)}
    return ax


def _rate_axis(key, title, labels, hits, n, p0, minimum, t=(0.08, 0.16), k=None):
    k = config.PROFILE_SHRINK_GAMES if k is None else k
    step = None if p0 is None or not n else _step(_shrunk_rate(hits, n, p0, k) - p0, *t)
    ax = _axis(key, title, labels, step, hits / n if n else None, n, "Fälle", minimum)
    ax["detail"] = {"hits": hits, "ref": p0}
    return ax


def axis_conversion(rows, curves, elo):
    win = [r for r in rows if r["winning"] and r["score"] is not None]
    won = sum(1 for r in win if r["score"] == 1)
    return _rate_axis("verwertung", "Chancenverwertung", ["lässt deutlich liegen", "lässt eher liegen", "ausgeglichen",
                                                          "verwertet eher sicher", "verwertet sicher"],
                      won, len(win), ref(curves, "conversion", elo), config.PROFILE_MIN_CASES)


def axis_resilience(rows, curves, elo):
    los = [r for r in rows if r["losing"] and r["score"] is not None]
    saved = sum(1 for r in los if r["score"] >= 0.5)
    return _rate_axis("zaehigkeit", "Zähigkeit", ["bricht deutlich ein", "bricht eher ein", "ausgeglichen", "eher zäh",
                                                   "sehr zäh"], saved, len(los), ref(curves, "resilience", elo),
                      config.PROFILE_MIN_CASES)


def axis_clock(rows, curves, elo):
    sh = [r["clock30_share"] for r in rows if r["clock30_share"] is not None]
    mu, sd = ref(curves, "clock30_mean", elo), ref(curves, "clock30_sd", elo)
    tt = [r["trouble"] for r in rows if r["trouble"] is not None]
    p0 = ref(curves, "trouble_rate", elo)

    def step_of(ss):
        if not ss or mu is None or not sd:
            return None
        return -_step((st.mean(ss) - mu) / sd * len(ss) / (len(ss) + config.PROFILE_SHRINK_GAMES), 0.25, 0.6)
    ax = _axis("uhr", "Uhr", ["deutlich schnell", "eher schnell", "ausgeglichen", "eher langsam", "deutlich langsam"],
               step_of(sh), st.mean(sh) if sh else None, len(sh), "Partien mit Uhr", config.PROFILE_MIN_CLOCK,
               [step_of(h) for h in _split(sh)])
    ax["detail"] = {"ref": mu, "trouble": sum(tt), "trouble_n": len(tt), "trouble_ref": p0,
                    "bases": sorted({r["base_min"] for r in rows if r["base_min"]})}
    return ax


def axis_repertoire(rows):
    fam80 = {}
    for col in (True, False):
        rr = [r for r in rows if r["is_white"] == col]
        if len(rr) < config.PROFILE_MIN_COLOR_GAMES:
            continue
        cnt = sorted(((sum(1 for r in rr if r["family"] == f), f) for f in {r["family"] for r in rr}), reverse=True)
        cum = k = 0
        for c, _ in cnt:
            cum += c
            k += 1
            if cum >= 0.8 * len(rr):
                break
        fam80["white" if col else "black"] = k
    v = st.mean(fam80.values()) if fam80 else None
    step = None if v is None else (-2 if v <= 1.5 else -1 if v <= 2.5 else 0 if v <= 3.5 else 1 if v <= 4.5 else 2)
    ax = _axis("repertoire", "Repertoire", ["sehr eng", "eher eng", "mittel", "eher breit", "sehr breit"],
               step, v, len(rows), "Partien", config.PROFILE_MIN_COLOR_GAMES)
    if v is None:
        ax.update(step=None, label="offen", conf=0)
    ax["detail"] = {"fam80": fam80}
    return ax


# ---------------------------------------------------------------- Aufbau
def player_elo(ident, games) -> tuple[float | None, str]:
    r = reference(ident)
    if r:
        return r["elo"], f"{r['kind']} {r['value']}" + (f" ≈ Elo {r['elo']}" if r["kind"] == "DWZ" else "")
    elos = [g["player_elo"] for g in games if g.get("player_elo")]
    return (st.mean(elos), f"Ø Elo in den Partien {round(st.mean(elos))}") if elos else (None, "")


def type_label(axes: dict) -> dict:
    ch, sk = axes["charakter"], axes["koennen"]
    pref = None if ch["step"] is None else ("Angreifer" if ch["step"] >= 1 else "Stratege" if ch["step"] <= -1 else None)
    comp = None
    if sk["step"] is not None and sk.get("significant"):
        comp = "rechenstark" if sk["diff"] > 0 else "rechenschwach"
    if pref and comp:
        return {"name": f"{pref}, {comp}", "hansen": TYPES.get((pref, comp)), "unsure": ch["unsure"] or sk["unsure"]}
    unsure = ch["step"] is None or sk["step"] is None
    return {"name": "Allrounder", "hansen": None, "unsure": unsure}


def build(ident, games: list[dict], ann: dict, pos: dict, team_rows: list[dict] | None) -> dict:
    """Profil des Gegners mit Belegen P1, P2, ..."""
    curves = load_curves()
    elo, elo_txt = player_elo(ident, games)
    rows = []
    for g in sorted(games, key=lambda g: (g["date"], g["id"])):
        r = side_stats(g, ann[g["id"]], pos.get(g["id"], []))
        r["date"], r["opp"] = g["date"], (g.get("opponent") or "").split(",")[0].strip().lower()
        rows.append(r)
    for t in team_rows or []:
        t["opp"] = (t.get("opponent") or "").split(",")[0].strip().lower()
    cc, pc = _class_counts(rows), _phase_counts(rows)
    e = elo or 1800.0
    fits = (curves or {}).get("classes", {})
    pfits = (curves or {}).get("phases", {})
    def tel(fit, counts, key, name):
        return teil_elo(fit, counts[name][0], counts[name][1], e, expected_errors(fit, rows, key, name, e))
    te = {c: tel((fits.get(c) or {}).get("fit"), cc, "classes", c) for c in CLASSES}
    tp = {p: tel((pfits.get(p) or {}).get("fit"), pc, "phases", p) for p in PHASES}
    dated = [r["elo"] for r in rows if r.get("elo")]
    axes = {
        "charakter": axis_character(rows, curves, e),
        "koennen": axis_skill(te),
        "ambition": axis_ambition(rows, team_rows, curves, e),
        "verwertung": axis_conversion(rows, curves, e),
        "zaehigkeit": axis_resilience(rows, curves, e),
        "uhr": axis_clock(rows, curves, e),
        "repertoire": axis_repertoire(rows),
    }
    opp_err = sum(r["opp_errors"] for r in rows)
    punished = sum(r["punished"] for r in rows)
    p_ref = ref(curves, "punish", e)
    axes["verwertung"]["detail"].update(opp_errors=opp_err, punished=punished, punish_ref=p_ref)
    phase_open = [p for p in PHASES if tp[p]["elo"] is None or tp[p]["open"]]
    ph_known = {p: tp[p]["elo"] for p in PHASES if p not in phase_open}
    weakest = min(ph_known, key=ph_known.get) if len(ph_known) >= 2 else None
    spread = (max(ph_known.values()) - ph_known[weakest]) if weakest else 0
    axes["phasen"] = {"key": "phasen", "title": "Phasen", "teil": tp, "weakest": weakest if spread >= 75 else None,
                      "spread": spread, "step": None, "conf": 0 if not ph_known else 2, "unsure": False,
                      "label": (f"{weakest} schwächer" if weakest and spread >= 75 else "ohne klare Schwäche")
                      if ph_known else "offen", "n": sum(pc[p][0] for p in PHASES), "unit": "Züge"}
    label = type_label(axes)
    proxy = sum(r["proxy_moves"] for r in rows)
    ch, sk = axes["charakter"]["detail"], axes["koennen"]
    s_, r_ = te["scharf"], te["ruhig"]
    known_y = s_["elo"] is not None and r_["elo"] is not None
    style_map = {  # x: Vorliebe ruhig(-) / scharf(+), y: Teil-Elo scharf - ruhig; je mit 1-sigma
        "x": ch.get("x", 0.0), "sx": ch.get("sx", 1.0), "x_known": "x" in ch,
        "y": (s_["elo"] - r_["elo"]) if known_y else 0.0,
        "sy": math.hypot(s_["span"], r_["span"]) if known_y else 300.0, "y_known": known_y,
        "x_cut": 0.2, "y_cut": config.PROFILE_SKILL_DIFF}
    prof = {"elo": round(e) if elo else None, "elo_text": elo_txt, "calibrated": bool(curves), "map": style_map,
            "curves_meta": (curves or {}).get("meta"), "teil": te, "axes": axes, "type": label,
            "proxy_moves": proxy, "rapid_games": sum(1 for r in rows if r["base_min"] and r["base_min"] < 60),
            "dated": {"n": len(dated), "games": len(rows), "min": min(dated) if dated else None,
                      "max": max(dated) if dated else None}}
    prof["facts"] = _facts(prof)
    return prof


# ---------------------------------------------------------------- Belege
def _f(x, d=0):
    return "–" if x is None else (f"{x:.{d}f}".replace(".", ",") if d else str(round(x)))


def _te_txt(t: dict) -> str:
    if t["elo"] is None:
        return f"offen ({t['x']} Fehler in {t['n']} Zügen)"
    return f"~{t['elo']} ±{t['span']} ({t['x']} Fehler/Patzer in {t['n']} Zügen)" + (" – dünn" if t["open"] else "")


def _facts(p: dict) -> list[dict]:
    out = []

    def add(text, topic, scope="all"):
        out.append({"id": f"P{len(out) + 1}", "text": text, "scope": scope, "topic": f"profil:{topic}"})
        return out[-1]["id"]
    ax, te = p["axes"], p["teil"]
    base = f"Bezug {p['elo_text']}" if p["elo_text"] else "ohne Wertung (Bezug Elo 1800)"
    if not p["calibrated"]:
        add("Profil ohne Vergleichskurven (data/elo_curves.json fehlt, `python briefing.py calibrate`): "
            "Teil-Elo und Vergleichswerte offen.", "daten")
    t = p["type"]
    t["fact"] = add(f"Spielertyp (berechnet): {t['name']}" + (f" (≈ {t['hansen']})" if t["hansen"] else "")
                         + (" – unsicher" if t["unsure"] else "") + f"; Partie-Charakter {ax['charakter']['label']}, "
                         f"Können {ax['koennen']['label']}.", "typ")
    c = ax["charakter"]
    if c["value"] is not None:
        dd = c["detail"]
        c["fact"] = add(f"Partie-Charakter {c['label']}: Ø {_f(c['value'], 2)} von 4 Schärfe-Merkmalen je Partie"
                        + (f" (Vergleich gleiche Spielstärke {_f(dd['ref'], 2)})" if dd["ref"] is not None else "")
                        + "; " + ", ".join(f"{MARKER_DE[k]} {v}/{c['n']}" for k, v in dd["counts"].items())
                        + f"; {c['n']} Partien.", "charakter")
    c["fact_te"] = add(f"Teil-Elo ({base}): scharf {_te_txt(te['scharf'])}, ruhig {_te_txt(te['ruhig'])}, "
                       f"Endspiel {_te_txt(te['endspiel'])}. Scharf = nur ein guter Zug (zweitbester ≥ "
                       f"{_f(config.ONLY_MOVE_GAP * 100)} Prozentpunkte schlechter)"
                       + (f"; Fehler gemessen an der Wertung zum Spielzeitpunkt ({p['dated']['min']}–{p['dated']['max']}, "
                          f"{p['dated']['n']} von {p['dated']['games']} Partien)" if p["dated"]["n"] else "") + ".", "koennen")
    ax["koennen"]["fact"] = c["fact_te"]
    a = ax["ambition"]
    if a["n"]:
        dd = a["detail"]
        a["fact"] = add(f"Ambition {a['label']}: {dd['draws']} Remis in {a['n']} Ergebnissen = {_f(100 * a['value'])} %"
                        + (f" (Vergleich {_f(100 * dd['ref'])} %)" if dd["ref"] is not None else "")
                        + f"; davon {dd['short_draws']} Kurzremis unter 25 Zügen"
                        + (f"; inkl. {dd['team']} Mannschaftsergebnisse ohne Partie" if dd["team"] else "") + ".", "ambition")
    v = ax["verwertung"]
    dd = v["detail"]
    v["fact"] = add(f"Chancenverwertung {v['label']}: aus {v['n']} klar besseren Stellungen (≥ 0,80) {dd['hits']} gewonnen"
                    + (f" (Vergleich {_f(100 * dd['ref'])} %)" if dd["ref"] is not None else "")
                    + f"; {dd['punished']} von {dd['opp_errors']} gegnerischen Fehlern sofort bestraft"
                    + (f" (Vergleich {_f(100 * dd['punish_ref'])} %)" if dd.get("punish_ref") is not None else "") + ".",
                    "verwertung")
    z = ax["zaehigkeit"]
    z["fact"] = add(f"Zähigkeit {z['label']}: aus {z['n']} klar schlechteren Stellungen (≤ 0,20) {z['detail']['hits']} gehalten"
                    + (f" (Vergleich {_f(100 * z['detail']['ref'])} %)" if z["detail"]["ref"] is not None else "") + ".",
                    "zaehigkeit")
    u = ax["uhr"]
    if u["n"]:
        dd = u["detail"]
        u["fact"] = add(f"Uhr {u['label']}: bei Zug 30 im Schnitt {_f(100 * u['value'])} % der Startzeit übrig"
                        + (f" (Vergleich {_f(100 * dd['ref'])} %)" if dd["ref"] is not None else "")
                        + f"; Zeitnot vor Zug 40 in {dd['trouble']} von {dd['trouble_n']} Partien"
                        + (f" (Vergleich {_f(100 * dd['trouble_ref'])} %)" if dd["trouble_ref"] is not None else "")
                        + f"; {u['n']} Partien mit Uhr.", "uhr")
    ph = ax["phasen"]
    ph["fact"] = add("Teil-Elo je Phase: " + ", ".join(f"{k} {_te_txt(t)}" for k, t in ph["teil"].items()) + ".", "phasen")
    r = ax["repertoire"]
    if r["detail"]["fam80"]:
        r["fact"] = add(f"Repertoire {r['label']}: für 80 % der Partien reichen "
                        + ", ".join(f"mit {'Weiß' if k == 'white' else 'Schwarz'} {n} Eröffnungsfamilie(n)"
                                    for k, n in r["detail"]["fam80"].items()) + ".", "repertoire")
    if p["rapid_games"]:
        add(f"{p['rapid_games']} Partien mit unter 60 min Grundzeit: Vergleichskurven gelten für lange Bedenkzeit.", "daten")
    if p["proxy_moves"]:
        add(f"{p['proxy_moves']} Züge ohne zweitbesten Zug: dort scharf = bester Zug schlägt oder gibt Schach.", "daten")
    return out


# ---------------------------------------------------------------- Eigenprofil
def load_me(pdir) -> dict | None:
    """me.json (Projektwurzel, Voreinstellung) ueberlagert von output/players/<slug>/me.json (nur dieses Briefing)."""
    base = read_json(config.ROOT / "me.json") or {}
    over = read_json(pdir / "me.json") or {}
    me = {**base, **over}
    for k in ("repertoire",):
        if isinstance(base.get(k), dict) and isinstance(over.get(k), dict):
            me[k] = {**base[k], **over[k]}
    return me or None


def my_elo(me: dict) -> float | None:
    r = me.get("rating") or {}
    v = r.get("value")
    if not v:
        return None
    return dwz_to_elo(float(v))[0] if str(r.get("system", "DWZ")).upper() == "DWZ" else float(v)


def _norm(items) -> list[str]:
    return [str(x).strip().lower() for x in (items or []) if str(x).strip()]


def _tree_line(trees: dict, col: str, path: str) -> tuple[int, list[tuple[str, int]]]:
    nodes = trees.get(col, {}).get("nodes", {})
    nd = nodes.get(path)
    if not nd:
        return 0, []
    return nd["n"], [(c["san"], c["n"]) for c in nd["children"]]


def _san_path(line: str) -> str:
    toks = [t.split(".")[-1] for t in line.replace("…", " ").split()]
    return " ".join(t for t in toks if t and not t.endswith("."))


def _rel(g: float) -> str:
    """Abstand seiner Teil-Elo zu deiner Elo in Worten."""
    if abs(g) < 25:
        return "etwa auf deiner Höhe"
    return f"~{abs(g):.0f} Elo {'über' if g > 0 else 'unter'} dir"


def corridor(dossier: dict, me: dict) -> dict:
    """Zielkorridor (1 ruhig .. 5 scharf) und Hinweise aus Profil + Eigenprofil; Belege M1, M2, ..."""
    prof = dossier.get("profile") or {}
    te = prof.get("teil") or {}
    ax = prof.get("axes") or {}
    his = prof.get("elo")
    mine = my_elo(me)
    strengths, weak = _norm(me.get("strengths")), _norm(me.get("weaknesses"))
    adj = {c: 0 for c in CLASSES}
    for word, sign in [(w, 1) for w in strengths] + [(w, -1) for w in weak]:
        for c in ME_CLASS.get(word, ()):
            adj[c] += sign * config.ME_ADJUST
    my_te = {c: (mine + adj[c]) if mine else None for c in CLASSES}
    gap = {c: (te[c]["elo"] - my_te[c]) if te.get(c, {}).get("elo") is not None and my_te[c] is not None else None
           for c in CLASSES}
    reasons, hints = [], []
    base = 3
    if gap["scharf"] is not None and gap["ruhig"] is not None and not (te["scharf"]["open"] and te["ruhig"]["open"]):
        d = gap["scharf"] - gap["ruhig"]
        base = 1 if d >= 150 else 2 if d >= 50 else 5 if d <= -150 else 4 if d <= -50 else 3
        reasons.append(f"er liegt im Scharfen {_rel(gap['scharf'])}, im Ruhigen {_rel(gap['ruhig'])} – "
                       f"{'ruhige' if base < 3 else 'scharfe' if base > 3 else 'beide'} Stellungen liegen dir besser")
    else:
        reasons.append("Teil-Elo offen: Grundstufe ausgeglichen")
    var = 0
    goal = str(me.get("goal") or "").lower()
    if his and mine:
        diff = his - mine
        if goal == "remis_ok":
            var = -1
            reasons.append("Remis reicht: eine Stufe ruhiger")
        elif goal == "sieg" and diff >= 100:
            var = 1
            reasons.append(f"er ist {diff:.0f} Elo stärker und du brauchst einen Sieg: eine Stufe schärfer")
        elif diff <= -100 and goal != "sieg":
            var = -1
            reasons.append(f"du bist {-diff:.0f} Elo stärker: eine Stufe ruhiger (weniger Zufall)")
    style = me.get("style")
    sty = 0
    if isinstance(style, (int, float)):
        sty = -1 if style <= 2 else 1 if style >= 4 else 0
        if sty:
            reasons.append(f"dein Stil ({'eher ruhig' if sty < 0 else 'eher scharf'}): eine Stufe {'ruhiger' if sty < 0 else 'schärfer'}")
    target = max(1, min(5, base + var + sty))
    if gap["endspiel"] is not None and gap["scharf"] is not None and gap["ruhig"] is not None and not te["endspiel"]["open"]:
        lo, hi = min(gap["scharf"], gap["ruhig"]), max(gap["scharf"], gap["ruhig"])
        if gap["endspiel"] <= lo - 75:
            hints.append(f"Abwickeln ins Endspiel lohnt: dort liegt er {_rel(gap['endspiel'])}, so weit wie nirgends sonst.")
        elif gap["endspiel"] >= hi + 75:
            hints.append(f"Endspiel eher meiden: dort ist er am stärksten ({_rel(gap['endspiel'])}).")
    ph = (ax.get("phasen") or {}).get("teil") or {}
    known = {p: t["elo"] for p, t in ph.items() if t.get("elo") is not None and not t.get("open")}
    if len(known) >= 2:
        best, worst = max(known, key=known.get), min(known, key=known.get)
        for w in weak:
            if w.capitalize() == best:
                hints.append(f"Deine Schwäche {best} trifft seine stärkste Phase: diese Phase kurz halten.")
        for s in strengths:
            if s.capitalize() == worst:
                hints.append(f"Deine Stärke {worst} trifft seine schwächste Phase: dorthin steuern.")
    if "verteidigung" in weak and (ax.get("verwertung") or {}).get("step") is not None and ax["verwertung"]["step"] >= 1:
        hints.append("Er verwertet Vorteile sicher und du verteidigst nach eigener Angabe nicht zäh: kein Material ohne klaren Gegenwert geben.")
    if "verwertung" in weak and (ax.get("zaehigkeit") or {}).get("step") is not None and ax["zaehigkeit"]["step"] >= 1:
        hints.append("Er verteidigt zäh und du verwertest nach eigener Angabe nicht sicher: Vorteile in einfache Stellungen umsetzen.")
    if "zeit" in weak and (ax.get("uhr") or {}).get("step") is not None and ax["uhr"]["step"] <= -1:
        hints.append("Er spielt schnell und Zeit ist nach eigener Angabe deine Schwäche: Bedenkzeit früh einteilen.")
    rep = []
    trees = dossier.get("trees") or {}
    r = me.get("repertoire") or {}
    if r.get("white"):
        path = _san_path(r["white"])
        n, ch = _tree_line(trees, "black", path)
        rep.append(("black", f"Dein Repertoire mit Weiß {r['white']}: er hatte dagegen {n} Schwarzpartien"
                    + (": " + ", ".join(f"…{s} {k}×" for s, k in ch) if ch else "") + "."))
    for key in ("vs_e4", "vs_d4", "vs_other"):
        if r.get(key):
            path = _san_path(r[key])
            first = path.split()[0] if path else ""
            n_first, _ = _tree_line(trees, "white", first)
            n, ch = _tree_line(trees, "white", path)
            root_n = (trees.get("white", {}).get("nodes", {}).get("") or {}).get("n", 0)
            rep.append(("white", f"Dein Repertoire gegen 1.{first}: {r[key]} – er spielte 1.{first} in {n_first} von {root_n} "
                        f"Weißpartien, die Stellung nach {r[key]} {n}×" + (": " + ", ".join(f"{s} {k}×" for s, k in ch) if ch else "") + "."))
    facts = []

    def add(text, topic, scope="all"):
        facts.append({"id": f"M{len(facts) + 1}", "text": text, "scope": scope, "topic": f"ich:{topic}"})
    who = []
    if me.get("rating", {}).get("value"):
        rr = me["rating"]
        who.append(f"{rr.get('system', 'DWZ')} {rr['value']}" + (f" ≈ Elo {round(mine)}" if str(rr.get("system", "DWZ")).upper() == "DWZ" and mine else ""))
    if isinstance(style, (int, float)):
        who.append(f"Stil {style}/5 (1 ruhig, 5 scharf)")
    if strengths:
        who.append("Stärken: " + ", ".join(me.get("strengths")))
    if weak:
        who.append("Schwächen: " + ", ".join(me.get("weaknesses")))
    if goal:
        who.append({"sieg": "Ziel: Sieg nötig", "remis_ok": "Ziel: Remis reicht"}.get(goal, f"Ziel: {goal}"))
    if me.get("note"):
        who.append(str(me["note"]))
    add("Nutzerangabe (Annahme, nicht gemessen): " + "; ".join(who) + ".", "angaben")
    labels = ["ruhig", "eher ruhig", "ausgeglichen", "eher scharf", "scharf"]
    add(f"Zielkorridor: {labels[target - 1]} (Stufe {target} von 5) – " + "; ".join(reasons) + ".", "korridor")
    for h in hints:
        add(h, "hinweis")
    for scope, text in rep:
        add(text, "repertoire", scope)
    return {"target": target, "label": labels[target - 1], "reasons": reasons, "hints": hints, "my_elo": mine,
            "my_teil": my_te, "gap": gap, "facts": facts, "repertoire": me.get("repertoire") or {}}


def me_snapshot(pdir, me: dict | None) -> None:
    if me:
        (pdir / "me_used.json").write_text(json.dumps(me, ensure_ascii=False, indent=1), encoding="utf-8")
