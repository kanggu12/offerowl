// Assembler for the 16:9 portfolio deck. It builds the slides as HTML; a separate step prints that HTML to PDF with chromium
// (resume.py does it for the builders).
// The look (colors, font, bands, cards, tags, yellow highlight) lives in theme.css and is carried over unchanged from the
// career-history resume layout (layout.js).
//
// A measurement script (PROBE, at the bottom) runs on every slide. It measures elements that leave the slide, text that overflows
// its box, footer intrusion, picture resolution and the empty space below a box, and leaves the result as JSON in #probe-out.
// The checks (check_documents.py) judge the deck from that JSON, so none of this has to be found by eye.
const fs = require("fs");
const path = require("path");
// Blind edition, made for attaching to a public profile. Text matched by "mask" in src/blind.json is hidden behind a bar of its
// original width (color mask_fill). Pictures are not hidden as a whole; only the matching text inside them is. A band across the
// top of the cover and a label in every slide footer make the blind edition obvious at a glance (BLIND_CSS).
const BL = require("../blind");
// A word joiner (U+2060, no line break allowed) goes between a bar and a Latin letter, digit or Hangul letter right next to it
// (for example a bar followed by "Gbps"). The original word is never split (keep-all) and moves to the next line as a whole, but
// the edge of a bar is a break opportunity, so the blind edition would wrap between the bar and the rest of the word. Inside the
// bar, white-space: nowrap on .bm prevents wrapping.
const WORD = /[A-Za-z0-9\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3]/;
function maskHtmlText(t) {
  if (!BL.hit(t)) return t;
  const segs = BL.segments(t);
  return segs.map(([s, m], i) => {
    if (!m) return s;
    const prev = i > 0 ? segs[i - 1][0].slice(-1) : "", next = i + 1 < segs.length ? segs[i + 1][0][0] : "";
    return (WORD.test(prev) ? "\u2060" : "") + BL.htmlBar(s) + (WORD.test(next) ? "\u2060" : "");
  }).join("");
}
// In SVG the bar width is fitted per <text> element, from its font size and weight
function maskSvg(svg) {
  return svg.replace(/<text\b([^>]*)>([\s\S]*?)<\/text>/g, (all, attrs, inner) => {
    const fs = Number((attrs.match(/font-size="([\d.]+)"/) || [0, 12])[1]);
    const bold = Number((attrs.match(/font-weight="(\d+)"/) || [0, 400])[1]) >= 600 || /font-weight="bold"/.test(attrs);
    const body = inner.replace(/(^|>)([^<]+)/g, (m, a, t) => a + (BL.hit(t) ? BL.segments(t).map(([s, mk]) => mk ? BL.svgBar(s, fs, bold) : s).join("") : t));
    return `<text${attrs}>${body}</text>`;
  });
}
// A link whose address the table covers loses its address (a mail link would carry the covered value into the PDF's link);
// the element stays an <a>, so the contact rows keep their look
const unhtml = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const unlink = html => html.replace(/<a href="([^"]*)"/g, (all, href) => BL.hit(unhtml(href)) ? "<a" : all);
function blindHtml(html) {
  html = unlink(html);                                                              // the addresses first: the text below is covered next
  const repl = s => s.replace(/(^|>)([^<]+)/g, (m, a, t) => a + maskHtmlText(t));
  let out = "", depth = 0, start = 0, m;
  const re = /<svg\b|<\/svg>/g;
  while ((m = re.exec(html))) {
    if (m[0] !== "</svg>") { if (depth === 0) { out += repl(html.slice(start, m.index)); start = m.index; } depth++; }
    else if (--depth === 0) { out += maskSvg(html.slice(start, re.lastIndex)); start = re.lastIndex; }
  }
  return out + repl(html.slice(start));
}
// Bar width fitting before printing: measure the original text (data-t) on a canvas with the real font, weight, size and letter
// spacing of its place, set the letter spacing of the bar (a run of square glyphs) so that it matches that width, then delete
// data-t. It runs before the measurement script (PROBE). Chromium finishes it inside --virtual-time-budget, before it prints
// the PDF.
const BLIND_JS = `(async () => {
  await document.fonts.ready;
  const cv = document.createElement("canvas").getContext("2d");
  for (const el of document.querySelectorAll(".bm[data-t]")) {
    const cs = getComputedStyle(el.parentElement);
    cv.font = cs.fontStyle + " " + cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily;
    cv.letterSpacing = cs.letterSpacing === "normal" ? "0px" : cs.letterSpacing;
    const want = cv.measureText(el.getAttribute("data-t")).width;
    el.removeAttribute("data-t");
    el.style.letterSpacing = "0px";
    const have = el.getBoundingClientRect().width, n = el.textContent.length;
    el.style.letterSpacing = ((want - have) / n).toFixed(3) + "px";
  }
  // SVG bars: insert the original text into the same <text> for a moment, read its real width, set textLength, then remove it
  for (const ts of document.querySelectorAll("tspan.bms[data-t]")) {
    const tmp = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
    tmp.textContent = ts.getAttribute("data-t");
    ts.parentNode.insertBefore(tmp, ts);
    const w = tmp.getComputedTextLength();
    tmp.remove();
    ts.removeAttribute("data-t");
    if (w > 0) ts.setAttribute("textLength", w.toFixed(2));
  }
})();`;
// Blind edition markers: a band across the top of the cover (.blindbar) and a label in every slide footer (.bv), both in dark red
// (mark_fill). The masking bars use the same red, so markers and bars read as one set.
const BLIND_CSS = lang => `
/* A bar shows only its background. The block glyphs are transparent because they stuck out of the width narrowed by negative spacing and touched the next letter.
   !important keeps the cover's text color rules (.cover .contact span and others) from overriding this */
.bm { background: #${BL.T.mask_fill} !important; color: transparent !important; border-radius: 1.5px; white-space: nowrap; }
.cover .top { position: relative; }
.cover .blindbar { position: absolute; left: 0; right: 0; top: 0; height: 26px; background: #${BL.T.mark_fill}; color: #FFFFFF;
  display: flex; align-items: center; justify-content: center; gap: 16px; }
.cover .blindbar b { font-size: 11.5px; font-weight: 700; letter-spacing: 2.2px; }
.cover .blindbar i { width: 1px; height: 11px; background: rgba(255,255,255,0.75); }
.cover .blindbar span { font-size: 11.5px; font-weight: 400; color: #FFECEA; }
.foot .bv { margin-left: 10px; padding: 1px 6px; background: #${BL.T.mark_fill}; color: #FFFFFF; font-weight: 700; letter-spacing: 1px; border-radius: 2px; }
`;

const ROOT = path.join(__dirname, "..", "..");
// A person's screen captures and logos stay outside the repository. render/run.sh mounts them at /offerowl-assets.
const ASSETS = fs.existsSync("/offerowl-assets") ? "/offerowl-assets" : (process.env.OFFEROWL_ASSETS || path.join(ROOT, "assets"));

