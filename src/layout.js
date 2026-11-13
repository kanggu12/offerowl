// Typesetting engine shared by every resume script. Content stays in the scripts that call it (resume_form.js); only
// layout lives here.
// Every document shares this one copy, so a fix reaches all of them.
const fs = require("fs");
const { execFileSync } = require("child_process");
const {
  Document, Packer, Paragraph, TextRun: DocxTextRun, AlignmentType, BorderStyle,
  Table, TableRow, TableCell, WidthType, convertInchesToTwip, Footer, PageNumber,
  PositionalTab, PositionalTabAlignment, PositionalTabRelativeTo, PositionalTabLeader, TabStopType,
  ShadingType, VerticalAlign, ExternalHyperlink, ImageRun, HeightRule,
  HorizontalPositionRelativeFrom, VerticalPositionRelativeFrom, TextWrappingType,
} = require("docx");
// Blind edition, for a copy to show in public (OFFEROWL_BLIND=1; docs/USAGE.md). The masking bars are painted by save.js when it writes the
// docx; this file only cuts the contact links and puts a banner strip on page 1.
const BL = require("./blind");
const TextRun = DocxTextRun;

// The fonts until setFont() picks another. The container has TeX Gyre Pagella (fonts-texgyre), with the same metrics as Palatino.
const F = {
  ascii: "Palatino Linotype",
  hAnsi: "Palatino Linotype",
  cs: "Palatino Linotype",
  eastAsia: "NanumGothic",
};
const INK = "1F1F1F", BODY = "333333", MID = "2B2B2B", GREY = "6B6B6B", FAINT = "9A9A9A", LINE = "D8D8D8";

// Right tab stop at 10366 twips. It is 40 twips short of the body width (10406), so a date ends 1.5pt to the left of
// the section rule, on purpose.
const RTAB = 10366;
const NONE = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };

function run(text, o = {}) {
  return new TextRun({ text, font: F, size: o.size || 18, bold: !!o.bold,
    italics: !!o.italics, color: o.color || INK, characterSpacing: o.cs || 0,
    ...(o.br ? { break: o.br } : {}),
    ...(o.raise ? { position: o.raise + "pt" } : {}),
    ...(LANG_KO ? { language: { value: "en-US", eastAsia: "ko-KR" } } : {}),
    ...(o.fill ? { shading: { type: ShadingType.CLEAR, fill: o.fill, color: "auto" } } : {}) });
}
// Highlight marking. A ==phrase== inside a text is painted on a pale yellow background (FFF0A0, not a saturated
// highlighter yellow). The marker characters do not appear in the render.
const HILITE = "FFF0A0";
// What rich() set, for the line checks (src/check_lines.py): every highlighted phrase in the order it was drawn, and every
// paragraph it set (the introduction, a card's cells, a competency, an item, about me, the motivation) without its marks.
// render() writes them beside the document as <name>.highlights.json; the checks find each in the PDF's word boxes and
// say whether a highlight broke across two lines, how long it is, and whether a paragraph ends on a word of its own
const HIGHLIGHTS = [];
const PARAS = [];
function rich(text, o = {}) {
  PARAS.push(String(text).replace(/==/g, ""));                                  // the paragraph as it reads
  // split() with a capture group puts the captured (marked) phrases at the odd positions. Empty pieces are filtered out
  // only after the pairing, so the parity stays right
  return String(text).split(/==(.+?)==/)
    .map((t, i) => [t, i % 2 === 1]).filter(([t]) => t !== "")
    .map(([t, marked]) => { if (marked) HIGHLIGHTS.push(t); return run(t, marked ? { ...o, fill: HILITE, color: INK } : o); });   // a highlight, in drawing order
}
function p(text, o = {}) {
  return new Paragraph({
    alignment: o.align || AlignmentType.LEFT,
    keepNext: !!o.keepNext,
    spacing: { before: o.before || 0, after: o.after === undefined ? 40 : o.after,
      ...(o.line ? { line: o.line } : {}) },
    children: Array.isArray(text) ? text : [run(text, o)],
  });
}
const CONTENT_W = 11906 - 750 - 750;

// The career-description layout: education, career summary, core competencies, skills, detailed career, other items,
// about me, motivation.

// The plain look: section titles keep only their rule (no accent bar, no faint English name), the about-me stages lose
// their rails and bands, the card tables their outer white borders and the quote box its bar. Set per document (setPlain)
// by an edition made in that look; the default is the full look.
let PLAIN = false;
function setPlain(v) { PLAIN = !!v; }

// Prose paragraph (about me, motivation)
function prose(text, o = {}) {
  return new Paragraph({
    spacing: { after: o.after ?? 80, line: o.line ?? 266 },   // a cover letter passes its own gap and line, sized to fill its page
    alignment: AlignmentType.BOTH,
    // rail draws a thin vertical line on the left, in the theme's rule color, which links the about-me stages like a
    // vertical timeline.
    // The plain look starts the paragraph at the body's left edge, with no line.
    ...(o.rail && !PLAIN ? { border: { left: { style: BorderStyle.SINGLE, size: 12, color: mix_rail(), space: 10 } },
                  indent: { left: 200 } } : {}),
    children: rich(text, { size: 18, color: BODY }),
  });
}
function mix_rail() { return T.rule; }

