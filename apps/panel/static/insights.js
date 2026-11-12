// Offerowl's panel, the Insights view: the person's whole search on one screen. Where the applications stand (a funnel,
// the weeks they moved in, how ready each open one is), what the evidence holds (the career's spans, facts by kind and
// by company), and where the postings ask for more than the evidence shows (every requirement line of every posting,
// sorted into areas: met, in part, not met). The numbers come from GET /api/v1/insights, the same for a program.
// Every figure keeps its words beside it (a legend with counts, a label on the mark) and answers a hover with the
// exact numbers; colour carries one meaning each: a stage's colour, or how well a requirement is met.
"use strict";                                                                       // catches undeclared names and silent writes early

const SVGN = "http://www.w3.org/2000/svg";                                          // the figures are SVG
function sv(tag, attrs, ...kids) {                                                  // an SVG element with attributes and children
  const el = document.createElementNS(SVGN, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined && v !== false) el.setAttribute(k, String(v));
  for (const kid of kids.flat(3)) if (kid !== null && kid !== undefined && kid !== false) el.append(typeof kid === "string" ? document.createTextNode(kid) : kid);
  return el;
}
const MET = { strong: "var(--met-strong)", weak: "var(--met-weak)", none: "var(--met-none)" };   // met, in part, not met: two poles and a neutral middle
const MET_WORD = { strong: "Met", weak: "In part", none: "Not met" };
const MET_SOLO = { strong: "var(--met-strong)", weak: "var(--ink-3)", none: "var(--met-none)" };   // a bar standing alone: "in part" darker than in a stack, so it still reads              // their words, in every legend
const metTone = (v) => v === null || v === undefined ? "none" : v >= 60 ? "strong" : v >= 35 ? "weak" : "none";   // a share met, read as the three (the fit's own thresholds)
const RESULT_COLOR = { offer: "var(--met-strong)", rejected: "var(--met-none)", closed: "var(--ink-3)", none: "var(--line-2, var(--line))" };   // how the ended ones ended
const RESULT_WORD = { offer: "Offer", rejected: "Rejected", closed: "Closed", none: "No result written" };

function insightsDoc() {                                                            // the numbers, fetched again only when what they count changed
  const key = "insights|" + JSON.stringify([(S.facts || {}).rev, (S.facts || {}).counts, (S.jobs || []).map((j) => [j.id, j.stage, j.result, j.dates, j.next, j.kit, (j.fit || {}).score, (j.questions || []).length, (j.rounds || []).length])]);   // a recorded round counts as an interview reached
  if (!UI.docs[key]) {                                                              // new numbers to fetch: the old ones go, and stay drawn until the new arrive
    for (const k of Object.keys(UI.docs)) if (k.startsWith("insights|") && k !== key && k !== UI.insKey) delete UI.docs[k];
    getDoc(key, "/api/v1/insights");
  }
  if (UI.docs[key] && !UI.docs[key].error) UI.insKey = key;                         // the newest that came
  return UI.docs[key] || (UI.insKey && UI.docs[UI.insKey]) || null;                 // the last numbers while new ones load
}

function insLayout() {                                                              // the grid at this width: its columns, a figure's span, the wide one's span
  const w = innerWidth;                                                             // skin.css switches the grid's columns at the same widths
  if (w <= 720) return { cols: 1, tile: 1, wide: 1 };                               // a phone: one under another
  if (w <= 1180) return { cols: 6, tile: 3, wide: 6 };                              // two to a row
  if (w >= 1800) return { cols: 12, tile: 3, wide: 6 };                             // a wide screen: four to a row, all of it on one screen
  return { cols: 12, tile: 4, wide: 12 };                                           // three to a row
}
function tileW(host, wide) {                                                        // the drawing width of a figure in a tile, or in the wide tile
  const cs = getComputedStyle(host);                                                // the canvas's own padding
  const inner = (host.clientWidth || 1200) - parseFloat(cs.paddingLeft || 0) - parseFloat(cs.paddingRight || 0);
  const L = insLayout(), gap = L.cols === 1 ? 8 : 10, pad = 28;                     // as skin.css lays them out: the gap and a tile's padding on both sides
  const s = wide ? L.wide : L.tile;                                                 // its span
  return Math.max(240, Math.floor((inner - gap * (L.cols - 1)) * s / L.cols + gap * (s - 1) - pad));   // its columns, the gaps it spans, less its padding
}

function tile(name, ic, title, sub, ...body) {                                     // one panel of the view: its mark, its name, a line under it, its figure
  const id = "ins-" + name;                                                         // for the heading's name
  return h("section", { class: "ins-tile " + id, "aria-labelledby": id + "-h" },
    h("header", { class: "ins-head" }, h("span", { class: "ins-ic", "aria-hidden": "true" }, icon(ic)), h("h3", { id: id + "-h", text: t(title) }),
      sub ? h("span", { class: "ins-sub", text: sub }) : null),
    body);
}
function legend(parts) {                                                            // a row of keys: a mark of the colour, its words, its number
  return h("div", { class: "ins-legend", "aria-hidden": "true" }, parts.map((p) =>
    h("span", { class: "ins-key" + (p.ring ? " ring" : "") + (p.shape ? " " + p.shape : "") }, h("i", { style: `--c:${p.color}` }), h("span", { text: p.words }), p.n !== undefined ? h("b", { text: String(p.n) }) : null)));   // its mark the chart's own: a square for a bar, a dot for a dot, a dashed square for a dashed bar
}
const pct = (n, d) => d ? Math.round(100 * n / d) : 0;                              // a share in whole percent
let measurer = null;                                                                // one canvas to measure words with, made once
function textW(text, px) {                                                          // the width of a line of words in the page's font, at a size
  if (!measurer) measurer = document.createElement("canvas").getContext("2d");
  measurer.font = `${px}px ${getComputedStyle(document.body).fontFamily}`;
  return Math.ceil(measurer.measureText(String(text)).width);
}
const ym = (s) => { const [y, m] = String(s).split("-").map(Number); return y + (m - 1) / 12; };   // "2024-02" as a year with its fraction