const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// rich() below turns ==phrase== into a yellow highlight (the same notation as the resume) and **text** into bold.
// A hyphenated word (CI-CD, Scale-out) is wrapped into one nowrap unit so that a line never breaks after its hyphen.
// A command-line option (--user) gets the same treatment, so it never splits into '--' and 'user'.
const nobreak = t => t.replace(/(^|[^\w&#;-])([A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)(?=$|[^\w-])/g, '$1<span class="nw">$2</span>')
  .replace(/(^|[\s(])(--?[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)(?=$|[^\w-])/g, '$1<span class="nw">$2</span>');
// The house style puts a space between a Latin word and the Korean particle (josa) that follows it. If the line broke at that
// space, the next line would start with the particle (the deck check flags this), and rewording the sentence only moved the break
// somewhere else. So that one space becomes a no-break space. The source string is untouched, so the keys of the English table
// are not affected.
const JOSA = "을|를|이|가|은|는|의|으로|로|와|과|에서|에|까지|부터|도|만|에는|에서는|으로는|이나|이라|이며|이고|이라는|라는|보다|처럼|마다|와는|과는|로는|에게";
const keepJosa = t => t.replace(new RegExp(`([A-Za-z0-9)\\]%+]) (${JOSA})(?=[\\s.,)/]|$)`, "g"), "$1\u00a0$2");
const rich = s => nobreak(keepJosa(esc(s))).replace(/==(.+?)==/g, "<mark>$1</mark>").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");

// Picture path. Forms: "pf:<folder>/<file>.png" (a picture under portfolio/ in the assets folder), "fig:<file>.png" (a generated
// figure under output/_fig) and "logo:<name>" (a logo tile under output/_logos).
function src(ref) {
  const [kind, rest] = ref.split(/:(.+)/);
  let p;
  if (kind === "pf") p = path.join(ASSETS, "portfolio", rest);
  else if (kind === "fig") p = path.join(ROOT, "output", "_fig", rest);
  else if (kind === "logo") p = path.join(ROOT, "output", "_logos", "tile_" + rest + ".png");
  else throw new Error("unknown picture path kind: " + ref);
  if (!fs.existsSync(p)) throw new Error("picture not found: " + p);
  return "file://" + esc(p);                         // an attribute's text: a path with a quote stays a path
}

// Number circle on a card title. The baseline of HTML text snaps to whole pixels, so depending on the fractional position of the
// card the digit moved up and down inside the circle by as much as 1.1px. The circle and the digit are drawn in one SVG so they
// share a coordinate system, and the vertical center of the digit's ink lands on the center of the circle (9).
const mkSvg = n => {
  const { inkV } = require("./draw"), [t, b] = inkV(String(n), 10.5, true), y = Math.round((9 - (t + b) / 2) * 100) / 100;
  return `<svg class="mkc" viewBox="0 0 18 18" width="18" height="18"><circle cx="9" cy="9" r="9" fill="#1B2E4B"/>` +
    `<text x="9" y="${y}" font-size="10.5" font-weight="700" fill="#FFFFFF" text-anchor="middle">${esc(String(n))}</text></svg>`;
};
const h = {
  esc, rich, src,
  // Header: the part of the title before a double space is the large title, the part after it the grey subtitle. The header line
  // (chapter, project, label on the right) and the chips are filled in by deck_structure.js.
  sec: (title, en, note) => {
    const t = String(title), [main, ...rest] = t.split(/\s{2,}/);
    // Pieces of a title that has no table entry are not added to the missing list (the whole title is already on it)
    return `<div class="sec" data-en="${esc(en || "")}"><!--EYEBROW--><div class="ttl"><h1>${rich(main)}` +
      (rest.length ? `<span class="t2">${rich(rest.join(" "))}</span>` : "") + `</h1>${note ? `<span class="note">${rich(note)}</span>` : ""}</div></div>`;
  },
  lede: t => `<p class="lede">${rich(t)}</p>`,
  cap: t => `<div class="cap">${rich(t)}</div>`,
  sub: t => `<div class="sub">${rich(t)}</div>`,
  tags: ts => ts && ts.length ? `<div class="tags">${ts.map(t => `<span>${esc(t)}</span>`).join("")}</div>` : "",
  // Card. A body that is an array becomes a bullet list. The number that pairs a card with a figure sits at the right end of the
  // title line (the same side where the figure panel carries its number), so the titles of cards with and without a number start
  // in the same column. Cards carry no line icon: it would be decoration with no fixed meaning.
  card: (title, body, o = {}) => `<div class="card${o.white ? " white" : ""}"${o.style ? ` style="${o.style}"` : ""}>` +
    (title ? `<h3><span>${rich(title)}</span>${o.no ? `<span class="mk">${mkSvg(o.no)}</span>` : ""}</h3>` : "") +
    // No technology tag row under a card. The names already appear in the stack entry of the header line, in the figure and in the
    // card text, so they are woven into those instead of being listed again.
    (Array.isArray(body) ? `<ul>${body.map(b => `<li>${rich(b)}</li>`).join("")}</ul>` : `<p>${rich(body)}</p>`) + `</div>`,
  // Flagship project card (the resume's fhighlights): problem / what was done / result
  hcard: c => `<div class="hcard"><div class="hd"><b>${rich(c.title)}</b><span>${rich(c.where || "")}</span></div>` +
    // A row's third value (extra detail) follows the main value only on the wide portfolio card; the narrow resume card shows the
    // main value alone.
    `<div class="bd">${c.rows.map(([k, v, more]) => `<span class="k">${esc(k)}</span><span class="v">${rich(v)}${more ? ". " + rich(more) : ""}</span>`).join("")}` + `</div></div>`,
  // Bullet list (the resume's fbul). An item may be a [bold lead, text] pair.
  bul: items => `<ul class="bul">${items.map(it => Array.isArray(it)
    ? `<li><b>${rich(it[0])}</b> ${rich(it[1])}</li>` : `<li>${rich(it)}</li>`).join("")}</ul>`,
  quote: (head, text) => `<div class="quote"><b>${rich(head)}</b><p>${rich(text)}</p></div>`,
  // Figure. ref is either a path for src() or an SVG string. o.cap is the caption below the figure and o.style sets the cell size.
  fig: (ref, o = {}) => `<figure class="fig${o.natural ? " natural" : ""}${o.cls ? " " + o.cls : ""}"${o.style ? ` style="${o.style}"` : ""}><div class="frame${o.bare ? " bare" : ""}">` +
    (ref.trim().startsWith("<svg") ? ref : `<img src="${src(ref)}" alt="">`) + `</div>` +
    (o.cap ? `<figcaption>${rich(o.cap)}</figcaption>` : "") + `</figure>`,
  table: (head, rows, o = {}) => `<table class="t"${o.style ? ` style="${o.style}"` : ""}><tr>${head.map(x => `<th>${rich(x)}</th>`).join("")}</tr>` +
    rows.map(r => `<tr>${r.map((x, i) => `<td${i === 0 && o.key ? ' class="k"' : ""}>${rich(x)}</td>`).join("")}</tr>`).join("") + `</table>`,
  div: (cls, ...kids) => `<div class="${cls}">${kids.join("")}</div>`,
  grid: (cls, style, ...kids) => `<div class="body ${cls}"${style ? ` style="${style}"` : ""}>${kids.join("")}</div>`,
};

// Table of glyph outline bounds for the characters used in figure text (SVG text). The probe's check of text inside boxes uses it
// to work out where the ink falls.
const glyphsOf = body => {
  const chars = new Set(" -0123456789");
  // Strip the tspan elements inside the text (draw.js splitSub) and collect only the characters
  for (const m of body.matchAll(/<text[^>]*>([\s\S]*?)<\/text>/g))
    for (const ch of m[1].replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&amp;/g, "&")) chars.add(ch);
  return require("./draw").glyphTable([...chars]);
};

// A color set from a theme file (OFFEROWL_THEME_FILE, the same file the resume's layout.js reads). Its colors override the theme.css
// variables. The mapping is the same pair list that the resume and the deck keep in step (nameFill is --navy, acc2 is --blue, band
// is --band, rule is --rule, key is --key). --deep is the name-cell color made a little darker. Without a theme file this
// returns an empty string, so the default output stays byte-identical.
function themeFileCss(name) {
  // With a set name (the theme setting of the deck) use that set. Without a name, use OFFEROWL_THEME or navy, but only when a
  // theme file exists. With neither a name nor a file, return an empty string.
  if (!name && !process.env.OFFEROWL_THEME_FILE) return "";
  if (name === "navy" && !process.env.OFFEROWL_THEME_FILE) return "";   // the built-in navy is theme.css as it is, with hand-picked pale steps
  const t = require("../theme_load").theme(name || process.env.OFFEROWL_THEME || "navy");
  const dark = hex => "#" + [0, 2, 4].map(i => Math.round(parseInt(hex.slice(i, i + 2), 16) * 0.75).toString(16).padStart(2, "0")).join("");
  // Pale steps mixed toward white (--b2, --b3 and --b4 are pale steps of the accent color, --paper is the figure frame background)
  const tint = (hex, k) => "#" + [0, 2, 4].map(i => Math.round(parseInt(hex.slice(i, i + 2), 16) * (1 - k) + 255 * k).toString(16).padStart(2, "0")).join("");
  // Dark color: the name-cell color, but when that is light (the mono set's E4E4E4) the section-title color, then the accent color,
  // whichever is dark enough first, else near black. Otherwise white text lands on a light fill and fails the contrast check.
  const lum = hex => [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)).reduce((a, c, i) => a + c * [0.299, 0.587, 0.114][i], 0);
  const deepC = [t.nameFill, t.sec, t.acc].find(x => x && lum(x) < 140) || "1F1F1F";
  const acc0 = t.acc2 || t.acc, acc = lum(acc0) < 170 ? acc0 : deepC;
  const v = { navy: deepC, blue: acc, band: t.band, rule: t.rule, key: t.key };
  return ":root{" + Object.entries(v).filter(([, x]) => x).map(([k, x]) => `--${k}:#${x};`).join("") + `--deep:${dark(deepC)};` +
    `--b2:${tint(acc, 0.3)};--b3:${tint(acc, 0.55)};--b4:${tint(acc, 0.8)};--paper:${tint(deepC, 0.95)};}`;
}

// The figures and badges are drawn in the navy family (draw.js). Another colour set maps that family to its own tones, so a figure never
// stays navy on a wine deck; the category colours and the greys stay as they are
function themeMap(name) {
  if (!name || (name === "navy" && !process.env.OFFEROWL_THEME_FILE)) return null;   // navy needs nothing
  const { C } = require("./draw");                   // the family as the figures use it
  const t = require("../theme_load").theme(name);    // the colour set
  const mix = (hex, k) => "#" + [0, 2, 4].map(i => Math.round(parseInt(hex.slice(i, i + 2), 16) * (1 - k) + 255 * k).toString(16).padStart(2, "0")).join("").toUpperCase();   // toward white
  const lum = hex => [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)).reduce((a, c, i) => a + c * [0.299, 0.587, 0.114][i], 0);   // how light
  const deep = [t.nameFill, t.sec, t.acc].find(x => x && lum(x) < 140) || "1F1F1F";   // as themeFileCss picks it
  const acc0 = t.acc2 || t.acc, acc = lum(acc0) < 170 ? acc0 : deep;   // and the accent
  // Some tones carry words: n3 holds white text and sits on white as text, b1 sits on white as text, and the pale ones hold the dark tone or grey
  const srgb = c => { const x = c / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };   // a channel's light
  const light = hex => [0, 2, 4].map(i => srgb(parseInt(hex.slice(i + 1, i + 3), 16))).reduce((a, c, i) => a + c * [0.2126, 0.7152, 0.0722][i], 0);   // a colour's light
  const contrast = (a, b) => (Math.max(light(a), light(b)) + 0.05) / (Math.min(light(a), light(b)) + 0.05);   // the probe's measure
  const reads = hex => { let h = hex; for (let k = 0; k < 40 && contrast(h, "#FFFFFF") < 4.6; k++) h = "#" + [1, 3, 5].map(i => Math.round(parseInt(h.slice(i, i + 2), 16) * 0.97).toString(16).padStart(2, "0")).join("").toUpperCase(); return h; };   // 3% darker at a time, past the probe's 4.5
  const under = (hex, ink) => { let h = hex; for (let k = 0; k < 40 && contrast(h, ink) < 4.6; k++) h = mix(h.slice(1), 0.06); return h; };   // a pale fill that words sit on: paler until they read
  const to = { navy: "#" + deep, n2: reads(mix(deep, 0.15)), n3: reads(mix(deep, 0.3)), blue: reads("#" + acc), b1: reads(mix(acc, 0.1)), b2: mix(acc, 0.3), b3: under(mix(acc, 0.55), "#" + deep), b4: under(mix(acc, 0.8), "#" + deep), b5: under(mix(acc, 0.9), C.grey),
               band: "#" + t.band, key: "#" + t.key, rule: "#" + t.rule };   // tone by tone
  const map = { "#DCE6F3": mix(acc, 0.85), "#E3E8EF": mix(deep, 0.88) };   // two pale tones the figures name directly
  for (const [k, v] of Object.entries(to)) if (C[k]) map[C[k].toUpperCase()] = v;   // the family's own hex values
  return map;
}

class Deck {
  // theme: name of a color set. lang: 'ko' (the default) or 'en'. css: CSS to append. look: "clean" for the light deck.
  constructor({ title, footer, theme, lang, css, look }) { this.look = look; this.title = title; this.footer = footer; this.slides = []; this.theme = theme; this.lang = lang || "ko"; this.css = css || ""; }
  // meta.company: the company section a slide belongs to (the length check counts by it). meta.part: the contents group.
  add(meta, ...parts) { this.slides.push({ meta, html: parts.join("") }); return this.slides.length; }
  render(outPath) {
    // The English edition appends theme_en.css (body text size and letter spacing). The Korean HTML is not affected.
    const css = fs.readFileSync(path.join(__dirname, "theme.css"), "utf8") +
      (this.lang === "en" ? fs.readFileSync(path.join(__dirname, "theme_en.css"), "utf8") : "") +
      (this.look === "clean" ? fs.readFileSync(path.join(__dirname, "style_clean.css"), "utf8") : "") +   // the light deck's colours, over the same parts
      (BL.on ? BLIND_CSS(this.lang) : "") + themeFileCss(this.theme) + this.css;
    const n = this.slides.length;
    let body = this.slides.map((s, i) =>
      `<section class="slide${s.meta.cls ? " " + s.meta.cls : ""}" data-company="${esc(s.meta.company || "")}" data-part="${esc(s.meta.part || "")}" ` +
      `data-kind="${esc(s.meta.kind || "")}">` +
      s.html + (s.meta.rail || "") + (s.meta.nofoot ? "" : `<div class="foot"><span>${esc(this.footer)}${BL.on ? `<b class="bv">${esc(BL.T.footer[this.lang === "en" ? "en" : "ko"])}</b>` : ""}${s.meta.footnote ? "   " + esc(s.meta.footnote) : ""}</span>` +
        `<span class="n">${i + 1} / ${n}</span></div>`) +
      `</section>`).join("\n");
    // The blind edition (OFFEROWL_BLIND=1) masks matching text run by run (src/blind.json: customer names and the like). Attributes
    // inside tags are left alone (picture paths), except a link's address that the table covers, which goes.
    if (BL.on) body = blindHtml(body);
    const tones = themeMap(this.theme);              // another colour set's tones for what is drawn in the navy family
    if (tones) body = body.replace(/#[0-9a-fA-F]{6}\b/g, m => tones[m.toUpperCase()] || m);   // every colour in the slides, by its value
    // The page's title is the PDF's title: a blind edition's leaves out what the table covers and says it is the blind edition
    const title = BL.on ? BL.title(this.title, this.lang === "en" ? "en" : "ko") : this.title;
    const html = `<!doctype html><html lang="${this.lang}"><head><meta charset="utf-8"><title>${esc(title)}</title>` +
      `<style>${css}</style><script>if (location.search.indexOf("prose") >= 0) document.documentElement.classList.add("prose-only")</script>` +
      `</head><body>${body}<pre id="probe-out"></pre><script>window.GLYPHS = ${JSON.stringify(glyphsOf(body))};</script>${BL.on ? `<script>${BLIND_JS}</script>` : ""}<script>${PROBE}</script></body></html>`;
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, html);
    return n;
  }
}

// Measured in the browser, slide by slide, once the fonts and pictures have loaded.
const PROBE = String.raw`
(async () => {
  await document.fonts.ready;
  await Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; })));
  const name = e => e.tagName.toLowerCase() + (e.className && typeof e.className === "string" ? "." + e.className.trim().split(/\s+/).join(".") : "");
  const txt = e => (e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40);
  // The lowest y where text or a picture is actually drawn
  const inkBottom = el => {
    let b = -1e9;
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let t = w.nextNode(); t; t = w.nextNode()) {
      if (!t.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(t);
      for (const r of rg.getClientRects()) if (r.height) b = Math.max(b, r.bottom);
    }
    el.querySelectorAll("img, svg, table").forEach(x => { const r = shown(x); if (r) b = Math.max(b, r.bottom); });
    return b;
  };
  // The area a picture really covers under object-fit: contain
  const shown = x => {
    const r = x.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    if (x.tagName === "svg" && x.viewBox && x.viewBox.baseVal && x.viewBox.baseVal.width) {
      const vb = x.viewBox.baseVal, k = Math.min(r.width / vb.width, r.height / vb.height);
      const w = vb.width * k, hh = vb.height * k;
      return { left: r.left + (r.width - w) / 2, top: r.top + (r.height - hh) / 2, width: w, height: hh, bottom: r.top + (r.height + hh) / 2, right: r.left + (r.width + w) / 2 };
    }
    if (x.tagName !== "IMG" || !x.naturalWidth) return r;
    const s = Math.min(r.width / x.naturalWidth, r.height / x.naturalHeight);
    const w = x.naturalWidth * s, hh = x.naturalHeight * s;
    return { left: r.left + (r.width - w) / 2, top: r.top + (r.height - hh) / 2, width: w, height: hh, bottom: r.top + (r.height + hh) / 2, right: r.left + (r.width + w) / 2 };
  };
  const out = { slides: [] };
  document.querySelectorAll(".slide").forEach((s, si) => {
    // The covered-text check below (elementFromPoint) only sees points on screen, so each slide is brought on screen before it is measured.
    // All rectangles depend on this position, so nothing scrolls again while one slide is being measured
    s.scrollIntoView();
    const R = s.getBoundingClientRect();
    const foot = s.querySelector(".foot");
    const limit = foot ? foot.getBoundingClientRect().top - 4 : R.bottom - 30;
    const rec = { n: si + 1, company: s.dataset.company, part: s.dataset.part, kind: s.dataset.kind,
                  title: txt(s.querySelector(".sec h1") || s), issues: [], imgs: [], gaps: [] };
    s.querySelectorAll("*").forEach(e => {
      // The left guide rail is a background that runs the full slide height, so it is not footer intrusion (deck_structure.js places its tabs)
      if (e.closest(".foot, .rail") || e.id === "probe-out") return;
      // A chapter divider's left and right panels are backgrounds painted to the slide edge. The text and pictures inside them are still measured
      if (e.matches(".chapter .cl, .chapter .cr")) return;
      const r = e.getBoundingClientRect();
      if (!r.width && !r.height) return;
      if (r.left < R.left - 0.5 || r.right > R.right + 0.5 || r.top < R.top - 0.5 || r.bottom > R.bottom + 0.5)
        rec.issues.push("outside the slide: " + name(e) + " '" + txt(e) + "'");
      else if (r.bottom > limit + 0.5 && !e.closest(".cover .top"))
        rec.issues.push("into the footer area: " + name(e) + " '" + txt(e) + "' (" + Math.round(r.bottom - limit) + "px)");
    });
    s.querySelectorAll(".card, .hcard, .hcard .bd, .fig .frame, .body > *, .stack > *, .body, .rest, .plist, .toc2, .pcover .main > *, .pcover .blk, .chapter .cl, .chapter .cr").forEach(e => {
      if (e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1)
        rec.issues.push("overflows its box: " + name(e) + " '" + txt(e) + "' (" + (e.scrollHeight - e.clientHeight) + "px)");
    });
    // Overlapping and covered HTML text. The overflow check measures named boxes and the figure checks do not see HTML text, so a
    // list that runs out of its box and under a picture would pass both. Adding box names would only move the problem to the next
    // new box, so collect a rectangle for each text line, then check whether they overlap and whether another element sits on top of them
    const lines = [];
    const tw2 = document.createTreeWalker(s, NodeFilter.SHOW_TEXT);
    for (let t = tw2.nextNode(); t; t = tw2.nextNode()) {
      const p = t.parentElement;
      if (!t.textContent.trim() || !p || p.closest("svg, .foot, .rail, #probe-out")) continue;
      const rg = document.createRange(); rg.selectNodeContents(t);
      for (const r of rg.getClientRects()) if (r.width > 1 && r.height > 1) lines.push({ p, r, t: t.textContent.trim().replace(/\s+/g, " ").slice(0, 24) });
    }
    // A yellow highlight that breaks across two lines
    s.querySelectorAll("mark").forEach(m => {
      if (m.closest("svg, .foot, .rail")) return;
      rec.marks = (rec.marks || 0) + 1;
      (rec.markText = rec.markText || []).push((m.textContent || "").trim().replace(/\s+/g, " "));   // kept for checks on highlight length and names
      const tops = [];
      for (const r of m.getClientRects()) if (r.width > 1 && r.height > 1 && !tops.some(t => Math.abs(t - r.top) < r.height * 0.5)) tops.push(r.top);
      if (tops.length > 1) rec.issues.push("highlight breaks across lines: '" + txt(m) + "'");
    });
    for (let i = 0; i < lines.length; i++) for (let j = i + 1; j < lines.length; j++) {
      const a = lines[i], c = lines[j];
      if (a.p === c.p) continue;
      const ix = Math.min(a.r.right, c.r.right) - Math.max(a.r.left, c.r.left), iy = Math.min(a.r.bottom, c.r.bottom) - Math.max(a.r.top, c.r.top);
      if (ix > 2 && iy > Math.min(a.r.height, c.r.height) * 0.3) rec.issues.push("text overlap: '" + a.t + "' / '" + c.t + "'");
    }
    lines.forEach(l => {
      const x = l.r.left + Math.min(l.r.width / 2, 12), y = (l.r.top + l.r.bottom) / 2;
      const top = document.elementFromPoint(x, y);
      if (top && !l.p.contains(top) && !top.contains(l.p)) rec.issues.push("text covered: '" + l.t + "' under " + name(top));
    });
    // Text that must stay on one line: title lines, ledes, figure captions, and project names on chapter dividers and in the contents.
    // On two lines, a lede or caption shrinks the picture and a name leaves its last word alone on the next line. This is easy to miss by eye.
    // Lines are counted by grouping text rectangles that overlap vertically (a caption mixing a bold head and grey body still counts as one)
    const lineCount = (el, direct) => {
      const nodes = [];
      // direct looks only at the name itself. It skips the blocks beside it: subtitle (.tg), role line (.rc), period (.per), contents note (em).
      // span.nw wraps a hyphenated word and is part of the name, so it counts
      const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let t = w.nextNode(); t; t = w.nextNode()) if (!direct || !t.parentElement.closest(".tg, .rc, .per, em, .pg")) nodes.push(t);
      const rs = [];
      nodes.forEach(t => {
        if (!t.textContent.trim()) return;
        const rg = document.createRange(); rg.selectNodeContents(t);
        for (const r of rg.getClientRects()) if (r.width > 1 && r.height > 1) rs.push({ top: r.top, bottom: r.bottom });
      });
      rs.sort((a, b) => a.top - b.top);
      const ls = [];
      rs.forEach(r => {
        const l = ls.find(l => Math.min(l.bottom, r.bottom) - Math.max(l.top, r.top) > Math.min(l.bottom - l.top, r.bottom - r.top) * 0.5);
        if (l) { l.top = Math.min(l.top, r.top); l.bottom = Math.max(l.bottom, r.bottom); } else ls.push({ ...r });
      });
      return ls.length;
    };
    rec.oneLine = 0;
    [[".sec h1", false], ["p.lede", false], ["figcaption", false], [".plist .p > .t", true], [".toc2 .it > .t", true]].forEach(([sel, direct]) =>
      s.querySelectorAll(sel).forEach(e => {
        rec.oneLine++;
        const n = lineCount(e, direct);
        if (n > 1) rec.issues.push("more than one line: " + name(e) + " '" + txt(e) + "' (" + n + " lines)");
      }));
    // One-word last line: the last line of a card or result text holds a single word.
    // Collect the left and right ends of the text pieces on each line, then compare the last line's width with the box width
    rec.orphanChecked = 0;
    s.querySelectorAll(".card p, .card li, .hcard .v, .quote p").forEach(e => {
      const rs = [];
      const tw = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
      for (let t = tw.nextNode(); t; t = tw.nextNode()) {
        if (!t.textContent.trim()) continue;
        const rg = document.createRange(); rg.selectNodeContents(t);
        for (const r of rg.getClientRects()) if (r.width > 1 && r.height > 1) rs.push(r);
      }
      if (!rs.length) return;
      rec.orphanChecked++;
      rs.sort((a, b) => a.top - b.top);
      const lines = [];
      rs.forEach(r => { const L = lines.find(l => Math.abs(l.top - r.top) < 4); if (L) { L.l = Math.min(L.l, r.left); L.r = Math.max(L.r, r.right); } else lines.push({ top: r.top, l: r.left, r: r.right }); });
      if (lines.length < 2) return;
      const last = lines[lines.length - 1], W = e.getBoundingClientRect().width;
      if (last.r - last.l < 0.15 * W) rec.issues.push("one-word last line: " + name(e) + " '" + (e.textContent || "").trim().slice(-16) + "' last line width " + Math.round((last.r - last.l) / W * 100) + "%");
    });
    s.querySelectorAll("img").forEach(i => {
      if (!i.naturalWidth) { rec.issues.push("picture not readable: " + i.getAttribute("src")); return; }
      const r = shown(i);
      const ppi = i.naturalWidth / (r.width / 96);
      rec.imgs.push({ src: i.getAttribute("src"), natural: [i.naturalWidth, i.naturalHeight], shown: [Math.round(r.width), Math.round(r.height)], ppi: Math.round(ppi) });
    });
    // Text in a figure: if it is longer than the width set when it was drawn (data-maxw, figure units), it overflows its box
    s.querySelectorAll("svg text[data-maxw]").forEach(t => {
      const len = t.getComputedTextLength(), mx = +t.getAttribute("data-maxw");
      if (len > mx + 0.5) rec.issues.push("figure text overflows its box: '" + t.textContent.slice(0, 30) + "' (" + Math.round(len - mx) + ")");
    });
    const on = s.querySelector(".rail .seg.on"), here = s.querySelector(".rail .here");
    rec.rail = on ? { on: on.dataset.name, tabs: s.querySelectorAll(".rail .seg").length, here: here ? Math.round(here.getBoundingClientRect().top - R.top) : null } : null;
    // The card number circle (.mkc) is also an svg, but it is not a figure
    rec.figures = s.querySelectorAll(".fig, .body svg:not([data-icon]):not(.mkc), .rest svg:not([data-icon]):not(.mkc)").length;
    // Layout defects inside figures.
    // The checks above see only HTML elements, so they miss clipping and overlap inside an SVG. Each element's screen rectangle is converted to figure units
    rec.svg = [];
    s.querySelectorAll(".fig svg, .body svg:not([data-icon]), .rest svg:not([data-icon])").forEach((svg, fi) => {
      const vb = svg.viewBox && svg.viewBox.baseVal;
      if (!vb || !vb.width) return;
      const sh = shown(svg);
      if (!sh) return;
      const k = sh.width / vb.width;
      const U = r => ({ x0: (r.left - sh.left) / k, y0: (r.top - sh.top) / k, x1: (r.right - sh.left) / k, y1: (r.bottom - sh.top) / k });
      const area = r => Math.max(0, r.x1 - r.x0) * Math.max(0, r.y1 - r.y0);
      const inter = (a, c) => Math.max(0, Math.min(a.x1, c.x1) - Math.max(a.x0, c.x0)) * Math.max(0, Math.min(a.y1, c.y1) - Math.max(a.y0, c.y0));
      const inside = (a, c, t) => a.x0 >= c.x0 - t && a.y0 >= c.y0 - t && a.x1 <= c.x1 + t && a.y1 <= c.y1 + t;
      const hasPt = (r, x, y) => x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
      const fmt = r => "(" + [r.x0, r.y0, r.x1, r.y1].map(v => Math.round(v)).join(",") + ")";
      const cap = svg.closest(".fig") && svg.closest(".fig").querySelector("figcaption b");
      const fig = cap ? cap.textContent.trim() : "figure " + (fi + 1);
      const add = (kind, msg) => rec.svg.push({ fig, kind, msg });
      // Shapes inside icons (data-icon) and decoration (data-deco, such as paper stacked with shadows) are not boxes
      const els = [...svg.querySelectorAll("text, rect, circle, ellipse, line, path, polygon")].filter(e => !e.closest("defs, marker, [data-icon], [data-deco]"));
      const boxes = els.map(e => ({ e, t: e.tagName.toLowerCase(), r: U(e.getBoundingClientRect()) }));
      const tx = b => "'" + b.e.textContent.trim().slice(0, 22) + "'";
      boxes.forEach(b => {
        if (b.r.x0 < -0.6 || b.r.y0 < -0.6 || b.r.x1 > vb.width + 0.6 || b.r.y1 > vb.height + 0.6)
          add("clipped", (b.t === "text" ? tx(b) : b.t) + " " + fmt(b.r) + " figure " + vb.width + "x" + vb.height);
      });
      const texts = boxes.filter(b => b.t === "text" && b.e.textContent.trim() && area(b.r) > 0);
      // A shape with no fill (a ring, a dashed frame) is a line, not a box that holds things
      const shapes = boxes.filter(b => (b.t === "rect" || b.t === "circle" || b.t === "ellipse") && getComputedStyle(b.e).fill !== "none" && area(b.r) > 1);
      for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
        const a = texts[i].r, c = texts[j].r, ov = inter(a, c);
        if (ov > 4 && ov > 0.12 * Math.min(area(a), area(c))) add("text overlap", tx(texts[i]) + " / " + tx(texts[j]));
      }
      // Text that only touches (overlap under 4) still reads as stuck together. On the same line (more than half vertical overlap), flag a gap under 3.
      // A box title and a dashed note can run together like one word while the overlap check passes
      for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
        const a = texts[i].r, c = texts[j].r;
        const vy = Math.min(a.y1, c.y1) - Math.max(a.y0, c.y0), hmin = Math.min(a.y1 - a.y0, c.y1 - c.y0);
        if (vy < 0.5 * hmin) continue;
        // A one-character symbol such as the required mark (*) belongs right after the name
        if ([texts[i], texts[j]].some(b => /^[^A-Za-z0-9가-힣]$/.test(b.e.textContent.trim()))) continue;
        const gap = Math.max(c.x0 - a.x1, a.x0 - c.x1), ov = inter(a, c);
        // A slight overlap (under the overlap check's 12% threshold) still collides on the same line. Large overlaps were caught above
        if (gap < 3 && !(ov > 4 && ov > 0.12 * Math.min(area(a), area(c)))) add("text touching", tx(texts[i]) + " / " + tx(texts[j]) + " gap " + gap.toFixed(1));
      }
      texts.forEach(tb => {
        const cx = (tb.r.x0 + tb.r.x1) / 2, cy = (tb.r.y0 + tb.r.y1) / 2;
        const cont = shapes.filter(sb => hasPt(sb.r, cx, cy)).sort((p, q) => area(p.r) - area(q.r))[0];
        if (cont) {
          const o = Math.max(cont.r.x0 - tb.r.x0, tb.r.x1 - cont.r.x1, cont.r.y0 - tb.r.y0, tb.r.y1 - cont.r.y1);
          if (o > 1) add("box overflow", tx(tb) + " over by " + o.toFixed(1));
        }
        shapes.forEach(sb => {
          if (hasPt(sb.r, cx, cy)) return;
          if (cont && (inside(sb.r, cont.r, 0.5) || inside(cont.r, sb.r, 0.5)) && !inside(sb.r, cont.r, 0.5)) return;
          const ov = inter(tb.r, sb.r);
          if (ov > 3 && ov > 0.15 * area(tb.r)) add("box intrusion", tx(tb) + " lies across " + sb.t + fmt(sb.r));
          // A slight overlap: the end of the text runs a few pixels into a neighbouring bar or box. The threshold above (15% of the text area)
          // misses a long label that runs 3 to 10px into the start of a bar
          // A shape painted the same color inside the box holding the text (a bar filling a header band's corner) is part of that box, so it is skipped
          else if (ov > 6 && !(cont && inside(sb.r, cont.r, 0.5) && getComputedStyle(sb.e).fill === getComputedStyle(cont.e).fill)) add("text over edge", tx(tb) + " overlaps " + sb.t + fmt(sb.r) + " by " + ov.toFixed(0));
        });
        const fs = parseFloat(getComputedStyle(tb.e).fontSize) * k;
        if (fs < 8.6) add("small text", tx(tb) + " " + fs.toFixed(1) + "px");
      });
      const rects = shapes.filter(b => b.t === "rect");
      for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i].r, c = rects[j].r, ov = inter(a, c);
        if (ov > 4 && ov > 0.04 * Math.min(area(a), area(c)) && !inside(a, c, 0.6) && !inside(c, a, 0.6)) add("box overlap", "rect" + fmt(a) + " / rect" + fmt(c));
      }
      // Tight margin: an inner box almost touches the border of the box around it.
      // Header bands that fit exactly (0 on left and right, or top and bottom) and left accent bars are intended shapes, so they are skipped
      for (const a of rects) {
        const c = rects.filter(q => q !== a && inside(a.r, q.r, 0.5) && area(q.r) > area(a.r) * 1.05).sort((p, q) => area(p.r) - area(q.r))[0];
        if (!c) continue;
        const g = [a.r.x0 - c.r.x0, c.r.x1 - a.r.x1, a.r.y0 - c.r.y0, c.r.y1 - a.r.y1];
        // Two or more sides flush with the border mean a panel filling its box (header band, window menu panel, step box header). A narrow one is a left accent bar.
        // One flush side (0 to 1.6), or no flush side but within 3.5, looks like touching the border
        const flushN = g.filter(v => Math.abs(v) <= 1.6).length;
        if (flushN >= 2 || (flushN >= 1 && a.r.x1 - a.r.x0 <= 6)) continue;
        const tight = g.filter(v => v > -0.5 && v < 3.5);
        if (tight.length) add("tight margin", "rect" + fmt(a.r) + " inside rect" + fmt(c.r) + " has a gap of " + Math.min(...tight).toFixed(1));
      }
      // Text margin: text sits against the left or right border of the box holding it
      texts.forEach(tb => {
        const cx = (tb.r.x0 + tb.r.x1) / 2, cy = (tb.r.y0 + tb.r.y1) / 2;
        const cont = shapes.filter(sb => sb.t === "rect" && hasPt(sb.r, cx, cy)).sort((p, q) => area(p.r) - area(q.r))[0];
        if (!cont) return;
        const gx = Math.min(tb.r.x0 - cont.r.x0, cont.r.x1 - tb.r.x1);
        if (gx > -0.5 && gx < 2.5) add("tight text margin", tx(tb) + " left or right " + gx.toFixed(1));
      });

      // Arrow placement.
      // The checks above do not see lines and arrowheads. For each line with a marker, find the tip and the tail in figure units and measure
      // whether it touches the border it should reach, enters the box at its center, tilts slightly off the axis, or covers text.
      // A box is a filled or outlined rectangle or circle. A rectangle holding the whole arrow (a group panel) is not a box to reach
      const ptU = (el, p) => { const q = new DOMPoint(p.x, p.y).matrixTransform(el.getScreenCTM()); return { x: (q.x - sh.left) / k, y: (q.y - sh.top) / k }; };
      const skipA = e => e.closest("defs, marker, [data-icon], [data-deco]");
      // A filled closed path (the face of a 3D block, a bent band) is also a box. Circles and ellipses are measured as curves (r.ell). With bounding boxes alone,
      // an arrow 16 away from a ring counts as touching, and a tail through the side of a path-drawn block goes unnoticed
      const closedPath = e => e.tagName.toLowerCase() === "path" && /[Zz]\s*$/.test(e.getAttribute("d") || "") && getComputedStyle(e).fill !== "none";
      const boxA = [...svg.querySelectorAll("rect, circle, ellipse, polygon, image, path")].filter(e => !skipA(e))
        .filter(e => { const tg = e.tagName.toLowerCase(); if (tg === "image") return true; if (tg === "path") return closedPath(e); const cs = getComputedStyle(e); return cs.fill !== "none" || (cs.stroke !== "none" && parseFloat(cs.strokeWidth) > 0); })
        .map(e => { const r = U(e.getBoundingClientRect()); if (/^(circle|ellipse)$/i.test(e.tagName)) r.ell = { cx: (r.x0 + r.x1) / 2, cy: (r.y0 + r.y1) / 2, rx: (r.x1 - r.x0) / 2, ry: (r.y1 - r.y0) / 2 }; return { e, r }; })
        .filter(b => area(b.r) > 4);
      // Icons are also arrow targets (an arrow can join two icons). They are measured by their drawn extent
      svg.querySelectorAll("[data-icon]").forEach(g => { if (!g.parentElement.closest("[data-icon]")) boxA.push({ e: g, r: U(g.getBoundingClientRect()) }); });
      const strokes = [...svg.querySelectorAll("path, line, polyline")].filter(e => !skipA(e) && getComputedStyle(e).stroke !== "none");
      const smp = new Map();
      const samplesOf = e => {
        if (smp.has(e)) return smp.get(e);
        const L = e.getTotalLength(), pts = [];
        for (let d = 0; d < L; d += 2) pts.push(ptU(e, e.getPointAtLength(d)));
        pts.push(ptU(e, e.getPointAtLength(L)));
        smp.set(e, pts); return pts;
      };
      // Whether a point is inside the shape grown by t (shrunk if negative). An ellipse grows its radii by t
      const inR = (r, p, t = 0) => {
        if (r.ell) { const ax = r.ell.rx + t, ay = r.ell.ry + t; return ax > 0 && ay > 0 && ((p.x - r.ell.cx) / ax) ** 2 + ((p.y - r.ell.cy) / ay) ** 2 < 1; }
        return p.x > r.x0 - t && p.x < r.x1 + t && p.y > r.y0 - t && p.y < r.y1 + t;
      };
      // From point p in direction d, the distances where the ray enters and leaves shape r (slab test for rectangles, quadratic for ellipses)
      const slab = (r, p, d) => {
        if (r.ell) {
          const E = r.ell, ox = (p.x - E.cx) / E.rx, oy = (p.y - E.cy) / E.ry, dx = d.x / E.rx, dy = d.y / E.ry;
          const A = dx * dx + dy * dy, B = 2 * (ox * dx + oy * dy), Cc = ox * ox + oy * oy - 1, D = B * B - 4 * A * Cc;
          if (A < 1e-12 || D < 0) return null;
          return [(-B - Math.sqrt(D)) / (2 * A), (-B + Math.sqrt(D)) / (2 * A)];
        }
        let t0 = -Infinity, t1 = Infinity;
        for (const [pp, dd, lo, hi] of [[p.x, d.x, r.x0, r.x1], [p.y, d.y, r.y0, r.y1]]) {
          if (Math.abs(dd) < 1e-9) { if (pp < lo || pp > hi) return null; continue; }
          const a = (lo - pp) / dd, b = (hi - pp) / dd;
          t0 = Math.max(t0, Math.min(a, b)); t1 = Math.min(t1, Math.max(a, b));
        }
        return t0 <= t1 ? [t0, t1] : null;
      };
      const unit = (a, b) => { const dx = b.x - a.x, dy = b.y - a.y, n = Math.hypot(dx, dy) || 1; return { x: dx / n, y: dy / n }; };
      const tilt = d => Math.atan2(Math.min(Math.abs(d.x), Math.abs(d.y)), Math.max(Math.abs(d.x), Math.abs(d.y))) * 180 / Math.PI;
      const P1 = p => "(" + Math.round(p.x) + "," + Math.round(p.y) + ")";
      const hits = [], outs = [], tipsAll = [];
      // Which side of the box (L, R, T, B) an arrowhead or tail sits on. d points from that end toward the box
      const sideOf = d => Math.abs(d.x) >= Math.abs(d.y) ? (d.x > 0 ? "L" : "R") : (d.y > 0 ? "T" : "B");
      svg.querySelectorAll("[marker-end], [marker-start]").forEach(el => {
        if (skipA(el)) return;
        const L = el.getTotalLength();
        if (L < 3) return;
        rec.arrows = (rec.arrows || 0) + 1;
        // Keep each arrow's position on the slide (CSS px), so each arrow can be cropped from the rendered PDF for a close look
        {
          const scr = p => { const q = new DOMPoint(p.x, p.y).matrixTransform(el.getScreenCTM()); return [+(q.x - R.left).toFixed(1), +(q.y - R.top).toFixed(1)]; };
          const bb = el.getBoundingClientRect();
          (rec.arrowList = rec.arrowList || []).push({ fig, d: (el.getAttribute("d") || "").slice(0, 60), a: scr(el.getPointAtLength(0)), b: scr(el.getPointAtLength(L)),
            box: [bb.left - R.left, bb.top - R.top, bb.right - R.left, bb.bottom - R.top].map(v => +v.toFixed(1)),
            end: !!el.getAttribute("marker-end"), start: !!el.getAttribute("marker-start"), dash: getComputedStyle(el).strokeDasharray,
            sw: +(parseFloat(getComputedStyle(el).strokeWidth) * k).toFixed(2), len: +(L * k).toFixed(1), free: el.hasAttribute("data-free") });
        }
        // data-free: a display-only arrow that touches no box (order, a conversion between charts). Touch, tail, tilt and center are not measured
        const free = el.hasAttribute("data-free");
        const sw = parseFloat(getComputedStyle(el).strokeWidth) || 1;
        const pA = ptU(el, el.getPointAtLength(0)), pB = ptU(el, el.getPointAtLength(L));
        // A rectangle holding the whole arrow (both ends) is a group panel
        const outer = boxA.filter(b => inR(b.r, pA, 1) && inR(b.r, pB, 1));
        const cand = boxA.filter(b => !outer.includes(b));
        const ends = [];
        if (el.getAttribute("marker-end")) ends.push({ tip: pB, pre: ptU(el, el.getPointAtLength(Math.max(0, L - 3))), tail: pA, tailNext: ptU(el, el.getPointAtLength(Math.min(L, 3))) });
        if (el.getAttribute("marker-start")) ends.push({ tip: pA, pre: ptU(el, el.getPointAtLength(Math.min(L, 3))), tail: pB, tailNext: ptU(el, el.getPointAtLength(Math.max(0, L - 3))) });
        const name = "'" + (el.getAttribute("d") || [el.getAttribute("x1"), el.getAttribute("y1"), el.getAttribute("x2"), el.getAttribute("y2")].join(",")).slice(0, 34) + "'";
        // Arrow with no shaft: without the heads (marker width x 0.75 x line width), under 3px of line remains, so only the head and tail end show
        const headOf = at => { const m2 = (el.getAttribute(at) || "").match(/#([^)]+)\)/); const mk = m2 && svg.querySelector("marker#" + CSS.escape(m2[1])); return mk ? 0.75 * parseFloat(mk.getAttribute("markerWidth") || "7") * sw : 0; };
        const shaft = (L - headOf("marker-end") - headOf("marker-start")) * k;
        if (shaft < 3) add("arrow without shaft", name + " shaft " + shaft.toFixed(1) + "px");
        if (el.getAttribute("marker-end")) tipsAll.push({ el, p: pB, name });
        if (el.getAttribute("marker-start")) tipsAll.push({ el, p: pA, name });
        // Through a shape: the shaft passes through a filled shape it does not connect (6 at each end are skipped). Panels holding other shapes and bars
        // under 6 wide (a panel's left band) may be crossed. No other check catches an arrow running through an unrelated box
        {
          const leaf = b => !b.e.matches("[data-icon]") && getComputedStyle(b.e).fill !== "none" && Math.min(b.r.x1 - b.r.x0, b.r.y1 - b.r.y0) > 6 &&
            !boxA.some(o => o !== b && !o.e.matches("[data-icon]") && area(o.r) < area(b.r) * 0.9 && o.r.x0 >= b.r.x0 - 0.5 && o.r.y0 >= b.r.y0 - 0.5 && o.r.x1 <= b.r.x1 + 0.5 && o.r.y1 <= b.r.y1 + 0.5);
          const own = b => inR(b.r, pA, 2) || inR(b.r, pB, 2);
          // A label on the line (a pill drawn after the line, centered on it) is not a crossing. data-through marks a line that passes through on purpose
          const onLabel = b => (el.compareDocumentPosition(b.e) & Node.DOCUMENT_POSITION_FOLLOWING) && samplesOf(el).some(q => Math.hypot(q.x - (b.r.x0 + b.r.x1) / 2, q.y - (b.r.y0 + b.r.y1) / 2) <= 2.5);
          const pts2 = samplesOf(el).filter(q => Math.hypot(q.x - pA.x, q.y - pA.y) > 6 && Math.hypot(q.x - pB.x, q.y - pB.y) > 6);
          const crossed = new Set();
          if (!el.hasAttribute("data-through")) for (const q of pts2) for (const b of boxA) if (!crossed.has(b) && !own(b) && inR(b.r, q, -1) && leaf(b) && !onLabel(b)) crossed.add(b);
          crossed.forEach(b => add("arrow through shape", name + " passes through " + touch_name(b)));
        }
        // Arrows crossing bands and lines.
        // The check above lets bars under 6 wide (a panel's left band) pass on purpose and does not measure crossings with other lines. An arrow can cut
        // through a panel's vertical band, or a branch can cross another stem. Flag a shaft (6 at each end skipped) that passes through a thin filled
        // bar or meets another line within 1.2. A tail or tip on that line (a branch leaving a stem) is a connection
        if (!el.hasAttribute("data-through") && !free) {
          const thin = boxA.filter(b => !b.e.matches("[data-icon]") && getComputedStyle(b.e).fill !== "none" && Math.min(b.r.x1 - b.r.x0, b.r.y1 - b.r.y0) <= 6 &&
            Math.max(b.r.x1 - b.r.x0, b.r.y1 - b.r.y0) > 12 && !inR(b.r, pA, 2) && !inR(b.r, pB, 2));
          const mid = samplesOf(el).filter(q => Math.hypot(q.x - pA.x, q.y - pA.y) > 6 && Math.hypot(q.x - pB.x, q.y - pB.y) > 6);
          const barHit = thin.find(b => mid.some(q => inR(b.r, q, -0.3)));
          if (barHit) add("arrow across band", name + " crosses " + touch_name(barHit));
          const near = (o, p) => samplesOf(o).some(q => Math.hypot(q.x - p.x, q.y - p.y) <= 2.5);
          // If another line ends on this arrow (a branch leaving it), that is a connection, not a crossing
          const endsOn = o => { const L2 = o.getTotalLength(); return [0, L2].some(d0 => { const q = ptU(o, o.getPointAtLength(d0)); return samplesOf(el).some(m2 => Math.hypot(q.x - m2.x, q.y - m2.y) <= 2.5); }); };
          const other = strokes.find(o => o !== el && !o.closest("[data-icon]") && !near(o, pA) && !near(o, pB) && !endsOn(o) &&
            samplesOf(o).some(q => mid.some(m2 => Math.hypot(q.x - m2.x, q.y - m2.y) <= 1.2)));
          if (other) add("arrow across line", name + " crosses '" + (other.getAttribute("d") || [other.getAttribute("x1"), other.getAttribute("y1"), other.getAttribute("x2"), other.getAttribute("y2")].join(",")).slice(0, 30) + "'");
        }
        ends.forEach(({ tip, pre, tail, tailNext }) => {
          const d = unit(pre, tip);
          // Arrowhead tip: whether it touches a box border (how deep it went in, how far it fell short)
          let touch = null, deep = null, near = null;
          for (const b of cand) {
            if (inR(b.r, tip)) {
              const s2 = slab(b.r, tip, { x: -d.x, y: -d.y });
              const depth = s2 ? s2[1] : 0;
              if (depth <= 3) { if (!touch) touch = { b, gap: -depth }; }
              else if (!deep || area(b.r) < area(deep.b.r)) deep = { b, depth };
            } else {
              const s2 = slab(b.r, tip, d);
              if (s2 && s2[0] >= 0 && s2[0] <= 40 && (!near || s2[0] < near.gap)) near = { b, gap: s2[0] };
            }
          }
          // Touching: the line end is within 3 before the border or at most 3 past it (the head's tip goes about 1 further than the line end)
          if (!touch && near && near.gap <= 3) touch = near;
          if (!free) {
            if (touch) hits.push({ el, tip, d, b: touch.b });
            else if (deep) add("arrowhead too deep", name + " tip " + P1(tip) + " is inside " + touch_name(deep.b) + " by " + deep.depth.toFixed(1));
            else if (near) add("arrow falls short", name + " tip " + P1(tip) + " to " + touch_name(near.b) + " gap " + near.gap.toFixed(1));
            else add("arrow ends in no box", name + " tip " + P1(tip));
            // An arrow slightly off the axis comes from two boxes at slightly different heights
            const tl = tilt(d);
            if (tl > 0.4 && tl < 12) add("arrow tilted", name + " tip " + P1(tip) + " " + tl.toFixed(1) + "°");
          }
          // Tail: it must start at a box border (within 3) or branch off another line
          if (!free && (!el.getAttribute("marker-start") || !el.getAttribute("marker-end"))) {
            const src = cand.filter(b => b.r.ell ? Math.abs(Math.hypot((tail.x - b.r.ell.cx) / b.r.ell.rx, (tail.y - b.r.ell.cy) / b.r.ell.ry) - 1) * Math.min(b.r.ell.rx, b.r.ell.ry) <= 3
              : inR(b.r, tail, 3) && !inR(b.r, tail, -3)).sort((p, q) => area(p.r) - area(q.r))[0];
            const onLine = !src && strokes.some(o => o !== el && samplesOf(o).some(q => Math.hypot(q.x - tail.x, q.y - tail.y) <= 2.2));
            const inBox = cand.filter(b => inR(b.r, tail, -3));
            if (src) outs.push({ el, tail, d: unit(tail, tailNext), b: src });
            else if (!onLine) add(inBox.length ? "tail inside box" : "tail in empty space", name + " tail " + P1(tail));
          }
          // Text covered by an arrowhead (the head size follows the marker width)
          const hs = (headOf(el.getAttribute("marker-end") ? "marker-end" : "marker-start") / (0.75 * sw)) / 7;
          const n = { x: -d.y * hs, y: d.x * hs }, head = [
            { x: tip.x + d.x * 0.7 * sw, y: tip.y + d.y * 0.7 * sw },
            { x: tip.x - d.x * 6.3 * sw + n.x * 3.5 * sw, y: tip.y - d.y * 6.3 * sw + n.y * 3.5 * sw },
            { x: tip.x - d.x * 6.3 * sw - n.x * 3.5 * sw, y: tip.y - d.y * 6.3 * sw - n.y * 3.5 * sw }];
          const hb = { x0: Math.min(...head.map(q => q.x)), y0: Math.min(...head.map(q => q.y)), x1: Math.max(...head.map(q => q.x)), y1: Math.max(...head.map(q => q.y)) };
          texts.forEach(tb => { if (inter(hb, tb.r) > 4) add("arrowhead over text", name + " tip " + P1(tip) + " covers " + tx(tb)); });
        });
        // A line running through text (2 at each end are skipped). Text covered by a label on the line (an opaque pill drawn after the line) is skipped
        const pts = samplesOf(el).slice(1, -1);
        texts.forEach(tb => {
          const r = { x0: tb.r.x0 + 1, y0: tb.r.y0 + 1, x1: tb.r.x1 - 1, y1: tb.r.y1 - 1 };
          if (!pts.some(q => inR(r, q))) return;
          const c = { x: (tb.r.x0 + tb.r.x1) / 2, y: (tb.r.y0 + tb.r.y1) / 2 };
          const cover = boxA.find(b => b.e.tagName.toLowerCase() !== "image" && inR(b.r, c) && getComputedStyle(b.e).fill !== "none" &&
            (el.compareDocumentPosition(b.e) & Node.DOCUMENT_POSITION_FOLLOWING));
          if (!cover) add("arrow through text", name + " crosses " + tx(tb));
        });
      });
      function touch_name(b) { return b.e.tagName.toLowerCase() + fmt(b.r); }
      // Arrowheads on one spot: the tips of different arrows come within 10 of each other
      for (let i = 0; i < tipsAll.length; i++) for (let j = i + 1; j < tipsAll.length; j++) {
        const a2 = tipsAll[i], b2 = tipsAll[j];
        if (a2.el !== b2.el && Math.hypot(a2.p.x - b2.p.x, a2.p.y - b2.p.y) < 10) add("arrowheads overlap", a2.name + " and " + b2.name + " tips meet at " + P1(a2.p));
      }
      // Double line: horizontal or vertical runs of two different lines sit 0.4 to 4 apart and run side by side for more than 4 (bent lines drawn
      // separately for each branch can end up slightly off and look doubled). Only straight runs are checked
      {
        const segs = [];
        strokes.forEach(e => {
          const tg = e.tagName.toLowerCase(); let P = null;
          if (tg === "line") P = [[+e.getAttribute("x1"), +e.getAttribute("y1")], [+e.getAttribute("x2"), +e.getAttribute("y2")]];
          else if (tg === "path" && /^M[-\d.]+,[-\d.]+( L[-\d.]+,[-\d.]+)+$/.test(e.getAttribute("d") || "")) P = e.getAttribute("d").slice(1).split(" L").map(q => q.split(",").map(Number));
          // A line with more than six points is a chart series (two series running side by side for a moment is not a defect)
          if (!P || P.length > 6) return;
          const Q = P.map(([x, y]) => ptU(e, { x, y }));
          for (let i = 1; i < Q.length; i++) segs.push({ e, a: Q[i - 1], b: Q[i] });
        });
        for (let i = 0; i < segs.length; i++) for (let j = i + 1; j < segs.length; j++) {
          const s1 = segs[i], s2 = segs[j];
          if (s1.e === s2.e) continue;
          for (const ax of ["x", "y"]) {
            const o = ax === "x" ? "y" : "x";
            if (Math.abs(s1.a[ax] - s1.b[ax]) > 0.3 || Math.abs(s2.a[ax] - s2.b[ax]) > 0.3) continue;
            const off = Math.abs(s1.a[ax] - s2.a[ax]);
            const ov = Math.min(Math.max(s1.a[o], s1.b[o]), Math.max(s2.a[o], s2.b[o])) - Math.max(Math.min(s1.a[o], s1.b[o]), Math.min(s2.a[o], s2.b[o]));
            if (off > 0.4 && off <= 4 && ov > 4) add("double line", "two lines " + off.toFixed(1) + " apart run side by side for " + ov.toFixed(0) + " at " + P1(s1.a) + " to " + P1(s1.b));
          }
        }
      }
      // Box center: a single arrow on one side of a box (in or out) must sit at the middle of that side.
      // One in and one out sharing a side must face each other across the middle (their offsets sum to within 3). Three or more are not measured
      const ends2 = [...hits.map(h2 => ({ p: h2.tip, d: h2.d, b: h2.b, io: "in" })),
                     ...outs.map(o2 => ({ p: o2.tail, d: { x: -o2.d.x, y: -o2.d.y }, b: o2.b, io: "out" }))].filter(e2 => tilt(e2.d) <= 0.4);
      const offOf = e2 => { const r = e2.b.r, sd = sideOf(e2.d); return sd === "L" || sd === "R" ? e2.p.y - (r.y0 + r.y1) / 2 : e2.p.x - (r.x0 + r.x1) / 2; };
      const spanOk = e2 => { const r = e2.b.r, sd = sideOf(e2.d); return sd === "L" || sd === "R" ? r.y1 - r.y0 <= 80 : r.x1 - r.x0 <= 220; };
      ends2.forEach(e2 => {
        if (!spanOk(e2)) return;
        const same = ends2.filter(o => o.b === e2.b && sideOf(o.d) === sideOf(e2.d));
        const off = offOf(e2);
        if (same.length === 1 && Math.abs(off) > 3)
          add("arrow off center", (e2.io === "in" ? "tip " : "tail ") + P1(e2.p) + " is off the center of " + touch_name(e2.b) + " by " + off.toFixed(1));
        if (same.length === 2 && e2.io === "in" && same.some(o => o.io === "out")) {
          const o = same.find(o2 => o2.io === "out");
          if (Math.abs(off + offOf(o)) > 3) add("arrow off center", "two facing arrows " + P1(e2.p) + ", " + P1(o.p) + " are off the center of " + touch_name(e2.b) + " by " + off.toFixed(1) + ", " + offOf(o).toFixed(1));
        }
      });
      // Number badges. D.mark pairs a figure with a card and D.num is a step number (data-badge groups).
      // A badge half on a box corner or right against the border of its box passes every other check. Flag a badge that lies across another shape's border,
      // sits within 3 of the border of the shape holding it, sits within 2 of a shape outside it, covers text,
      // or has a line drawn after it passing over it (a line drawn earlier goes under the badge and does not show)
      svg.querySelectorAll("[data-badge]").forEach(g => {
        const br = U(g.getBoundingClientRect()), bk = g.getAttribute("data-badge");
        const c = { x: (br.x0 + br.x1) / 2, y: (br.y0 + br.y1) / 2 }, rad = (br.x1 - br.x0) / 2;
        const label = bk + " '" + g.textContent.trim() + "' " + P1(c);
        rec.badges = (rec.badges || 0) + 1;
        // The smallest shape holding the badge. A same-color piece with no border (a bar filling the lower corner of a rounded header band) does not stand
        // out from the background, so it cannot collide with the badge. With a border, a same-color shape is a visible box (a white box on a white panel),
        // and a badge on its corner must still be caught
        const home = boxA.filter(b => !b.e.closest("[data-badge]") && inside(br, b.r, 0)).sort((p, q) => area(p.r) - area(q.r))[0];
        const noEdge = e => { const cs = getComputedStyle(e); return cs.stroke === "none" || !(parseFloat(cs.strokeWidth) > 0); };
        const sameAsHome = b => home && b !== home && inter(b.r, home.r) > 0 && noEdge(b.e) && getComputedStyle(b.e).fill === getComputedStyle(home.e).fill;
        boxA.forEach(b => {
          if (b.e.closest("[data-badge]") || sameAsHome(b)) return;
          if (inter(br, b.r) <= 0) {
            const gap = Math.max(b.r.x0 - br.x1, br.x0 - b.r.x1, b.r.y0 - br.y1, br.y0 - b.r.y1);
            if (gap >= 0 && gap < 2) add("badge touching shape", label + " and " + touch_name(b) + " gap " + gap.toFixed(1));
            return;
          }
          if (inside(b.r, br, 0.5)) return;
          if (inside(br, b.r, 0)) {
            const m = Math.min(br.x0 - b.r.x0, b.r.x1 - br.x1, br.y0 - b.r.y0, b.r.y1 - br.y1);
            if (m < 3) add("badge against border", label + " to the inner border of " + touch_name(b) + ": " + m.toFixed(1));
            return;
          }
          add("badge across shape", label + " lies across the border of " + touch_name(b));
        });
        texts.forEach(tb => { if (!g.contains(tb.e) && inter(br, tb.r) > 1) add("badge over text", label + " covers " + tx(tb)); });
        strokes.forEach(e => {
          if (e.closest("[data-badge]") || !(g.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)) return;
          if (samplesOf(e).some(p => Math.hypot(p.x - c.x, p.y - c.y) < rad + 1)) add("line over badge", label + " crossed by " + e.tagName.toLowerCase());
        });
      });
      // Contrast between text and background (WCAG relative luminance). The smallest filled shape holding the text is the background, or white if
      // there is none. The minimum on screen is 3 for text of 18.5px or more and bold text of 14px or more, and 4.5 otherwise
      const rgbOf = v => { const m = (v || "").match(/[\d.]+/g); return m && m.length >= 3 ? m.slice(0, 3).map(Number) : null; };
      const lumOf = q => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(q[0]) + 0.7152 * f(q[1]) + 0.0722 * f(q[2]); };
      texts.forEach(tb => {
        const cx = (tb.r.x0 + tb.r.x1) / 2, cy = (tb.r.y0 + tb.r.y1) / 2;
        // Background candidates: filled rectangles and circles, filled polygons and closed paths (chevrons). Icons and picture files are not backgrounds
        const cont = boxA.filter(sb => !sb.e.closest("[data-icon]") && /^(rect|circle|ellipse|polygon|path)$/i.test(sb.e.tagName) && getComputedStyle(sb.e).fill !== "none"
          && hasPt(sb.r, cx, cy) && !tb.e.contains(sb.e)).sort((p, q) => area(p.r) - area(q.r))[0];
        const fg = rgbOf(getComputedStyle(tb.e).fill), bg = cont ? rgbOf(getComputedStyle(cont.e).fill) : [255, 255, 255];
        if (!fg || !bg) return;
        const a1 = lumOf(fg), a2 = lumOf(bg), ratio = (Math.max(a1, a2) + 0.05) / (Math.min(a1, a2) + 0.05);
        const cs = getComputedStyle(tb.e), fs = parseFloat(cs.fontSize) * k, bold = parseInt(cs.fontWeight) >= 600;
        const need = fs >= 18.5 || (bold && fs >= 14) ? 3 : 4.5;
        if (ratio < need) add("low contrast", tx(tb) + " " + ratio.toFixed(2) + ":1 (minimum " + need + ", text " + cs.fill + " background " + (cont ? getComputedStyle(cont.e).fill : "white") + ")");
      });
    });
    // Empty space under a box: the height left below the last text or picture in each body box
    s.querySelectorAll(".body > *, .card, .hcard .bd, .stack > *").forEach(e => {
      if (e.classList.contains("fig") || e.closest(".fig")) return;
      const r = e.getBoundingClientRect();
      const ib = inkBottom(e);
      if (ib > -1e8) rec.gaps.push({ el: name(e), text: txt(e), gap: Math.round(r.bottom - ib) });
    });
    // Empty space in a vertical stack. The right column uses space-between, so with few items
    // the spare height spreads between them. Box height, total item height and the gaps between items are kept for checks on that space
    rec.stacks = [];
    s.querySelectorAll(".body > .stack").forEach(st => {
      const kids = [...st.children].filter(e => e.getBoundingClientRect().height > 0), sr = st.getBoundingClientRect();
      const rs = kids.map(e => e.getBoundingClientRect());
      rec.stacks.push({ h: Math.round(sr.height), used: Math.round(rs.reduce((a, r) => a + r.height, 0)), n: kids.length,
                        between: rs.slice(1).map((r, i) => Math.round(r.top - rs[i].bottom)), text: txt(st).slice(0, 24) });
    });
    // Figure box: how much of the box the picture fills (the bands left by contain)
    s.querySelectorAll(".fig .frame").forEach(f => {
      const fb = f.getBoundingClientRect(), cs = getComputedStyle(f), pd = k => parseFloat(cs["padding" + k]) || 0;
      const fr = { width: fb.width - pd("Left") - pd("Right"), height: fb.height - pd("Top") - pd("Bottom") };
      const x = f.querySelector("img, svg");
      const r = x ? shown(x) : null;
      if (r) rec.gaps.push({ el: "frame", text: (x.getAttribute("src") || "svg").split("/").pop(), fill: +(r.width * r.height / (fr.width * fr.height)).toFixed(2),
                             frame: [Math.round(fr.width), Math.round(fr.height)],
                             canvas: x.viewBox && x.viewBox.baseVal ? [x.viewBox.baseVal.width, x.viewBox.baseVal.height] : null });
    });
    // Text fit inside boxes.
    // The checks above see only a glyph's em box, so they do not know where the strokes (ink) land inside it. A descender touching a label border,
    // a three-line paragraph past a box's lower border, or a two-line block 1 to 7px off center would all pass.
    // Ink comes from a table of glyph outline bounds (GLYPHS, taken with opentype at build time) and the baseline the browser set (the first glyph's start).
    // Against 300 and 600dpi rasters it matches within 0.1 to 0.2px. Limits (CSS px): ink within 1.5 of the box's inner border is touching, a block center
    // off by more than 0.6 is vertical misalignment (Latin descenders excluded), and a centered line off by more than 1.0 is horizontal misalignment
    // The number badge at the end of a card title (.mk) against the title's first line. A zero-height inline-block placed before the title gives the first
    // line's baseline, and the visible middle of Hangul and Latin capitals (0.36em above it, measured from Pretendard ink) is compared with the badge center.
    // The PDF is printed by another chromium run, so this brief DOM change does not reach it
    s.querySelectorAll(".card h3").forEach(h => {
      const mk = h.querySelector(".mk svg"), sp = h.querySelector("span");
      if (!mk || !sp) return;
      const b = mk.getBoundingClientRect(), z = document.createElement("span");
      z.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline";
      sp.insertBefore(z, sp.firstChild);
      const base = z.getBoundingClientRect().bottom;
      z.remove();
      const dy = (b.top + b.bottom) / 2 - (base - 0.36 * parseFloat(getComputedStyle(sp).fontSize));
      if (Math.abs(dy) > 1.5) rec.svg.push({ fig: "card number", kind: "card number height", msg: "'" + sp.textContent.trim().slice(0, 24) + "' first line and number badge differ in height by " + dy.toFixed(1) + "px" });
    });
    rec.boxtext = 0;
    if (window.GLYPHS) {
      const TOUCH = 1.5, OFF_V = 0.6, OFF_H = 1.0, DESC = new Set("gjpqy,;()[]{}/|_@$Q");
      const within = (b, r, t) => b.left >= r.left - t && b.right <= r.right + t && b.top >= r.top - t && b.bottom <= r.bottom + t;
      s.querySelectorAll(".fig svg, .body svg:not([data-icon]), .rest svg:not([data-icon]), .card h3 .mk svg").forEach((svg, fi) => {
        if (svg.closest("[data-icon]")) return;
        const cap = svg.closest(".fig") && svg.closest(".fig").querySelector("figcaption b");
        const fig = cap ? cap.textContent.trim() : svg.closest(".mk") ? "card number" : "figure " + (fi + 1);
        const add = (kind, msg) => rec.svg.push({ fig, kind, msg });
        const shapes = [...svg.querySelectorAll("rect, circle, ellipse, polygon")].filter(e => !e.closest("defs, marker, [data-icon], [data-deco]")).map(e => {
          const cs = getComputedStyle(e), m = e.getScreenCTM();
          return { e, r: e.getBoundingClientRect(), tag: e.tagName.toLowerCase(), fill: cs.fill, stroke: cs.stroke,
                   sw: cs.stroke === "none" ? 0 : parseFloat(cs.strokeWidth) * (m ? m.a : 1), badge: e.closest("[data-badge]") ? e.closest("[data-badge]").getAttribute("data-badge") : null,
                   valign: e.getAttribute("data-valign") };
        }).filter(o => o.r.width > 5 && o.r.height > 5 && (o.fill !== "none" || o.stroke !== "none"));
        // The ink box of one text run (a text or tspan). Rotated text is skipped
        const runInk = run => {
          const n = run.getNumberOfChars(), cs = getComputedStyle(run), m = run.getScreenCTM();
          const str = run.textContent.replace(/\s+/g, " ").trim();
          if (!n || !str || !m || Math.abs(m.b) > 1e-6 || Math.abs(m.c) > 1e-6) return null;
          const wt = parseFloat(cs.fontWeight), G = GLYPHS.w[wt >= 650 ? 700 : wt >= 550 ? 600 : 400], kk = parseFloat(cs.fontSize) / GLYPHS.upm;
          // Figure text sits on the alphabetic baseline (draw.js P.text), so the y of the first glyph's start is the baseline. Other baselines are not measured
          if (!/^(auto|alphabetic)$/.test(cs.dominantBaseline)) return null;
          const e0 = run.getExtentOfChar(0), eN = run.getExtentOfChar(n - 1), base = run.getStartPositionOfChar(0).y;
          const chars = [...str];
          let top = -1e9, bot = 1e9, body = 1e9, adv = 0;
          for (const ch of chars) {
            const g = G[ch];
            if (!g) continue;
            adv += g[0];
            if (g[4] > g[3]) { top = Math.max(top, g[4]); bot = Math.min(bot, g[3]); if (!DESC.has(ch)) body = Math.min(body, g[3]); }
          }
          if (top < -1e8) return null;
          if (body > 1e8) body = bot;
          const ls = parseFloat(cs.letterSpacing) || 0;
          const x0u = Math.min(e0.x, eN.x), x1u = Math.max(e0.x + e0.width, eN.x + eN.width) - ls;
          const nat = adv * kk + ls * Math.max(0, chars.length - 1), sx = nat > 0 ? (x1u - x0u) / nat : 1;
          const f = chars.find(c => c.trim() && G[c]), l = chars.slice().reverse().find(c => c.trim() && G[c]);
          const P = (x, y) => new DOMPoint(x, y).matrixTransform(m);
          const a = P(x0u + (f ? G[f][1] : 0) * kk * sx, base - top * kk), b = P(x1u - (l ? G[l][0] - G[l][2] : 0) * kk * sx, base - bot * kk);
          const em0 = P(x0u, e0.y), em1 = P(x1u, e0.y + e0.height);
          return { s: str, anchor: cs.textAnchor, ink: [a.x, a.y, b.x, b.y], body: P(0, base - body * kk).y, base: P(0, base).y,
                   cx: (em0.x + em1.x) / 2, cy: (em0.y + em1.y) / 2 };
        };
        const groups = new Map();
        [...svg.querySelectorAll("text")].filter(t => !t.closest("defs, [data-icon]") && t.textContent.trim()).forEach(t => {
          const runs = t.querySelector("tspan") ? [...t.querySelectorAll("tspan")].filter(x => !x.querySelector("tspan") && x.textContent.trim()) : [t];
          runs.forEach(run => {
            const u = runInk(run);
            if (!u) return;
            // The smallest shape holding the text. If shapes of the same size are stacked (a pile of cards), the top one (later in document order)
            const cand = shapes.filter(o => u.cx >= o.r.left - 0.5 && u.cx <= o.r.right + 0.5 && u.cy >= o.r.top - 0.5 && u.cy <= o.r.bottom + 0.5);
            if (!cand.length) return;
            const amin = Math.min(...cand.map(o => o.r.width * o.r.height)), home = cand.filter(o => o.r.width * o.r.height <= amin * 1.02).pop();
            if (!groups.has(home)) groups.set(home, []);
            groups.get(home).push(u);
          });
        });
        // Between an icon and its name. An icon's right end and the name's first stroke can look stuck together at 1 to 2px.
        // On the same line (more than half vertical overlap), flag ink that starts past the icon's middle and under 4.5px from its right end (an icon
        // looks half a stroke width larger)
        const runsAll = [...groups.values()].flat();
        svg.querySelectorAll("[data-icon]").forEach(ic => {
          const b = ic.getBoundingClientRect();
          if (b.width < 3) return;
          runsAll.forEach(u => {
            const vy = Math.min(b.bottom, u.ink[3]) - Math.max(b.top, u.ink[1]);
            if (vy < 0.5 * Math.min(b.height, u.ink[3] - u.ink[1])) return;
            const gap = u.ink[0] - b.right;
            if (u.ink[0] > (b.left + b.right) / 2 && gap < 4.5) add("icon touching text", "'" + ic.getAttribute("data-icon") + "' icon and '" + u.s.slice(0, 24) + "' gap " + gap.toFixed(1) + "px");
          });
        });
        // Height of a badge or icon against text on the same line. For a text run right beside a badge or icon (horizontal gap within 24,
        // more than half vertical overlap), compare its visible middle (between the ink top and the bottom without descenders) with the badge or icon center.
        // Flag a difference over 1.5. Digits in a badge and the name of a box holding an icon (the box centering check covers it) are skipped
        const vmid = u => (u.ink[1] + u.body) / 2;
        svg.querySelectorAll("[data-badge], [data-icon]").forEach(g => {
          if (g.parentElement && g.parentElement.closest("[data-badge], [data-icon]")) return;
          const b = g.getBoundingClientRect();
          if (b.width < 3 || b.height < 3) return;
          const cyB = (b.top + b.bottom) / 2, kind = g.hasAttribute("data-badge") ? "badge and text height" : "icon and text height";
          const name = g.getAttribute("data-badge") ? "badge '" + g.textContent.trim() + "'" : "'" + g.getAttribute("data-icon") + "' icon";
          runsAll.forEach(u => {
            if (u.cx >= b.left && u.cx <= b.right && u.cy >= b.top && u.cy <= b.bottom) return;
            const ov = Math.min(b.bottom, u.ink[3]) - Math.max(b.top, u.ink[1]);
            if (ov < 0.5 * Math.min(b.height, u.ink[3] - u.ink[1])) return;
            const gap = Math.max(u.ink[0] - b.right, b.left - u.ink[2]);
            if (gap < -0.5 || gap > 24) return;
            const dy = cyB - vmid(u);
            if (Math.abs(dy) > 1.5) add(kind, name + " and '" + u.s.slice(0, 24) + "' differ in height by " + dy.toFixed(1) + "px (" + (dy > 0 ? "lower" : "higher") + " than the text)");
          });
        });
        // Between text and a nearby box that does not hold it. Text can sit 1px from a neighbouring box's corner while the overlap check (6 or more) passes.
        // Flag a distance under 2.5px between the ink box and the box (diagonal distance at corners). The box holding the text (its center is inside) and
        // pieces stuck to the outside of that box (a bar filling a header band's corner) are skipped
        const homeOf = new Map();
        groups.forEach((rs, hm) => rs.forEach(u => homeOf.set(u, hm)));
        const dist = (a, b) => {
          const gx = Math.max(b.left - a.right, a.left - b.right), gy = Math.max(b.top - a.bottom, a.top - b.bottom);
          return gx > 0 && gy > 0 ? Math.hypot(gx, gy) : Math.max(gx, gy);
        };
        runsAll.forEach(u => {
          const ib = { left: u.ink[0], top: u.ink[1], right: u.ink[2], bottom: u.ink[3] }, hm = homeOf.get(u);
          shapes.forEach(o => {
            const b = o.r;
            if (o === hm || b.width * b.height < 30) return;
            if (u.cx >= b.left - 0.5 && u.cx <= b.right + 0.5 && u.cy >= b.top - 0.5 && u.cy <= b.bottom + 0.5) return;
            if (hm && !within(b, hm.r, 0.5) && dist(b, hm.r) <= 0.5) return;
            // An inner piece painted the same color as the box holding the text (a bar filling a header band's lower corner) is also part of that box
            if (hm && o.fill !== "none" && o.fill === hm.fill && within(b, hm.r, 0.5)) return;
            const d = dist(ib, b);
            if (d < 2.5 && d > -6) add("text touching box", "'" + u.s.slice(0, 24) + "' ink to " + o.tag + " gap " + d.toFixed(1) + "px (slide text " +
              [u.ink[0] - R.left, u.ink[1] - R.top, u.ink[2] - R.left, u.ink[3] - R.top].map(Math.round).join(",") + ", box " +
              [b.left - R.left, b.top - R.top, b.right - R.left, b.bottom - R.top].map(Math.round).join(",") + ")");
          });
        });
        groups.forEach((runs, home) => {
          rec.boxtext++;
          const r = home.r, iw = home.sw / 2, ix0 = r.left + iw, iy0 = r.top + iw, ix1 = r.right - iw, iy1 = r.bottom - iw;
          const ik = [Math.min(...runs.map(u => u.ink[0])), Math.min(...runs.map(u => u.ink[1])), Math.max(...runs.map(u => u.ink[2])), Math.max(...runs.map(u => u.ink[3]))];
          const label = "'" + runs.map(u => u.s).join(" / ").slice(0, 34) + "'";
          const g = [ik[1] - iy0, iy1 - ik[3], ik[0] - ix0, ix1 - ik[2]];
          if (Math.min(...g) < TOUCH) add("text touching border", label + " to the inner border: top " + g[0].toFixed(1) + ", bottom " + g[1].toFixed(1) + ", left " + g[2].toFixed(1) + ", right " + g[3].toFixed(1));
          const lines = [];
          runs.slice().sort((p, q) => p.base - q.base).forEach(u => { const L = lines[lines.length - 1]; if (L && Math.abs(L[0].base - u.base) < 1.5) L.push(u); else lines.push([u]); });
          let bt = ik[1], bb = Math.max(...runs.map(u => u.body));
          // A step number circle (D.num) inside a box counts as part of the text block. Corner marks (D.mark) do not
          shapes.forEach(o => { if (o.badge === "num" && o.tag === "circle" && o !== home && within(o.r, r, 1)) { bt = Math.min(bt, o.r.top); bb = Math.max(bb, o.r.bottom); } });
          // A box holding other boxes, lines or curves is a panel (diagram, chart). Only leaf boxes get the center check
          const kids = shapes.filter(o => o !== home && !o.badge && within(o.r, r, 0.5) && (o.r.width < r.width - 1 || o.r.height < r.height - 1)).length +
            [...svg.querySelectorAll("path, line, polyline")].filter(e => !e.closest("defs, marker, [data-icon]")).map(e => e.getBoundingClientRect())
              .filter(b => (b.width > 4 || b.height > 4) && within(b, r, 0.5)).length;
          const icons = [...svg.querySelectorAll("[data-icon]")].map(e => e.getBoundingClientRect()).filter(b => within(b, r, 1));
          const ih = iy1 - iy0, cover = (bb - bt) / ih;
          if (!kids && !home.valign && !icons.some(b => b.bottom <= bt + 1) && lines.length <= 4 && (cover >= 0.33 || (lines.length === 1 && ih <= 44))) {
            const dy = (bt + bb) / 2 - (iy0 + iy1) / 2;
            if (Math.abs(dy) > OFF_V) add("text off center vertically", label + " block center is " + Math.abs(dy).toFixed(2) + "px " + (dy > 0 ? "below" : "above") + " the box center");
          }
          if (!kids && !icons.length && home.tag !== "polygon") lines.forEach(L => {
            if (!L.every(u => u.anchor === "middle")) return;
            // A line made only of blind edition masking bars (■) is not text. The bar font's ink bottom differs from the text baseline, so it reads as a separate line.
            // The centering of the same text is measured in the edition without the bars
            if (L.every(u => /^■+$/.test(u.s))) return;
            const dx = (Math.min(...L.map(u => u.ink[0])) + Math.max(...L.map(u => u.ink[2]))) / 2 - (ix0 + ix1) / 2;
            if (Math.abs(dx) > OFF_H) add("text off center horizontally", "'" + L.map(u => u.s).join(" ").slice(0, 30) + "' ink center is " + Math.abs(dx).toFixed(2) + "px " + (dx > 0 ? "right of" : "left of") + " the box center");
          });
        });
      });
    }
    out.slides.push(rec);
  });
  document.getElementById("probe-out").textContent = JSON.stringify(out);
})();
`;

module.exports = { Deck, h };
