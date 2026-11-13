// The deck's figure library.
// These templates draw common figure shapes from data, with the deck's drawing parts (portfolio/draw.js: measured text, rectangles, connectors whose
// arrowheads snap to the box they point at), so the deck checks (overflow, overlap, arrows, small text, contrast) read them like
// any other drawing.
//
// Every template draws into a box of one shared coordinate system and returns its parts. That is what lets `panels` hold several
// sub-figures in one frame (multi-panel figures) while arrow snapping still sees every box in one place.
//
// Templates and their data (text fields may carry two spaces 'Name  note' for a bold head and a regular rest):
//   pipeline     steps left to right, a second row runs back (snake)      { steps: [[title, sub, kind]], groups: [[label, from, to]] }
//   beforeAfter  the old structure and the new one with an arrow           { before: { title, items, flow, note }, after: {...}, change }
//   bars         one value per row, horizontal, with an axis               { unit, rows: [[label, value]], highlight: [label], note }
//   matrix       rows against columns with marks or short text            { cols, rows: [[name, ...cells]], groups: [[label, from, to]], highlight }
//   phases       named periods on a month axis                            { rows: [[name, start, end, note]] }
//   cluster      groups of nodes as squares with their counts              { unit, groups: [[name, count, note]] }
//   timeline     phases in lanes and milestones on a date axis             { phases: [[name, start, end, note, kind]], milestones: [[label, date, kind]] }
//   gantt        workstreams of tasks on a month axis                      { groups: [{ name, tasks: [[name, start, end, kind]] }], milestones, today }
//   architecture zones of nodes with labeled links                        { zones: [{ title, kind, nodes: [{ id, title, sub, kind, units, unitKinds }] }], links: [[from, to, label, kind]] }
//   rack         racks of units under a switch fabric                      { racks: [{ name, sub, units: [[label, kind, count]] }], fabric: { label, items } }
//   metric       before and after values with conditions                  { unit, better, beforeLabel, afterLabel, rows: [[name, before, after, condition]], conditions, delta }
//   columns      grouped vertical bars with a value axis                   { unit, series: [names], groups: [[label, v1, v2, ...]], highlight }
//   trend        lines over ordered points with labels at their ends       { unit, x: [labels], series: [[name, [values], kind]] }
//   tree         a hierarchy: root, children, grandchildren               { root: [title, sub], children: [[title, sub, kind, [[title, sub, kind]]]] }
//   panels       several of the above in one frame, with titles and marks  { layout: "1+2" | "2+1" | "2" | "2v" | "2x2" | "3", panels: [{ title, mark, note, figure }] }
//
// Kinds give color a meaning, and every figure that uses one draws a legend for it: mine (my part), key (core or outcome), old (before),
// ext (external, customer), data (data, storage), plan (proposed), stop (stopped, failed), hl (evidence). `legend` renames them.
// Schemes: light (the deck's colors, draw.js C) and dark (for pictures on dark pages). Both pass the deck's contrast check.
//
// Every template returns an SVG string sized for its frame (W x H) and records text it had to shorten in the cut list (the document
// check reports that list). audit() is a fast static check of the same drawing (text outside the canvas, text over text, text across
// a box edge, text wider than its box) for tests and for the drafting step, which runs before any browser does.
//   node src/deck_figures.js --audit <figure.json> [W H ko|en light|dark]   prints the audit of one figure as JSON
const { C, P, D, Svg, tw, stackY } = require("./portfolio/draw");   // the shared drawing parts

// palettes and kinds

// Scheme colors. light is the deck's own set (the figure frame is paper behind the drawing); dark paints its own page
const PAL = {
  // The deck's own colors; no page fill, so the frame's paper shows through
  light: { name: "light", page: null, panel: C.white, zone: C.key, zone2: C.b5, line: C.rule, grid: "#E3E8EF", ink: C.navy, body: C.body,
           // Text greys, the strong fill with its text colors, and the accent
           muted: C.grey, faint: C.faint, strong: C.navy, onStrong: C.white, onStrongSub: "#DCE6F3", accent: C.blue, accentText: C.b1,
           // Light fills, chart series colors, and draw.js's own arrowhead names
           soft: C.b4, soft2: C.b3, series: [C.b3, C.blue, C.navy, C.t2, C.a2], arrow: { navy: "navy", blue: "blue", grey: "grey" },
           arrowColor: { navy: C.navy, blue: C.blue, grey: C.faint } },   // the stroke color that goes with each arrowhead
  // Dark paints its own page, so a figure reads the same on any slide background
  dark: { name: "dark", page: "#0F1722", panel: "#182232", zone: "#131C2A", zone2: "#16263D", line: "#3A4A63", grid: "#273349", ink: "#E6EDF7",
          // Light text on dark; strong fills turn light and carry dark text
          body: "#C9D3E1", muted: "#A3B0C2", faint: "#7D8BA0", strong: "#DCE6F3", onStrong: "#0F1722", onStrongSub: "#2A3A52", accent: "#6EA8F0",
          accentText: "#A9C9F5", soft: "#22344F", soft2: "#3A5578", series: ["#5B7290", "#6EA8F0", "#DCE6F3", "#2BB38F", "#E08A3E"],   // series colors lifted so each reads on the dark page
          // The DARK_DEFS heads (ah-dnavy and so on) and their lighter strokes
          arrow: { navy: "dnavy", blue: "dblue", grey: "dgrey" }, arrowColor: { navy: "#C9D3E1", blue: "#6EA8F0", grey: "#7D8BA0" } },
};
// Arrowheads for the dark scheme (draw.js defines navy, blue and grey heads for light pages only). The ids keep draw.js's pattern
// (ah-<letters>, and -s for the small head that snapArrows swaps in on short arrows)
const DARK_DEFS = `<defs>${Object.entries(PAL.dark.arrowColor).map(([k, c]) => [["", 5.4], ["-s", 3.9]].map(([sfx, mw]) =>
  `<marker id="ah-d${k}${sfx}" viewBox="0 0 10 10" refX="7.5" refY="5" markerWidth="${mw}" markerHeight="${mw}" orient="auto-start-reverse">` +
  `<path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`).join("")).join("")}</defs>`;
// Box styles per kind and scheme: fill, stroke, stroke width, dash, title and sub colors (every pair passes contrast 4.5)
const KIND = {
  light: {                                                   // kinds on light pages
    "": { fill: C.white, stroke: C.rule, sw: 1, title: C.navy, sub: C.grey },   // no kind: a plain white box
    mine: { fill: C.white, stroke: C.blue, sw: 1.6, title: C.navy, sub: C.b1 },   // the person's part: a thicker blue outline
    key: { fill: C.navy, stroke: C.navy, sw: 1, title: C.white, sub: "#DCE6F3" },   // core or outcome: solid navy with white text
    old: { fill: "#F3F5F8", stroke: C.rule, sw: 1, dash: "4 3", title: "#5F5F5F", sub: "#5F5F5F" },   // before: grey and dashed, it is gone
    ext: { fill: C.t4, stroke: C.t2, sw: 1.2, title: "#0E5E4C", sub: "#0E5E4C" },   // external or customer: teal
    data: { fill: C.a4, stroke: C.a2, sw: 1.2, title: "#8A4513", sub: "#8A4513" },   // data or storage: amber
    plan: { fill: C.white, stroke: C.n3, sw: 1.2, dash: "4 3", title: C.navy, sub: C.grey },   // proposed: dashed, not built yet
    stop: { fill: "#FDECEA", stroke: "#D64541", sw: 1.2, title: "#9E2A22", sub: "#9E2A22" },   // stopped or failed: red
    hl: { fill: C.hl, stroke: "#D9B92E", sw: 1.2, title: C.navy, sub: "#5A4A00" },   // evidence: the deck's yellow highlight
  },
  dark: {                                                    // the same kinds on dark pages
    "": { fill: "#182232", stroke: "#3A4A63", sw: 1, title: "#E6EDF7", sub: "#A3B0C2" },   // no kind: a box in the panel color
    mine: { fill: "#16263D", stroke: "#6EA8F0", sw: 1.6, title: "#E6EDF7", sub: "#A9C9F5" },   // the person's part: a light blue outline
    key: { fill: "#DCE6F3", stroke: "#DCE6F3", sw: 1, title: "#0F1722", sub: "#2A3A52" },   // core: a light fill with dark text, the inverse of light pages
    old: { fill: "#141B26", stroke: "#3A4A63", sw: 1, dash: "4 3", title: "#A3B0C2", sub: "#A3B0C2" },   // before: darker than a plain box, dashed
    ext: { fill: "#0F2A24", stroke: "#2BB38F", sw: 1.2, title: "#BFEBDD", sub: "#9ED8C5" },   // external: teal on deep green
    data: { fill: "#2E1F12", stroke: "#E08A3E", sw: 1.2, title: "#F6D9BF", sub: "#EBC29C" },   // data: amber on deep brown
    plan: { fill: "#182232", stroke: "#7D8BA0", sw: 1.2, dash: "4 3", title: "#E6EDF7", sub: "#A3B0C2" },   // proposed: a dashed grey outline
    stop: { fill: "#331715", stroke: "#E5534B", sw: 1.2, title: "#F8C9C6", sub: "#F0AFAA" },   // stopped: red on deep red
    hl: { fill: "#3D3610", stroke: "#D9B92E", sw: 1.2, title: "#FFF0A0", sub: "#E9DC8C" },   // evidence: yellow on deep olive
  },
};
// Small square marks (node units, legend swatches) per kind: a fill and an outline
const UNIT = {
  light: { "": [C.b4, C.b3], mine: [C.blue, C.blue], key: [C.navy, C.navy], old: ["#E4E8EE", C.rule], ext: [C.t2, C.t2], data: [C.a2, C.a2],   // light pages: a square takes its kind's box colors
           plan: [C.white, C.n3], stop: ["#D64541", "#D64541"], hl: [C.hl, "#D9B92E"], off: [C.white, C.rule] },   // off is an empty square, a unit not in use
  // The same marks for dark pages
  dark: { "": ["#2D4466", "#3A5578"], mine: ["#6EA8F0", "#6EA8F0"], key: ["#DCE6F3", "#DCE6F3"], old: ["#243045", "#3A4A63"], ext: ["#2BB38F", "#2BB38F"],
          // Off stays an outline on the panel color
          data: ["#E08A3E", "#E08A3E"], plan: ["#182232", "#7D8BA0"], stop: ["#E5534B", "#E5534B"], hl: ["#D9B92E", "#D9B92E"], off: ["#182232", "#3A4A63"] },
};
// Words per language: legend names of the kinds, and the defaults a figure falls back on
const WORDS = {
  ko: { mine: "맡은 부분", key: "핵심", old: "이전", ext: "외부, 고객", data: "데이터, 저장", plan: "제안, 계획", stop: "막힘, 실패", hl: "근거",   // Korean legend names of the kinds
        before: "전", after: "후", yes: "예", partial: "일부", no: "아니오", today: "현재" },   // Korean defaults: metric labels, matrix marks, today's word
  en: { mine: "My part", key: "Core", old: "Before", ext: "External", data: "Data", plan: "Proposed", stop: "Stopped", hl: "Evidence",   // English legend names of the kinds
        before: "Before", after: "After", yes: "yes", partial: "partial", no: "no", today: "Now" },   // English defaults for the same places
};
const KINDS = Object.keys(KIND.light).filter(Boolean);       // the kind names a figure may use

// text helpers

// Fit text to a width by trimming words (or characters when one word is left), so a label never runs out of its box; the cut is reported
function fit(s, size, bold, width, cut, where) {
  let t = String(s ?? "");                                   // the label as given
  if (tw(t, size, bold) <= width) return t;                  // it fits
  const words = t.split(/\s+/);                              // drop words from the end until it fits
  while (words.length > 1 && tw(words.join(" ") + "…", size, bold) > width) words.pop();   // the ellipsis is measured too, so the result still fits
  t = words.join(" ");                                       // the words that fit with room for the ellipsis
  while (t.length > 1 && tw(t + "…", size, bold) > width) t = t.slice(0, -1);   // one long word: drop characters
  t = t + "…";                                               // the ellipsis tells the reader text was cut
  if (cut) cut.push(`${where}: '${s}' was shortened to fit its box`);   // say so (the deck check reports it)
  return tw(t, size, bold) <= width ? t : "";                // a room too narrow for even one letter and the ellipsis shows nothing
}

// Wrap text into lines of a width (Hangul and Latin measured with the real font widths)
function wrap(s, size, width, bold) {
  const words = String(s ?? "").split(/\s+/).filter(Boolean), lines = [];   // words of the text
  let cur = "";                                              // the line being filled
  for (const w of words) {                                   // greedy line filling
    const next = cur ? cur + " " + w : w;                    // the line with this word added
    if (cur && tw(next, size, bold) > width) { lines.push(cur); cur = w; } else cur = next;   // too wide: close the line and start the next with this word (a lone long word stays whole)
  }
  if (cur) lines.push(cur);                                  // the last, partly filled line
  return lines;                                              // empty for blank text
}

// Wrap to at most max lines; the last line is fitted (and the cut reported) when the text runs longer
function lines(s, size, bold, width, max, cut, where) {
  const all = wrap(s, size, width, bold);                    // every line the text needs
  if (all.length <= max) return all.map(l => fit(l, size, bold, width, cut, where));   // a single over-long word is still fitted
  const keep = all.slice(0, max - 1);                        // the lines that stay whole
  keep.push(fit(all.slice(max - 1).join(" "), size, bold, width, cut, where));   // the rest squeezed into the last line
  return keep;                                               // exactly max lines
}

// The y of each line (P.text's y) so the ink of the whole block is centered on cy. specs = [[text, size, bold]], gaps between centers
function block(cy, specs, gaps) {
  return specs.length ? stackY(cy, specs, gaps) : [];       // draw.js measures the ink of the first and the last line
}

// Number text: thousands grouped, at most two decimals, no trailing zeros
function num(v) {
  const r = Math.round(v * 100) / 100;                       // two decimals at most
  return Math.abs(r) >= 1000 ? r.toLocaleString("en-US") : String(r);   // 1,200 but 12.5
}

// Nice axis ticks from lo to hi (1, 2 or 5 times a power of ten)
function ticks(lo, hi, n = 4) {
  const span = hi - lo || Math.abs(hi) || 1;                 // the range to cover
  const raw = span / n, mag = 10 ** Math.floor(Math.log10(raw)), e = raw / mag;   // a step in the right order of magnitude
  const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;   // round it to 1, 2 or 5
  const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, out = [];   // the axis starts and ends on whole steps around the data
  for (let v = a; v <= b + step * 1e-6; v += step) out.push(Math.round(v / step) * step);   // the tick values
  return out;                                                // tick values from a to b
}

// Year-month to a month count ('2024.03' -> 24291); NaN when unreadable
const ym = s => { const m = String(s ?? "").match(/((?:19|20)\d{2})(?:[.\-/](\d{1,2}))?/); return m ? +m[1] * 12 + ((m[2] ? +m[2] : 1) - 1) : NaN; };
const ymText = t => `${Math.floor(t / 12)}.${String((t % 12) + 1).padStart(2, "0")}`;   // a month count back to 'YYYY.MM'

// drawing helpers (palette aware)

// The style of a kind in this figure's scheme; the kind is remembered for the legend
function kindOf(ctx, kind, quiet) {
  const k = KIND[ctx.pal.name][kind] ? kind : "";            // unknown kinds draw as plain boxes
  if (k && ctx.kinds && !quiet) ctx.kinds.add(k);            // the legend lists kinds the data chose (a default look stays out)
  return KIND[ctx.pal.name][k];                              // the box style in this scheme
}

// Text in the scheme's ink unless a color is given
function T(ctx, x, y, s, o = {}) {
  return P.text(x, y, s, { ...o, fill: o.fill ?? ctx.pal.ink });   // dark pages need light ink, so the scheme picks the default
}

// A box with a title and an optional sub line, text centered by its ink, in a kind's colors. o: title, sub, kind, align (center|left),
// size, subSize, mark (a figure-to-card number badge), units (a grid of small squares under the title), unitKinds, fill, titleLines
function box(ctx, x, y, w, h, o = {}) {
  const K = kindOf(ctx, o.kind, o.quiet);                    // colors of the kind
  const size = o.size ?? 12, ss = o.subSize ?? 10.5, pad = o.pad ?? 9;   // title and sub sizes, inner margin
  const left = o.align === "left", markW = o.mark ? 24 : 0; // left aligned or centered; room kept for a badge
  const avail = w - 2 * pad - (left ? markW : 2 * markW);    // text width inside the box
  const parts = [P.rect(x, y, w, h, { fill: o.fill ?? K.fill, stroke: K.stroke, sw: K.sw, r: o.r ?? 4, dash: K.dash,   // a fill given by the caller wins over the kind's
    valign: o.units ? "top" : o.valign })];                  // the box (a box with squares keeps its text at the top)
  const where = `${ctx.where} box`;                          // names the box in cut notes
  const tl = o.title ? lines(o.title, size, true, avail, o.titleLines ?? 2, ctx.cut, where) : [];   // title lines (two at most)
  const unitsH = o.units ? unitRows(o.units, w - 2 * pad, o.unitSize).h + 6 : 0;   // height of the squares under the title
  // Sub lines: as many as the height leaves room for (each 13.5 high); the rest is cut and reported
  const room = Math.max(0, Math.floor((h - 10 - unitsH - tl.length * (size * 1.2) - (tl.length ? 4 : 0)) / (ss * 1.3)));
  let sl = o.sub ? wrap(o.sub, ss, avail).map(l => fit(l, ss, false, avail, ctx.cut, where)) : [];   // the sub text's lines (a word longer than the box is fitted)
  if (sl.length > room) {                                    // more than fits: keep what fits, the last one fitted
    if (room > 0) sl = [...sl.slice(0, room - 1), fit(sl.slice(room - 1).join(" "), ss, false, avail, ctx.cut, where)];   // the overflow squeezed into the last line that fits
    else { if (ctx.cut) ctx.cut.push(`${where}: the note of '${o.title}' did not fit`); sl = []; }   // no room for any sub line: the note goes and the cut says so
  }
  const specs = [...tl.map(t => [t, size, true]), ...sl.map(t => [t, ss, false])];   // every line with its size
  // Center to center gaps: between title lines, title to sub, between sub lines
  const gaps = specs.slice(1).map((s, i) => i < tl.length - 1 ? size * 1.22 : i === tl.length - 1 ? size * 0.55 + ss * 0.55 + 3 : ss * 1.3);
  const textH = specs.length ? gaps.reduce((a, g) => a + g, 0) + (specs[0][1] + specs[specs.length - 1][1]) / 2 : 0;   // first line top to last line foot
  const cy = o.units ? y + 8 + textH / 2 : y + h / 2;        // centered in the box, or on top of the squares
  const ys = block(cy, specs, gaps);                         // ink-centered line positions
  const tx = left ? x + pad : x + w / 2, anchor = left ? "start" : "middle";   // where the text starts
  specs.forEach(([t, z, b], i) => parts.push(P.text(tx, ys[i], t, { size: z, bold: b, anchor, maxw: avail + 0.5,   // every line at its centered y; maxw holds it to the box in the probe
    fill: i < tl.length ? (o.color ?? K.title) : (o.subColor ?? K.sub) })));   // title lines in the title color, sub lines in the sub color
  if (o.units) parts.push(units(ctx, x + pad, cy + textH / 2 + 7, w - 2 * pad, o.units, o.unitKinds, o.unitSize));   // the squares
  if (o.mark) parts.push(D.mark(x + w - 15, specs.length && !o.units ? Math.min(y + 15, ys[0]) : y + 14, o.mark));   // the badge on the title line
  return parts.join("");                                     // the box and its contents as one SVG string
}