// ---------------------------------------------------------------- the numbers at the top

function kpiRow(d) {
  const k = d.kpi || {};
  const years = Math.floor((k.career_months || 0) / 12), rest = (k.career_months || 0) % 12;   // as a resume writes a career: years and months
  const st = d.stages || {}, f = d.funnel || {}, lanes = ((d.evidence || {}).lanes || []).filter((l) => l.kind === "role");
  const mini = (parts) => h("span", { class: "ins-mini", "aria-hidden": "true" }, parts.filter((p) => p.n > 0).map((p) => h("i", { style: `flex-grow:${p.n};--c:${p.c}` })));   // a thin bar under a number: what it is made of
  const minis = [                                                                   // one per number, in the tiles' order
    mini(["preparing", "submitted", "interview", "result"].map((s) => ({ n: st[s] || 0, c: `var(--stage-${s})` }))),   // the applications by stage
    mini([{ n: f.interview || 0, c: "var(--stage-interview)" }, { n: Math.max(0, (f.submitted || 0) - (f.interview || 0)), c: "var(--line-2)" }]),   // the share that reached an interview
    k.fit_avg === null || k.fit_avg === undefined ? null : h("span", { class: "ins-mini scale", "aria-hidden": "true" },   // the average on a scale of 100, the best marked
      h("i", { style: `width:${k.fit_avg}%;--c:var(--ink-2)` }), k.fit_best ? h("b", { style: `left:${k.fit_best.score}%` }) : null),
    mini([{ n: k.projects || 0, c: "var(--blue-bar)" }, { n: Math.max(0, (k.facts || 0) - (k.projects || 0)), c: "var(--line-2)" }]),   // projects among the facts
    mini(lanes.map((l) => ({ n: l.months, c: "var(--ink-3)" }))),                  // each company's months, in order
    null,
  ];
  const tiles = [
    ["case", t("Applications"), String(k.applications || 0), t("{n} still open", { n: k.open || 0 })],
    ["chat", t("Reached interview"), k.interview_rate === null || k.interview_rate === undefined ? "–" : k.interview_rate + "%",
      t("{i} of {s} submitted", { i: (d.funnel || {}).interview || 0, s: (d.funnel || {}).submitted || 0 })],
    ["check", t("Average fit"), k.fit_avg === null || k.fit_avg === undefined ? "–" : String(k.fit_avg), k.fit_best ? t("Best: {c} {n}", { c: jobNameOf(k.fit_best.job, k.fit_best.company), n: k.fit_best.score }) : t("No posting rated yet")],
    ["list", t("Facts kept"), String(k.facts || 0), t("{n} projects", { n: k.projects || 0 })],
    ["person", t("Career length"), years || rest ? t("{y}y {m}m", { y: years, m: rest }) : "–", t("{n} companies", { n: k.companies || 0 })],
    ["clock", t("Submission to interview"), k.wait_days === null || k.wait_days === undefined ? "–" : t("{n} days", { n: k.wait_days }), k.waits ? tn(k.waits, "the middle of {n} wait", "the middle of {n} waits") : t("the middle of every wait")],
  ];
  return h("div", { class: "ins-kpis" }, tiles.map(([ic, w, n, sub], i) =>
    h("div", { class: "ins-kpi" }, h("span", { class: "ins-ic", "aria-hidden": "true" }, icon(ic)),
      h("div", { class: "ins-kpi-t" }, h("span", { class: "ins-kpi-w", text: w }), h("b", { class: "ins-kpi-n", text: n }), h("span", { class: "ins-kpi-s", text: sub }), minis[i]))));
}

// ---------------------------------------------------------------- the persona: who the evidence says the person is

function personaTile(d) {
  const p = d.persona || {};
  const rated = (d.areas || []).filter((a) => a.demand >= 2 && a.met !== null);    // areas asked for often enough to judge
  // strong only from "in part" up (the fit's own 35), so a 25% area never reads as a strength when only a few are rated;
  // to build: what is under "met" (60) and not already strong. Either may be empty, and says so
  const strong = rated.filter((a) => a.met >= 35).sort((a, b) => b.met - a.met || b.demand - a.demand).slice(0, 3);   // met best
  const weak = rated.filter((a) => a.met < 60 && !strong.includes(a)).sort((a, b) => a.met - b.met || b.demand - a.demand).slice(0, 3);   // met least
  const row = (a) => h("li", { "data-tip": t("{area}: {s} met, {w} in part, {n} not met, of {d} lines in {p} postings", { area: t(a.area), s: a.strong, w: a.weak, n: a.none, d: a.demand, p: a.postings }), tabindex: "0" },
    h("span", { class: "pa-name", text: t(a.area) }), h("span", { class: "pa-bar", "aria-hidden": "true" }, h("i", { style: `width:${a.met}%;--c:${MET_SOLO[metTone(a.met)]}` })),
    h("b", { text: a.met + "%" }));
  return h("section", { class: "ins-tile ins-persona", "aria-labelledby": "ins-persona-h" },
    h("div", { class: "pa-id" },
      h("header", { class: "ins-head" }, h("span", { class: "ins-ic", "aria-hidden": "true" }, icon("person")), h("h3", { id: "ins-persona-h", text: t("Persona") })),
      h("div", { class: "pa-who" }, S.photo && S.photo.on && S.photo.at ? h("img", { class: "pa-photo", src: `/api/v1/photo?w=160&v=${S.photo.at}`, alt: "" }) : null,   // an ID card: the photo, the name, the line under it
        h("div", {}, p.name ? h("b", { text: p.name }) : null, p.tagline ? h("span", { text: p.tagline }) : null)),
      p.headline ? h("p", { class: "pa-head", text: p.headline }) : null,
      (p.competencies || []).length ? h("ul", { class: "pa-chips", "aria-label": t("Competencies") }, p.competencies.slice(0, 6).map((c) => h("li", { text: c }))) : null),
    (p.cards || []).length ? h("dl", { class: "pa-cards" }, p.cards.map((c) => h("div", { class: "pa-card" }, h("dt", { text: c.title }), h("dd", { text: c.text })))) : null,
    h("div", { class: "pa-sw" }, rated.length ? [
      h("div", {}, h("h4", {}, icon("check"), t("Strongest areas")), strong.length ? h("ol", { class: "pa-list" }, strong.map(row)) : h("p", { class: "ins-none", text: t("None yet") })),
      h("div", {}, h("h4", {}, icon("refresh"), t("Areas to build")), weak.length ? h("ol", { class: "pa-list" }, weak.map(row)) : h("p", { class: "ins-none", text: t("None yet") }))]
      : h("p", { class: "ins-none", text: t("Add a posting to see where you are strong.") })));
}

