// Offerowl's panel, part 2: the canvas. The resume is drawn from GET /api/v1/documents/resume as it will print: A4
// sheets with the PDF's own margins, type sizes and line heights (src/layout.js, app.css .rs), the blocks in the order
// src/resume_form.js prints them, the theme's colours. The blocks are measured once and laid onto pages as LibreOffice
// lays the PDF: a heading kept with what follows, a table broken between rows with its head again, a paragraph broken
// between lines with two of them at least on either side. The notebook's margin beside each page names its sections and
// marks a sentence without evidence in red. Every sentence is a key: a click (or Enter) opens its evidence in the inspector.
"use strict";                                                                       // catches undeclared names and silent writes early

const A4 = { w: 793.73, h: 1122.53, top: 22.67, bottom: 72 };                       // the page and its margins in CSS px (11906 x 16838 twips; 340 and 1080 twips: layout.js render)
const ROOM = (16838 - 340 - 1080) / 15;                                             // the height a page's text may take, to the twip
const KEEP_LINES = 2;                                                               // the lines a broken paragraph keeps at a page's foot and at the next one's head (LibreOffice's orphans and widows)
const PHONE = window.matchMedia("(max-width: 859px)");                              // a phone: the pages are scaled to its width
const MARGIN_NAME = { overview: "Overview", career: "Career", edu: "Education", comp: "Strengths", skills: "Skills",  // the margin's labels, in the app's language
  detail: "Experience", about: "About me", motivation: "Motivation", list: "Lists", head: "Profile" };

function resumeKey(lang, theme, jid) { return `res|${lang}|${theme}|${(S.settings || {}).form || ""}|${jid || ""}|${rev()}`; }   // one cached model per revision
function resumeModel() {                                                            // the model for the canvas now, or null while it loads
  const lang = docLang(), jid = jobId() || "";                                      // the document's language and the job in view (none: the general edition)
  const key = resumeKey(lang, UI.theme, jid), base = `${lang}|${UI.theme}|${(S.settings || {}).form || ""}|${jid}`;   // its cache key, and the same document at any revision
  if (!UI.docs[key]) {                                                              // not fetched for this revision
    for (const k of Object.keys(UI.docs)) if (k.startsWith("res|") && k !== key && !k.endsWith(rev())) delete UI.docs[k];  // older revisions go
    getDoc(key, `/api/v1/documents/resume?lang=${lang}&theme=${UI.theme}` + (jid ? `&job=${enc(jid)}` : ""));  // fetched once
  }
  if (UI.docs[key]) UI.lastRes = { base, m: UI.docs[key] };                          // the newest model of this document
  return UI.docs[key] || (UI.lastRes && UI.lastRes.base === base ? UI.lastRes.m : null);  // the last one stays on the canvas while the new one loads
}
function coverModel() {                                                             // the cover letter of the job in view
  const jid = jobId(); if (!jid) return null;                                       // no job, no letter
  const key = `cov|${docLang()}|${jid}|${rev()}`;                                   // per revision
  if (!UI.docs[key]) getDoc(key, `/api/v1/documents/cover?job=${enc(jid)}&lang=${docLang()}`);  // fetched once
  return UI.docs[key] || null;                                                      // null while it loads
}
function deckModel() {                                                              // the deck as it will print, for the job in view or the general edition
  const ed = edition(); if (!ed) return null;                                       // nothing to draw for
  const base = `${docLang()}|${UI.theme}|${(S.settings || {}).deck_style || ""}|${ed.id}`, key = `deck|${base}|${rev()}`;  // the same document, and this revision of it
  if (!UI.docs[key]) {                                                              // not fetched for this revision
    for (const k of Object.keys(UI.docs)) if (k.startsWith("deck|") && k !== key) delete UI.docs[k];  // pages are large: older ones go
    getDoc(key, `/api/v1/jobs/${enc(ed.id)}/deck/${docLang()}?theme=${UI.theme}`);  // fetched once
  }
  if (UI.docs[key]) UI.lastDeck = { base, d: UI.docs[key] };                        // the newest page of this document
  return UI.docs[key] || (UI.lastDeck && UI.lastDeck.base === base ? UI.lastDeck.d : null);  // the last one stays on the canvas while the new one loads
}
function sentenceOf(sid) {                                                          // a sentence's record, from whichever document holds it
  if (sid && sid.startsWith("cover.")) {                                            // a cover letter sentence
    const c = coverModel();                                                         // the letter
    for (const p of (c && c.paragraphs) || []) for (const s of p.sentences) if (s.sid === sid) return s;  // found
    return null;                                                                    // gone
  }
  const m = resumeModel();                                                          // the resume
  return (m && m.sentences && m.sentences[sid]) || null;                            // its record
}

// ---------------------------------------------------------------- sentences

function sourcesOf(m) {                                                             // the document's source files in the order its sentences first cite them: [{file, n}]
  if (m._sources) return m._sources;                                                // worked out once per model
  const seen = new Map();                                                           // file -> its row
  let details = 0, typed = 0;                                                       // sentences resting only on Your details, or on facts the person added
  for (const rec of Object.values(m.sentences || {})) {                            // every sentence, in the document's order
    for (const e of rec.evidence || []) {                                           // what it rests on
      if (!e || !e.file) continue;                                                  // the person's own words cite no file
      if (!seen.has(e.file)) seen.set(e.file, { file: e.file, n: 0 });              // a file not seen yet: the next number
    }
    const files = new Set((rec.evidence || []).map((e) => e && e.file).filter(Boolean));   // the files this sentence rests on, once each
    files.forEach((f) => { seen.get(f).n += 1; });                                  // a sentence more for each
    if (!files.size && (rec.evidence || []).length) {                               // no file behind it: counted too, so the list adds up
      if ((rec.evidence || []).some((e) => e && e.where === "details")) details += 1; else typed += 1;   // Your details, or a fact added by hand
    }
  }
  m._sources = [...seen.values(), ...(details ? [{ file: t("Your details"), n: details, typed: true }] : []),   // numbered from one, in order; the person's own words last
    ...(typed ? [{ file: t("Facts you added"), n: typed, typed: true }] : [])];
  return m._sources;
}
// a piece of evidence by what it is: a fact of the profile (its id), or a passage of an imported file; the person's own details cite nothing
const evKey = (e) => (!e || e.where === "details") ? null : (e.unit || (e.file || "") + "|" + String(e.quote || "").slice(0, 80));
function evidenceIndex(m) {                                                         // the document's evidence numbered in the order its sentences first cite it
  if (m._evIndex) return m._evIndex;                                                // worked out once per model
  const idx = new Map();                                                            // evidence -> its number
  for (const rec of Object.values(m.sentences || {})) for (const e of rec.evidence || []) {   // every sentence, in the document's order
    const k = evKey(e);
    if (k && !idx.has(k)) idx.set(k, idx.size + 1);                                 // first cited: the next number
  }
  m._evIndex = idx;
  return idx;
}
function evNums(m, rec) {                                                           // the numbers of the evidence one sentence rests on
  const idx = evidenceIndex(m);
  return [...new Set((rec.evidence || []).map(evKey).filter((k) => k && idx.has(k)).map((k) => idx.get(k)))].sort((a, b) => a - b);
}
// the numbers of a sentence's evidence after it, always, as a retrieval interface numbers its passages. They used to number the
// files, and only when a document had two or more, so a workspace of one file showed none. Screen only: the PDF has none
function citeMark(m, rec) {
  const nums = evNums(m, rec);
  if (!nums.length) return null;                                                    // the person's own words, or no evidence (drawn as such)
  const first = (rec.evidence || []).find((e) => evKey(e));                         // the first passage, to read on hover
  return h("sup", { class: "cite", "aria-hidden": "true", title: first ? unmarked(first.quote || first.file).slice(0, 160) : null, text: nums.join(",") });
}
const inKorean = (m, rec) => m.lang === "en" && /[가-힣]/.test((rec && rec.text) || "");   // a sentence of the English edition still in Korean (no English for its field yet)
function sent(m, sid, extra, kids) {                                                // one sentence as a key on the page; kids: its words drawn in parts (a dated line)
  const rec = m.sentences[sid];                                                     // its record
  if (!rec) return null;                                                            // not in this model
  const cls = ["s", rec.state === "unsupported" ? "unsupported" : "", rec.state === "edited" ? "edited" : "", inKorean(m, rec) ? "kr" : "", UI.sel === sid ? "sel" : ""].filter(Boolean).join(" ");
  const el = h("span", { class: cls, "data-sid": sid, tabindex: "0", role: "button", "aria-pressed": UI.sel === sid ? "true" : "false",  // a key with its state
    "aria-label": rec.state === "unsupported" ? t("No evidence: {text}", { text: unmarked(rec.text) }) : null }, kids || marks(rec.text));
  const cite = citeMark(m, rec);                                                    // which sources it rests on
  if (cite) el.append(cite);                                                        // right after its words
  if (extra) el.append(extra);                                                      // a space or a mark after it
  return el;                                                                        // in the paragraph
}

// ---------------------------------------------------------------- the resume's units, in print order

