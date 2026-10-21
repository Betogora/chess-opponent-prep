"""Lokaler PGN-Empfaenger fuer den Browser-Schritt (ChessBase) – ohne Download-Dialog und ohne Agenten-Kontext.

Ablauf: `python briefing.py receive <slug>` startet den Empfaenger. Der Agent oeffnet im Browser die ChessBase-
Profilseite und fuehrt dort receiver_js() aus: das Skript laedt die PGN wie ein normaler Seitenbesucher (keine
Umgehung der Bot-Pruefung) und schickt sie als Formular (POST) an http://127.0.0.1:<port>/upload/chessbase_<slug>.pgn.
Das ist ein gewoehnlicher Seitenwechsel: kein Download-Dialog, kein Popup, kein Text durch den Agenten-Kontext.
Der Empfaenger nimmt nur genau diese Datei an (nur von 127.0.0.1), schreibt sie nach output/players/<slug>/inbox/ und
beendet sich danach (oder nach der Zeitgrenze).

Warum kein fetch()/iframe: Browser sperren Anfragen einer https-Seite an lokale Adressen (Private Network Access);
der eingebettete Browser der Claude-App oeffnet window.open() im selben Tab. Formular-Navigationen sind davon frei.
"""
from __future__ import annotations

import http.server
import json
import threading
import urllib.parse
from pathlib import Path

from . import config
from .util import log

PORT = 8767
DONE_PAGE = ("<!doctype html><meta charset='utf-8'><title>PGN übernommen</title>"
             "<body style='font:16px sans-serif;padding:2rem'><h1>PGN übernommen</h1><p>{n} Partien gespeichert unter "
             "<code>{path}</code>. Dieses Fenster wird nicht mehr gebraucht.</p></body>")


def receiver_js(ident, port: int = PORT) -> str:
    """In der ChessBase-Profilseite ausfuehren: laedt die PGN und schickt sie per Formular an den Empfaenger."""
    from .sources.chessbase import pgn_path_on_site
    name = f"chessbase_{ident.slug}.pgn"
    return ("(async () => { const pgn = await (await fetch('" + pgn_path_on_site(ident) + "')).text(); "
            "const f = document.createElement('form'); f.method = 'POST'; "
            f"f.action = 'http://127.0.0.1:{port}/upload/{name}'; "
            "f.enctype = 'application/x-www-form-urlencoded'; "
            "const t = document.createElement('textarea'); t.name = 'pgn'; t.value = pgn; f.appendChild(t); "
            "f.style.display = 'none'; document.body.appendChild(f); setTimeout(() => f.submit(), 0); "
            "return pgn.split('[Event ').length - 1; })()")


def serve(slug: str, timeout: float = 180, port: int = PORT) -> Path | None:
    """Wartet auf genau eine Datei chessbase_<slug>.pgn und schreibt sie nach output/players/<slug>/inbox/."""
    target = config.PLAYERS_DIR / slug / "inbox" / f"chessbase_{slug}.pgn"
    got: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code: int, html: str):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def do_GET(self):
            self._reply(200, "<!doctype html><meta charset='utf-8'><p>PGN-Empfänger bereit.</p>")

        def do_POST(self):
            name = urllib.parse.unquote(self.path.rsplit("/", 1)[-1])
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(min(n, 50_000_000))
            if self.client_address[0] != "127.0.0.1" or name != target.name:
                return self._reply(403, "falsche Datei")
            ctype = self.headers.get("Content-Type", "")
            body = (urllib.parse.parse_qs(raw.decode("utf-8", "replace")).get("pgn", [""])[0]
                    if "x-www-form-urlencoded" in ctype else raw.decode("utf-8", "replace"))
            if "[Event " not in body:
                return self._reply(400, "keine PGN")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(body.replace("\r\n", "\n"), encoding="utf-8")
            tmp.replace(target)
            got["path"], got["games"] = target, body.count("[Event ")
            self._reply(200, DONE_PAGE.format(n=got["games"], path=target))
            threading.Thread(target=srv.shutdown, daemon=True).start()

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    timer = threading.Timer(timeout, srv.shutdown)
    timer.start()
    try:
        srv.serve_forever()
    finally:
        timer.cancel()
        srv.server_close()
    if got:
        log(f"   ChessBase-PGN empfangen: {got['path']} ({got['games']} Partien)")
    return got.get("path")


def run(inp: str, timeout: float = 180, fide_id=None) -> int:
    """CLI: Empfaenger fuer einen Spieler starten und den Befehl fuer die Browser-Seite ausgeben."""
    from .identify import resolve
    ident = resolve(inp, fide_id=fide_id)
    log(f"   Empfänger bereit für {ident.display}: {ident.chessbase_url} öffnen und dort ausführen:\n     {receiver_js(ident)}")
    p = serve(ident.slug, timeout)
    print(json.dumps({"ok": bool(p), "path": str(p) if p else None}, ensure_ascii=False), flush=True)
    return 0 if p else 1