// ---------------------------------------------------------------- the funnel: how far the applications got

function funnelTile(d) {
  const f = d.funnel || {}, r = d.results || {};
  const steps = [["added", "On the board", "var(--stage-preparing)"], ["submitted", "Submitted", "var(--stage-submitted)"], ["interview", "Interview", "var(--stage-interview)"], ["offer", "Offer", "var(--met-strong)"]];
  const top = f.added || 0;                                                         // the first step's width
  const ended = Object.values(r).reduce((s, n) => s + n, 0);                       // the ended ones
  return tile("funnel", "columns", "Progress funnel", tn(top, "{n} application", "{n} applications"),
    h("ol", { class: "fn-steps" }, steps.map(([k, w, c], i) => {
      const n = f[k] || 0, prev = i ? f[steps[i - 1][0]] || 0 : 0;                  // this step, and the one before it
      return h("li", { class: "fn-step", "data-tip": i ? t("{w}: {n}, {p}% of the step before", { w: t(w), n, p: pct(n, prev) }) : t("{w}: {n}", { w: t(w), n }), tabindex: "0" },
        h("span", { class: "fn-w", text: t(w) }),
        h("span", { class: "fn-track", "aria-hidden": "true" }, h("i", { class: "fn-bar", style: `width:${top ? Math.max(n ? 2 : 0, 100 * n / top) : 0}%;--c:${c}` })),
        h("b", { class: "fn-n", text: String(n) }), h("span", { class: "fn-p", text: i ? pct(n, prev) + "%" : "" }));
    })),
    h("div", { class: "fn-ends" }, h("h4", { text: t("Where the cards stand now") }), stageBar(S.jobs || [], { compact: true, id: "ins-stages" })),
    h("div", { class: "fn-ends" }, h("h4", { text: t("How the ended ones ended") }),
      segBar(["rejected", "closed", "none", "offer"].map((k) => ({ n: r[k] || 0, words: t(RESULT_WORD[k]), color: RESULT_COLOR[k] })), { label: t("How the ended ones ended"), id: "ends", total: ended || 0, compact: true })));
}

// ---------------------------------------------------------------- the weeks: what moved, week by week

function weeksTile(d, host) {
  const W = tileW(host), H = 196, padL = 22, padB = 18, padT = 6;               // the drawing's size and its margins for the axis words
  const weeks = d.weeks || [];
  const max = Math.max(1, ...weeks.map((w) => w.submitted + w.interview));          // the tallest column
  const step = max <= 4 ? 1 : max <= 10 ? 2 : 5;                                    // the grid's lines: whole counts
  const top = Math.ceil(max / step) * step;                                         // the axis's top
  const y = (n) => padT + (H - padT - padB) * (1 - n / top);                        // a count's height
  const cw = (W - padL) / Math.max(1, weeks.length);                                // one week's width
  const bw = Math.max(6, Math.min(22, cw - 8));                                     // a column: thin, with air between
  const svg = sv("svg", { class: "ins-svg", width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: `width:${W}px`, "data-w": W, role: "img", "aria-label": t("Moves by week") });
  for (let g = 0; g <= top; g += step) svg.append(sv("line", { class: "grid", x1: padL, x2: W, y1: y(g), y2: y(g) }), sv("text", { class: "ax", x: padL - 6, y: y(g) + 3, "text-anchor": "end" }, String(g)));
  weeks.forEach((w, i) => {
    const x = padL + i * cw + (cw - bw) / 2;                                        // the column's left edge
    const g = sv("g", { class: "col", tabindex: "0", "data-tip": t("Week of {d}: {s} submitted, {i} interviews, {r} results", { d: shortDay(w.week), s: w.submitted, i: w.interview, r: w.result }) });
    let base = 0;                                                                   // stacked from the axis up
    for (const [k, c] of [["submitted", "var(--ev-submitted)"], ["interview", "var(--ev-interview)"]]) {
      const n = w[k] || 0;
      if (!n) continue;
      const y1 = y(base + n), y0 = y(base);                                        // its top and bottom
      g.append(sv("rect", { class: "mk", x, y: y1, width: bw, height: Math.max(1, y0 - y1 - (base ? 2 : 0)), style: `fill:${c}` }));   // a 2px gap between the parts
      base += n;
    }
    g.append(sv("rect", { class: "hit", x: padL + i * cw, y: padT, width: cw, height: H - padT - padB }));   // the hover's target: the whole week
    if ((weeks.length - 1 - i) % 2 === 0) g.append(sv("text", { class: "ax", x: x + bw / 2, y: H - 4, "text-anchor": "middle" }, shortDay(w.week)));
    svg.append(g);
  });
  const sums = weeks.reduce((s, w) => ({ s: s.s + w.submitted, i: s.i + w.interview }), { s: 0, i: 0 });
  return tile("weeks", "clock", "Moves by week", t("The last {n} weeks", { n: weeks.length }),
    legend([{ words: t("Submitted"), color: "var(--ev-submitted)", n: sums.s }, { words: t("Interview"), color: "var(--ev-interview)", n: sums.i }]), svg);
}

// ---------------------------------------------------------------- the map: how often an area is asked for, and how well it is met