// A unit is one paragraph or one table of the printed resume, in the order src/resume_form.js prints them:
// {el, keep, label, sids, split}. keep: it stays on the page of what follows (a heading, a company's band, a dated line);
// split: "lines" for a paragraph LibreOffice may break between its lines, "rows" for a table it may break between rows.
// The classes carry the printed measures (app.css .rs); the widths of a table's columns are resume_form.js's own.
const TWIPS_W = 10406;                                                              // the text's width in twips (layout.js CONTENT_W)
function resumeUnits(m) {                                                           // [{el, keep, label, sids, split}] for the pager
  const U = [], P = m.person || {}, L = m.labels || {}, ko = m.lang !== "en";      // the units, the person, the table heads; the faint English labels are the Korean edition's only
  const form = m.form || "detailed", plain = form === "compact";                   // the form it prints in (src/resume_form.js FORMS); the one-column form draws lines where the others draw tables
  const add = (el, opt = {}) => U.push({ el, keep: !!opt.keep, label: opt.label || null, sids: opt.sids || [], split: opt.split || null });  // one unit
  const bullet = () => h("span", { class: "b", text: "•" });                        // a bullet and its tab
  const words = (sids) => sids.flatMap((sid, i) => { const s = sent(m, sid); return s ? (i ? [" ", s] : [s]) : []; });   // sentences in a line, a space between
  const two = /\n/.test(P.tagline || "");                                            // a tagline written on two lines sits further in
  if (plain) {                                                                      // the one-column form (resume_form.js plainHead): the name, what the person is, one line of contacts
    add(h("p", { class: "r-pname" }, h("b", { text: P.name || t("Your name") }), P.name_en ? h("span", { text: "  " + P.name_en }) : null), { label: "head" });   // 20 pt, the other spelling 10 pt grey
    if (P.tagline) add(h("p", { class: "r-ptag", text: P.tagline }));               // 8.5 pt bold in the accent
    add(h("p", { class: "r-pcon", text: (P.contacts || []).map((c) => c[1]).filter(Boolean).join("   |   ") }));   // the values only, as a reader's eye and a program both find them
  } else if (form === "table") {                                                    // the table form (resume_form.js tableHead): the document's name, then who and how to reach them in a key table
    add(h("p", { class: "r-title", text: L.resume || "" }), { label: "head" });     // 18 pt bold, centred
    add(rtable([2000, TWIPS_W - 2000], null, [[{ kids: [L.name || ""], cls: "k" }, { kids: [[P.name || t("Your name"), P.name_en].filter(Boolean).join("  ")], cls: "pre" }],   // the name row: both spellings two spaces apart
      ...(P.contacts || []).map(([k, v]) => [{ kids: [k], cls: "k" }, { kids: [v] }])]), { split: "rows" });   // a label and its value per row
  } else add(h("div", { class: "r-head" + (P.photo ? " photo" : "") },             // the photo, the name band and the contacts, as printed
    P.photo ? h("div", { class: "r-ph" }, h("img", { class: "r-photo", src: P.photo, alt: "" })) : null,
    h("div", { class: "r-name" + (two ? " two" : "") }, h("p", { class: "n" }, h("b", { text: P.name || t("Your name") }), P.name_en ? h("span", { text: "  " + P.name_en }) : null),
      P.tagline ? h("p", { class: "tag", text: P.tagline }) : null),
    h("div", { class: "r-contacts" }, (P.contacts || []).map(([k, v]) => h("p", {}, h("b", { text: k }), h("span", { text: v }))))), { label: "head" });
  let section = null;                                                               // the current section, for the margin
  for (const b of m.blocks || []) {                                                 // in print order
    if (b.type === "headline") add(h("p", { class: "r-headline" }, sent(m, b.sid)), { sids: [b.sid] });  // one line, or two where it was written so
    else if (b.type === "intro") add(h("p", { class: "r-prose" }, words(b.sids)), { sids: b.sids, split: "lines" });   // the introduction
    else if (b.type === "figure") add(h("img", { class: "r-fig f-" + b.key, src: b.src, alt: "",   // the timeline or the hierarchy figure at 694 px, as printed (f-: the tracker owns .timeline)
      style: `height:${Math.round(b.h * 694 / b.w)}px` }));
    else if (b.type === "section") {                                                // a heading: kept with what follows
      section = sectionKey(b);                                                      // for the margin label
      add(h("div", { class: "r-sec" }, h("h2", {}, b.title, b.note ? h("span", { text: "  " + b.note }) : null), ko && b.en ? h("small", { text: b.en }) : null),
        { keep: true, label: section });
    } else if (b.type === "cards") add(h("div", { class: "r-cards" }, b.items.map((c) => h("div", { class: "r-card" }, h("b", { text: c.title }), h("p", {}, sent(m, c.sid))))),
      { sids: b.items.map((c) => c.sid) });
    else if (b.type === "highlights") {                                             // the key projects: a caption, then a card each
      add(h("p", { class: "r-cap", text: b.title }), { keep: true });               // the caption, kept with the cards
      const n = Math.min(b.items.length, 4), w = Math.floor(TWIPS_W / n);          // four at most, in columns of equal twips, the last one taking the rest
      const fills = Array.from({ length: n }, (_, i) => (i < n - 1 ? w : TWIPS_W - w * (n - 1)) / 15 - 6);   // each card's fill: its column less the 4.5 pt line before it
      add(h("div", { class: "r-hls", style: `grid-template-columns:${fills.map((x) => x.toFixed(2) + "px").join(" ")}` },
        b.items.slice(0, n).map((c, i) => h("div", { class: "r-hlh", style: `--o:${2 * i}` }, h("b", { text: c.title }), h("small", { text: c.where || "\u00a0" }))),   // the heads in one row (on a phone, each over its body)
        b.items.slice(0, n).map((c, i) => h("div", { class: "r-hlb", style: `--o:${2 * i + 1}` }, c.rows.map((r) => [h("b", { text: r.label }), h("p", {}, sent(m, r.sid))])))),   // the bodies in the next
        { sids: b.items.flatMap((c) => c.rows.map((r) => r.sid)) });
    } else if (b.type === "career") add(careerTable(m, b, L), { sids: b.rows.map((r) => r.sid), split: "rows" });
    else if (b.type === "education" && plain) for (const r of b.rows) add(frow(sent(m, r.sid), [r.major, r.degree, r.note].filter(Boolean).join(", "), r.period),   // a line per school (plainEducation)
      { sids: [r.sid], keep: true });
    else if (b.type === "education") add(educationTable(m, b, L), { sids: b.rows.map((r) => r.sid), split: "rows" });
    else if (b.type === "competencies") for (const c of b.items) add(h("p", { class: "r-bul" }, bullet(), c.head ? h("b", { text: c.head + ": " }) : null,   // a strength: its name, its text
      sent(m, c.sid), c.evidence ? " " + c.evidence : null), { sids: [c.sid], split: "lines" });   // and the projects behind it, as printed
    else if (b.type === "skills" && plain) for (const r of b.rows) add(h("p", { class: "r-bul after30" }, bullet(), h("b", { text: r.category + ": " }), sent(m, r.sid)),   // a bullet per category (plainSkills)
      { sids: [r.sid], split: "lines" });
    else if (b.type === "skills") add(rtable([2000, TWIPS_W - 2000], [L.cat, L.tech], b.rows.map((r) => [{ kids: [r.category], cls: "k" }, { kids: [sent(m, r.sid)] }])),
      { sids: b.rows.map((r) => r.sid), split: "rows" });
    else if (b.type === "service") add(rtable([2000, TWIPS_W - 2000], [L.period, L.kind], [[{ kids: [b.period] }, { kids: [b.label] }]], ["c", "l"]), { split: "rows" });   // the table form's service record: when, and what
    else if (b.type === "role" && plain) {                                          // the one-column form (plainWork): the company's line, its grey line, then its projects
      add(frow(m.sentences[b.sid] ? sent(m, b.sid) : b.org, [ko ? b.title || b.title_long : b.title_long || b.title, b.place].filter(Boolean).join(", "), b.period), { sids: [b.sid], keep: true });   // the edition's own word for the role, and the place
      if (b.desc) add(h("p", { class: "r-desc a40", text: b.desc }), { keep: true });   // the company in a line, kept with the first project
      for (const p of b.projects) {                                                 // each project as in the detailed form, 70 twips after
        const head = p.title + (p.period ? ` (${p.period})` : "");                 // its name and dates
        add(p.sids.length ? h("p", { class: "r-bul after70" }, bullet(), h("b", { text: head + ": " }), words(p.sids))
          : h("p", { class: "r-bul after40" }, bullet(), head), { sids: p.sids, split: "lines" });   // one with no summary yet shows its title alone
      }
    } else if (b.type === "role") {                                                 // a company: its band, the line under it, a grey line, then its projects
      if (b.logo) add(h("div", { class: "r-gap" }), { keep: true });               // the band's 200 twips above it are a paragraph of their own
      add(h("div", { class: "r-band" + (b.logo ? "" : " plain") }, b.logo ? h("img", { class: "r-logo", src: b.logo, alt: "" }) : null,
        h("b", { text: b.org }), b.badge ? h("span", { class: "badge", text: b.badge }) : null,
        b.place ? h("span", { class: "place", text: b.place + "   " }) : null, h("span", { class: "when", text: (b.period || "") + (b.tenure ? ` (${b.tenure})` : "") })),
        { keep: true });
      if (b.sub) add(h("p", { class: "r-sub" + ((m.colors || {}).acc === "1F1F1F" ? " ink" : ""), text: b.sub }), { keep: true }); // the underlined line under the band
      if (b.desc) add(h("p", { class: "r-desc", text: b.desc }), { keep: true });   // the grey line about the company, kept with the first project
      for (const p of b.projects) {                                                 // each project as a bullet: 'Title (period): summary'
        const head = p.title + (p.period ? ` (${p.period})` : "");                 // its name and dates
        add(p.sids.length ? h("p", { class: "r-bul after90" }, bullet(), h("b", { text: head + ": " }), words(p.sids))
          : h("p", { class: "r-bul" }, bullet(), head), { sids: p.sids, split: "lines" });   // one with no summary yet shows its title alone
      }
    } else if (b.type === "list") for (const g of b.groups || [{ items: b.items, lines: [] }]) {   // a list: under each caption, its bullets, dated lines, table and note
      if (g.caption) add(h("p", { class: "r-cap", text: g.caption }), { keep: true }); // a group's caption, kept with its first line
      for (const it of g.items || []) add(h("p", { class: "r-bul after40" }, bullet(), sent(m, it.sid)), { sids: [it.sid], split: "lines" });
      (g.lines || []).forEach((ln, i, all) => add(h("p", { class: "r-line" }, h("span", { class: "b", text: "•  " }), dated(m, ln)),   // a dated line, kept with the next one of its group
        { sids: [ln.sid], keep: !plain && i < all.length - 1 }));                   // (the one-column form keeps none)
      const say = (c) => (c && c.t) || "";                                          // a table cell's words
      if (g.table && plain) for (const r of g.table.rows) add(h("p", { class: "r-line" }, h("span", { class: "b", text: "•  " }),   // the one-column form: a row is a dated line
        dateLine(say(r[0]), r.slice(1, -1).map(say).filter(Boolean).join(", "), r.length > 1 ? say(r[r.length - 1]) : "")));   // the first cell, the middle ones, the last on the right
      else if (g.table) add(rtable(g.table.widths, g.table.head, g.table.rows.map((r) => r.map((c) => ({ kids: [c.t], cls: [c.bold ? "bold" : "", c.accent ? "acc" : ""].join(" ").trim() }))),
        g.table.align), { split: "rows" });
      if (g.note && !plain) add(h("p", { class: "r-note", text: g.note }));         // a grey note under a table or a list (not in the one-column form)
    } else if (b.type === "about") for (const a of b.items) {                         // about me: a stage title, then its paragraphs on a rail
      add(h("p", { class: "r-stage" }, h("span", { text: a.title })), { keep: true }); // the stage's shaded title, kept with its first paragraph
      const paras = a.paras || [a.sids];                                            // an older model has its sentences in one paragraph
      paras.forEach((ps, k) => add(h("p", { class: "r-prose rail" + (k === paras.length - 1 ? " last" : "") }, words(ps)), { sids: ps, split: "lines" }));
    } else if (b.type === "motivation") for (const ps of b.paras || [b.sids]) add(h("p", { class: "r-prose" }, words(ps)), { sids: ps, split: "lines" });
  }
  return U;                                                                         // in print order
}
function rtable(widths, head, rows, align) {                                        // a table as layout.js ftable prints it: widths in twips, a head row, rows of {kids, cls}
  return h("table", { class: "r-table" }, h("colgroup", {}, widths.map((w) => h("col", { style: `width:${(w / 15).toFixed(3)}px` }))),   // each column its twips wide
    head ? h("thead", {}, h("tr", {}, head.map((x) => h("th", { text: x })))) : null,
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c, i) => h("td", { class: [c.cls || "", { c: "c", r: "r" }[(align || [])[i]] || ""].join(" ").trim() || null }, c.kids))))));
}
function lines(...items) {                                                          // a cell's lines, the empty ones left out: the first as written, the later ones grey
  return items.filter((x) => x !== null && x !== undefined && x !== "").map((x, i) => (i ? h("div", { class: "g", text: x }) : h("div", {}, x))); // each a paragraph of the cell
}
function nameCell(logo, kids) {                                                     // a table's name cell: the logo tile at its left, centred on the lines
  return logo ? { kids: [h("div", { class: "r-org" }, h("img", { class: "r-logo", src: logo, alt: "" }), h("div", {}, kids))], cls: "lg" } : { kids }; // no logo: the lines alone
}
function careerTable(m, b, L) {                                                     // the career summary with resume_form.js's columns and widths
  const en = m.lang === "en", logos = b.rows.some((r) => r.logo);                   // the edition; a logo column needs a wider name column
  const dept = b.rows.some((r) => r.department), tenure = b.rows.some((r) => r.tenure);   // the columns the table has
  const full = en ? [1700, 3300, 2550, 1650] : logos ? [1850, 2850, 2600, 2100] : [1850, 2400, 3000, 2100];   // period, company, department, role
  const preset = dept ? (tenure ? full : [full[0], full[1] + 350, full[2] + 300]) : (tenure ? [full[0], full[1] + 750, full[2] + full[3] - 750] : [full[0], full[1] + 1350]);
  const widths = [...preset, TWIPS_W - preset.reduce((a, x) => a + x, 0)];         // the last column takes the rest
  const head = [L.period, L.org, ...(dept ? [L.dept] : []), L.role || L.dept, ...(tenure ? [L.tenure] : [])]; // the head row
  const align = ["c", "l", "l", "l", "c"].slice(0, head.length - 1).concat(tenure ? ["c"] : ["l"]);   // dates and tenure centred
  if (!b.rows.some((r) => "role" in r)) return rtable([1850, 2850, 3600, TWIPS_W - 8300], [L.period, L.org, L.dept, L.tenure],   // an older model: four columns
    b.rows.map((r) => [{ kids: [r.period] }, { kids: [sent(m, r.sid)] }, { kids: [r.dept] }, { kids: [r.tenure] }]), ["c", "l", "l", "c"]);
  return rtable(widths, head, b.rows.map((r) => [{ kids: [r.period] }, nameCell(r.logo, lines(sent(m, r.sid), r.sub)),
    ...(dept ? [{ kids: [r.department || ""] }] : []), { kids: [r.role || ""] }, ...(tenure ? [{ kids: [r.tenure || ""] }] : [])]), align);
}
function educationTable(m, b, L) {                                                  // the schools with resume_form.js's widths
  const logos = b.rows.some((r) => r.logo);                                         // a logo column needs a wider school column
  const preset = m.lang === "en" ? [1630, 3530, 2715] : logos ? [1650, 3200, 3000] : [1650, 2850, 3300]; // period, school, major; the degree takes the rest
  return rtable([...preset, TWIPS_W - preset.reduce((a, x) => a + x, 0)], [L.period, L.school, L.major, L.degree],
    b.rows.map((r) => [{ kids: [r.period] }, nameCell(r.logo, lines(sent(m, r.sid), r.sub)), { kids: lines(r.major, r.majorSub) }, { kids: lines(r.degree, r.note) }]), ["c", "l", "l", "l"]);
}
function dated(m, ln) {                                                             // a dated line: one sentence, its parts drawn as printed (the date at the right tab)
  const rec = m.sentences[ln.sid];                                                  // its record
  const whole = [ln.main, ln.org, ln.date].filter(Boolean).join(" ");               // the sentence as the model made it from the parts
  if (!rec || rec.text !== whole) return sent(m, ln.sid);                           // changed since: its words as they are now
  return sent(m, ln.sid, null, dateLine(ln.main, ln.org, ln.date));                 // its parts
}
// A dated line's words (layout.js fline): the main words, the organization in grey after three spaces, then the date at the
// right tab. The date comes last and floats right: it sits on the line's last line where it fits there, else on a line of
// its own under it, as LibreOffice moves a right tab's words that do not fit. The three spaces are a text of their own, so
// a line that wraps before the organization leaves them at its end and the name whole on the next (one text would read as
// a word broken across two lines)
function dateLine(main, org, date) {
  return [main, org ? h("span", { class: "org" }, "   ", org) : null, date ? h("span", { class: "date", text: date }) : null];
}
function frow(main, sub, right) {                                                   // a line of the one-column form (layout.js frow): the name in bold, its details, the dates at the right tab
  return h("p", { class: "r-row" }, main, sub ? h("span", { class: "sub" }, "   ", sub) : null, right ? h("span", { class: "date", text: right }) : null);
}
function sectionKey(b) {                                                            // which margin label a section heading gets
  const byEn = { OVERVIEW: "overview", "CAREER SUMMARY": "career", EDUCATION: "edu", "CORE COMPETENCIES": "comp", "TECHNICAL SKILLS": "skills",
    "PROFESSIONAL EXPERIENCE": "detail", "ABOUT ME": "about", MOTIVATION: "motivation" };
  return { overview: "overview", career: "career", edu: "edu", comp: "comp", skills: "skills", detail: "detail", about: "about", motivation: "motivation" }[b.key]
    || byEn[b.en] || (b.title ? "list:" + b.title : "list");                        // any other list is named by its own heading (Certificates over certificates, not "Lists")
}
function themeVars(m) {                                                             // the theme's colours as the sheet's custom properties
  const c = m.colors || {}, hex = (k, d) => "#" + (c[k] || d);                      // a colour or its default
  return `--c-name:${hex("nameFill", "1B2E4B")};--c-name-ink:${hex("nameText", "FFFFFF")};--c-sec:${hex("sec", "1B2E4B")};--c-rule:${hex("rule", "C9D4E3")};` +
    `--c-band:${hex("band", "EEF3F9")};--c-band-ink:${hex("bandText", "1B2E4B")};--c-head:${hex("head", "1B2E4B")};--c-head-ink:${hex("headText", "FFFFFF")};` +
    `--c-key:${hex("key", "F5F8FC")};--c-acc:${hex("acc", "1B2E4B")};--c-acc2:${hex("acc2", c.acc || "2F6EBA")}`;   // every colour the resume prints with
}