// The grid of small squares inside a node: how many rows a count needs at a width
function unitRows(n, width, size = 11) {
  const per = Math.max(1, Math.floor((width + 3) / (size + 3)));   // squares per row
  const rows = Math.ceil(Math.min(n, 48) / per);             // at most 48 squares are drawn
  return { per, rows, h: rows * (size + 3) - 3 };            // the grid's height
}

// The squares themselves (a node's GPUs or members); kinds color them one by one, the rest are plain
function units(ctx, x, y, width, n, kinds = [], size = 11) {
  const { per } = unitRows(n, width, size), out = [];        // squares per row
  for (let i = 0; i < Math.min(n, 48); i++) {                // row by row
    const [f, s] = UNIT[ctx.pal.name][kinds[i] || ""] || UNIT[ctx.pal.name][""];   // colors of this square
    if (kinds[i] && KIND.light[kinds[i]]) ctx.kinds.add(kinds[i]);   // a colored square is a kind for the legend
    out.push(P.rect(x + (i % per) * (size + 3), y + Math.floor(i / per) * (size + 3), size, size, { fill: f, stroke: s, r: 2 }));   // a square on the grid, 3 px apart
  }
  return out.join("");                                       // the squares as one SVG string
}

// A zone or panel: a tinted rectangle with a bold label at the top left (and a badge at the top right). Content starts 26 below its top
function group(ctx, x, y, w, h, label, o = {}) {
  const K = o.kind ? kindOf(ctx, o.kind) : null;             // a zone may carry a kind (my part, external, proposed)
  const fill = o.fill ?? (K && o.kind !== "key" ? (o.kind === "mine" ? ctx.pal.zone2 : K.fill) : ctx.pal.zone);   // tint of the zone
  const stroke = K ? K.stroke : ctx.pal.line, labelColor = K && o.kind !== "key" ? K.title : ctx.pal.ink;   // its outline and label color
  const lw = w - 20 - (o.mark ? 26 : 0) - (o.right ? tw(o.right, 10, false) + 10 : 0);   // room for the label
  const parts = [P.rect(x, y, w, h, { fill, stroke, sw: K ? K.sw : 1, r: 6, dash: K && K.dash })];   // the zone, dashed when its kind is (before, proposed)
  // The bold label at the top left, shortened to the room the note and badge leave
  if (label) parts.push(P.text(x + 10, y + 13, fit(label, 10.5, true, lw, ctx.cut, `${ctx.where} zone`), { size: 10.5, bold: true, fill: labelColor, ls: 0.3, maxw: lw + 2 }));
  if (o.right) parts.push(P.text(x + w - 10 - (o.mark ? 26 : 0), y + 13, o.right, { size: 10, fill: ctx.pal.muted, anchor: "end" }));   // a note at the right
  if (o.mark) parts.push(D.mark(x + w - 15, y + 14, o.mark));   // the figure-to-card badge
  return parts.join("");                                     // the zone as one SVG string
}

// A connector with an arrowhead in the scheme's colors. kind: '' navy, mine blue, old grey dashed, plan dashed
function link(ctx, pts, o = {}) {
  const col = o.kind === "mine" ? "blue" : o.kind === "old" ? "grey" : "navy";   // color by meaning (draw.js: blue is my part, grey the old path)
  if (o.kind === "mine" || o.kind === "old" || o.kind === "plan") ctx.kinds.add(o.kind);   // a colored link needs the legend too
  const d = "M" + pts.map(p => p.map(v => Math.round(v * 10) / 10).join(",")).join(" L");   // the straight segments
  // The scheme's stroke for the color; before and proposed links are dashed
  return P.path(d, { stroke: ctx.pal.arrowColor[col], sw: o.sw ?? 1.4, dash: o.kind === "old" || o.kind === "plan" ? "4 3" : undefined,
    arrow: o.noArrow ? undefined : ctx.pal.arrow[col], free: o.free });   // the scheme's arrowhead; free keeps snapArrows off this link
}

// A plain line in the scheme (no arrowhead): gridlines, tree branches, fabric links
function line(ctx, x1, y1, x2, y2, o = {}) {
  return P.line(x1, y1, x2, y2, { stroke: o.stroke ?? ctx.pal.line, sw: o.sw ?? 1, dash: o.dash });   // the scheme's rule color unless one is given
}

// A short label pill on a link (a protocol or what flows); white with a dark outline, as draw.js D.proto
function pill(ctx, x, y, s) {
  const w = tw(s, 10, true) + 12;                            // its width
  return P.rect(x - w / 2, y - 8, w, 16, { fill: ctx.pal.panel, stroke: ctx.pal.ink, r: 8 }) +   // a rounded pill centered on the point; its panel fill hides the link under it
    P.text(x, y, s, { size: 10, bold: true, fill: ctx.pal.ink, anchor: "middle" });   // the label centered in it
}
const pillW = s => tw(s, 10, true) + 12;                     // a pill's width

// The legend of the kinds a figure drew, in one row from x; returns { svg, h }. Words come from the figure's legend, else the language
function legend(ctx, x, y, w, extra = []) {
  // A template's own items first, then the kinds in the order they were drawn
  const items = [...extra, ...[...ctx.kinds].filter(k => KINDS.includes(k)).map(k => ({ k, t: (ctx.legend && ctx.legend[k]) || WORDS[ctx.lang][k] }))];
  if (!items.length) return { svg: "", h: 0 };               // nothing colored: no legend
  const out = [];                                            // swatch and word parts
  let lx = x;                                                // the legend runs left to right
  for (const it of items) {                                  // one swatch and word per item
    const tWidth = tw(it.t, 10, false);                      // the word's width
    if (lx + 16 + tWidth > x + w) break;                     // no room for more (the words are short; this only guards odd data)
    const [f, s] = UNIT[ctx.pal.name][it.k] || [it.fill, it.fill];   // the swatch colors
    // The swatch, dashed for the dashed kinds so it matches their boxes
    out.push(P.rect(lx, y - 5, 10, 10, { fill: it.fill ?? f, stroke: it.stroke ?? s, r: 2, dash: it.k === "old" || it.k === "plan" ? "2 2" : undefined }),
      P.text(lx + 15, y, it.t, { size: 10, fill: ctx.pal.muted }));   // swatch and word
    lx += 15 + tWidth + 16;                                  // the next item
  }
  return { svg: out.join(""), h: 18 };                       // one legend row, 18 px tall
}

// templates
// Each draws into B = { x, y, w, h } and returns { parts: [svg strings], h: used height }

// Steps left to right. Up to five fit one row; more wrap to a second row that runs right to left under the first (a snake), so every
// arrow stays short and horizontal or vertical. The last step is the outcome (dark) unless the data gives kinds
function pipeline(fig, B, ctx) {
  const steps = fig.steps.map(s => (Array.isArray(s) ? s : typeof s === "object" ? [s.title, s.sub, s.kind, s.mark] : [s, ""]));   // [title, sub, kind, mark]
  // Boxes per row: up to five, fewer when the width would make a box narrower than about 104 px (a step name in two lines); the rows
  // snake back and forth so every arrow stays short and straight
  const fitPer = Math.max(2, Math.floor((B.w - 12 + 30) / (104 + 30)));
  const n = steps.length, gapX = Math.max(26, Math.min(40, B.w * 0.045));   // the step count, the gap between boxes
  const kinds = steps.some(s => s[2]);                       // the data colors its own steps
  const legRoom = kinds ? 24 : 0;                            // a legend row under the boxes when the data colors its steps
  const widthAt = per => (B.w - 12 - gapX * (per - 1)) / per;   // box width with per boxes in a row
  // What the tallest step needs at a box width (two title lines and its note)
  const needAt = bw0 => Math.max(...steps.map(([t, sub]) => 18 + Math.min(2, wrap(t, 12.5, bw0 - 18, true).length) * 15.5 + (sub ? wrap(sub, 10.5, bw0 - 18).length * 13.7 + 4 : 0)));
  const bandAt = per => new Set((fig.groups || []).filter(([, a]) => a >= 0 && a < n).map(([, a]) => Math.floor(a / per)));   // the rows bands start on
  // The height a layout of so many rows needs: a first-row band's label, the boxes, the turns, later bands' labels, the legend
  const heightAt = rw => { const per = Math.ceil(n / rw), bs = bandAt(per); return (bs.has(0) ? 34 : 4) + rw * needAt(widthAt(per)) + 26 * (rw - 1) + 30 * [...bs].filter(r => r > 0).length + 10 + legRoom; };
  let rows = Math.ceil(n / Math.min(5, fitPer));             // the snake's rows
  const longest = Math.max(...steps.map(([t]) => Math.max(0, ...String(t ?? "").split(/\s+/).map(w => tw(w, 12.5, true)))));   // the widest title word, which cannot wrap
  // A short frame (the side column) keeps up to six steps on one row when the snake would not fit its height and every title word
  // still fits a box: one row of narrower boxes needs far less height than two rows
  if (rows > 1 && n <= 6 && longest <= widthAt(n) - 18 && heightAt(rows) > B.h && heightAt(1) < heightAt(rows)) rows = 1;
  const perRow = Math.ceil(n / rows);                        // boxes per row
  // Bands as [label, first index, last index]; one that names no step is reported and left out
  const groups = (fig.groups || []).filter(([label, a]) => (a >= 0 && a < n) || (ctx.cut.push(`${ctx.where}: the band '${label}' names no step and was left out`), false));
  const bandRows = bandAt(perRow);                           // the rows a band starts on; each needs room above it for the band's label
  const top = B.y + (bandRows.has(0) ? 34 : 4);              // room for a first-row band
  const extra = [...bandRows].filter(r => r > 0).length * 30;   // the label room of bands on later rows
  const bw = widthAt(perRow);                                // box width
  const need = needAt(bw);                                   // box height: what the tallest step needs, within what the frame allows (below)
  const gapY = rows > 1 ? Math.max(26, Math.min(46, (B.h - (top - B.y) - 10 - legRoom - extra - rows * Math.min(need, 90)) / (rows - 1))) : 46;   // the turn's room
  const bh = Math.max(40, Math.min(fig.boxH || 150, need, (B.h - (top - B.y) - 10 - legRoom - extra - gapY * (rows - 1)) / rows));   // box height: what the steps need, within the frame's share per row
  const rowTop = [top];                                      // each row's top: the row above, its gap, and a band's label room when one starts here
  for (let r = 1; r < rows; r++) rowTop.push(rowTop[r - 1] + bh + gapY + (bandRows.has(r) ? 30 : 0));
  const parts = [], pos = steps.map((_, i) => {              // box positions, the second row reversed
    const r = Math.floor(i / perRow), k = i % perRow, col = r % 2 ? perRow - 1 - k : k;   // every second row runs right to left (the snake)
    return { x: B.x + 6 + col * (bw + gapX), y: rowTop[r] };   // the box's top left
  });
  groups.forEach(([label, a, b], gi) => {                    // a band over a run of steps in one row
    const r = Math.floor(a / perRow), last = Math.max(a, Math.min(b, n - 1, (r + 1) * perRow - 1));   // a band ends with its row (the next row runs back under it)
    const xa = Math.min(pos[a].x, pos[last].x) - 5, xb = Math.max(pos[a].x, pos[last].x) + bw + 5;   // the band spans its steps, whichever way the row runs
    // On a later row the turn arrow comes down into the row's first step; a label that would sit across it is reported and the band left out
    const turnX = r > 0 ? pos[r * perRow].x + bw / 2 : null, lw = tw(fit(label, 10.5, true, xb - xa - 20), 10.5, true);
    if (turnX !== null && turnX > xa + 4 && turnX < xa + 10 + lw + 6) { ctx.cut.push(`${ctx.where}: the band '${label}' would sit across the turn arrow and was left out`); return; }
    parts.push(group(ctx, xa, rowTop[r] - 30, xb - xa, bh + 37, label, { fill: gi % 2 ? ctx.pal.zone2 : ctx.pal.zone }));   // the band behind its steps; neighbors alternate tints
  });
  steps.forEach(([t, sub, kind, mark], i) => {               // the step boxes
    const p = pos[i], k = kinds ? kind : i === n - 1 ? "key" : "";   // the outcome step is dark
    parts.push(box(ctx, p.x, p.y, bw, bh, { title: t, sub, kind: k, size: 12.5, subSize: 10.5, mark, quiet: !kinds }));   // quiet: the default outcome color adds no legend
    if (i + 1 < n) {                                         // the arrow to the next step
      const q = pos[i + 1];                                  // the next box
      // Same row: side to side, rightward on a forward row, leftward on one that runs back
      if (q.y === p.y) parts.push(link(ctx, q.x > p.x ? [[p.x + bw, p.y + bh / 2], [q.x, q.y + bh / 2]] : [[p.x, p.y + bh / 2], [q.x + bw, q.y + bh / 2]]));
      else parts.push(link(ctx, [[p.x + bw / 2, p.y + bh], [q.x + bw / 2, q.y]]));   // the turn: straight down
    }
  });
  const foot = rowTop[rows - 1] + bh;                        // the bottom of the last row of boxes
  const lg = legend(ctx, B.x + 6, foot + 16, B.w - 12);      // kinds used by the data
  parts.push(lg.svg);                                        // empty when the steps have no kinds
  return { parts, h: foot - B.y + 10 + (lg.h ? lg.h + 6 : 0) };   // the height used, so the frame can end under the content
}

// Two panels: before (the old structure) and after (the new one), with one arrow between them. A side may chain its items with arrows
// (flow: true) and carry a note line at its foot; change is a short word over the arrow. The panels are as tall as their items need
function beforeAfter(fig, B, ctx) {
  const W0 = WORDS[ctx.lang], gap = fig.change ? Math.max(70, tw(fig.change, 10, true) + 22) : 64;   // the gap holds the arrow (and its word)
  const pw = (B.w - gap - 8) / 2, parts = [];                // panel width
  // Items as [title, sub, kind, mark], given as lists, objects or plain strings
  const norm = sd => (sd.items || []).map(it => (Array.isArray(it) ? it : typeof it === "object" ? [it.title, it.sub, it.kind, it.mark] : [it, ""]));
  const sides = [fig.before || {}, fig.after || {}].map(sd => {   // what each side needs: item height, gaps, foot note
    const items = norm(sd), g = sd.flow ? 22 : 10;           // chained items need room for their arrows
    const noteL = sd.note ? lines(sd.note, 10.5, false, pw - 24, 2, ctx.cut, `${ctx.where} note`) : [];   // the foot note, two lines at most
    // The tallest item: up to two title lines and three sub lines
    const need = Math.max(...items.map(([t, sub]) => 16 + Math.min(2, wrap(t, 12, pw - 46, true).length) * 14.6 + (sub ? Math.min(3, wrap(sub, 10.5, pw - 46).length) * 13.7 + 4 : 0)));
    return { sd, items, g, noteL, footH: noteL.length ? noteL.length * 14 + 8 : 0, need: Math.max(34, Math.min(76, need)) };   // an item box between 34 and 76 px tall
  });
  // The panel height: the taller side's items at their own height (a little looser when the frame has room), within the frame
  const content = sd => 30 + sd.items.length * sd.need + sd.g * (sd.items.length - 1) + 12 + sd.footH;
  const ph = Math.min(B.h - 8, Math.max(...sides.map(content)) * 1.12 + 6);   // 12% looser than needed, never taller than the frame
  const side = (x, S, isAfter) => {                          // one side: a titled zone with stacked item boxes
    const { sd, items, g, noteL, footH } = S;                // what this side needs, measured above
    // The side's zone, titled before or after in the edition's words unless the data names it
    parts.push(group(ctx, x, B.y + 4, pw, ph, sd.title || (isAfter ? W0.after : W0.before), { fill: isAfter ? ctx.pal.zone2 : ctx.pal.zone, kind: sd.kind, mark: sd.mark }));
    const n = Math.max(1, items.length), avail = ph - 34 - footH - 6;   // height for the items
    const ih = Math.max(30, Math.min(S.need * 1.1, (avail - g * (n - 1)) / n));   // item box height
    const y0 = B.y + 4 + 30 + Math.max(0, (avail - (ih * n + g * (n - 1))) / 2);   // the stack centered under the title
    items.forEach(([t, sub, kind, mark], i) => {             // one box per item
      const y = y0 + i * (ih + g);                           // this item's top
      // The new side reads as the person's part by default, without a legend entry
      parts.push(box(ctx, x + 14, y, pw - 28, ih, { title: t, sub, kind: kind || (isAfter ? "mine" : ""), quiet: !kind, size: 12, subSize: 10.5, mark,
        color: !kind && !isAfter ? ctx.pal.muted : undefined }));   // the old side reads grey unless the data says otherwise
      // A flow side chains its items downward; the old side's arrows are grey and dashed
      if (sd.flow && i + 1 < n) parts.push(link(ctx, [[x + pw / 2, y + ih], [x + pw / 2, y + ih + g]], { kind: isAfter ? "" : "old", quiet: true }));
    });
    noteL.forEach((l, k) => parts.push(T(ctx, x + 12, B.y + 4 + ph - footH + 6 + k * 14 + 6, l, { size: 10.5, fill: ctx.pal.body, maxw: pw - 22 })));   // the foot note at the bottom of the zone
    foot = Math.max(foot, y0 + n * ih + g * (n - 1) + footH + 10 - B.y);   // where this side's content really ends
  };
  let foot = 0;                                              // the lower of the two sides' content
  side(B.x + 4, sides[0], false);                            // the old structure on the left
  side(B.x + B.w - pw - 4, sides[1], true);                  // the new one on the right
  const ay = B.y + 4 + ph / 2;                               // the change itself, across the middle
  parts.push(link(ctx, [[B.x + 4 + pw, ay], [B.x + B.w - pw - 4, ay]], { sw: 2 }));   // a heavier arrow from the old side to the new
  // The change word over the arrow, shortened to the gap
  if (fig.change) parts.push(T(ctx, B.x + B.w / 2, ay - 14, fit(fig.change, 10, true, gap - 10, ctx.cut, `${ctx.where} change`), { size: 10, bold: true, anchor: "middle", fill: ctx.pal.muted, maxw: gap - 8 }));
  return { parts, h: Math.max(ph + 8, foot) };               // the zones, or the content when it runs lower
}