function mapTile(d, host) {
  const areas = (d.areas || []).filter((a) => a.demand > 0);                        // the areas a posting asks for
  const W = tileW(host), H = 206, pl = 30, pr = 10, pt = 10, pb = 22;            // its size and the axes' room
  const maxD = Math.max(4, ...areas.map((a) => a.demand));                          // the widest demand
  const topM = Math.max(0, ...areas.map((a) => a.met)) > 70 ? 100 : 75;            // the axis's top: 75% while no area is met past 70%, so the dots get the height
  const x = (v) => pl + (W - pl - pr) * v / maxD, y = (v) => pt + (H - pt - pb) * (1 - v / topM);   // demand across, the share met up
  const sorted = areas.map((a) => a.demand).sort((a, b) => a - b);
  const midD = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;           // the middle demand: left of it asked less often
  const narrow = W < 420, byDemand = [...areas].sort((a, b) => b.demand - a.demand);   // a phone's map: too narrow for every name beside its dot
  const label = (a) => narrow ? String(byDemand.indexOf(a) + 1) : t(a.area);       // there each dot carries its number, and the names are listed under the map
  const svg = sv("svg", { class: "ins-svg", width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: `width:${W}px`, "data-w": W, role: "img", "aria-label": t("Strengths and gaps map") });
  const rules = sv("g", {});                                                        // the lines, under everything else: drawn below, once the names have their places
  svg.append(rules, ...[0, 50, topM].map((v) => sv("text", { class: "ax", x: pl - 6, y: y(v) + 3, "text-anchor": "end" }, v + "%")));
  const placed = areas.map((a) => ({ x: x(a.demand) - 7, y: y(a.met) - 7, w: 14, h: 14 }));   // every dot's box first: no label goes over a dot
  const dots = placed.slice();                                                      // the dots alone, before any words
  placed.push(...[0, 50, topM].map((v) => { const w = textW(v + "%", 10.5); return { x: pl - 6 - w, y: y(v) - 7, w, h: 13 }; }));   // the axis's own numbers: a label may stand left of the axis, never over them
  const words = (cx, cy, anchor, text, cls, step = 0) => {                         // a quiet line of words, its box kept so no label covers it
    const w = textW(text, 10.5);
    for (const dy of [0]) {                                                         // a corner's name over a dot is left out: moved beside it, it read as the dot's name
      const box = { x: anchor === "end" ? cx - w : cx, y: cy + dy - 10, w, h: 13 };
      if (step && dots.some((p) => box.x < p.x + p.w + 8 && box.x + box.w > p.x - 8 && box.y < p.y + p.h + 8 && box.y + box.h > p.y - 8)) continue;   // near a dot it would read as its name
      placed.push(box);
      return sv("text", { class: cls, x: cx, y: cy + dy, "text-anchor": anchor }, text);
    }
    return null;
  };
  svg.append(...[words(W - pr - 2, pt + 10, "end", t("Strong where asked"), "qd", 14), words(W - pr - 2, H - pb - 6, "end", t("Build these first"), "qd", -14),
    words(pl + 4, pt + 10, "start", t("Strong, asked less"), "qd", 14), words(pl + 4, H - pb - 6, "start", t("Later"), "qd", -14),
    words(W - pr, H - 4, "end", t("lines asked for →"), "ax")].filter(Boolean));
  const meets = (b, p) => b.x < p.x + p.w && b.x + b.w > p.x && b.y < p.y + p.h && b.y + b.h > p.y;   // two boxes share a pixel
  const spots = (cx, cy) => [[cx + 8, cy + 4, "start"], [cx - 8, cy + 4, "end"], [cx, cy - 10, "middle"], [cx, cy + 18, "middle"],   // right, left, above, below,
    [cx + 6, cy - 8, "start"], [cx - 6, cy - 8, "end"], [cx + 6, cy + 16, "start"], [cx - 6, cy + 16, "end"],                       // then the four corners;
    [cx + 22, cy + 4, "start"], [cx - 22, cy + 4, "end"], [cx, cy - 22, "middle"], [cx, cy + 30, "middle"],                         // no room beside it: a little
    [cx + 18, cy - 18, "start"], [cx - 18, cy - 18, "end"], [cx + 18, cy + 28, "start"], [cx - 18, cy + 28, "end"],                 // further, with a line to it,
    [cx + 30, cy - 30, "start"], [cx - 30, cy - 30, "end"], [cx, cy - 36, "middle"], [cx + 40, cy + 4, "start"], [cx - 40, cy + 4, "end"]];   // then further still
  const NEAR = 8;                                                                   // the first eight touch the dot; the rest get a leader
  const leadOf = (cx, cy, b) => {                                                   // a leader: from the dot's edge to the label's nearest point
    const ex = Math.max(b.x, Math.min(cx, b.x + b.w)), ey = Math.max(b.y, Math.min(cy, b.y + b.h)), d = Math.hypot(ex - cx, ey - cy) || 1;
    return { x1: cx + (ex - cx) * 7 / d, y1: cy + (ey - cy) * 7 / d, x2: ex, y2: ey };
  };
  const beads = (l) => [1, 2, 3, 4, 5, 6, 7].map((k) => ({ x: l.x1 + (l.x2 - l.x1) * k / 8 - 1, y: l.y1 + (l.y2 - l.y1) * k / 8 - 1, w: 2, h: 2 }));   // the line as small boxes: it crosses nothing, and nothing is set down across it
  const gap = (b, px, py) => Math.hypot(Math.max(b.x - px, 0, px - (b.x + b.w)), Math.max(b.y - py, 0, py - (b.y + b.h)));   // from a box to a point, 0 inside it
  const floor = { x: pl, y: y(0) - 1, w: W - pl - pr, h: 2 };                        // the 0% line: words are never set across it (it would underline or strike them)
  const quiet = [50, topM].map((v) => ({ x: pl, y: y(v) - 1, w: W - pl - pr, h: 2 })).concat({ x: x(midD) - 1, y: pt, w: 2, h: H - pt - pb });   // the dashed middles and the top: crossed only when no place clears them
  const place = (order) => {                                                        // one pass: each dot in turn takes the first free place around it
    const taken = placed.slice(), at = new Map();                                   // the dots, the corner words and the axis's numbers stay clear
    at.cost = 0;                                                                    // how far the names had to move, summed
    for (const a of order) {
      const cx = x(a.demand), cy = y(a.met), w = textW(label(a), 11) + 4, own = dots[areas.indexOf(a)];   // the label's width, as the font sets it, and the dot's own box
      const all = spots(cx, cy).map(([lx, ly, anchor]) => {
        const bx = anchor === "start" ? lx : anchor === "end" ? lx - w : Math.min(Math.max(lx - w / 2, 2), W - pr - w);   // above or below, it slides sideways to stay inside the picture
        return { lx: anchor === "middle" ? bx + w / 2 : lx, ly, anchor, box: { x: bx, y: ly - 11, w, h: 13 } };
      });
      pick: for (const far of [false, true]) for (const clear of [true, false]) for (const c of far ? all.slice(NEAR) : all.slice(0, NEAR)) {   // beside the dot before apart from it, clear of the lines before across one
        const box = c.box;
        if (box.x < 2 || box.x + box.w > W - pr || box.y < 0 || box.y + box.h > H - 1 || meets(box, floor) || taken.some((p) => p !== own && meets(box, p))) continue;   // inside the picture (under the floor too, for a dot on it), clear of the rest (its own dot aside: the corner places touch it)
        if (clear && quiet.some((l) => meets(box, l))) continue;                    // a dashed line would run through the words: another place first
        if (!far && areas.some((o) => o !== a && (x(o.demand) !== cx || y(o.met) !== cy) && gap(box, x(o.demand), y(o.met)) < gap(box, cx, cy) + 5)) continue;   // as near another dot as its own: it would read as that dot's name (set apart, a line says whose it is)
        const lead = far ? leadOf(cx, cy, box) : null, line = lead ? beads(lead) : [];   // set apart from its dot, it gets a line back to it
        if (line.some((q) => taken.some((p) => p !== own && meets(q, p)))) continue;   // a line through another dot or another name would tie the wrong two together
        taken.push(box, ...line); at.set(a, { lx: c.lx, ly: c.ly, anchor: c.anchor, lead, box });
        at.cost += (far ? 8 : 0) + (clear ? 0 : 2);                                  // what the picture pays for this place: a leader most, a line through the words less
        break pick;
      }
    }
    return at;
  };
  const order = [...areas].sort((a, b) => b.demand - a.demand);                     // the most asked first: they get the places beside their dots
  let at = place(order);
  if (at.size < order.length || at.cost) {                                          // a dot left unnamed, or a name set apart from its dot: other orders are tried
    const left = order.filter((a) => !at.has(a));                                   // the unnamed ones first,
    const tries = [[...left, ...order.filter((a) => at.has(a))], [...order].reverse()];   // then the least asked first,
    let seed = 11;                                                                  // then sixty shuffles, the same sixty every time (the picture must not change between two looks)
    const rnd = () => (seed = seed * 48271 % 2147483647) / 2147483647;
    for (let k = 0; k < 60; k++) tries.push(order.map((a) => [rnd(), a]).sort((p, q) => p[0] - q[0]).map((p) => p[1]));
    for (const o of tries) {
      const got = place(o);
      if (got.size > at.size || (got.size === at.size && got.cost < at.cost)) at = got;   // more dots named, or as many with less moved
      if (at.size === order.length && !at.cost) break;                              // every name beside its dot
    }
  }
  const names = [...at.values()].map((s) => s.box);                                 // where the names stand
  const rule = (cls, from, to, fixed, flat) => {                                    // a line in pieces: left out where a name stands on it, so none runs through the words
    const cuts = names.filter((b) => flat ? b.y - 1 < fixed && fixed < b.y + b.h + 1 : b.x - 1 < fixed && fixed < b.x + b.w + 1)
      .map((b) => flat ? [b.x - 3, b.x + b.w + 3] : [b.y - 2, b.y + b.h + 2]).sort((p, q) => p[0] - q[0]);   // each name's stretch of the line, a little wider than the words
    const parts = [];
    let at0 = from;                                                                 // where the next piece starts
    for (const [c0, c1] of cuts) {
      if (c0 > at0 && at0 < to) parts.push([at0, Math.min(c0, to)]);                // the piece before this name
      at0 = Math.max(at0, c1);                                                      // on from its far side
    }
    if (at0 < to) parts.push([at0, to]);                                            // the rest of the line
    return parts.map(([p, q]) => sv("line", flat ? { class: cls, x1: p, x2: q, y1: fixed, y2: fixed } : { class: cls, x1: fixed, x2: fixed, y1: p, y2: q }));
  };
  rules.append(sv("line", { class: "grid", x1: pl, x2: W - pr, y1: y(0), y2: y(0) }),   // the floor whole: no name is ever set across it
    ...rule("grid", pl, W - pr, y(50), true), ...rule("grid", pl, W - pr, y(topM), true),
    ...rule("mid", pt, H - pb, x(midD), false), ...rule("mid", pl, W - pr, y(50), true));
  for (const a of order) {
    const cx = x(a.demand), cy = y(a.met), tone = metTone(a.met), name = t(a.area), spot = at.get(a);
    const g = sv("g", { class: "dot", tabindex: "0", "data-tip": t("{area}: {m}% met over {d} lines in {p} postings; {e} facts back it", { area: name, m: a.met, d: a.demand, p: a.postings, e: a.evidence }) });
    g.append(sv("circle", { class: "hit", cx, cy, r: 11 }), sv("circle", { class: "mk" + (a.soft ? " ring" : ""), cx, cy, r: 5, style: `--c:${MET[tone]}` }));
    if (spot && spot.lead) g.append(sv("line", { class: "lead", ...spot.lead }));   // the line from the dot to a name set apart from it
    if (spot) g.append(sv("text", { class: "lb", x: spot.lx, y: spot.ly, "text-anchor": spot.anchor }, label(a)));   // an unnamed dot still answers the pointer and the keyboard with its line
    svg.append(g);
  }
  return tile("map", "map", "Strengths and gaps map", t("Each dot is an area of the postings"),
    legend([...["strong", "weak", "none"].map((k) => ({ words: t(MET_WORD[k]), color: MET[k], shape: "dot", n: areas.filter((x) => metTone(x.met) === k).length })),   // each mark with how many areas it marks
      { words: t("Any trade"), color: "var(--ink-3)", ring: true, n: areas.filter((x) => x.soft).length }]),   // the map's marks are dots
    areas.length ? svg : h("p", { class: "ins-none", text: t("Add a posting to see where you are strong.") }),
    areas.length && narrow ? h("ol", { class: "map-key", "aria-label": t("Strengths and gaps map") }, byDemand.map((a, i) =>   // the numbers' names, the most asked first
      h("li", {}, h("b", { text: String(i + 1) }), h("span", { text: t(a.area) }), h("small", { text: a.met + "%" })))) : null);
}