// ---------------------------------------------------------------- the pager

// The units are measured once in a page-wide column off screen, then laid onto pages as LibreOffice lays the PDF: the space
// between two units is the larger of the one's after and the other's before, and none above a page's first unit; a unit
// kept with the next one goes to the next page when the next one's start does not fit beside it; a paragraph breaks between
// lines with two lines at least on either side, and a table between rows, its head row printed again on the next page
// Writer lays a page out in whole twips (1/15 px), the browser in 1/64 px: a 250-twip line is 16.6667 px in the PDF and
// 16.671875 px on the screen, and sixty of them end a page 0.3 px lower, enough to keep a line the PDF moves on. So the
// pager counts in twips: each height, spacing and line pitch at its nearest twip, a paragraph as its lines times the pitch
const TW = (px) => Math.round(px * 15) / 15;                                        // a length at the PDF's grain
const FIT = 0.05;                                                                   // what a unit may pass the page's foot by and still fit: less than a twip
function measure(u) {                                                               // a unit's height, its spacing, and its lines or rows
  const r = u.el.getBoundingClientRect(), cs = getComputedStyle(u.el);              // its box and its style
  const m = { h: TW(r.height), mt: TW(parseFloat(cs.marginTop) || 0), mb: TW(parseFloat(cs.marginBottom) || 0), pt: TW(parseFloat(cs.paddingTop) || 0), pb: TW(parseFloat(cs.paddingBottom) || 0) };
  if (u.split === "lines") {                                                        // its lines, all of one height
    const lh = parseFloat(cs.lineHeight) || 16;                                     // the pitch as the browser draws it
    m.n = Math.max(1, Math.round((r.height - m.pt - m.pb) / lh));                   // how many
    m.lh = TW(lh); m.h = m.pt + m.n * m.lh + m.pb;                                  // the pitch and the height as the PDF has them
  }
  if (u.split === "rows") {                                                         // a table: its head and its rows
    m.head = u.el.tHead ? TW(u.el.tHead.getBoundingClientRect().height) : 0;        // its head row, printed again on each page
    m.rows = [...((u.el.tBodies[0] || {}).rows || [])].map((tr) => TW(tr.getBoundingClientRect().height)); // each row, never broken
  }
  return m;                                                                         // for the placing
}
function lead(units, M, j) {                                                        // what of unit j must stand on the page of the unit before it
  const u = units[j], m = M[j];                                                     // the unit and its measures
  if (!u) return 0;                                                                 // the document's end
  let first = m.h;                                                                  // all of it, unless it can break
  if (u.split === "lines" && m.n >= 2 * KEEP_LINES) first = m.pt + KEEP_LINES * m.lh;   // a paragraph's first two lines
  if (u.split === "rows" && m.rows.length > 1) first = m.pt + m.head + m.rows[0];   // a table's head and first row
  return u.keep ? m.h + Math.max(m.mb, (M[j + 1] || {}).mt || 0) + lead(units, M, j + 1) : first;   // a kept unit takes the next one's start with it
}
function cutLines(el, m, k) {                                                       // the paragraph's lines after its k-th moved into a paragraph of their own
  const top = el.getBoundingClientRect().top + m.pt + k * m.lh - 1;                 // where the (k+1)-th line starts
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), range = document.createRange(); // its text, letter by letter
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {                           // each piece of text, in order
    if (n.parentElement.closest(".cite, .b")) continue;                             // a source number or the bullet starts no line
    for (let i = 0; i < n.length; i++) {                                            // each letter
      if (/\s/.test(n.data[i])) continue;                                           // a space ends a line, it starts none
      range.setStart(n, i); range.setEnd(n, i + 1);                                 // one letter
      const r = range.getClientRects()[0];                                          // where it stands
      if (!r || r.top < top) continue;                                              // still on the lines that stay
      range.setStart(n, i); range.setEndAfter(el.lastChild);                        // from that letter to the paragraph's end
      const tail = el.cloneNode(false);                                             // the same paragraph's look
      tail.append(range.extractContents());                                         // the sentence cut there is cloned with its id: both halves are its key
      tail.classList.add("cont");                                                   // no bullet, no indent
      el.classList.add("cut");                                                      // its last line here is a full line
      el.after(tail);                                                               // measured at the page's width beside it
      return tail;                                                                  // the lines that go on
    }
  }
  return null;                                                                      // no line starts there
}
function cutRows(el, k) {                                                           // the table's rows after its k-th moved into a table of their own with the same head
  const tail = el.cloneNode(false);                                                 // the same table
  for (const part of el.children) if (part.tagName !== "TBODY") tail.append(part.cloneNode(true));   // its columns and its head row, again
  const body = h("tbody", {});                                                      // the rows that go on
  body.append(...[...el.tBodies[0].rows].slice(k));                                 // moved from the table above
  tail.append(body);
  el.after(tail);                                                                   // measured beside it
  return tail;
}
function paginate(units, style) {                                                   // the units laid onto A4 pages: [[{unit, top}]]
  const probe = h("article", { class: "sheet rs", style: style + ";position:absolute;left:-12000px;top:0;visibility:hidden;height:auto;zoom:1" });  // a page to measure in
  document.body.append(probe);                                                      // laid out off screen
  units.forEach((u) => probe.append(u.el));                                         // in print order, at the page's width
  const M = units.map(measure);                                                     // each unit measured once
  const pages = [[]];                                                               // the first page
  let y = 0, mb = 0;                                                                // the height used on this page, and the space after its last unit
  const place = (unit, m) => { const top = pages[pages.length - 1].length ? y + Math.max(mb, m.mt) : 0; pages[pages.length - 1].push({ unit, top }); y = top + m.h; mb = m.mb; };
  const turn = () => { pages.push([]); y = 0; mb = 0; };                           // a new page
  for (let i = 0; i < units.length; i++) {                                          // in order
    let u = units[i], m = M[i];                                                     // the unit, or what is left of it after a break
    for (;;) {                                                                      // until all of it is placed
      const first = !pages[pages.length - 1].length;                                // the page's first unit has no space above it
      const top = first ? 0 : y + Math.max(mb, m.mt);                              // where it would start
      const kept = u.keep ? Math.max(m.mb, (M[i + 1] || {}).mt || 0) + lead(units, M, i + 1) : 0;   // what it must take with it
      if (top + m.h + kept <= ROOM + FIT) { place(u, m); break; }                   // it fits, with what it is kept with
      if (u.split === "lines" && !u.keep) {                                         // a paragraph breaks between lines
        let k = Math.floor((ROOM + FIT - top - m.pt) / m.lh);                       // the lines that fit here
        if (m.n - k < KEEP_LINES) k = m.n - KEEP_LINES;                             // two go on together at the next page's head
        if (k >= KEEP_LINES && k < m.n) {                                           // and two stay at this page's foot
          const tail = cutLines(u.el, m, k);                                        // the lines that go on
          if (tail) {
            place(u, { ...m, h: m.pt + k * m.lh, mb: 0 }); turn();                  // the first lines here, the rest on the next page
            u = { ...u, el: tail, label: null }; m = { ...m, h: (m.n - k) * m.lh + m.pb, mt: 0, pt: 0, n: m.n - k };
            continue;                                                               // the rest, which may break again
          }
        }
      }
      if (u.split === "rows") {                                                     // a table breaks between rows
        let k = 0, h0 = m.pt + m.head;                                              // its head row comes first on every page
        while (k < m.rows.length && top + h0 + m.rows[k] <= ROOM + FIT) h0 += m.rows[k++];   // the rows that fit here
        if (k > 0 && k < m.rows.length) {                                           // one at least, and not all
          const tail = cutRows(u.el, k);                                            // the rows that go on, under the same head
          place(u, { ...m, h: h0, mb: 0 }); turn();
          const rest = m.rows.slice(k);                                             // what is left
          u = { ...u, el: tail, label: null }; m = { ...m, rows: rest, h: m.pt + m.head + rest.reduce((a, x) => a + x, 0), mt: 0 };
          continue;                                                                 // which may break again
        }
      }
      if (first) { place(u, m); break; }                                            // too tall for any page: it stays here, as the PDF lets it run on
      turn();                                                                       // the next page, where it starts at the top
    }
  }
  probe.remove();                                                                   // measured
  return pages;                                                                     // pages of placed units
}
function drawResume(m, host) {                                                      // the resume's pages, with the margin
  const style = themeVars(m);                                                       // its colours
  // measured in the printed face only: a page laid out before Pretendard has loaded would break its lines elsewhere. With the
  // face there (every redraw after the first) the pages are drawn at once, in the frame the canvas keeps the reader's place in
  const faces = ["400 12px Pretendard", "700 12px Pretendard"];                     // the regular and the bold the resume prints in
  const draw = () => {
    if (!host.isConnected || host.childElementCount) return;                        // the canvas moved on while the face loaded
    const units = resumeUnits(m);                                                   // its parts
    const pages = paginate(units, style);                                           // laid onto A4
    const width = host.clientWidth || 900, phone = PHONE.matches;                   // the canvas's room; a phone's pages are scaled down whole (fitPhone)
    const twoUp = !phone && pages.length > 1 && width >= 2 * (A4.w * 0.86 + 104) + 24;   // a wide screen shows a spread
    const zoom = phone ? 1 : Math.max(0.5, Math.min(1.12, ((twoUp ? (width - 24) / 2 : width) - 104) / A4.w));  // the page as large as fits
    const grid = h("div", { class: "pages", style: `--cols:${twoUp ? 2 : 1}` });    // one or two columns
    const P = m.person || {};                                                       // whose pages: the name on every foot
    pages.forEach((placed, i) => {                                                  // each page
      const margin = h("div", { class: "marginal", "aria-hidden": "true" });        // the notebook's margin beside it
      let lastLabel = null;                                                         // one label per section
      for (const { unit, top } of placed) {                                         // each unit on it
        const y = (A4.top + top) * zoom;                                            // its top on screen
        if (unit.label && unit.label !== lastLabel) {                               // a section starts here
          margin.append(h("div", { class: "mlabel", style: `top:${y}px`, text: unit.label.startsWith("list:") ? unit.label.slice(5) : t(MARGIN_NAME[unit.label] || "Lists") }));  // its name, in the app's language (another list: its own heading)
          lastLabel = unit.label;                                                   // once
        }
        const bad = unit.sids.some((sid) => (m.sentences[sid] || {}).state === "unsupported");  // a sentence without evidence here
        const locked = unit.sids.some((sid) => (m.sentences[sid] || {}).locked);    // a locked sentence here
        if (bad) margin.append(h("div", { class: "mlabel bad", style: `top:${y + 18 * zoom}px`, text: t("No evidence") }));  // said in words, not by colour alone
        else if (unit.sids.some((sid) => inKorean(m, m.sentences[sid]))) margin.append(h("div", { class: "mlabel kr", style: `top:${y + 18 * zoom}px`, text: t("In Korean") }));   // the English edition's untranslated words
        if (bad || locked) margin.append(h("div", { class: "mdot " + (bad ? "bad" : "lock"), style: `top:${y + 3}px` }));  // the dot on the margin line
      }
      if (placed.length) placed[0].unit.el.classList.add("top0");                   // no space above a page's first paragraph, as printed
      const foot = h("div", { class: "r-foot", "aria-hidden": "true" }, h("b", { text: P.name || "" }),   // the name and the page on every foot (layout.js setFooterName)
        m.lang !== "en" && P.name_en ? h("span", { class: "en", text: "  " + P.name_en }) : null,
        h("span", { class: "pg" }, h("b", { text: String(i + 1) }), h("span", { class: "of", text: ` / ${pages.length}` })));
      const sheet = h("article", { class: "sheet rs", style: `${style};--zoom:${zoom}`, "aria-label": t("Page {n} of {m}", { n: i + 1, m: pages.length }) },
        placed.map((p) => p.unit.el), foot);
      grid.append(h("div", { class: "pagewrap" }, margin, sheet));                  // the margin, then the page
    });
    host.append(grid);                                                              // on the desk
    if (phone && UI.pageZoom !== "actual") fitPhone(grid);                          // a phone: each page at A4, scaled to the phone's width
    else if (phone) grid.classList.add("actual");                                   // or at its own size, the pages sliding sideways: a sentence a finger can hit
    placeCites(grid, m);                                                            // the source numbers beside the sentences, once the lines are where they print
    $("canvas").dataset.ready = "resume";                                           // the first-run timer waits for this
  };
  if (faces.every((f) => document.fonts.check(f))) draw();                          // loaded: now
  else Promise.all(faces.map((f) => document.fonts.load(f).catch(() => null))).then(draw);   // else once they are
}
// A phone shows the same A4 pages as the desk, laid out at their printed size and scaled down as one picture (the deck's
// slides are shown so): its lines break where the PDF breaks them, and a pinch enlarges them. The scale is the room across
// the page grid over the page's width; the negative margins give the scaled page the room it takes, so the grid neither
// leaves the A4 height under it nor runs past the window. Measured twice, as the deck is: the first pages can bring a scroll
// bar that takes its own width from the window
addEventListener("resize", () => requestAnimationFrame(refitInPlace));             // a frame later: inside the resize event Firefox still answers the phone query for the old width
function refitInPlace() {                                                           // the window changed while a sentence is typed over: the canvas is not redrawn
  if (!UI.inplace) return;                                                          // under the caret, so the pages it holds are fitted where they stand
  const grid = document.querySelector("#canvas .pages");                            // the pages of the resume in view
  if (!grid) return;
  if (PHONE.matches) {                                                              // a phone now: one page under another, each scaled to its width
    if (!grid.dataset.cols) grid.dataset.cols = grid.style.getPropertyValue("--cols") || "1";   // a wide screen's spread, kept to put back
    grid.style.setProperty("--cols", "1");
    if (UI.pageZoom !== "actual") fitPhone(grid); else grid.classList.add("actual");   // fitted, or at its own size
  } else {                                                                          // wide again: the spread and the desk's own scale come back
    if (grid.dataset.cols) { grid.style.setProperty("--cols", grid.dataset.cols); delete grid.dataset.cols; }
    for (const s of grid.querySelectorAll(".sheet.rs")) { s.style.transform = ""; s.style.marginRight = ""; s.style.marginBottom = ""; delete s.dataset.fit; }
  }
  // the source numbers placed again for the new width (a phone's pages are laid out at zoom 1, the desk's at its own, and a
  // line's end moves by a pixel or two with it): the old set taken off first, the sentence being typed keeps its own aside
  grid.querySelectorAll(".cite.over").forEach((x) => x.remove());
  try { placeCites(grid, resumeModel()); } catch (_) { /* no model in hand: the numbers come back when the typing ends */ }
  grid.querySelectorAll(`.cite.over[data-for="${CSS.escape(UI.inplace)}"]`).forEach((x) => { x.hidden = true; });
}
function zoomSeg() {                                                               // a phone's choice: the page fitted to the screen, or at its own size to read and tap
  if (!PHONE.matches || UI.doc !== "resume" || UI.mode === "typeset") return null;   // the live resume on a phone only
  const now = UI.pageZoom === "actual" ? "actual" : "fit";
  return h("div", { class: "seg zoomseg", role: "group", "aria-label": t("Page size") }, [["fit", "Fit the screen"], ["actual", "Actual size"]].map(([k, w]) =>
    h("button", { type: "button", "aria-pressed": now === k ? "true" : "false", onclick: () => { UI.pageZoom = k; $("canvas")._key = null; render(); }, text: t(w) })));
}
function fitPhone(grid) {
  for (let pass = 0; pass < 2; pass++) {
    const cs = getComputedStyle(grid);                                              // the grid's own padding is not room for the page
    const room = grid.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
    const k = Math.min(1, room / A4.w) || 0.4;                                      // never enlarged
    for (const sheet of grid.querySelectorAll(".sheet.rs")) {                       // every page alike
      sheet.dataset.fit = k.toFixed(4);                                             // read by placeCites (pageScale)
      sheet.style.transform = `scale(${k})`;                                        // the page as one picture
      sheet.style.marginRight = `${(-(1 - k) * A4.w).toFixed(2)}px`;                // the room it takes across
      sheet.style.marginBottom = `${(-(1 - k) * A4.h).toFixed(2)}px`;               // and down
    }
  }
}
const pageScale = (sheet) => (parseFloat(getComputedStyle(sheet).zoom) || 1) * (parseFloat(sheet.dataset.fit) || 1);   // screen px per page px: the desk's zoom, a phone's scale
function onLabel(block, right, w, zoom, box, labelUsed, mark) {                    // a sentence in a narrow box whose last line is full: its numbers at the
  const br = block.getBoundingClientRect();                                         // right end of the box's own label line above it ("강점", "한 일"), inside
  if ((br.right - box.left) / zoom > A4.w - 80) return false;                       // the box; a full-width paragraph keeps the page's right margin
  const label = block.previousElementSibling;                                       // the box's label, printed on its own line above the words
  if (!label || label.tagName !== "B") return false;
  const lr = label.getBoundingClientRect(), lh = parseFloat(getComputedStyle(label).lineHeight) || 16;
  if (lr.height > lh * zoom * 1.6) return false;                                    // a label on more than one line has no free end
  const words = document.createRange(); words.selectNodeContents(label);           // the label's words, not its box (a block as wide as the card)
  const wr = words.getBoundingClientRect();
  const taken = labelUsed.get(label) || 0;                                          // numbers already there, from the right
  const x = (right - box.left) / zoom - w - taken;                                  // right-aligned in the box, the earlier numbers to its right
  if ((wr.right - box.left) / zoom + 4 > x) return false;                           // no room beside the label's words
  mark.style.cssText = `left:${x.toFixed(2)}px;top:${((lr.top - box.top) / zoom - 1).toFixed(2)}px`;
  labelUsed.set(label, taken + w + 2);
  return true;
}
function placeCites(grid, m) {                                                      // each sentence's source numbers where the PDF has white space
  const last = new Map();                                                           // a sentence's last piece (one broken across two pages has two)
  for (const s of grid.querySelectorAll(".rs .s[data-sid]")) last.set(s.dataset.sid, s);
  const used = new Map();                                                           // the right margin's room taken on each line, per page
  const labelUsed = new Map();                                                      // a box label's room taken by numbers already, from its right end
  for (const [sid, s] of last) {                                                    // each sentence once
    const rec = m.sentences[sid], mark = rec && citeMark(m, rec);                   // its numbers, if it rests on any
    if (!mark) continue;                                                            // the person's own words, or none to show
    const sheet = s.closest(".sheet"), zoom = pageScale(sheet);                     // its page, drawn at the page's zoom or a phone's scale
    const box = sheet.getBoundingClientRect(), rects = s.getClientRects();          // the page and the sentence's lines
    const r = rects[rects.length - 1];                                              // its last line
    if (!r) continue;                                                               // not laid out
    const block = s.parentElement.closest("p, td, th, div"), bs = getComputedStyle(block);   // the paragraph or cell it ends in
    let right = block.getBoundingClientRect().right - (parseFloat(bs.paddingRight) || 0) * zoom;   // where that line may end:
    for (const d of block.querySelectorAll(".date")) {                              // before a date at the right tab on the same line
      const q = d.getBoundingClientRect();
      if (Math.abs(q.top - r.top) < 3 * zoom) right = Math.min(right, q.left);
    }
    const after = document.createRange();                                           // whatever follows it in that paragraph or cell:
    after.setStartAfter(s); after.setEnd(block, block.childNodes.length);           // the next sentence, or words that are no sentence (a strength's projects)
    const goesOn = [...after.getClientRects()].some((q) => q.width > .5 && Math.abs(q.top - r.top) < 3 * zoom);   // on its last line: the number would lie over them
    mark.classList.add("over"); mark.dataset.for = sid;                             // a number laid over the page
    if (UI.sel === sid) mark.classList.add("sel");                                  // the one the inspector shows
    sheet.append(mark);                                                             // measured once on the page
    const w = mark.getBoundingClientRect().width / zoom;                            // its width in the page's own px
    const top = (r.top - box.top) / zoom - 1;                                       // its line, a little raised
    if (!goesOn && r.right + (2 + w) * zoom <= right) mark.style.cssText = `left:${((r.right - box.left) / zoom + 2).toFixed(2)}px;top:${top.toFixed(2)}px`;   // after the words, where the line ends with them
    else if (onLabel(block, right, w, zoom, box, labelUsed, mark)) { /* placed on its box's label line */ }   // a narrow box (a column card, a project card): on its own label's line, never the page's margin
    else {                                                                          // the line goes on: beside it, in the right margin
      const taken = used.get(sheet) || new Map(); used.set(sheet, taken);           // the margin's room already taken on this page, per line
      let key = String(Math.round(top)), dy = 0;                                    // the line's row of numbers
      if ((taken.get(key) || 0) && (taken.get(key) || 0) + w > 44) { key += "+"; dy = 9.5; }   // a full row: the next number goes under it, not off the page
      const x = taken.get(key) || 0;                                                // where in its row
      mark.style.cssText = `left:${(A4.w - 47 + x).toFixed(2)}px;top:${(top + dy).toFixed(2)}px`;
      taken.set(key, x + w + 2);                                                    // the next one goes after it
    }
  }
}