// Horizontal bars, one per row, value at the end, a value axis under them; rows named in highlight (or with a kind) stand out
function bars(fig, B, ctx) {
  const rows = fig.rows, unit = fig.unit || "", hi = new Set(fig.highlight || []);   // rows, value unit, highlighted labels
  const max = Math.max(...rows.map(r => r[1])) || 1, tk = ticks(0, max, 4), top = tk[tk.length - 1] || 1;   // the axis
  const noteL = fig.note ? lines(fig.note, 10.5, false, B.w - 12, 2, ctx.cut, `${ctx.where} note`) : [];   // a note under the axis
  const lab = Math.min(B.w * 0.38, Math.max(...rows.map(r => tw(r[0], 12, true))) + 16);   // label column
  const vw = Math.max(...rows.map(r => tw(num(r[1]) + unit, 11.5, true))) + 14;   // room for the value text
  const axisH = 22, footH = noteL.length * 14 + (noteL.length ? 6 : 0);   // axis band and note
  const x0 = B.x + lab, barW = B.w - lab - vw - 6;           // where bars start and how long the longest may be
  const legRoom = rows.some(r => r[2]) ? 26 : 2;              // a legend row when rows carry kinds
  const rowH = Math.max(26, Math.min(44, (B.h - 6 - axisH - footH - legRoom) / rows.length)), bh = Math.min(24, rowH * 0.58);   // row and bar heights
  const X = v => x0 + barW * v / top, parts = [];            // value to x
  const yb = B.y + 6 + rows.length * rowH;                   // the axis line
  tk.forEach(v => {                                          // gridlines and tick labels
    parts.push(line(ctx, X(v), B.y + 4, X(v), yb, { stroke: ctx.pal.grid }));   // a light gridline behind the bars
    parts.push(T(ctx, X(v), yb + 11, num(v), { size: 10, fill: ctx.pal.muted, anchor: "middle" }));   // its value under the axis
  });
  parts.push(line(ctx, x0, yb, x0 + barW, yb, { stroke: ctx.pal.faint }));   // the axis
  rows.forEach(([name, v, kind], i) => {                     // one bar per row, top to bottom in the data's order
    const y = B.y + 6 + i * rowH + (rowH - bh) / 2, on = hi.has(name) || kind === "mine";   // bar top, centered in its row
    const w = Math.max(2, X(v) - x0);                        // bar length (a zero still shows a sliver)
    // The row name right-aligned before the bar, centered on it by its ink
    parts.push(T(ctx, x0 - 10, block(y + bh / 2, [[name, 12, true]])[0], fit(name, 12, true, lab - 16, ctx.cut, `${ctx.where} label`), { size: 12, bold: true, anchor: "end", maxw: lab - 14 }));
    const f = kind && UNIT[ctx.pal.name][kind] ? UNIT[ctx.pal.name][kind][0] : on ? ctx.pal.accent : ctx.pal.soft2;   // bar color
    if (kind) kindOf(ctx, kind);                             // a kind joins the legend
    parts.push(P.rect(x0, y, w, bh, { fill: f, r: 3 }));     // the bar
    // The value at the bar's end, bold and accented on a highlighted row
    parts.push(T(ctx, x0 + w + 7, block(y + bh / 2, [[num(v) + unit, 11.5, on]])[0], num(v) + unit, { size: 11.5, bold: on, fill: on ? ctx.pal.accentText : ctx.pal.muted }));
  });
  noteL.forEach((l, k) => parts.push(T(ctx, B.x + 6, yb + axisH + 4 + k * 14, l, { size: 10.5, fill: ctx.pal.body, maxw: B.w - 10 })));   // the note lines under the axis
  const lg = legend(ctx, B.x + 6, yb + axisH + footH + 10, B.w - 12);   // the kinds the rows used, under the note
  parts.push(lg.svg);                                        // empty when no row has a kind
  return { parts, h: yb - B.y + axisH + footH + (lg.h ? lg.h + 8 : 2) };   // the height used, so the frame ends under it
}

// Rows against columns. A cell is "yes", "partial", "no", "" or short text; marks get a legend so color is never the only sign.
// groups put a band over runs of columns; highlight tints one column (the option chosen)
function matrix(fig, B, ctx) {
  const cols = fig.cols, rows = fig.rows, W0 = WORDS[ctx.lang];   // column heads and rows
  const groups = fig.groups || [], gH = groups.length ? 24 : 0;   // the group band above the heads
  const hiCol = typeof fig.highlight === "number" ? fig.highlight : cols.indexOf(fig.highlight);   // the tinted column
  const nameW = Math.min(B.w * 0.34, Math.max(...rows.map(r => tw(r[0], 12, true))) + 22);   // the row-name column
  const cw = (B.w - nameW - 8) / cols.length, headH = 32, legendH = 22;   // column width, head row and legend
  const rh = Math.max(28, Math.min(40, (B.h - gH - headH - legendH - 8) / rows.length));   // row height
  const parts = [], x0 = B.x + 4 + nameW, y0 = B.y + 2 + gH;   // where the cells start
  if (hiCol >= 0) parts.push(P.rect(x0 + hiCol * cw + 2, y0 + headH - 2, cw - 4, rows.length * rh + 2, { fill: ctx.pal.zone2, r: 3 }));   // the chosen column's tint
  groups.forEach(([label, a, b]) => {                        // bands over column runs
    const xa = x0 + a * cw + 2, xb = x0 + (Math.min(b, cols.length - 1) + 1) * cw - 2;   // the band's ends, clipped to the last column, inset from the column edges
    parts.push(P.rect(xa, B.y + 2, xb - xa, gH - 4, { fill: ctx.pal.zone, stroke: ctx.pal.line, r: 4 }));   // the band's box above the heads
    // The band's label centered in it, shortened to its width
    parts.push(T(ctx, (xa + xb) / 2, block(B.y + gH / 2, [[label, 10.5, true]])[0], fit(label, 10.5, true, xb - xa - 12, ctx.cut, `${ctx.where} group`), { size: 10.5, bold: true, anchor: "middle", maxw: xb - xa - 10 }));
  });
  cols.forEach((c, j) => {                                   // the column heads
    const x = x0 + j * cw, t = fit(c, 11.5, true, cw - 14, ctx.cut, `${ctx.where} column`);   // the column's left edge and its head, shortened to the column
    parts.push(P.rect(x + 2, y0, cw - 4, headH - 6, { fill: j === hiCol ? ctx.pal.accent : ctx.pal.strong, r: 4 }));   // a dark head cell; the chosen column's in the accent color
    parts.push(T(ctx, x + cw / 2, block(y0 + (headH - 6) / 2, [[t, 11.5, true]])[0], t, { size: 11.5, bold: true, anchor: "middle", maxw: cw - 10,   // the head centered in its cell
      // Text in contrast to its cell: white on the light accent, dark on the dark scheme's light fills
      fill: j === hiCol ? (ctx.pal.name === "dark" ? ctx.pal.onStrong : C.white) : ctx.pal.onStrong }));
  });
  const yes = ctx.pal.name === "dark" ? ctx.pal.accent : C.blue;   // the mark color
  const mark = (x, y, v) => {                                // one cell mark
    if (v === "yes") return P.circle(x, y, 7, { fill: yes });   // a full dot
    if (v === "partial") return P.circle(x, y, 7, { fill: ctx.pal.panel, stroke: yes, sw: 2 }) + `<path d="M${x} ${y - 7} A7 7 0 0 1 ${x} ${y + 7} Z" fill="${yes}"/>`;   // a half dot
    if (v === "no") return P.line(x - 6, y, x + 6, y, { stroke: ctx.pal.faint, sw: 2 });   // a dash
    return "";                                               // an empty cell
  };
  rows.forEach((r, i) => {                                   // one row per entry
    const y = y0 + headH + i * rh;                           // the row's top under the heads
    if (i % 2 === 0) parts.push(P.rect(B.x + 2, y, nameW + 2, rh, { fill: ctx.pal.zone, r: 0, deco: true }));   // zebra band on the names
    // The row name at the left, shortened to the name column
    parts.push(T(ctx, B.x + 12, block(y + rh / 2, [[r[0], 12, true]])[0], fit(r[0], 12, true, nameW - 18, ctx.cut, `${ctx.where} row`), { size: 12, bold: true, maxw: nameW - 14 }));
    r.slice(1).forEach((v, j) => {                           // the cells
      const cx = x0 + j * cw + cw / 2, cy = y + rh / 2;      // the cell's center
      if (["yes", "partial", "no", ""].includes(v)) parts.push(mark(cx, cy, v));   // a mark word draws as its sign
      // Any other value is short text, shortened to the cell
      else { const t = fit(v, 11, false, cw - 14, ctx.cut, `${ctx.where} cell`); parts.push(T(ctx, cx, block(cy, [[t, 11, false]])[0], t, { size: 11, fill: ctx.pal.body, anchor: "middle", maxw: cw - 10 })); }
    });
  });
  const used = new Set(rows.flatMap(r => r.slice(1)));       // a legend for the marks that appear
  let lx = B.x + 6;                                          // the legend runs left to right
  const tableEnd = y0 + headH + rows.length * rh, ly = tableEnd + 13;   // the legend right under the table
  for (const [k, label] of [["yes", fig.yes || W0.yes], ["partial", fig.partial || W0.partial], ["no", fig.no || W0.no]]) {   // each mark with its word; the data may rename them
    if (!used.has(k)) continue;                              // only marks the table shows
    parts.push(mark(lx + 7, ly, k), T(ctx, lx + 20, ly, label, { size: 10.5, fill: ctx.pal.muted }));   // the sign, then its word
    lx += 30 + tw(label, 10.5) + 14;                         // past the word to the next item
  }
  return { parts, h: tableEnd - B.y + legendH + 4 };         // the table and its legend row
}

// The month axis shared by phases, timeline and gantt: ticks every year, quarter or month, labels kept inside the frame
function monthAxis(ctx, X, lo, hi, yTop, yAxis, xMin, xMax) {
  const span = hi - lo, step = span > 48 ? 12 : span > 18 ? 6 : span > 8 ? 3 : 1, parts = [];   // tick step in months
  const first = step === 12 ? Math.ceil(lo / 12) * 12 : Math.ceil(lo / step) * step;   // ticks on round months
  for (let t = first; t <= hi; t += step) {                  // the ticks
    const x = X(t);                                          // the tick's x
    parts.push(P.line(x, yTop, x, yAxis, { stroke: ctx.pal.grid, deco: true }));   // a faint vertical line
    const yy = Math.floor(t / 12), mm = (t % 12) + 1;        // the month count back to year and month
    const label = step === 12 ? String(yy) : `${String(yy).slice(2)}.${String(mm).padStart(2, "0")}`;   // '2024' or '24.03'
    if (x + tw(label, 10) / 2 > xMax || x - tw(label, 10) / 2 < xMin) continue;   // a label never runs past the frame or into the names
    parts.push(T(ctx, x, yAxis + 11, label, { size: 10, fill: ctx.pal.muted, anchor: "middle" }));   // the label under the axis line
  }
  parts.push(line(ctx, xMin, yAxis, xMax, yAxis, { stroke: ctx.pal.faint }));   // the axis line
  return parts.join("");                                     // the axis as one SVG string
}

// Named periods on a month axis (YYYY.MM). A row without an end runs to the latest end
function phases(fig, B, ctx) {
  const rows = fig.rows.map(([n, a, b, note]) => [n, ym(a), Number.isFinite(ym(b)) ? ym(b) + 1 : NaN, note]);   // a period runs through its last month
  const lo = Math.min(...rows.map(r => r[1])), hi = Math.max(...rows.map(r => (Number.isFinite(r[2]) ? r[2] : r[1] + 1)));   // first start to last end; a row without an end counts one month
  // The name column: as wide as the longest name up to 38% of the frame; a longer name takes a second line (the row grows for it)
  const nameW = Math.min(B.w * 0.38, Math.max(...rows.map(r => tw(r[0], 12, true))) + 18);
  const names = rows.map(r => lines(r[0], 12, true, nameW - 16, 2, ctx.cut, `${ctx.where} name`));   // one or two lines a name
  const X = t => B.x + nameW + (B.w - nameW - 12) * (t - lo) / Math.max(1, hi - lo);   // month to x
  const two = names.some(l => l.length > 1);                 // a two-line name sets a taller row
  // Row height between 28 (36 with two-line names) and 44, the bar about 60% of it
  const axisH = 24, rh = Math.max(two ? 36 : 28, Math.min(44, (B.h - axisH - 8) / rows.length)), bh = Math.min(26, rh * 0.62), parts = [];
  const yAx = B.y + 6 + rows.length * rh;                    // the axis under the rows
  parts.push(monthAxis(ctx, X, lo, hi, B.y + 2, yAx, B.x + nameW - 4, B.x + B.w - 2));   // gridlines and labels between the name column and the right edge
  rows.forEach(([n, a, b, note], i) => {                     // one bar per period, in the data's order
    const y = B.y + 4 + i * rh + (rh - bh) / 2, end = Number.isFinite(b) ? b : hi, last = i === rows.length - 1;   // bar top; an open period runs to the latest end; the last row stands out
    const nl = names[i], ys = block(y + bh / 2, nl.map(t => [t, 12, true]), nl.length > 1 ? [14] : []);   // the name, centered on its bar
    nl.forEach((t, k) => parts.push(T(ctx, B.x + nameW - 10, ys[k], t, { size: 12, bold: true, anchor: "end", maxw: nameW - 14 })));   // the name right-aligned against the axis
    const x0 = X(a), x1 = Math.max(x0 + 6, X(end));          // the bar's ends (a one-month phase still shows)
    parts.push(P.rect(x0, y, x1 - x0, bh, { fill: last ? ctx.pal.strong : ctx.pal.soft2, r: 4 }));   // the bar, dark for the last period
    if (note) {                                              // a note inside the bar when it fits, else beside it
      const nw = tw(note, 10.5), inside = nw + 14 < x1 - x0; // the note fits inside with 7 px on each side
      // The room after the bar (to the frame's edge) and before it (back to the name column)
      const after = B.x + B.w - x1 - 12, before = x0 - (B.x + nameW) - 14;
      const right = inside || after >= nw || after >= before;   // after the bar unless the room before it is the larger and the note needs it
      const room = inside ? x1 - x0 - 10 : right ? after : before;   // the width the note may take
      const t = inside ? note : fit(note, 10.5, false, room, ctx.cut, `${ctx.where} note`);   // shortened to that room (nothing when no letter fits)
      // Inside the bar from its start, after its end, or right-aligned before its start; colors that read on the bar (muted beside it)
      if (t) parts.push(T(ctx, inside ? x0 + 7 : right ? x1 + 7 : x0 - 7, block(y + bh / 2, [[t, 10.5, false]])[0], t, { size: 10.5, anchor: inside || right ? "start" : "end",
        fill: inside ? (last ? ctx.pal.onStrong : ctx.pal.name === "dark" ? ctx.pal.ink : C.navy) : ctx.pal.muted, maxw: room + 2 }));
    }
  });
  return { parts, h: yAx - B.y + axisH };                    // the rows and the axis band
}

// Groups of nodes: one panel per group with small squares in proportion; the count is written, the squares only show proportion
function cluster(fig, B, ctx) {
  const groups = fig.groups, n = groups.length;              // the groups and their number
  const cols = n > 3 ? Math.min(3, Math.ceil(n / 2)) : n, rowsN = Math.ceil(n / cols), gap = 12;   // up to three side by side
  const gw = (B.w - gap * (cols - 1) - 8) / cols, max = Math.max(...groups.map(g => g[1])) || 1, parts = [];   // panel width, scale
  const sz = 13, per = Math.max(1, Math.floor((gw - 24 + 4) / (sz + 4)));   // square size and squares per row
  const k = c => Math.max(1, Math.round(Math.min(40, per * 4) * c / max));   // squares in proportion to the largest group
  const rowsQ = Math.ceil(k(max) / per), noteH = groups.some(g => g[2]) ? 22 : 8;   // square rows of the largest group, note room
  const gh = Math.min((B.h - gap * (rowsN - 1) - 8) / rowsN, 28 + rowsQ * (sz + 4) + noteH + 4);   // panel height from its squares
  groups.forEach(([name, count, note, kind], i) => {         // one panel per group, row by row
    const x = B.x + 4 + (i % cols) * (gw + gap), y = B.y + 4 + Math.floor(i / cols) * (gh + gap);   // the panel's place in the grid
    parts.push(group(ctx, x, y, gw, gh, name, { right: num(count) + (fig.unit || ""), kind }));   // the panel titled by name, the written count at its right
    for (let j = 0; j < k(count); j++) {                     // the squares, row by row
      const cx = x + 12 + (j % per) * (sz + 4), cy = y + 26 + Math.floor(j / per) * (sz + 4);   // the square's place under the panel title
      if (cy + sz > y + gh - noteH) break;                   // keep inside the panel
      const [f, st] = UNIT[ctx.pal.name][kind || ""] || UNIT[ctx.pal.name][""];   // the group's kind colors its squares; unknown kinds look plain
      parts.push(P.rect(cx, cy, sz, sz, { fill: f, stroke: st, r: 2 }));   // one square
    }
    // The note at the foot of the panel, shortened to its width
    if (note) parts.push(T(ctx, x + 12, y + gh - 12, fit(note, 10.5, false, gw - 24, ctx.cut, `${ctx.where} note`), { size: 10.5, fill: ctx.pal.muted, maxw: gw - 20 }));
  });
  return { parts, h: rowsN * gh + gap * (rowsN - 1) + 8 };   // the height of the panel rows
}

// Lanes for periods that overlap: each item joins the first lane that ended before it starts
function lanesOf(items) {
  const ends = [];                                           // the end of the last item in each lane
  // Per item the first lane free by its start (else a new lane); n is the lane count
  return { lane: items.map(([a, b]) => { let k = ends.findIndex(e => e <= a); if (k < 0) { k = ends.length; ends.push(b); } else ends[k] = b; return k; }), n: Math.max(1, ends.length) };
}

