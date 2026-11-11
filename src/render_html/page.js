// Layout engine of a page made by src/render_html/docx2html.py. It runs in the browser before printing and does what
// the container's LibreOffice does with the same DOCX: line heights, tab stops, floating pictures, page breaks and the
// footer.
// When it is done it sets data-owl-ready on <html>, and window.OWL_RESULT says how many pages it made.
(function () {
  "use strict";
  const CFG = window.OWL_PAGE;                       // page size, margins and font metrics from the converter
  const PX = 96 / 72;                                // CSS pixels per point
  const px2pt = v => v / PX;                         // the browser measures in pixels, the DOCX speaks in points
  const S = CFG.scale || 1;                          // the page is laid out S times larger and drawn at 1/S (docx2html.py)
  const DEFAULT_TAB = 36 * S;                        // Word's default tab interval, 0.5 inch
  const EPS = 0.05 * S;                              // two positions closer than this are the same
  // LibreOffice's PDF places the text 0.1pt right of and below the DOCX position: measured on every line of three
  // documents, its words started 0.10pt further right and lower than here. The page moves its content the same way.
  const NUDGE = (CFG.nudge === undefined ? 0.1 : CFG.nudge) * S;
  const WIDOWS = 2, ORPHANS = 2;                     // lines a split paragraph keeps at least on the next and on this page

  // The ascent and descent (fractions of the em) of a CSS family list, from the converter's table.
  function metrics(el) {
    const fam = getComputedStyle(el).fontFamily.split(",")[0].replace(/['"]/g, "").trim();
    return CFG.metrics[fam] || { asc: 0.9517, desc: 0.2412 };   // Pretendard's values when the family is unknown
  }

  // ---------------------------------------------------------------- line heights
  // LibreOffice's rules, measured on its PDFs of a test document (8, 9, 12 and 18pt, several spacings):
  //  - single spacing: each line is as high as the largest ascent plus the largest descent of the letters on it, and
  //    the baseline sits one ascent below the line's top;
  //  - exact spacing H (every w:line of layout.js, see docx2html.py): each line is H high, the baseline at 80% of H;
  //  - proportional spacing p (only with an explicit lineRule="auto"): lines after the first are p times as high, the
  //    extra above the text.
  // The ascent and descent come from the font file (fonts.py) and are forced on the browser with ascent-override and
  // descent-override, so they are the same here. Line heights are written as numbers, not `normal`: the browser rounds
  // `normal` to whole pixels (9.75pt for 8pt Pretendard instead of 9.54pt).
  function textSpans(p) { return p.querySelectorAll("span[style*='font-size']"); }
  function lineHeights(root) {
    root.querySelectorAll(".p").forEach(p => {
      const rule = p.dataset.lr, v = parseFloat(p.dataset.lh);
      const spans = textSpans(p);
      const first = spans[0] || p;
      if (rule === "exact") {
        // The block's strut alone sets the line box: H high, with its baseline at 80% (its font size is chosen so).
        const m = metrics(first);
        p.style.fontFamily = getComputedStyle(first).fontFamily;
        p.style.lineHeight = v + "pt";
        p.style.fontSize = (0.6 * v / Math.max(0.1, m.asc - m.desc)) + "pt";
        spans.forEach(s => { s.style.lineHeight = "0"; });
        // A picture on such a line does not make it taller: its margin box shrinks to nothing, it still sits on the baseline.
        p.querySelectorAll("img.inl").forEach(img => { img.style.marginTop = "-" + img.style.height; });
        // An empty paragraph has no line box at all in CSS, so it gets the line's height as its own (layout.js uses such
        // paragraphs as fixed gaps, for example the 10pt above each company band with a logo).
        if (!spans.length && !p.querySelector("img")) p.style.height = v + "pt";
        return;
      }
      if (rule === "atLeast") {                       // a minimum: the strut is the minimum, taller letters win
        p.style.lineHeight = v + "pt";
        spans.forEach(s => { const m = metrics(s); s.style.lineHeight = String(m.asc + m.desc); });
        return;
      }
      spans.forEach(s => {                           // every run: its own ascent plus descent, times p
        const m = metrics(s);
        s.style.lineHeight = String(v * (m.asc + m.desc));
      });
      if (Math.abs(v - 1) < 1e-6) return;            // single spacing needs nothing more
      const m = metrics(first);
      const tH = (m.asc + m.desc) * parseFloat(p.dataset.mx);   // text height of the paragraph's largest letters
      const extra = (v - 1) * tH;                     // what p adds to one line
      const mt = parseFloat(getComputedStyle(p).marginTop) / PX, mb = parseFloat(getComputedStyle(p).marginBottom) / PX;
      p.style.marginTop = (mt - Math.abs(extra) / 2) + "pt";    // CSS centres the extra; LibreOffice puts it above
      p.style.marginBottom = (mb - extra / 2) + "pt";           // and the first line gets none
    });
  }

  // ---------------------------------------------------------------- justified Latin lines
  // LibreOffice adds about 0.045pt less to each space of a justified English line than the line needs, so the line ends
  // that much per space short of the margin; a line with Hangul fills it, and the browser fills every line. A line cannot
  // be given its own right edge here without cutting up its runs, so a paragraph takes its lines' average. LibreOffice
  // breaks the lines first and falls short after, so a paragraph whose lines would break elsewhere keeps its full width.
  const SPACE_SHORT = 0.045 * S;                     // points each space falls short, in the page's scale
  function lineStarts(p) {                           // where each line of a paragraph starts, as character offsets
    const walk = document.createTreeWalker(p, NodeFilter.SHOW_TEXT), r = document.createRange(), out = [];
    let at = 0, top = null;                          // characters so far; the line being read
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {    // each piece of text in order
      for (const m of n.data.matchAll(/\S+/g)) {     // each word
        r.setStart(n, m.index); r.setEnd(n, m.index + 1);      // its first letter
        const b = r.getClientRects()[0];             // where that letter sits
        if (b && Math.round(b.top) !== top) { top = Math.round(b.top); out.push(at + m.index); }  // a new line starts here
      }
      at += n.data.length;                           // on to the next piece
    }
    return out.join(",");                            // comparable as one string
  }
  function justifiedLatin(root) {
    root.querySelectorAll(".p").forEach(p => {
      if (getComputedStyle(p).textAlign !== "justify") return;   // only justified paragraphs
      const text = p.textContent;                    // what it says
      if (/[\uac00-\ud7a3]/.test(text)) return;       // Hangul on the line: LibreOffice fills the margin
      const r = document.createRange();              // its lines, from their boxes
      r.selectNodeContents(p);
      const tops = new Set(Array.from(r.getClientRects()).filter(b => b.width > 0).map(b => Math.round(b.top)));  // one top per line
      if (tops.size < 2) return;                     // a single line is the last line, which is not justified
      const spaces = (text.trim().match(/\s+/g) || []).length;   // the gaps a line can stretch
      const short = SPACE_SHORT * spaces / tops.size;    // the average line's shortfall
      const before = lineStarts(p), had = p.style.paddingRight;  // the lines as they break at full width
      p.style.paddingRight = (parseFloat(getComputedStyle(p).paddingRight) / PX + short) + "pt";  // on top of what it has
      if (lineStarts(p) !== before) p.style.paddingRight = had;  // a line moved: the words must stay where they break
    });
  }

  // ---------------------------------------------------------------- tab stops

  // The left edge of the column a paragraph belongs to: the cell's content box, else the page body.
  function columnLeft(p) {
    const cell = p.closest("td");
    if (cell) {
      const r = cell.getBoundingClientRect(), cs = getComputedStyle(cell);
      return r.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft);
    }
    const body = p.closest(".body") || p.closest(".ftr");
    return body.getBoundingClientRect().left;
  }

  // The width of the text after a tab up to the next tab or the end of the paragraph.
  function segmentWidth(tab) {
    const range = document.createRange();
    range.setStartAfter(tab);
    const p = tab.closest(".p");
    const all = Array.from(p.querySelectorAll(".tab"));
    const next = all[all.indexOf(tab) + 1];
    if (next) range.setEndBefore(next); else range.setEnd(p, p.childNodes.length);
    const rects = Array.from(range.getClientRects()).filter(r => r.width > 0);
    if (!rects.length) return 0;
    return px2pt(Math.max(...rects.map(r => r.right)) - Math.min(...rects.map(r => r.left)));
  }

  function tabs(root) {
    root.querySelectorAll(".p").forEach(p => {
      const list = p.querySelectorAll(".tab");
      if (!list.length) return;
      const stops = JSON.parse(p.dataset.tabs || "[]");          // [kind, position] from the column's left edge
      const ind = parseFloat(p.dataset.ind || "0");             // a hanging indent is also a stop
      list.forEach(tab => {
        const x0 = columnLeft(p);
        const x = px2pt(tab.getBoundingClientRect().left - x0); // where the tab starts
        let stop = stops.find(s => s[1] > x + EPS);
        if (!stop && ind > x + EPS) stop = ["left", ind];
        if (!stop) stop = ["left", (Math.floor(x / DEFAULT_TAB + EPS) + 1) * DEFAULT_TAB];
        let w = stop[1] - x;                                     // a left stop: the text starts at the stop
        if (stop[0] === "right") w -= segmentWidth(tab);         // a right stop: the text ends at the stop
        else if (stop[0] === "center") w -= segmentWidth(tab) / 2;
        tab.style.width = Math.max(0, w) + "pt";
      });
    });
  }

  // ---------------------------------------------------------------- floating pictures

  function floats(root) {
    root.querySelectorAll("img.flt").forEach(img => {
      const p = img.closest(".p");
      const pr = p.getBoundingClientRect(), cs = getComputedStyle(p);
      const x = parseFloat(img.dataset.x), y = parseFloat(img.dataset.y);
      // Horizontal offsets are from the column, vertical ones from the top of the paragraph (above its border).
      const colLeft = columnLeft(p);
      const padLeft = pr.left + parseFloat(cs.borderLeftWidth);  // the containing block starts inside the border
      img.style.left = (x - px2pt(padLeft - colLeft)) + "pt";
      img.style.top = (y - parseFloat(cs.borderTopWidth) / PX) + "pt";
    });
  }

  // ---------------------------------------------------------------- pages

  // Lines of a paragraph: [top, bottom, offset of the first character] in points from the galley top.
  function lines(p, galleyTop) {
    const out = [];
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let node;
    while ((node = walker.nextNode())) {
      for (let i = 0; i < node.length; i++) {
        range.setStart(node, i); range.setEnd(node, i + 1);
        const r = range.getClientRects()[0];
        if (!r || !r.height) continue;
        const top = px2pt(r.top - galleyTop), bottom = px2pt(r.bottom - galleyTop);
        const last = out[out.length - 1];
        if (!last || top >= last.bottom - EPS * 4) out.push({ top, bottom, node, offset: i });
        else { last.top = Math.min(last.top, top); last.bottom = Math.max(last.bottom, bottom); }
      }
    }
    return out;
  }

  // Split a paragraph before a character: the first part keeps the start, a clone takes the rest.
  function splitParagraph(p, node, offset) {
    const range = document.createRange();
    range.setStart(node, offset);
    range.setEnd(p, p.childNodes.length);
    const rest = range.extractContents();
    const q = p.cloneNode(false);
    q.appendChild(rest);
    q.style.textIndent = "0";                        // the continuation is not a first line
    q.style.marginTop = "0"; q.style.borderTop = "none"; q.style.paddingTop = "0";
    p.style.marginBottom = "0"; p.style.borderBottom = "none"; p.style.paddingBottom = "0";
    if (getComputedStyle(p).textAlign === "justify") p.style.textAlignLast = "justify";  // its last line is not the paragraph's last
    p.after(q);
    return q;
  }

  // Split a table before row k: the first part keeps rows before k, a clone with the header rows takes the rest.
  function splitTable(t, k) {
    const rows = Array.from(t.rows);
    const q = t.cloneNode(false);
    const cg = t.querySelector("colgroup");
    if (cg) q.appendChild(cg.cloneNode(true));
    const tb = document.createElement("tbody");
    q.appendChild(tb);
    rows.filter(r => r.dataset.head).forEach(r => tb.appendChild(r.cloneNode(true)));   // the header repeats
    rows.slice(k).forEach(r => tb.appendChild(r));
    t.after(q);
    return q;
  }

  function paginate() {
    const g = document.getElementById("galley");
    const P = CFG.page, CH = P.h - P.top - P.bottom;            // the height of the body area
    const pages = [];
    let page = [], start = 0;                                    // blocks of the current page, galley offset of its top
    const gTop = () => g.getBoundingClientRect().top;
    const box = b => {                                           // margin box of a block in points from the galley top
      const r = b.getBoundingClientRect(), cs = getComputedStyle(b);
      return { top: px2pt(r.top - gTop()) - parseFloat(cs.marginTop) / PX, btop: px2pt(r.top - gTop()),
               bottom: px2pt(r.bottom - gTop()), mb: parseFloat(cs.marginBottom) / PX };
    };
    const keepNext = b => !!b.dataset.kn || (b.tagName === "TABLE" && !!b.querySelector(".p[data-kn]"));
    let blocks = Array.from(g.children);
    let i = 0, guard = 0;
    while (i < blocks.length && guard++ < 10000) {
      const b = blocks[i];
      // LibreOffice drops the spacing before a paragraph that starts a page after a natural break (measured: a section
      // title at the top of page 2 sat 12.5pt higher than its spacing before would put it).
      if (!page.length && pages.length && b.classList.contains("p") && !b.dataset.pb) b.style.marginTop = "0";
      const bx = box(b);
      if (!page.length) start = bx.top;                          // a page starts at its first block's margin box
      if (b.dataset.pb && page.length) {                         // a page break before this paragraph
        pages.push(page); page = []; continue;
      }
      if (bx.bottom - start <= CH + EPS) { page.push(b); i++; continue; }   // it fits
      // It does not fit. A paragraph may be split between lines, a table between rows.
      let rest = null;
      if (b.classList.contains("p") && !b.dataset.kl) {
        const ls = lines(b, gTop());
        let k = 0;
        while (k < ls.length && ls[k].bottom - start <= CH + EPS) k++;
        // Widow and orphan control: LibreOffice reads the DOCX with two lines at least on each side of a break (measured:
        // a paragraph whose last line alone would have reached the next page took the line before it along).
        if (ls.length - k < WIDOWS) k = ls.length - WIDOWS;
        if (k < ORPHANS) k = 0;
        if (k > 0 && k < ls.length) rest = splitParagraph(b, ls[k].node, ls[k].offset);
      } else if (b.tagName === "TABLE") {
        const rows = Array.from(b.rows);
        let k = 0;
        while (k < rows.length && px2pt(rows[k].getBoundingClientRect().bottom - gTop()) - start <= CH + EPS) k++;
        const heads = rows.filter(r => r.dataset.head).length;
        if (k > heads && k < rows.length) rest = splitTable(b, k);
      }
      if (rest) {                                                // the first part stays, the rest starts the next page
        page.push(b); pages.push(page); page = [];
        blocks = Array.from(g.children); i = blocks.indexOf(rest);
        continue;
      }
      // Nothing of it fits: it moves to the next page, and the blocks before it that keep with the next one go along.
      if (!page.length) { page.push(b); i++; continue; }        // taller than a page on its own: it stays and overflows
      let j = i;
      while (j > 0 && page.includes(blocks[j - 1]) && keepNext(blocks[j - 1])) j--;
      if (j < i && page.indexOf(blocks[j]) > 0) {               // a chain that does not start the page moves along
        page.splice(page.indexOf(blocks[j]));
        i = j;
      }
      pages.push(page); page = [];                               // a chain that starts the page is broken here instead
    }
    if (page.length) pages.push(page);
    return pages;
  }

  // Build the printed pages from the blocks, with a footer on each. Each page is a sheet laid out at S times the size,
  // measured and finished at that size, and only then drawn at 1/S inside a box of the printed size.
  function build(pages) {
    const P = CFG.page;
    const g = document.getElementById("galley"), tpl = document.getElementById("footer");
    const sheets = [];
    pages.forEach((blocks, n) => {
      const sh = document.createElement("div");
      sh.className = "sheet";
      sh.style.width = P.w + "pt"; sh.style.height = P.h + "pt";
      const body = document.createElement("div");
      body.className = "body";
      body.style.left = (P.left + NUDGE) + "pt"; body.style.top = (P.top + NUDGE) + "pt"; body.style.width = (P.w - P.left - P.right) + "pt";
      blocks.forEach(b => body.appendChild(b));
      sh.appendChild(body);
      if (tpl && tpl.innerHTML.trim()) {
        const f = document.createElement("div");
        f.className = "ftr body";
        f.style.left = (P.left + NUDGE) + "pt"; f.style.width = (P.w - P.left - P.right) + "pt";
        f.innerHTML = tpl.innerHTML;
        f.querySelectorAll(".fld").forEach(x => { x.textContent = x.dataset.f === "page" ? String(n + 1) : String(pages.length); });
        sh.appendChild(f);
      }
      sheets.push(sh);
    });
    g.remove();
    sheets.forEach(sh => document.body.appendChild(sh));
    // A picture anchored to the page (the blind edition's band across the top of page one, layout.js) is placed from its sheet's
    // corner, as LibreOffice places it; floats() could only place it from its paragraph, before the pages existed
    document.querySelectorAll(".sheet img.flt").forEach(img => {
      if (img.dataset.rh !== "page" && img.dataset.rv !== "page") return;   // a picture anchored to its column and paragraph stays
      const sr = img.closest(".sheet").getBoundingClientRect(), p = img.closest(".p");   // the sheet, and the paragraph the picture hangs from
      const pr = p.getBoundingClientRect(), cs = getComputedStyle(p);       // where the paragraph's box starts, inside its border
      if (img.dataset.rh === "page") img.style.left = (parseFloat(img.dataset.x) - px2pt(pr.left + parseFloat(cs.borderLeftWidth) - sr.left)) + "pt";
      if (img.dataset.rv === "page") img.style.top = (parseFloat(img.dataset.y) - px2pt(pr.top + parseFloat(cs.borderTopWidth) - sr.top)) + "pt";
    });
    // Footers sit at the footer distance from the bottom edge, growing upwards (Word's rule, which LibreOffice imports).
    document.querySelectorAll(".sheet > .ftr").forEach(f => {
      lineHeights(f); tabs(f);
      const h = px2pt(f.getBoundingClientRect().height);
      f.style.top = (P.h - P.footer - h + NUDGE) + "pt";
    });
    // Now draw each sheet at 1/S inside a page box of the printed size.
    sheets.forEach(sh => {
      const pg = document.createElement("div");
      pg.className = "page";
      pg.style.width = (P.w / S) + "pt"; pg.style.height = (P.h / S) + "pt";
      sh.before(pg);
      pg.appendChild(sh);
      sh.style.transform = "scale(" + (1 / S) + ")";
    });
    return sheets.length;
  }

  async function run() {
    try {
      await Promise.all(Array.from(document.fonts).map(f => f.load().catch(() => null)));   // every face, before measuring
      await document.fonts.ready;
      const g = document.getElementById("galley");
      lineHeights(g);
      justifiedLatin(g);
      tabs(g);
      floats(g);
      const pages = paginate();
      const n = build(pages);
      window.OWL_RESULT = { pages: n };
    } catch (e) {
      window.OWL_RESULT = { error: String(e && e.stack || e) };
    }
    document.documentElement.setAttribute("data-owl-ready", window.OWL_RESULT.error ? "error" : "1");
    document.documentElement.setAttribute("data-owl-result", JSON.stringify(window.OWL_RESULT));
  }
  run();
})();
