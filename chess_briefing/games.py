"""PGN -> einheitliche Partie-Datensaetze, Zusammenfuehren mehrerer Quellen, Dubletten."""
from __future__ import annotations

import hashlib
import io
import re

import chess
import chess.pgn

from .util import name_key, name_matches

_CLK = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")


def _date(h) -> str:
    d = (h.get("Date") or "").replace(".", "-")
    m = re.match(r"(\d{4})-(\d{2}|\?\?)-(\d{2}|\?\?)", d)
    if not m or m.group(1) == "????":
        return ""
    y, mo, da = m.groups()
    return y if mo == "??" else (f"{y}-{mo}" if da == "??" else f"{y}-{mo}-{da}")


def _int(v) -> int | None:
    try:
        i = int(str(v).strip())
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def parse_pgn(text: str, ident) -> list[dict]:
    out, stream = [], io.StringIO(text)
    while True:
        try:
            g = chess.pgn.read_game(stream)
        except Exception:
            continue
        if g is None:
            break
        h = g.headers
        wm = name_matches(h.get("White", ""), ident.last, ident.first)
        bm = name_matches(h.get("Black", ""), ident.last, ident.first)
        fid = str(ident.fide_id or "")
        if fid and h.get("WhiteFideId") == fid:
            wm = "strong"
        if fid and h.get("BlackFideId") == fid:
            bm = "strong"
        if not (wm or bm) or (wm and bm):
            continue
        rec = record(g, bool(wm))
        if rec:
            out.append(rec)
    return out


def record(g: chess.pgn.Game, is_white: bool) -> dict | None:
    """Partie-Datensatz aus Sicht einer Seite (is_white); None bei illegalen Zuegen oder < 2 Halbzuegen."""
    h = g.headers
    board = g.board()
    sans, ucis, clocks = [], [], []
    for node in g.mainline():
        mv = node.move
        if mv not in board.legal_moves:
            return None
        sans.append(board.san(mv))
        ucis.append(mv.uci())
        board.push(mv)
        m = _CLK.search(node.comment or "")
        clocks.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None)
    if len(sans) < 2:
        return None
    res = h.get("Result", "*")
    if res == "*" and board.is_checkmate():
        res = "0-1" if board.turn == chess.WHITE else "1-0"
    score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(res)
    rec = {
        "white": h.get("White", ""), "black": h.get("Black", ""), "result": res,
        "date": _date(h), "event": h.get("Event", ""), "site": h.get("Site", ""),
        "round": h.get("Round", ""),
        "white_elo": _int(h.get("WhiteElo")), "black_elo": _int(h.get("BlackElo")),
        "eco": h.get("ECO", ""), "opening_header": h.get("Opening", ""),
        "time_control": h.get("TimeControl", ""),
        "sans": sans, "ucis": ucis,
        "clocks": clocks if any(c is not None for c in clocks) else [],
        "sources": [h.get("Source", "PGN")],
        "source_urls": [u for u in [h.get("SourceURL") or h.get("GameURL")] if u and u.startswith("http")],
        "is_white": is_white,
        "player_score": None if score is None else (score if is_white else 1 - score),
    }
    rec["opponent"] = rec["black"] if is_white else rec["white"]
    rec["opponent_elo"] = rec["black_elo"] if is_white else rec["white_elo"]
    rec["player_elo"] = rec["white_elo"] if is_white else rec["black_elo"]
    return rec


def _last_name(n: str) -> str:
    base = n.split(",")[0] if "," in n else (n.split()[-1] if n.split() else n)
    return name_key(base)


def _key(g: dict) -> tuple:
    return (g["date"][:7], _last_name(g["opponent"]), g["is_white"], tuple(g["sans"][:16]))


def merge(games: list[dict]) -> list[dict]:
    """Dubletten zusammenfuehren: gleicher Monat, gleicher Gegner-Nachname, gleiche Farbe, gleiche ersten 16 Halbzuege."""
    merged: dict[tuple, dict] = {}
    for g in games:
        k = _key(g)
        if k not in merged:
            merged[k] = g
            continue
        a = merged[k]
        keep, other = (a, g) if len(a["sans"]) >= len(g["sans"]) else (g, a)
        if not keep["clocks"] and other["clocks"] and len(other["sans"]) == len(keep["sans"]):
            keep["clocks"] = other["clocks"]
        if keep["event"].startswith("Round") and other["event"] and not other["event"].startswith("Round"):
            keep["event"], keep["round"] = other["event"], other["round"]
        for f in ("white_elo", "black_elo", "eco", "opening_header", "time_control", "date"):
            if not keep.get(f) and other.get(f):
                keep[f] = other[f]
        if keep["result"] == "*" and other["result"] != "*":
            keep["result"], keep["player_score"] = other["result"], other["player_score"]
        keep["sources"] = sorted(set(keep["sources"]) | set(other["sources"]))
        keep["source_urls"] = sorted(set(keep["source_urls"]) | set(other["source_urls"]))
        keep["opponent_elo"] = keep["black_elo"] if keep["is_white"] else keep["white_elo"]
        keep["player_elo"] = keep["white_elo"] if keep["is_white"] else keep["black_elo"]
        merged[k] = keep
    out = sorted(merged.values(), key=lambda g: (g["date"], g["round"]), reverse=True)
    for g in out:
        g["id"] = hashlib.sha1(("|".join(g["ucis"]) + g["date"] + g["opponent"]).encode()).hexdigest()[:10]
    return out


def to_pgn(g: dict) -> str:
    game = chess.pgn.Game()
    for k, v in (("Event", g["event"]), ("Site", g["site"]), ("Date", (g["date"] or "????").replace("-", ".")),
                 ("Round", g["round"] or "?"), ("White", g["white"]), ("Black", g["black"]),
                 ("Result", g["result"])):
        game.headers[k] = v
    for k, v in (("WhiteElo", g["white_elo"]), ("BlackElo", g["black_elo"]), ("ECO", g["eco"]),
                 ("TimeControl", g["time_control"])):
        if v:
            game.headers[k] = str(v)
    game.headers["Source"] = "; ".join(g["sources"])
    node = game
    for i, u in enumerate(g["ucis"]):
        node = node.add_variation(chess.Move.from_uci(u))
        if g["clocks"] and i < len(g["clocks"]) and g["clocks"][i] is not None:
            c = int(g["clocks"][i])
            node.comment = f"[%clk {c // 3600}:{c % 3600 // 60:02d}:{c % 60:02d}]"
    return str(game)