// ---------------------------------------------------------------- the areas: every requirement line, by area

function areasTile(d) {
  const areas = (d.areas || []).filter((a) => a.demand > 0).sort((a, b) => b.demand - a.demand);   // the most asked first
  const max = Math.max(1, ...areas.map((a) => a.demand));                           // the longest bar
  const shown = areas.slice(0, insLayout().tile === 3 ? 10 : 15), more = areas.length - shown.length;   // as many as its row has room for
  const tot = areas.reduce((s, a) => ({ s: s.s + a.strong, w: s.w + a.weak, n: s.n + a.none }), { s: 0, w: 0, n: 0 });
  const u = d.unsorted || {};
  return tile("areas", "list", "What postings ask, by area", tn((d.fits || []).length, "{n} lines in {p} posting", "{n} lines in {p} postings", { n: tot.s + tot.w + tot.n, p: (d.fits || []).length }),
    legend([{ words: t(MET_WORD.strong), color: MET.strong, n: tot.s }, { words: t(MET_WORD.weak), color: MET.weak, n: tot.w }, { words: t(MET_WORD.none), color: MET.none, n: tot.n }]),
    h("ul", { class: "ar-rows" }, shown.map((a) => h("li", { class: "ar-row", tabindex: "0",
      "data-tip": t("{area}: {s} met, {w} in part, {n} not met, of {d} lines in {p} postings; {e} facts back it", { area: t(a.area), s: a.strong, w: a.weak, n: a.none, d: a.demand, p: a.postings, e: a.evidence }) },
      h("span", { class: "ar-name", text: t(a.area) }),
      h("span", { class: "ar-track", "aria-hidden": "true" }, h("span", { class: "ar-bar", style: `width:${100 * a.demand / max}%` },
        ["strong", "weak", "none"].map((k) => a[k] ? h("i", { style: `flex-grow:${a[k]};--c:${MET[k]}` }) : null))),
      h("b", { class: "ar-n", text: String(a.demand), title: tn(a.demand, "{n} line asked for", "{n} lines asked for"), "aria-label": tn(a.demand, "{n} line asked for", "{n} lines asked for") }), h("span", { class: "ar-ev", text: t("{n} facts", { n: a.evidence }) })))),
    h("p", { class: "ins-foot", text: [more > 0 ? t("{n} more areas", { n: more }) : "", (u.other || 0) ? t("{n} lines of no area", { n: u.other }) : "", (u.process || 0) ? t("{n} lines about the hiring itself, left out", { n: u.process }) : ""].filter(Boolean).join(" · ") }));
}

