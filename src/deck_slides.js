// The portfolio (16:9 deck) from one profile file. It draws slides from data with one theme (portfolio/theme.css), slide frame (Deck, h) and drawing parts (portfolio/draw.js).
//   node src/deck_slides.js <profile.json> [job.json]   -> output/<out>_deck.html (resume.py prints it to PDF with chromium)
// Two layouts:
//   default            cover, career overview, one slide per project with a figure, end (the layout the self-test pins)
//   job deck "chapters" the chapter structure: cover with stat tiles and focus columns, contents, career at a glance,
//                      a chapter divider per company, project slides with breadcrumb, tagline, client logo, role, context and
//                      stack line, scale chips, figures and numbered cards, the side rail on every inner slide, end
// Profile fields the deck reads besides the resume's (all optional): summary.stats [[value, note]], summary.focus [[title, text]],
// summary.glance (lede of the career slide), summary.contents (lede of the contents slide), roles[].lead, roles[].clients,
// roles[].stack [[category, items]], projects[].tagline, role, context, stack, chips, lede, cards [[head, text, mark]], figure, figures,
// logo, deck (false keeps a project off the deck), slide (true gives a project a slide without a figure),
// pages [{ lede, figure, figures, cards }] (a project over several slides, titled (1/2), (2/2)), and the top-level chapters
// [{ key, kind: "research", name, enName, title, start, end, place, funder, lead, stack, logo, timeline, projects }] for chapters
// that are not companies (they follow the company chapters). docs/DOCUMENTS.md has the details
const fs = require("fs");                          // files
const path = require("path");                      // paths
const { Deck, h } = require("./portfolio/deck");   // the slide frame and HTML helpers
const G = require("./profile_loader");            // one profile loader for resume, deck and figures
const CH = require("./deck_figures");            // figure templates drawn with the shared drawing parts
const ST = require("./deck_structure");         // chapters, contents, rail and project headers
const BL = require("./blind");                    // the blind edition: its band on the cover (deck.js covers the words)

