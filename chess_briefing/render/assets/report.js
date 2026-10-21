/* chess-opponent-briefing - Interaktion (ohne Abhaengigkeiten).
   Daten: <script id="cb-data" type="application/json">. Figuren: <symbol id="p-wK"> usw. */
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("cb-data").textContent);
  var NS = "http://www.w3.org/2000/svg";
  var FILES = "abcdefgh";

  // ------------------------------------------------------------ Brett
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function sqXY(sq, flip) {
    var f = FILES.indexOf(sq[0]), r = parseInt(sq[1], 10) - 1;
    return flip ? [7 - f, r] : [f, 7 - r];
  }
  function drawBoard(host, fen, opt) {
    opt = opt || {};
    var flip = !!opt.flip;
    host.innerHTML = "";
    var svg = el("svg", { viewBox: "0 0 80 80", role: "img", "aria-label": opt.label || "Schachbrett" }, host);
    for (var y = 0; y < 8; y++) for (var x = 0; x < 8; x++) {
      el("rect", { x: x * 10, y: y * 10, width: 10, height: 10,
        fill: (x + y) % 2 ? "var(--sq-dark)" : "var(--sq-light)" }, svg);
    }
    (opt.highlight || []).forEach(function (sq) {
      var p = sqXY(sq, flip);
      el("rect", { x: p[0] * 10, y: p[1] * 10, width: 10, height: 10, fill: "var(--sq-last)" }, svg);
    });
    for (var i = 0; i < 8; i++) {
      var fl = flip ? FILES[7 - i] : FILES[i];
      var rk = flip ? i + 1 : 8 - i;
      el("text", { x: i * 10 + 9.2, y: 79.2, "text-anchor": "end", class: "coord",
        fill: i % 2 ? "var(--sq-light)" : "var(--sq-dark)" }, svg).textContent = fl;
      el("text", { x: 0.6, y: i * 10 + 2.8, class: "coord",
        fill: i % 2 ? "var(--sq-light)" : "var(--sq-dark)" }, svg).textContent = rk;
    }
    var rows = fen.split(" ")[0].split("/");
    rows.forEach(function (row, ri) {
      var fi = 0;
      for (var c = 0; c < row.length; c++) {
        var ch = row[c];
        if (/\d/.test(ch)) { fi += parseInt(ch, 10); continue; }
        var sq = FILES[fi] + (8 - ri), p = sqXY(sq, flip);
        var id = "p-" + (ch === ch.toUpperCase() ? "w" : "b") + ch.toUpperCase();
        var u = el("use", { x: p[0] * 10, y: p[1] * 10, width: 10, height: 10 }, svg);
        u.setAttribute("href", "#" + id);
        fi++;
      }
    });
    (opt.arrows || []).forEach(function (a) { arrow(svg, a[0], a[1], a[2], flip); });
    if (opt.marker && GLYPHS[opt.marker.lvl]) marker(svg, opt.marker.sq, opt.marker.lvl, flip);
    return svg;
  }
  var GLYPHS = { inaccuracy: "?!", mistake: "?", blunder: "??" };
  var GCOL = { inaccuracy: "#56b4e9", mistake: "#e69f00", blunder: "#df5353" };
  // Lichess-Stil: farbiger Kreis mit Glyphe oben rechts am Zielfeld
  function marker(svg, sq, lvl, flip) {
    var p = sqXY(sq, flip), cx = Math.min(p[0] * 10 + 9.2, 78.4), cy = Math.max(p[1] * 10 + 0.8, 1.6);
    var g = el("g", {}, svg);
    el("circle", { cx: cx, cy: cy, r: 2.6, fill: GCOL[lvl], stroke: "#fff", "stroke-width": 0.45 }, g);
    var t = el("text", { x: cx, y: cy + 0.95, "text-anchor": "middle", fill: "#fff",
      style: "font: 700 " + (lvl === "inaccuracy" || lvl === "blunder" ? 2.5 : 3) + "px var(--btb-font-sans)" }, g);
    t.textContent = GLYPHS[lvl];
  }
  function arrow(svg, from, to, color, flip) {
    var a = sqXY(from, flip), b = sqXY(to, flip);
    var x1 = a[0] * 10 + 5, y1 = a[1] * 10 + 5, x2 = b[0] * 10 + 5, y2 = b[1] * 10 + 5;
    var dx = x2 - x1, dy = y2 - y1, len = Math.sqrt(dx * dx + dy * dy) || 1;
    var ux = dx / len, uy = dy / len, hx = x2 - ux * 3.6, hy = y2 - uy * 3.6;
    var g = el("g", { opacity: 0.82 }, svg);
    el("line", { x1: x1, y1: y1, x2: hx, y2: hy, stroke: color, "stroke-width": 1.9, "stroke-linecap": "round" }, g);
    el("polygon", { points: [x2, y2, hx - uy * 2.3, hy + ux * 2.3, hx + uy * 2.3, hy - ux * 2.3].join(","), fill: color }, g);
  }
  // Grosse Engine-Bewertung neben/unter dem Brett (Weiss-Sicht)
  function setEval(box, cp, mate) {
    if (!box) return;
    if (cp == null && mate == null) { box.hidden = true; return; }
    box.hidden = false;
    box.querySelector(".cb-eval__value").textContent = mate != null ? (mate === 0 ? "Matt" : "#" + mate)
      : ((cp > 0 ? "+" : cp < 0 ? "−" : "") + Math.abs(cp / 100).toFixed(2));
  }
  function uciArrow(uci, color) { return uci ? [uci.slice(0, 2), uci.slice(2, 4), color] : null; }
  var C_BEST = "#0a8a50", C_PLAYED = "#d92d20", C_MOVE = "#236492";

  // statische Bretter (Schluesselstellungen, Eroeffnungsziele)
  document.querySelectorAll(".cb-board[data-fen]").forEach(function (b) {
    var arrows = [];
    if (b.dataset.played) arrows.push(uciArrow(b.dataset.played, C_PLAYED));
    if (b.dataset.best) arrows.push(uciArrow(b.dataset.best, C_BEST));
    var hl = b.dataset.last ? [b.dataset.last.slice(0, 2), b.dataset.last.slice(2, 4)] : [];
    var mk = b.dataset.lvl && b.dataset.played ? { sq: b.dataset.played.slice(2, 4), lvl: b.dataset.lvl } : null;
    drawBoard(b, b.dataset.fen, { flip: b.dataset.flip === "1", arrows: arrows.filter(Boolean), highlight: hl, label: b.dataset.label, marker: mk });
  });

  // ------------------------------------------------------------ Online-Account: Button klappt Link + Begruendung auf
  document.querySelectorAll("[data-acct-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var panel = document.getElementById(btn.getAttribute("aria-controls"));
      var open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      if (panel) panel.hidden = open;
    });
  });

  // ------------------------------------------------------------ Umschalter (Seg-Controls)
  document.querySelectorAll("[data-seg]").forEach(function (seg) {
    var group = seg.dataset.seg;
    seg.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        seg.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-selected", b === btn ? "true" : "false"); });
        document.querySelectorAll("[data-panel-group='" + group + "']").forEach(function (p) {
          p.hidden = p.dataset.panel !== btn.dataset.value;
        });
        if (group === "tree") renderTree(btn.dataset.value, "");
        if (group === "src") { treeState.src = btn.dataset.value; renderTree(treeState.color, ""); }
      });
    });
  });

  // ------------------------------------------------------------ Belege
  var FACTS = {};
  (D.facts || []).forEach(function (f) { FACTS[f.id] = f.text; });
  document.querySelectorAll(".cb-ev button").forEach(function (b) {
    b.title = FACTS[b.dataset.f] || "";
    b.addEventListener("click", function () {
      var host = b.closest(".cb-ev");
      var box = host.nextElementSibling && host.nextElementSibling.classList.contains("cb-evtext") ? host.nextElementSibling : null;
      var open = b.getAttribute("aria-expanded") === "true";
      host.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-expanded", "false"); });
      if (open) { if (box) box.remove(); return; }
      if (!box) { box = document.createElement("div"); box.className = "cb-evtext"; host.after(box); }
      box.textContent = b.dataset.f + " · " + (FACTS[b.dataset.f] || "");
      b.setAttribute("aria-expanded", "true");
    });
  });

  // ------------------------------------------------------------ Eroeffnungsbaum
  var treeState = { color: "white", path: "", src: "otb" };
  function TREES() { return treeState.src === "online" && D.trees_online ? D.trees_online : D.trees; }
  function numbered(path) {
    if (!path) return [];
    return path.split(" ").map(function (s, i) { return (i % 2 === 0 ? (i / 2 + 1) + "." : "") + s; });
  }
  function renderTree(color, path) {
    var host = document.getElementById("cb-explorer");
    if (!host) return;
    treeState.color = color; treeState.path = path;
    var nodes = TREES()[color].nodes, nd = nodes[path];
    if (!nd) return;
    var oppMoves = color === "white" ? 0 : 1;   // Halbzug-Paritaet, an der ER zieht
    drawBoard(host.querySelector(".cb-board"), nd.fen, { flip: color === "white", highlight: nd.uci ? [nd.uci.slice(0, 2), nd.uci.slice(2, 4)] : [],
      arrows: (nd.children || []).slice(0, 4).map(function (c) { var k = nodes[c.path]; return k && k.uci ? [k.uci.slice(0, 2), k.uci.slice(2, 4), C_MOVE] : null; }).filter(Boolean) });
    // Brotkrumen
    var crumbs = host.querySelector(".cb-crumbs");
    crumbs.innerHTML = "";
    var toks = path ? path.split(" ") : [];
    numbered(path).forEach(function (t, i) {
      var b = document.createElement("button");
      b.textContent = t;
      var p = toks.slice(0, i + 1).join(" ");
      if (i === toks.length - 1) b.className = "is-current";
      b.onclick = function () { renderTree(color, p); };
      crumbs.appendChild(b);
    });
    host.querySelector(".cb-opname").textContent = (nd.eco ? nd.eco + " · " : "") + (nd.name || (path ? "" : "Ausgangsstellung"));
    setEval(host.querySelector("[data-eval]"), nd.eval, null);
    var info = host.querySelector(".cb-nodeinfo");
    if (info) info.textContent = (treeState.src === "online" ? "Online · " : "") + nd.n + (nd.n === 1 ? " Partie" : " Partien") + (nd.score_pct != null ? " · er holte " + nd.score_pct + " %" : "") +
      (nd.eval != null ? " · Engine " + (nd.eval > 0 ? "+" : "") + (nd.eval / 100).toFixed(2) : "");
    var list = host.querySelector(".cb-moves");
    list.innerHTML = "";
    var ply = toks.length;
    var hisTurn = (ply % 2) === oppMoves;
    if (!nd.children || !nd.children.length) {
      list.innerHTML = '<p class="cb-note">Ende der erfassten Partien in dieser Linie.</p>';
    }
    (nd.children || []).forEach(function (c) {
      var k = nodes[c.path];
      var b = document.createElement("button");
      b.className = "cb-move";
      var mvNo = Math.floor(ply / 2) + 1, label = (ply % 2 === 0 ? mvNo + "." : mvNo + "…") + c.san;
      var pct = Math.round(100 * c.n / nd.n);
      b.innerHTML = '<span><b>' + label + '</b></span>' +
        '<span class="tb-bar"><i style="--w:' + pct + '%;--c:' + (color === "white" ? "var(--c-white)" : "var(--c-black)") + '"></i></span>' +
        '<span class="num">' + c.n + '×</span><span class="num">' + (k.score_pct != null ? k.score_pct + " %" : "–") + '</span>';
      b.title = (k.name || "") + (k.eval != null ? " · Engine " + (k.eval / 100).toFixed(2) : "");
      b.onclick = function () { renderTree(color, c.path); };
      list.appendChild(b);
    });
    var kids = nd.children && nd.children.length;
    host.querySelector("[data-t=first]").disabled = !path;
    host.querySelector("[data-t=prev]").disabled = !path;
    host.querySelector("[data-t=next]").disabled = !kids;
    host.querySelector("[data-t=last]").disabled = !kids;
  }
  var ex = document.getElementById("cb-explorer");
  if (ex) {
    // Navigation wie im Partie-Viewer: zurueck = ein Zug, vor = haeufigste Fortsetzung (erstes Kind)
    function treeBack() { var p = treeState.path; if (p) renderTree(treeState.color, p.indexOf(" ") > -1 ? p.slice(0, p.lastIndexOf(" ")) : ""); }
    function treeNext() { var nd = TREES()[treeState.color].nodes[treeState.path]; if (nd && nd.children && nd.children.length) renderTree(treeState.color, nd.children[0].path); }
    function treeEnd() {
      var nodes = TREES()[treeState.color].nodes, p = treeState.path, nd = nodes[p];
      while (nd && nd.children && nd.children.length && nodes[nd.children[0].path]) { p = nd.children[0].path; nd = nodes[p]; }
      renderTree(treeState.color, p);
    }
    ex.querySelector("[data-t=first]").onclick = function () { renderTree(treeState.color, ""); };
    ex.querySelector("[data-t=prev]").onclick = treeBack;
    ex.querySelector("[data-t=next]").onclick = treeNext;
    ex.querySelector("[data-t=last]").onclick = treeEnd;
    renderTree(ex.dataset.start || "white", "");
    document.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      if (/input|textarea|select/i.test(e.target.tagName)) return;
      if (navOwner() !== ex) return;
      if (e.key === "ArrowRight") treeNext(); else treeBack();
      e.preventDefault();
    });
  }
  // Wer bekommt die Pfeiltasten? Der Bereich (Baum oder Partie-Viewer) mit dem groesseren sichtbaren Anteil.
  function visShare(el) {
    if (!el) return 0;
    var r = el.getBoundingClientRect(), h = Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0);
    return h > 0 ? h : 0;
  }
  var lastNav = null;
  document.addEventListener("pointerdown", function (e) {
    var t = e.target.closest && e.target.closest("#cb-explorer, #cb-viewer");
    if (t) lastNav = t;
  }, true);
  function navOwner() {
    var t = document.getElementById("cb-explorer"), v = document.getElementById("cb-viewer");
    if (lastNav && visShare(lastNav) > 120) return lastNav;
    var a = visShare(t), b = visShare(v);
    if (!a && !b) return null;
    return a >= b ? t : v;
  }

  // ------------------------------------------------------------ Partie-Viewer
  var V = { id: null, ply: 0 };
  var viewer = document.getElementById("cb-viewer");
  function gameById(id) { for (var i = 0; i < D.games.length; i++) if (D.games[i].id === id) return D.games[i]; }
  function fenAfter(moves, ply) {
    if (ply === 0) return moves.length ? moves[0].fen : "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
    return ply < moves.length ? moves[ply].fen : (D.final_fen[V.id] || moves[moves.length - 1].fen);
  }
  var LVL = { inaccuracy: "Ungenauigkeit", mistake: "Fehler", blunder: "Patzer" };
  function showPly(ply) {
    var g = gameById(V.id), moves = D.viewer[V.id];
    V.ply = Math.max(0, Math.min(moves.length, ply));
    var m = V.ply > 0 ? moves[V.ply - 1] : null;
    drawBoard(viewer.querySelector(".cb-board"), fenAfter(moves, V.ply), {
      flip: !g.is_white, highlight: m ? [m.uci.slice(0, 2), m.uci.slice(2, 4)] : [],
      arrows: m && m.lvl && m.lvl !== "inaccuracy" && m.best_uci ? [uciArrow(m.best_uci, C_BEST)] : [],
      marker: m && m.lvl ? { sq: m.uci.slice(2, 4), lvl: m.lvl } : null
    });
    viewer.querySelectorAll(".mv").forEach(function (x) { x.classList.toggle("cur", +x.dataset.ply === V.ply); });
    var cur = viewer.querySelector(".mv.cur");
    if (cur) { var box = cur.parentElement; box.scrollTop = cur.offsetTop - box.offsetTop - box.clientHeight / 2; }
    setEval(viewer.querySelector("[data-eval]"), m ? m.cp : null, m ? m.mate : null);
    var info = viewer.querySelector(".cb-vinfo");
    if (!m) { info.innerHTML = ""; }
    else {
      var no = Math.floor((V.ply - 1) / 2) + 1, mover = (V.ply % 2 === 1) ? "." : "…";
      var txt = "<b>" + no + mover + m.san + "</b>";
      if (m.cp != null || m.mate != null) {
        var ev = m.mate != null ? (m.mate === 0 ? "Matt" : "#" + m.mate) : ((m.cp > 0 ? "+" : "") + (m.cp / 100).toFixed(2));
        txt += " · Engine " + ev + " · Erwartungswert für " + D.player_short + " " + Math.round(100 * m.exp) + " %";
      } else { txt += " · Online-Partie (ohne Engine-Analyse)"; }
      if (m.lvl) txt += " · <b style='color:var(--lvl-" + m.lvl + ")'>" + GLYPHS[m.lvl] + " " + LVL[m.lvl] + "</b>" + (m.best ? " – besser " + m.best : "");
      if (m.tip) txt += " · Kipp-Punkt";
      if (m.clk != null) txt += " · Uhr: " + Math.floor(m.clk / 60) + ":" + ("0" + Math.floor(m.clk % 60)).slice(-2);
      info.innerHTML = txt;
    }
    var mk = viewer.querySelector(".cb-graph .marker");
    if (mk) { var x = moves.length ? (V.ply / moves.length) * 600 : 0; mk.setAttribute("x1", x); mk.setAttribute("x2", x); }
  }
  function openGame(id) {
    V.id = id; V.ply = 0;
    var g = gameById(id), moves = D.viewer[id];
    viewer.querySelectorAll(".cb-gcard").forEach(function (c) { c.setAttribute("aria-pressed", c.dataset.id === id ? "true" : "false"); });
    var sel = viewer.querySelector("[data-gselect]"); if (sel) sel.value = id;
    var card = viewer.querySelector(".cb-gcard[data-id='" + id + "']");
    if (card && !card.hidden) { var grid = card.parentElement; grid.scrollTop = card.offsetTop - grid.offsetTop - 8; }
    viewer.querySelector(".cb-vhead").innerHTML = "<b>" + g.white + " – " + g.black + "</b>";
    var ml = viewer.querySelector(".cb-mlist"), html = "";
    moves.forEach(function (m, i) {
      if (i % 2 === 0) html += "<span class='no'>" + (i / 2 + 1) + ".</span>";
      html += "<span class='mv" + (m.own ? " own" : "") + (m.lvl ? " " + m.lvl : "") + "' data-ply='" + (i + 1) + "'>" + m.san +
        (m.lvl ? "<span class='gl'>" + GLYPHS[m.lvl] + "</span>" : "") + "</span> ";
    });
    ml.innerHTML = html;
    ml.querySelectorAll(".mv").forEach(function (x) { x.onclick = function () { showPly(+x.dataset.ply); }; });
    // Erwartungswert-Verlauf aus Sicht des Gegners
    var gh = viewer.querySelector(".cb-graph"), W = 600, H = 88, n = moves.length || 1;
    if (!moves.length || moves[0].exp == null) {
      gh.innerHTML = "<p class='cb-note'>Online-Partie: keine Engine-Kurve. " + (g.url ? "<a href='" + g.url + "' target='_blank' rel='noopener'>Auf der Plattform öffnen</a>" : "") + "</p>";
      showPly(0); return;
    }
    var pts = [[0, H / 2]].concat(moves.map(function (m, i) { return [(i + 1) / n * W, (1 - m.exp) * H]; }));
    var area = "M0," + H / 2 + " " + pts.map(function (p) { return "L" + p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ") + " L" + W + "," + H / 2 + " Z";
    var dots = moves.map(function (m, i) {
      if (!m.own || !m.lvl) return "";
      return "<circle cx='" + ((i + 1) / n * W).toFixed(1) + "' cy='" + ((1 - m.exp) * H).toFixed(1) + "' r='3.2' fill='var(--lvl-" + m.lvl + ")'/>";
    }).join("");
    gh.innerHTML = "<svg viewBox='0 0 " + W + " " + H + "' preserveAspectRatio='none'>" +
      "<rect width='" + W + "' height='" + H + "' fill='var(--muted)' rx='6'/>" +
      "<path d='" + area + "' fill='color-mix(in oklab, var(--primary) 22%, transparent)' stroke='var(--primary)' stroke-width='1.5' vector-effect='non-scaling-stroke'/>" +
      "<line x1='0' x2='" + W + "' y1='" + H / 2 + "' y2='" + H / 2 + "' stroke='var(--border-strong)' stroke-dasharray='2 4' vector-effect='non-scaling-stroke'/>" +
      dots + "<line class='marker' x1='0' x2='0' y1='0' y2='" + H + "' stroke='var(--foreground)' stroke-width='1' vector-effect='non-scaling-stroke'/></svg>";
    gh.querySelector("svg").onclick = function (e) {
      var r = this.getBoundingClientRect(); showPly(Math.round((e.clientX - r.left) / r.width * n));
    };
    showPly(0);
  }
  if (viewer) {
    viewer.querySelectorAll(".cb-gcard").forEach(function (c) { c.onclick = function () { openGame(c.dataset.id); }; });
    var F = { year: "all", col: "all", src: "otb" };
    function applyFilter() {
      var shown = 0;
      viewer.querySelectorAll(".cb-gcard").forEach(function (c) {
        var ok = (F.year === "all" || c.dataset.year === F.year) && (F.col === "all" || c.dataset.col === F.col) &&
          (!c.dataset.src || c.dataset.src === F.src);
        c.hidden = !ok; if (ok) shown++;
      });
      var total = viewer.querySelectorAll(".cb-gcard[data-src='" + F.src + "']").length;
      viewer.querySelector(".cb-gcount").textContent = shown + " von " + total + (F.src === "online" ? " Online-Partien (Stichprobe)" : " Turnierpartien");
      viewer.querySelectorAll(".cb-years .tb-chip").forEach(function (x) {
        var y = x.dataset.year, cnt = 0;
        viewer.querySelectorAll(".cb-gcard").forEach(function (c) { if ((y === "all" || c.dataset.year === y) && (!c.dataset.src || c.dataset.src === F.src)) cnt++; });
        x.hidden = cnt === 0 && y !== "all"; var bb = x.querySelector("b"); if (bb) bb.textContent = cnt;
      });
    }
    viewer.querySelectorAll(".cb-years .tb-chip").forEach(function (b) {
      b.onclick = function () {
        F.year = b.dataset.year;
        viewer.querySelectorAll(".cb-years .tb-chip").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        applyFilter();
      };
    });
    viewer.querySelectorAll("[data-colfilter] button").forEach(function (b) {
      b.onclick = function () {
        F.col = b.dataset.col;
        viewer.querySelectorAll("[data-colfilter] button").forEach(function (x) { x.setAttribute("aria-selected", x === b ? "true" : "false"); });
        applyFilter();
      };
    });
    viewer.querySelectorAll("[data-srcfilter] button").forEach(function (b) {
      b.onclick = function () {
        F.src = b.dataset.src; F.year = "all";
        viewer.querySelectorAll("[data-srcfilter] button").forEach(function (x) { x.setAttribute("aria-selected", x === b ? "true" : "false"); });
        viewer.querySelectorAll(".cb-years .tb-chip").forEach(function (x) { x.setAttribute("aria-pressed", x.dataset.year === "all" ? "true" : "false"); });
        applyFilter();
        var first = viewer.querySelector(".cb-gcard:not([hidden])"); if (first) openGame(first.dataset.id);
      };
    });
    viewer.querySelector("[data-gselect]").onchange = function () { openGame(this.value); };
    applyFilter();
    viewer.querySelector("[data-v=first]").onclick = function () { showPly(0); };
    viewer.querySelector("[data-v=prev]").onclick = function () { showPly(V.ply - 1); };
    viewer.querySelector("[data-v=next]").onclick = function () { showPly(V.ply + 1); };
    viewer.querySelector("[data-v=last]").onclick = function () { showPly(1e9); };
    viewer.querySelector("[data-v=err]").onclick = function () {
      var moves = D.viewer[V.id];
      for (var i = V.ply; i < moves.length; i++) if (moves[i].own && (moves[i].lvl === "mistake" || moves[i].lvl === "blunder")) { showPly(i + 1); return; }
    };
    document.addEventListener("keydown", function (e) {
      if (/input|textarea|select/i.test(e.target.tagName)) return;
      if (navOwner() !== viewer) return;
      if (e.key === "ArrowRight") { showPly(V.ply + 1); e.preventDefault(); }
      if (e.key === "ArrowLeft") { showPly(V.ply - 1); e.preventDefault(); }
    });
    document.querySelectorAll("[data-open-game]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault(); openGame(a.dataset.openGame); showPly(+a.dataset.ply || 0);
        viewer.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    var firstOtb = viewer.querySelector(".cb-gcard[data-src='otb']") || viewer.querySelector(".cb-gcard");
    openGame(firstOtb.dataset.id);
  }

  // ------------------------------------------------------------ Hell/Dunkel (Standard: hell)
  var root = document.documentElement;
  try { var saved = localStorage.getItem("cb-theme"); if (saved === "dark" || saved === "light") root.dataset.theme = saved; } catch (e) {}
  document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
      try { localStorage.setItem("cb-theme", root.dataset.theme); } catch (e) {}
    });
  });

  // ------------------------------------------------------------ Navigation aktiv markieren
  var links = document.querySelectorAll(".cb-nav a");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) links.forEach(function (l) { l.classList.toggle("is-active", l.getAttribute("href") === "#" + e.target.id); });
      });
    }, { rootMargin: "-30% 0px -65% 0px" });
    document.querySelectorAll(".cb-section[id]").forEach(function (s) { io.observe(s); });
  }
})();