// ---------------------------------------------------------------- the fits and the lines to work on

function gapsTile(d, host) {
  const fits = d.fits || [];
  const stacks = {};                                                               // dots at about one score stack upward: the strip grows to hold them
  for (const f of fits) { const k = Math.round(f.score / 3); stacks[k] = (stacks[k] || 0) + 1; }
  const extra = Math.max(0, Math.max(0, ...Object.values(stacks)) - 1) * 9;        // the room the tallest stack needs above the axis
  const W = tileW(host), H = 44 + extra, pl = 6, pr = 6;                           // a strip of the postings' scores
  const x = (v) => pl + (W - pl - pr) * v / 100;
  const svg = sv("svg", { class: "ins-svg strip", width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: `width:${W}px`, "data-w": W, role: "img", "aria-label": t("Fit per posting") });
  const ay = 22 + extra;                                                            // the axis, under the room the dots need
  svg.append(sv("line", { class: "axis", x1: pl, x2: W - pr, y1: ay, y2: ay }));
  for (const v of [0, 25, 50, 75, 100]) svg.append(sv("line", { class: "tick", x1: x(v), x2: x(v), y1: ay - 4, y2: ay + 4 }), sv("text", { class: "ax", x: x(v), y: ay + 18, "text-anchor": v === 0 ? "start" : v === 100 ? "end" : "middle" }, String(v)));
  const seen = {};                                                                  // dots at one score stack upward a little
  for (const f of fits) {
    const k = Math.round(f.score / 3), lift = (seen[k] = (seen[k] || 0) + 1) - 1;  // near the same score: lifted, not hidden
    svg.append(sv("g", { class: "dot", tabindex: "0", "data-tip": t("{c}: fit {n}, {s} met, {w} in part, {m} not met", { c: jobNameOf(f.job, f.company), n: f.score, s: f.counts.strong, w: f.counts.weak, m: f.counts.none }) },
      sv("circle", { class: "hit", cx: x(f.score), cy: ay - lift * 9, r: 9 }), sv("circle", { class: "mk", cx: x(f.score), cy: ay - lift * 9, r: 5, style: `--c:var(--stage-${f.stage})` })));
  }
  const pick = (d.areas || []).filter((a) => a.none > 0 && !a.soft).sort((a, b) => b.none - a.none || b.demand - a.demand).slice(0, 3);   // the craft's areas most often not met
  const soft = (d.areas || []).filter((a) => a.none > 0 && a.soft).sort((a, b) => b.none - a.none)[0];   // and the general one most often not met
  const lines = [...pick, soft].filter(Boolean).flatMap((a) => (a.unmet || []).filter((l) => l.rating === "none").slice(0, a === soft ? 1 : 2).map((l) => ({ ...l, area: a.area })));
  return tile("gaps", "refresh", "Requirements to work on", t("Not met, in the areas asked most"),
    h("h4", { class: "ins-h4", text: t("Fit per posting") }), svg,
    fits.length ? legend(["preparing", "submitted", "interview", "result"].map((st) => ({ words: t(STAGE[st]), color: `var(--stage-${st})`, shape: "dot", n: fits.filter((f) => f.stage === st).length })).filter((k) => k.n)) : null,   // the dots' colours are the stages
    lines.length ? h("h4", { class: "ins-h4", text: t("Lines not met") }) : null,   // the tile's second part named too: the strip above is the postings, these their lines
    lines.length ? h("ul", { class: "gp-rows" }, lines.slice(0, 6).map((l) => h("li", { class: "gp-row" },
      mono(l.company, "sm", ((S.jobs || []).find((j) => j.id === l.job) || {}).stage), h("div", { class: "gp-t" }, h("span", { class: "gp-area", text: t(l.area) + " · " + jobNameOf(l.job, l.company) }), h("span", { class: "gp-text", text: l.text, title: l.text })))))
      : h("p", { class: "ins-none", text: t("Nothing unmet yet.") }));
}

