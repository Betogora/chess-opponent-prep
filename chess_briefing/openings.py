"""Eroeffnungsnamen (Lichess chess-openings, CC0) und Eroeffnungsbaum aus Sicht des Gegners."""
from __future__ import annotations

import csv
from collections import defaultdict
from functools import lru_cache

import chess

from . import config


@lru_cache(maxsize=1)
def _book() -> dict[str, tuple[str, str, int]]:
    """EPD -> (ECO, Name, Halbzuege). Bei mehreren Namen fuer dieselbe Stellung gewinnt der kuerzere Pfad."""
    book = {}
    for f in sorted(config.DATA_DIR.glob("eco_*.tsv")):
        with f.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                b = chess.Board()
                ply = 0
                try:
                    for tok in row["pgn"].split():
                        if tok.endswith("."):
                            continue
                        b.push_san(tok)
                        ply += 1
                except ValueError:
                    continue
                epd = b.epd()
                if epd not in book or ply < book[epd][2]:
                    book[epd] = (row["eco"], row["name"], ply)
    return book


def name_line(ucis: list[str], max_ply: int = 30) -> tuple[str, str, int]:
    """Tiefster Buchtreffer der ersten max_ply Halbzuege -> (ECO, Name, Halbzug des Treffers)."""
    book = _book()
    b = chess.Board()
    best = ("", "", 0)
    for i, u in enumerate(ucis[:max_ply]):
        b.push(chess.Move.from_uci(u))
        hit = book.get(b.epd())
        if hit:
            best = (hit[0], hit[1], i + 1)
    return best


def family(name: str) -> str:
    return name.split(":")[0].strip() if name else "Unbekannt"


def label_for_player(g: dict) -> str:
    """Kurzlabel aus Sicht des Gegners: 'Mit Weiss: 1.e4' / 'gegen 1.d4: ...Nf6 2.c4 g6'"""
    s = g["sans"]
    if g["is_white"]:
        return f"1.{s[0]}"
    return f"gegen 1.{s[0]}: …{s[1]}" if len(s) > 1 else f"gegen 1.{s[0]}"


def build_tree(games: list[dict], color_white: bool, analysis: dict, max_ply: int | None = None,
               keep_games: bool = True, min_n: int = 1, keep_ids: set[str] | frozenset = frozenset()) -> dict:
    """Baum der Partien, in denen der Gegner die Farbe color_white hatte.

    Knoten-Schluessel = Zugfolge (SAN mit Leerzeichen). Je Knoten: Anzahl, Score des Gegners,
    Bewertung (Weiss-Sicht, cp) aus der Engine, Kinder, Eroeffnungsname, Partie-IDs (keep_games).
    min_n > 1 entfernt seltene Knoten (fuer den Online-Vollbaum aus Tausenden Partien); Stellungen aus Partien
    in keep_ids (z. B. die analysierte Stichprobe) bleiben trotzdem erhalten.
    """
    max_ply = max_ply or config.TREE_MAX_PLY
    nodes: dict[str, dict] = {}
    book = _book()

    def node(path: str, fen: str, ply: int) -> dict:
        if path not in nodes:
            nodes[path] = {"path": path, "fen": fen, "ply": ply, "n": 0, "score": 0.0, "w": 0, "d": 0, "l": 0,
                           "evals": [], "children": defaultdict(int), "games": [], "eco": "", "name": ""}
        return nodes[path]

    for g in games:
        if g["is_white"] != color_white:
            continue
        pos = analysis.get(g["id"])
        b = chess.Board()
        path = ""
        n = node(path, b.fen(), 0)
        _count(n, g, pos, 0)
        for i, (san, uci) in enumerate(zip(g["sans"][:max_ply], g["ucis"][:max_ply])):
            b.push(chess.Move.from_uci(uci))
            parent = n
            path = (path + " " + san).strip()
            parent["children"][path] += 1
            n = node(path, b.fen(), i + 1)
            n["uci"] = uci
            hit = book.get(b.epd())
            if hit:
                n["eco"], n["name"] = hit[0], hit[1]
            _count(n, g, pos, i + 1)

    if min_n > 1:
        nodes = {p: nd for p, nd in nodes.items() if nd["n"] >= min_n or any(i in keep_ids for i in nd["games"])}
        for nd in nodes.values():
            nd["children"] = {c: k for c, k in nd["children"].items() if c in nodes}
    if not keep_games:
        for nd in nodes.values():
            del nd["games"]
    # Namen nach unten vererben, Aufbereitung
    for path in sorted(nodes, key=lambda p: nodes[p]["ply"]):
        nd = nodes[path]
        if not nd["name"] and nd["ply"] > 0:
            parent = nodes.get(path.rsplit(" ", 1)[0] if " " in path else "")
            if parent:
                nd["eco"], nd["name"] = parent["eco"], parent["name"]
        nd["eval"] = round(sum(nd["evals"]) / len(nd["evals"])) if nd["evals"] else None
        # Score nur ueber Partien mit Ergebnis (manuelle Importe ohne Ergebnis: Result "*")
        scored = nd["w"] + nd["d"] + nd["l"]
        nd["score_pct"] = round(100 * nd["score"] / scored) if scored else None
        nd["children"] = [{"path": c, "san": c.rsplit(" ", 1)[-1], "n": k}
                          for c, k in sorted(nd["children"].items(), key=lambda x: -x[1])]
        del nd["evals"]
    return {"color": "white" if color_white else "black", "nodes": nodes}


def _count(n: dict, g: dict, pos: list | None, ply: int) -> None:
    n["n"] += 1
    sc = g.get("player_score")
    if sc is not None:
        n["score"] += sc
        n["w" if sc == 1 else "d" if sc == 0.5 else "l"] += 1
    n["games"].append(g["id"])
    if pos and ply < len(pos) and pos[ply]["mate"] is None:
        n["evals"].append(max(-1000, min(1000, pos[ply]["cp"])))


def main_lines(tree: dict, min_games: int = 1, max_lines: int = 8) -> list[dict]:
    """Haeufigste Linien: von der Wurzel immer dem haeufigsten Kind folgen, an jeder Verzweigung neue Linie."""
    nodes = tree["nodes"]
    lines = []

    def walk(path: str, depth_guard: int = 0):
        nd = nodes[path]
        kids = [c for c in nd["children"] if c["n"] >= min_games]
        if not kids or depth_guard > 40:
            if nd["ply"] >= 2:
                lines.append(nd)
            return
        for c in kids:
            walk(c["path"], depth_guard + 1)

    walk("")
    lines.sort(key=lambda nd: (-nd["n"], nd["path"]))
    return lines[:max_lines]