// ---------------------------------------------------------------- the cover letter and the typeset pages

function drawCover(c, m, host) {                                                    // the cover letter as a page, every sentence a key
  const P = (m && m.person) || {};                                                  // the person, from the resume model
  const sheet = h("article", { class: "sheet", style: themeVars(m || {}), "aria-label": t("Cover letter") },
    h("div", { class: "c-letter" }, h("h2", { text: P.name || "" }),
      h("div", { style: "font-size:11px;color:#4a4a4a" }, (P.contacts || []).map(([, v]) => v).join(" · ")),
      (c.job && c.job.company) ? h("div", { style: "font-weight:700", text: [c.job.company, c.job.role].filter(Boolean).join(" · ") }) : null,
      c.paragraphs.map((p) => h("p", {}, p.sentences.map((s, i) => [i ? " " : "",
        h("span", { class: "s" + (s.state === "unsupported" ? " unsupported" : "") + (UI.sel === s.sid ? " sel" : ""), "data-sid": s.sid, tabindex: "0", role: "button",
          "aria-pressed": UI.sel === s.sid ? "true" : "false" }, marks(s.text))]))),
      c.signature ? h("div", { class: "sig", text: c.signature }) : null));
  host.append(h("div", { class: "pages" }, h("div", { class: "pagewrap" }, h("div", { class: "marginal", "aria-hidden": "true" }), sheet)));
  $("canvas").dataset.ready = "cover";                                              // drawn
}
function drawLiveDeck(d, host) {                                                    // the slides in a frame: the page has the deck's own styles and runs nothing
  const wrap = h("div", { class: "deckframe" });                                    // holds the frame at the pane's width
  const frame = h("iframe", { title: t("Portfolio deck"), sandbox: "allow-same-origin", tabindex: "-1" });  // no scripts run in it, so the panel's address is safe to share
  frame.srcdoc = d.html;                                                            // the page, made on the server
  wrap.append(frame);                                                               // in place
  host.append(wrap);                                                                // on the canvas
  const fit = () => {                                                               // a slide is 1280 wide: the frame is scaled, so the slides stay as they print
    let scale = 0.5;                                                                // until measured
    frame.style.height = `${d.slides * (720 + 24)}px`;                              // every slide and its gap
    // measured twice: the first height can make the page tall enough for a scroll bar, which on Windows takes its own width
    // from the pane (overlay scroll bars take none), and the second measure fits what is left
    for (let pass = 0; pass < 2; pass++) {
      scale = Math.min(wrap.clientWidth, 960) / 1280 || 0.5;                        // 960 at most, as the typeset slides are shown
      frame.style.transform = `scale(${scale})`;                                    // the whole frame
      wrap.style.height = `${Math.ceil((d.slides * (720 + 24) - 24) * scale)}px`;   // the space it takes on the canvas
    }
    wrap.style.width = `${Math.floor(1280 * scale)}px`;                             // and across, never a pixel past the pane
  };
  requestAnimationFrame(() => { wrap.style.width = "100%"; fit(); });               // measured once in the page; the pane is drawn again when its width changes
}
function drawShots(kind, host) {                                                    // the typeset pages of the job in view, else of the general edition
  const j = edition(), lang = docLang();                                            // the job and the edition
  const b = j && j.builds && j.builds[lang];                                        // its edition
  const n = b ? (kind === "deck" ? b.slides : kind === "cover" ? ((b.cover || {}).pages || 0) : b.pages) : 0;  // how many pages
  if (!n) return false;                                                             // nothing typeset yet
  const pre = { resume: "r", deck: "d", cover: "c" }[kind];                         // the pictures' prefix
  // a stamp per made document: its PDF's hash, so pages made again within the same minute (the blind switch) are never the browser's older pictures
  const v = (b.hashes || {})[kind + ".pdf"] || b.at || "";
  const imgs = Array.from({ length: n }, (_, i) => h("img", { class: "shot", src: `/api/v1/jobs/${enc(j.id)}/files/${lang}/preview/${pre}-${i + 1}.png?v=${enc(v)}`, loading: "lazy",
    alt: t("{doc}, page {n} of {m}", { doc: t(kind === "deck" ? "Portfolio deck" : kind === "cover" ? "Cover letter" : "Resume"), n: i + 1, m: n }) }));
  if (kind === "deck") { host.append(h("div", { class: "shots deck" }, imgs)); return true; }   // the slides at the width the live deck has
  // a resume's or a letter's pages laid out as the live pages are: the same margin column, the same size, a spread on a wide
  // screen, so switching between Live and Typeset PDF keeps the page where it stood
  const grid = h("div", { class: "pages shotpages" }, imgs.map((img) => h("div", { class: "pagewrap" }, h("div", { class: "marginal", "aria-hidden": "true" }), img)));
  host.append(grid);
  requestAnimationFrame(() => {                                                     // measured once in the page, as drawResume measures
    if (!grid.isConnected || PHONE.matches) return;                                // a phone's pages fill its width (app.css)
    const width = grid.parentElement.clientWidth || 900;                            // the canvas's room
    const twoUp = n > 1 && width >= 2 * (A4.w * 0.86 + 104) + 24;                   // a wide screen shows a spread
    const zoom = Math.max(0.5, Math.min(1.12, ((twoUp ? (width - 24) / 2 : width) - 104) / A4.w));   // the page as large as fits, as the live page is
    grid.style.setProperty("--cols", twoUp ? "2" : "1");
    imgs.forEach((img) => { img.style.width = `${(A4.w * zoom).toFixed(1)}px`; });
  });
  return true;                                                                      // drawn
}

