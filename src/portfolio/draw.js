// Drawing tools for the portfolio. Every picture is redrawn from scratch as a vector (SVG) in the resume theme. The original
// screenshots a person supplies are used only for their structure and names: the numbers and people's names inside a
// screen are not copied. Values become bars, lines and progress bars, and only the information structure, such as menu and card
// names, is kept.
//
// SVG text has no automatic line breaking. Text that has to fit a box carries data-maxw, and the browser probe (PROBE in deck.js)
// reports an overflow when the real text width is larger than that.

const C = {
  navy: "#1B2E4B", blue: "#2F6EBA", band: "#EEF3F9", key: "#F5F8FC", rule: "#C9D4E3", ink: "#1F1F1F",
  body: "#333333", grey: "#6B6B6B", faint: "#9A9A9A", line: "#D8D8D8", hl: "#FFF0A0", white: "#FFFFFF",
  // Steps of one color family, used only for charts and for telling hierarchy levels apart. n3 is dark enough that white text on it
  // reaches a contrast of 5.0 and n3 text on white stays above 4.5. The probe's
  // contrast check measures it.
  n2: "#3A5578", n3: "#5B7290", b2: "#6E9BD1", b3: "#A9C3E4", b4: "#D5E2F2",
  // Two extra colors for telling categories apart. Blue, orange (a2) and teal (t2) are the set of three category colors. Every pair
  // of the three stays distinguishable, color-vision simulations included (OKLab distance of 9.7 or more), and each has a contrast
  // above 3:1 on white (checked with a palette validator).
  // Steps: teal and amber are dark fills that carry white text (contrast 5.2). t2 and a2 are marks without text (bars, cells). t3
  // and a3 are pale fills that carry navy text. t4 and a4 are group backgrounds (color difference from white 9.3 and 7.6). When
  // color carries a meaning, the figure states that meaning in a legend or a label.
  // Group background of the blue category (b5) and the text on it (b1): blue text on b4 reached only 3.94:1, which is too low.
  b1: "#24599A", b5: "#E6EFF9",
  teal: "#137A63", t2: "#1A9C7E", t3: "#A3DCC8", t4: "#E1F3EC",
  amber: "#A9561B", a2: "#D97A2B", a3: "#F2C9A2", a4: "#FBEEE2",
};
// Background levels. The four light backgrounds (white, the figure frame paper #F4F6FA, band and key) differ from each other by
// only 0.6 to 4.2 in CIEDE2000, so a box placed directly on another one disappears (band on paper measures 1.6).
// A box on the figure frame gets a white fill with a rule border. A box on a white panel gets band (4.2, no border needed) or a
// white fill with a rule border. A box on band or key gets a white fill with a rule border. key is only 2.6 away from a white
// panel, so it is not used as a box fill (a group background is used together with a border). A line is never lighter than rule
// (a band line is invisible).
// Text color on a painted fill: navy on a light fill (b2, b3, b4, band), white on a dark one. White text exceeds a contrast of
// 4.5 below a luminance of 0.18 and navy text exceeds it above 0.3 (white on b2 was only 2.9:1).
const lumHex = h => { const v = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
C.on = fill => /^#[0-9A-Fa-f]{6}$/.test(fill) && lumHex(fill) > 0.24 ? C.navy : C.white;

const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");   // text and attribute values alike: a quote never ends an attribute early
const r1 = v => Math.round(v * 10) / 10;

// Text width, measured from the glyph advances in the Pretendard font files (opentype.js). Estimates per character class
// overstated Hangul by 8% and threw box layouts off. Weight is 700 for true or 700, 600 for "semi" or 600, and 400 otherwise.
const path = require("path");
const opentype = require("opentype.js");
const FONT_DIR = path.join(__dirname, "..", "..", "fonts");
const FONTS = { 400: opentype.loadSync(path.join(FONT_DIR, "Pretendard-Regular.ttf")),
  600: opentype.loadSync(path.join(FONT_DIR, "Pretendard-SemiBold.ttf")), 700: opentype.loadSync(path.join(FONT_DIR, "Pretendard-Bold.ttf")) };
const weightOf = b => b === true || b === 700 || b === "bold" ? 700 : b === "semi" || b === 600 ? 600 : 400;
// Distance from the middle of the em box to the alphabetic baseline, in multiples of the font size. It is the same place as
// dominant-baseline central, but Chrome derives central from font metrics rounded at screen size, so text moved up and down by
// up to 0.5px depending on the scale a figure was shrunk to and on the font size. Computing the baseline directly and drawing
// with alphabetic puts the text at the same spot at every scale.
const CENTRAL = (FONTS[400].ascender + FONTS[400].descender) / 2 / FONTS[400].unitsPerEm;
const r2 = v => Math.round(v * 100) / 100;
// Top and bottom of the ink of a text, relative to the baseline (down is positive). Latin descenders (g, j, p, q, y, brackets and
// so on) are left out of the bottom so that the optical center is found.
const DESC = new Set("gjpqy,;()[]{}/|_@$Q");
function inkV(s, size, bold) {
  const f = FONTS[weightOf(bold)], k = size / f.unitsPerEm;
  let top = -Infinity, bot = Infinity;
  for (const ch of String(s)) {
    if (!ch.trim()) continue;
    const bb = f.charToGlyph(ch).getBoundingBox();
    if (bb.y2 <= bb.y1) continue;
    top = Math.max(top, bb.y2);
    if (!DESC.has(ch)) bot = Math.min(bot, bb.y1);
  }
  if (top === -Infinity) return [-0.7 * size, 0];
  if (bot === Infinity) bot = 0;
  return [-top * k, -bot * k];
}
// Glyph outline bounds used by the deck probe (PROBE in deck.js): for each character of chars and each weight, [advance width,
// xMin, xMax, yMin, yMax] in font units (up is positive). Ink measures from a browser canvas are rounded to whole numbers,
// which is too coarse for a test within 1px.
function glyphTable(chars) {
  const w = {};
  for (const [k, f] of Object.entries(FONTS)) {
    const t = {};
    for (const ch of chars) {
      const g = f.charToGlyph(ch);
      if (!g || g.index === 0) continue;
      const bb = g.getBoundingBox();
      t[ch] = [g.advanceWidth, bb.x1, bb.x2, bb.y1, bb.y2].map(v => Math.round(v));
    }
    w[k] = t;
  }
  return { upm: FONTS[400].unitsPerEm, w };
}
// Center several lines vertically as one block. lines is [[text, size, weight], ...] and gaps are the distances between line
// centers (one fewer than the lines). Returns the y of each line (the y that P.text takes) such that the middle between the top
// of the first line's ink and the bottom of the last line's ink (Latin descenders excluded) lands on cy.
function stackY(cy, lines, gaps = []) {
  const ys = [0]; gaps.forEach(g => ys.push(ys[ys.length - 1] + g));
  const [s0, z0, b0] = lines[0], [s1, z1, b1] = lines[lines.length - 1];
  const top = CENTRAL * fsz(z0) + inkV(s0, fsz(z0), b0)[0];
  const bot = ys[ys.length - 1] + CENTRAL * fsz(z1) + inkV(s1, fsz(z1), b1)[1];
  const sh = cy - (top + bot) / 2;
  return ys.map(v => v + sh);
}
function tw(s, size, bold, ls = 0) {
  const str = String(s);
  return FONTS[weightOf(bold)].getAdvanceWidth(str, size) + (ls ? ls * Math.max(0, [...str].length - 1) : 0);
}

// Minimum text size in figures (figure coordinates). The large figure on the left sits at about 0.87 of its natural size, because
// of the frame padding (6px) and the project header, so 10 comes out as 8.7px on screen. The probe flags text under 8.6px on
// screen. The clamp is applied here in fsz instead of at every call site.
const MIN_TEXT = 10;
const fsz = v => Math.max(v, MIN_TEXT);

const attrs = o => Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== false)
  .map(([k, v]) => `${k}="${esc(v)}"`).join(" ");

