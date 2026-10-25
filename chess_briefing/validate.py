"""Pruefung von matchplan.json gegen dossier.json.

Fehler (blockierend): Pflichtfelder, unbekannte Beleg-IDs, Perspektivfehler, illegale Zugfolgen.
Warnungen: Zahlen ohne Beleg, Floskeln, zu lange Saetze, Handlungen ohne Beleg.
"""
from __future__ import annotations

import re

import chess

from . import config

PLAN_PHASES = {"Eröffnung", "Mittelspiel", "Abwicklung", "Endspiel", "Zeit", "Praxis", "Psychologie"}
# Der Matchplan steuert die Partie nach der Eröffnung; die Eröffnung steht in den Karten und im Baum.
PLAN_CORE = ("Mittelspiel", "Zeit")
MAX_CAVEAT = 110
SLOP = [
    "es ist wichtig", "wichtig ist", "im auge behalten", "nicht unterschätzen", "schlüssel zum erfolg",
    "zusammenfassend", "insgesamt lässt sich", "spannend", "solide leistung", "auf jeden fall",
    "es empfiehlt sich", "man sollte", "gilt es", "in der regel", "grundsätzlich", "durchaus",
    "nicht zu vergessen", "von entscheidender bedeutung", "eine gute idee", "achte darauf, dass du",
    "vielseitig", "facettenreich", "ganzheitlich", "unter druck setzen",
]
MAX_DO, MAX_WHY = 220, 360


def _texts(b: dict):
    yield "headline", b.get("headline", "")
    ps = b.get("profile_summary") or {}
    yield "profile_summary", ps.get("type", "") + " " + ps.get("lever", "")
    for i, s in enumerate(b.get("summary", [])):
        yield f"summary[{i}]", s.get("title", "") + " " + s.get("text", "")
    for side in ("as_white", "as_black"):
        p = b.get(side) or {}
        yield f"{side}.goal", p.get("goal", "")
        yield f"{side}.online_goal", p.get("online_goal", "")
        for i, o in enumerate(p.get("opening", [])):
            yield f"{side}.opening[{i}]", o.get("idea", "")
            yield f"{side}.opening[{i}].online", (o.get("online") or {}).get("idea", "")
        for i, s in enumerate(p.get("plan", [])):
            yield f"{side}.plan[{i}]", s.get("do", "") + " " + s.get("why", "")
            on = s.get("online") or {}
            yield f"{side}.plan[{i}].online", on.get("do", "") + " " + on.get("why", "")
        for i, a in enumerate(p.get("avoid", [])):
            yield f"{side}.avoid[{i}]", a.get("text", "")
            yield f"{side}.avoid[{i}].online", (a.get("online") or {}).get("text", "")
    for i, w in enumerate(b.get("watch", [])):
        yield f"watch[{i}]", w.get("text", "")
    for k, v in (b.get("moments") or {}).items():
        yield f"moments.{k}", v


def _numbers(text: str) -> set[str]:
    # Zahlen ohne Zugnummern (z. B. "12…Ba6", "1.e4") und ohne Feldnamen
    t = re.sub(r"\d+\s*(\.{1,3}|…)\s*[KQRBNOa-h]", " ", text)
    t = re.sub(r"\b[a-h][1-8]\b", " ", t)
    nums = set()
    for m in re.finditer(r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w])", t):
        n = m.group(1).replace(",", ".")
        if n in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}:
            continue
        nums.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return nums


def _fact_numbers(facts) -> set[str]:
    out = set()
    for f in facts:
        for m in re.finditer(r"\d+(?:[.,]\d+)?", f["text"]):
            n = m.group(0).replace(",", ".")
            out.add(n.rstrip("0").rstrip(".") if "." in n else n)
            try:
                v = float(n)
                out.add(str(round(v)))
                if v <= 1:
                    out.add(str(round(v * 100)))      # 0.35 -> 35 (%)
            except ValueError:
                pass
    return out