// A project timeline: phases as bars in lanes (overlapping phases take separate lanes, tracks name them), milestones as diamonds on a
// band above with a guide line down to the axis. Labels go inside bars when they fit, else beside them
function timeline(fig, B, ctx) {
  const ph = (fig.phases || []).map(r => (Array.isArray(r) ? r : [r.name, r.start, r.end, r.note, r.kind, r.track]));   // [name, start, end, note, kind, track]
  const ms = (fig.milestones || []).map(r => (Array.isArray(r) ? r : [r.label, r.date, r.kind]));   // [label, date, kind]
  const items = ph.map(r => [ym(r[1]), Number.isFinite(ym(r[2])) ? ym(r[2]) + 1 : ym(r[1]) + 1]);   // months, through the last month
  const all = [...items.flat(), ...ms.map(m => ym(m[1])), ...ms.map(m => ym(m[1]) + 1)].filter(Number.isFinite);   // every month the figure shows, so the axis covers phases and milestones
  // The axis range: the data's own, unless start or end is given
  const lo = Number.isFinite(ym(fig.start)) ? ym(fig.start) : Math.min(...all), hi = Number.isFinite(ym(fig.end)) ? ym(fig.end) + 1 : Math.max(...all);
  const tracks = fig.tracks || null;                         // named lanes, or lanes found by overlap
  // A phase's track picks its lane (clamped to the tracks), else lanes come from overlap
  const L = tracks ? { lane: ph.map(r => Math.max(0, Math.min(tracks.length - 1, +r[5] || 0))), n: tracks.length } : lanesOf(items);
  const nameW = tracks ? Math.min(B.w * 0.26, Math.max(...tracks.map(t => tw(t, 11.5, true))) + 16) : 0;   // the track names
  const x0 = B.x + 6 + nameW, x1 = B.x + B.w - 8, X = t => x0 + (x1 - x0) * (t - lo) / Math.max(1, hi - lo);   // month to x
  const msH = ms.length ? 52 : 0, axisH = 24, legH = 20;     // the milestone band, axis band, legend row
  const legRoom = ph.some(r => r[4]) || ms.some(m => m[2]) ? 26 : 2;   // a legend row under the axis when phases or milestones carry kinds
  // Lanes under the milestone band, 34 to 50 px each, bars 10 px shorter than their lane
  const laneTop = B.y + 4 + msH, laneH = Math.max(34, Math.min(50, (B.h - 8 - msH - axisH - legRoom) / L.n)), bh = Math.min(32, laneH - 10);
  const yAxis = laneTop + L.n * laneH + 4, parts = [];       // the axis under the lanes
  parts.push(monthAxis(ctx, X, lo, hi, laneTop - 2, yAxis, x0 - 4, x1 + 2));   // gridlines behind the lanes, labels under them
  // The track names in the left column, one per lane
  if (tracks) tracks.forEach((t, i) => parts.push(T(ctx, B.x + 6, block(laneTop + i * laneH + laneH / 2, [[t, 11.5, true]])[0], fit(t, 11.5, true, nameW - 12, ctx.cut, `${ctx.where} track`), { size: 11.5, bold: true, maxw: nameW - 10 })));
  ph.forEach(([name, , , note, kind], i) => {                // the phase bars
    const [a, b] = items[i], y = laneTop + L.lane[i] * laneH + (laneH - bh) / 2;   // the phase's months and its lane's bar top
    const xa = X(a) + 1, xb = Math.max(xa + 8, X(b) - 1);    // a small gap between neighbors in a lane
    const K = kindOf(ctx, kind || "");                       // colors of the kind (plain bars use the soft shade)
    // The bar in its kind's style, or the soft shade when it has none
    parts.push(P.rect(xa, y, xb - xa, bh, { fill: kind ? K.fill : ctx.pal.soft, stroke: kind ? K.stroke : ctx.pal.soft2, sw: kind ? K.sw : 1, r: 4, dash: kind ? K.dash : undefined }));
    const tc = kind ? K.title : ctx.pal.ink, sc = kind ? K.sub : ctx.pal.body;   // text colors on the bar
    const room = xb - xa - 14, two = note && bh >= 28 && tw(note, 10, false) <= room && tw(name, 11.5, true) <= room;   // name and note both inside
    if (two) {                                               // name over note, both inside the bar
      const ys = block(y + bh / 2, [[name, 11.5, true], [note, 10, false]], [12.5]);   // two lines centered on the bar
      // The name and the note, held to the bar's inner width
      parts.push(T(ctx, xa + 7, ys[0], name, { size: 11.5, bold: true, fill: tc, maxw: room + 1 }), T(ctx, xa + 7, ys[1], note, { size: 10, fill: sc, maxw: room + 1 }));
    } else if (tw(name, 11.5, true) <= room) {               // the name inside
      parts.push(T(ctx, xa + 7, block(y + bh / 2, [[name, 11.5, true]])[0], name, { size: 11.5, bold: true, fill: tc, maxw: room + 1 }));   // the name alone, centered on the bar by its ink
    } else {                                                 // beside the bar, on the side with more room
      const right = x1 - xb > xa - x0, w = right ? x1 - xb - 8 : xa - x0 - 8;   // the side with more room and the width there
      const t = fit(name, 11.5, true, w, ctx.cut, `${ctx.where} phase`);   // shortened to that width
      // Left-aligned after the bar, or right-aligned before it
      parts.push(T(ctx, right ? xb + 6 : xa - 6, block(y + bh / 2, [[t, 11.5, true]])[0], t, { size: 11.5, bold: true, anchor: right ? "start" : "end", maxw: w + 1 }));
    }
  });
  // Milestones: diamonds on one line above the lanes, labels above them on two staggered rows so neighbors do not collide
  const msY = B.y + 4 + msH - 12, rowsY = [msY - 17, msY - 31], placed = [[], []];
  ms.forEach(([label, date, kind]) => {                      // in the data's order: earlier labels take the row next to the diamonds first
    const x = X(ym(date) + 0.5), K = kindOf(ctx, kind || "key", !kind), w = tw(label, 10.5, true);   // the diamond's place and the label width
    parts.push(P.line(x, msY + 6, x, yAxis, { stroke: ctx.pal.faint, dash: "2 3", deco: true }));   // the guide line down to the axis
    parts.push(P.poly([[x, msY - 6], [x + 6, msY], [x, msY + 6], [x - 6, msY]], { fill: kind ? K.stroke : ctx.pal.strong }));   // the diamond
    const lx = Math.max(B.x + 4 + w / 2, Math.min(B.x + B.w - 4 - w / 2, x));   // the label centered, kept inside the frame
    const row = placed.findIndex(rw => rw.every(([a, b]) => lx + w / 2 + 6 < a || lx - w / 2 - 6 > b));   // the first row where it fits
    const r = row < 0 ? 1 : row;                             // no free row: the upper one, and the touch is reported
    if (row < 0) ctx.cut.push(`${ctx.where} milestone '${label}' is close to another; its label may touch`);   // reported so the dates or labels can be adjusted
    placed[r].push([lx - w / 2, lx + w / 2]);                // this label's span, for the next labels' test
    parts.push(T(ctx, lx, rowsY[r], label, { size: 10.5, bold: true, anchor: "middle", fill: ctx.pal.ink }));   // the label on its row
  });
  const lg = legend(ctx, B.x + 6, yAxis + axisH + 6, B.w - 12);   // kinds used
  parts.push(lg.svg);                                        // empty when nothing carries a kind
  return { parts, h: yAxis - B.y + axisH + (lg.h ? lg.h + 8 : 2) };   // lanes, axis and the legend row
}

// Workstreams of tasks on a month axis: a name column, a header row per group with its span, one row per task, milestones on top and
// an optional dashed line for today
function gantt(fig, B, ctx) {
  // Groups with tasks as [name, start, end, kind], from lists or objects
  const groups = fig.groups.map(g => ({ name: g.name, tasks: (g.tasks || []).map(t => (Array.isArray(t) ? t : [t.name, t.start, t.end, t.kind])) }));
  const ms = (fig.milestones || []).map(r => (Array.isArray(r) ? r : [r.label, r.date]));   // milestones as [label, date]
  // Every month on the chart: task starts, ends through their last month, milestones
  const all = groups.flatMap(g => g.tasks.flatMap(t => [ym(t[1]), Number.isFinite(ym(t[2])) ? ym(t[2]) + 1 : ym(t[1]) + 1])).concat(ms.map(m => ym(m[1]))).filter(Number.isFinite);
  const lo = Math.min(...all), hi = Math.max(...all) + (ms.length ? 1 : 0);   // the axis range
  // The name column: the widest group or indented task name, up to 36% of the frame
  const nameW = Math.min(B.w * 0.36, Math.max(...groups.flatMap(g => [tw(g.name, 11.5, true), ...g.tasks.map(t => tw(t[0], 10.5) + 12)])) + 16);
  const x0 = B.x + 4 + nameW, x1 = B.x + B.w - 8, X = t => x0 + (x1 - x0) * (t - lo) / Math.max(1, hi - lo);   // the chart area and month to x
  const rowsN = groups.reduce((a, g) => a + 1 + g.tasks.length, 0), msH = ms.length ? 30 : 0, axisH = 24, legH = 20;   // a header row per group plus its tasks; bands for milestones and the axis
  const legRoom = groups.some(g => g.tasks.some(t => t[3])) ? 24 : 2;   // a legend row under the axis when tasks carry kinds
  const rh = Math.max(18, Math.min(26, (B.h - 4 - msH - 2 - axisH - legRoom) / rowsN)), bh = Math.max(10, Math.min(15, rh - 8)), parts = [];   // rows 18 to 26 px to fill the frame, bars 10 to 15 px
  const top = B.y + 4 + msH, yAxis = top + rowsN * rh + 2;   // rows start under the milestone band; the axis under the last row
  parts.push(monthAxis(ctx, X, lo, hi, top - 2, yAxis, x0 - 4, x1 + 2));   // gridlines behind the rows, labels under them
  let r = 0;                                                 // the row being drawn, across all groups
  groups.forEach((g, gi) => {                                // a header row, then the tasks
    const ys = top + r * rh + rh / 2, span = g.tasks.map(t => [ym(t[1]), Number.isFinite(ym(t[2])) ? ym(t[2]) + 1 : ym(t[1]) + 1]);   // the header row's center and each task's months
    if (gi) parts.push(line(ctx, B.x + 4, top + r * rh, x1, top + r * rh, { stroke: ctx.pal.grid }));   // a rule between groups
    // The group name in bold at the left
    parts.push(T(ctx, B.x + 6, block(ys, [[g.name, 11.5, true]])[0], fit(g.name, 11.5, true, nameW - 10, ctx.cut, `${ctx.where} group`), { size: 11.5, bold: true, maxw: nameW - 8 }));
    if (span.length) {                                       // the group's span as a thin dark bar
      const a = Math.min(...span.map(s => s[0])), b = Math.max(...span.map(s => s[1]));   // from the first task's start to the last task's end
      parts.push(P.rect(X(a), ys - 3, Math.max(6, X(b) - X(a)), 6, { fill: ctx.pal.strong, r: 3 }));   // 6 px tall, so it reads as a summary and not a task
    }
    r++;                                                     // the tasks start on the next row
    g.tasks.forEach(([name, , , kind], ti) => {              // one row per task
      const [a, b] = span[ti], y = top + r * rh + (rh - bh) / 2, K = kindOf(ctx, kind || "");   // the task's months, bar top and kind style
      // The task name, indented under its group
      parts.push(T(ctx, B.x + 16, block(y + bh / 2, [[name, 10.5, false]])[0], fit(name, 10.5, false, nameW - 20, ctx.cut, `${ctx.where} task`), { size: 10.5, fill: ctx.pal.body, maxw: nameW - 18 }));
      // The task bar in its kind's style, else the soft shade without an outline
      parts.push(P.rect(X(a) + 1, y, Math.max(6, X(b) - X(a) - 2), bh, { fill: kind ? K.fill : ctx.pal.soft2, stroke: kind ? K.stroke : "none", sw: kind ? K.sw : 1, r: 3, dash: kind ? K.dash : undefined }));
      r++;                                                   // the next task's row
    });
  });
  const placed = [];                                         // milestone labels on the band above, staggered when they would touch
  ms.forEach(([label, date]) => {                            // milestones over the rows
    // The diamond mid-month; the label centered on it, kept inside the frame
    const x = X(ym(date) + 0.5), w = tw(label, 10.5, true), lx = Math.max(B.x + 4 + w / 2, Math.min(B.x + B.w - 4 - w / 2, x));
    parts.push(P.line(x, top - 6, x, yAxis, { stroke: ctx.pal.faint, dash: "2 3", deco: true }));   // a faint dashed guide line down through the rows
    parts.push(P.poly([[x, top - 12], [x + 5, top - 7], [x, top - 2], [x - 5, top - 7]], { fill: ctx.pal.strong }));   // a small diamond above the rows
    const clash = placed.some(([a, b]) => lx + w / 2 + 6 >= a && lx - w / 2 - 6 <= b);   // closer than 6 px to a label already placed
    if (clash) ctx.cut.push(`${ctx.where} milestone '${label}' is close to another; its label may touch`);   // one label row here, so a close pair is reported
    placed.push([lx - w / 2, lx + w / 2]);                   // its span, for the next labels
    parts.push(T(ctx, lx, top - 21, label, { size: 10.5, bold: true, anchor: "middle" }));   // the label above its diamond
  });
  if (fig.today && Number.isFinite(ym(fig.today))) {         // today, a dashed accent line with its word under the axis
    const x = X(ym(fig.today) + 0.5);                        // mid-month, like the milestones
    parts.push(P.line(x, top - 2, x, yAxis, { stroke: ctx.pal.accent, sw: 1.4, dash: "4 3" }));   // a dashed accent line across every row
  }
  const lg = legend(ctx, B.x + 6, yAxis + axisH + 4, B.w - 12);   // the kinds the tasks used, under the axis
  parts.push(lg.svg);                                        // empty when no task has a kind
  return { parts, h: yAxis - B.y + axisH + (lg.h ? lg.h + 6 : 2) };   // rows, axis and legend
}

// Proper crossing of two axis-aligned segments (shared end points do not count)
function crosses(a, b) {
  const [[ax1, ay1], [ax2, ay2]] = a, [[bx1, by1], [bx2, by2]] = b;   // each segment's two end points
  const ah = Math.abs(ay1 - ay2) < 0.01, bh = Math.abs(by1 - by2) < 0.01;   // horizontal or vertical
  if (ah === bh) return false;                               // parallel segments do not cross (overlap is a different defect)
  const [h, v] = ah ? [a, b] : [b, a];                       // name the horizontal one and the vertical one
  const hx = [Math.min(h[0][0], h[1][0]), Math.max(h[0][0], h[1][0])], vy = [Math.min(v[0][1], v[1][1]), Math.max(v[0][1], v[1][1])];   // the horizontal's x span and the vertical's y span
  const vx = v[0][0], hy = h[0][1];                          // the vertical's x and the horizontal's y
  return vx > hx[0] + 1.5 && vx < hx[1] - 1.5 && hy > vy[0] + 1.5 && hy < vy[1] - 1.5;   // strictly inside both
}

