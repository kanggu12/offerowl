// Blind edition, for sharing a document with names and contacts hidden. With OFFEROWL_BLIND=1, text that matches the mask patterns of the table is
// covered by a bar of the original width (mask_fill color, dark red). The text is never replaced by other words, only
// covered. save.js calls this for each text run of the docx, and deck.js for each text node of the HTML and SVG. The
// table and the principles are in the header comment of blind.json.
// The table is src/blind.json, or the file OFFEROWL_BLIND_TABLE names: a person's own table, which the panel keeps in the
// workspace and stages under output/_inputs (named relative to the repository, as the container sees it). A person's
// table goes over src/blind.json key by key, and the band's and the label's words per language, as src/blind.py merges it.
const fs = require("fs");                                                          // a person's table is read from its file
const path = require("path");                                                      // and found from the repository root
const BASE = require("./blind.json");                                              // the shipped table: generic and empty
// A named table that cannot be read stops the build: a blind edition never falls back to a table that covers nothing
const MINE = process.env.OFFEROWL_BLIND_TABLE ? JSON.parse(fs.readFileSync(path.resolve(__dirname, "..", process.env.OFFEROWL_BLIND_TABLE), "utf8")) : {};
const T = { ...BASE, ...MINE, footer: { ...BASE.footer, ...(MINE.footer || {}) }, banner: { ...BASE.banner, ...(MINE.banner || {}) } };   // theirs over the shipped one
const M = require("./blind_metrics.json");
const on = process.env.OFFEROWL_BLIND === "1";
// The resume layout (layout.js) does not know the document language (the Korean and the English base editions both call
// setLangKo(true)), so the English entry script passes OFFEROWL_BLIND_LANG=en.
const lang = process.env.OFFEROWL_BLIND_LANG === "en" ? "en" : "ko";
// A plain space in a pattern also matches the no-break space the documents put between words: deck.js keeps a name's words,
// and a word and its particle, together with one, and a name written with a plain space went uncovered in the deck
// ("NH Investment"). A space inside a character class stays as it is; blind.py nbsp() is the same rule.
function nbsp(p) {
  let out = "", cls = false;                                                       // the pattern rewritten; inside [...] or not
  for (let i = 0; i < p.length; i++) {
    const c = p[i];
    if (c === "\\") { out += c + (p[i + 1] || ""); i++; continue; }              // an escape stays whole (\s, \., \[)
    if (c === "[") cls = true; else if (c === "]") cls = false;                    // into or out of a class
    out += c === " " && !cls ? "[ \u00a0]" : c;                                    // a space outside a class: either space
  }
  return out;
}
// No patterns, no expression: an empty one would match the empty text at every place, and every run would count as a hit
const RE = (T.mask || []).length ? new RegExp(T.mask.map(p => "(?:" + nbsp(p) + ")").join("|"), "g") : null;
const WHOLE = (T.mask_whole || []).map(p => new RegExp("^(?:" + nbsp(p) + ")$"));

// Splits s into [text, masked] pieces. The spaces inside a matched phrase are not masked, so the bar is cut at each
// word, as the original words are, and the line can wrap there.
function segments(s) {
  const out = [];
  let last = 0;
  if (!RE) return [[s, false]];                                                    // an empty table covers nothing
  for (const m of s.matchAll(RE)) {
    if (!m[0]) continue;
    if (m.index > last) out.push([s.slice(last, m.index), false]);
    // A value that is one unit, such as a contact value, is covered with its spaces by a single bar (cutting at every
    // space scattered the bar into small pieces and looked untidy)
    if (WHOLE.some(r => r.test(m[0]))) out.push([m[0], true]);
    else for (const part of m[0].split(/(\s+)/)) if (part) out.push([part, !/^\s+$/.test(part)]);
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push([s.slice(last), false]);
  return out;
}
// A match that holds a character, as segments() counts one (an empty match covers nothing)
const hit = s => !!RE && typeof s === "string" && [...s.matchAll(RE)].some(m => m[0]);
// A text with what the table covers taken out, on one line: what a blind edition may say where no bar can stand (the
// document's own title and author). src/blind.py plain() is the same rule.
const plain = s => segments(String(s || "")).filter(([, m]) => !m).map(([p]) => p).join("").split(/\s+/).filter(Boolean).join(" ");
// The blind edition's own title: the title without what is covered, then the edition's label ("블라인드 버전", "Blind version")
// in the document's language (the deck knows its own; the resume's comes from OFFEROWL_BLIND_LANG)
const title = (s, lg = lang) => [plain(s), T.footer[lg] ? `(${T.footer[lg]})` : ""].filter(Boolean).join(" ");

// Width of a text in em, from the real advance widths of Pretendard (the table in blind_metrics.json). All Hangul
// characters share one width from the table, and a character missing from the table counts as 0.6
function widthEm(s, bold) {
  const t = M[bold ? "bold" : "regular"];
  let w = 0;
  for (const ch of s) w += /[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3]/.test(ch) ? t.hangul : (t.ascii[ch] ?? 0.6);
  return w;
}
// Makes the bar exactly as wide as the original text. It places the rounded-up number of squares (U+25A0) and takes the
// surplus width back with a negative character spacing. The squares have the same color as the background, so they read
// as one continuous bar, and only the square glyphs are left in the text layer. A bar made of space characters would be
// stretched by justification (the Korean resume went to seven pages), and the spaces in the text layer would make a
// checker read the bar as a column break.
const FIG = "\u25A0";
function fit(s, bold, extraEm = 0) {
  const w = widthEm(s, bold) + extraEm, nb = M[bold ? "bold" : "regular"].box;
  const n = Math.max(1, Math.ceil(w / nb - 1e-9));
  return { n, ls: w / n - nb };          // number of squares, and the spacing to add per glyph (em)
}
// For HTML text nodes: a bar of squares on a mask_fill background (the squares are transparent, and only the square
// glyphs remain in the text layer). In places such as titles the weight and letter spacing differ, so the pre-measured
// width would be off. The original text is therefore kept in data-t, the browser measures it with the real font before
// printing, fits the bar width to it and then removes data-t (BLIND_JS in deck.js). Nothing of it remains in the PDF.
const attr = s => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
function htmlBar(s) {
  const { n, ls } = fit(s, false);
  return `<span class="bm" data-t="${attr(s)}" style="letter-spacing:${ls.toFixed(4)}em">${FIG.repeat(n)}</span>`;
}
// For SVG figures: one square glyph of the same font is stretched horizontally to the original width (textLength), so
// the glyph height and the vertical alignment stay the same. The width is estimated from the font table, and before
// printing the browser replaces it with the real width, measured by briefly putting the original text into the same
// <text> element (BLIND_JS in deck.js). The table has only two weights, regular and bold, so a bar for semibold text at
// another size was off by almost 2pt and pushed the text after it.
function svgBar(s, fontSize, bold) {
  return `<tspan class="bms" data-t="${attr(s)}" fill="#${T.mask_fill}" textLength="${(widthEm(s, bold) * fontSize).toFixed(2)}" lengthAdjust="spacingAndGlyphs">\u25A0</tspan>`;
}

module.exports = { on, lang, T, M, FIG, segments, hit, plain, title, widthEm, fit, htmlBar, svgBar };