def _check_line(line: str) -> str | None:
    b = chess.Board()
    toks = [t for t in re.split(r"\s+", line.replace("…", "... ").strip()) if t]
    for t in toks:
        t = re.sub(r"^\d+\.(\.\.)?", "", t)
        if not t or t in ("...", "..") or re.fullmatch(r"\d+\.+", t):
            continue
        try:
            b.push_san(t)
        except ValueError:
            return t
    return None


def validate_briefing(b: dict | None, d: dict | None) -> tuple[list[str], list[str]]:
    P, W = [], []
    if not d:
        return ["dossier.json fehlt – zuerst prepare ausführen."], []
    if not b:
        return ["matchplan.json fehlt."], []
    facts = {f["id"]: f for f in d["facts"]}
    fact_nums = _fact_numbers(d["facts"])

    # Stufe briefing-medium: nur die Seite des Nutzers (dossier.mode.sides); research: beide Seiten
    mode = d.get("mode") or {}
    sides = tuple(mode.get("sides") or ("as_white", "as_black"))
    min_steps = mode.get("min_plan_steps", 4)
    for key in ("headline", "summary", *sides):
        if not b.get(key):
            P.append(f"Pflichtfeld fehlt: {key}")
    if len(b.get("summary", [])) not in (2, 3, 4):
        W.append("summary sollte 3 Kernpunkte haben.")
    if len(" ".join(b.get("caveats") or [])) > MAX_CAVEAT:
        W.append(f"caveats: zusammen höchstens {MAX_CAVEAT} Zeichen (eine Zeile im Report).")

    online_active = bool((d.get("online") or {}).get("active"))

    def check_ev(where: str, ids, allowed: set[str] | None, required=True, online=False):
        if not ids:
            if required:
                W.append(f"{where}: kein Beleg (evidence).")
            return
        for i in ids:
            if online and not (i.startswith("O") or i.startswith("E")):
                P.append(f"{where}: Online-Feld zitiert Turnier-Beleg {i} – nur O…/E… erlaubt")
            if not online and i.startswith("O"):
                P.append(f"{where}: Turnier-Feld zitiert Online-Beleg {i} – gehört in das Feld `online`")
            if i not in facts:
                P.append(f"{where}: unbekannter Beleg {i}")
            elif allowed and facts[i]["scope"] not in allowed:
                P.append(f"{where}: Perspektivfehler – {i} beschreibt ihn mit "
                         f"{'Weiß' if facts[i]['scope'] == 'white' else 'Schwarz'}, passt nicht zu diesem Plan.")

    for i, s in enumerate(b.get("summary", [])):
        check_ev(f"summary[{i}]", s.get("evidence"), None)
    ps = b.get("profile_summary")
    if d.get("profile") and not ps:
        W.append("profile_summary fehlt (Typ-Satz + Hebel-Satz zum Spielerprofil).")
    if ps:
        check_ev("profile_summary", ps.get("evidence"), None)
        if not any(str(i).startswith("P") for i in ps.get("evidence") or []):
            W.append("profile_summary: sollte mindestens einen Profil-Beleg P… zitieren.")
    for side, allowed in (("as_white", {"black", "all"}), ("as_black", {"white", "all"})):
        if side not in sides:
            if b.get(side):
                P.append(f"{side}: diese Stufe gilt nur für {', '.join(sides)} (die Farbe steht fest)")
            continue
        p = b.get(side) or {}
        if not p.get("goal"):
            P.append(f"{side}.goal fehlt")
        if not p.get("opening"):
            P.append(f"{side}.opening fehlt (mind. eine konkrete Linie)")
        has_online = bool(p.get("online_goal")) or any(x.get("online") for k in ("opening", "plan", "avoid") for x in p.get(k, []))
        if has_online and not online_active:
            P.append(f"{side}: Online-Felder ohne übernommenen Online-Account (Konfidenz < 50 %)")
        if online_active and not has_online:
            W.append(f"{side}: Online-Account vorhanden, aber keine Online-Felder geschrieben.")
        for i, o in enumerate(p.get("opening", [])):
            if o.get("line"):
                bad = _check_line(o.get("line", ""))
                if bad:
                    P.append(f"{side}.opening[{i}]: illegaler/unklarer Zug '{bad}' in '{o.get('line')}'")
                if o.get("basis") not in ("partien", "theorie", "beides"):
                    W.append(f"{side}.opening[{i}]: basis sollte partien|theorie|beides sein.")
                check_ev(f"{side}.opening[{i}]", o.get("evidence"), allowed, required=o.get("basis") != "theorie")
            elif not o.get("online"):
                P.append(f"{side}.opening[{i}]: weder Turnier-Linie noch Online-Teil")
            on = o.get("online")
            if on:
                bad = _check_line(on.get("line", "")) if on.get("line") else None
                if bad:
                    P.append(f"{side}.opening[{i}].online: illegaler/unklarer Zug '{bad}'")
                check_ev(f"{side}.opening[{i}].online", on.get("evidence"), allowed, online=True)
        phases = [s.get("phase") for s in p.get("plan", [])]
        if len(phases) < min_steps:
            W.append(f"{side}.plan: weniger als {min_steps} Schritte.")
        if phases.count("Eröffnung") > 1:
            W.append(f"{side}.plan: höchstens ein Eröffnungs-Schritt; die Eröffnung gehört in die Karten.")
        for ph in PLAN_CORE:
            if ph not in phases:
                W.append(f"{side}.plan: Schritt zur Phase '{ph}' fehlt (Stärke je Phase, Zeitmanagement gegen ihn).")
        if not {"Abwicklung", "Endspiel"} & set(phases):
            W.append(f"{side}.plan: Schritt 'Abwicklung' oder 'Endspiel' fehlt (tauschen oder komplex halten?).")
        n_me = sum(1 for s in p.get("plan", []) if any(str(i).startswith("M") for i in s.get("evidence") or []))
        if n_me > config.ME_MAX_PLAN_STEPS:
            P.append(f"{side}.plan: {n_me} Schritte stützen sich auf das Eigenprofil (M…), höchstens "
                     f"{config.ME_MAX_PLAN_STEPS} – der Plan richtet sich gegen den Gegner.")
        for i, s in enumerate(p.get("plan", [])):
            if s.get("phase") not in PLAN_PHASES:
                P.append(f"{side}.plan[{i}]: Phase '{s.get('phase')}' unbekannt ({', '.join(sorted(PLAN_PHASES))})")
            if not s.get("do"):
                P.append(f"{side}.plan[{i}]: 'do' fehlt")
            if len(s.get("do", "")) > MAX_DO:
                W.append(f"{side}.plan[{i}]: Handlung länger als {MAX_DO} Zeichen.")
            if len(s.get("why", "")) > MAX_WHY:
                W.append(f"{side}.plan[{i}]: Begründung länger als {MAX_WHY} Zeichen.")
            check_ev(f"{side}.plan[{i}]", s.get("evidence"), allowed)
            if s.get("online"):
                if not s["online"].get("do"):
                    P.append(f"{side}.plan[{i}].online: 'do' fehlt")
                check_ev(f"{side}.plan[{i}].online", s["online"].get("evidence"), allowed, online=True)
        for i, a in enumerate(p.get("avoid", [])):
            if not a.get("text") and not a.get("online"):
                P.append(f"{side}.avoid[{i}]: weder Text noch Online-Teil")
            check_ev(f"{side}.avoid[{i}]", a.get("evidence"), allowed, required=False)
            if a.get("online"):
                check_ev(f"{side}.avoid[{i}].online", a["online"].get("evidence"), allowed, required=True, online=True)
    for i, w in enumerate(b.get("watch", [])):
        check_ev(f"watch[{i}]", w.get("evidence"), None, required=False)
    km_ids = {k["id"] for k in d.get("key_moments", [])}
    for k in (b.get("moments") or {}):
        if k not in km_ids:
            P.append(f"moments: unbekannte Schlüsselstellung {k}")

    for where, text in _texts(b):
        low = text.lower()
        for s in SLOP:
            if s in low:
                W.append(f"{where}: Floskel „{s}“")
        missing = [n for n in _numbers(text) if n not in fact_nums]
        if missing:
            W.append(f"{where}: Zahl(en) ohne Beleg im Dossier: {', '.join(sorted(missing))}")
    return P, W