const P = {
  rect: (x, y, w, h, o = {}) => `<rect ${attrs({ x: r1(x), y: r1(y), width: r1(w), height: r1(h), rx: o.r ?? 3, fill: o.fill ?? C.white,
    stroke: o.stroke ?? "none", "stroke-width": o.sw ?? 1, "stroke-dasharray": o.dash, opacity: o.op, "data-deco": o.deco ? 1 : undefined,
    // A box whose text is deliberately pinned to the top (top) or placed by hand (free). The probe leaves it out of the vertical
    // centering test; the touching test still applies.
    "data-valign": o.valign })}/>`,
  circle: (cx, cy, r, o = {}) => `<circle ${attrs({ cx: r1(cx), cy: r1(cy), r: r1(r), fill: o.fill ?? C.white, stroke: o.stroke ?? "none",
    "stroke-width": o.sw ?? 1, opacity: o.op })}/>`,
  line: (x1, y1, x2, y2, o = {}) => `<line ${attrs({ x1: r1(x1), y1: r1(y1), x2: r1(x2), y2: r1(y2), stroke: o.stroke ?? C.rule,
    "stroke-width": o.sw ?? 1, "stroke-dasharray": o.dash, "marker-end": o.arrow ? `url(#ah-${o.arrow})` : undefined,
    "marker-start": o.arrow2 ? `url(#ah-${o.arrow2})` : undefined, "stroke-linecap": o.cap, "data-free": o.free ? 1 : undefined, "data-through": o.through ? 1 : undefined })}/>`,
  path: (d, o = {}) => { curvedArrowGuard(d, o); return `<path ${attrs({ d, fill: o.fill ?? "none", stroke: o.stroke ?? C.rule, "stroke-width": o.sw ?? 1,
    "stroke-dasharray": o.dash, "stroke-linejoin": "round", "stroke-linecap": o.arrow ? "butt" : "round", opacity: o.op,
    "marker-end": o.arrow ? `url(#ah-${o.arrow})` : undefined, "data-free": o.free ? 1 : undefined, "data-through": o.through ? 1 : undefined })}/>`; },
  // Polygon. Arrow snapping and the probe recognize it as a box (the same shape drawn as a path would be missed by both).
  poly: (pts, o = {}) => `<polygon ${attrs({ points: pts.map(p => p.map(r1).join(",")).join(" "), fill: o.fill ?? C.white, stroke: o.stroke ?? "none",
    "stroke-width": o.sw ?? 1, "stroke-linejoin": "round" })}/>`,
  // Text. y is the middle of the text (the middle of the em box; the baseline is computed from CENTRAL). Giving maxw makes it a
  // measured text. The size never goes below MIN_TEXT.
  // Text centered this way lands within about 0.1px of the center of the bands and boxes it sits in (shape centers and ink centers
  // compared on the same raster). Badges and pills are the parts that can look off, so their offsets are handled in those parts
  // (D.num, D.mark, D.pill).
  text: (x, y, s, o = {}) => { const size = fsz(o.size ?? 11.5); return `<text ${attrs({ x: r1(x), y: r2(y + CENTRAL * size), "font-size": size, "font-weight": o.bold ? 700 : o.semi ? 600 : 400,
    fill: o.fill ?? C.ink, "text-anchor": o.anchor ?? "start", "letter-spacing": o.ls,
    "data-maxw": o.maxw ? r1(o.maxw) : undefined, opacity: o.op,
    // halo: a white outline around text that sits on a line, so that it stays readable
    stroke: o.halo ? "#FFFFFF" : undefined, "stroke-width": o.halo ? 4 : undefined, "paint-order": o.halo ? "stroke" : undefined,
    "stroke-linejoin": o.halo ? "round" : undefined })}>${splitSub(s, size, o)}</text>`; },
};

// Figure text of the form 'name  description' (a double space). SVG collapses consecutive spaces into one, so such a label read
// as one run-on sentence. The part after the double space becomes a tspan offset by half an em, and bold text drops to normal
// weight there. The color is unchanged.
function splitSub(t, size, o) {
  const parts = String(t).split(/ {2,}/);
  if (parts.length < 2 || !parts[0].trim()) return esc(t);
  const w = o.bold || o.semi ? ' font-weight="400"' : "";
  // The leading name is wrapped in a tspan too. The probe measures only the tspans of a text that has any, so an unwrapped name
  // would escape the check.
  return `<tspan>${esc(parts[0])}</tspan>` + parts.slice(1).map(p => `<tspan dx="${r1(size * 0.5)}"${w}>${esc(p)}</tspan>`).join("");
}

// Arrowhead markers: a normal head and a small one for every color. snapArrows swaps the small head onto short arrows.
// A curved arrow must end in a straight segment at least 1.2 times the head length. The head points along the tangent at the end
// point, and if the curve keeps bending under the head, the line pokes out of the head's side. Curved paths are seen neither by
// snapArrows nor by the probe's arrow checks, so the build refuses them. Only absolute commands (M L H V C Q A) are allowed.
function curvedArrowGuard(d, o) {
  if (!o.arrow || !/[CcSsQqTtAa]/.test(d)) return;
  const segs = d.match(/[A-Za-z][^A-Za-z]*/g).map(t => [t[0], (t.slice(1).match(/-?\d*\.?\d+(?:e-?\d+)?/g) || []).map(Number)]);
  if (segs.some(([c]) => c !== c.toUpperCase())) throw new Error("a curved arrow must use absolute coordinates: " + d);
  let x = 0, y = 0, px = 0, py = 0;
  for (const [c, a] of segs) {
    px = x; py = y;
    if (c === "H") x = a[a.length - 1]; else if (c === "V") y = a[a.length - 1];
    else { x = a[a.length - 2]; y = a[a.length - 1]; }
  }
  const last = segs[segs.length - 1][0], need = 1.2 * HEAD * (o.sw ?? 1), len = Math.hypot(x - px, y - py);
  if (!"LHV".includes(last) || len < need) throw new Error(`a curved arrow must end in a straight segment of at least ${need.toFixed(1)} (now ${last} ${len.toFixed(1)}): ${d}`);
}
// The line ends inside the head (refX 7.5) with a butt cap. At refX 9 the head is narrower than the stroke, so the round line end
// stuck out past the pointed tip as a dot. The heads (HEAD, HEAD_S) are kept small because larger ones looked big against the
// gaps between boxes.
const HEAD = 5.4, HEAD_S = 3.9;
const DEFS = `<defs>${[["blue", C.blue], ["navy", C.navy], ["grey", C.faint]].map(([k, c]) => [["", HEAD], ["-s", HEAD_S]].map(([sfx, mw]) =>
  `<marker id="ah-${k}${sfx}" viewBox="0 0 10 10" refX="7.5" refY="5" markerWidth="${mw}" markerHeight="${mw}" orient="auto-start-reverse">` +
  `<path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`).join("")).join("")}</defs>`;

// Arrow end snapping
// Arrow end points are fitted in one pass when the figure is exported, so a head neither stops short of a box nor pierces it:
// the head of a straight arrow (a path made only of M and L, or a line) moves to TIP_GAP before the first box border it meets in
// its direction of travel (the tip of the head reaches about 1 past the end of the line, so it looks like it touches the border),
// and the tail moves to start on the border of the box behind it. A rectangle that holds both ends of the arrow (a grouping
// panel) is not a box to touch. A tail that branches off another line and an arrow marked data-free (order markers, conversions
// between graphs) are left alone. Whether the result is right is measured separately on the rendered figure, by the arrow checks
// in the PROBE of deck.js.
const TIP_GAP = 2.2, REACH = 30, PULL = 12;
// Vertices of a closed straight-line path (M, L, H, V, Z and their lowercase forms). Returns null when a curve is mixed in (such
// a path is not counted as a box).
function pathVertices(d) {
  if (!d || /[CcSsQqTtAa]/.test(d) || !/[Zz]\s*$/.test(d)) return null;
  const toks = d.match(/[MmLlHhVvZz]|-?\d*\.?\d+(?:e-?\d+)?/g) || [];
  const pts = [];
  let x = 0, y = 0, cmd = null, i = 0;
  const n = () => parseFloat(toks[i++]);
  while (i < toks.length) {
    if (/[A-Za-z]/.test(toks[i])) cmd = toks[i++];
    if (cmd === "Z" || cmd === "z") continue;
    if (cmd === "M" || cmd === "L") { x = n(); y = n(); }
    else if (cmd === "m" || cmd === "l") { x += n(); y += n(); }
    else if (cmd === "H") x = n(); else if (cmd === "h") x += n();
    else if (cmd === "V") y = n(); else if (cmd === "v") y += n();
    else return null;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    pts.push([x, y]);
  }
  return pts.length >= 3 ? pts : null;
}
function snapArrows(markup) {
  const num = v => parseFloat(v);
  const attrsOf = t => { const o = {}; t.replace(/([\w:-]+)="([^"]*)"/g, (_, k, v) => { o[k] = v; return ""; }); return o; };
  const toks = [], boxes = [], strokes = [];
  const gstack = [];
  const re = /<(\/?)(g|rect|circle|ellipse|polygon|image|path|line|defs|marker)\b([^>]*?)(\/?)>/g;
  let m, inDefs = 0;
  while ((m = re.exec(markup))) {
    const [all, close, tag, rest, self] = m;
    if (tag === "defs" || tag === "marker") { if (!self) inDefs += close ? -1 : 1; continue; }
    if (tag === "g") {
      if (close) { gstack.pop(); continue; }
      // An icon (lucide, drawn from 2 to 22 inside its 24 cell) counts as a box over its visible extent. The shapes inside an icon are
      // not boxes.
      const ic = /data-icon=/.test(rest) && !gstack.some(Boolean) && /translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+)\)/.exec(rest);
      if (ic) { const x = num(ic[1]), y = num(ic[2]), k = num(ic[3]); boxes.push({ x0: x + 2 * k, y0: y + 2 * k, x1: x + 22 * k, y1: y + 22 * k }); }
      if (!self) gstack.push(/data-icon=/.test(rest) || gstack.some(Boolean));
      continue;
    }
    if (close || inDefs || gstack.some(Boolean)) continue;
    const a = attrsOf(rest);
    if (a["data-deco"]) continue;
    const painted = tag === "image" || (a.fill ?? "") !== "none" || (a.stroke ?? "none") !== "none";
    let r = null;
    if (tag === "rect" || tag === "image") r = { x0: num(a.x), y0: num(a.y), x1: num(a.x) + num(a.width), y1: num(a.y) + num(a.height) };
    // Circles and ellipses are measured as true curves. Measured by bounding box, an arrow beside a loop ring counted as touching it
    // even 16 away from the ring.
    else if (tag === "circle") r = { ell: true, cx: num(a.cx), cy: num(a.cy), rx: num(a.r), ry: num(a.r) };
    else if (tag === "ellipse") r = { ell: true, cx: num(a.cx), cy: num(a.cy), rx: num(a.rx), ry: num(a.ry) };
    else if (tag === "polygon" || (tag === "path" && (a.fill ?? "none") !== "none")) {
      // A filled closed shape (the side face of a 3D block, a gate shape) is also a box that arrows touch. Leaving it out let a tail
      // pierce the side face of a block.
      const v = tag === "polygon" ? (() => { const q = (a.points || "").trim().split(/[\s,]+/).map(num); const o = []; for (let k = 0; k + 1 < q.length; k += 2) o.push([q[k], q[k + 1]]); return o; })() : pathVertices(a.d);
      if (v && v.length) r = { x0: Math.min(...v.map(p => p[0])), y0: Math.min(...v.map(p => p[1])), x1: Math.max(...v.map(p => p[0])), y1: Math.max(...v.map(p => p[1])) };
    }
    if (r && r.ell) { Object.assign(r, { x0: r.cx - r.rx, y0: r.cy - r.ry, x1: r.cx + r.rx, y1: r.cy + r.ry }); }
    if (r && [r.x0, r.y0, r.x1, r.y1].every(Number.isFinite) && r.x1 - r.x0 >= 3 && r.y1 - r.y0 >= 3 && painted) { boxes.push(r); if (tag !== "path") continue; }
    let pts = null;
    if (tag === "path" && /^M[-\d.]+,[-\d.]+( L[-\d.]+,[-\d.]+)+$/.test(a.d || "")) pts = a.d.slice(1).split(" L").map(q => q.split(",").map(num));
    else if (tag === "line") pts = [[num(a.x1), num(a.y1)], [num(a.x2), num(a.y2)]];
    if (!pts || (a.stroke ?? "none") === "none") continue;
    strokes.push(pts);
    if (a["marker-end"] || a["marker-start"]) toks.push({ i: m.index, len: all.length, all, tag, a, pts, free: !!a["data-free"] });
  }
  if (!toks.length) return markup;
  const area = r => r.ell ? Math.PI * r.rx * r.ry : (r.x1 - r.x0) * (r.y1 - r.y0);
  // Whether point p is inside shape r, t inside its border (a negative t widens the shape outward)
  const inR = (r, p, t = 0) => {
    if (r.ell) { const ax = r.rx - t, ay = r.ry - t; return ax > 0 && ay > 0 && ((p[0] - r.cx) / ax) ** 2 + ((p[1] - r.cy) / ay) ** 2 < 1; }
    return p[0] > r.x0 + t && p[0] < r.x1 - t && p[1] > r.y0 + t && p[1] < r.y1 - t;
  };
  const inside = (q, r) => q.x0 >= r.x0 - 0.5 && q.y0 >= r.y0 - 0.5 && q.x1 <= r.x1 + 0.5 && q.y1 <= r.y1 + 0.5;
  // Distances [t0, t1] at which a ray from point p in direction d enters and leaves the shape
  const slab = (r, p, d) => {
    if (r.ell) {
      const ox = (p[0] - r.cx) / r.rx, oy = (p[1] - r.cy) / r.ry, dx = d[0] / r.rx, dy = d[1] / r.ry;
      const A = dx * dx + dy * dy, B = 2 * (ox * dx + oy * dy), Cc = ox * ox + oy * oy - 1, D = B * B - 4 * A * Cc;
      if (A < 1e-12 || D < 0) return null;
      const s = Math.sqrt(D);
      return [(-B - s) / (2 * A), (-B + s) / (2 * A)];
    }
    let t0 = -Infinity, t1 = Infinity;
    for (const [pp, dd, lo, hi] of [[p[0], d[0], r.x0, r.x1], [p[1], d[1], r.y0, r.y1]]) {
      if (Math.abs(dd) < 1e-9) { if (pp <= lo || pp >= hi) return null; continue; }
      const u = (lo - pp) / dd, v = (hi - pp) / dd;
      t0 = Math.max(t0, Math.min(u, v)); t1 = Math.min(t1, Math.max(u, v));
    }
    return t0 <= t1 ? [t0, t1] : null;
  };
  // Whether the point lies on the border of the shape (within 0.75)
  const onBorder = (r, p) => {
    if (r.ell) { const q = Math.hypot((p[0] - r.cx) / r.rx, (p[1] - r.cy) / r.ry); return Math.abs(q - 1) * Math.min(r.rx, r.ry) <= 0.75; }
    return p[0] >= r.x0 - 0.75 && p[0] <= r.x1 + 0.75 && p[1] >= r.y0 - 0.75 && p[1] <= r.y1 + 0.75 && !inR(r, p, 0.75);
  };
  const onStroke = (p, own) => strokes.some(s2 => s2 !== own && s2.some((q, k) => {
    if (!k) return false;
    const a0 = s2[k - 1], dx = q[0] - a0[0], dy = q[1] - a0[1], L2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((p[0] - a0[0]) * dx + (p[1] - a0[1]) * dy) / L2));
    return Math.hypot(a0[0] + t * dx - p[0], a0[1] + t * dy - p[1]) <= 2.5;
  }));
  // End point E and its inner neighbor F. For a tip, E is the end in the direction of travel; otherwise it is the tail.
  const snapEnd = (E, F, own, outer, tip) => {
    const len = Math.hypot(E[0] - F[0], E[1] - F[1]);
    if (len < 1) return E;
    const u = [(E[0] - F[0]) / len, (E[1] - F[1]) / len];
    const cand = boxes.filter(b => !outer.includes(b));
    const holders = cand.filter(b => inR(b, E, 0.25)).sort((p, q) => area(p) - area(q));
    const P0 = holders[0];
    if (tip) {
      // A head inside box P0 is one of two cases. If the arrow is on its way through a grouping panel to a box inside it (that inner
      // box is close ahead), snap to that box. Otherwise the head only crossed the border slightly, so pull it back to just before the
      // point where it entered.
      const depth = P0 ? (slab(P0, E, [-u[0], -u[1]]) || [0, 0])[1] : 0;
      const reach = P0 ? (depth <= 6 ? 12 : REACH) : REACH;
      const ahead = cand.filter(b => !inR(b, E, 0.25) && (!P0 || inside(b, P0)))
        .map(b => ({ b, h: slab(b, E, u) })).filter(o => o.h && o.h[0] >= 0 && o.h[0] <= reach).sort((p, q) => p.h[0] - q.h[0]);
      if (ahead.length) { const t = ahead[0].h[0] - TIP_GAP; return [E[0] + u[0] * t, E[1] + u[1] * t]; }
      if (P0 && depth <= PULL && depth + TIP_GAP < len - 3) { const t = depth + TIP_GAP; return [E[0] - u[0] * t, E[1] - u[1] * t]; }
      return E;
    }
    // Tail: leave it if it is already on the border of some box (a tail leaving the border of an inner box once got moved by 10 to
    // the border of the enclosing panel, which was wrong). Leave it if it branches off another line. Move it to the border of a box
    // close behind it. When it starts inside a box, move it to just outside that box.
    if (cand.some(b => onBorder(b, E)) || onStroke(E, own)) return E;
    const behind = cand.filter(b => !inR(b, E, 0.25)).map(b => ({ b, h: slab(b, E, u) })).filter(o => o.h && o.h[0] >= 0 && o.h[0] <= PULL).sort((p, q) => p.h[0] - q.h[0]);
    if (behind.length) { const t = behind[0].h[0]; return [E[0] + u[0] * t, E[1] + u[1] * t]; }
    if (P0) {
      const h = slab(P0, E, [-u[0], -u[1]]);
      if (h && h[1] <= PULL && h[1] < len - 3) return [E[0] - u[0] * h[1], E[1] - u[1] * h[1]];
    }
    return E;
  };
  let out = "", at = 0;
  for (const t of toks) {
    if (t.free) continue;
    const pts = t.pts.map(q => q.slice()), n = pts.length;
    const first = pts[0], last = pts[n - 1];
    const outer = boxes.filter(b => inR(b, first, -0.5) && inR(b, last, -0.5));
    const endTip = !!t.a["marker-end"], startTip = !!t.a["marker-start"];
    pts[n - 1] = snapEnd(last, pts[n - 2], t.pts, outer, endTip);
    pts[0] = snapEnd(first, pts[1], t.pts, outer, startTip);
    const r = v => Math.round(v * 10) / 10;
    let rep;
    // An arrow whose shaft is short once the heads are subtracted gets the small head. A normal head in a gap of 10 to 12 between
    // boxes left only the head visible, with no shaft.
    const Lt = pts.reduce((acc, q, k) => k ? acc + Math.hypot(q[0] - pts[k - 1][0], q[1] - pts[k - 1][1]) : 0, 0);
    const swv = parseFloat(t.a["stroke-width"] || "1"), heads = (endTip ? 1 : 0) + (startTip ? 1 : 0);
    // A shaft shorter than 8 counts as short. At 4, arrows in gaps of 12 to 16 had a large head and a stubby shaft and looked cut off.
    const small = Lt - heads * 0.75 * HEAD * swv < 8;
    const mk = s2 => small ? s2.replace(/url\(#(ah-[a-z]+)\)/g, "url(#$1-s)") : s2;
    if (t.tag === "path") rep = mk(t.all.replace(/ d="[^"]*"/, ` d="M${pts.map(q => q.map(r).join(",")).join(" L")}"`));
    else rep = mk(t.all.replace(/ x1="[^"]*"/, ` x1="${r(pts[0][0])}"`).replace(/ y1="[^"]*"/, ` y1="${r(pts[0][1])}"`)
      .replace(/ x2="[^"]*"/, ` x2="${r(pts[1][0])}"`).replace(/ y2="[^"]*"/, ` y2="${r(pts[1][1])}"`));
    out += markup.slice(at, t.i) + rep; at = t.i + t.len;
  }
  return out + markup.slice(at);
}

class Svg {
  constructor(w, h) { this.w = w; this.h = h; this.parts = []; }
  add(...p) { this.parts.push(...p.flat(Infinity).filter(Boolean)); return this; }
  toString() {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${this.w} ${this.h}" width="${this.w}" height="${this.h}" ` +
      `font-family="Pretendard, sans-serif">${DEFS}${snapArrows(this.parts.join(""))}</svg>`;
  }
}