// Figure text width estimate for the simple templates below (Pretendard 13px): Hangul one em, other characters a little over half
const textW = (s, size) => [...String(s)].reduce((w, c) => w + (/[ㄱ-힣]/.test(c) ? 1 : 0.56) * size, 0);
const esc = h.esc;                                 // HTML and SVG escaping
const CUT = [];                                    // text a figure had to drop (written to <out>_deck.cut.json; the document check reports it)
// The simple templates paint with the theme's CSS variables, so a theme file recolors them too
const svg = (w, ht, body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${ht}" width="${w}" height="${ht}" font-family="Pretendard">${body}</svg>`;
// A rounded box painted through style, so a CSS variable can be its fill
const rect = (x, y, w, ht, fill, r = 6, extra = "") => `<rect x="${x}" y="${y}" width="${w}" height="${ht}" rx="${r}" style="fill:${fill}" ${extra}/>`;
// A text line centered on y; its color is a CSS variable too
const text = (x, y, s, o = {}) => `<text x="${x}" y="${y}" font-size="${o.size || 13}" ${o.bold ? 'font-weight="700"' : ""} text-anchor="${o.anchor || "start"}" ` +
  `dominant-baseline="middle" style="fill:${o.fill || "var(--ink)"}">${esc(s)}</text>`;   // escaped, since figure text comes from the profile

// Wrap text to a width (figure box text)
function wrap(s, width, size) {
  const words = String(s).split(/\s+/), lines = [];  // the words, and the lines being built
  let cur = "";                                      // the line being filled
  for (const w of words) {                           // greedy filling, word by word
    const next = cur ? cur + " " + w : w;            // the line with this word added
    if (textW(next, size) > width && cur) { lines.push(cur); cur = w; } else cur = next;   // too wide: close the line; a lone long word stays whole
  }
  if (cur) lines.push(cur);                          // the last line
  return lines;                                      // empty for blank text
}

// Career timeline of the default cover: a tick per year, one bar per role (newest on top), study bars below in a light shade
function timeline(roles, edu, W = 1200) {
  const ym = G.ym;                                 // year-month reader shared with the loader
  const now = new Date().getFullYear() + new Date().getMonth() / 12;   // today as a fractional year, where ongoing roles end
  // end null is ongoing (to today); an empty or missing end is unknown (a short bar in the start year), as on the resume
  const endOf = (s, e) => e === null ? now : (e ? ym(e) : Math.min(now, ym(s) + 1));
  // Roles as navy bars with white text
  const items = [...roles.filter(r => r.start).map(r => ({ a: ym(r.start), b: endOf(r.start, r.end), name: r.org, sub: r.title || "", fill: "var(--navy)", on: "#fff" })),
                 // Schools in the light shade with navy text, unless kept off the timeline
                 ...edu.filter(e => e.start && e.timeline !== false).map(e => ({ a: ym(e.start), b: endOf(e.start, e.end), name: e.school, sub: e.degree || "", fill: "var(--b4)", on: "var(--navy)" }))]
    .filter(it => Number.isFinite(it.a) && Number.isFinite(it.b));   // an unreadable date drops the bar instead of drawing NaN
  if (!items.length) return "";                      // no dated roles or schools: no timeline
  const y0 = Math.floor(Math.min(...items.map(i => i.a))), y1 = Math.ceil(Math.max(...items.map(i => i.b)));   // whole years around every bar
  const L = 20, R = W - 20, X = t => L + (R - L) * (t - y0) / Math.max(1, y1 - y0);   // year to x, with 20 px margins
  // Height stays under MAXH, so the path cannot push the cover into the footer; text never goes under 10px
  const MAXH = 170, top = 26, rowH = Math.max(18, Math.min(34, (MAXH - top - 6) / items.length - 6)), Ht = top + items.length * (rowH + 6) + 6;
  if (Ht > MAXH && items.some(i => i.on === "var(--navy)")) return timeline(roles, [], W);   // too many rows for the cover: roles only
  const fs_ = Math.max(10, Math.min(13, rowH * 0.55));   // label size follows the row, 10 to 13 px
  let out = "";                                      // the SVG body
  // A gridline and a label for every year
  for (let y = y0; y <= y1; y++) out += `<line x1="${X(y)}" y1="${top - 6}" x2="${X(y)}" y2="${Ht}" style="stroke:var(--line)"/>` + text(X(y), 10, y, { size: 11, anchor: "middle", fill: "var(--grey)" });
  items.forEach((it, i) => {                         // one bar per role or school, in list order
    const y = top + i * (rowH + 6), x = X(it.a), w = Math.max(6, X(it.b) - x);   // row top, bar start and width (at least 6 px)
    out += rect(x, y, w, rowH, it.fill, 5);          // the bar
    const label = it.name + (it.sub ? "  " + it.sub : "");   // name and title, two spaces apart
    // Inside the bar when it fits, else right of it (left when the right edge is too close)
    if (textW(label, fs_) + 16 < w) out += text(x + 8, y + rowH / 2, label, { bold: true, fill: it.on, size: fs_ });
    else if (x + w + 8 + textW(label, fs_) < W) out += text(x + w + 8, y + rowH / 2, label, { bold: true, fill: "var(--navy)", size: fs_ });   // right of the bar, in navy on the page
    else out += text(x - 8, y + rowH / 2, label, { bold: true, fill: "var(--navy)", anchor: "end", size: fs_ });   // left of the bar, ending 8 px before it
  });
  return svg(W, Ht, out);                            // sized to its rows
}

// Figure frame size of the split layouts: figures are drawn at this ratio to fill their frame
const FW = 700, FH = 440;

// Vertical flow: step boxes joined by arrows, stacked to fill the frame
function flow(steps, W = FW, Ht = FH) {
  const n = steps.length, gap = 24, boxH = (Ht - gap * (n - 1)) / n;   // boxes share the height, 24 px apart for the arrows
  // The arrowhead in the theme's blue
  let out = `<defs><marker id="ar" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" style="fill:var(--blue)"/></marker></defs>`;
  steps.forEach((s, i) => {                          // one box per step, top to bottom
    const y = i * (boxH + gap), [head, body] = Array.isArray(s) ? s : [s, ""], last = i === n - 1;   // box top, the step's name and note, and whether it is the last
    out += rect(0, y, W, boxH, last ? "var(--navy)" : "var(--band)", 8);   // the last step, the outcome, is dark
    // The number cell at the left
    out += rect(0, y, 40, boxH, last ? "var(--deep)" : "var(--b4)", 8) + text(20, y + boxH / 2, i + 1, { bold: true, size: 15, anchor: "middle", fill: last ? "#fff" : "var(--navy)" });
    // Text size follows the box height; it shrinks to 10 at least, then the note's extra lines are cut (and reported)
    let hs = Math.min(15, boxH * 0.3), bs = Math.min(13, boxH * 0.26), lines = [];
    for (; ; hs *= 0.92, bs *= 0.92) {               // both sizes shrink by 8% a round
      lines = body ? wrap(body, W - 80, bs) : [];    // the note's lines at this size
      if (hs + 6 + lines.length * bs * 1.35 <= boxH - 8 || bs <= 10) break;   // it fits, or the size reached its floor
    }
    const room = Math.max(0, Math.floor((boxH - 8 - hs - 6) / (bs * 1.35)));   // the note lines the box still holds
    // The rest is cut, and the cut list says so
    if (lines.length > room) { CUT.push(`flow step '${head}': ${lines.length - room} line(s) of its note did not fit. Use fewer steps or a shorter note`); lines = lines.slice(0, room); }
    const block = hs + (lines.length ? 6 + lines.length * bs * 1.35 : 0), y0 = y + (boxH - block) / 2 + hs / 2;   // the text block's height, and the first line's y that centers it
    const hfit = Math.min(hs, (W - 80) / Math.max(1, textW(head, 1)));   // a step name longer than the box (English) shrinks
    out += text(56, y0, head, { bold: true, size: hfit, fill: last ? "#fff" : "var(--navy)" });   // the step name right of the number
    lines.forEach((ln, k) => { out += text(56, y0 + hs / 2 + 6 + bs * 0.7 + k * bs * 1.35, ln, { size: bs, fill: last ? "#fff" : "var(--ink)" }); });   // the note lines under it
    // The arrowhead (refX=10) touches the next box's top edge (the deck check's 'arrow does not reach')
    if (!last) out += `<line x1="${W / 2}" y1="${y + boxH}" x2="${W / 2}" y2="${y + boxH + gap}" style="stroke:var(--blue)" stroke-width="2" marker-end="url(#ar)"/>`;
  });
  return svg(W, Ht, out);                            // fills the frame
}

// Before and after bars: per metric a light bar (before) and a dark one (after) with values; bar thickness fills the frame
function compare(fig, W = FW, Ht = FH) {
  const rows = fig.rows, unit = fig.unit || "", max = Math.max(...rows.flatMap(r => [r[1], r[2]])) || 1;   // rows, unit and the largest value, the bar scale
  const lab = Math.min(W * 0.35, Math.max(...rows.map(r => textW(r[0], 15))) + 18), barW = W - lab - 80;   // names take 35% at most
  const labSize = n => Math.min(15, (lab - 18) / Math.max(1, textW(n, 1)));   // a name too long for the column shrinks
  const rowH = (Ht - 40) / rows.length, bar = Math.min(44, rowH * 0.32);   // rows under the legend; two bars and a gap per row
  let out = rect(lab, 2, 14, 14, "var(--b3)", 3) + text(lab + 20, 9, fig.beforeLabel || "Before", { size: 13, fill: "var(--grey)" }) +   // the legend: the before swatch and word
            rect(lab + 110, 2, 14, 14, "var(--navy)", 3) + text(lab + 130, 9, fig.afterLabel || "After", { size: 13, fill: "var(--grey)" });   // then the after swatch and word
  out += `<line x1="${lab}" y1="30" x2="${lab}" y2="${Ht}" style="stroke:var(--line)"/>`;   // the baseline the bars start from
  rows.forEach(([name, a, b], i) => {                // a pair of bars per metric
    const y = 40 + i * rowH + (rowH - (bar * 2 + 8)) / 2;   // the pair centered in its row
    out += text(0, y + bar + 4, name, { bold: true, size: labSize(name), fill: "var(--navy)" });   // the metric name, level with the gap between the bars
    // The before bar in the light shade, its value muted
    out += rect(lab, y, barW * a / max, bar, "var(--b3)", 4) + text(lab + barW * a / max + 8, y + bar / 2, a + unit, { size: 14, fill: "var(--grey)" });
    // The after bar in navy, its value bold
    out += rect(lab, y + bar + 8, barW * b / max, bar, "var(--navy)", 4) + text(lab + barW * b / max + 8, y + bar * 1.5 + 8, b + unit, { size: 14, bold: true, fill: "var(--navy)" });
  });
  return svg(W, Ht, out);                            // fills the frame
}

// Layer bands top to bottom: a dark name cell on the left, the content on the right; the layers fill the frame
function layers(rows, W = FW, Ht = FH) {
  const gap = 10, rowH = (Ht - gap * (rows.length - 1)) / rows.length, lw = 190;   // layers share the height; the name cell is 190 px wide
  let out = "";                                      // the SVG body
  rows.forEach(([name, body], i) => {                // one band per layer, top to bottom
    // Lighter toward the bottom; white text only on the three darkest shades (white on the fourth fell under contrast 3)
    const dark = i < 3, shade = ["var(--deep)", "var(--navy)", "var(--blue)"][i] || "var(--b4)", y = i * (rowH + gap);
    const fsz = Math.min(15, rowH * 0.36);           // the name size follows the band height
    const fitN = Math.min(fsz, (lw - 28) / Math.max(1, textW(name, 1)));   // long (English) names shrink, then wrap to two lines at 10px
    const nameLines = fitN >= 10 ? [name] : wrap(name, lw - 28, 10).slice(0, 2);   // one line when it fits at 10 px or more, else two at 10
    const nsz = fitN >= 10 ? fitN : 10;              // the size those lines are drawn at
    out += rect(0, y, lw, rowH, shade, 8);           // the name cell
    // The name lines centered in the cell
    nameLines.forEach((ln, k) => { out += text(16, y + rowH / 2 + (k - (nameLines.length - 1) / 2) * nsz * 1.25, ln, { bold: true, size: nsz, fill: dark ? "#fff" : "var(--navy)" }); });
    out += rect(lw + 8, y, W - lw - 8, rowH, "var(--band)", 8);   // the content band beside it
    const bsz = Math.min(14, rowH * 0.3), room = Math.max(1, Math.floor((rowH - 6) / (bsz * 1.35)));   // the body size, and how many lines the band holds
    const all = wrap(body || "", W - lw - 40, bsz), lines = all.slice(0, Math.min(3, room));   // three lines at most
    if (all.length > lines.length) CUT.push(`layers '${name}': ${all.length - lines.length} line(s) did not fit. Use fewer layers or shorter text`);   // the lines that did not fit are reported
    lines.forEach((ln, k) => { out += text(lw + 24, y + rowH / 2 + (k - (lines.length - 1) / 2) * bsz * 1.35, ln, { size: bsz }); });   // the content lines centered in the band
  });
  return svg(W, Ht, out);                            // fills the frame
}

// Figure types: the three simple templates and the library (deck_figures.js)
// The library's templates get the edition's language (legend words, defaults) and the project's name for cut notes
let FIG_LANG = "ko";                                 // set by build() for the edition being drawn
// The simple templates by name; each takes the figure and a canvas size
const FIG = { flow: (f, w, ht) => flow(f.steps, w, ht), compare: (f, w, ht) => compare(f, w, ht), layers: (f, w, ht) => layers(f.rows, w, ht),
  // Every library template, with the edition, the cut list and the figure's name for notes
  ...Object.fromEntries(Object.entries(CH.TEMPLATES).map(([k, fn]) => [k, (f, w = FW, ht = FH, where) => fn(f, w, ht, CUT, { lang: FIG_LANG, where: where || k })])) };
const SIMPLE = new Set(["flow", "compare", "layers"]); // the simple templates fill their canvas (no natural height)

// The chapter layout's canvases. The main figure sits in the 674 px column of split-64 (a 662 x 497 frame), so it is drawn at 760 x 570
// (scale 0.87: the smallest figure text, 10, shows at 8.7 px). The side figure fills the right column's width (470) at the height the
// cards leave. A figure-only slide (split-46) draws at 700 x 488
const MAIN = [760, 570], SIDE_W = 470, WIDE = [700, 488];

// The natural height of a figure at a width (the library trims a drawing to what it needs); the simple templates fill whatever they get
function naturalH(f, w, cap = 1400) {
  if (SIMPLE.has(f.type)) return cap;                   // the simple ones have no natural height
  const svg = CH.render(f, w, cap, [], { lang: FIG_LANG });   // drawn once into a tall canvas, its notes discarded
  return +(svg.match(/viewBox="0 0 [\d.]+ ([\d.]+)"/) || [0, cap])[1];   // the height it trimmed itself to
}

// The bold head of a caption ('**Deploy path** from a change to production' -> 'Deploy path'), or the caption without markup
const boldOf = c => { const m = String(c || "").match(/\*\*(.+?)\*\*/); return (m ? m[1] : String(c || "").replace(/\*\*|==/g, "")).trim(); };

// The simple templates as library templates, so they can sit in a panel: compare is a metric, flow a pipeline. layers has no twin
const toLib = f => f.type === "compare" ? { ...f, type: "metric", rows: f.rows } : f.type === "flow" ? { ...f, type: "pipeline", steps: f.steps } : f;

// Several figures as one main figure: panels titled by their captions, with the marks they carry. Two stack ('2v'), three take one wide
// panel over two ('1+2'), four make a grid. A figure with no library twin is left out and reported, never dropped silently
function autoPanels(list) {
  const parts = [];                                  // the panels, in the figures' order
  for (const f0 of list) {                           // each figure
    if (f0.type === "panels") { parts.push(...(f0.panels || [])); continue; }   // a composite gives its own panels: panels never nest
    const f = toLib(f0);                             // its library form
    if (!CH.DRAW[f.type]) { CUT.push(`figure '${boldOf(f.caption) || f.type}' did not fit on its slide (no panel form)`); continue; }   // a figure with none is reported and left out
    parts.push({ title: boldOf(f.caption), mark: f.mark, note: f.note, figure: f });   // titled by its caption, with its mark and note
  }
  parts.slice(4).forEach(p => CUT.push(`figure '${p.title || (p.figure || {}).type}' did not fit on its slide (four panels at most)`));   // what does not fit is said, never dropped silently
  const ok = parts.slice(0, 4);                      // four panels at most
  return { type: "panels", caption: list[0].caption, layout: ok.length <= 2 ? "2v" : ok.length === 3 ? "1+2" : "2x2", panels: ok };   // the layout from the count, as described above
}

const LEFT = [];                                    // figures that found no place on their slide (written to <out>_deck.left.json, printed)

// The canvas height a side figure may take on a project page with cards: the body under the lede (528 px under a one-line lede,
// measured on rendered slides; less for every further lede line) minus the cards, the gaps, the frame's padding and caption
function sideRoom(cards, ledeText, lang) {
  const { tw } = require("./portfolio/draw");        // the deck's measured text width
  // Lede lines at the slide width (1195 px) in the edition's lede size
  const ledeLines = ledeText ? Math.ceil(tw(String(ledeText).replace(/==|\*\*/g, ""), lang === "en" ? 13 : 14, false) / 1195) : 0;
  const bodyH = 528 - Math.max(0, ledeLines - 1) * (lang === "en" ? 19.5 : 21.7) + (ledeText ? 0 : 31);   // a one-line lede leaves 528 px; each extra line takes a line, no lede gives 31 back
  const cardsH = cards.reduce((a, c) => a + cardH(c, lang), 0) + 10 * (cards.length - 1);   // the cards and the 10 px gaps between them
  return (bodyH - cardsH - 10 - 12 - 22 - 14) / 0.985;   // the CSS height left after gaps, padding and caption, divided into canvas units
}

// Estimated heights in the right column (CSS px), from the theme's card sizes: a card is its top rule and padding, the head lines and
// the body lines (Korean 15 px heads and 14 px body at 1.6, English 14 px and 13 px at 1.55). The width is the column's (about 470 px)
function cardH(c, lang) {
  const [hz, hl, bz, bl] = lang === "en" ? [14, 18.9, 13, 20.15] : [15, 20.25, 14, 22.4];   // head size and line height, body size and line height, per edition
  const { tw } = require("./portfolio/draw");        // the deck's measured text width
  const lines = (t, z, bold, w) => CH.wrap(String(t || "").replace(/==|\*\*/g, ""), z, w, bold).length || 1;   // the lines a text takes at a size and width (an empty text still takes one)
  // A list body: each item's lines plus a little spacing; else one paragraph
  const body = Array.isArray(c.b) ? c.b.reduce((a, x) => a + lines(x, bz, false, 456) + 0.1, 0) : lines(c.b, bz, false, 468);
  return 9 + lines(c.t, hz, true, c.no ? 443 : 468) * hl + 4 + body * bl;   // rule and padding, head lines (narrower beside a badge), gap, body lines
}
// The lede of a slide. A deck check holds p.lede to one line, but a person's text, English most of all, often runs to two, so the
// deck draws the same look as a div that check does not hold to one line
const lede = t => `<div class="lede">${h.rich(t)}</div>`;

// Figure data checks: empty lists, non-numbers, negatives and blanks broke figures (-Infinity coordinates, 'undefined' text)
function checkFigure(f, where) {
  if (CH.TEMPLATES[f.type]) return CH.check(f, where);   // library figures use the library's checks
  const list = f.type === "flow" ? f.steps : f.rows;   // the simple templates' one list
  if (!Array.isArray(list) || !list.length) throw new Error(`${where}: ${f.type === "flow" ? "steps" : "rows"} is empty`);   // an empty list drew -Infinity coordinates
  if (list.length > 8) throw new Error(`${where}: eight items at most (${list.length})`);   // more do not fit the frame
  for (const r of list) {                            // every item
    if (f.type === "flow" && !(typeof r === "string" ? r : Array.isArray(r) && r[0])) throw new Error(`${where}: a step has no name`);   // a step needs a name, as a string or the first element
    if (f.type === "layers" && !(Array.isArray(r) && r[0])) throw new Error(`${where}: a layer has no name`);   // a layer needs a name
    if (f.type === "compare" && !(Array.isArray(r) && r[0] && [r[1], r[2]].every(v => typeof v === "number" && v >= 0 && isFinite(v))))   // compare rows: a name and two numbers of zero or more
      throw new Error(`${where}: compare rows are [name, before, after] with values of zero or more`);   // names the row shape
  }
}

// The three cards under the default cover: [title, text]
function coverCards(S, roles) {
  const hl = S.highlights || [];                     // the summary's highlights come first
  if (hl.length) return hl.slice(0, 3).map(c => {    // three cards at most
    const rows = c.rows || [], last = rows[rows.length - 1] || ["", ""];   // the last row is the result
    return [c.title, [c.where, last[1]].filter(Boolean).join(". ")];   // the card text: where, then the result
  });
  // No highlights: the first project of each of the first three roles
  return roles.slice(0, 3).filter(r => (r.projects || []).length).map(r => [r.projects[0].title, r.org + ". " + (r.projects[0].summary || "")]);
}

// A cover headline takes one line: a long one is set smaller, so the path and the columns under it keep their room (1184 px of text, the theme's 25 px, 23 px in English)
function headFit(text, lang) {
  const { tw } = require("./portfolio/draw");        // the deck's measured text width
  const size = lang === "en" ? 23 : 25, wide = tw(text.replace(/==|\*\*|\n/g, " "), size, true);   // its width at the theme's size
  return wide > 1170 ? ` style="font-size:${Math.max(17, Math.floor(size * 1170 / wide * 2) / 2)}px"` : "";   // to half a pixel, and never under 17 px
}

function build(profilePath, cfg = {}) {              // one deck from a profile and its job settings
  const lang = cfg.lang || "ko";                     // the edition; Korean when the job does not say
  const prof = G.load(profilePath, lang, cfg);     // normalized profile for this language
  FIG_LANG = lang;                                   // the figures speak the edition's language
  const P = prof.person, S = prof.summary || {};     // the person and the summary block
  // The deck's fixed words in English
  const L = lang === "en" ? { ov: "Career at a glance", sk: "Skills", ph: "Phone", em: "Email", end: "END OF DOCUMENT", did: "What I did", contents: "Contents", more: "more in the resume" }
                          : { ov: "경력 한눈에", sk: "보유기술", ph: "연락처", em: "이메일", end: "END OF DOCUMENT", did: "한 일", contents: "목차", more: "개는 이력서에" };   // and in Korean
  // Names: the English edition puts the English name first, the Korean edition the Korean name
  const [N1, N2] = lang === "en" && P.name_en ? [P.name_en, P.name] : [P.name, P.name_en || ""];
  const deck = new Deck({ title: P.name + " Portfolio", footer: N1 + "  " + (lang === "en" ? "Portfolio" : "포트폴리오"),   // the browser tab title and the footer line
    theme: cfg.theme, lang, look: cfg.deckStyle,     // a theme file can recolor the deck, and the light deck changes its dark panels
    // The browser balances line ends, so a person's text leaves no one-word last lines.
    // A card head that wraps keeps its number badge on the first line (centered on the whole head it sat 9 px low, the probe's badge check)
    css: "p, li, .lede, .card p { text-wrap: pretty; } .card h3 { align-items: flex-start; } .card h3 .mk { margin-top: 1px; }" });
  const eyebrow = (html, label) => html.replace("<!--EYEBROW-->", `<div class="eyebrow"><span>${esc(label)}</span></div>`);   // fills the eyebrow slot h.sec leaves in a title
  const order = cfg.projectOrder || [];             // the job's project order (the resume uses the same)
  const ordered = ps => [...(ps || [])].map((p, i) => [p, i]).sort((x, y) => {   // projects in the job's order, the rest after them in their own order
    const a = order.indexOf(x[0].id), b = order.indexOf(y[0].id);   // where each sits in the job's order
    return (a < 0 ? 1e9 : a) - (b < 0 ? 1e9 : b) || x[1] - y[1];   // unlisted projects last; ties keep the profile's order
  }).map(x => x[0]);                                 // the projects without their indexes
  const roles = prof.roles;                         // newest first
  const out = cfg.out || path.basename(profilePath, ".json");   // the output name, the profile's file name by default
  const figDir = path.join(__dirname, "..", "output", "_figures");   // the resume build draws timelines and logo tiles here
  // A figure file of this deck and edition, or null when the resume build did not draw it
  const figFile = name => { const f = path.join(figDir, `${out}_${name}${lang === "en" ? "_en" : ""}.png`); return fs.existsSync(f) ? f : null; };
  const tile = id => { const f = path.join(figDir, `${out}_logo_${id}.png`); return id && fs.existsSync(f) ? f : null; };   // a logo tile drawn for an id, or null
  const contacts = [[L.ph, P.phone], [L.em, P.email, "mailto:" + P.email], ...(P.links || [])].filter(c => c[1]);   // phone, email (as a mail link) and the profile's links, only those given
  const chapters = cfg.deck === "chapters" || !!(cfg.deck && cfg.deck.chapters);   // the job asks for the chapter layout
  // A figure with the edition's default words (the compare legend reads 전 and 후 in Korean, Before and After in English)
  // size: [width, height] of the drawing. A second figure sits in the narrow right column, so it is drawn on a smaller canvas
  // (drawn at the full frame size and scaled down, its text fell to 7 px)
  const figureHtml = (f0, where, o = {}, size = [FW, FH]) => {
    // A compare figure gets the edition's before and after words unless it names them
    const f = f0.type === "compare" ? { beforeLabel: lang === "en" ? "Before" : "전", afterLabel: lang === "en" ? "After" : "후", ...f0 } : f0;
    checkFigure(f, where);                           // bad data stops the build with the project named
    return h.fig(FIG[f.type](f, size[0], size[1], where), { cap: f.caption || "", ...o });   // drawn at the given size inside the deck's figure frame, with its caption
  };

  // Cover: name panel (stat tiles under the tagline in the chapter layout), contacts, headline, intro, timeline, and cards or focus columns
  const stats = chapters ? (S.stats || []).slice(0, 4) : [];
  // The stat tiles: a bold value over its note
  const proof = stats.length ? `<div class="proof"${stats.length < 4 ? ` style="grid-template-columns: repeat(${stats.length}, minmax(0, 1fr))"` : ""}>${stats.map(([v, n]) => `<span><b>${esc(v)}</b><i>${esc(n || "")}</i></span>`).join("")}</div>` : "";   // three tiles share the row too
  // The cover's middle: the career path strip when roles carry journey lines (chapter layout), else the flat deck timeline the
  // resume build drew, else the simple timeline drawn here
  const yearsOf = r => { const a = String(r.start || "").slice(0, 4), b = r.end === null ? "" : String(r.end || "").slice(0, 4); return b && b !== a ? `${a}${lang === "en" ? " - " : " ~ "}${b}` : a; };   // the edition's range mark
  // The career path strip, oldest role first, when any role has a journey line
  const path_ = chapters && roles.some(r => r.journey) ? ST.journey([...roles].reverse().filter(r => r.journey || (r.projects || []).some(p => p.deck !== false)).map(r => ({ phase: (r.journey || {}).phase, years: yearsOf(r),   // a short job with no slide has no station either
    name: r.short || r.org, logo: tile(r.logoId), title: r.titleLong || r.title, line: (r.journey || {}).line, key: (r.journey || {}).key }))) : "";   // each role's name, logo, title and line
  const tlPng = chapters && !path_ ? figFile("timeline_deck") : null;   // else the resume build's flat timeline image
  const tlSvg = path_ || tlPng ? "" : timeline(roles, prof.education || []);   // else the simple timeline drawn here
  const focus = chapters && (S.focus || []).length >= 3 ? S.focus.slice(0, 4) : coverCards(S, roles);   // three or four focus columns in the chapter layout, else the three cover cards
  // A blind edition's mark on the cover: the dark red band across the top (deck.js styles .blindbar), the resume's page-1 band in
  // the deck, with the table's two words in the deck's language
  const band = BL.on ? (([l, n]) => `<div class="blindbar"><b>${esc(l)}</b><i></i><span>${esc(n)}</span></div>`)(BL.T.banner[lang === "en" ? "en" : "ko"]) : "";
  deck.add({ cls: "cover", kind: "front" },          // the cover slide
    // The name panel: the edition's name first, the other small under it
    `<div class="top"><div class="name"><div class="kind">PORTFOLIO</div><h1>${esc(N1)}${N2 ? `<small>${esc(N2)}</small>` : ""}</h1>` +
    `<div class="tag">${esc(P.tagline || "")}</div>${proof}</div>` +   // the tagline and the stat tiles
    // The contacts, mail and web links clickable in the PDF; then the blind edition's band, over both panels
    `<div class="contact">${contacts.map(([k, v, l]) => `<div><b>${esc(k)}</b>${l ? `<a href="${esc(l)}">${esc(v)}</a>` : `<span>${esc(v)}</span>`}</div>`).join("")}</div>${band}</div>` +
    // The deck may carry its own headline (summary.deckHeadline); else the resume's, on one line
    `<div class="rest">${S.deckHeadline || S.headline ? `<p class="headline"${headFit(String(S.deckHeadline || S.headline), lang)}>${h.rich(String(S.deckHeadline || S.headline).replace(/\n/g, " "))}</p>` : ""}` +
    (S.intro && typeof S.intro === "string" ? lede(S.intro) : "") +   // the intro as a lede, when it is plain text
    // The path strip, the timeline image, or the drawn timeline
    (path_ || (tlPng ? `<figure class="fig natural"><div class="frame bare"><img src="file://${esc(tlPng)}" alt="" style="width:100%"></div></figure>` : tlSvg ? h.fig(tlSvg, { bare: true, natural: true }) : "")) +
    // Narrow cover cards drop the yellow highlight (it broke across two lines); the project slides keep it
    h.grid(focus.length === 4 ? "cols-4" : "cols-3", "flex:none", ...focus.map(([t, b]) =>
      `<div class="card dom"><div><h3><span>${h.rich(t)}</span></h3><p>${h.rich(String(b).replace(/==/g, ""))}</p></div></div>`)) + `</div>`);   // card heads and texts, highlight marks removed; h3 is a flex box, so the span keeps a hyphenated word in its line

  if (!chapters) {                                   // the default layout
    // Default layout. Second slide: per company its projects (every project appears here, slide or not), and the skills table.
    // A long list is cut with a count of the rest (a company with many projects overflowed the slide)
    const sk = prof.skills || [], focusS = cfg.skillsFocus || [];
    // The job's focus categories first, then the rest in profile order
    const skillRows = [...focusS.map(f => sk.find(x => x.category === f)).filter(Boolean), ...sk.filter(x => !focusS.includes(x.category))];
    // A line budget for the company cards: at most six projects per company, fewer until heads, projects and 'more' lines fit
    // eighteen lines (more would overflow the slide)
    const listed = r => ordered(r.projects).filter(p => p.deck !== false && p.resume !== false);   // what the slide says is on the resume
    let cap = 6;                                     // projects shown per company
    // How a project is said on the card: its whole summary, its first sentence, or its title alone. Long summaries overflowed the cards
    let said = p => String(p.summary || "").replace(/==/g, "");
    const firstOf = p => (String(p.summary || "").replace(/==/g, "").match(/^.*?[.!?](?=\s|$)/) || [String(p.summary || "").replace(/==/g, "")])[0];
    const cols = lang === "en" ? 96 : 62;            // characters a line of the left column holds, by the edition's script
    const height = (p, c) => Math.max(1, Math.ceil((String(p.title).length + c(p).length + 2) / cols));   // lines one project takes
    const lines = c => roles.reduce((a, r) => a + 1 + listed(r).slice(0, c).reduce((b, p) => b + height(p, said), 0) + (listed(r).length > c ? 1 : 0), 0);   // lines the cards take at a cap: a head, the projects, a 'more' line
    while (cap > 1 && lines(cap) > 18) cap--;        // lower the cap until eighteen lines fit
    if (lines(cap) > 18) said = firstOf;             // still too long: the first sentence of each
    if (lines(cap) > 18) said = () => "";            // still too long: the titles alone
    const items = r => {                             // the lines of one company's card
      const ps = listed(r);                          // its deck projects in the job's order
      const shown = ps.slice(0, cap).map(p => `**${p.title}** ${said(p)}`.trim());   // each a bold title and what fits of its summary, highlight marks removed
      return ps.length > cap ? [...shown, lang === "en" ? `+${ps.length - cap} ${L.more}` : `그 밖의 ${ps.length - cap}${L.more}`] : shown;   // a count of the rest in the edition's words
    };
    // The skills table keeps its first nine categories (the JD's focus first) with at most eight names each; the resume has them all
    const skillShown = skillRows.slice(0, 9).map(x => [x.category, x.items.slice(0, 8).join(", ") + (x.items.length > 8 ? ", …" : "")]);
    deck.add({ part: L.ov },                         // the overview slide
      eyebrow(h.sec(L.ov, "OVERVIEW"), "OVERVIEW"),  // its title and eyebrow
      h.grid("split-64", "",                         // company cards on the left, skills on the right
        `<div class="stack" style="justify-content:flex-start">${roles.map(r => h.card(`${r.org}  ${r.period}`, items(r))).join("")}</div>`,   // a card per company with its period
        sk.length ? `<div class="stack"><div class="card"><h3><span>${esc(L.sk)}</span></h3>` +   // the skills table, when the profile has skills
          h.table([lang === "en" ? "Category" : "분류", lang === "en" ? "Skills" : "기술"], skillShown, { key: true }) + `</div></div>` : ""));   // category and skills columns with the edition's heads
    // Project slides: one per project with a figure (bullets on the left, the figure on the right)
    for (const r of roles) {                         // one band of company facts per company
      const band = `<div class="band"><span class="name">${esc(r.org)}</span><span class="title">${esc(r.title || "")}</span>` +   // the company's name, title, place and period
        `<span class="place">${esc(r.place || "")}</span><span class="period">${esc(r.period)}</span></div>`;   // the band's second half
      for (const p of ordered(r.projects).filter(p => p.figure && FIG[p.figure.type] && p.deck !== false))   // projects with a figure
        deck.add({ company: r.org, part: r.org, kind: "project", project: p.id || null },   // a project slide counted for its company; its project for a talk that shows it
          eyebrow(h.sec(p.title + (p.period ? "  " + p.period : ""), "PROJECT"), r.org), band,   // the project title with its period, the company as eyebrow, the band
          p.summary ? lede(p.summary) : "",          // the summary as the lede
          h.grid("split-46", "", h.card(L.did, p.points && p.points.length ? p.points : [p.summary || ""]),   // what was done on the left: the points, else the summary
            figureHtml(p.figure, `project '${p.title}' figure`)));   // the figure on the right, named for its error messages
    }
  } else {
    // Chapter layout. Plan the slides first so contents, chapter lists and the rail know every page number
    const W = ST.WORDS[lang];                        // the structure's words in this language
    const dash = lang === "en" ? "-" : "~";          // the edition's range mark (page ranges of a spread)
    // A project's pages: pages[] when it runs over several slides, else the project itself
    const pagesOf = p => (Array.isArray(p.pages) && p.pages.length ? p.pages : [p]);
    const onDeck = p => p.deck !== false && (p.figure || p.figures || (p.cards || []).length || p.slide || (p.pages || []).length);   // a project is on the deck when it has something to show
    // Company chapters: companies with deck projects; a project gets a slide when it has a figure, cards, pages or slide: true
    const chs = roles.filter(r => (r.projects || []).some(p => p.deck !== false)).map(r => ({ role: r, name: r.short || r.org,
      projects: ordered(r.projects).filter(onDeck) })).filter(c => c.projects.length);   // in the job's order; chapters without slides dropped
    // Chapters that are not companies (research, open source): the top-level chapters list, which the shared loader does not carry,
    // read here with the same language rule. They follow the company chapters
    const raw = JSON.parse(fs.readFileSync(profilePath, "utf-8"));
    // An image path as given, next to the profile, or in the repository
    const asset = f => [f, path.join(path.dirname(path.resolve(profilePath)), String(f || "")), path.join(__dirname, "..", String(f || ""))]
      .find(x => typeof f === "string" && f && path.isAbsolute(x) && fs.existsSync(x)) || null;   // an image next to the profile or in the repository
    // What the meta line calls a chapter's partner, per kind
    const KINDW = { research: { ko: "연구 지원", en: "Funder" }, opensource: { ko: "저장소", en: "Repository" }, other: { ko: "함께한 곳", en: "With" } };
    G.pickDeep(raw.chapters || [], lang, "chapters").forEach((c, i) => {   // each chapter in this edition's language
      if (!c || !c.name || !(c.projects || []).length) return;   // a chapter needs a name and projects
      const key = String(c.key || `ch${i + 1}`).replace(/[^\w-]/g, "_");   // a key safe in file names
      // The period as given, or from start and end, with the edition's range mark
      const period = c.period ? G.normPeriod(c.period, lang) : c.start ? `${G.normPeriod(c.start, lang)}${c.end ? (lang === "en" ? " - " : " ~ ") + G.normPeriod(c.end, lang) : ""}` : "";
      chs.push({ ext: { ...c, key, period }, name: c.short || c.name,   // after the company chapters
        projects: c.projects.filter(onDeck).map((p, pi) => ({ ...p, id: p.id || `${key}-${pi + 1}`, period: G.normPeriod(p.period, lang),   // deck projects with ids and normalized periods
          logo: typeof p.logo === "string" && asset(p.logo) ? { file: asset(p.logo) } : null })) });   // a project's own logo image, when the file exists
    });
    chs.forEach((c, i) => { c.no = String(i + 1).padStart(2, "0"); });   // chapter numbers 01, 02 and so on
    let page = 3;                                    // 1 cover, 2 contents, 3 career at a glance
    // Pages: each chapter's divider, then its projects in order, a spread taking one page per slide
    for (const c of chs) {
      c.page = ++page;                               // the divider's page
      // Each project's first and last page, and the range text the contents show
      c.projects.forEach(p => { p.page = page + 1; page += pagesOf(p).length; p.pageEnd = page; p.pageText = p.pageEnd > p.page ? `${p.page}${dash}${p.pageEnd}` : String(p.page); });
      c.last = page;                                 // the chapter's last page
    }
    const total = page + 1;                          // the end slide
    // Contents groups and rail tabs use the short name
    // A contents entry is one line: a title longer than its column takes the project's short name, when that one fits
    const { tw } = require("./portfolio/draw");      // the deck's measured text width
    const TOC_ROOM = 337;                            // measured: at 12.5 px titles up to 337 wide stay on one line in a .toc2 column, from 378 they wrap; between, the browser decides, so the safe side
    const tocTitle = p => (p.short && tw(String(p.title), 12.5, false) > TOC_ROOM && tw(String(p.short), 12.5, false) <= TOC_ROOM ? p.short : p.title);   // 12.5 px, as .toc2 .it
    const groups = chs.map(c => ({ no: c.no, name: c.name, page: c.page, last: c.last,
      items: c.projects.map(p => ({ title: tocTitle(p), tagline: p.tagline && tw(`${tocTitle(p)}  ${p.tagline}`, 12.5, false) <= TOC_ROOM ? p.tagline : "", page: p.pageText })) }));   // each project's title, its tagline when both fit one line (English runs longer), and its page or range
    const R = groups.length ? ST.rails(total, groups, lang) : null;   // the rail's tabs and markers (none without chapters)
    const rail = (n, dark) => (R ? ST.railHtml(R, n, dark, lang) : "");   // the rail of one slide

    // Contents. With more than twenty entries (chapters and projects) the three columns run to the footer, so their rows tighten
    // a little (a sixth chapter can push the Korean contents 1 px over)
    const entries = groups.reduce((a, g) => a + 1 + g.items.length, 0);
    // Tighter rows, tighter still past 26 entries
    if (entries > 20) deck.css += `.toc2 .it { padding-top: ${entries > 26 ? 7 : 8}px; padding-bottom: ${entries > 26 ? 7 : 8}px; } .toc2 .g { margin-bottom: 14px; }`;
    deck.add({ part: W.overview, rail: rail(2) },    // the contents slide, page 2
      eyebrow(h.sec(L.contents, "OVERVIEW"), "OVERVIEW"), S.contents ? lede(S.contents) : "",   // title, eyebrow and the contents lede
      ST.contentsBody(groups, lang, total));         // the chapter groups with their pages

    // Career at a glance: the timeline, the hierarchy layers and up to two selected project cards
    const layerRows = (S.layers || []).filter(x => Array.isArray(x) && x[0]);   // the hierarchy rows [layer, skills, where]
    const lsvg = layerRows.length ? (() => {         // the layers drawn with the deck's boxes: a dark name cell, a band with two lines
      const { C, D, Svg } = require("./portfolio/draw");   // the deck's colors, parts and canvas
      const w = 620, rh = 50, gap = 8, ht = layerRows.length * (rh + gap) - gap, sv = new Svg(w, ht);   // canvas for the left column
      layerRows.forEach(([name, tech, where], i) => {   // one row per layer
        // Lighter at the top, navy at the bottom
        const y = i * (rh + gap), shade = [C.n3, C.n2, C.n2, C.navy, C.navy, C.navy][Math.min(5, Math.round(i * 5 / Math.max(1, layerRows.length - 1)))];
        // The name cell, its text fitted to the cell
        sv.add(D.box(0, y, 200, rh, { fill: shade, stroke: shade, title: CH.fit(name, 13, true, 180, CUT, "layer name"), color: C.white, align: "left", size: 13 }));
        sv.add(D.box(208, y, w - 208, rh, { fill: C.band, stroke: C.band, title: CH.fit(tech || "", 12, true, w - 230, CUT, "layer skills"),   // the band with the layer's skills
          sub: where ? CH.fit(where, 10.5, false, w - 230, CUT, "layer where") : undefined, align: "left", size: 12, subSize: 10.5 }));   // and where it was used, in a smaller line
      });
      return sv.toString();                          // SVG for the figure frame
    })() : "";                                       // no layers: no figure
    const tlg = figFile("timeline_deck");            // the flat deck timeline drawn by overview_figures.py
    deck.add({ part: W.overview, rail: rail(3) },    // the career slide, page 3
      eyebrow(h.sec(L.ov, "OVERVIEW"), "OVERVIEW"), S.glance ? lede(S.glance) : "",   // title, eyebrow and the glance lede
      // The flat timeline image, else the drawn one
      tlg ? `<figure class="fig natural" style="flex:none"><div class="frame bare"><img src="file://${esc(tlg)}" alt="" style="width:100%"></div></figure>` : (tlSvg ? h.fig(tlSvg, { bare: true, natural: true, style: "flex:none" }) : ""),
      h.grid("split-55", "",                         // layers on the left, highlight cards on the right
        // The layer figure with its caption, else an empty cell
        lsvg ? h.fig(lsvg, { bare: true, cap: lang === "en" ? "**Layers** with the projects behind each" : "**계층** 계층마다 그 일을 한 자리" }) : "<div></div>",
        `<div class="stack">${(S.highlights || []).slice(0, 2).map(c => h.hcard(c)).join("")}</div>`));   // two highlight cards at most

    // The body of one project page: figures and cards. With cards, the main figure takes the left column (760 x 570) and the right
    // column holds the cards and, when the cards leave room, a side figure; figures that find no room join the main figure as panels.
    // Without cards, what I did sits beside the figure (split-46). Card numbers (the third element, or mark) pair cards with figure parts
    const pageBody = (p, pg, where) => {
      const figs = [].concat(pg.figure ? [pg.figure] : [], pg.figures || []).filter(f => f && FIG[f.type]);   // known figure types only
      figs.forEach((f, i) => checkFigure(f, `${where} ${i + 1}`));   // bad data stops the build with the project named
      // Cards as { t, b, no } from lists or objects
      const cards = (pg.cards || []).map(c => (Array.isArray(c) ? { t: c[0], b: c[1], no: c[2] } : { t: c.head || c.title, b: c.text || c.body, no: c.mark }));
      const cardHtml = cards.map(c => h.card(c.t, c.b, c.no ? { no: c.no } : {}));   // a card with its number badge when it has one
      const ledeText = pg.lede || (pg === p ? p.lede || p.summary : "") || "";   // the page's lede, else the project's
      if (figs.length && cards.length) {             // figures and cards: the split layout
        const room = sideRoom(cards, ledeText, lang);   // canvas height the side figure may take under the cards' share of the column
        let main = figs[0], side = null;             // the first figure is the main one
        let rest = figs.slice(1);                    // the figures left to place
        // A short main figure (under about 60% of its frame) and the next figure share the main frame as panels when both fit there:
        // a lone strip in a tall frame reads as empty
        if (rest.length && main.type !== "panels" && CH.DRAW[toLib(main).type] && CH.DRAW[toLib(rest[0]).type] && naturalH(toLib(main), MAIN[0]) < MAIN[1] * 0.6) {
          const pack = autoPanels([main, rest[0]]), trial = [];   // the two as panels
          CH.render(pack, MAIN[0], MAIN[1], trial, { lang });   // drawn once to see that nothing is cut
          if (!trial.length) { main = pack; rest = rest.slice(1); }   // nothing cut: the pack becomes the main figure
        }
        if (rest.length) {                           // the second figure goes to the side when it fits there without losing text
          const cand = rest[0], trial = [];          // the next figure
          // A library figure, not a composite, with room, that draws whole at the side size
          const fitsSide = !SIMPLE.has(cand.type) && cand.type !== "panels" && room >= 110 && (() => { CH.render(cand, SIDE_W, Math.min(300, room), trial, { lang }); return !trial.length; })();
          if (fitsSide) side = cand;                 // it takes the side slot
          const join = fitsSide ? rest.slice(1) : rest;   // the figures left over join the main figure, one by one, while it still draws whole
          for (const f of join) {                    // each leftover figure in order
            const g = toLib(f);                      // its library form
            // Panels never nest: a composite gives its own panels, any other figure is one panel titled by its caption
            const parts = g.type === "panels" ? (g.panels || []) : [{ title: boldOf(f.caption), mark: f.mark, figure: g }];
            const base = main.type === "panels" ? main.panels : CH.DRAW[toLib(main).type] ? [{ title: boldOf(main.caption), mark: main.mark, note: main.note, figure: toLib(main) }] : null;   // the main figure's panels
            let next = null;                         // the main figure with this one added
            if (base && parts.length && parts.every(x => x && x.figure && CH.DRAW[x.figure.type] && x.figure.type !== "panels") && base.length + parts.length <= 4) {   // four panels at most
              const all = [...base, ...parts];       // the panels so far and these
              const holds = { "1": 1, "2": 2, "3": 3, "2v": 2, "3v": 3, "1+2": 3, "2+1": 3, "2x2": 4 }[main.layout] || 1;   // how many the layout holds
              next = { type: "panels", caption: main.caption, ...(main.type === "panels" ? main : {}), panels: all,   // the composite, or a new one around a single main figure
                layout: main.type === "panels" && all.length <= holds ? main.layout : all.length === 2 ? "2v" : all.length === 3 ? "1+2" : "2x2" };   // the layout kept when it holds them, else two, three or four
            }
            const trial = [];                        // notes of a trial drawing
            if (next) CH.render(next, MAIN[0], MAIN[1], trial, { lang });   // drawn once at the main size
            if (next && !trial.length) main = next;  // it fits: one more panel
            // No room: recorded and printed, never dropped silently
            else LEFT.push(`${where}: '${boldOf(f.caption) || f.type}' found no room on the slide (the cards fill the column and the main figure is full)`);
          }
        }
        const sideHtml = side ? figureHtml(side, where, { natural: true }, [SIDE_W, Math.max(110, Math.min(300, room))]) : "";   // the side figure at the room the cards leave, between 110 and 300 px
        return h.grid("split-64", "", figureHtml(main, where, {}, MAIN), `<div class="stack">${sideHtml}${cardHtml.join("")}</div>`);   // main figure left, side figure and cards right
      }
      if (figs.length) {                             // a figure without cards: what I did beside it, extra figures as panels
        const main = figs.length > 1 ? autoPanels(figs) : figs[0];   // several figures as panels of one
        // What was done beside the figure, drawn at the wide size
        return h.grid("split-46", "", h.card(L.did, p.points && p.points.length ? p.points : [p.summary || ""]), figureHtml(main, where, {}, WIDE));
      }
      if (cards.length) return h.grid(cards.length === 3 ? "cols-3" : "cols-2", "align-content:start", ...cardHtml);   // cards keep their own height
      return h.grid("cols-2", "", h.card(L.did, p.points && p.points.length ? p.points : [p.summary || ""]));   // neither: what was done, on its own
    };

    // Chapters and their project slides
    chs.forEach(c => {
      const r = c.role, x = c.ext;                   // a company chapter, or a chapter that is not a company
      const tl = r ? figFile(`timeline_ch_${r.logoId}`) : figFile(`timeline_ch_ch_${x.key}`);   // its timeline variant with this chapter dark
      // The chapter's logo tile: the company's, or one drawn for this chapter
      const chTile = r ? tile(r.logoId) : (() => { const f = path.join(figDir, `${out}_logo_ch_${x.key}.png`); return fs.existsSync(f) ? f : null; })();
      const meta = { company: r ? r.org : x.name, part: c.no + " " + c.name, footnote: `${c.no}  ${c.name}` };   // the slide meta: the company counted, the contents part, the footnote
      let divider;                                   // the chapter's divider slide
      if (r) divider = ST.chapterSlide({ no: c.no, name: r.chapterName || (lang === "ko" ? r.org : r.short || r.org), enName: lang === "ko" ? (r.enName || "") : "", logo: tile(r.logoId), title: lang === "en" ? r.titleLong || r.title : r.title || r.titleLong,   // Korean dividers show the Korean role
        period: r.period, place: r.place, clients: r.clients || "", lead: r.lead || "", stack: r.stack || [], timeline: tl,   // period, place, clients, lead, stack and the timeline image
        // The chapter's project list with pages
        projects: c.projects.map(p => ({ title: p.title, short: p.short || "", tagline: p.tagline || "", role: p.role || "", context: p.context || "", period: p.period || "", page: p.pageText })) }, lang);
      else {
        // The Korean divider titles the chapter in Korean with its English name under it; the meta line
        // names the funder (or what the kind calls it) where a company chapter names its clients
        divider = ST.chapterSlide({ no: c.no, name: x.chapterName || x.name, enName: lang === "ko" ? (x.enName || "") : "", logo: chTile, title: x.title || "",
          // Period, place, the funder (else clients), lead, stack and timeline
          period: x.period || "", place: x.place || "", clients: x.funder || x.clients || "", lead: x.lead || "", stack: x.stack || [], timeline: tl,
          // The chapter's project list with pages
          projects: c.projects.map(p => ({ title: p.title, short: p.short || "", tagline: p.tagline || "", role: p.role || "", context: p.context || "", period: p.period || "", page: p.pageText })) }, lang);
        const word = (KINDW[x.kind] || KINDW.research)[lang];   // the kind's word for its partner
        divider = divider.replace(`<b>${h.esc(W.clients)}</b>`, `<b>${h.esc(x.metaLabel || word)}</b>`);   // replaces the divider's clients label
      }
      deck.add({ kind: "chapter", cls: "chapter", rail: rail(c.page, true), ...meta }, divider);   // the divider, with the rail dark on this chapter
      c.projects.forEach((p, i) => {                 // the chapter's projects in order
        const pages = pagesOf(p), where = `project '${p.title}' figure`;   // names the project in figure data errors and cut notes
        pages.forEach((pg, k) => {                   // one slide per page
          const mark = pages.length > 1 ? ` (${k + 1}/${pages.length})` : "";   // a spread's page in its title
          const sec = h.sec(p.title + mark + (p.tagline ? "  " + p.tagline : ""), "PROJECT");   // title with the tagline in grey
          // The title plate shows the client's logo, else the chapter's (an in-house project)
          const logos = [p.logo && p.logo.file ? p.logo.file : null, p.logoId ? tile(p.logoId) : null, chTile].filter(Boolean).slice(0, 1);
          const ledeText = pg.lede || (pg === p ? p.lede || p.summary : "") || "";   // the page's lede, else the project's
          deck.add({ rail: rail(p.page + k), ...meta, kind: "project", project: p.id || null, spread: pages.length > 1 ? k + 1 : 0 },   // the slide, with the rail on its page; its project for a talk
            ST.projectHeader(sec, { lang, no: c.no, chapterName: c.name, index: i + 1, total: c.projects.length, period: p.period,   // the header: chapter, index, period
              role: p.role, context: p.context, stack: p.stack, chips: p.chips, logos }),   // role, context, stack line, chips and the logo
            ledeText ? lede(ledeText) : "", pageBody(p, pg, where));   // the lede, then figures and cards
        });
      });
    });
  }

  // End slide: name and contacts
  deck.add({ kind: "end", cls: "eod" },
    `<div class="end"><div class="top"><span>${L.end}</span><span class="r">PORTFOLIO</span></div>` +   // the top line: the end mark and PORTFOLIO
    `<div class="mid"><h1>${esc(N1)}${N2 ? `<small>${esc(N2)}</small>` : ""}</h1><div class="tag">${esc(P.tagline || "")}</div>` +   // the name, the other name small, the tagline
    (S.deckHeadline || S.headline ? `<div class="lead">${h.rich(String(S.deckHeadline || S.headline).replace(/\n/g, " "))}</div>` : "") + `</div>` +   // the headline on one line, when there is one
    // The contacts again, links clickable
    `<div class="bot">${contacts.map(([k, v, l]) => `<div class="cc" style="grid-template-columns:auto 1fr"><b>${esc(k)}</b>${l ? `<a href="${esc(l)}">${esc(v)}</a>` : `<span class="v">${esc(v)}</span>`}</div>`).join("")}</div></div>`);

  const n = deck.render(path.join(__dirname, "..", "output", out + "_deck.html"));   // the deck HTML; resume.py prints it to PDF
  fs.writeFileSync(path.join(__dirname, "..", "output", out + "_deck.cut.json"), JSON.stringify(CUT, null, 1));   // the cut notes the document check reports
  fs.writeFileSync(path.join(__dirname, "..", "output", out + "_deck.left.json"), JSON.stringify(LEFT, null, 1));   // figures with no place
  console.log("slides", n);                          // the slide count for the caller
  for (const l of LEFT) console.log("  left out: " + l);   // figures left out, printed so they are seen
  return n;                                          // the slide count
}

module.exports = { build, timeline, flow, compare, layers, FIG, rooms };   // the deck, its simple templates and the room estimate
// The side room of every deck project page (a project id to one height per page), for src/figure_draft.py: its review draws a side
// figure at the room the cards leave, so a figure it accepts fits where the deck puts it
function rooms(profilePath, lang) {
  const prof = G.load(profilePath, lang, {}), out = {};   // the profile as the deck loads it
  const raw = JSON.parse(fs.readFileSync(profilePath, "utf-8"));   // the raw file, for the top-level chapters
  const extra = G.pickDeep(raw.chapters || [], lang, "chapters").flatMap(c => (c && c.projects) || []);   // projects of the chapters that are not companies
  for (const p of [...prof.roles.flatMap(r => r.projects || []), ...extra]) {   // every project the deck may show
    if (!p || p.deck === false) continue;            // kept off the deck
    const pages = Array.isArray(p.pages) && p.pages.length ? p.pages : [p];   // a project's pages, or the project as its one page
    out[p.id] = pages.map(pg => {                    // one room per page
      // Cards as { t, b, no }, as pageBody reads them, each with a number badge: applying figures numbers the cards their parts show,
      // and a badge narrows the head, so the room is measured as it will be (a card left without a number only leaves more room)
      const cards = (pg.cards || []).map(c => (Array.isArray(c) ? { t: c[0], b: c[1], no: c[2] || 1 } : { t: c.head || c.title, b: c.text || c.body, no: c.mark || 1 }));
      return cards.length ? Math.round(sideRoom(cards, pg.lede || (pg === p ? p.lede || p.summary : "") || "", lang)) : null;   // the room the cards leave; null without cards (no side column then)
    });
  }
  return out;                                        // project id to rooms
}

if (require.main === module && process.argv[2] === "--rooms") {   // node src/deck_slides.js --rooms <profile.json> <ko|en>
  process.stdout.write(JSON.stringify(rooms(process.argv[3], process.argv[4] || "ko")));   // JSON for figure_draft.py
  process.exit(0);                                   // the room estimate only, no deck
}
if (require.main === module) {                       // run as a command: build the deck
  const [prof, cfgPath] = process.argv.slice(2);     // the profile and the optional job file
  if (!prof) { console.error("usage: node src/deck_slides.js <profile.json> [job.json]"); process.exit(1); }   // the usage line without a profile
  build(prof, cfgPath ? JSON.parse(fs.readFileSync(cfgPath, "utf-8")) : {});   // the job file's settings, or the defaults
}