// ---------------------------------------------------------------- readiness: the open applications and their kits

function readyTile(d) {
  const all = d.ready || [], rows = all.slice(0, 5);                                // the nearest interviews first; the rest are on the board
  const goJob = (r, tab) => { S.job = r.job; UI.jobTab = tab; act("/api/v1/jobs/select", { job: r.job }); go("jobs"); };   // that application, on its tab
  return tile("ready", "mic", "Interview readiness", tn(all.length, "{n} open application", "{n} open applications"),
    rows.length ? h("ul", { class: "rd-list" }, rows.map((r) => {
      const c = r.coverage, sum = c ? c.strong + c.weak + c.none : 0;               // the kit's likely questions
      return h("li", { class: "rd-item", "data-stage": r.stage },
        mono(r.company, "sm", r.stage),
        h("button", { class: "rd-name", type: "button", onclick: () => goJob(r, "interview"), title: t("Open its interview tab") }, h("b", { text: jobNameOf(r.job, r.company) }), h("small", { text: t(STAGE[r.stage]) })),
        h("span", { class: "rd-fit", "data-tip": r.fit === null ? null : t("Fit {n} / 100", { n: r.fit }) }, r.fit === null ? h("small", { text: t("No posting") }) : [h("b", { text: String(r.fit) }), h("i", { class: "rd-fitbar", style: `--w:${r.fit}%;--c:${MET_SOLO[metTone(r.fit)]}`, "aria-hidden": "true" })]),
        h("span", { class: "rd-meta" },
          c ? h("span", { class: "rd-cov", tabindex: "0", "data-tip": t("Interview map: {s} met, {w} in part, {n} not met, {k} scripts", { s: c.strong, w: c.weak, n: c.none, k: r.scripts }) },
            h("span", { class: "rd-seg", "aria-hidden": "true" }, ["strong", "weak", "none"].map((k) => c[k] ? h("i", { style: `flex-grow:${c[k]};--c:${MET[k]}` }) : null)), h("small", { text: t("map {p}%", { p: pct(c.strong, sum) }) }))
            : h("button", { class: "btn small", type: "button", onclick: () => goJob(r, "interview"), text: t("Make the kit") }),
          r.questions ? h("small", { class: "rd-q", text: t("form answers {a}/{n}", { a: r.answered, n: r.questions }) }) : null,
          r.next ? h("small", { class: "rd-next", text: r.next }) : r.interview ? h("small", { class: "rd-next", text: t("Interview {d}", { d: shortDay(r.interview) }) }) : null));
    })) : h("p", { class: "ins-none", text: t("No application is open.") }),
    all.length > rows.length ? h("button", { class: "btn small ghost ins-more", type: "button", onclick: () => { UI.jobsMode = "board"; go("jobs"); }, text: t("{n} more on the board", { n: all.length - rows.length }) }) : null);
}

// ---------------------------------------------------------------- the career and its evidence

function careerTile(d, host) {
  const ev = d.evidence || {}, lanes = ev.lanes || [];
  const W = tileW(host, true), rowH = insLayout().wide === 6 ? 22 : 16, pr = 54, pt = 4;   // a lane per span; the names on the left, the counts on the right
  const need = Math.max(0, ...lanes.map((l) => textW(l.org, 11))) + 14;            // the longest name, whole
  const pl = Math.min(Math.max(Math.round(W * 0.2), need), Math.round(W * 0.45));   // its column: as wide as that name, up to 45% of the tile (a phone's narrow one too)
  const H = pt + lanes.length * rowH + 18;
  const from = Math.floor(Math.min(...lanes.map((l) => ym(l.start)), 2020)), to = Math.ceil(Math.max(...lanes.map((l) => ym(l.end) + 1 / 12), from + 1));
  const x = (v) => pl + (W - pl - pr) * (v - from) / Math.max(1, to - from);
  const svg = sv("svg", { class: "ins-svg", width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: `width:${W}px`, "data-w": W, role: "img", "aria-label": t("Career and evidence") });
  const every = [1, 2, 4, 5, 10].find((e) => (W - pl - pr) / ((to - from) / e) >= 34) || 10;   // a year's mark as often as its four digits fit apart (a phone: every fourth or fifth)
  for (let yv = from; yv <= to; yv += every) svg.append(sv("line", { class: "grid v", x1: x(yv), x2: x(yv), y1: pt, y2: H - 16 }), sv("text", { class: "ax", x: x(yv), y: H - 4, "text-anchor": "middle" }, String(yv)));
  lanes.forEach((l, i) => {
    const y0 = pt + i * rowH, x0 = x(ym(l.start)), x1 = Math.max(x0 + 3, x(ym(l.end) + 1 / 12));   // the span, a month at least
    let name = l.org;                                                               // the lane's name, whole in its column
    const fs = textW(name, 11) > pl - 12 ? 10 : 11;                                  // a name longer than the column a size smaller
    while (name.length > 2 && textW(name, fs) > pl - 12) name = name.slice(0, -1);   // past 45% of the tile even so: the last resort
    if (name !== l.org) name = name.slice(0, -1) + "…";
    const g = sv("g", { class: "lane " + l.kind, tabindex: "0", "data-tip": `${l.org} · ${l.title} · ${l.start.replace("-", ".")} ~ ${l.ongoing ? t("now") : l.end.replace("-", ".")} (${t("{n} months", { n: l.months })})` + (l.kind === "role" ? " · " + t("{n} facts", { n: l.facts }) : "") });
    g.append(sv("text", { class: "lb", x: pl - 8, y: y0 + 12, "text-anchor": "end", style: fs < 11 ? "font-size:10px" : null }, name),
      sv("rect", { class: "hit", x: 0, y: y0, width: W, height: rowH }),
      sv("rect", { class: "mk", x: x0, y: y0 + 4, width: x1 - x0, height: rowH - 8 }));
    if (l.kind === "role") g.append(sv("text", { class: "ct", x: x1 + 6, y: y0 + 12 }, t("{n} facts", { n: l.facts })));
    svg.append(g);
  });
  const kinds = Object.entries(ev.kinds || {}).filter(([k]) => k !== "skill" && k !== "other");   // what the facts are, the skill lists aside
  const top = kinds.slice(0, 3), restN = kinds.slice(3).reduce((s, [, n]) => s + n, 0) + ((ev.kinds || {}).other || 0) + ((ev.kinds || {}).skill || 0);   // three kinds, then the rest together (the skill lists too: the bar adds up to the facts the head counts)
  const KC = ["var(--blue-bar)", "var(--orange-bar)", "var(--ink-2)"];               // fixed order: the most common first (blue and orange stay apart; blue and violet did not)
  return tile("career", "layers", "Career and evidence", t("{n} facts, {m} of them with no company", { n: (d.kpi || {}).facts || 0, m: ev.unattached || 0 }),
    segBar([...top.map(([k, n], i) => ({ n, words: t(KIND[k] || k), color: KIND_COLOR[k] || KC[i] })), ...(restN ? [{ n: restN, words: t("Other"), color: "var(--ink-3)" }] : [])],
      { label: t("Facts by kind"), id: "kinds", compact: true }),
    lanes.length ? svg : h("p", { class: "ins-none", text: t("No role with a period yet.") }),
    legend([{ words: t("Employment"), color: "var(--ink-2)" }, { words: t("Education"), color: "var(--ink-3)", shape: "dash" }]));   // a school's lane is a dashed bar
}