// Icons: lucide (ISC license) line icons inserted as they are. (x, y) is the center and s the side length.
// data-icon is set so that the probe does not mistake the shapes inside an icon for boxes.
const fs = require("fs");
const LUCIDE = path.join(__dirname, "..", "..", "node_modules", "lucide-static", "icons");
const iconCache = {};
function lucide(name) {
  if (!iconCache[name]) {
    const f = path.join(LUCIDE, name + ".svg");
    if (!fs.existsSync(f)) throw new Error("lucide icon not found: " + name);
    iconCache[name] = fs.readFileSync(f, "utf8").replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "").replace(/\s*\n\s*/g, "");
  }
  return iconCache[name];
}
const icon = (name, x, y, s, c = C.navy, o = {}) => `<g data-icon="${name}" transform="translate(${r1(x - s / 2)},${r1(y - s / 2)}) scale(${(s / 24).toFixed(4)})" ` +
  `fill="none" stroke="${c}" stroke-width="${o.sw ?? (s < 15 ? 2.4 : 2.1)}" stroke-linecap="round" stroke-linejoin="round">${lucide(name)}</g>`;
// Old icon names map to lucide names. New figures call icon(name, ...) with the lucide name directly.
const ALIAS = { server: "server", gpu: "gpu", db: "database", user: "user", cloud: "cloud", lock: "lock", gear: "settings", doc: "file-text",
  switch: "network", k8s: "ship-wheel", chart: "chart-line", bell: "bell", term: "square-terminal", model: "box", shield: "shield-check",
  flow: "workflow", dc: "building-2" };