// Zones of nodes (left to right) with labeled links. Links between neighboring zones run through the corridor between them; links that
// skip zones find a free height through the zones between; links inside a zone join stacked neighbors. Incoming links on one side get
// their own points so arrowheads never meet. Nodes may hold a grid of squares (GPUs, members) colored by kind
function architecture(fig, B, ctx) {
  // Corridors widen (twice at most) until every link label finds room; the attempt that is kept reports its own notes
  for (const extra of [0, 26, 52]) {
    const tmp = { ...ctx, cut: [], kinds: new Set() }, res = architectureAt(fig, B, tmp, extra);   // each attempt draws with its own notes and legend
    if (extra === 52 || !tmp.cut.some(c => /no room for the label/.test(c))) {   // every label found room, or this is the widest try
      ctx.cut.push(...tmp.cut); tmp.kinds.forEach(k => ctx.kinds.add(k));   // keep this attempt's notes and legend
      return res;                                            // this attempt's drawing
    }
  }
}
function architectureAt(fig, B, ctx, extra) {                // one attempt, with every corridor widened by extra px
  const zones = fig.zones.map(z => ({ title: z.title, kind: z.kind, mark: z.mark, right: z.note,   // zones with their note shown at the right of the label
    // Nodes as objects; a node given as a list is named by its title, which is also its id
    nodes: (z.nodes || []).map(n => (Array.isArray(n) ? { id: n[0], title: n[0], sub: n[1], kind: n[2] } : { ...n, id: n.id ?? n.title })) }));
  const links = (fig.links || []).map(l => (Array.isArray(l) ? { from: l[0], to: l[1], label: l[2], kind: l[3] } : l));   // links as { from, to, label, kind }
  const nz = zones.length, legH = 22, parts = [];            // zone count and the legend row
  // Zone widths in proportion to what their nodes need (titles, subs, squares), within what the frame has after the corridors
  const corridor = Math.max(30, Math.min(64, B.w * 0.06 + links.length * 1.2)) + extra;   // wider on a retry for labels
  // The width a zone needs: its label, its widest node title or sub (subs count up to 220), squares at least 90
  const needW = zones.map(z => Math.max(tw(z.title || "", 10.5, true) + 30, ...z.nodes.map(n => Math.max(tw(n.title, 12, true), n.sub ? Math.min(tw(n.sub, 10.5), 220) : 0, n.units ? 90 : 0) + 40)));
  const free = B.w - 8 - corridor * (nz - 1), sum = needW.reduce((a, v) => a + v, 0);   // the width left for zones after the corridors
  const zw = needW.map(v => Math.max(96, free * v / sum));   // proportional, at least 96
  const k = free / zw.reduce((a, v) => a + v, 0);            // squeeze back when minimums overshoot
  const zx = []; let xx = B.x + 4;                           // zone left edges, from the frame's left
  zw.forEach((w, i) => { zw[i] = w * k; zx.push(xx); xx += zw[i] + corridor; });   // scaled widths placed left to right with a corridor between
  // Node heights from their content, and zones as tall as the tallest stack (the figure then ends under its zones; a frame centers it)
  // Links that arrive on a node's left or right side, counted per node and side: each needs its own point on that side, 10 px apart
  const where0 = {}; zones.forEach((z, zi) => z.nodes.forEach((n, ni) => { where0[n.id] = { zi, ni }; }));   // node id -> zone and place in it
  const perSide = new Map(), arrive = new Map();             // node and side -> links arriving there; node id -> the most on one side
  links.forEach(l => {                                       // links between zones arrive on the left or the right side
    const a = where0[l.from], b = where0[l.to];              // where the two ends sit
    if (!a || !b || a.zi === b.zi) return;                   // unknown ends are reported later; links inside a zone arrive on top or bottom
    const k = l.to + (a.zi < b.zi ? "\u0000L" : "\u0000R"), c = (perSide.get(k) || 0) + 1;   // the side it arrives on, and its count so far
    perSide.set(k, c); arrive.set(l.to, Math.max(arrive.get(l.to) || 0, c));   // the busiest side of each node
  });
  const needs = zones.map((z, zi) => z.nodes.map(n => {
    // The node's inner width, its title lines and sub lines (two each at most)
    const nw = zw[zi] - 20, tl = Math.min(2, wrap(n.title, 12, nw - 18, true).length), sl = n.sub ? Math.min(2, wrap(n.sub, 10.5, nw - 18).length) : 0;
    const text = 16 + tl * 14.6 + (sl ? sl * 13.7 + 4 : 0) + (n.units ? unitRows(n.units, nw - 18).h + 10 : 0);   // padding, the text lines, and the squares under them
    return (arrive.get(n.id) || 0) > 1 ? Math.max(text, 12 * arrive.get(n.id) + 12) : text;   // tall enough for its arrows when several arrive on one side
  }));
  // Zones holding a link between two of their own nodes
  const inner = new Set(links.filter(l => { const a = zones.findIndex(z => z.nodes.some(n => n.id === l.from)); return a >= 0 && zones[a].nodes.some(n => n.id === l.to); }).map(l => zones.findIndex(z => z.nodes.some(n => n.id === l.from))));
  const GAP = zi => inner.has(zi) ? 26 : 18;                 // a zone with a link between stacked nodes keeps room for its arrow
  const stackH = needs.map((ns, zi) => ns.reduce((a, v) => a + v, 0) + GAP(zi) * (ns.length - 1));   // each zone's stack at its own height
  const zy = B.y + 4, zh = Math.min(B.h - 8 - legH, Math.max(...stackH) * 1.08 + 28 + 18);   // the zones' common height
  const pos = {};                                            // node id -> { zi, ni, x, y, w, h }
  zones.forEach((z, zi) => {                                 // each zone's stack of nodes
    const room = zh - 28 - 12, ns = needs[zi], total = ns.reduce((a, v) => a + v, 0);   // height inside the zone for its nodes
    const gMin = GAP(zi) - (inner.has(zi) ? 2 : 6);           // the smallest gap: an arrow's room, else a plain gap
    let g = Math.max(gMin, Math.min(30, (room - total) / Math.max(1, ns.length + 1)));   // the gap between nodes
    let scale = total + g * (ns.length - 1) > room ? (room - gMin * (ns.length - 1)) / total : 1;   // squeeze when the zone is short
    // Squeezed: the smallest gap, and the crowding is reported
    if (scale < 1) { g = gMin; if (ctx.cut) ctx.cut.push(`${ctx.where} zone '${z.title}': ${z.nodes.length} nodes are crowded; use fewer`); }
    scale = Math.max(0.6, Math.min(1, scale));               // never under 60% of the height the text needs
    const used = total * scale + g * (ns.length - 1);        // the stack's height after scaling
    let y = zy + 28 + Math.max(0, (room - used) / 2);        // the stack centered under the label
    z.nodes.forEach((n, ni) => {                             // nodes top to bottom in the data's order
      const h = Math.max(30, ns[ni] * scale);                // at least 30 px for one title line
      pos[n.id] = { zi, ni, x: zx[zi] + 10, y, w: zw[zi] - 20, h, n };   // inset 10 px from the zone's sides
      y += h + g;                                            // the next node under it
    });
  });
  const unknown = links.filter(l => !pos[l.from] || !pos[l.to]);   // links to nodes that are not drawn
  if (unknown.length) ctx.cut.push(`${ctx.where}: links to unknown nodes left out (${unknown.map(l => `${l.from}->${l.to}`).join(", ")})`);   // named in the cut notes, so a mistyped id is found
  const ok = links.filter(l => pos[l.from] && pos[l.to] && l.from !== l.to);   // the links that can be drawn (a link to itself has no route)
  // End points: incoming and outgoing links share a side's middle unless several arrive there; then each gets its own point
  const sideOf = l => { const a = pos[l.from], b = pos[l.to]; return a.zi === b.zi ? (a.ni < b.ni ? ["B", "T"] : ["T", "B"]) : a.zi < b.zi ? ["R", "L"] : ["L", "R"]; };
  const ins = {};                                            // node:side -> incoming links
  ok.forEach(l => { const [, s2] = sideOf(l); (ins[l.to + ":" + s2] = ins[l.to + ":" + s2] || []).push(l); });   // incoming links grouped by the node and side they arrive at
  // The middle of a side, moved along it by off
  const at = (p, side, off = 0) => side === "R" ? [p.x + p.w, p.y + p.h / 2 + off] : side === "L" ? [p.x, p.y + p.h / 2 + off] : side === "T" ? [p.x + p.w / 2 + off, p.y] : [p.x + p.w / 2 + off, p.y + p.h];
  const offs = new Map();                                    // each incoming link's offset along its side
  Object.values(ins).forEach(list => {                       // spread the links that arrive on one side
    const p = pos[list[0].to], side = sideOf(list[0])[1], span = side === "L" || side === "R" ? p.h : p.w;   // the target node, its side and that side's length
    list.sort((u, v) => (pos[u.from].y - pos[v.from].y) || (pos[u.from].x - pos[v.from].x));   // top source first, so lines do not cross
    const step = Math.min(14, (span - 10) / Math.max(1, list.length));   // spacing between arrival points, 14 px at most
    if (list.length > 1 && step < 10) ctx.cut.push(`${ctx.where}: ${list.length} links into '${p.n.title}' crowd one side`);   // closer than 10 px the arrowheads crowd: reported
    list.forEach((l, i) => offs.set(l, list.length > 1 ? (i - (list.length - 1) / 2) * Math.max(10, step) : 0));   // offsets centered on the side's middle, at least 10 px apart
  });
  // Routes: straight when the ends line up, else one turn in the corridor next to the source, else around through a free height
  const corridorX = zi => zx[zi] + zw[zi] + corridor / 2;   // the middle of the corridor right of zone zi
  const lanes = {};                                          // corridor -> links with a vertical run there
  const routes = ok.map(l => {                               // a route per link: its points now, or a corridor lane to place later
    const a = pos[l.from], b = pos[l.to], [s1, s2] = sideOf(l);   // the two nodes and the sides the link leaves and enters
    const p0 = at(a, s1), p1 = at(b, s2, offs.get(l) || 0);  // the start, and the end at its own arrival point
    // Inside a zone: a vertical run to the next node, with a short step to an offset end
    if (a.zi === b.zi) return { l, pts: [p0, [p0[0], p1[1]]].concat(Math.abs(p0[0] - p1[0]) > 0.5 ? [[p1[0], p1[1]]] : []) };
    const dir = a.zi < b.zi ? 1 : -1, zFirst = dir > 0 ? a.zi : a.zi - 1, zLast = dir > 0 ? b.zi - 1 : b.zi;   // corridors at either end
    if (Math.abs(p0[1] - p1[1]) < 0.5 && Math.abs(a.zi - b.zi) === 1) return { l, pts: [p0, p1] };   // a straight line
    // Neighboring zones: one turn, at a lane of the corridor placed below
    if (Math.abs(a.zi - b.zi) === 1) { (lanes[zFirst] = lanes[zFirst] || []).push(l); return { l, pts: null, c: zFirst, p0, p1 }; }
    // Skipping zones: a height free of nodes in every zone between (bands between nodes, or the zone's top and foot)
    const mids = []; for (let z = Math.min(a.zi, b.zi) + 1; z < Math.max(a.zi, b.zi); z++) mids.push(z);
    const blocked = y => mids.some(z => zones[z].nodes.some(n => { const q = pos[n.id]; return y > q.y - 7 && y < q.y + q.h + 7; }));   // a height is blocked within 7 px of a node in a zone between
    // Candidate heights: both ends, just above and below each node between, the zones' foot
    const cands = [p0[1], p1[1], ...mids.flatMap(z => zones[z].nodes.map(n => pos[n.id].y - 10)), ...mids.flatMap(z => zones[z].nodes.map(n => pos[n.id].y + pos[n.id].h + 10)), zy + zh - 10];
    // The free height closest to both ends, inside the zones' content area
    const yFree = cands.filter(y => y > zy + 24 && y < zy + zh - 4 && !blocked(y)).sort((u, v) => (Math.abs(u - p0[1]) + Math.abs(u - p1[1])) - (Math.abs(v - p0[1]) + Math.abs(v - p1[1])))[0];
    if (yFree === undefined) { ctx.cut.push(`${ctx.where}: no free path for ${l.from}->${l.to}`); return { l, pts: null, skip: true }; }   // no free height: the link is reported and left out
    (lanes[zFirst] = lanes[zFirst] || []).push(l); (lanes[zLast] = lanes[zLast] || []).push(l);   // a vertical run in the corridor at each end
    return { l, pts: null, c: zFirst, c2: zLast, p0, p1, yFree };   // points are built once the lane x positions are known
  });
  // Lane x in each corridor: try every order (up to six links) and keep the one with the fewest crossings
  const build = (r, xa, xb) => {                             // the points of a routed link with its lane x positions
    if (r.yFree === undefined) return [r.p0, [xa, r.p0[1]], [xa, r.p1[1]], r.p1];   // neighbors: across, along the lane, across
    const pts = [r.p0];                                      // a skipping link starts at its source
    if (Math.abs(r.yFree - r.p0[1]) > 0.5) pts.push([xa, r.p0[1]], [xa, r.yFree]); else pts.push([xa, r.p0[1]]);   // to the near lane, then along it to the free height (or on at that height)
    if (Math.abs(r.yFree - r.p1[1]) > 0.5) pts.push([xb, r.yFree], [xb, r.p1[1]]); else pts.push([xb, r.yFree]);   // across at the free height to the far lane, then to the end's height
    pts.push(r.p1);                                          // into the target
    return pts.filter((p, i) => !i || Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) > 0.5);   // drop points that repeat the one before
  };
  const segsOf = pts => pts.slice(1).map((p, i) => [pts[i], p]);   // a polyline's segments
  // Crossings between every pair of routes, segment by segment
  const countX = rs => { let n = 0; for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) for (const s of segsOf(rs[i])) for (const t of segsOf(rs[j])) if (crosses(s, t)) n++; return n; };
  const laneX = {};                                          // link -> x in each of its corridors
  // Every order of a list (six links give 720, few enough to try all)
  const perms = arr => arr.length <= 1 ? [arr] : arr.flatMap((v, i) => perms([...arr.slice(0, i), ...arr.slice(i + 1)]).map(p => [v, ...p]));
  Object.entries(lanes).forEach(([c, list]) => {             // corridor by corridor, the links that run through it
    const cx = corridorX(+c), width = corridor - 16;         // the corridor's usable width
    const orders = list.length <= 6 ? perms(list) : [list];  // every order, or the given one for many links
    let best = null;                                         // the order with the fewest crossings so far
    for (const ord of orders) {                              // the order with the fewest crossings among all routes so far
      // Lanes spread evenly across the corridor in this order (one link: the middle)
      const xs = new Map(ord.map((l, i) => [l, ord.length === 1 ? cx : cx - width / 2 + width * i / (ord.length - 1)]));
      const trial = routes.filter(r => r.pts || r.c !== undefined).map(r => {   // every route's points with this order tried here
        if (r.pts) return r.pts;                             // fixed routes as they are
        const xa = r.c === +c ? xs.get(r.l) : (laneX[r.l.from + ">" + r.l.to + "@" + r.c] ?? corridorX(r.c));   // in this corridor the trial's lane; elsewhere a lane already chosen, else the middle
        // The far corridor's x the same way (the near one for a link with one corridor)
        const xb = r.c2 === undefined ? xa : r.c2 === +c ? xs.get(r.l) : (laneX[r.l.from + ">" + r.l.to + "@" + r.c2] ?? corridorX(r.c2));
        return build(r, xa, xb);                             // the route's points with those lanes
      });
      const n = countX(trial);                               // crossings in this trial
      if (!best || n < best.n) best = { n, xs };             // keep the first order with the fewest
      if (n === 0) break;                                    // no crossings: no order can do better
    }
    best.xs.forEach((x, l) => { laneX[l.from + ">" + l.to + "@" + c] = x; });   // fix this corridor's lanes for the corridors after it
  });
  // Every route's final points, with the chosen lanes (the middle where none was chosen)
  const final = routes.filter(r => !r.skip).map(r => r.pts ? r : { ...r, pts: build(r, laneX[r.l.from + ">" + r.l.to + "@" + r.c] ?? corridorX(r.c), r.c2 === undefined ? (laneX[r.l.from + ">" + r.l.to + "@" + r.c] ?? corridorX(r.c)) : (laneX[r.l.from + ">" + r.l.to + "@" + r.c2] ?? corridorX(r.c2))) });
  const nx = countX(final.map(r => r.pts));                  // crossings that no order could remove
  if (nx) ctx.cut.push(`${ctx.where}: ${nx} link crossing(s) remain; reorder the nodes`);   // reported: reordering the nodes in the data is the fix
  // Drawing: zones, then links (under the nodes' labels), then nodes, then the link labels on top
  zones.forEach((z, zi) => parts.push(group(ctx, zx[zi], zy, zw[zi], zh, z.title, { kind: z.kind, mark: z.mark, right: z.right })));
  final.forEach(r => parts.push(link(ctx, r.pts, { kind: r.l.kind })));   // links under the nodes
  // The nodes on top with their titles, subs, badges and squares
  Object.values(pos).forEach(p => parts.push(box(ctx, p.x, p.y, p.w, p.h, { title: p.n.title, sub: p.n.sub, kind: p.n.kind, mark: p.n.mark,
    units: p.n.units, unitKinds: p.n.unitKinds, size: 12, subSize: 10.5 })));   // squares colored one by one by unitKinds
  // Link labels, as a person would write them: short grey words above a horizontal run (else beside a vertical run), clear of every node,
  // every other link and every other label. A label that finds no room is reported, never drawn over something
  const boxes = Object.values(pos).map(p => [p.x - 3, p.y - 3, p.x + p.w + 3, p.y + p.h + 3]);   // node rectangles with a margin
  const taken = [];                                          // labels placed so far
  const hit = (r, list) => list.some(b => r[2] > b[0] && r[0] < b[2] && r[3] > b[1] && r[1] < b[3]);   // rectangle overlap
  // A segment that passes through a rectangle (with a 2 px margin)
  const segHit = (r, segs) => segs.some(([p, q]) => Math.max(p[0], q[0]) >= r[0] - 2 && Math.min(p[0], q[0]) <= r[2] + 2 && Math.max(p[1], q[1]) >= r[1] - 2 && Math.min(p[1], q[1]) <= r[3] + 2);
  final.forEach(r => {                                       // each drawn link's label
    if (!r.l.label) return;                                  // a link without a label needs no place
    // The label, its width, the other links' segments and this link's own
    const t = r.l.label, w = tw(t, 10, false), others = final.filter(o => o !== r).flatMap(o => segsOf(o.pts)), own = segsOf(r.pts);
    const tries = [];                                        // candidate places: [x, y, anchor, rectangle]
    own.forEach(([p, q]) => {                                // candidates along each run of the link
      const len = Math.hypot(q[0] - p[0], q[1] - p[1]);      // the run's length (longer runs are tried first)
      if (Math.abs(p[1] - q[1]) < 0.5 && len >= w + 12) {    // above or below a horizontal run, centered on it
        const cx = (p[0] + q[0]) / 2;                        // the run's middle
        tries.push([cx, p[1] - 9, "middle", [cx - w / 2 - 1, p[1] - 17, cx + w / 2 + 1, p[1] - 3], len]);   // above the run, the usual placement place
        tries.push([cx, p[1] + 10, "middle", [cx - w / 2 - 1, p[1] + 3, cx + w / 2 + 1, p[1] + 17], len - 1]);   // below the run, ranked just after above
      }
      if (Math.abs(p[0] - q[0]) < 0.5 && len >= 24) {        // beside a vertical run, at its middle
        const cy = (p[1] + q[1]) / 2;                        // the run's middle
        tries.push([p[0] + 6, cy, "start", [p[0] + 4, cy - 8, p[0] + 7 + w, cy + 8], len - 2]);   // right of the run
        tries.push([p[0] - 6, cy, "end", [p[0] - 7 - w, cy - 8, p[0] - 4, cy + 8], len - 3]);   // left of the run, the last choice for this run
      }
    });
    tries.sort((u, v) => v[4] - u[4]);                       // the longest run first
    // A label sits inside one zone or in a corridor, never across a zone's edge
    const across = rc => zones.some((z, zi) => { const z0 = zx[zi], z1 = zx[zi] + zw[zi], y0 = zy, y1 = zy + zh;
      // The rectangle touches the zone, or sits fully inside its content area
      const inter = rc[2] > z0 - 2 && rc[0] < z1 + 2 && rc[3] > y0 - 2 && rc[1] < y1 + 2, inside = rc[0] >= z0 + 3 && rc[2] <= z1 - 3 && rc[1] >= y0 + 20 && rc[3] <= y1 - 3;
      return inter && !inside; });                           // touching without being inside means across an edge
    // The first candidate inside the frame and clear of nodes, labels, links and zone edges
    const ok = tries.find(([, , , rc]) => rc[0] >= B.x + 2 && rc[2] <= B.x + B.w - 2 && !hit(rc, boxes) && !hit(rc, taken) && !segHit(rc, others) && !segHit(rc, own) && !across(rc));
    if (!ok) { ctx.cut.push(`${ctx.where}: no room for the label '${t}' on ${r.l.from}->${r.l.to}`); return; }   // no place: reported, never drawn over something
    taken.push(ok[3]);                                       // later labels keep clear of this one
    parts.push(T(ctx, ok[0], ok[1], t, { size: 10, fill: ctx.pal.muted, anchor: ok[2] }));   // short grey words
  });
  ctx.legend = fig.legend || ctx.legend;                     // the figure may rename the kind words
  const lg = legend(ctx, B.x + 6, zy + zh + 13, B.w - 12);   // the legend right under the zones
  parts.push(lg.svg);                                        // empty when nothing carries a kind
  return { parts, h: zh + 8 + (lg.h ? lg.h + 6 : 0) };       // the zones and the legend row
}