// ---------------------------------------------------------------- the documents view

function viewDocuments(host) {                                                      // the canvas with the document as it will print
  const m = resumeModel();                                                          // the resume model (null while it loads)
  const j = job();                                                                  // the job in view
  const lang = docLang();                                                           // the document's language
  const docTabs = h("div", { class: "seg", role: "tablist", "aria-label": t("Document") }, [["resume", "Resume", "file"], ["cover", "Cover letter", "mail"], ["deck", "Portfolio deck", "slides"]].map(([k, w, ic]) =>
    h("button", { role: "tab", "aria-selected": UI.doc === k ? "true" : "false", onclick: () => { UI.doc = k; UI.sel = null; render(); } }, icon(ic), t(w))));
  const modes = ownFileIn(edition(), UI.doc) ? null : h("div", { class: "seg", "aria-label": t("View") }, [["live", "Live"], ["typeset", "Typeset PDF"]].map(([k, w]) =>   // a file the person made is shown as its pages only
    h("button", { "aria-pressed": UI.mode === k ? "true" : "false", onclick: () => { UI.mode = k; render(); }, text: t(w) })));
  const cov = UI.doc === "cover" ? coverModel() : null;                              // the cover letter, on its tab
  const counts = (cov && cov.state === "drafted" ? cov.counts : null) || (UI.doc === "cover" ? {} : (m && m.counts)) || {};  // the evidence totals of the document on screen
  const evsum = !m || !counts.sentences || UI.doc === "deck" || ownFileIn(edition(), UI.doc) || m.missing && m.missing.length && !(m.blocks || []).length ? null :   // a file the person made has no sentences of Offerowl's; the deck's are the resume's
    h("span", { class: "evsum" }, counts.unsupported ? h("span", { class: "chip bad", text: t("{n} without evidence", { n: counts.unsupported }) })
      : h("span", { class: "chip ok", text: t("Every sentence has evidence") }), h("span", { class: "sep", "aria-hidden": "true", text: "·" }), tn(counts.sentences || 0, "{n} sentence", "{n} sentences"));   // two facts, apart
  const ed = edition(), b = ed && ed.builds && ed.builds[lang];                     // the typeset edition
  const sent = !!(j && j.locked && j.locked.lang === lang);                         // submitted in this language: export gives the copies that went out
  const why = sent ? null : !b ? t("Make the PDFs to export them.") : counts.unsupported > 0 ? t("Every sentence needs evidence before export.") : null;   // why export waits, said beside it
  const emptyCover = UI.doc === "cover" && (!j || !(coverModel() || {}).state || (coverModel() || {}).state !== "drafted");   // the cover letter's tab with no letter yet: its own key leads there
  const exportBtn = h("button", { class: "btn" + (b && !emptyCover ? " primary" : ""), disabled: why || null,   // export needs the PDFs, and evidence everywhere; the main key once they are there
    title: why, onclick: () => exportPdfs() }, icon("desktop"), t("Export to Desktop"));
  const building = !!ed && task("build:" + ed.id).state === "running";              // PDFs on the way
  const frozen = !!(j && j.locked);                                                  // a submitted application is not made again
  // the next step before any PDF, once there is an edition to make them of; a submitted application has none (its lock says so
  // beside it: a key that could not be pressed only said why on a hover a phone cannot show)
  const makeBtn = frozen ? null : h("button", { class: "btn" + (b || !ed ? "" : " primary"), disabled: !ed || building || null,
    onclick: () => makePdfs() }, icon("file"), building ? t("Making the PDFs…") : t("Make PDFs"));
  // The blind edition's switch: on, the PDFs are made again with the names of the person's table under bars. It shows what the
  // pages are, or while they are made, what was asked for them
  const asked = building && UI.blindAsk && UI.blindAsk.key === (ed ? ed.id : "") + "|" + lang ? UI.blindAsk.on : null;   // the switch pressed for this edition, while it is made
  const blindSwitch = !ed ? null : h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: asked === null ? !!(b && b.blind) : asked,   // the pages as they are, or as asked
    disabled: building || !!S.engine || !!(j && j.locked) || null, onchange: (e) => makeBlind(e.target.checked) }), h("span", { class: "track" }), t("Blind edition"));   // a submitted edition stays as it went
  // a document the person made: their own file stands for the typeset resume, or the resume they wrote prints as written
  // a state, not a key: words with their sign, never a box the height of the keys beside them
  const ownChip = b && (b.notes || []).includes("own_file") ? h("span", { class: "docstate" }, icon("file", 14), h("span", { text: t("Your own file") }))
    : ed && (ed.own || []).includes(lang) ? h("span", { class: "docstate" }, icon("edit", 14), h("span", { text: t("As you wrote it") })) : null;
  const lockBtn = !j ? null : j.locked ? h("span", { class: "docstate ok" }, icon("lock", 14), h("span", { text: t("Submitted and locked") })) :  // the general edition is never submitted
    h("button", { class: "btn lockkey", disabled: !b || counts.unsupported > 0 || null, onclick: () => lockJob(j.id), title: t("Lock when submitted"), "aria-label": t("Lock when submitted") },
      icon("lock"), h("span", { class: "w", text: t("Lock when submitted") }));  // the rule of the export; on a phone its sign alone, beside the other two
  const jobName = j ? [j.company, j.role].filter(Boolean).join(", ") || j.id : "";  // the application in view
  // "For {job}" only when this edition was written or brought in for it; a job with none of its own shows the general
  // resume, and says so (a submitted application's own files are its own)
  const ownForJob = !!(j && ((m && m.draft && m.draft.own) || (ed && (ed.own || []).includes(lang)) || ownFileIn(ed) || (j.locked && j.locked.brought)));
  fill($("dochead"),                                                                // the head, over the document and its inspector
    h("div", { class: "viewhead" }, h("h1", { text: t("Documents") }),
      h("span", { class: "sub", text: j ? (ownForJob ? t("For {job}", { job: jobName }) : t("For {job}: the general resume as it is", { job: jobName })) : named() ? named().name : (S.jobs || []).length ? t("General edition") : t("Your general edition: add a job to tailor it") }),
      h("span", { class: "grow" }), h("div", { class: "docacts" }, ownChip, blindSwitch, writeKey(), makeBtn, h("span", { class: "expgrp" }, exportBtn, lockBtn)),   // the page's actions beside its title, as one group; Export and its lock on one row
      named() ? h("button", { class: "btn small quiet danger edrm", type: "button", "data-key": "edition-remove", "aria-label": t("Remove the edition {name}", { name: named().name }),   // a named edition: off the list, into the Trash; at the row's end, away from its name and the keys that make it
        onclick: () => removeAct("/api/v1/jobs/remove", { job: named().id }, t("Removed the edition {name}. It waits in the trash.", { name: named().name })) }, icon("trash"), t("Remove this edition")) : null),
    // what is shown; why export waits at the row's right (under the keys it came and went, and the head jumped 27 px); the
    // inspector's key at the row's end where it is a drawer
    h("div", { class: "doctools" }, docTabs, modes, zoomSeg(), evsum, h("span", { class: "grow" }), why && !counts.unsupported ? h("span", { class: "hint why", text: why }) : null,
      h("button", { class: "btn insp-toggle", onclick: () => { UI.drawer = true; render(); }, "aria-label": t("Open the inspector") }, icon("panel"), t("Inspector"))));
  fill(host,
    buildBand(ed),                                                                  // the last PDFs of this edition failed: why, with the key that fixes it
    counts.unsupported ? h("div", { class: "band" }, h("p", { text: UI.doc === "cover"   // the letter's sentences have no Edit of their own: what can be done there
      ? t("A sentence with no evidence is marked with a red wave and cannot be exported. Write the letter again, or put the evidence in your profile.")
      : t("A sentence with no evidence is marked with a red wave and cannot be exported. Click it to fix it, regenerate it or put the evidence in your profile.") }),
      h("button", { class: "btn small", onclick: () => selectNextBad(), text: t("Show the first one") })) : null,
    blindBand(b),                                                                   // a blind edition says what its pages are
    checksBand(b),                                                                  // the checks its typeset pages failed, which keep them home
    polishBand(b),                                                                  // and what they would polish, which does not
    docBody(m, j));
  // one main key in sight: an empty page's own next step, or the Save of a sentence being edited in the inspector, outranks the head's
  if (UI.editing || host.querySelector(".btn.primary")) $("dochead").querySelectorAll(".btn.primary").forEach((k) => k.classList.remove("primary"));
  host.dataset.ready = "";                                                          // set again once the pages are drawn
}
// The document checks' findings by their codes (src/check_documents.py --report, src/check_lines.py), in the page's language:
// a line the checks wrote in another language, or one with no code (a layout check, a deck's own), is shown as written
const CHECK_WORDS = {
  too_long: "{pages} pages, over the limit of {limit}.", no_role: "A company is missing from the resume: {name}", no_project: "A project is missing from the resume: {name}",
  korean_left: "Korean is left in the English edition: '{text}' ({n} places)", no_text: "The resume's text could not be read.",
  form_suffix: "The education table writes '{value}' ({school}) unlike its other lines, which end in '{suffix}'.", banned: "A character your rules ban is printed: '{c}'",
  no_pack: "The writing rules file could not be read.", no_probe: "The deck's measurement is missing.", slide_count: "The deck's PDF has {pages} pages for {slides} slides.",
  not_wide: "The deck's pages are not 16:9.", slide: "Slide {n}: {what}", empty_value: "A value the build left empty is printed: '{word}'",
  markup_left: "Marks are printed as typed ({marks}): '{near}'", editing_note: "An editing note is printed ({why}): '{near}'",
  comma_ending: "A comma after a connective ending: '{near}'", instead: "The contrastive '{word}': '{near}'", not_a_but_b: "'{form}' {n} times; your rules allow {limit}.",
  latin_and: "와/과 between Latin words, where your rules write a slash: '{near}'", colloquial: "A machine said to act like a person: '{near}'",
  repeated_word: "The same word twice in one sentence ({word}): '{near}'", hl_broken: "A highlight breaks across two lines: '{text}'",
  hl_size: "A highlight of {size}; your rules say {lo} to {hi}: '{text}'", hl_name: "A name inside a highlight ({names}): '{text}'",
  hl_missing: "A highlight was not found on the page: '{text}'", last_word: "A paragraph ends on '{tail}' alone: '…{end}'",
  para_missing: "A paragraph was not found on the page: '{text}…'", no_words: "No words could be read from the PDF, so its lines were not measured.",
  deck_tool: "The deck's own check {tool}: {what}", deck_tool_failed: "The deck's own check {tool} did not run: {what}" };