// The look: a band for the name cell, bold section titles with an underline, a band for each company, an underlined
// department line, bullets, and a band for the about-me section.
// Color sets: each set uses a single accent color, and the body text stays grey whichever set is chosen. The sets are
// in src/themes.json (its header explains the choices). OFFEROWL_THEME picks one, and a JSON file named by
// OFFEROWL_THEME_FILE adds sets or overrides sets of the same name (for example someone else's colors).
const { THEMES, theme } = require("./theme_load"); // color set loader (validates values; an unknown name stops with a clear message)
let T = theme(process.env.OFFEROWL_THEME || "mono");
// Changes the font. The career-description layout is set in Pretendard alone, following the convention that a Korean
// resume builds its hierarchy from the weights of one sans-serif family and does not mix a serif Latin face with a
// sans-serif Hangul face.
function setFont(name) { F.ascii = F.hAnsi = F.cs = F.eastAsia = name; }
function setTheme(name) { if (!process.env.OFFEROWL_THEME) T = theme(name); }
function accent2() { return T.acc2 || T.acc; }
const shade = fill => ({ type: ShadingType.CLEAR, fill, color: "auto" });
// en is the faint English section name at the right edge (OVERVIEW and the like).
function fsec(title, note, en) {
  const kids = [run(title, { bold: true, size: 24, color: T.sec })];   // 12 pt: a step above the company bands (11 pt) and sub-headings (10 pt)
  if (note) kids.push(run(note, { size: 18, color: GREY }));
  if (en && !PLAIN) { kids.push(run("\t")); kids.push(run(en, { size: 14, color: "8A94A3", cs: 40 })); }   // no English name in the plain look
  return new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: RTAB - 140 }],
    spacing: { before: 250, after: 100 },
    keepNext: true,
    // Outline level 1: LibreOffice exports it as a PDF bookmark (the table of contents beside the viewer)
    outlineLevel: 0,
    // A thick accent bar on the left and a thin rule below; the plain look keeps the rule only
    border: PLAIN ? { bottom: { style: BorderStyle.SINGLE, size: 6, color: T.rule, space: 3 } }
      : { bottom: { style: BorderStyle.SINGLE, size: 6, color: T.rule, space: 3 },
          left: { style: BorderStyle.SINGLE, size: 36, color: accent2(), space: 6 } },
    indent: { left: PLAIN ? 0 : 140 },
    children: kids,
  });
}
// Grey band. Used for the company heading in the detailed career and for the stage titles of the about-me section.
function fband(left, right, o = {}) {
  if (o.logo && fs.existsSync(o.logo)) return fbandLogo(left, right, o);
  // An about-me stage in the plain look is a bold title in the section color, with no band and no rail
  if (PLAIN && o.rail) return new Paragraph({ spacing: { before: 200, after: 60 }, keepNext: true,
    children: [run(left, { bold: true, size: 20, color: T.sec })] });
  return new Paragraph({
    spacing: { before: o.before === undefined ? 200 : o.before, after: 50, line: 300 },
    keepNext: true,
    shading: shade(T.band),
    ...(o.rail ? { border: { left: { style: BorderStyle.SINGLE, size: 36, color: T.acc, space: 8 } },
                  indent: { left: 180 } } : {}),
    tabStops: [{ type: TabStopType.RIGHT, position: RTAB }],
    children: [
      // Sized to fit inside the band height (15pt); at 18px the logo stuck out above and below the band
      ...(o.logo ? logoRun(o.logo, 13) : []),
      // The stage-title band (rail) raises its text by 1pt: the center of the rendered ink was 0.7 to 1.0pt below the
      // band center (measured)
      run(left, { bold: true, size: 20, color: T.bandText, ...(o.rail ? { raise: 1 } : {}) }),
      // A small badge next to the company name
      ...(o.badge ? [run("  "), run("\u00a0" + o.badge + "\u00a0", { size: 15, bold: true, color: "FFFFFF", fill: accent2() })] : []),
      run("\t"),
      ...(o.place ? [run(o.place + "   ", { size: 16, color: GREY })] : []),
      run(right || "", { bold: !!o.boldRight, size: 18, color: o.boldRight ? INK : GREY }),
    ],
  });
}
// Company band with a logo. The band is an ordinary shaded paragraph, and the logo is a picture floating on that
// paragraph, placed at the left and centered vertically. It is not drawn as a one-row table, because LibreOffice does
// not keep a table together with the next line across a page break, which can leave a company band alone at the bottom
// of a page. A paragraph honors keepNext. The line height is fixed (BAND_H) and the picture is moved down by half of
// the difference between BAND_H and the logo height to center it.
function fbandLogo(left, right, o) {
  // The space before the band comes from an empty paragraph of fixed height right before it, not from the band
  // paragraph's own before. The picture's vertical reference is the top of the paragraph including its before spacing,
  // and LibreOffice shrinks or drops before in some places (top of a page, right after a section title), so the logo
  // sat differently each time; in a band at the top of a page it stuck out 3.6pt below the band (pixel measurement).
  // With before at 0 the reference is always the top of the band.
  const BAND_H = 24, LOGO = 18, GAP = (o.before === undefined ? 200 : o.before);   // BAND_H and LOGO are in pt; GAP is in twips
  // Text is centered vertically with equal inner padding above and below (PAD). Giving the line the full band height
  // (24pt) and raising the text does not work: LibreOffice seats the text near the bottom of such a line, and even
  // after raising everything by 3.5pt the rendered ink sat below the band center (company name 1.3pt, badge 3.7pt,
  // location 2.4pt, period 1.9pt). A badge box cannot be centered by raising it either, because its background box only
  // stretches down by the amount raised (it is drawn to the bottom of the line). The padding is the inner spacing of a
  // border in the band's own color (whole points). Smaller text on the same baseline looks lower, so it is raised a
  // little (RAISE). A band check measures the center of each element.
  const PAD = 5, LINE = BAND_H - 2 * PAD - 0.5;   // 0.5 = thickness of the top and bottom borders
  const RAISE = { name: 0, place: 2, right: 1 };
  // The badge is a floating picture. Drawn as a text background, its box would stretch down by the amount the text is
  // raised, leaving the text against the top of the box. badge.py draws the box and measures the company name's width
  // in Pretendard. The company name starts at the left tab (28pt) and the badge sits 5pt after it.
  const BADGE_H = 9, NAME_X = 28, BADGE_GAP = 5;
  const data = fs.readFileSync(o.logo);
  const emu = pt => Math.round(pt * 12700);
  const img = new ImageRun({ type: "png", data, transformation: { width: LOGO * 4 / 3, height: LOGO * 4 / 3 },
    floating: {
      horizontalPosition: { relative: HorizontalPositionRelativeFrom.COLUMN, offset: emu(4) },
      verticalPosition: { relative: VerticalPositionRelativeFrom.PARAGRAPH, offset: emu((BAND_H - LOGO) / 2 + BAND_NUDGE) },
      wrap: { type: TextWrappingType.NONE }, allowOverlap: true, behindDocument: false,
    } });
  let badge = [];
  if (o.badge) {
    const dir = __dirname + "/../output/_fig";
    fs.mkdirSync(dir, { recursive: true });
    const out = dir + "/badge_" + Buffer.from(o.badge + "|" + left).toString("hex").slice(0, 40) + ".png";
    const info = JSON.parse(execFileSync("python3", [__dirname + "/badge.py", out, o.badge, left, "11", "7.5", String(BADGE_H), accent2()]).toString());
    badge = [new ImageRun({ type: "png", data: fs.readFileSync(out),
      transformation: { width: info.w * 4 / 3, height: BADGE_H * 4 / 3 },
      floating: {
        horizontalPosition: { relative: HorizontalPositionRelativeFrom.COLUMN, offset: emu(NAME_X + info.name_w + BADGE_GAP) },
        verticalPosition: { relative: VerticalPositionRelativeFrom.PARAGRAPH, offset: emu((BAND_H - BADGE_H) / 2 + BAND_NUDGE) },
        wrap: { type: TextWrappingType.NONE }, allowOverlap: true, behindDocument: false,
      } })];
  }
  return [
    new Paragraph({ spacing: { before: 0, after: 0, line: GAP, lineRule: "exact" }, keepNext: true, children: [] }),
    new Paragraph({
      spacing: { before: 0, after: 50, line: Math.round(LINE * 20), lineRule: "exact" },
      keepNext: true,
      shading: shade(T.band),
      border: { top: { style: BorderStyle.SINGLE, size: 2, color: T.band, space: PAD },
                bottom: { style: BorderStyle.SINGLE, size: 2, color: T.band, space: PAD } },
      tabStops: [{ type: TabStopType.LEFT, position: 560 }, { type: TabStopType.RIGHT, position: RTAB }],
      children: [
        img,
        ...badge,
        run("\t"),
        run(left, { bold: true, size: 22, color: T.bandText, raise: RAISE.name }),
        run("\t"),
        ...(o.place ? [run(o.place + "   ", { size: 16, color: GREY, raise: RAISE.place })] : []),
        run(right || "", { bold: !!o.boldRight, size: 18, color: o.boldRight ? INK : GREY, raise: RAISE.right }),
      ],
    }),
  ];
}
// Vertical correction for the logo, in pt. It is set by measuring the offset between the band center and the logo
// center in a render.
let BAND_NUDGE = 0;
// Department and title line under the band: bold and underlined, as in the form
function fsub(text) {
  return new Paragraph({
    spacing: { before: 50, after: 70 },
    keepNext: true,
    children: [new TextRun({ text, font: F, size: 18, bold: true, color: T.acc === INK ? MID : T.acc, underline: {} })],
  });
}
// Bullet item: the head is bold and the text is justified, as in the form
function fbul(head, body, o = {}) {
  return new Paragraph({
    spacing: { after: o.after === undefined ? 60 : o.after, line: 250 },   // 3 pt between items (was 2.5)
    keepNext: !!o.keepNext,
    // Body bullets are justified, as in the form. Justification can spread a line out letter by letter; the form-mode
    // verification catches that.
    alignment: AlignmentType.BOTH,
    indent: { left: 300, hanging: 200 },
    // The bullet is followed by a tab. With a space, justification stretched that space too, and the first letter
    // landed in a different place in each item
    tabStops: [{ type: TabStopType.LEFT, position: 300 }],
    children: [
      // o.weak marks a competency outside the job description. It is only placed later by the caller; this function
      // draws it like any other item, without fading.
      run("\u2022\t", { size: 18, color: accent2() }),
      run(head ? head + ": " : "", { size: 18, bold: true, color: T.acc }),
      ...rich(body, { size: 18, color: BODY }),
    ],
  });
}
// Splits the skills table into two layers according to the job description.
// focus lists the category names to put in the front layer, in that order; the other rows follow in their original
// order. Without focus the rows come back unchanged. A category name
// that is not in the table stops the build, so a typo is never ignored silently.
// strong (o.skillsStrong): only the skill names the job needs are set in bold. The row order, the order inside a cell
// and the category column stay as they are; only the weight changes. A skill name that is not in the table stops the
// build.
function strongItems(rows, strong, hiList) {
  const items = r => (typeof r[1] === "string" ? r[1] : r[1].t).split(", ");
  const plain = x => x.replace(/\u00a0/g, " ");
  const all = new Set(rows.flatMap(items).map(plain));
  const unknown = strong.filter(x => !all.has(x));
  if (unknown.length) throw new Error("skillsStrong에 표에 없는 기술: " + unknown.join(", "));
  // Bold names also get a yellow fill, name by name; the commas between them do not.
  return rows.map(r => {
    const parts = [];
    items(r).forEach((x, k) => {
      // Bold applies to every skillsStrong name, but the yellow fill only to those also in skillsHighlight (with nearly
      // thirty fills the marking lost its effect)
      const st = strong.includes(plain(x)), hl = st && (hiList || strong).includes(plain(x));
      if (k) parts.push({ t: ", " });
      parts.push(st ? (hl ? { t: x, bold: true, hl: true } : { t: x, bold: true }) : { t: x });
    });
    // Adjacent pieces with the same weight and no fill are merged into one (the commas and the skills without a fill)
    const same = (x, y) => !!x.hl === !!y.hl && !!x.bold === !!y.bold;
    const merged = parts.reduce((a, x) => (a.length && !x.hl && same(a[a.length - 1], x) ? (a[a.length - 1].t += x.t, a) : [...a, { ...x }]), []);
    return [r[0], { t: items(r).join(", "), parts: merged }];
  });
}
// edit (o.skillsEdit): { order: [category...], text: { category: skill list } }. A resume for a job of a different
// kind (a data science role, say) reorders the rows, rewrites cell text, and adds a category that is not in the table
// as a new row. Rows that order does not name stay at the end in their original order, so none are dropped. Without an
// edit the table is unchanged.
function editRows(rows, edit) {
  if (!edit) return rows;
  const name = r => (typeof r[0] === "string" ? r[0] : r[0].t);
  const text = edit.text || {};
  const base = rows.map(r => (text[name(r)] ? [r[0], text[name(r)]] : r));
  const extra = Object.keys(text).filter(k => !rows.some(r => name(r) === k)).map(k => [k, text[k]]);
  const all = [...base, ...extra], order = edit.order || [];
  const unknown = order.filter(k => !all.some(r => name(r) === k));
  if (unknown.length) throw new Error("skillsEdit.order 에 표에 없는 분류: " + unknown.join(", "));
  // edit.only keeps just the rows named in order
  if (edit.only) return order.map(k => all.find(r => name(r) === k));
  return [...order.map(k => all.find(r => name(r) === k)), ...all.filter(r => !order.includes(name(r)))];
}
function focusRows(rowsIn, focus, strongList, hiList, edit) {
  const rows = editRows(rowsIn, edit);
  if (strongList) return strongItems(rows, strongList, hiList);         // bold per skill name (rows are not faded)
  if (!focus) return rows;                                   // an edition that does not use the two layers
  const name = r => (typeof r[0] === "string" ? r[0] : r[0].t);
  const unknown = focus.filter(f => !rows.some(r => name(r) === f));
  if (unknown.length) throw new Error("skillsFocus에 표에 없는 분류: " + unknown.join(", "));
  const strong = focus.map(f => rows.find(r => name(r) === f)); // front layer: the categories the job asks for, in the order given
  // back layer: the rest in their original order, in the same type as the front layer (no fading)
  const weak = rows.filter(r => !focus.includes(name(r)));
  return [...strong, ...weak];
}