// Racks of units under a switch fabric: the fabric's switches on top with an uplink to every rack, each rack a column of unit rows
// (servers, switches, storage) colored by kind, with its count written and, when it is small, drawn as squares
function rack(fig, B, ctx) {
  // Racks with units as [label, kind, count], from lists or objects
  const racks = fig.racks.map(r => ({ name: r.name, sub: r.sub, kind: r.kind, units: (r.units || []).map(u => (Array.isArray(u) ? u : [u.label, u.kind, u.count])) }));
  const fab = fig.fabric, legH = 22, gap = 12, parts = [];   // the fabric band, legend, gap between racks
  const fabH = fab ? 66 : 0, top = B.y + 4 + fabH + (fab ? 20 : 0);   // racks start under the fabric
  const n = racks.length, rw = (B.w - 8 - gap * (n - 1)) / n;   // rack width
  const m = Math.max(...racks.map(r => r.units.length)), uh = 24;   // the most units in a rack, unit row height
  const rh = Math.min(B.y + B.h - legH - 6 - top, 30 + m * (uh + 5) + 8);   // racks as tall as the fullest one
  if (fab) {                                                 // the fabric: a band with its switches in a row
    const items = fab.items || [], fw = B.w - 8;             // the switches and the band's width
    parts.push(group(ctx, B.x + 4, B.y + 4, fw, fabH, fab.label || "", { kind: fab.kind }));   // the fabric band across the top
    // Switch boxes up to 150 px wide, the row centered in the band
    const sw = Math.min(150, (fw - 24 - 10 * (items.length - 1)) / Math.max(1, items.length)), sx0 = B.x + 4 + (fw - (sw * items.length + 10 * (items.length - 1))) / 2;
    // One box per switch, dark by default (a given kind colors it and joins the legend)
    items.forEach((s0, i) => parts.push(box(ctx, sx0 + i * (sw + 10), B.y + 26, sw, 32, { title: Array.isArray(s0) ? s0[0] : s0, kind: Array.isArray(s0) && s0[1] ? s0[1] : "key", quiet: !(Array.isArray(s0) && s0[1]), size: 11 })));
    racks.forEach((r, i) => {                                // one uplink per rack from the fabric's foot
      const cx = B.x + 4 + i * (rw + gap) + rw / 2;          // the rack's center
      parts.push(line(ctx, cx, B.y + 4 + fabH, cx, top, { stroke: ctx.pal.faint, sw: 1.2 }));   // a plain line: an uplink, not a flow
    });
  }
  racks.forEach((r, i) => {                                  // the racks
    const x = B.x + 4 + i * (rw + gap);                      // the rack's left edge
    parts.push(group(ctx, x, top, rw, rh, r.name, { kind: r.kind, right: r.sub }));   // the rack as a zone, its sub at the right of the name
    const per = Math.max(1, (rh - 38 - 5 * (r.units.length - 1)) / Math.max(1, r.units.length)), h = Math.min(uh, per);   // squeezed rows when the rack is short
    if (per < 16) ctx.cut.push(`${ctx.where} rack '${r.name}': ${r.units.length} units are crowded; use fewer`);   // under 16 px a unit row's text no longer fits: reported
    r.units.forEach(([label, kind, count], j) => {           // unit rows top to bottom
      const y = top + 28 + j * (h + 5);                      // under the rack's name, 5 px apart
      const K = kindOf(ctx, kind || ""), cnt = count ? `×${num(count)}` : "";   // the unit's style and its count text
      const cw = cnt ? tw(cnt, 10.5, true) + 8 : 0;          // room for the count
      // The unit row; valign free keeps it out of the probe's centering check
      parts.push(P.rect(x + 8, y, rw - 16, h, { fill: K.fill, stroke: K.stroke, sw: K.sw, r: 3, dash: K.dash, valign: "free" }));
      const lw0 = tw(label, 10.5, false), sq = count && count <= 12 ? count : 0;   // the label's width; servers drawn as squares when few
      const sqW = sq ? sq * 9 - 2 : 0, fitsSq = sq && 16 + lw0 + 10 + sqW + 8 + cw <= rw - 16;   // do the squares fit after the label
      const lw = rw - 16 - 16 - cw - (fitsSq ? sqW + 10 : 0);   // the label's room after the count and the squares
      const t = fit(label, 10.5, false, lw, ctx.cut, `${ctx.where} unit`);   // shortened to that room
      parts.push(T(ctx, x + 16, block(y + h / 2, [[t, 10.5, false]])[0], t, { size: 10.5, fill: K.title, maxw: lw + 1 }));   // the label at the row's left, in the kind's title color
      if (fitsSq) {                                          // one square per server, right before the count
        const [f, st] = UNIT[ctx.pal.name][kind || ""] || UNIT[ctx.pal.name][""], sx = x + rw - 8 - 8 - cw - sqW;   // square colors, and their x so they end before the count
        // One 7 px square per server, in a color that shows on the row's own fill
        for (let q = 0; q < sq; q++) parts.push(P.rect(sx + q * 9, y + h / 2 - 3.5, 7, 7, { fill: kind === "key" ? ctx.pal.onStrong : f === K.fill ? K.stroke : f, r: 1.5, deco: true }));
      }
      // The count, right-aligned at the row's end
      if (cnt) parts.push(T(ctx, x + rw - 16, block(y + h / 2, [[cnt, 10.5, true]])[0], cnt, { size: 10.5, bold: true, fill: K.title, anchor: "end" }));
    });
  });
  ctx.legend = fig.legend || ctx.legend;                     // the figure may rename the kind words
  const lg = legend(ctx, B.x + 6, top + rh + 13, B.w - 12);  // the kinds used, under the racks
  parts.push(lg.svg);                                        // empty when nothing carries a kind
  return { parts, h: top + rh - B.y + (lg.h ? lg.h + 8 : 4) };   // fabric, racks and legend
}

// Before and after values per metric with the conditions they were measured under: paired bars on one value axis, a legend, an optional
// change label per row (delta: true; it is arithmetic on the data, so it stays off unless asked for)
function metric(fig, B, ctx) {
  const W0 = WORDS[ctx.lang], unit = fig.unit || "", rows = fig.rows;   // words, unit and rows [name, before, after, condition]
  const bl = fig.beforeLabel || W0.before, al = fig.afterLabel || W0.after;   // the series names, the edition's words by default
  const condL = fig.conditions ? lines(fig.conditions, 10.5, false, B.w - 12, 2, ctx.cut, `${ctx.where} conditions`) : [];   // the measuring conditions, two lines at most, under the axis
  const footH = condL.length * 14 + (condL.length ? 8 : 0), axisH = 22, headH = 24;   // conditions, axis and legend bands
  // The name column: the widest name or condition, at most 36% of the frame
  const nameW = Math.min(B.w * 0.36, Math.max(...rows.map(r => Math.max(tw(r[0], 12, true), r[3] ? Math.min(tw(r[3], 10), B.w * 0.36) : 0))) + 16);
  const max = Math.max(...rows.flatMap(r => [r[1], r[2]])) || 1, tk = ticks(0, max, 4), top = tk[tk.length - 1] || 1;   // one axis for both series, from zero to a round tick
  const vw = Math.max(...rows.flatMap(r => [tw(num(r[1]) + unit, 11, false), tw(num(r[2]) + unit, 11.5, true)])) + 12;   // room for the widest value text after a bar
  const dw = fig.delta ? 58 : 0, x0 = B.x + nameW, barW = B.w - nameW - vw - dw - 8;   // where bars start and their longest length
  const X = v => x0 + barW * v / top, parts = [];            // value to x
  // Rows under the legend, 40 to 66 px each, the bars 30% of a row and 18 px at most
  const rowsTop = B.y + headH + 4, rowH = Math.max(40, Math.min(66, (B.h - headH - axisH - footH - 10) / rows.length)), bh = Math.min(18, rowH * 0.3);
  const yb = rowsTop + rows.length * rowH;                   // the axis line
  // The legend: the two series as swatches at the top left of the bars
  parts.push(P.rect(x0, B.y + 6, 12, 10, { fill: ctx.pal.soft2, r: 2 }), T(ctx, x0 + 17, B.y + 11, bl, { size: 10.5, fill: ctx.pal.muted }));
  const ax = x0 + 17 + tw(bl, 10.5) + 18;                    // the second swatch after the first word
  parts.push(P.rect(ax, B.y + 6, 12, 10, { fill: ctx.pal.accent, r: 2 }), T(ctx, ax + 17, B.y + 11, al, { size: 10.5, fill: ctx.pal.muted }));   // the after swatch in the accent, like its bars
  tk.forEach(v => {                                          // gridlines and ticks
    parts.push(line(ctx, X(v), rowsTop - 2, X(v), yb, { stroke: ctx.pal.grid }));   // a light gridline through the rows
    // Tick values under the axis; the last carries the unit, right-aligned to stay inside
    parts.push(T(ctx, X(v), yb + 11, num(v) + (v === tk[tk.length - 1] ? unit : ""), { size: 10, fill: ctx.pal.muted, anchor: v === tk[tk.length - 1] && unit ? "end" : "middle" }));
  });
  parts.push(line(ctx, x0, yb, x0 + barW, yb, { stroke: ctx.pal.faint }));   // the axis line
  rows.forEach(([name, a, b, cond], i) => {                  // a pair of bars per metric
    const y = rowsTop + i * rowH + (rowH - (2 * bh + 5)) / 2;   // the pair's top, centered in its row
    // The name, and its condition under it in a smaller size, both shortened to the column
    const specs = [[fit(name, 12, true, nameW - 14, ctx.cut, `${ctx.where} name`), 12, true]].concat(cond ? [[fit(cond, 10, false, nameW - 14, ctx.cut, `${ctx.where} condition`), 10, false]] : []);
    const ys = block(y + bh + 2.5, specs, [13.5]);           // centered on the pair of bars
    // Right-aligned against the bars; the condition muted
    specs.forEach(([t, z, bo], k) => parts.push(T(ctx, x0 - 10, ys[k], t, { size: z, bold: bo, anchor: "end", fill: k ? ctx.pal.muted : ctx.pal.ink, maxw: nameW - 12 })));
    parts.push(P.rect(x0, y, Math.max(2, X(a) - x0), bh, { fill: ctx.pal.soft2, r: 3 }));   // the before bar in the soft shade
    parts.push(T(ctx, X(a) + 6, y + bh / 2, num(a) + unit, { size: 11, fill: ctx.pal.muted }));   // its value, muted
    parts.push(P.rect(x0, y + bh + 5, Math.max(2, X(b) - x0), bh, { fill: ctx.pal.accent, r: 3 }));   // the after bar in the accent, under it
    parts.push(T(ctx, X(b) + 6, y + bh * 1.5 + 5, num(b) + unit, { size: 11.5, bold: true, fill: ctx.pal.accentText }));   // its value in bold, the result the slide is about
    if (fig.delta && a > 0) {                                // the change, as a percent or a ratio
      // A ratio when it changed twofold or more, else a signed percent
      const r = b / a, t = r >= 2 || r <= 0.5 ? `×${num(r >= 1 ? r : 1 / r)}` : `${b >= a ? "+" : "−"}${num(Math.abs(r - 1) * 100)}%`;
      parts.push(T(ctx, B.x + B.w - 6, y + bh + 2.5, t, { size: 11.5, bold: true, anchor: "end", fill: ctx.pal.ink }));   // at the row's right edge
    }
  });
  condL.forEach((l, k) => parts.push(T(ctx, B.x + 6, yb + axisH + 6 + k * 14, l, { size: 10.5, fill: ctx.pal.body, maxw: B.w - 10 })));   // the conditions under the axis
  return { parts, h: yb - B.y + axisH + footH + 4 };         // the legend, rows, axis and conditions
}

// Grouped vertical bars on a value axis: groups along the bottom, one bar per series, a legend of the series at the top right
function columns(fig, B, ctx) {
  const series = fig.series || [], groups = fig.groups, unit = fig.unit || "";   // series names, groups [label, v1, v2, ...]
  const hiS = typeof fig.highlight === "number" ? fig.highlight : series.indexOf(fig.highlight);   // a series in the accent
  const max = Math.max(...groups.flatMap(g => g.slice(1))) || 1, tk = ticks(0, max, 4), top = tk[tk.length - 1] || 1;   // the value axis from zero to a round tick over the largest bar
  const yW = Math.max(...tk.map(v => tw(num(v), 10))) + 10, legH = series.length > 1 ? 20 : 0;   // the axis labels' column, legend row
  const labL = groups.map(g => lines(g[0], 10.5, false, (B.w - yW - 10) / groups.length - 8, 2, ctx.cut, `${ctx.where} group`));   // group labels in up to two lines, each as wide as its group's share
  const labH = Math.max(...labL.map(l => l.length)) * 13 + 8;   // room for the group labels
  const plotH = Math.max(70, Math.min(B.h - legH - 20 - labH - 4, Math.max(120, B.w * 0.52)));   // the plot's height: the frame's, at most about half its width
  const x0 = B.x + 4 + yW, x1 = B.x + B.w - 6, yTop = B.y + 6 + legH + 14, yb = yTop + plotH;   // the plot area
  const Y = v => yb - (yb - yTop) * v / top, parts = [];     // value to y, zero at the axis
  const rest = [ctx.pal.series[0], ctx.pal.series[2], ctx.pal.series[3], ctx.pal.series[4]];   // series colors when one is highlighted
  // Plain series colors, or the accent for the highlighted series and the rest in order
  const colors = series.map((_, i) => hiS < 0 ? ctx.pal.series[i % 5] : i === hiS ? ctx.pal.accent : rest[(i < hiS ? i : i - 1) % 4]);
  tk.forEach(v => {                                          // gridlines and the value labels at the left
    parts.push(line(ctx, x0, Y(v), x1, Y(v), { stroke: v ? ctx.pal.grid : ctx.pal.faint }));   // the zero line darker than the gridlines
    parts.push(T(ctx, x0 - 6, Y(v), num(v), { size: 10, fill: ctx.pal.muted, anchor: "end" }));   // the tick value right-aligned left of the plot
  });
  if (unit) parts.push(T(ctx, x0 - 6, yTop - 12, unit, { size: 10, fill: ctx.pal.muted, anchor: "end" }));   // the unit over the top tick
  const gw = (x1 - x0) / groups.length, ns = Math.max(1, groups[0].length - 1), bw = Math.min(34, (gw - 16) / ns - 3);   // group and bar widths
  groups.forEach((g, gi) => {                                // one cluster of bars per group
    const gx = x0 + gi * gw + (gw - (bw * ns + 3 * (ns - 1))) / 2;   // the cluster's left edge, centered in the group's share
    g.slice(1).forEach((v, si) => {                          // one bar per series
      const x = gx + si * (bw + 3), y = Y(v);                // bars 3 px apart; the bar's top
      parts.push(P.rect(x, y, bw, Math.max(1.5, yb - y), { fill: colors[si] || ctx.pal.soft2, r: 2 }));   // the bar (a zero still shows a sliver)
      const t = num(v);                                      // the value text
      // The value over the bar only when it fits the bar's width
      if (tw(t, 10, si === hiS) <= bw + 1) parts.push(T(ctx, x + bw / 2, y - 8, t, { size: 10, bold: si === hiS, anchor: "middle", fill: si === hiS ? ctx.pal.accentText : ctx.pal.muted }));
    });
    // The group label centered under its cluster
    labL[gi].forEach((l, k) => parts.push(T(ctx, x0 + gi * gw + gw / 2, yb + 11 + k * 13, l, { size: 10.5, anchor: "middle", fill: ctx.pal.body, maxw: gw - 6 })));
  });
  if (series.length > 1) {                                   // the series legend, right aligned at the top
    let lx = x1;                                             // laid out from the right edge leftward
    for (let i = series.length - 1; i >= 0; i--) {           // the last series first, so the order reads left to right
      const w = tw(series[i], 10.5);                         // the name's width
      lx -= w;                                               // room for the name
      parts.push(T(ctx, lx, B.y + 12, series[i], { size: 10.5, fill: ctx.pal.muted }));   // the series name
      lx -= 16;                                              // room for the swatch before it
      parts.push(P.rect(lx, B.y + 7, 11, 10, { fill: colors[i], r: 2 }));   // the swatch in the series color
      lx -= 14;                                              // space before the next item
    }
  }
  return { parts, h: yb - B.y + labH + 4 };                  // the plot and its group labels
}

// Lines over ordered points (stages, sizes, dates) on a value axis, each line labeled at its right end (no separate legend)
function trend(fig, B, ctx) {
  const xs = fig.x || [], series = fig.series.map(s => (Array.isArray(s) ? { name: s[0], values: s[1], kind: s[2] } : s));   // x labels, and series as { name, values, kind }
  const all = series.flatMap(s => s.values.filter(v => typeof v === "number"));   // every value drawn (a missing one is null)
  const lo = Math.min(0, ...all), max = Math.max(...all) || 1, tk = ticks(lo, max, 4), top = tk[tk.length - 1], bottom = tk[0];   // the axis covers zero and the data, on round ticks
  const yW = Math.max(...tk.map(v => tw(num(v), 10))) + 10, labW = Math.max(...series.map(s => tw(s.name, 10.5, true))) + 14;   // axis labels and end labels
  const yTop = B.y + (fig.unit ? 28 : 14);                   // the unit sits above the top tick, inside the frame
  // The plot area: labels on both sides, the height from the frame within about half the width
  const x0 = B.x + 4 + yW, x1 = B.x + B.w - 6 - labW, yb = yTop + Math.max(70, Math.min(B.h - (yTop - B.y) - 30 - (fig.note ? 16 : 0), Math.max(110, B.w * 0.5)));
  // Point index to x (a single point sits in the middle) and value to y
  const X = i => x0 + (x1 - x0) * (xs.length > 1 ? i / (xs.length - 1) : 0.5), Y = v => yb - (yb - yTop) * (v - bottom) / ((top - bottom) || 1), parts = [];
  tk.forEach(v => {                                          // gridlines and tick values
    parts.push(line(ctx, x0, Y(v), x1, Y(v), { stroke: v === bottom ? ctx.pal.faint : ctx.pal.grid }));   // the bottom line darker, as an axis
    parts.push(T(ctx, x0 - 6, Y(v), num(v), { size: 10, fill: ctx.pal.muted, anchor: "end" }));   // the value right-aligned left of the plot
  });
  if (fig.unit) parts.push(T(ctx, x0 - 6, B.y + 9, fig.unit, { size: 10, fill: ctx.pal.muted, anchor: "end" }));   // the unit over the value labels
  xs.forEach((t, i) => {                                     // x labels, kept inside the plot
    const w = tw(t, 10.5), cx = Math.max(x0 + w / 2, Math.min(x1 + labW - 4 - w / 2, X(i)));   // centered on its point, moved in so it stays inside
    // Shortened to the spacing between points
    parts.push(T(ctx, cx, yb + 14, fit(t, 10.5, false, (x1 - x0) / Math.max(1, xs.length - 1) + 8, ctx.cut, `${ctx.where} x`), { size: 10.5, anchor: "middle", fill: ctx.pal.body }));
  });
  const ends = [];                                           // end labels, nudged apart so they never touch
  series.forEach((s, si) => {                                // one line per series
    // A kind's color, else the scheme's series colors with the strongest two first
    const col = s.kind && UNIT[ctx.pal.name][s.kind] ? UNIT[ctx.pal.name][s.kind][0] : ctx.pal.series[[1, 2, 0, 3, 4][si % 5]];
    if (s.kind) kindOf(ctx, s.kind);                         // the kind is recorded; the line's name at its end says what it is
    const pts = s.values.map((v, i) => (typeof v === "number" ? [X(i), Y(v)] : null)).filter(Boolean);   // points with a value; a missing value is skipped and the line joins its neighbors
    if (pts.length > 1) parts.push(P.path("M" + pts.map(p => p.map(v => Math.round(v * 10) / 10).join(",")).join(" L"), { stroke: col, sw: 2 }));   // the line through the points, rounded to 0.1 px
    pts.forEach(p => parts.push(P.circle(p[0], p[1], 3.2, { fill: col })));   // a dot on every point
    if (pts.length) ends.push({ y: pts[pts.length - 1][1], x: pts[pts.length - 1][0], name: s.name, col });   // the last point, where the line's name goes
  });
  ends.sort((a, b) => a.y - b.y);                            // top to bottom, so nudging only pushes down
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;   // push down to keep 14 apart
  ends.forEach(e => parts.push(T(ctx, x1 + 10, e.y, e.name, { size: 10.5, bold: true })));   // the line's name at its end
  // A note under the x labels, shortened to the frame's width
  if (fig.note) parts.push(T(ctx, B.x + 6, yb + 32, fit(fig.note, 10, false, B.w - 12, ctx.cut, `${ctx.where} note`), { size: 10, fill: ctx.pal.muted }));
  return { parts, h: yb - B.y + 26 + (fig.note ? 16 : 0) };  // the plot, the x labels and the note
}