const ICON = new Proxy({}, { get: (_, k) => (x, y, s, c) => icon(ALIAS[k] || k, x, y, s, c) });

// Diagram parts
const D = {
  // Box. o.head: title in a navy band on top. o.title and o.sub: centered text. o.icon: icon on the left.
  box(x, y, w, h, o = {}) {
    const out = [P.rect(x, y, w, h, { fill: o.fill ?? C.white, stroke: o.stroke ?? C.rule, sw: o.sw ?? 1, r: o.r ?? 4, dash: o.dash, valign: o.valign })];
    let top = y;
    if (o.head) {
      const hh = o.headH ?? 22;
      out.push(P.rect(x, y, w, hh, { fill: o.headFill ?? C.navy, r: o.r ?? 4 }), P.rect(x, y + hh - 4, w, 4, { fill: o.headFill ?? C.navy, r: 0 }));
      // The header text starts at the same x + 10 as the lines below it, so their left edges line up.
      // The inner margin of the header text is 10 by default and o.hpad changes it (to line up with the text column of a box above).
      out.push(P.text(x + (o.hpad ?? 10), y + hh / 2, o.head, { size: o.headSize ?? 11.5, bold: true, fill: o.headText ?? C.white, maxw: w - 4 - (o.hpad ?? 10) }));
      if (o.headRight) out.push(P.text(x + w - 8, y + hh / 2, o.headRight, { size: 9.5, fill: C.white, anchor: "end", op: 0.9 }));
      top = y + hh;
    }
    // 4 between the right edge of the icon and the name: with 2, the first stroke of the name looked stuck to the icon stroke by 1 to
    // 2px (the probe flags this).
    // The inner margin of left-aligned text is 10 by default and o.pad changes it (to line up the text start with other lines of the
    // same column).
    const ix = o.icon ? x + 14 + (o.iconS ?? 16) : x + (o.align === "left" ? (o.pad ?? 10) : w / 2);
    if (o.icon) out.push(ICON[o.icon](x + 10 + (o.iconS ?? 16) / 2, top + (y + h - top) / 2, o.iconS ?? 16, o.iconC));
    const anchor = o.icon || o.align === "left" ? "start" : "middle";
    // The figure-to-card number badge (o.mark) sits inside the top right corner of the box (15 from the right, 14 from the top), and
    // its space is subtracted from the title width (on both sides for centered text).
    const avail = (o.icon ? w - (ix - x) - 6 : w - 12) - (o.mark ? (anchor === "middle" ? 48 : 24) : 0);
    const cy = top + (y + h - top) / 2;
    // The number badge (o.mark) is placed at the height of the title line. A fixed 14 from the top put it 2.5 above the title in a
    // two-line box of height 48 (the probe checks the badge against the text line height). Without a title it stays 14 from the top.
    let markY = y + 14;
    if (o.title && o.sub) {
      // Center the ink block of the two lines (15 between their centers) in the box. The fixed offsets (-7, +8) left the block 0.7px
      // low with Korean sub text.
      const ts = fsz(o.size ?? 11), ss = fsz(o.subSize ?? 9.5);
      const top = cy - 7 + CENTRAL * ts + inkV(o.title, ts, o.bold !== false)[0], bot = cy + 8 + CENTRAL * ss + inkV(o.sub, ss)[1];
      const sh = cy - (top + bot) / 2;
      out.push(P.text(ix, cy - 7 + sh, o.title, { size: o.size ?? 11, bold: o.bold !== false, fill: o.color ?? C.navy, anchor, maxw: avail }));
      markY = cy - 7 + sh;
      out.push(P.text(ix, cy + 8 + sh, o.sub, { size: o.subSize ?? 9.5, fill: o.subColor ?? ({ [C.a4]: C.amber, [C.t4]: C.teal, [C.b5]: C.b1 }[o.fill] ?? C.grey), anchor, maxw: avail }));
    } else if (o.title) { out.push(P.text(ix, cy, o.title, { size: o.size ?? 11, bold: o.bold !== false, fill: o.color ?? C.navy, anchor, maxw: avail })); markY = cy; }
    if (o.lines) o.lines.forEach((t, i) => out.push(P.text(x + 10, top + (o.lpad ?? 14) + i * (o.lh ?? 15), t, { size: o.lsize ?? 10, fill: C.body, maxw: w - 18 })));
    if (o.mark) out.push(D.mark(x + w - 15, markY, o.mark));
    return out.join("");
  },
  // Group frame: a pale fill or a dashed outline, with the name at the top left. The default name color is navy: a blue default
  // blurred the meaning of the "my part / changed part" legend.
  // o.mark is the figure-to-card number badge. It sits inside the top right corner of the group (15 from the right, 14 from the top;
  // at 12 it touches the border). With a badge, the group name also moves down to 14 so that it stands at the height of the badge
  // (a name at 12 and a badge at 14 were 2 apart). Content inside starts 26 below the top.
  group(x, y, w, h, label, o = {}) {
    return P.rect(x, y, w, h, { fill: o.fill ?? C.key, stroke: o.stroke ?? C.rule, sw: 1, r: 6, dash: o.dash }) +
      // The inner margin of the name is 10 by default and o.lpad changes it (when the group stands next to a panel and the name must
      // share the column of the panel title).
      // The height of the name is 12 from the top by default (14 with a badge) and o.ly changes it (to put the name on the same line as
      // the name of a neighboring group that has a badge).
      (label ? P.text(x + (o.lpad ?? 10), y + (o.ly ?? (o.mark ? 14 : 12)), label, { size: o.size ?? 10, bold: true, fill: o.color ?? C.navy, ls: 0.6, maxw: w - 2 * (o.lpad ?? 10) - (o.mark ? 24 : 0) }) : "") +
      (o.mark ? D.mark(x + w - 15, y + 14, o.mark) : "");
  },
  // Polyline connector. pts = [[x, y], ...]
  conn(pts, o = {}) {
    const d = "M" + pts.map(p => p.map(r1).join(",")).join(" L");
    // Connectors are navy by default. Blue (color: "blue") is used only where the figure caption gives it a meaning, and grey marks
    // the old path (the "before" side of a before/after figure). Blue and navy arrows mixed without a meaning looked arbitrary.
    const col = o.color === "blue" ? "blue" : o.color === "grey" ? "grey" : "navy";
    return P.path(d, { stroke: { blue: C.blue, grey: C.faint, navy: C.navy }[col], sw: o.sw ?? 1.4, dash: o.dash, arrow: o.noArrow ? undefined : col, free: o.free, through: o.through }) +
      (o.label ? P.text(o.lx ?? (pts[0][0] + pts[pts.length - 1][0]) / 2, o.ly ?? (pts[0][1] + pts[pts.length - 1][1]) / 2 - 8, o.label,
        { size: 9.5, fill: C.grey, anchor: "middle" }) : "");
  },
  // Numbered circle for a step number. The circle and the digit are grouped with data-badge so that the probe can measure the badge
  // position (crossing a border, covering text).
  // No y offset is applied: the old +0.25 correction made up for the rounded central baseline, and now that the baseline is
  // computed directly (P.text) it would push the digit 0.23px low.
  num(x, y, n, o = {}) { return `<g data-badge="num">` + P.circle(x, y, o.r ?? 8, { fill: o.fill ?? C.blue }) + P.text(x, y, String(n), { size: o.size ?? 9.5, bold: true, fill: o.color ?? C.white, anchor: "middle" }) + `</g>`; },
  // Small pill-shaped label. o.w fixes the width (for chips laid out on a grid, where differing text widths put them off by 1px).
  pill(x, y, s, o = {}) {
    const z = fsz(o.size ?? 9.5), w = o.w ?? tw(s, z, true) + 12;
    return P.rect(x, y - 9, w, 18, { fill: o.fill ?? C.band, r: 9, stroke: o.stroke }) + P.text(x + w / 2, y, s, { size: z, bold: true, fill: o.color ?? C.blue, anchor: "middle" });
  },
  pillW: (s, size = 9.5) => tw(s, fsz(size), true) + 12,
  // Figure-to-card number mark. The same number is put on a part of the figure and on the title of its card on the right. A navy
  // fill with a white border keeps it apart from the step number (D.num, blue).
  // On a box it goes at the inner corner (its center 9 inside the corner). Straddling the corner would put the digit against the box
  // border and fail the probe's text-margin check.
  mark(x, y, n) {
    return `<g data-badge="mark">` + P.circle(x, y, 9, { fill: C.navy, stroke: C.white, sw: 2 }) + P.text(x, y, String(n), { size: 10, bold: true, fill: C.white, anchor: "middle" }) + `</g>`;
  },
  // Protocol name label on a connector. (x, y) is the center. Add one only for a protocol that the source facts support.
  proto(x, y, s) {
    const w = tw(s, fsz(10), true) + 12;
    // Navy border and text: blue means "my part / changed part" in the deck, so it is not used for protocol labels.
    return P.rect(x - w / 2, y - 8, w, 16, { fill: C.white, stroke: C.navy, r: 8 }) + P.text(x, y, s, { size: 10, bold: true, fill: C.navy, anchor: "middle" });
  },
};