// Table: a grid of grey lines, a shaded header row and a lightly shaded first column (the category column).
// A cell is a string or { t, bold, fill, rows, cols, color, center }.
const TLINE = { style: BorderStyle.SINGLE, size: 4, color: "C8C8C8" };
const TBORDER = { top: TLINE, bottom: TLINE, left: TLINE, right: TLINE,
  insideHorizontal: TLINE, insideVertical: TLINE };
function tcell(c, width, keep = false, bare = false) {
  if (typeof c === "string") c = { t: c };
  const lines = String(c.t).split("\n");
  // A cell that holds only a logo tile: one square picture in the center
  if (c.img) return new TableCell({
    width: { size: width, type: WidthType.DXA }, rowSpan: c.rows, verticalAlign: VerticalAlign.CENTER,
    margins: { top: 40, bottom: 40, left: 60, right: 60 },
    children: [new Paragraph({ alignment: AlignmentType.CENTER, keepNext: keep, spacing: { after: 0 },
      children: logoRun(c.img, c.px || 24).slice(0, 1) })],
  });
  // A logo to the left of the name. A borderless two-column table inside the cell centers the logo
  // against the height of the name and location lines. A separate logo column looked detached from the name.
  if (c.logoLeft) {
    const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
    const lw = 420, inner = width - 200 - lw;
    const rest = { ...c, logoLeft: null };
    return new TableCell({
      width: { size: width, type: WidthType.DXA }, rowSpan: c.rows, columnSpan: c.cols,
      verticalAlign: VerticalAlign.CENTER, margins: { top: 30, bottom: 30, left: 100, right: 100 },
      shading: c.fill ? shade(c.fill) : undefined,
      children: [new Table({
        width: { size: width - 200, type: WidthType.DXA }, columnWidths: [lw, inner],
        borders: { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB },
        rows: [new TableRow({ cantSplit: true, children: [
          new TableCell({ width: { size: lw, type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
            margins: { top: 0, bottom: 0, left: 0, right: 60 },
            children: [new Paragraph({ spacing: { after: 0 }, keepNext: keep, children: logoRun(c.logoLeft, 22).slice(0, 1) })] }),
          tcell(rest, inner, keep, true),
        ] })],
      }), new Paragraph({ spacing: { after: 0, line: 20, lineRule: "exact" }, children: [] })],
    });
  }
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    rowSpan: c.rows, columnSpan: c.cols,
    verticalAlign: VerticalAlign.CENTER,
    margins: bare ? { top: 0, bottom: 0, left: 0, right: 0 } : { top: 40, bottom: 40, left: 100, right: 100 },
    shading: c.fill ? shade(c.fill) : undefined,
    // c.parts: runs of text inside one paragraph (the skill names of the two-layer skills table), each with its own
    // color and size
    children: c.parts ? [new Paragraph({ spacing: { after: 0, line: 230 }, keepNext: keep,
      children: c.parts.map(x => run(x.t, { size: x.size || c.size || 17, bold: !!x.bold, color: x.hl ? INK : x.color || BODY, ...(x.hl ? { fill: HILITE } : {}) })) })]
    : lines.map((ln, i) => new Paragraph({
      alignment: c.center ? AlignmentType.CENTER : c.right ? AlignmentType.RIGHT : AlignmentType.LEFT,
      spacing: { after: 0, line: 230 },
      // keep stops the table from breaking between pages (keepNext on every row except the last)
      keepNext: keep,
      children: [...(i === 0 && c.logo ? logoRun(c.logo, 13) : []), c.link
        ? new ExternalHyperlink({ link: c.link, children: [new TextRun({ text: ln, font: F, size: c.size || 17,
            color: c.color || BODY, underline: {} })] })
        // c.subSize: size of the second and later lines (the grey secondary lines); used for the location and the
        // school name in logo cells
        : run(ln, { size: (i && c.subSize) || c.size || 17, bold: !!c.bold, color: c.color || (i ? GREY : BODY) })],
    })),
  });
}
// widths are in twips and must add up to CONTENT_W. o.head is the header row; o.key says whether the first column is
// shaded as the category column
function ftable(widths, rows, o = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  if (Math.abs(total - CONTENT_W) > 2) throw new Error(`표 폭 ${total} != ${CONTENT_W}`);
  const out = [];
  if (o.head) out.push(new TableRow({ cantSplit: true, tableHeader: true,
    children: o.head.map((h, i) => tcell({ t: h, bold: true, fill: T.head, center: true, color: T.headText }, widths[i], false)) }));
  rows.forEach((r, ri) => {
    // No keepNext is set in table cells, whether or not o.split is given. LibreOffice reads a keepNext inside a cell as
    // applying to the whole table, which moves the table to the next page as one block and leaves the bottom of the
    // previous page empty (even a four-row table did this). Rows are cantSplit, so a row never splits, and the header
    // row is repeated on the next page (tableHeader).
    const keep = false;
    // A merge can remove cells from a row. The missing ones are the leading columns, so the widths are matched from the
    // back of the row
    const off = widths.length - r.reduce((a, c) => a + ((c && c.cols) || 1), 0);
    let col = off;
    out.push(new TableRow({ cantSplit: true, children: r.map((c, i) => {
      const span = (c && c.cols) || 1;
      const w = widths.slice(col, col + span).reduce((a, b) => a + b, 0);
      const isKey = o.key && col === 0;
      const al = o.align && o.align[col];
      col += span;
      if (typeof c === "string") c = { t: c };
      // o.align gives "c" (center) or "r" (right) per column; periods, dates and numbers are centered
      if (al === "c") c = { center: true, ...c };
      if (al === "r") c = { right: true, ...c };
      return tcell(isKey ? { bold: true, fill: T.key, color: T.acc, ...c } : c, w, keep);
    }) }));
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    borders: TBORDER,
    rows: out,
  });
}
// Small inline picture at a fixed height. Nothing is inserted when the file is missing.
// Logo files are trademarks, so they are not kept in the repository, only in output/_logos/.
function logoRun(path, hpx = 14) {
  if (!path || !fs.existsSync(path)) return [];
  const data = fs.readFileSync(path);
  const w = data.readUInt32BE(16), h = data.readUInt32BE(20);
  return [new ImageRun({ type: "png", data, transformation: { width: Math.round(w * hpx / h), height: hpx } }), run("  ")];
}
// Picture (a PNG made by the figure scripts), fitted to the body width. The size is read from the PNG header.
function fimage(path, o = {}) {
  const data = fs.readFileSync(path);
  const w = data.readUInt32BE(16), h = data.readUInt32BE(20);
  const width = 694, height = Math.round(h * width / w);
  return new Paragraph({
    spacing: { before: o.before || 40, after: o.after === undefined ? 80 : o.after },
    keepNext: !!o.keepNext,
    children: [new ImageRun({ type: "png", data, transformation: { width, height } })],
  });
}
// Overview cards: a two-column grid of lightly tinted cells, each with a bold accent-colored head and a body text.
// Thick white lines separate the cells.
function fcards(items) {
  const GAP = { style: BorderStyle.SINGLE, size: 36, color: "FFFFFF" };
  const half = Math.round(CONTENT_W / 2);
  // The card cells and the selected-project cells are not tied to the next section. LibreOffice reads a keepNext on a
  // paragraph inside a table as applying to the whole table, which chains everything from the cards to the career
  // summary table into one block. As soon as the table grows a little, the whole block moves to the next page and
  // leaves the bottom of page 1 empty. Rows are cantSplit, so a row never splits inside the table.
  const cellOf = ([h, b], last) => new TableCell({
    width: { size: half, type: WidthType.DXA },
    margins: { top: 60, bottom: 60, left: 160, right: 160 },
    shading: shade(T.band),
    children: [
      new Paragraph({ spacing: { after: 40 }, keepNext: false,
        children: [run(h, { size: 16, bold: true, color: accent2() })] }),
      new Paragraph({ spacing: { after: 0, line: 250 }, keepNext: false,
        children: rich(b, { size: 17, color: INK }) }),
    ],
  });
  const rows = [];
  for (let i = 0; i < items.length; i += 2) {
    const last = i + 2 >= items.length;
    rows.push(new TableRow({ cantSplit: true, children: [cellOf(items[i], last), cellOf(items[i + 1], last)] }));
  }
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [half, CONTENT_W - half],
    // The plain look drops the outer white borders at the sides, so the cards line up with the body's edges
    borders: { top: GAP, bottom: GAP, left: PLAIN ? NONE : GAP, right: PLAIN ? NONE : GAP, insideHorizontal: GAP, insideVertical: GAP },
    rows,
  });
}
// Quote block with a thick accent bar on the left: one paragraph about the person, such as a working-style note
function fquote(head, text) {
  // The plain look: the heading and the paragraph without the bar
  if (PLAIN) return [
    new Paragraph({ spacing: { before: 60, after: 30 }, keepNext: true, children: [run(head, { size: 16, bold: true, color: T.acc })] }),
    new Paragraph({ spacing: { after: 60, line: 270 }, children: [run(text, { size: 18, color: INK })] }),
  ];
  return [
    new Paragraph({ spacing: { before: 60, after: 30 }, keepNext: true,
      border: { left: { style: BorderStyle.SINGLE, size: 24, color: T.acc, space: 8 } }, indent: { left: 160 },
      children: [run(head, { size: 16, bold: true, color: T.acc })] }),
    new Paragraph({ spacing: { after: 60, line: 270 },
      border: { left: { style: BorderStyle.SINGLE, size: 24, color: T.acc, space: 8 } }, indent: { left: 160 },
      children: [run(text, { size: 18, color: INK })] }),
  ];
}
// Two-column page header: a navy cell on the left with the name and the English tagline, a pale cell on the right with
// the contacts. It absorbs the personal-information table.
// A photo (photo: { file, layout }) adds a photo cell on the left of the navy cell. The contact cell is nearly full (a
// long profile URL leaves almost no spare width), so the photo's width is taken from the name cell. The photo cell is a
// 3:4 portrait, about 61pt wide at the 81pt header height (PHOTO_W, PHOTO_H). The usual resume photo convention is a
// 3:4 portrait down to the chest; a wider cell could only be filled by cropping a 3:4 original at the top and bottom,
// which enlarged the face and cut the shoulders. The header height (five contact lines) does not change.
// With layout "flush" the photo fills its cell; with "frame" a 3:4 photo (53x71pt) sits inside a 5pt navy border. The
// blind edition has no photo (a face is personal information that must be hidden).
// LibreOffice also applies the largest top and bottom cell margin of a row (8pt in the name cell) to the photo cell,
// which grew the header from 81pt to 97pt and pushed the document to seven pages. With a photo, all three cells
// therefore get 0 top and bottom margin and rely on vertical centering. Fixing the photo row height (exact) clips 16pt
// below the photo (measured).
// A photo whose backdrop is lighter than the card navy keeps the photo cell visibly apart from the name cell.
const PHOTO_W = 1215, PHOTO_H = 1620;
function fheader(name, en, tag, contacts, photo) {
  // In the blind edition the contact lines stay in place and only the value is covered by a single bar (save.js,
  // mask_whole in blind.json). A value that would survive inside a link, such as a mail link, is unlinked: the labels in
  // contacts_unlink, and any contact whose value or address the table covers (the bar hides the words, not the link).
  if (BL.on) contacts = contacts.map(c => BL.T.contacts_unlink.includes(c[0]) || BL.hit(c[1]) || BL.hit(c[2]) ? [c[0], c[1]] : c);
  const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const pic = photo && !BL.on ? photo : null;
  // photo.w (in pt) sets the width of the photo cell; PHOTO_W applies when it is absent
  const PW = pic && pic.w ? Math.round(pic.w * 20) : PHOTO_W;
  const lw = pic ? 4700 - PW : 4700;
  const cells = [];
  if (pic) {
    // Even in the flush layout the photo is inset by 0.5pt at the top, bottom and left. A bitmap edge covers its pixels
    // completely, while the navy and contact fills are drawn with soft edges, so even when both end at the same
    // position the photo appears one pixel outside the card. The outer edge of the card is always drawn by the fills.
    const flush = pic.layout !== "frame", m = flush ? 0 : 100, inset = flush ? 10 : 0;
    const h = (PHOTO_H - 2 * m - 2 * inset) / 20, w = flush ? (PW - inset) / 20 : h * 3 / 4;
    cells.push(new TableCell({
      width: { size: PW, type: WidthType.DXA }, shading: shade(T.nameFill), verticalAlign: VerticalAlign.CENTER,
      // The photo cell and the name cell are two navy fills that touch, and a one-pixel light line shows at their
      // border in the PDF view (measured at 400dpi). A border of the same navy is drawn over the seam to cover it.
      borders: { right: { style: BorderStyle.SINGLE, size: 6, color: T.nameFill } },
      margins: { top: m, bottom: m, left: m + inset, right: 0 },
      children: [new Paragraph({ spacing: { before: 0, after: 0 },
        children: [new ImageRun({ type: /\.jpe?g$/i.test(pic.file) ? "jpg" : "png", data: fs.readFileSync(pic.file), transformation: { width: w * 4 / 3, height: h * 4 / 3 } })] })],   // a JPEG kept as a JPEG
    }));
  }
  const left = new TableCell({
    width: { size: lw, type: WidthType.DXA }, shading: shade(T.nameFill),
    // With a photo and a two-line tagline, the name block would crowd the photo and leave a wide empty navy area on the
    // right, so the left margin is larger only for a two-line tagline. At 330 the block (its first tagline line is
    // 136pt wide) is centered in the name cell.
    verticalAlign: VerticalAlign.CENTER, margins: { top: pic ? 0 : 160, bottom: pic ? 0 : 160, left: pic ? (tag.includes("\n") ? 330 : 140) : 280, right: pic ? 100 : 200 },
    children: [
      new Paragraph({ spacing: { after: 30 }, children: [run(name, { size: 44, bold: true, color: T.nameText, cs: 20 }),
        run("  " + en, { size: 20, color: T.nameText })] }),
      // A \n in the tagline is a line break. The photo cell narrows the name cell, so a long posting title is split
      // into two lines.
      new Paragraph({ spacing: { after: 0 }, children: tag.split("\n").map((t, i) => run(t, { size: 14, bold: true, color: T.nameText, cs: 16, br: i ? 1 : 0 })) }),
    ],
  });
  const right = new TableCell({
    width: { size: CONTENT_W - 4700, type: WidthType.DXA }, shading: shade(T.band),
    verticalAlign: VerticalAlign.CENTER, margins: { top: pic ? 0 : 100, bottom: pic ? 0 : 100, left: 260, right: 200 },
    children: contacts.map(([k, v, link]) => new Paragraph({
      spacing: { after: 20, line: 240 },
      tabStops: [{ type: TabStopType.LEFT, position: 1250 }],
      children: [run(k, { size: 15, bold: true, color: T.acc }), run("\t"),
        link ? new ExternalHyperlink({ link, children: [new TextRun({ text: v, font: F, size: 16, color: INK })] })
             : run(v, { size: 16, color: INK })],
    })),
  });
  const table = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [...(pic ? [PW] : []), lw, CONTENT_W - 4700],
    borders: { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB },
    rows: [new TableRow({ cantSplit: true, ...(pic ? { height: { value: PHOTO_H, rule: HeightRule.ATLEAST } } : {}), children: [...cells, left, right] })],
  });
  if (!BL.on) return table;
  // Blind-edition marker: a dark red strip across the full page width at the very top edge of page 1 (blind_banner.py).
  // It fits inside the top margin (17pt), so the body layout does not move. It hangs from a paragraph 1pt high.
  const dir = __dirname + "/../output/_fig";
  fs.mkdirSync(dir, { recursive: true });
  const [label, note] = BL.T.banner[BL.lang];
  // One picture per wording and colour: two editions made with different tables (two panels can share this folder) never take
  // each other's band, and the same band is drawn over itself
  const key = require("crypto").createHash("sha1").update([label, note, BL.T.mark_fill].join("|")).digest("hex").slice(0, 10);
  const out = dir + "/blind_banner_" + BL.lang + "_" + key + ".png", PAGE_W = 11906 / 20, BAND_H = 14.5;
  execFileSync("python3", [__dirname + "/blind_banner.py", out, String(PAGE_W), String(BAND_H), label, note]);
  const emu = pt => Math.round(pt * 12700);
  const band = new ImageRun({ type: "png", data: fs.readFileSync(out), transformation: { width: PAGE_W * 4 / 3, height: BAND_H * 4 / 3 },
    floating: {
      horizontalPosition: { relative: HorizontalPositionRelativeFrom.PAGE, offset: 0 },
      verticalPosition: { relative: VerticalPositionRelativeFrom.PAGE, offset: 0 },
      wrap: { type: TextWrappingType.NONE }, allowOverlap: true, behindDocument: false,
    } });
  return [table, new Paragraph({ spacing: { before: 0, after: 0, line: 20, lineRule: "exact" }, children: [band] })];
}
// A colour between two hex colours: t of the way from a to b
function mixHex(a, b, t) {
  const c = (h, i) => parseInt(h.slice(i, i + 2), 16);
  return [0, 2, 4].map(i => Math.round(c(a, i) + (c(b, i) - c(a, i)) * t).toString(16).padStart(2, "0")).join("").toUpperCase();
}
// Selected-project cards (usually three): a navy title band on top, then one row for each label (problem, action,
// result), so a label stands at the same height in every card and a shorter card's room sits inside its rows instead
// of under them; a hairline divides the rows. (Until 2026-11-13 each card was one cell: its labels stood at different
// heights from its neighbours' and the short cards ended in an empty block, "안예쁜 빈공간".)
function fhighlights(cards) {
  const GAP = { style: BorderStyle.SINGLE, size: 36, color: "FFFFFF" };
  const HAIR = { style: BorderStyle.SINGLE, size: 4, color: T.rule };   // between a card's rows
  const w = Math.floor(CONTENT_W / cards.length);
  const widths = cards.map((_, i) => i < cards.length - 1 ? w : CONTENT_W - w * (cards.length - 1));
  const meta = mixHex(T.headText, T.head, 0.3);   // the company and the years, a step quieter than the title on the band
  const head = new TableRow({ cantSplit: true, children: cards.map((c, i) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA }, shading: shade(T.head),
    margins: { top: 90, bottom: 90, left: 150, right: 130 },
    children: [
      new Paragraph({ keepNext: false, spacing: { after: 20 }, children: [run(c.title, { size: 18, bold: true, color: T.headText })] }),
      new Paragraph({ keepNext: false, spacing: { after: 0 }, children: [run(c.where, { size: 14, color: meta, cs: 6 })] }),
    ] })) });
  // Each card is recorded in the per-layer text cell by cell (title, problem, action, result). The rich() calls below
  // do not record the same text again.
  const n = Math.max(...cards.map(c => c.rows.length));   // the rows: as many as the card with the most labels
  const body = Array.from({ length: n }, (_, j) => new TableRow({ cantSplit: true, children: cards.map((c, i) => {
    const [k, v] = c.rows[j] || ["", ""];   // a card with fewer labels leaves the row empty
    return new TableCell({
      width: { size: widths[i], type: WidthType.DXA }, shading: shade(T.band),
      // the first row keeps the band's room under the title, the last one room above the card's end
      margins: { top: j ? 60 : 80, bottom: j === n - 1 ? 90 : 60, left: 150, right: 130 },
      borders: { top: j && !PLAIN ? HAIR : NONE, bottom: NONE },   // the plain look draws no rule
      children: [
        new Paragraph({ keepNext: false, spacing: { after: 10 }, children: [run(k, { size: 14, bold: true, color: T.acc, cs: 10 })] }),
        new Paragraph({ keepNext: false, spacing: { after: 0, line: 248 }, children: rich(v, { size: 16, color: INK }) }),
      ] });
  }) }));
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    borders: { top: GAP, bottom: GAP, left: PLAIN ? NONE : GAP, right: PLAIN ? NONE : GAP, insideHorizontal: NONE, insideVertical: GAP },   // the plain look: no outer sides
    rows: [head, ...body],
  });
}
// One list line: the content, a faded organization, and a date at the right edge. Used for certifications, training and
// awards in the other-items section.
// keep puts the line on the same page as the next line of its group, so the last line of a group is never left alone on
// the next page.
function fline(main, org, date, keep) {
  return new Paragraph({
    spacing: { after: 30, line: 240 }, keepNext: !!keep,
    indent: { left: 300, hanging: 200 },
    tabStops: [{ type: TabStopType.RIGHT, position: RTAB }],
    children: [
      run("\u2022  ", { size: 17, color: accent2() }),
      run(main, { size: 18, color: BODY }),
      ...(org ? [run("   " + org, { size: 16, color: GREY })] : []),
      ...(date ? [run("\t" + date, { size: 16, color: GREY })] : []),
    ],
  });
}
// A heading line of the one-column form: bold name, its details, a date at the right edge. Kept with what follows
function frow(main, sub, right) {
  return new Paragraph({
    spacing: { before: 110, after: 20, line: 240 }, keepNext: true,
    tabStops: [{ type: TabStopType.RIGHT, position: RTAB }],
    children: [
      run(main, { bold: true, size: 20, color: INK }),
      ...(sub ? [run("   " + sub, { size: 17, color: BODY })] : []),
      ...(right ? [run("\t" + right, { size: 16, color: GREY })] : []),
    ],
  });
}
// Sub-heading above a table
function tcap(text) {
  return new Paragraph({
    spacing: { before: 140, after: 60 }, keepNext: true,
    children: [run(text, { bold: true, size: 20, color: T.acc })],
  });
}