// A hierarchy: the root on top, its children in a row joined by a bus line, each child's own items stacked under it on a spine
function tree(fig, B, ctx) {
  const node = v => (Array.isArray(v) ? { title: v[0], sub: v[1], kind: v[2], children: v[3] } : v || {});   // [title, sub, kind, children]
  const root = node(fig.root), kids = (fig.children || root.children || []).map(node), n = Math.max(1, kids.length), parts = [];   // the children come from the figure or from the root itself
  const gap = 12, cw = (B.w - 8 - gap * (n - 1)) / n, rootW = Math.min(B.w * 0.5, Math.max(200, tw(root.title || "", 13, true) + 60));   // child width; the root box half the frame at most
  const rootH = root.sub ? 46 : 34, kidH = Math.max(...kids.map(k => k.sub ? 46 : 34)), busY = B.y + 4 + rootH + 18;   // rows
  const ky = busY + 16, gy0 = ky + kidH + 14;                // the children row and where their items start
  const maxG = Math.max(0, ...kids.map(k => (k.children || []).length));   // the longest list of items under one child
  // Item height: one line of title, or two when an item's title is wider than its box (English names run longer)
  const twoLine = kids.some(k => (k.children || []).map(node).some(g => tw(g.title || "", 11, true) > cw - 24 - 16));
  // Item height that fits the longest column in the frame, within a range for one or two lines
  const gh = maxG ? Math.max(twoLine ? 38 : 24, Math.min(twoLine ? 40 : 34, (B.y + B.h - 30 - gy0 - 8 * (maxG - 1)) / maxG)) : 0;
  // The root, dark by default without a legend entry
  parts.push(box(ctx, B.x + (B.w - rootW) / 2, B.y + 4, rootW, rootH, { title: root.title, sub: root.sub, kind: root.kind || "key", quiet: !root.kind, size: 13 }));
  const cx = i => B.x + 4 + i * (cw + gap) + cw / 2;         // a child's center
  parts.push(line(ctx, B.x + B.w / 2, B.y + 4 + rootH, B.x + B.w / 2, busY, { stroke: ctx.pal.faint, sw: 1.2 }));   // root down to the bus
  if (n > 1) parts.push(line(ctx, cx(0), busY, cx(n - 1), busY, { stroke: ctx.pal.faint, sw: 1.2 }));   // the bus
  kids.forEach((k, i) => {                                   // each child and its column of items
    const x = B.x + 4 + i * (cw + gap);                      // the child's left edge
    parts.push(line(ctx, cx(i), busY, cx(i), ky, { stroke: ctx.pal.faint, sw: 1.2 }));   // down to the child
    parts.push(box(ctx, x, ky, cw, kidH, { title: k.title, sub: k.sub, kind: k.kind, mark: k.mark, size: 12 }));   // the child box, which may carry a card badge
    const items = (k.children || []).map(node);              // its items, in the same shapes as the root
    if (!items.length) return;                               // a child without items has no spine
    const sx = x + 12;                                       // the spine on the child's left
    parts.push(line(ctx, sx, ky + kidH, sx, gy0 + (items.length - 1) * (gh + 8) + gh / 2, { stroke: ctx.pal.faint }));   // the spine down to the last item's middle
    items.forEach((g, j) => {                                // items stacked down the spine
      const y = gy0 + j * (gh + 8);                          // 8 px between items
      parts.push(line(ctx, sx, y + gh / 2, x + 24, y + gh / 2, { stroke: ctx.pal.faint }));   // the branch
      // A left-aligned item box; the sub shows only when the box is tall and titles take one line
      parts.push(box(ctx, x + 24, y, cw - 24, gh, { title: g.title, sub: gh >= 38 && !twoLine ? g.sub : undefined, kind: g.kind, align: "left", size: 11, subSize: 10, titleLines: twoLine ? 2 : 1, pad: 8 }));
    });
  });
  const end = maxG ? gy0 + maxG * (gh + 8) - 8 : ky + kidH;  // the foot of the deepest column
  const lg = legend(ctx, B.x + 6, end + 14, B.w - 12);       // the kinds used, under the deepest column
  if (lg.h && end + 24 <= B.y + B.h) parts.push(lg.svg);    // the legend under it when there is room
  return { parts, h: end - B.y + (lg.h && end + 24 <= B.y + B.h ? 26 : 4) };   // the tree, plus the legend row when it was drawn
}

// Several figures in one frame, each on a white panel with a title, an optional figure-to-card badge and a closing note: the
// multi-panel figures. layout: '1+2' (one wide on top, two below), '2+1', '2' (side by side), '2v' (stacked), '3v', '2x2', '3'.
// Rows get their height from what their figures need (measured by a dry run), and the frame's spare height is shared out; a figure
// shorter than its panel is centered in it
function panels(fig, B, ctx) {
  const list = (fig.panels || []).filter(Boolean), gap = 10, parts = [];   // the panels and the gap between them
  const ALIAS = { "2+2": "2x2", "1+1": "2v", "1+1+1": "3v", "4": "2x2", "2h": "2", "3h": "3" };   // other names for the same layouts
  const byCount = n => (n === 2 ? "2" : n === 3 ? "1+2" : n >= 4 ? "2x2" : "1");   // the layout that fits a count of panels
  const LAYOUTS = { "1": [1], "2": [2], "3": [3], "2v": [1, 1], "3v": [1, 1, 1], "1+2": [1, 2], "2+1": [2, 1], "2x2": [2, 2] };   // panels per row of each layout
  let lay = ALIAS[fig.layout] || fig.layout;                 // the layout as asked, under its main name
  if (!LAYOUTS[lay] || LAYOUTS[lay].reduce((a, v) => a + v, 0) < list.length) lay = byCount(list.length);   // an unknown layout, or one too small
  let ROWS = LAYOUTS[lay];                                   // panels per row; rebuilt below when a figure needs a full row
  // A figure that needs more than a half-width panel (many zones, steps, columns or children) gets a row of its own; the others pair up
  const minW = f => {
    const t = f && f.type, n = x => (Array.isArray(x) ? x.length : 0);   // the type and a safe list length
    if (t === "architecture") return n(f.zones) * 112 + (n(f.zones) - 1) * 34 + 8;   // a zone needs about 112 px, a corridor 34
    if (t === "pipeline") {                                  // it snakes onto more rows, so it only needs two boxes side by side
      // The widest single word of a step title, which cannot wrap
      const word = Math.max(...(f.steps || []).map(st => Math.max(0, ...String(Array.isArray(st) ? st[0] : st && st.title || st).split(/\s+/).map(w => tw(w, 12.5, true)))));
      return 2 * Math.max(80, word + 26) + 30;               // two boxes of at least 80 px and one gap
    }
    if (t === "matrix") return 150 + n(f.cols) * 62;         // the name column and about 62 px per column
    if (t === "tree") return n(f.children || (f.root && f.root.children)) * 108 + 8;   // about 108 px per child
    if (t === "rack") return n(f.racks) * 118;               // about 118 px per rack
    if (t === "beforeAfter") return 2 * 150 + 64;            // two sides and the arrow's gap
    if (t === "timeline" || t === "gantt") return 340;       // a date axis needs width to space its labels
    return 230;                                              // charts and small layouts read at half width
  };
  const half = (B.w - 10) / 2 - 24, wide = list.map(pn => minW(pn.figure) > half);   // which figures need a full row
  if (ROWS.some(v => v > 1) && wide.some(Boolean)) {         // rebuild the rows: wide figures alone, the rest two by two, in order
    const rows0 = [];                                        // the new panels per row
    let pend = [];                                           // a narrow figure waiting for its pair
    list.forEach((pn, i) => {                                // in the data's order
      if (wide[i]) { if (pend.length) rows0.push(pend.length); pend = []; rows0.push(1); }   // a wide figure closes the pending row and takes one of its own
      else { pend.push(i); if (pend.length === 2) { rows0.push(2); pend = []; } }   // a narrow one pairs with the next narrow one
    });
    if (pend.length) rows0.push(pend.length);                // a last unpaired figure gets a row alone
    ROWS = rows0.slice(0, 3);                                // three rows at most in one frame
  }
  const cap = ROWS.reduce((a, v) => a + v, 0);               // how many panels the rows hold
  if (list.length > cap) ctx.cut.push(`${ctx.where}: the frame holds ${cap} panels, ${list.length - cap} left out`);   // the panels past that are reported, not drawn
  const rows = [];                                           // panel indices per row
  let k = 0;                                                 // the next panel to place
  // Fill each row with the next panels in order; an empty row is dropped
  ROWS.forEach(nr => { const row = []; for (let i = 0; i < nr && k < list.length; i++) row.push(k++); if (row.length) rows.push(row); });
  // A panel's own height around its figure: the frame margin (4 a side), the title row (28), the note's lines, the foot (6)
  const chrome = (pn, w) => 8 + 24 + (pn.note ? lines(pn.note, 10.5, true, w - 8 - 24, 2, null, "").length * 14 + 8 : 0) + 6;
  const widthOf = row => (B.w - gap * (row.length - 1)) / row.length;   // panel width in a row
  // A dry run: the height a figure takes in a box, and whether it had to cut anything there
  const run = (sub, w, h) => { const c = []; const r = DRAW[sub.type] && sub.type !== "panels" ? DRAW[sub.type](sub, { x: 0, y: 0, w, h }, { ...ctx, cut: c, kinds: new Set() }) : { h: 60 }; return { h: r.h, cut: c.length }; };
  const dry = (sub, w, h) => run(sub, w, h).h;               // the height alone
  // The least height a figure draws in without cutting anything (a search between 40 px and its comfortable height)
  const leastH = (sub, w, top) => {
    let lo = 40, hi = Math.max(41, top);                     // the search range
    const base = run(sub, w, hi).cut;                        // notes the figure has at any height (a crossing, a bad link) are not about height
    const fits = h => { const r = run(sub, w, h); return r.cut <= base && r.h <= h + 1; };   // nothing more cut than at full height, nothing taller than the box
    if (!fits(hi)) return hi;                                // it needs at least its comfortable height
    while (hi - lo > 3) { const mid = (lo + hi) / 2; if (fits(mid)) hi = mid; else lo = mid; }   // a binary search to within 3 px
    return hi;                                               // the smallest height known to fit
  };
  const avail = B.h - gap * (rows.length - 1);               // height for the rows
  // Each row's comfortable height (its figures drawn with room to spare) and its least height (drawn in no room: every minimum)
  const need = rows.map(row => Math.max(...row.map(i => dry(list[i].figure || {}, widthOf(row) - 24, avail) + chrome(list[i], widthOf(row)))));
  // Each row's least height, searched below its comfortable height
  const least = rows.map((row, ri) => Math.max(...row.map(i => leastH(list[i].figure || {}, widthOf(row) - 24, need[ri] - chrome(list[i], widthOf(row))) + chrome(list[i], widthOf(row)))));
  const sum = a => a.reduce((t, v) => t + v, 0);             // the total of a list
  let heights;                                               // the row heights chosen below
  if (fig.split && rows.length === 2) heights = [avail * fig.split, avail * (1 - fig.split)];   // the data fixes the top row's share
  else if (sum(need) <= avail) heights = need.map(v => v + (avail - sum(need)) * v / sum(need));   // spare height shared in proportion
  else if (sum(least) <= avail) {                            // short of room: every row gets its least, the rest goes where it is wanted
    const want = need.map((v, i) => Math.max(0, v - least[i])), wsum = sum(want) || 1;   // what each row would still like above its least
    heights = least.map((v, i) => v + (avail - sum(least)) * want[i] / wsum);   // the spare height shared by that wish
  } else heights = least.map(v => v * avail / sum(least));  // too much for the frame: squeezed, and the panels report it
  let y = B.y;                                               // rows from the top of the frame
  rows.forEach((row, ri) => {                                // row by row
    const w = widthOf(row), h = heights[ri];                 // this row's panel width and height
    row.forEach((pi, j) => {                                 // the panels of the row, left to right
      const pn = list[pi], x = B.x + j * (w + gap);          // the panel and its left edge
      const [px, py, pw, ph] = [x + 4, y + 4, w - 8, h - 8];   // inside the frame's margin
      // The closing note in bold, markup removed, two lines at most
      const noteL = pn.note ? lines(String(pn.note).replace(/\*\*|==/g, ""), 10.5, true, pw - 24, 2, ctx.cut, `${ctx.where} note`) : [];
      const noteH = noteL.length ? noteL.length * 14 + 8 : 0;   // the closing note's room
      parts.push(P.rect(px, py, pw, ph, { fill: ctx.pal.panel, stroke: ctx.pal.line, r: 6 }));   // the white panel (the panel color on dark pages)
      const tlw = pw - 24 - (pn.mark ? 26 : 0);              // the title's room, less a badge's
      // The panel title at the top left, markup removed, shortened to its room
      if (pn.title) parts.push(T(ctx, px + 12, py + 15, fit(String(pn.title).replace(/\*\*/g, ""), 12, true, tlw, ctx.cut, `${ctx.where} panel title`), { size: 12, bold: true, maxw: tlw + 2 }));
      if (pn.mark) parts.push(D.mark(px + pw - 15, py + 15, pn.mark));   // the card number badge at the top right
      const inner = { x: px + 8, y: py + 24, w: pw - 16, h: ph - 24 - noteH - 6 };   // the sub-figure's box under the title row
      const sub = pn.figure || {};                           // the panel's figure
      if (!DRAW[sub.type] || sub.type === "panels") { ctx.cut.push(`${ctx.where}: panel ${pi + 1} has no known figure`); return; }   // an unknown or nested figure is reported and its panel left empty
      const sctx = { ...ctx, where: `${ctx.where} panel ${pi + 1} ${sub.type}`, kinds: new Set(), legend: sub.legend || ctx.legend };   // own legend per panel
      const hNat = Math.min(inner.h, dry(sub, inner.w, inner.h));   // how tall the figure is at this size
      const top = inner.y + Math.max(0, (inner.h - hNat) / 2);   // the figure and its note centered together under the title
      const res = DRAW[sub.type](sub, { ...inner, y: top, h: hNat }, sctx);   // drawn into the shared canvas, so arrow snapping sees every box
      if (res.h > inner.h + 1) ctx.cut.push(`${sctx.where}: needs ${Math.ceil(res.h)} px, the panel has ${Math.floor(inner.h)}`);   // too tall for its panel
      parts.push(...res.parts);                              // its parts join the frame's
      // The note under the figure, as a closing line
      noteL.forEach((l, q) => parts.push(T(ctx, px + 12, top + hNat + 14 + q * 14, l, { size: 10.5, bold: true, fill: ctx.pal.ink, maxw: pw - 22 })));
    });
    y += h + gap;                                            // the next row under this one
  });
  return { parts, h: B.h };                                  // a composite always fills its frame
}

const DRAW = { pipeline, beforeAfter, bars, matrix, phases, cluster, timeline, gantt, architecture, rack, metric, columns, trend, tree, panels };   // the templates by type name

// public: drawing, checks, catalog, audit

