// The panel's layout audit, run in the page (tests/app/walk.py): it measures what the eye misses and reports it as
// counts, so a screenshot is never the only proof.
//   overflow   a line of text outside its own box or cut by a box that does not scroll; the page wider than the window
//   truncated  text cut short with an ellipsis (it hides words)
//   overlap    two lines of text from different elements on top of each other
//   markup     raw marks or placeholders on screen: ==, **, tags, entities, {name}, undefined, NaN, null
//   paths      file paths or commands on screen (the panel promises neither); the person's own file names are allowed
//   contrast   text under 4.5:1 against what is behind it (3:1 for large text), glass composited over the desk; the
//              document's own print colours (inside .sheet) and disabled keys are left to their own checks (WCAG exempts them)
//   align      rows and columns: keys, fields and menus side by side in one line that differ in height or sit off each
//              other's middle, small cards of one kind (tiles) that share a row but end at different heights, and Make's
//              columns whose heads leave one row or whose first cards start off one line (content cards end where their
//              content does: none is stretched to a neighbour)
//   center     a one-line key whose words and signs sit off its middle by more than a pixel: up or down for every key, and
//              across for a key whose contents are centred (a list's row key is left-aligned on purpose). The words' middle
//              is their body from the font's own measure (Hangul syllables, or the capital's height for Latin letters and
//              figures; the text's box holds the font's whole ascent and descent); a sign, a badge or a lamp inside the key
//              counts with them; the middle is the key's inside, so a tab's underline is out
// Text under a fixed or sticky bar (the bar at a phone's foot, the top bar, the first run's cover) is hidden by it, not
// overlapping it, so it is left out of the overlap count. The argument lists the names the person gave their files.
(allowedNames) => {                                                                 // page.evaluate passes the allowed names in
  const out = { overflow: [], truncated: [], overlap: [], markup: [], paths: [], contrast: [], align: [], center: [], texts: 0, keys: 0 };  // findings and how much was looked at
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;  // the window
  const desc = (el) => {                                                            // a short name for an element
    // the id and the first two classes (an SVG's className is not a string)
    const id = el.id ? "#" + el.id : "", cls = el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
    return `${el.tagName.toLowerCase()}${id}${cls} "${(el.textContent || "").trim().slice(0, 40)}"`;  // tag, id, classes and the start of its text
  };
  // a sideways scrollbar on the whole page
  if (document.documentElement.scrollWidth > vw + 1) {                              // and which element reaches furthest past the window's edge
    let far = null, right = vw;                                                     // the culprit, and how far it reaches
    for (const el of document.body.querySelectorAll("*")) { const r = el.getBoundingClientRect(); if (r.width && r.right > right + 1) { right = r.right; far = el; } }
    out.overflow.push({ what: "page wider than the window", px: document.documentElement.scrollWidth - vw, el: far ? desc(far) : "" });
  }
  const pinned = (el) => { for (let a = el; a && a !== document.documentElement; a = a.parentElement) { const p = getComputedStyle(a).position; if (p === "fixed" || p === "sticky") return a; } return null; };  // the bar it belongs to
  const fillAlpha = (c) => {                                                        // the alpha of a computed colour: rgb(), rgba() or color(srgb ... / a)
    const m = String(c).match(/^rgba?\(([^)]+)\)$/) || String(c).match(/^color\(srgb ([^)]+)\)$/);  // the two forms Chrome writes
    if (!m) return 0;                                                               // transparent or unknown
    const slash = m[1].split("/");                                                  // color(srgb r g b / a)
    if (slash.length > 1) return Number(slash[1]);                                  // its alpha
    const p = m[1].split(/[ ,]+/).filter(Boolean).map(Number);                      // rgb or rgba channels
    return p.length > 3 ? p[3] : 1;                                                 // rgba's alpha, or opaque rgb
  };
  const imageAlpha = (img) => {                                                     // a gradient's thinnest stop: what it lets through at most
    const stops = [...String(img || "").matchAll(/rgba?\(([^)]*)\)/g)].map((m) => fillAlpha(`rgba(${m[1]})`));
    return stops.length ? Math.min(...stops) : 0;
  };
  const hides = (x) => {                                                            // a layer that hides the text under it: an opaque fill, or frosted glass
    for (const cs of [getComputedStyle(x), getComputedStyle(x, "::before")]) {      // the box itself, and a frost drawn on a layer of its own (the bar's)
      const a = 1 - (1 - fillAlpha(cs.backgroundColor)) * (1 - imageAlpha(cs.backgroundImage));   // its fill, colour and gradient together
      const blur = Number((/blur\(([\d.]+)px\)/.exec(cs.backdropFilter || cs.webkitBackdropFilter || "") || [])[1] || 0);   // how far it frosts what is behind
      if (a >= 0.9 || (a >= 0.5 && blur >= 12)) return true;                        // opaque, or half filled over a blur no words survive
    }
    return false;
  };
  const covered = (r, el) => {                                                      // hidden under a fixed or sticky layer it is not part of
    const top = document.elementFromPoint(Math.min(Math.max((r.left + r.right) / 2, 0), vw - 1), Math.min(Math.max((r.top + r.bottom) / 2, 0), vh - 1));  // what is drawn at its middle
    if (!top || top === el || el.contains(top) || top.contains(el)) return false;   // itself
    if (!pinned(top) || pinned(top).contains(el)) return false;                     // not a bar, or the text is part of it
    if (top.closest("#toast") && el.closest("#top")) return false;                  // a note over the bar's own words: they should have stepped aside (core.js stepAside), so it counts
    for (let x = top; x && x !== document.documentElement; x = x.parentElement) {   // the cover's fills, from the point upward
      if (x.contains(el)) return false;                                             // reached the text's own branch first: drawn over nothing opaque
      if (hides(x)) return true;                                                     // an opaque fill above the text hides it, or glass frosted past reading
    }
    return false;                                                                   // glass all the way: the text shows through, so it counts as overlapping
  };
  const visible = (el) => {                                                         // drawn and not hidden by a parent
    for (let a = el; a && a !== document.body; a = a.parentElement) {               // the element and each parent up to the body
      const cs = getComputedStyle(a);                                               // the styles in effect, inline or not
      if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0) return false;  // hidden by this box or one above it
      if (cs.clipPath === "inset(50%)" && a.getBoundingClientRect().width <= 1) return false;  // the screen-reader-only pattern (.sr): read aloud, never drawn
    }
    return true;                                                                    // nothing on the way up hides it
  };
  const shown = (r, el) => {                                                        // the part of a line that is drawn: inside every box that cuts or scrolls
    let x0 = r.left, y0 = r.top, x1 = r.right, y1 = r.bottom;                       // start from the whole line
    for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {  // every box around it
      const cs = getComputedStyle(a);                                               // how this box treats what spills
      if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;      // this box lets it out
      const ar = a.getBoundingClientRect();                                         // the cutting box on screen
      x0 = Math.max(x0, ar.left); y0 = Math.max(y0, ar.top); x1 = Math.min(x1, ar.right); y1 = Math.min(y1, ar.bottom);  // keep only the part inside it
    }
    x0 = Math.max(x0, 0); y0 = Math.max(y0, 0); x1 = Math.min(x1, vw); y1 = Math.min(y1, vh);  // and inside the window
    return x1 - x0 > 1 && y1 - y0 > 1 ? { left: x0, top: y0, right: x1, bottom: y1 } : null;  // null: scrolled away
  };
  const rects = [];                                                                 // every line of text that is drawn: [rect, element]
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);    // text nodes only, in page order
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {                      // each text node
    if (!n.nodeValue.trim()) continue;                                              // whitespace between tags is not text
    const el = n.parentElement;                                                     // the element that lays it out
    if (!el || ["SCRIPT", "STYLE", "OPTION"].includes(el.tagName) || !visible(el)) continue;  // code, menu items and hidden text are skipped
    const range = document.createRange(); range.selectNodeContents(n);              // a range gives one rectangle per line
    const own = el.getBoundingClientRect();                                         // its element's box
    const lines = new Set([...range.getClientRects()].filter((r) => r.width > 1).map((r) => Math.round(r.top)));  // the lines it takes
    const word = n.nodeValue.trim();                                                // one word: no space inside
    // a short word on two lines was squeezed; addresses and paths may wrap, and a line may break before an opening parenthesis
    // (a school and its place, '가나다대학교' then '(서울)', is set that way) or after the hyphen of a compound word
    // ('client-' then 'side', as English is set and every browser breaks it): only a break elsewhere in the word counts
    if (lines.size > 1 && !/\s/.test(word) && word.length < 40 && !/[@/.]/.test(word)) {
      const t = n.nodeValue, tops = [];
      for (let i = 0; i < t.length; i++) { const one = document.createRange(); one.setStart(n, i); one.setEnd(n, i + 1); const b = one.getClientRects()[0]; tops.push(b && b.width > 0 ? Math.round(b.top) : null); }
      const breaks = []; for (let i = 1, last = tops[0]; i < t.length; i++) { if (tops[i] === null) continue; if (last !== null && tops[i] !== last) breaks.push(i); last = tops[i]; }
      const setRight = (i) => t[i] === "(" || t[i] === "\uff08" || /[\p{L}\p{N}][-\u2010\u2013]$/u.test(t.slice(0, i));   // before a parenthesis, or after a compound word's hyphen
      if (!breaks.length || breaks.some((i) => !setRight(i))) out.overflow.push({ what: "a word broken across lines", el: desc(el) });
    }
    for (const r of range.getClientRects()) {                                       // each line of it
      if (r.width < 1 || r.height < 1) continue;                                    // empty boxes at line ends
      out.texts++;                                                                  // how much was looked at, in lines
      const vis = shown(r, el);                                                     // what of it is on screen
      if (vis && !covered(vis, el)) rects.push([vis, el]);                          // kept for the overlap check, unless a bar hides it
      // spilling out of its own element's box
      if (r.right > own.right + 1.5 || r.left < own.left - 1.5) out.overflow.push({ what: "text outside its box", el: desc(el), px: Math.round(Math.max(r.right - own.right, own.left - r.left)) });
      for (let a = el; a && a !== document.documentElement; a = a.parentElement) { // boxes that cut what spills
        const cs = getComputedStyle(a);                                             // how this box treats what spills
        const clipX = /hidden|clip/.test(cs.overflowX), clipY = /hidden|clip/.test(cs.overflowY);  // which directions this box cuts
        if (/auto|scroll/.test(cs.overflowX + cs.overflowY)) break;                // a box that scrolls: what spills is read by scrolling it, and the boxes around it cut only the box itself
        if (!clipX && !clipY) continue;                                             // visible boxes do not cut
        const ar = a.getBoundingClientRect();                                       // the cutting box on screen
        if (clipX && (r.right > ar.right + 1 || r.left < ar.left - 1)) {            // the line runs past its sides
          // with an ellipsis the cut is truncation, without one plain overflow
          (cs.textOverflow === "ellipsis" || getComputedStyle(el).textOverflow === "ellipsis" ? out.truncated : out.overflow)
            .push({ what: "cut across", el: desc(el), by: desc(a) });               // which box cut it
          break;                                                                    // one finding per line is enough
        }
        if (clipY && (r.bottom > ar.bottom + 1 || r.top < ar.top - 1) && a !== document.body) {  // past its top or bottom; the body only scrolls
          out.overflow.push({ what: "cut below", el: desc(el), by: desc(a) });      // a line hidden under the box's edge
          break;                                                                    // one finding per line is enough
        }
      }
    }
  }
  for (const el of document.querySelectorAll("*")) {                                // ellipsis that is in effect
    const cs = getComputedStyle(el);                                                // whether it asks for an ellipsis
    // the text is wider than its box, so the dots show
    if (cs.textOverflow === "ellipsis" && el.scrollWidth > el.clientWidth + 1 && visible(el)) out.truncated.push({ what: "ellipsis", el: desc(el) });
  }
  rects.sort((a, b) => a[0].top - b[0].top);                                        // overlap: lines that share space
  for (let i = 0; i < rects.length; i++) {                                          // each line against the lines below it
    const [a, ea] = rects[i];                                                       // the upper line and its element
    for (let j = i + 1; j < rects.length && rects[j][0].top < a.bottom - 2; j++) {  // sorted by top: stop once lines start below it
      const [b, eb] = rects[j];                                                     // the lower line and its element
      if (ea === eb || ea.contains(eb) || eb.contains(ea)) continue;                // one element's own lines
      // the shared rectangle's width and height
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      const shared = { left: Math.max(a.left, b.left), right: Math.min(a.right, b.right), top: Math.max(a.top, b.top), bottom: Math.min(a.bottom, b.bottom) };  // where they meet
      if (w > 2 && h > 2 && !covered(shared, ea) && !covered(shared, eb))           // an opaque layer over the meeting place (an open menu) hides one of them there
        out.overlap.push({ a: desc(ea), b: desc(eb), w: Math.round(w), h: Math.round(h) });  // more than a touching edge
    }
  }
  // contrast: each element that holds text, against the colours behind it
  const rgba = (c) => {                                                             // a computed colour as channels 0-255 and alpha
    let m = String(c).match(/rgba?\(([^)]+)\)/);                                   // rgb() and rgba()
    if (m) { const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    m = String(c).match(/color\(srgb ([^)]+)\)/);                                    // color-mix() results: color(srgb r g b / a), channels 0-1
    if (m) { const [rgb, a] = m[1].split("/"); const p = rgb.trim().split(/\s+/).map(Number); return { r: p[0] * 255, g: p[1] * 255, b: p[2] * 255, a: a === undefined ? 1 : Number(a) }; }
    return null;                                                                    // transparent or unknown
  };
  const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };  // sRGB to linear light
  const lum = (c) => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);     // relative luminance
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });  // one layer over another
  const desk = rgba(getComputedStyle(document.documentElement).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };  // the page's own colour
  const behind = (el) => {                                                          // the colour under an element's text: its backgrounds up to an opaque one
    const layers = [];                                                              // translucent layers on the way up
    for (let a = el; a; a = a.parentElement) {                                      // the element and its parents
      const c = rgba(getComputedStyle(a).backgroundColor);                          // this one's fill
      if (c && c.a > 0) { layers.push(c); if (c.a >= 0.99) break; }                 // an opaque fill ends the walk
    }
    let col = layers.length && layers[layers.length - 1].a >= 0.99 ? layers.pop() : (desk.a >= 0.99 ? desk : { r: 255, g: 255, b: 255, a: 1 });  // the floor
    while (layers.length) col = over(layers.pop(), col);                            // glass and tints composited, lowest first
    return col;                                                                     // what the eye sees behind the text
  };
  const seen = new Set();                                                           // each element once
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);        // text nodes again
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {                               // each one
    const el = n.parentElement;                                                     // its element
    if (!n.nodeValue.trim() || !el || seen.has(el) || ["SCRIPT", "STYLE", "OPTION"].includes(el.tagName) || !visible(el)) continue;  // only drawn text, once
    seen.add(el);                                                                   // measured
    if (el.closest(".sheet, button:disabled, [aria-disabled='true'], [hidden], .sr") || el.closest("[inert]")) continue;  // print colours, disabled keys, hidden layers
    const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) continue;  // not drawn
    const cs = getComputedStyle(el), fg = rgba(cs.color); if (!fg) continue;        // its colour
    let op = 1; for (let a = el; a; a = a.parentElement) op *= Number(getComputedStyle(a).opacity);  // faded parents fade the text
    const bg = behind(el), ink = over({ ...fg, a: fg.a * op }, bg);                 // the text as drawn over what is behind it
    const L1 = lum(ink), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);  // the contrast ratio
    const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;       // large text needs less
    const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;                   // WCAG AA
    if (ratio < need - 0.02) out.contrast.push({ el: desc(el), ratio: Math.round(ratio * 100) / 100, need });  // too faint
  }
  // align: the keys and fields that stand side by side in one line, one height and one middle
  const CONTROL = "button, a.btn, input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]), select, .barchip, .seg";
  const lineUp = new Map();                                                         // parent -> its controls
  for (const el of document.querySelectorAll(CONTROL)) {
    if (!visible(el) || el.closest(".seg") && !el.matches(".seg") || el.closest(".sheet, .sendbox, .stepper, .callbars, .notebook")) continue;  // a choice inside its group, a key inside its field, the document itself
    if (getComputedStyle(el).position === "absolute" || getComputedStyle(el).position === "fixed") continue;   // placed on its own
    const p = el.parentElement; if (!lineUp.has(p)) lineUp.set(p, []); lineUp.get(p).push(el);
  }
  for (const [p, els] of lineUp) {
    if (els.length < 2 || !/flex|grid/.test(getComputedStyle(p).display)) continue;  // controls laid out side by side
    const rs = els.map((e) => [e, e.getBoundingClientRect()]);
    for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
      const [ea, a] = rs[i], [eb, b] = rs[j];
      if (Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) < Math.min(a.height, b.height) / 2) continue;   // not on one line
      if (Math.abs(a.height - b.height) > 1.5) out.align.push({ what: "keys of different heights in one line", a: desc(ea), b: desc(eb), px: Math.round(Math.abs(a.height - b.height)) });
      else if (Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2) > 1.5) out.align.push({ what: "keys off each other's middle", a: desc(ea), b: desc(eb) });
    }
  }
  // align: Make's columns side by side: their heads share a row (top and foot), and their first cards start on one line. The cards
  // end where their content ends: a card stretched to the tallest beside it shows a blank foot, so none is
  for (const flow of document.querySelectorAll(".flow")) {
    const cols = [...flow.children].filter((c) => visible(c)).map((c) => [c, c.getBoundingClientRect()]);
    const side = cols.filter(([, r]) => Math.abs(r.top - cols[0][1].top) <= 1.5);  // the columns that stand side by side on the first row
    if (side.length < 2) continue;
    const heads = side.map(([c]) => c.children[0]).filter((e) => e && visible(e)).map((e) => e.getBoundingClientRect());   // each column's head
    const firsts = side.map(([c]) => c.querySelector(".flow-cards > *")).filter((e) => e && visible(e)).map((e) => e.getBoundingClientRect());   // each column's first card
    const spread = (v) => v.length > 1 ? Math.max(...v) - Math.min(...v) : 0;
    if (spread(heads.map((r) => r.top)) > 1.5 || spread(heads.map((r) => r.bottom)) > 1.5)
      out.align.push({ what: "Make's column heads out of one row", px: Math.round(Math.max(spread(heads.map((r) => r.top)), spread(heads.map((r) => r.bottom)))) });
    if (spread(firsts.map((r) => r.top)) > 1.5) out.align.push({ what: "Make's first cards not on one line", px: Math.round(spread(firsts.map((r) => r.top))) });
  }
  // align: small cards of one kind that share a row end together (tiles and job cards are one size by design). The content cards (Make's
  // columns, the stage board, the question board, the scripts) end where their content does and are not measured here
  for (const sel of [".tiles > .tile", ".jobgrid > .jobcard", ".parts > *"]) {
    const rs = [...document.querySelectorAll(sel)].filter(visible).map((e) => [e, e.getBoundingClientRect()]).filter(([, r]) => r.height > 0);
    const rows = [];                                                                // cards grouped by their top
    for (const x of rs) { const row = rows.find((g) => Math.abs(g[0][1].top - x[1].top) <= 1.5); if (row) row.push(x); else rows.push([x]); }
    for (const row of rows) {
      if (row.length < 2) continue;                                                 // alone on its row
      const lo = Math.min(...row.map(([, r]) => r.bottom)), hi = Math.max(...row.map(([, r]) => r.bottom));
      if (hi - lo > 1.5) out.align.push({ what: "cards in one row end at different heights", sel, px: Math.round(hi - lo), a: desc(row[0][0]) });
    }
  }
  let text = document.body.innerText;                                               // what a person reads
  for (const f of document.querySelectorAll("textarea")) if (f.textContent) text = text.split(f.textContent).join(" ");  // the words being edited are the person's own, marks included
  const near = (i) => text.slice(Math.max(0, i - 30), i + 30).replace(/\s+/g, " ");  // the words around a finding, on one line
  // each kind of raw mark or placeholder, with its name
  for (const [re, what] of [[/==\S|\S==/, "=="], [/\*\*\S/, "**"], [/<\/?[a-z][a-z0-9]*[\s>/]/i, "a tag"], [/&(?:[a-z]+|#\d+);/i, "an entity"],
                            [/\{[a-z_]+(?:\|[^}]*)?\}/i, "a placeholder"], [/\bundefined\b|\bNaN\b|\[object /, "a script value"], [/\bnull\b/, "null"]]) {
    const m = text.match(re); if (m) out.markup.push({ what, at: near(m.index) });  // the first match of each kind is enough
  }
  let scrubbed = text;                                                              // the person's own file names are fine
  for (const name of allowedNames || []) scrubbed = scrubbed.split(name).join("");  // cut out, so they never count as paths
  // Unix and Windows paths, commands, code files and setting names
  for (const [re, what] of [[/(?:^|[\s(])(?:\/(?:root|home|tmp|usr|mnt|var|Users|opt)\/|[A-Za-z]:\\|~\/)/m, "a path"],
                            [/\b(?:python3? [\w./-]+|docker (?:compose|run|build|ps)|npm (?:ci|install|run)|npx [\w@/-]+|pip3? install|bash [\w./-]+)|(?:^|\s)\.\/[\w-]+|\bofferowl (?:panel|build|ingest|init|selftest)\b/m, "a command"],
                            [/\b[\w-]+\.(?:py|js|sh|jsonl)\b/, "a code file"], [/\bOFFEROWL_[A-Z_]+/, "a setting name"]]) {
    // the first match of each kind, with the words around it
    const m = scrubbed.match(re); if (m) out.paths.push({ what, at: scrubbed.slice(Math.max(0, m.index - 30), m.index + 30).replace(/\s+/g, " ") });
  }
  // center: the words and signs of a one-line key in its middle (see the head of this file)
  const ink = document.createElement("canvas").getContext("2d");                    // the font's own measure of its glyphs
  const alpha = (c) => fillAlpha(c || "");                                          // rgb(), rgba() and color(srgb ... / a): a badge filled with color-mix() is drawn too
  for (const k of document.querySelectorAll("button, a.btn, [role=tab], .chip, .pill, .barchip")) {
    if (!visible(k) || k.closest(".sheet")) continue;                               // the document's own words are not keys
    const B = k.getBoundingClientRect(), cs = getComputedStyle(k);
    if (B.height > 48 || B.width < 12) continue;                                    // one-line keys only
    const top = B.top + (parseFloat(cs.borderTopWidth) || 0), bottom = B.bottom - (parseFloat(cs.borderBottomWidth) || 0);   // its inside
    const left = B.left + (parseFloat(cs.borderLeftWidth) || 0), right = B.right - (parseFloat(cs.borderRightWidth) || 0);
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;              // what is drawn in it
    const walker = document.createTreeWalker(k, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {                     // its words
      if (!n.nodeValue.trim() || !visible(n.parentElement)) continue;
      const ps = getComputedStyle(n.parentElement);
      // measured at ten times the size: the canvas rounds its metrics to whole pixels, which moved a middle by up to a pixel
      ink.font = `${ps.fontStyle} ${ps.fontWeight} ${parseFloat(ps.fontSize) * 10}px ${ps.fontFamily}`;
      // the words' body, as a reader centres them: Hangul by its syllables, Latin letters and figures by the capital's height
      // (a p or a g hanging below the line is not part of where a word sits; measured whole, an English key read 1.5 px low)
      const m = ink.measureText(/[\u3131-\u318E\uAC00-\uD7A3]/.test(n.nodeValue) ? "가나다" : "HIE");   // the glyphs above and below the baseline
      const fa = m.fontBoundingBoxAscent / 10, fd = m.fontBoundingBoxDescent / 10, ia = m.actualBoundingBoxAscent / 10, id = m.actualBoundingBoxDescent / 10;
      const range = document.createRange(); range.selectNodeContents(n);
      for (const r of range.getClientRects()) {
        if (r.width < 1) continue;
        // the text's box is its font's content area: the baseline is the font's ascent below its top
        const base = r.top + (r.height - (fa + fd)) / 2 + fa;
        y0 = Math.min(y0, base - ia); y1 = Math.max(y1, base + id);
        x0 = Math.min(x0, r.left); x1 = Math.max(x1, r.right);
      }
    }
    for (const d of k.querySelectorAll("*")) {                                      // its signs, badges and lamps
      if (d.closest("svg") && d.tagName.toLowerCase() !== "svg" || !visible(d)) continue;
      const r = d.getBoundingClientRect(), ds = getComputedStyle(d);
      // a lamp is its child's dot, lit (a fill) or unlit (a ring drawn by its shadow or border)
      const lamp = ["::before", "::after"].some((w) => { const q = getComputedStyle(d, w); return q.content !== "none" && q.content !== "normal" && (alpha(q.backgroundColor) > 0.05 || q.boxShadow !== "none" || parseFloat(q.borderTopWidth) > 0); });
      const drawn = /^(svg|img)$/i.test(d.tagName) || alpha(ds.backgroundColor) > 0.05 || ds.backgroundImage !== "none" || lamp;   // a lamp is its child's dot
      if (!drawn || r.width < 3 || r.height < 3 || r.width > B.width - 4) continue; // a face as wide as the key is the key itself
      x0 = Math.min(x0, r.left); x1 = Math.max(x1, r.right); y0 = Math.min(y0, r.top); y1 = Math.max(y1, r.bottom);
    }
    if (!isFinite(y0)) continue;                                                    // nothing drawn
    out.keys++;                                                                     // how many keys were measured
    const pseudo = ["::before", "::after"].some((w) => { const q = getComputedStyle(k, w); return q.content !== "none" && q.content !== "normal" && (alpha(q.backgroundColor) > 0.05 || q.content.length > 2); });
    const centred = cs.justifyContent === "center" || (cs.textAlign === "center" && !/flex|grid/.test(cs.display));
    const dy = (y0 + y1) / 2 - (top + bottom) / 2, dx = (x0 + x1) / 2 - (left + right) / 2;
    // a lamp drawn by the key's own ::before or ::after has no box to measure: such a key is judged up and down only
    if (Math.abs(dy) > 1 || centred && !pseudo && Math.abs(dx) > 1) out.center.push({ el: desc(k), dy: +dy.toFixed(1), dx: centred && !pseudo ? +dx.toFixed(1) : null });
  }
  return out;                                                                       // walk.py counts each list
}