function checkWords(x) {                                                            // one finding in the page's words
  if (typeof x === "string") return x === "check_failed" ? t("The checks did not run.") : x;   // a line as the checks wrote it
  if (!x || !CHECK_WORDS[x.code]) return (x && x.text) || "";                       // no code of the page's own: as written
  const size = x.code === "hl_size" ? (docLang() === "en" ? tn(x.size, "{n} word", "{n} words") : t("{n} letters", { n: x.size })) : "";   // a highlight's size in the edition's unit
  return t(CHECK_WORDS[x.code], { ...x, size });
}
function checksBand(b) {                                                            // the checks a typeset edition failed: what keeps its PDFs from going out
  const coded = b && Array.isArray(b.checks) && b.checks.length ? b.checks : null;  // the findings with their codes, when the build kept them
  const lines = b ? [...(coded || (b.issues || []).filter((x) => typeof x === "string" && x)), ...(((b.cover || {}).issues) || []).filter((x) => typeof x === "string" && x)] : [];
  if (!lines.length) return null;                                                   // passed, or not made
  return h("div", { class: "band", role: "status" }, h("p", { text: t("These documents did not pass their checks:") }),
    h("ul", { class: "checklist" }, lines.slice(0, 8).map((x) => h("li", { text: checkWords(x) }))),
    lines.length > 8 ? h("p", { class: "hint", text: t("{n} more", { n: lines.length - 8 }) }) : null);
}
function polishBand(b) {                                                            // what the checks would polish: said beside the pages, never a reason to keep them home
  const items = b && Array.isArray(b.polish) ? b.polish : [];
  if (!items.length || (b.issues || []).length) return null;                        // nothing to polish, or a failure says more first
  return h("div", { class: "band info", role: "status" }, h("p", { text: t("Worth a look before you send them:") }),
    h("ul", { class: "checklist" }, items.slice(0, 5).map((x) => h("li", { text: checkWords(x) }))),
    items.length > 5 ? h("p", { class: "hint", text: t("{n} more", { n: items.length - 5 }) }) : null);
}
function buildBand(ed) {                                                            // the last PDFs of an edition failed: the reason, and the key that fixes it
  const bt = ed ? task("build:" + ed.id) : {};
  if (bt.state !== "error" || !bt.error) return null;                               // made, never asked, or making now
  return band(bt.error.code, { retry: () => makePdfs(), detail: bt.error.detail });   // a missing English text offers the translation; anything else, to try again
}
function sentPanel(j, sent) {                                                       // a submitted application: the copies that went out, as they went
  const files = Object.entries(sent.files || {});                                   // name -> hash
  const label = (f) => (sent.brought && sent.name && f === "deck.pdf" ? sent.name : f === "resume.pdf" ? t("Resume") : f === "deck.pdf" ? t("Portfolio deck") : f === "cover.pdf" ? t("Cover letter") : f);
  return h("div", { class: "empty glass sent-panel" },
    h("h3", {}, icon("lock"), t("Submitted and locked")),
    h("p", { text: t("The copies that went out on {date} are kept as they went. Export them to your Desktop to read them.", { date: sent.at || "" }) }),
    h("ul", { class: "matlist" }, files.map(([f, hash]) => h("li", {}, h("span", { class: "nm", text: label(f) }), h("span", { class: "hint mono-hash", text: String(hash).slice(0, 12) })))),
    h("div", { class: "part-keys" }, h("button", { class: "btn primary", type: "button", onclick: async () => {   // the copies as they went, in the language they went in
        const r = await act("/api/v1/jobs/export", { job: j.id, lang: sent.lang });
        if (r && r.exported) toast(r.exported.length ? t("On your Desktop: {names}", { names: r.exported.join(", ") }) : t("Make the PDFs first."), null, r.exported.length ? "done" : "info");
      } }, icon("desktop"), t("Export to Desktop")),
      h("button", { class: "btn", type: "button", onclick: () => openApplication(j.id, "docs") }, icon("case"), t("Open the application"))));
}
function docBody(m, j) {                                                            // the page area under the toolbar
  const body = h("div", { id: "docbody" });                                         // where the pages go
  if (!m || m.error) return fill(body, h("div", { class: "empty glass" }, h("p", { text: t("Laying out your pages…") })));  // loading, or refused for now (never read as "no resume yet")
  const sent = j && j.locked ? j.locked : null;                                     // what this application sent, frozen
  // a submitted application with nothing to draw, or whose own files went out (no pages of Offerowl's, in either view: the
  // live page would draw a resume that never went out): the copies that went out, never an offer to write it again
  if (sent && (!(m.blocks || []).length || sent.brought) && UI.doc !== "cover") return fill(body, sentPanel(j, sent));
  if (m.missing && m.missing.includes("needs_translation") && UI.mode !== "typeset") return fill(body, band("needs_translation"));  // the English edition without its profile: the live canvas waits for it, the printed pages do not
  if (!(m.blocks || []).length) return fill(body, h("div", { class: "empty glass" }, h("h3", { text: t("Your resume starts with your files") }),  // nothing kept yet
    h("p", { text: t("Add an old resume, a portfolio or notes, and keep the facts you want. The resume appears here as it will print.") }),
    h("button", { class: "btn primary", onclick: () => go("profile"), text: t("Add material") })));
  const top = UI.doc === "deck" ? figureBand(m) : null;                             // what the agent can do for the deck
  const area = top ? h("div", {}) : body;                                           // the slides go under it
  if (top) body.append(top, area);                                                  // both in place
  if (UI.mode === "typeset" || ownFileIn(edition(), UI.doc)) {                    // the PDF's own pages (a file the person made has only those)
    const gone = blindLeft(UI.doc);                                                 // a document the blind edition left out
    if (gone) return fill(area, h("div", { class: "empty glass" }, h("h3", { text: t("Not in the blind edition") }), h("p", { text: t(BLIND_NOTES[gone]) }))), body;
    if (!drawShots(UI.doc, area)) fill(area, h("div", { class: "empty glass" }, h("h3", { text: t("No PDF yet") }),
      h("p", { text: t("Make the PDFs to see the typeset pages. The live canvas shows the same document now.") }),
      S.engine ? band(S.engine) : null));
    return body;                                                                    // drawn
  }
  if (UI.doc === "resume") {                                                        // the live resume
    const top = writeBand(m);                                                       // what the agent can do for it
    const pages = h("div", {});                                                     // the pages go here
    if (sent) body.append(h("div", { class: "band info", role: "status" }, h("p", { text: t("This page is drawn from your profile as it is now. The copies you sent stay as they went: Typeset PDF shows them.") }),
      h("button", { class: "btn small", onclick: () => { UI.mode = "typeset"; render(); }, text: t("Typeset PDF") })));   // a submitted application: what went out is in the PDFs
    const korean = m.lang === "en" ? Object.values(m.sentences || {}).filter((r) => inKorean(m, r)).length : 0;   // the English edition's sentences still in Korean
    if (korean) { const e = errorInfo("needs_translation"); body.append(h("div", { class: "band", role: "status" },   // said, marked on the page, with the key that translates them
      h("p", { text: tn(korean, "{n} sentence of the English edition is still in Korean. It is marked on the page.", "{n} sentences of the English edition are still in Korean. They are marked on the page.") }),
      e.sent ? sendNote(e.sent) : null, sent ? null : h("button", { class: "btn small agent", onclick: () => e.go(), text: e.fix }))); }
    if (top) body.append(top);                                                      // above the pages
    body.append(pages);                                                             // the pages' place
    requestAnimationFrame(() => { if (pages.isConnected && !pages.childElementCount) drawResume(m, pages); });  // laid out once in the page
    return body;                                                                    // drawn
  }
  if (UI.doc === "cover") {                                                         // the cover letter
    const c = coverModel();                                                         // its model
    if (!j) return fill(body, h("div", { class: "empty glass" }, h("h3", { text: t("A cover letter is written for one job") }), h("button", { class: "btn primary", onclick: () => go("jobs"), text: t("Add a job") })));
    if (sent && !Object.keys(sent.files || {}).includes("cover.pdf")) return fill(body, h("div", { class: "empty glass" }, h("h3", { text: t("No cover letter went out") }),   // submitted without one: nothing to write now
      h("p", { text: t("The copies you sent on {date} hold no cover letter.", { date: sent.at || "" }) })));
    if (sent && (!c || c.state !== "drafted" || sent.brought)) return fill(body, sentPanel(j, sent));   // the letter that went out, as it went
    if (!c) return fill(body, h("div", { class: "empty glass" }, h("p", { text: t("Laying out your pages…") })));
    if (c.state !== "drafted") return fill(body, h("div", { class: "empty glass" }, h("h3", { text: t("No cover letter yet") }),
      h("p", { text: t("The agent writes it from this job's posting and your evidence, and every sentence names the fact it rests on.") }),
      sendNote(t("Tailoring sends the posting and your evidence to the agent.")),
      S.agent.state !== "ready" ? h("div", { class: "band info" }, h("p", { text: t("Writing it needs the agent: turn it on to have it written.") }),   // nothing failed: it was never asked
        h("button", { class: "btn small", onclick: () => openAgentMenu(), text: t("Turn on the agent") }))
        : h("button", { class: "btn primary", onclick: () => tailorJob(j.id), text: t("Tailor this job") })));
    drawCover(c, m, body); return body;                                             // the letter
  }
  const d = deckModel();                                                            // the deck as it will print
  if (!d) return fill(area, h("div", { class: "empty glass" }, h("p", { text: t("Laying out your pages…") }))), body;  // loading
  if (d.html) { drawLiveDeck(d, area); return body; }                               // the slides now
  if (d.missing === "needs_translation") return fill(area, band("needs_translation")), body;  // the English edition without its profile
  if (d.missing === "build_failed") area.append(band("build_failed"));              // the slides cannot be drawn: why, above the last printed ones
  if (d.missing === "own_deck") area.append(h("p", { class: "hint", text: t("Your own portfolio, page for page as you made it. Make the PDFs to see it here.") }));   // a deck the person made: its printed pages
  if (drawShots("deck", area)) return body;                                         // no live page: its slides as printed, once there are any
  fill(area, h("div", { class: "empty glass" }, h("h3", { text: t("The deck is made with the PDFs") }),  // none yet
    h("p", { text: t("Its slides come from the same profile. Make the PDFs to see them, then switch to Typeset PDF.") }),
    h("button", { class: "btn", onclick: () => { UI.mode = "typeset"; makePdfs(); }, text: t("Make PDFs") })));
  return body;                                                                      // drawn
}
function figureBand(m) {                                                            // the deck's figures: the state of drawing them, and the button
  const ed = edition(), d = m && m.draft, tk = ed ? task("figures:" + ed.id) : {};  // the edition, its draft, the drawing now
  if (!ed || (job() && job().locked)) return null;                                  // nothing to draw for
  if (deckModel() && deckModel().missing === "own_deck") return null;               // the person's own portfolio: nothing to draw
  if (tk.state === "running") return h("div", { class: "band ai" }, pill("busy", t("Drawing the figures from your evidence")), h("span", { class: "hint", text: t("This can take several minutes.") }));  // shown while it runs
  const error = tk.state === "error" ? band(tk.error.code, { retry: () => drawFigures(ed.id) }) : null;  // why the last try stopped
  if (d && d.figures && d.drawn && d.drawn.added) return h("div", { class: "band info" }, h("p", { text: tn(d.drawn.added, "{n} figure is in the deck.", "{n} figures are in the deck.") +   // what the deck holds now,
    (d.drawn.left_out ? " " + tn(d.drawn.left_out, "{n} more was left out: it said what the evidence does not.", "{n} more were left out: they said what the evidence does not.") : "") }), error);   // and what the checks kept out, and why
  if ((d && d.figures) || !agentOn()) return error;                                 // drawn, or no agent to draw them
  if (!d) return h("div", { class: "band offer" }, h("p", { text: t("When the agent writes the resume, its sentences go into the slides.") }), error);   // no draft yet: the slides take the facts' words until one is written (the head's key writes it, as on the resume tab)
  return h("div", { class: "band offer" }, h("p", { text: t("The agent can draw figures for each project from its evidence. A figure that says what the evidence does not is left out.") }),  // what it does
    sendNote(t("Drawing sends each project's evidence to the agent.")), h("button", { class: "btn small", onclick: () => drawFigures(ed.id), text: t("Draw the figures") }), error);  // what it sends, and the button
}
function drawFigures(jid) { return act("/api/v1/jobs/figures", { job: jid, lang: docLang() }); }  // the task starts; the band follows it
function markSelected() {                                                           // the selected sentence and its numbers marked on the page as they stand: a click redraws no page
  const canvas = $("canvas"); if (!canvas) return;
  for (const el of canvas.querySelectorAll(".s[data-sid]")) {                       // every sentence
    const on = el.dataset.sid === UI.sel;
    if (el.classList.contains("sel") !== on) el.classList.toggle("sel", on);       // only what changed
    el.setAttribute("aria-pressed", on ? "true" : "false");
  }
  for (const el of canvas.querySelectorAll(".cite.over[data-for]")) el.classList.toggle("sel", el.dataset.for === UI.sel);   // its numbers
}
function select(sid) {                                                              // a sentence opens its evidence
  UI.sel = sid; UI.editing = false; UI.tab = "evidence"; forget("sentence-edit");    // the inspector shows it
  if (window.matchMedia("(max-width: 1000px)").matches) UI.drawer = true;           // the drawer opens where the rail sits under the page
  render();                                                                         // drawn
}
function selectNextBad() {                                                          // the first sentence without evidence
  const cov = UI.doc === "cover" ? coverModel() : null, m = resumeModel();          // the letter when it is on screen, else the resume
  const sid = cov && cov.paragraphs ? ((cov.paragraphs.flatMap((p) => p.sentences).find((s) => s.state === "unsupported") || {}).sid)  // the letter's first one
    : m && Object.keys(m.sentences).find((k) => m.sentences[k].state === "unsupported");  // the resume's first one
  if (sid) { select(sid); const el = document.querySelector(`[data-sid="${CSS.escape(sid)}"]`); if (el) el.scrollIntoView({ block: "center" }); }
}
async function makePdfs(blind) {                                                   // the typeset PDFs of the job in view
  const ed = edition(); if (!ed) return;                                            // the job in view, else the general edition
  if (S.engine) { toast(errorInfo(S.engine).msg, null, "bad"); return; }                         // the typesetting cannot run here
  const b = ed.builds && ed.builds[docLang()];                                      // the edition as last made
  // a blind edition stays blind and an ordinary one ordinary, unless the switch says otherwise; before the first PDFs the server
  // decides (a resume brought in as a blind edition is made blind)
  const keep = blind === undefined ? (b ? !!b.blind : undefined) : blind;
  const own = b && Number(b.maxPages);                                              // the limit the PDFs on screen were made with
  const pages = blind !== undefined && own ? own : UI.maxPagesChosen || !own ? UI.maxPages : own;   // the switch keeps it; the key uses the one picked in the Style tab, else keeps it
  await act("/api/v1/jobs/build", { job: ed.id, lang: docLang(), theme: UI.theme, maxPages: pages, cover: UI.cover && !!job(), blind: keep });  // started; a letter needs a job
}
function makeBlind(on) {                                                            // the blind edition's switch: the PDFs again, with or without the bars
  const ed = edition(); if (!ed) return;                                            // nothing to make
  UI.blindAsk = { key: ed.id + "|" + docLang(), on };                               // the switch shows what was asked while the PDFs are made
  UI.mode = "typeset";                                                              // the bars are on the typeset pages: show them
  makePdfs(on);                                                                     // made again
}
// What a blind edition leaves out, said where the document would be (src/blind.js cannot cover a file the person made)
const BLIND_NOTES = { blind_no_deck: "The portfolio you made is not in the blind edition: its pages cannot be covered.",
  blind_no_cover: "The cover letter is not in the blind edition: it is written to one company by name.",
  blind_own_file: "The blind edition's resume is typeset from your words: the file you brought in cannot be covered." };