// Draw one figure as an SVG string of W x H (pipeline may end shorter). o: lang (ko|en), scheme (light|dark), where (names it in notes)
function render(fig, W, H, cut, o = {}) {
  const pal = PAL[o.scheme || fig.scheme] || PAL.light;      // the scheme
  // Notes, edition, scheme, the name used in notes, the kinds drawn and the legend words
  const ctx = { cut: cut || [], lang: o.lang === "en" || fig.lang === "en" ? "en" : "ko", pal, where: o.where || fig.type, kinds: new Set(), legend: fig.legend };
  const inset = pal.page ? 8 : 0;                            // a dark figure paints its own page with a margin inside it
  const res = DRAW[fig.type](fig, { x: inset, y: inset, w: W - 2 * inset, h: H - 2 * inset }, ctx);   // draw into the canvas inside the margin
  // A drawing taller than the frame is reported with the height it needs
  if (res.h > H - 2 * inset + 0.5) ctx.cut.push(`${ctx.where}: needs ${Math.ceil(res.h + 2 * inset)} px of height, the frame has ${H}; use fewer items or a bigger frame`);
  const h = Math.min(H, Math.ceil(res.h + 2 * inset));       // a shorter figure (one-row pipeline) ends under its last part
  const svg = new Svg(W, h);                                 // draw.js's canvas, which snaps the arrows when it writes the SVG
  if (pal.page) svg.add(DARK_DEFS, P.rect(0, 0, W, h, { fill: pal.page, r: 8 }));   // dark arrowheads and the dark page
  svg.add(res.parts);                                        // the template's parts over the page
  const label = String(fig.alt || fig.caption || fig.type).replace(/\*\*|==/g, "").replace(/"/g, "'");   // what the picture shows
  // data-figure names the template (a composite lists its panels' templates), so counts of figure kinds can be read from a deck
  const kinds = fig.type === "panels" ? "panels:" + (fig.panels || []).filter(x => x && x.figure).map(x => x.figure.type).join("+") : fig.type;
  // Role and label for screen readers (escaped for the attribute), data-figure for counts
  return svg.toString().replace("<svg ", `<svg role="img" data-figure="${kinds}" aria-label="${label.replace(/&/g, "&amp;").replace(/</g, "&lt;")}" `);
}

// Checks shared by the templates: the list each one needs is present, small enough, and its values are usable. A failed check stops the
// build with the field named (a figure with broken data drew -Infinity coordinates and 'undefined' labels)
function check(fig, where) {
  const T0 = fig.type, isNum = v => typeof v === "number" && isFinite(v);   // the type and a number test
  const need = { pipeline: "steps", bars: "rows", matrix: "rows", phases: "rows", cluster: "groups", timeline: "phases", gantt: "groups",   // the list each type must have
    architecture: "zones", rack: "racks", metric: "rows", columns: "groups", trend: "series", panels: "panels" }[T0];   // beforeAfter and tree are checked on their own below
  if (!DRAW[T0]) throw new Error(`${where}: unknown figure type '${T0}'`);   // a type the library cannot draw
  if (T0 === "beforeAfter") {                                // two sides instead of one list
    // Both sides need items
    if (!fig.before || !fig.after || !(fig.before.items || []).length || !(fig.after.items || []).length) throw new Error(`${where}: beforeAfter needs before.items and after.items`);
    if (fig.before.items.length > 6 || fig.after.items.length > 6) throw new Error(`${where}: beforeAfter takes six items a side at most`);   // more than six items do not fit a side
    return;                                                  // nothing else applies to beforeAfter
  }
  if (T0 === "tree") {                                       // children may sit on the figure or on the root
    const kids = fig.children || (fig.root && fig.root.children);   // either place
    if (!fig.root || !Array.isArray(kids) || !kids.length) throw new Error(`${where}: tree needs root and children`);   // a tree needs a root and at least one child
    if (kids.length > 6) throw new Error(`${where}: six children at most (${kids.length})`);   // more than six columns do not fit the frame
    return;                                                  // nothing else applies to tree
  }
  const list = fig[need], cap = { panels: 4, architecture: 6, rack: 8, trend: 6 }[T0] || 10;   // the list and its size limit
  if (!Array.isArray(list) || !list.length) throw new Error(`${where}: ${need} is empty`);   // an empty list drew -Infinity coordinates
  if (list.length > cap) throw new Error(`${where}: ${cap === 10 ? "ten" : cap} ${need} at most (${list.length})`);   // more items than this cannot fit the frame
  if (T0 === "bars" && !list.every(r => Array.isArray(r) && r[0] && isNum(r[1]) && r[1] >= 0))   // bars need a label and a value of zero or more
    throw new Error(`${where}: bars rows are [label, value] with a value of zero or more`);   // names the shape a row needs
  if (T0 === "matrix" && (!Array.isArray(fig.cols) || !fig.cols.length || !list.every(r => Array.isArray(r) && r.length === fig.cols.length + 1)))   // a matrix row is a name plus one cell per column
    throw new Error(`${where}: matrix needs cols and rows of [name, one cell per column]`);   // names the shape the rows need
  if (T0 === "phases" && !list.every(r => Array.isArray(r) && r[0] && /\d{4}[.\-/]\d{1,2}/.test(r[1])))   // phases need a name and a YYYY.MM start
    throw new Error(`${where}: phases rows are [name, YYYY.MM start, YYYY.MM end]`);   // names the date format
  if (T0 === "cluster" && !list.every(r => Array.isArray(r) && r[0] && isNum(r[1]) && r[1] > 0))   // a count must be above zero to draw squares
    throw new Error(`${where}: cluster groups are [name, count, note] with a count above zero`);   // names the group shape
  if (T0 === "timeline") {                                   // dates of phases and milestones
    const rows = list.map(r => (Array.isArray(r) ? r : [r.name, r.start, r.end]));   // phases as lists, from lists or objects
    // A readable start, and an end that is not before it
    if (!rows.every(r => r[0] && Number.isFinite(ym(r[1])) && (!r[2] || ym(r[2]) >= ym(r[1])))) throw new Error(`${where}: timeline phases are [name, YYYY.MM start, YYYY.MM end] with the end not before the start`);
    // Every milestone needs a readable date
    if ((fig.milestones || []).some(m => !Number.isFinite(ym(Array.isArray(m) ? m[1] : m.date)))) throw new Error(`${where}: timeline milestones are [label, YYYY.MM]`);
  }
  // Every group needs a name and tasks with a name and a readable start
  if (T0 === "gantt" && !list.every(g => g && g.name && Array.isArray(g.tasks) && g.tasks.length && g.tasks.every(t => Array.isArray(t) && t[0] && Number.isFinite(ym(t[1])))))
    throw new Error(`${where}: gantt groups are { name, tasks: [[name, YYYY.MM start, YYYY.MM end]] }`);   // names the group shape
  // Headers and tasks share the rows; more than sixteen do not fit
  if (T0 === "gantt" && list.reduce((a, g) => a + 1 + g.tasks.length, 0) > 16) throw new Error(`${where}: gantt takes sixteen rows at most (groups and tasks)`);
  if (T0 === "architecture") {                               // zones, ids and links
    // One to six nodes per zone
    if (!list.every(z => z && Array.isArray(z.nodes) && z.nodes.length && z.nodes.length <= 6)) throw new Error(`${where}: architecture zones are { title, nodes: [...] } with one to six nodes`);
    const ids = list.flatMap(z => z.nodes.map(n => (Array.isArray(n) ? n[0] : n.id ?? n.title)));   // every node's id, as the template reads it
    if (new Set(ids).size !== ids.length) throw new Error(`${where}: architecture node ids must be unique`);   // links find nodes by id, so a repeat is ambiguous
    if ((fig.links || []).length > 12) throw new Error(`${where}: twelve links at most`);   // more links than this cannot be routed apart
  }
  if (T0 === "rack" && !list.every(r => r && r.name && Array.isArray(r.units) && r.units.length && r.units.length <= 12))   // a rack needs a name and one to twelve units
    throw new Error(`${where}: rack racks are { name, units: [[label, kind, count]] } with one to twelve units`);   // names the rack shape
  if (T0 === "metric" && !list.every(r => Array.isArray(r) && r[0] && isNum(r[1]) && isNum(r[2]) && r[1] >= 0 && r[2] >= 0))   // a metric needs a name and two values of zero or more
    throw new Error(`${where}: metric rows are [name, before, after, condition] with values of zero or more`);   // names the row shape
  if (T0 === "metric" && list.length > 5) throw new Error(`${where}: metric takes five rows at most`);   // more than five pairs crowd the rows
  if (T0 === "columns") {                                    // every group needs the same number of values
    const ns = list[0].length - 1;                           // the first group sets the series count
    if (!list.every(g => Array.isArray(g) && g[0] && g.length === ns + 1 && g.slice(1).every(v => isNum(v) && v >= 0)) || ns < 1)   // each group: a label and one value per series, zero or more
      throw new Error(`${where}: columns groups are [label, one value per series] with values of zero or more`);   // names the group shape
    if (fig.series && fig.series.length !== ns) throw new Error(`${where}: columns series names one per value`);   // series names must match the value count
  }
  // Each series needs one value (or null) per x label
  if (T0 === "trend" && !list.every(s => { const v = Array.isArray(s) ? s[1] : s.values; return Array.isArray(v) && v.length === (fig.x || []).length && v.every(x => x === null || isNum(x)); }))
    throw new Error(`${where}: trend series are [name, values] with one value per x label`);   // names the series shape
  if (T0 === "panels") list.forEach((p, i) => {              // each panel holds one figure
    if (!p || !p.figure || p.figure.type === "panels") throw new Error(`${where}: panels[${i}] needs a figure (not another panels)`);   // a panel needs a figure, and panels do not nest
    check(p.figure, `${where} panel ${i + 1}`);              // the panel's figure gets its own type's checks
  });
}

// What each template is for and the shape of its data. The drafting step (src/figure_draft.py) puts this in its prompt, docs/DOCUMENTS.md lists it
const CATALOG = {
  // Steps snake onto a second row past five, so up to eight read well
  pipeline: { use: "a process or path in 3 to 8 steps", shape: '{"type":"pipeline","steps":[["title","short note","kind"]],"groups":[["band label",0,1]]}' },
  // The flow flag chains a side's items; the after items default to the person's part
  beforeAfter: { use: "the old structure next to the new one (2 to 5 items a side)", shape: '{"type":"beforeAfter","before":{"title":"","items":[["title","note"]],"flow":true,"note":""},"after":{"title":"","items":[["title","note","mine"]],"flow":true,"note":""},"change":"short word"}' },
  // Node ids tie links to nodes; units draw a node's squares
  architecture: { use: "a system as zones of nodes (2 to 4 zones, 1 to 5 nodes each) with labeled links between neighbors", shape: '{"type":"architecture","zones":[{"title":"","kind":"","nodes":[{"id":"a","title":"","sub":"","kind":"mine","units":8}]}],"links":[["a","b","protocol","mine"]]}' },
  // Units carry a count; twelve or fewer are also drawn as squares
  rack: { use: "a cluster or data center as racks of units under a switch fabric", shape: '{"type":"rack","fabric":{"label":"","items":["switch"]},"racks":[{"name":"","sub":"","units":[["GPU node","mine",8]]}]}' },
  // Dates must be YYYY.MM so the checks can read them
  timeline: { use: "project phases and milestones on dates (YYYY.MM)", shape: '{"type":"timeline","phases":[["name","2024.01","2024.06","note","kind"]],"milestones":[["label","2024.06"]]}' },
  // The sixteen-row cap is the one check() enforces
  gantt: { use: "workstreams of tasks over months (up to 16 rows)", shape: '{"type":"gantt","groups":[{"name":"","tasks":[["task","2024.01","2024.03","kind"]]}],"milestones":[["label","2024.03"]]}' },
  // The fact check holds both values to the project's own numbers
  metric: { use: "before and after numbers measured under stated conditions (numbers must be in the evidence)", shape: '{"type":"metric","unit":"","better":"lower","beforeLabel":"","afterLabel":"","rows":[["metric",10,4,"condition"]],"conditions":""}' },
  bars: { use: "one number per item (numbers must be in the evidence)", shape: '{"type":"bars","unit":"","rows":[["item",3]],"highlight":["item"]}' },   // highlight names the rows to accent
  // One value per series in every group
  columns: { use: "numbers per group and series (numbers must be in the evidence)", shape: '{"type":"columns","unit":"","series":["A","B"],"groups":[["group",1,2]]}' },
  // One value per x label in every series
  trend: { use: "how numbers move across ordered points (numbers must be in the evidence)", shape: '{"type":"trend","unit":"","x":["p1","p2","p3"],"series":[["name",[1,2,3]]]}' },
  // The mark words (yes, partial, no) draw as signs with a legend
  matrix: { use: "options or items against criteria with yes, partial, no or short text", shape: '{"type":"matrix","cols":["c1","c2"],"rows":[["row","yes","partial"]]}' },
  // A child's fourth element lists its items
  tree: { use: "a hierarchy: a root, 2 to 5 children, their items", shape: '{"type":"tree","root":["title","sub"],"children":[["child","sub","kind",[["item"]]]]}' },
  // The count is written; the squares only show proportion
  cluster: { use: "counts of nodes per role (numbers must be in the evidence)", shape: '{"type":"cluster","unit":"","groups":[["role",4,"note"]]}' },
  phases: { use: "a few named periods on months", shape: '{"type":"phases","rows":[["name","2024.01","2024.06","note"]]}' },   // a lighter form of timeline for a few periods
  // The mark field ties a panel to the card with the same number
  panels: { use: "the main figure of a slide: two to four of the above, each with a title and the number of the card it explains", shape: '{"type":"panels","layout":"1+2","panels":[{"title":"","mark":1,"note":"","figure":{}}]}' },
};

// Static audit of a drawn figure: text outside the canvas, text over text, text across a box edge, text wider than its box. It reads the
// SVG the templates wrote (P.text and P.rect attributes) with the font metrics, so it runs in node without a browser. The deck's browser
// probe is the final word; this catches the same faults earlier (tests, the drafting step's review)
function audit(svg) {
  const vb = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/), W = vb ? +vb[1] : 0, H = vb ? +vb[2] : 0;   // the canvas
  const attr = (s, k) => { const m = s.match(new RegExp(`\\s${k}="([^"]*)"`)); return m ? m[1] : null; };   // one attribute
  // Markup and entities back to the plain text that is measured
  const unesc = s => s.replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&amp;/g, "&");
  const body = svg.replace(/<defs>[\s\S]*?<\/defs>/g, "");   // markers are not drawing
  const texts = [], rects = [], issues = [];                 // measured texts, box rectangles, findings
  for (const m of body.matchAll(/<text\b([^>]*)>([\s\S]*?)<\/text>/g)) {   // every text with its box
    const a = m[1], s = unesc(m[2]);                         // the attributes and the shown text
    if (!s.trim()) continue;                                 // empty text cannot overflow
    const size = +attr(a, "font-size"), bold = +(attr(a, "font-weight") || 400) >= 600, x = +attr(a, "x"), base = +attr(a, "y");   // what the width depends on, and the anchor point
    // A squeezed text's own length, else the measured width (a two-space sub gets its half-letter gap)
    const w = attr(a, "textLength") ? +attr(a, "textLength") : tw(s.replace(/\s{2,}/g, "  "), size, bold) + (/<tspan[^>]*dx=/.test(m[2]) ? size * 0.5 : 0);
    const anchor = attr(a, "text-anchor") || "start", x0 = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;   // the left edge from the anchor
    // The text's box from its baseline (ascent 0.78, descent 0.12 of the size) and its maxw
    texts.push({ s, x0, x1: x0 + w, y0: base - size * 0.78, y1: base + size * 0.12, maxw: attr(a, "data-maxw") ? +attr(a, "data-maxw") : null, w });
  }
  for (const m of body.matchAll(/<rect\b([^>]*)\/>/g)) {     // every rectangle that is a box (decorations are not)
    const a = m[1];                                          // the rectangle's attributes
    if (/data-deco="1"/.test(a)) continue;                   // decorations are not boxes
    const x = +attr(a, "x"), y = +attr(a, "y"), w = +attr(a, "width"), h = +attr(a, "height");   // its geometry
    if (w >= W - 0.5 && h >= H - 0.5) continue;              // the dark page under everything
    rects.push({ x0: x, y0: y, x1: x + w, y1: y + h });      // as edges, like the texts
  }
  const inter = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));   // the overlap area of two rectangles
  const area = a => (a.x1 - a.x0) * (a.y1 - a.y0);           // a rectangle's area
  texts.forEach(t => {                                       // each text against the canvas and every box
    if (t.x0 < -0.5 || t.x1 > W + 0.5 || t.y0 < -0.5 || t.y1 > H + 0.5) issues.push(`text outside the canvas: '${t.s.slice(0, 30)}'`);   // half a pixel of rounding is allowed
    if (t.maxw && t.w > t.maxw + 0.5) issues.push(`text wider than its box: '${t.s.slice(0, 30)}' (${Math.round(t.w - t.maxw)})`);   // the probe's maxw rule, checked here first
    rects.forEach(r => {                                     // a text that is partly inside a box crosses its edge
      const ov = inter(t, r);                                // how much of the text lies inside the box
      if (ov > 2 && ov < area(t) - 2 && ov > 0.08 * area(t)) issues.push(`text across a box edge: '${t.s.slice(0, 30)}'`);   // partly inside and partly out, beyond tiny rounding overlaps
    });
  });
  // Arrow over arrow: two arrows whose shafts cross away from their ends. The browser probe finds the same when the deck is printed;
  // finding it here lets the figure step turn such a drawing down before anyone sees it. A branch that ends on another arrow meets
  // it at its own end, which is a connection and not a crossing, and a line marked data-through crosses on purpose
  const arrows = [];                                         // each arrow's points
  for (const m of body.matchAll(/<(path|line)\b([^>]*)\/>/g)) {   // every path and line
    const a = m[2], d = attr(a, "d");                        // its attributes and its path
    if (!/marker-(end|start)=/.test(a) || /data-through="1"/.test(a)) continue;   // not an arrow, or a crossing on purpose
    let pts = null;                                          // its corners
    if (m[1] === "path" && d && /^M[-\d.]+,[-\d.]+( L[-\d.]+,[-\d.]+)+$/.test(d)) pts = d.slice(1).split(" L").map(q => q.split(",").map(Number));   // straight runs only
    else if (m[1] === "line") pts = [[+attr(a, "x1"), +attr(a, "y1")], [+attr(a, "x2"), +attr(a, "y2")]];   // one run
    if (pts) arrows.push({ pts, d: d || pts.join(" ") });    // kept with its path for the message
  }
  const segPt = (p, a, b) => {                               // the distance from point p to run a-b
    const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;   // the run's direction and squared length
    const t = L2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) : 0;   // the nearest place along it
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);   // to that place
  };
  const side = (a, b, c) => Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));   // which side of a-b point c lies on
  const meets = (p, q, r, s) =>                             // do runs p-q and r-s cross, touch or run along each other
    (side(p, q, r) !== side(p, q, s) && side(r, s, p) !== side(r, s, q)) || Math.min(segPt(p, r, s), segPt(q, r, s), segPt(r, p, q), segPt(s, p, q)) <= 0.5;
  const nearPoly = (pt, pts) => pts.slice(1).some((q, k) => segPt(pt, pts[k], q) <= 2.5);   // does a line pass at a point
  for (let i = 0; i < arrows.length; i++) for (let j = i + 1; j < arrows.length; j++) {   // each pair
    const A = arrows[i].pts, B = arrows[j].pts;              // their corners
    // Arrows that meet at an end (a shared start, a branch that leaves or reaches another) are connected, as the probe reads them
    if ([A[0], A[A.length - 1]].some(e => nearPoly(e, B)) || [B[0], B[B.length - 1]].some(e => nearPoly(e, A))) continue;
    let hit = false;                                         // a crossing found
    for (let k = 0; k + 1 < A.length && !hit; k++) for (let l = 0; l + 1 < B.length && !hit; l++) hit = meets(A[k], A[k + 1], B[l], B[l + 1]);   // run by run
    if (hit) issues.push(`arrow over arrow: '${arrows[i].d.slice(0, 30)}' / '${arrows[j].d.slice(0, 30)}'`);   // both named by their path
  }
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {   // text over text
    const a = texts[i], b = texts[j], ov = inter(a, b);      // a pair and their overlap
    if (ov > 3 && ov > 0.1 * Math.min(area(a), area(b))) issues.push(`text over text: '${a.s.slice(0, 24)}' / '${b.s.slice(0, 24)}'`);   // more than 10% of the smaller text covered
  }
  return [...new Set(issues)];                               // each finding once
}

const TEMPLATES = Object.fromEntries(Object.keys(DRAW).map(k => [k, (fig, W, H, cut, o) => render({ ...fig, type: k }, W, H, cut, o)]));   // one function per type that sets the type on the data
module.exports = { TEMPLATES, DRAW, render, check, audit, wrap, fit, lines, CATALOG, PAL, KIND, KINDS, WORDS, ym };   // what the deck, the drafting step and the tests use

// Command line: draw one figure and print its audit and cut notes (the drafting step's review calls this)
if (require.main === module) {
  const a = process.argv.slice(2);                           // the command's arguments
  // Only --audit with a file is understood
  if (a[0] !== "--audit" || !a[1]) { console.error("usage: node src/deck_figures.js --audit <figure.json> [W H ko|en light|dark]"); process.exit(1); }
  const figs = JSON.parse(require("fs").readFileSync(a[1], "utf-8"));   // one figure or a list of them
  const out = [].concat(figs).map(f => {                     // one result per figure, in order
    const W = +(f._w || a[2] || 760), H = +(f._h || a[3] || 570), cut = [];   // the figure's own slot size, else the arguments, else the main slot
    try { check(f, "figure"); } catch (e) { return { ok: false, error: e.message }; }   // bad data: no drawing
    try {                                                    // a drawing error comes back as a result, not a crash
      const svg = render(f, W, H, cut, { lang: f._lang || a[4] || "ko", scheme: a[5] || "light" });   // the edition the figure carries, else the arguments
      const issues = audit(svg);                             // the static checks of the drawing
      return { ok: !issues.length && !cut.length, issues, cut, bytes: svg.length };   // ok only with no findings and nothing cut
    } catch (e) { return { ok: false, error: `${e.name}: ${e.message}` }; }   // the error named, so the review can show it
  });
  process.stdout.write(JSON.stringify(out));                 // JSON for figure_draft.py to read
}