// ---------------------------------------------------------------- the view

function viewInsights(host) {
  const d = insightsDoc();                                                          // the numbers
  if (!d) return fill(host, h("div", { class: "ins loading", "aria-busy": "true" }, h("div", { class: "ins-kpis" }, [1, 2, 3, 4, 5, 6].map(() => h("div", { class: "ins-kpi ghost" }))),
    h("p", { class: "ins-none", text: t("Counting…") })));
  if (d.error) return fill(host, h("div", { class: "ins" }, h("p", { class: "ins-none", text: t("The numbers could not be read.") })));
  const out = h("div", { class: "ins" },
    personaTile(d),
    kpiRow(d),
    h("div", { class: "ins-grid" },
      funnelTile(d), weeksTile(d, host), mapTile(d, host),
      areasTile(d), gapsTile(d, host), readyTile(d),
      careerTile(d, host)));
  const L = insLayout();                                                            // the same spans the figures were drawn for
  if (L.cols > 1) for (const el of out.querySelectorAll(".ins-grid > .ins-tile")) el.style.gridColumn = "span " + (el.classList.contains("ins-career") ? L.wide : L.tile);
  for (const el of out.querySelectorAll(".ins-tile")) el.dataset.viz = (el.className.split(" ")[1] || "") + ":" + hashText(el.textContent);   // its name and numbers: motion.js plays it again only when they change
  fill(host, out);
  // drawn for the width the canvas had a moment ago (opening from Documents, whose inspector takes a side): when a
  // figure's box turns out wider or narrower once laid out, the view is drawn again for it, once
  requestAnimationFrame(() => {
    const off = [...out.querySelectorAll(".ins-svg[data-w]")].some((svg) => Math.abs(svg.parentElement.clientWidth - padOf(svg.parentElement) - Number(svg.dataset.w)) > 6);
    if (off && (UI.insRedrawn || 0) < 2) { UI.insRedrawn = (UI.insRedrawn || 0) + 1; host._key = null; render(); }
    else UI.insRedrawn = 0;
  });
}
function padOf(el) { const cs = getComputedStyle(el); return parseFloat(cs.paddingLeft || 0) + parseFloat(cs.paddingRight || 0); }   // a box's own padding, both sides
function hashText(s) { let x = 0; for (const ch of s) x = (x * 31 + ch.codePointAt(0)) >>> 0; return x.toString(36); }   // a short stamp of what a tile says

// the numbers are counted once in the background after the page starts, so the view opens with them: the first count
// reads every interview kit, which takes the server a few seconds
setTimeout(function warm() { if (typeof S !== "undefined" && S && S.jobs) insightsDoc(); else setTimeout(warm, 2000); }, 4000);

// ---------------------------------------------------------------- the hover: the exact numbers of a mark

(function () {
  let tip = null;                                                                   // the one tooltip of the page
  function show(el) {
    const words = el.getAttribute("data-tip");
    if (!words) return;
    if (!tip) { tip = document.createElement("div"); tip.className = "viz-tip"; tip.setAttribute("role", "tooltip"); document.body.append(tip); }
    tip.textContent = words;
    const r = el.getBoundingClientRect();                                           // above the mark, inside the window
    tip.style.left = "0px"; tip.style.top = "0px"; tip.hidden = false;
    const w = tip.offsetWidth, hh = tip.offsetHeight;
    tip.style.left = Math.round(Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2))) + "px";
    tip.style.top = Math.round(r.top - hh - 8 < 8 ? r.bottom + 8 : r.top - hh - 8) + "px";
  }
  function hide() { if (tip) tip.hidden = true; }
  document.addEventListener("mouseover", (e) => { const el = e.target.closest && e.target.closest("[data-tip]"); if (el) show(el); else hide(); });
  document.addEventListener("focusin", (e) => { const el = e.target.closest && e.target.closest("[data-tip]"); if (el) show(el); else hide(); });
  document.addEventListener("scroll", hide, true);                                  // the mark moved away from it
})();
