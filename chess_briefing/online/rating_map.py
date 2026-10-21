"""Online-Wertung -> erwartete FIDE-Standard-Elo, und DWZ -> Elo. Nichtlinear, je Plattform und Bedenkzeit.

Stuetzpunkte (Stand Recherche Okt. 2026; alle Werte auf FIDE-Niveau nach der Anhebung vom 1.3.2024,
neu = alt + 0,4 * (2000 - alt) unter 2000, Untergrenze 1400):
- ChessGoals Rating Comparison (Umfrage, Juli 2026; Lichess-Blitz n=1935, Rapid n=1066, Classical n=240,
  Chess.com-Blitz-FIDE-Pool n=1923) – Hauptquelle, ca. 75 % Gewicht.
- Lichess Blitz: Ferdy/TalkChess 2021 (FIDE = 181 + 0,83458 * Blitz, n=5727, RMSE 159), angehoben.
- Chess.com: GagarinGambit 2013 (Blitz 483 + 0,769x, Standard 594 + 0,702x, je +-195), angehoben, ca. 25 %.
- DWZ -> Elo: Grenke-Teilnehmer (n=1718, Lichess-Forum ca. 2025): ab 2000 DWZ ~ Elo, 1400–2000 Elo ~ DWZ + 100,
  darunter Elo ~ DWZ + 300..400 (Untergrenze 1400).
Werte unten in den Tabellen ohne direkte Quelle sind aus den Verhaeltnissen abgeleitet (Lichess-Rapid/Classical
unter 1800, Chess.com unter 1200). Folgen: Lichess ist unten deutlich hoeher als Chess.com; im Blitz kreuzen sich
die Kurven bei ~2230 (darueber ist Chess.com hoeher), im Rapid nicht.

sigma = Streuung eines einzelnen Spielers um die Kurve (Elo-Punkte), belegt bzw. konservativ geschaetzt.
"""
from __future__ import annotations

# (Online-Wertung, erwartete FIDE-Standard-Elo)
CURVES: dict[tuple[str, str], list[tuple[int, int]]] = {
    ("lichess", "blitz"): [(1000, 1400), (1200, 1510), (1400, 1610), (1600, 1695), (1800, 1790), (2000, 1910),
                           (2200, 2040), (2400, 2205), (2600, 2370), (2800, 2530)],
    ("lichess", "rapid"): [(1000, 1400), (1200, 1450), (1400, 1520), (1600, 1615), (1800, 1700), (2000, 1815),
                           (2200, 2005), (2400, 2245), (2600, 2470)],
    ("lichess", "classical"): [(1000, 1400), (1200, 1450), (1400, 1520), (1600, 1600), (1800, 1720), (2000, 1855),
                               (2200, 2035), (2400, 2290)],
    ("chesscom", "blitz"): [(1000, 1550), (1200, 1665), (1400, 1715), (1600, 1790), (1800, 1880), (2000, 1980),
                            (2200, 2100), (2400, 2225), (2600, 2345), (2800, 2400)],
    ("chesscom", "rapid"): [(1000, 1580), (1200, 1660), (1400, 1705), (1600, 1775), (1800, 1865), (2000, 1985),
                            (2200, 2155), (2400, 2360)],
}
SIGMA = {("lichess", "blitz"): 150, ("lichess", "rapid"): 200, ("lichess", "classical"): 200,
         ("chesscom", "blitz"): 160, ("chesscom", "rapid"): 190}

DWZ_TO_ELO = [(1000, 1440), (1200, 1520), (1400, 1635), (1600, 1745), (1800, 1855), (2000, 2000), (2200, 2200),
              (2400, 2385), (2600, 2570)]

UPWARD = 1.3        # Online staerker als am Brett ist haeufiger (inaktiv am Brett, Jugendliche) -> breiter
OK_Z = 1.0          # |z| <= 1: plausibel
BAD_Z = 2.0         # |z| > 2: unplausibel
MIN_GAMES = 50      # weniger Partien oder vorlaeufige Wertung (Lichess "?") -> nicht verwenden


def _interp(pts: list[tuple[int, int]], x: float) -> float:
    """Stueckweise linear; ausserhalb mit der Steigung des Randabschnitts fortgesetzt, Elo nie unter 1400."""
    if x <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    elif x >= pts[-1][0]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
    else:
        i = next(i for i in range(1, len(pts)) if x <= pts[i][0])
        (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    return max(1400.0, y0 + (y1 - y0) * (x - x0) / (x1 - x0))


def online_to_elo(platform: str, speed: str, rating: float) -> tuple[float, float] | None:
    """Erwartete FIDE-Standard-Elo und sigma, oder None fuer unbekannte Kombination (z. B. Chess.com Daily)."""
    key = (platform, speed)
    if key not in CURVES:
        return None
    return _interp(CURVES[key], rating), SIGMA[key]


def dwz_to_elo(dwz: float) -> tuple[float, float]:
    """DWZ -> Elo-Niveau und sigma (Grenke-Korrelation: r=0,96 ueber 2000, 0,84 darunter, 0,45 unter 1400)."""
    sigma = 70 if dwz >= 2000 else 110 if dwz >= 1400 else 175
    return _interp(DWZ_TO_ELO, dwz), sigma


def reference(ident) -> dict | None:
    """Turnierwertung auf Elo-Niveau: FIDE-Standard-Elo, sonst DWZ umgerechnet."""
    elo = (ident.elo or {}).get("standard")
    if elo:
        return {"kind": "Elo", "value": elo, "elo": float(elo), "sigma": 0.0}
    dwz = (ident.dsb or {}).get("dwz")
    if dwz:
        e, s = dwz_to_elo(dwz)
        return {"kind": "DWZ", "value": dwz, "elo": round(e), "sigma": s}
    return None


def check(platform: str, ratings: dict, ref: dict | None) -> dict | None:
    """Vergleicht verwertbare Online-Wertungen ({speed: rating}) mit der Turnierwertung.
    Erwartung = nach 1/sigma^2 gewichtetes Mittel der Bedenkzeiten; sigma = kleinstes Einzel-sigma (die Werte
    eines Accounts sind korreliert) kombiniert mit der Unsicherheit der Referenz. z > 0 = online staerker."""
    if not ref:
        return None
    est = {s: online_to_elo(platform, s, r) for s, r in ratings.items() if r}
    est = {s: v for s, v in est.items() if v}
    if not est:
        return None
    w = {s: 1 / v[1] ** 2 for s, v in est.items()}
    expected = sum(est[s][0] * w[s] for s in est) / sum(w.values())
    sigma = (min(v[1] for v in est.values()) ** 2 + ref["sigma"] ** 2) ** 0.5
    diff = expected - ref["elo"]
    z = diff / (sigma * (UPWARD if diff > 0 else 1.0))
    verdict = "plausibel" if abs(z) <= OK_Z else "unplausibel" if abs(z) > BAD_Z else "möglich"
    return {"expected_elo": round(expected), "per_speed": {s: round(v[0]) for s, v in est.items()},
            "ref_kind": ref["kind"], "ref_value": ref["value"], "ref_elo": round(ref["elo"]),
            "sigma": round(sigma), "z": round(z, 2), "verdict": verdict}
