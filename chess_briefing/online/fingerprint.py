"""Eroeffnungs-Fingerabdruck: Wie oft trifft ein Account an den Entscheidungsstellen des Spielers
dieselbe Wahl wie der Spieler in seinen Turnierpartien?

Entscheidungsstelle = Zugfolge (Pfad) bis zu einem eigenen Zug des Spielers in den ersten
FP_MAX_PLY Halbzuegen. Je Stelle wird verglichen:
  p_acc = Anteil, mit dem der Account dort denselben Zug spielt (nur wenn er die Stelle >= FP_MIN_N mal erreicht)
  p_pop = derselbe Anteil ueber alle Kandidaten zusammen (Grundrate, z. B. 1.e4 ist ohnehin haeufig)
  lift  = p_acc - p_pop
Der Fingerabdruck-Wert ist der Mittelwert der Lifts, gewichtet mit der Seltenheit (1 - p_pop):
seltene Uebereinstimmungen (Morra-Gambit) zaehlen mehr als haeufige (1.e4).
"""
from __future__ import annotations

from collections import Counter, defaultdict

FP_MAX_PLY = 10
FP_MIN_N = 2


def node_table(games: list[dict], who: str | None) -> dict:
    """games: [{'sans': [...], 'white': name, 'black': name}] -> {(color, path): Counter(next_move)}
    who=None: alle Seiten (fuer OTB-Partien wird stattdessen is_white genutzt)."""
    table: dict = defaultdict(Counter)
    for g in games:
        sans = g["sans"]
        for side_white in (True, False):
            if who is not None:
                name = (g.get("white") if side_white else g.get("black")) or ""
                if name.lower() != who.lower():
                    continue
            elif g.get("is_white") is not None and g["is_white"] != side_white:
                continue
            start = 0 if side_white else 1
            for i in range(start, min(len(sans), FP_MAX_PLY), 2):
                table[(side_white, " ".join(sans[:i]))][sans[i]] += 1
    return table


def otb_events(otb_games: list[dict]) -> list[tuple]:
    ev = []
    for g in otb_games:
        sans, w = g["sans"], g["is_white"]
        start = 0 if w else 1
        for i in range(start, min(len(sans), FP_MAX_PLY), 2):
            ev.append((w, " ".join(sans[:i]), sans[i]))
    return ev


def score_candidates(otb_games: list[dict], cand_tables: dict[str, dict]) -> dict[str, dict]:
    events = otb_events(otb_games)
    pop: dict = defaultdict(Counter)
    for t in cand_tables.values():
        for k, c in t.items():
            pop[k].update(c)
    out = {}
    for name, t in cand_tables.items():
        lifts, weights, raw, covered, samples = [], [], [], 0, []
        for color, path, mv in events:
            c = t.get((color, path))
            n = sum(c.values()) if c else 0
            if n < FP_MIN_N:
                continue
            covered += 1
            pc = pop[(color, path)]
            p_pop = pc[mv] / sum(pc.values()) if pc else 0.0
            p_acc = c[mv] / n
            w = 1.0 - p_pop + 0.05
            lifts.append((p_acc - p_pop) * w)
            weights.append(w)
            raw.append(p_acc)
            if p_acc >= 0.5 and p_pop <= 0.35 and not any(x.startswith(f"{'W' if color else 'S'}: {path + ' ' if path else ''}{mv} (") for x in samples):
                samples.append(f"{'W' if color else 'S'}: {path + ' ' if path else ''}{mv} ({c[mv]}/{n})")
        out[name] = {
            "events": len(events), "covered": covered,
            "lift": round(sum(lifts) / sum(weights), 4) if weights else 0.0,
            "agreement": round(sum(raw) / len(raw), 3) if raw else 0.0,
            "distinctive": samples[:8],
        }
    return out


def repertoire_profile(games: list[dict], who: str | None = None) -> dict:
    """Kurzprofil: erste Zuege mit Weiss, Antworten mit Schwarz auf 1.e4 / 1.d4 (fuer Belege/Anzeige)."""
    t = node_table(games, who)
    def dist(key):
        c = t.get(key, Counter())
        n = sum(c.values())
        return n, [(m, k) for m, k in c.most_common(4)]
    return {"white_first": dist((True, "")), "black_vs_e4": dist((False, "e4")),
            "black_vs_d4": dist((False, "d4")), "white_vs_c5": dist((True, "e4 c5"))}