let FOOTER_LABEL = "";
// Marks the East Asian text language as Korean (ko-KR; Latin text stays en-US). Without a language, LibreOffice leaves
// a gap before punctuation when it justifies a Hangul paragraph, which looked like a stray space. Setting only ko-KR
// removes the gap (checked with a small test document).
let LANG_KO = false;
function setLangKo(v) { LANG_KO = v; }
function setFooterLabel(t) { FOOTER_LABEL = t; }
// Name footer: the same name as in the header, with the English name beside it, and no word for the document kind.
// Putting the name and the page number on every page is the usual resume practice, so a loose page still shows whose
// document it is. A thin rule above it separates the footer from the body, and only the current page number is bold, in
// the theme color. A cover letter has a label on the left and the page number on the right instead (setFooterLabel).
let FOOTER_NAME = null;
function setFooterName(name, sub) { FOOTER_NAME = name ? { name, sub } : null; }
let DOC_META = {};                                                              // the file's own title and author, as Word and the PDF show them
// set by each form before it renders. A blind edition's title and author leave out what the table covers (a bar cannot
// stand in a file's properties), and the title says it is the blind edition; src/resume.py stamp_meta writes the PDF's the same way
function setDocMeta(meta) {
  DOC_META = meta || {};                                                         // as the form gives it
  if (BL.on) DOC_META = { title: BL.title(DOC_META.title || ""), author: BL.plain(DOC_META.author || "") || BL.T.footer[BL.lang] };   // nothing covered in the Word file's properties
}
function render(ch, outPath) {
  // When OFFEROWL_OUT is set, the output goes to that directory. A check script uses it to build the otherwise unused
  // build scripts into a throwaway folder, so drift in the layout API shows up. Scripts that nobody runs rot silently
  // (for example, when grid2's return type changed from an array to a Table, the retired scripts that called it broke
  // unnoticed).
  if (process.env.OFFEROWL_OUT) {
    outPath = require("path").join(process.env.OFFEROWL_OUT,
                                   require("path").basename(outPath));
  }
  const doc = new Document({
    ...(DOC_META.title ? { title: DOC_META.title } : {}),                       // the document's title (the PDF converted from it keeps it)
    ...(DOC_META.author ? { creator: DOC_META.author, lastModifiedBy: DOC_META.author } : {}),   // whose document it is
    // In a justified paragraph, a line that ends with a manual line break is stretched to the full width and the gaps
    // between words open up, so that behavior is switched off (Word and LibreOffice both honor this compatibility
    // setting). Only the career-description layout enables it.
    ...(LANG_KO ? { compatibility: { doNotExpandShiftReturn: true } } : {}),
    styles: { default: { document: { run: { font: F, size: 18, color: INK } } } },
    sections: [{
      footers: {
        default: new Footer({
          // The name (setFooterName) or label (setFooterLabel), so a loose page still shows whose document it is
          children: [FOOTER_NAME ? new Paragraph({
            tabStops: [{ type: TabStopType.RIGHT, position: RTAB }],
            border: { top: { style: BorderStyle.SINGLE, size: 4, color: T.rule, space: 6 } },
            children: [
              new TextRun({ text: FOOTER_NAME.name, font: F, size: 15, bold: true, color: T.acc }),
              ...(FOOTER_NAME.sub ? [new TextRun({ text: "  " + FOOTER_NAME.sub, font: F, size: 13, color: FAINT })] : []),
              // the blind-edition marker is the same red label as in the older footer
              ...(BL.on ? [new TextRun({ text: "  ", font: F, size: 14 }), new TextRun({ text: " " + BL.T.footer[BL.lang] + " ", font: F, size: 13, bold: true, color: "FFFFFF",
                characterSpacing: 10, shading: { type: ShadingType.CLEAR, fill: BL.T.mark_fill, color: "auto" } })] : []),
              new TextRun({ text: "\t", font: F, size: 14 }),
              new TextRun({ children: [PageNumber.CURRENT], font: F, size: 15, bold: true, color: T.acc }),
              new TextRun({ text: " / ", font: F, size: 13, color: FAINT }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], font: F, size: 13, color: FAINT }),
            ],
          }) : new Paragraph({
            alignment: FOOTER_LABEL ? AlignmentType.LEFT : AlignmentType.RIGHT,
            tabStops: FOOTER_LABEL ? [{ type: TabStopType.RIGHT, position: RTAB }] : [],
            children: [
              ...(FOOTER_LABEL ? [new TextRun({ text: FOOTER_LABEL + (BL.on ? "  " : "\t"), font: F, size: 14, color: FAINT })] : []),
              // The blind edition puts a label in white on dark red (the color of the page-1 strip) in the footer of
              // every page
              ...(FOOTER_LABEL && BL.on ? [new TextRun({ text: " " + BL.T.footer[BL.lang] + " ", font: F, size: 13, bold: true, color: "FFFFFF",
                characterSpacing: 10, shading: { type: ShadingType.CLEAR, fill: BL.T.mark_fill, color: "auto" } }), new TextRun({ text: "\t", font: F, size: 14 })] : []),
              new TextRun({
                children: [PageNumber.CURRENT, " / ", PageNumber.TOTAL_PAGES],
                font: F, size: 14, color: FAINT,
              })],
          })],
        }),
      },
      properties: {
        page: {
          size: { width: 11906, height: 16838 },
          // The bottom margin has to be larger than the page number. The page number sits at the footer position of 708
          // twips and its glyphs reach up to 928 twips. If the bottom margin is smaller, the body flows into the
          // page-number area and the two touch. At 1080 twips (54pt) at least 6.5pt stays free.
          margin: { top: 340, bottom: 1080, left: 750, right: 750, footer: 708 },
        },
      },
      children: ch,
    }],
  });
  // the highlights and paragraphs set, beside the document, for the line checks (written before the save, so a document
  // that saved always has them, and an older pair is never read beside a newer document)
  require("fs").writeFileSync(outPath.replace(/\.docx$/, ".highlights.json"), JSON.stringify({ highlights: HIGHLIGHTS, paras: PARAS }, null, 1));
  require("./save").save(doc, outPath, { fieldResults: PLAIN || !!FOOTER_NAME });   // page fields filled in when the footer or the plain look shows them
}

module.exports = {
  INK, GREY, CONTENT_W, run, p, render, prose, fsec, fband, fsub, fbul, focusRows, ftable, tcap, fimage, fline, frow,
  fcards, fquote, setFont, fheader, fhighlights, setTheme, accent2, setLangKo, setFooterLabel, setFooterName, setDocMeta, setPlain,
};