// Screen wireframe parts: values become bars and only the names stay.
// Deterministic pseudo-random numbers, so that a figure does not change from build to build.
function rng(seed) { let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }

const U = {
  // App window: a navy bar on top (product name), a menu on the left, content on the right. Returns the coordinates of the content
  // area.
  app(x, y, w, h, o = {}) {
    const top = 26, side = o.side ?? 150;
    const out = [P.rect(x, y, w, h, { fill: C.white, stroke: C.rule, r: 6 }),
      P.rect(x, y, w, top, { fill: C.navy, r: 6 }), P.rect(x, y + top - 6, w, 6, { fill: C.navy, r: 0 }),
      P.circle(x + 12, y + top / 2, 3.2, { fill: C.b3 }), P.circle(x + 22, y + top / 2, 3.2, { fill: C.b3 }), P.circle(x + 32, y + top / 2, 3.2, { fill: C.b3 }),
      P.text(x + 46, y + top / 2, o.title ?? "", { size: 11, bold: true, fill: C.white, maxw: 260 })];
    if (o.search !== false) out.push(P.rect(x + w * 0.42, y + 6, w * 0.26, 14, { fill: "#33496A", r: 7 }));
    // The title bar has no pair of dots (navy and blue) at its right end: they matched no screen control and were only decoration.
    if (o.nav) {
      // o.navDeco: the menu background starts 1 inside the frame border, so when the frame is not at the left edge (0) of the figure,
      // the row-and-column alignment check sees a column 1px away from the frame. Only that figure marks the menu background as
      // decoration. Marking it on every screen would compare the menu text lines with the content text lines as one row and report a
      // 1px misalignment elsewhere.
      out.push(P.rect(x + 1, y + top, side, h - top - 1, { fill: C.band, r: 0, deco: o.navDeco }));
      let yy = y + top + 16;
      o.nav.forEach(sec => {
        // The space below a group name keeps the descenders of an English name off the background of the selected item (a smaller gap
        // let them come within 2px).
        if (sec.sec) { out.push(P.text(x + 14, yy, sec.sec, { size: 8.5, fill: C.grey, ls: 0.8, maxw: side - 20 })); yy += 18; }
        (sec.items || []).forEach(it => {
          const act = it === o.active;
          if (act) out.push(P.rect(x + 6, yy - 9, side - 12, 18, { fill: C.white, r: 3 }), P.rect(x + 6, yy - 9, 3, 18, { fill: C.blue, r: 1 }));
          out.push(P.text(x + 18, yy, it, { size: 10, semi: act, fill: act ? C.navy : C.body, maxw: side - 26 }));
          yy += 19;
        });
        yy += 5;
      });
    }
    const cx = x + (o.nav ? side + 14 : 14), cw = w - (o.nav ? side + 28 : 28);
    let cy = y + top + 14;
    if (o.page) { out.push(P.text(cx, cy + 4, o.page, { size: 14, bold: true, fill: C.navy, maxw: cw })); cy += 18;
      if (o.pageSub) { out.push(P.text(cx, cy + 3, o.pageSub, { size: 9.5, fill: C.grey, maxw: cw })); cy += 14; } cy += 6; }
    return { svg: out.join(""), x: cx, y: cy, w: cw, h: y + h - cy - 12 };
  },
  // Value card: a name, a thick bar in place of the big value, a progress bar and a small trend line
  kpi(x, y, w, h, label, o = {}) {
    const R = rng(o.seed ?? label.length * 7);
    const out = [P.rect(x, y, w, h, { fill: C.white, stroke: C.rule, r: 4 }),
      P.text(x + 10, y + 13, label, { size: 9.5, fill: C.grey, maxw: w - 20 }),
      P.rect(x + 10, y + 25, w * (0.32 + R() * 0.12), 13, { fill: o.color ?? C.navy, r: 3 }),
      P.rect(x + 10, y + h - 20, w - 20, 5, { fill: C.band, r: 2.5 }),
      P.rect(x + 10, y + h - 20, (w - 20) * (o.fill ?? (0.35 + R() * 0.55)), 5, { fill: o.color ?? C.blue, r: 2.5 })];
    if (h > 62 && o.spark !== false) {
      const pts = [...Array(9)].map((_, i) => [x + w * 0.55 + i * (w * 0.36 / 8), y + 40 - R() * 10 - i * 0.8]);
      out.push(P.path("M" + pts.map(p => p.map(r1).join(",")).join(" L"), { stroke: o.color ?? C.blue, sw: 1.4 }));
    }
    return out.join("");
  },
  // Empty card with a title (something else is drawn inside it)
  panel(x, y, w, h, title, o = {}) {
    return P.rect(x, y, w, h, { fill: o.fill ?? C.white, stroke: C.rule, r: 4 }) +
      (title ? P.text(x + 10, y + 13, title, { size: 10.5, bold: true, fill: C.navy, maxw: w - 20 - (o.badge ? D.pillW(o.badge, 8.5) + 6 : 0) }) : "") +
      (o.badge ? D.pill(x + w - D.pillW(o.badge, 8.5) - 8, y + 13, o.badge, { size: 8.5 }) : "");
  },
  // Time-series line chart (no tick numbers)
  lines(x, y, w, h, o = {}) {
    const R = rng(o.seed ?? 3), n = o.n ?? 24, series = o.series ?? 2;
    const out = [];
    for (let i = 0; i <= 3; i++) out.push(P.line(x, y + i * h / 3, x + w, y + i * h / 3, { stroke: C.band }));
    const cols = [C.blue, C.navy, C.b2, C.n3];
    for (let s = 0; s < series; s++) {
      let v = 0.3 + R() * 0.4; const pts = [];
      for (let i = 0; i < n; i++) { v = Math.max(0.08, Math.min(0.92, v + (R() - 0.5) * 0.18)); pts.push([x + i * w / (n - 1), y + h - v * h]); }
      if (o.area && s === 0) out.push(P.path("M" + pts.map(p => p.map(r1).join(",")).join(" L") + ` L${x + w},${y + h} L${x},${y + h} Z`, { fill: C.band, stroke: "none" }));
      out.push(P.path("M" + pts.map(p => p.map(r1).join(",")).join(" L"), { stroke: cols[s % 4], sw: 1.6 }));
    }
    return out.join("");
  },
  // Bar chart
  bars(x, y, w, h, o = {}) {
    const R = rng(o.seed ?? 5), n = o.n ?? 8, gap = w / n * 0.35, bw = w / n - gap;
    const out = [P.line(x, y + h, x + w, y + h, { stroke: C.rule })];
    for (let i = 0; i < n; i++) {
      const v = o.values ? o.values[i] : 0.25 + R() * 0.7;
      // The bars in a screen are decoration, so they are left out of the box checks and the row-and-column alignment check.
      out.push(P.rect(x + i * (bw + gap) + gap / 2, y + h - v * h, bw, v * h, { fill: o.colors ? o.colors[i % o.colors.length] : (i === o.hi ? C.blue : C.b3), r: 1.5, deco: true }));
    }
    return out.join("");
  },
  donut(cx, cy, r, parts, o = {}) {
    let a = -Math.PI / 2; const out = []; const cols = o.colors ?? [C.blue, C.navy, C.b3, C.b4];
    parts.forEach((p, i) => {
      const b = a + p * 2 * Math.PI, large = p > 0.5 ? 1 : 0;
      out.push(P.path(`M${r1(cx + r * Math.cos(a))},${r1(cy + r * Math.sin(a))} A${r},${r} 0 ${large} 1 ${r1(cx + r * Math.cos(b))},${r1(cy + r * Math.sin(b))}`,
        { stroke: cols[i % cols.length], sw: o.sw ?? 9 }));
      a = b;
    });
    return out.join("");
  },
  // Table: the names of the header cells stay as in the original and the values become bars. o.cells can give some cells text.
  table(x, y, w, cols, rows, o = {}) {
    const R = rng(o.seed ?? 11), rh = o.rh ?? 19, ws = o.widths ?? cols.map(() => 1), tot = ws.reduce((a, b) => a + b, 0);
    const out = [P.rect(x, y, w, rh, { fill: C.band, r: 2 })];
    let xx = x;
    const xs = ws.map(v => { const s = xx; xx += w * v / tot; return s; });
    cols.forEach((c, i) => out.push(P.text(xs[i] + 6, y + rh / 2, c, { size: 9, bold: true, fill: C.navy, maxw: w * ws[i] / tot - 10 })));
    for (let r = 0; r < rows; r++) {
      const yy = y + rh * (r + 1);
      out.push(P.line(x, yy + rh, x + w, yy + rh, { stroke: C.band }));
      cols.forEach((c, i) => {
        const cw = w * ws[i] / tot - 12;
        const cell = o.cells && o.cells[r] && o.cells[r][i];
        if (cell && cell.pill) out.push(D.pill(xs[i] + 6, yy + rh / 2, cell.pill, { size: 8.5, fill: cell.fill, color: cell.color, stroke: cell.stroke }));
        else if (cell) out.push(P.text(xs[i] + 6, yy + rh / 2, cell, { size: 9, fill: C.body, maxw: cw }));
        else out.push(P.rect(xs[i] + 6, yy + rh / 2 - 3, cw * (0.35 + R() * 0.55), 6, { fill: i === 0 ? C.b3 : C.band, r: 3 }));
      });
    }
    return out.join("");
  },
  // Input form: a name plus a field
  form(x, y, w, fields, o = {}) {
    const lw = o.lw ?? 90, rh = o.rh ?? 24;
    return fields.map((f, i) => {
      const yy = y + i * rh;
      // The name and the value are centered in the field (height rh - 6). The earlier yy + 9 sat 1px below the center of the field.
      const my = yy + (rh - 6) / 2;
      return P.text(x, my, f.label ?? f, { size: 9.5, fill: C.navy, semi: true, maxw: lw - 6 }) +
        (f.req ? P.text(x + tw(f.label, 9.5, true) + 3, my - 2, "*", { size: 9, fill: C.blue }) : "") +
        P.rect(x + lw, yy, w - lw, rh - 6, { fill: C.white, stroke: C.rule, r: 3 }) +
        (f.value ? P.text(x + lw + 7, my, f.value, { size: 9, fill: C.body, maxw: w - lw - 14 }) :
          P.rect(x + lw + 7, my - 3, (w - lw) * 0.4, 6, { fill: C.band, r: 3 }));
    }).join("");
  },
  // Button
  button(x, y, s, o = {}) {
    const w = tw(s, 9.5, true) + 18;
    return P.rect(x, y, w, 18, { fill: o.primary ? C.blue : C.white, stroke: o.primary ? "none" : C.rule, r: 3 }) +
      P.text(x + w / 2, y + 9, s, { size: 9.5, bold: true, fill: o.primary ? C.white : C.navy, anchor: "middle" });
  },
  // Phone frame. Returns the inner coordinates.
  phone(x, y, w, h) {
    return { svg: P.rect(x, y, w, h, { fill: C.navy, r: 16 }) + P.rect(x + 6, y + 18, w - 12, h - 34, { fill: C.white, r: 4 }) +
      P.rect(x + w / 2 - 14, y + 7, 28, 4, { fill: C.n3, r: 2 }) + P.circle(x + w / 2, y + h - 8, 4, { fill: C.n3 }),
      x: x + 6, y: y + 18, w: w - 12, h: h - 34 };
  },
  // Text line bars (stand in for a paragraph)
  lines2(x, y, w, n, o = {}) {
    const R = rng(o.seed ?? 21);
    return [...Array(n)].map((_, i) => P.rect(x, y + i * (o.lh ?? 10), w * (i === n - 1 ? 0.45 + R() * 0.2 : 0.85 + R() * 0.15), o.th ?? 5, { fill: o.fill ?? C.band, r: 2.5 })).join("");
  },
};

// Standalone icon placed in HTML (header chips, card titles, the cover). data-icon keeps the probe from counting it as a figure.
const svgIcon = (name, s, c = C.navy, sw = 2.1) => `<svg data-icon="${name}" viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="${c}" ` +
  `stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round">${lucide(name)}</svg>`;

// Text outline (path data and bounding box). Used for guide text that must stay out of the PDF text layer (the rail on the left).
// As HTML text, the vertical letters were read by pdftotext right next to the period in the header line, which made the layout
// checks report numbers split from their units on every slide.
function outline(str, size, bold) {
  const g = FONTS[weightOf(bold)].getPath(String(str), 0, 0, size);
  return { d: g.toPathData(2), bb: g.getBoundingBox() };
}

module.exports = { C, P, D, U, ICON, icon, svgIcon, lucide, Svg, tw, fsz, rng, esc, MIN_TEXT, outline, snapArrows, inkV, CENTRAL, stackY, glyphTable };
