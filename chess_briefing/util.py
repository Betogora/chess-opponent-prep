"""Kleine Helfer: HTTP mit Cache, Namen, Slugs, JSON."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import unicodedata
from pathlib import Path

import requests

from . import __version__
from .config import CACHE_DIR

# Ehrliche App-Kennung (kein Browser-User-Agent). Lichess, Chess.com und Chessable lehnen den Standard-User-Agent
# von python-requests ab, akzeptieren aber diese Kennung. Bot-Pruefungen (ChessBase) werden nicht umgangen.
UA = f"chess-opponent-prep/{__version__} (personal opening-preparation tool)"

_local = threading.local()          # je Thread eine Session und ein Log-Kennzeichen (parallele Gegner)
_gates: dict[str, threading.BoundedSemaphore] = {}
_gates_lock = threading.Lock()
# Gleichzeitige Anfragen je Host: Lichess erlaubt nur eine (sonst 429), Chess.com vertraegt wenige parallele.
HOST_PARALLEL = {"lichess.org": 1, "api.chess.com": 4}


def session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "de,en;q=0.8"})
        _local.session = s
    return s


def host_gate(url: str) -> threading.BoundedSemaphore:
    """Semaphore je Host, damit parallele Laeufe die Ratenlimits nicht reissen."""
    host = url.split("/")[2] if "//" in url else url
    with _gates_lock:
        g = _gates.get(host)
        if g is None:
            g = _gates[host] = threading.BoundedSemaphore(HOST_PARALLEL.get(host, 4))
        return g


def fetch(url: str, *, ttl_hours: float = 24, binary: bool = False, method: str = "GET",
          headers: dict | None = None, cache: bool = True, timeout: int = 40):
    """GET/POST mit Datei-Cache. Gibt Text (oder bytes) zurueck, None bei Fehler."""
    key = hashlib.sha1(f"{method} {url}".encode()).hexdigest()[:20]
    path = CACHE_DIR / "http" / key
    if cache and path.exists() and (time.time() - path.stat().st_mtime) < ttl_hours * 3600:
        data = path.read_bytes()
        return data if binary else _decode(data)
    for attempt in range(2):
        try:
            with host_gate(url):
                r = session().request(method, url, headers=headers or {}, timeout=timeout)
        except requests.RequestException:
            return None
        if r.status_code == 429 and attempt == 0:      # Ratenlimit (z. B. Lichess): einmal warten, dann wiederholen
            wait = int(r.headers.get("Retry-After", "60") or 60) + 5
            log(f"  Ratenlimit {url.split('/')[2]}, warte {wait} s")
            time.sleep(min(wait, 120))
            continue
        break
    if r.status_code != 200:
        return None
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    return r.content if binary else _decode(r.content)


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def strip_accents(s: str) -> str:
    s = s.replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


TITLES = {"dr", "prof", "gm", "im", "fm", "cm", "wgm", "wim", "wfm", "wcm", "dipl", "ing"}
_UMLAUT = {"ae": "a", "oe": "o", "ue": "u"}


def name_tokens(name: str) -> list[str]:
    """'Muster, Max' / 'Max Muster' / 'Muster,M' -> sortierte, normalisierte Tokens."""
    s = strip_accents(name or "").lower()
    toks = [t for t in re.split(r"[\s,;.\-_]+", s) if t and t not in TITLES]
    out = []
    for t in toks:
        for k, v in _UMLAUT.items():   # Loessing == Lössing
            t = t.replace(k, v)
        out.append(t)
    return sorted(set(out))


def name_key(name: str) -> str:
    return " ".join(name_tokens(name))


def name_matches(candidate: str, last: str, first: str) -> str:
    """'strong' (Nachname + Vorname), 'initial' (Nachname + Initiale), '' (kein Treffer)."""
    toks = name_tokens(candidate)
    lt, ft = name_tokens(last), name_tokens(first)
    if not lt or not all(t in toks for t in lt):
        return ""
    rest = [t for t in toks if t not in lt]
    if ft and all(t in rest for t in ft):
        return "strong"
    if ft and rest and any(len(r) == 1 and r == ft[0][0] for r in rest):
        return "initial"
    return ""


def slugify(last: str, first: str) -> str:
    s = strip_accents(f"{last}_{first}").lower()
    return re.sub(r"[^a-z0-9_]+", "", s.replace(" ", "_").replace("-", "_"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def set_log_tag(tag: str | None) -> None:
    """Kennzeichen fuer alle Logzeilen dieses Threads (z. B. "1" bei mehreren Gegnern parallel)."""
    _local.tag = tag


def log_tag() -> str | None:
    return getattr(_local, "tag", None)


def log(msg: str) -> None:
    tag = log_tag()
    if tag:
        msg = "\n".join(f"[{tag}] {line}" if line else line for line in msg.split("\n"))
    print(msg, flush=True)