function blindLeft(doc) {                                                           // the note of a document the blind edition left out, or null
  const ed = edition(), b = ed && ed.builds && ed.builds[docLang()];                // the edition as made
  if (!b || !b.blind) return null;                                                  // an ordinary edition leaves nothing out
  if (doc === "cover") return "blind_no_cover";                                     // a blind edition never has a letter
  return doc === "deck" && (b.notes || []).includes("blind_no_deck") ? "blind_no_deck" : null;   // the deck, when it was the person's own
}
function blindBand(b) {                                                             // what a blind edition's pages are, above them
  if (!b || !b.blind) return null;                                                  // an ordinary edition
  const bl = S.blind || {}, typeset = UI.mode === "typeset";                        // the table in use; the view
  const words = [typeset ? t("These are the blind edition's pages: what your table covers is under bars, and the first page carries the blind band.")
    : t("The live canvas shows your words as they are. The blind edition's bars are on the typeset pages."),
    !((bl.counts || {}).mask) ? t("Your table covers nothing yet. Add your own in the inspector's Style tab.") : "",   // an empty table: only the band and the label
    (b.blind_table || "") !== (bl.stamp || "") ? t("Your table changed after these pages were made. Make the PDFs again.") : "",   // the bars are the older table's
    ...(b.notes || []).filter((n) => BLIND_NOTES[n] && n !== "blind_no_cover").map((n) => t(BLIND_NOTES[n]))].filter(Boolean);   // what it left out (the letter is said on its own tab)
  return h("div", { class: "band info", role: "status" }, h("p", { text: words.join(" ") }),
    typeset ? null : h("button", { class: "btn small", onclick: () => { UI.mode = "typeset"; render(); }, text: t("Typeset PDF") }));
}
function ownFileIn(ed, doc = "resume") {                                           // the edition's resume (or letter) is the person's own file in this language
  const b = ed && ed.builds && ed.builds[docLang()];                                // the typeset edition
  if (!b) return false;                                                             // not made yet
  return doc === "cover" ? !!(b.cover && b.cover.own) : doc === "resume" && (b.notes || []).includes("own_file");   // the build said so
}
function writeBand(m) {                                                             // the resume's state of writing, and the button that writes it
  const ed = edition(), d = m.draft, tk = ed ? task("write:" + ed.id) : {};         // the edition, its draft, the writing now
  if (!ed || (job() && job().locked)) return null;                                  // nothing to write for: no edition, or it was submitted
  if ((ed.own || []).includes(docLang()) || ownFileIn(ed)) return null;            // the person's own edition or file: written already, printed as it is
  if (tk.state === "running" || task("tailor:" + ed.id).state === "running") return h("div", { class: "band ai" }, pill("busy", t("Writing the resume from your evidence")), h("span", { class: "hint", text: t("This can take several minutes.") }));  // shown while it runs, on its own or as part of tailoring
  const error = tk.state === "error" ? band(tk.error.code, { retry: () => writeResume(ed.id) }) : null;  // why the last try stopped
  const own = d && d.own;                                                           // this edition's own draft
  if (d && d.stale) return h("div", { class: "band" }, h("p", { text: t("Your facts changed after this was written. Write it again to use them.") }),  // the facts moved on
    agentOn() ? h("button", { class: "btn small", onclick: () => writeResume(ed.id), text: t("Write it again") }) : null);
  if (own || !agentOn()) return error;                                              // written for this edition, or no agent to write it
  if (!d) return error;                                                             // the general edition from the facts as they are: nothing to say over the page (the head's key writes it)
  const words = t("This is your general resume. Write it for this job, from the same facts.");
  return h("div", { class: "band offer" }, h("p", { text: words }), sentLine(true, job() ? t("Writing sends your facts and the posting to the agent.") : t("Writing sends your facts to the agent.")),  // what it does; what it sends on hover
    h("button", { class: "btn small", onclick: () => writeResume(ed.id), text: t("Write the resume") }), error);
}
function writeKey() {                                                              // the agent writes the resume: a key in the head when no band says so over the page
  const ed = edition(), m = UI.doc === "resume" || UI.doc === "deck" ? resumeModel() : null;   // the edition and its model; the deck's slides take the resume's sentences, so its tab has the same key
  if (!ed || !m || m.draft || !agentOn() || (job() && job().locked) || (ed.own || []).includes(docLang()) || ownFileIn(ed)) return null;   // a draft exists, or nothing to write
  const busy = task("write:" + ed.id).state === "running";                         // writing now
  return h("button", { class: "btn agent", disabled: busy || null, title: job() ? t("Writing sends your facts and the posting to the agent.") : t("Writing sends your facts to the agent."),
    onclick: () => writeResume(ed.id) }, icon("agent"), busy ? t("Writing the resume from your evidence")
      : (m.counts || {}).sentences ? t("Rewrite with the agent") : t("Write the resume"));   // a resume on the page already (your profile's own words): the agent writes it again
}
function writeResume(jid) { return act("/api/v1/jobs/write", { job: jid, lang: docLang() }); }  // the task starts; the band follows it
async function lockJob(jid) {                                                       // keep exact copies of what was sent
  const r = await act("/api/v1/jobs/lock", { job: jid, lang: docLang() });          // refused when a sentence lacks evidence
  if (r && r.locked) toast(t("Locked. Exact copies of what you submitted are kept with this job."), null, "done");
}
async function exportPdfs() {                                                       // copies on the Desktop
  const ed = edition(); if (!ed) return;                                            // the job in view, else the general edition
  const r = await act("/api/v1/jobs/export", { job: ed.id, lang: docLang() });      // refused when a sentence lacks evidence
  if (r && r.exported) toast([r.exported.length ? t("On your Desktop: {names}", { names: r.exported.join(", ") }) : t("Make the PDFs first."),   // what went
    ...(r.refused || []).map((x) => refusedWords(x.why))].filter(Boolean).join(" "));   // and a Word or PowerPoint file that stayed home, with why
}
let lastHit = { sid: "", at: 0 };                                                   // the last click on a sentence: the first click redraws the canvas, so a browser's own double click would lose its target
function editInPlace(sid, tries = 12) {                                             // type over a sentence where it stands on the page
  const rec = sentenceOf(sid), el = document.querySelector(`#canvas .s[data-sid="${CSS.escape(sid)}"]`);  // its record and its words on the page
  if (!rec || sid.startsWith("cover.")) return;                                     // only the resume's sentences can be changed
  if (sentAway()) { toast(t("This application was submitted and locked."), null, "warn"); return; }   // its sentences stay as they went
  if (rec.locked) { toast(errorInfo("locked").msg, null, "warn"); return; }                       // said plainly
  if (!el) { if (tries) setTimeout(() => editInPlace(sid, tries - 1), 50); return; }  // the pages are still being laid out
  UI.inplace = sid;                                                                 // the canvas is not redrawn under the caret
  document.querySelectorAll(`#canvas .s[data-sid="${CSS.escape(sid)}"]`).forEach((x) => { if (x !== el) x.hidden = true; });   // a sentence broken over two pages is typed whole in its first piece
  document.querySelectorAll(`#canvas .cite.over[data-for="${CSS.escape(sid)}"]`).forEach((x) => { x.hidden = true; });   // and its numbers, which stood after its old words, step aside
  el.textContent = rec.text;                                                        // the words with their == marks, as the inspector's form has them
  el.setAttribute("contenteditable", "plaintext-only");                             // plain words only, nothing pasted with its own style
  el.classList.add("typing");                                                       // it looks like a field
  el.focus();                                                                       // the keyboard goes here
  const range = document.createRange(); range.selectNodeContents(el);               // every word of it
  const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);    // selected, ready to be typed over
  toast(t("Typing over the sentence: Enter or a click elsewhere saves, Esc puts it back."));   // the keys of a field with no keys of its own, said once
  const finish = async (save) => {                                                  // Enter or leaving the sentence saves, Esc puts it back
    if (UI.inplace !== sid) return;                                                 // already finished
    UI.inplace = null;                                                              // the canvas may be redrawn again
    const text = el.textContent.trim();                                             // the new words
    el.removeAttribute("contenteditable");                                          // a sentence again
    UI.sel = sid;                                                                   // saveSentence writes the selected sentence
    if (save && text && text !== rec.text) await saveSentence(text);                // checked against the evidence there
    $("canvas")._key = null; render();                                              // drawn from the model again
  };
  el.addEventListener("keydown", (e) => {                                           // the keys that end the typing
    e.stopPropagation();                                                            // the page's own keys wait
    if (e.isComposing) return;                                                      // a Korean syllable being put together: its Enter ends the syllable, not the edit
    if (e.key === "Enter") { e.preventDefault(); el.blur(); }                       // saved through blur, once
    if (e.key === "Escape") { e.preventDefault(); finish(false).then(() => {}); }   // put back
  });
  el.addEventListener("blur", () => finish(true), { once: true });                  // leaving it saves
}
document.addEventListener("click", (e) => {                                         // a sentence on the canvas, or its source numbers beside it
  const s = e.target.closest && e.target.closest(".s[data-sid], .cite[data-for]");  // the sentence clicked
  if (!s || s.isContentEditable) return;                                            // elsewhere, or moving the caret inside the sentence being typed
  e.preventDefault();                                                               // no text selection jump
  const sid = s.dataset.sid || s.dataset.for, again = lastHit.sid === sid && Date.now() - lastHit.at < 450;  // the second click of a double click
  lastHit = { sid, at: Date.now() };                                                // remembered
  select(sid);                                                                      // its evidence
  if (again) editInPlace(sid);                                                      // and the words, where they stand
});
document.addEventListener("keydown", (e) => {                                       // Enter or Space on a sentence
  const s = e.target.closest && e.target.closest(".s[data-sid]");                   // the focused sentence
  if (!s || s.isContentEditable) return;                                            // elsewhere, or typing in it
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(s.dataset.sid); }  // as a click
  if (e.key === "F2") { e.preventDefault(); select(s.dataset.sid); editInPlace(s.dataset.sid); }  // as a double click
});
