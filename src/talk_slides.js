// The talk: a 16:9 deck for a presentation interview, made of the person's own portfolio slides and slides drawn for the talk.
//   node src/talk_slides.js --pages <profile.json> <job.json> <page name>    -> the portfolio's slides as JSON on stdout
//   node src/talk_slides.js <talk.json> <profile.json> <job.json> <page name> -> output/<page name>.html (src/interview/talk.py prints it)
// The portfolio is drawn as the job's edition draws it: from the person's own deck source when the build names one
// (OFFEROWL_DECK_SOURCE, a folder with build.js and portfolio/deck.js), else from the profile (src/deck_slides.js). Its slides are
// caught before they are written, so a talk shows the portfolio's pages exactly as the portfolio prints them. The talk's own
// slides are drawn with the same frame (Deck, h) and drawing parts (draw.js), so both kinds share one look.
// talk.json is written by src/interview/talk.py: every word, page number and evidence is settled there, and this file only draws.
"use strict";
const fs = require("fs");                                                    // files
const path = require("path");                                                // paths
const ROOT = path.join(__dirname, "..");                                     // the engine's folder, where every output goes

// ───────── the frame: the person's deck source, else the engine's ─────────
const SRC = process.env.OFFEROWL_DECK_SOURCE ? path.join(ROOT, process.env.OFFEROWL_DECK_SOURCE) : null;   // a staged source, repository-relative
const OWN = !!SRC && ["deck.js", "draw.js", "structure.js"].every(f => fs.existsSync(path.join(SRC, "portfolio", f))) && fs.existsSync(path.join(SRC, "build.js"));   // its frame is usable
const FRAME = OWN ? path.join(SRC, "portfolio") : path.join(__dirname, "portfolio");   // where Deck, h and the drawing parts come from
const { Deck, h } = require(path.join(FRAME, "deck"));                       // the slide frame and HTML helpers
const { C, P, D, Svg, svgIcon, outline } = require(path.join(FRAME, "draw"));   // colours, primitives, boxes, the SVG canvas, icons, glyph outlines
const STR = OWN ? require(path.join(SRC, "portfolio", "structure")) : require("./deck_structure");   // the side rail of either frame
const esc = h.esc, rich = h.rich;                                            // escaping, and **bold** / ==highlight== markup

// The few words the frame needs in each language: the rest comes written in talk.json
const WORDS = {
  ko: { chapter: "CHAPTER", contents: "CONTENTS", pages: n => `${n} PAGES`, overview: "개요", page: n => `${n}쪽`, about: "ABOUT ME",
        minutes: m => `약 ${m}분`, presentation: "PRESENTATION", qa: "Q&A", mine: "제 몫", learned: "익힌 것", evidence: "근거",
        output: "결과물", metric: "지표", question: "풀어야 할 질문", step: "단계" },
  en: { chapter: "CHAPTER", contents: "CONTENTS", pages: n => `${n} PAGES`, overview: "Overview", page: n => `p.${n}`, about: "ABOUT ME",
        minutes: m => `about ${m} min`, presentation: "PRESENTATION", qa: "Q&A", mine: "My part", learned: "Learned", evidence: "Evidence",
        output: "Output", metric: "Measure", question: "The open question", step: "Step" },
};
const pagesText = (list, lang) => {                                          // "3, 5쪽" or "p.3, 5": pages in order, once each
  const ps = [...new Set((list || []).filter(n => Number.isInteger(n) && n > 0))].sort((a, b) => a - b);   // whole page numbers only
  return ps.length ? (lang === "en" ? `p.${ps.join(", ")}` : `${ps.join(", ")}쪽`) : "";   // nothing when no page backs it
};

// ───────── the portfolio, caught before it is written ─────────
function portfolio(profile, jobFile, page) {
  let got = null;                                                            // the deck the portfolio builds
  const render0 = Deck.prototype.render;                                     // the frame's own writer
  Deck.prototype.render = function () { got = this; return this.slides.length; };   // keep the slides, write nothing
  const argv = process.argv, log = console.log;                             // the person's build.js reads its arguments from here; its words go aside
  console.log = (...a) => console.error(...a);                               // a builder's own lines never mix into the JSON this file prints
  try {
    if (OWN) {                                                               // the person's own slides
      process.argv = [argv[0], path.join(SRC, "build.js"), profile, jobFile, page];   // as Offerowl runs it
      require(path.join(SRC, "build.js"));                                   // it builds and calls render, which is caught
    } else {                                                                 // the slides drawn from the profile
      const cfg = jobFile && fs.existsSync(jobFile) ? JSON.parse(fs.readFileSync(jobFile, "utf-8")) : {};   // the edition's settings
      require("./deck_slides").build(profile, cfg);                          // builds and calls render, which is caught
    }
  } finally {
    process.argv = argv;                                                     // as it was
    console.log = log;                                                       // this file's own lines go out again
    Deck.prototype.render = render0;                                         // the talk is written for real
  }
  if (!got || !got.slides.length) throw new Error("the portfolio drew no slides");   // nothing to show
  return got;                                                                // its slides, its title, its colour set
}

const plain = s => String(s || "").replace(/<[^>]+>/g, " ").replace(/&nbsp;| /g, " ").replace(/&lt;/g, "<")
  .replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();   // a slide's words without markup; &amp; last, so "&amp;lt;" reads "&lt;", not "<"

// What each portfolio slide is, for the planner: its number, kind, title, tagline, period, role and context, and its project
function slideInfo(s, i) {
  const x = s.html;                                                          // the slide's HTML
  const t = x.match(/<h1>([\s\S]*?)(?:<span class="t2">([\s\S]*?)<\/span>)?<\/h1>/);   // the big title and its grey tagline
  const pm = (x.match(/<div class="pmeta">([\s\S]*?)<\/div>/) || [])[1] || "";   // the role, context and stack line of a project slide
  const spans = [...pm.matchAll(/<span><b>([^<]*)<\/b>([\s\S]*?)<\/span>/g)].map(m => [plain(m[1]), plain(m[2])]);   // its labelled parts
  const period = plain((x.match(/<span class="en">([\s\S]*?)<\/span>/) || [])[1] || "");   // the eyebrow's right end: the period
  const kind = s.meta.kind || (pm ? "project" : /class="cl"/.test(x) ? "chapter" : "other");   // a slide without a kind that has a meta line is a project
  return { n: i + 1, kind, title: plain(t ? t[1] : ""), tag: plain(t && t[2] ? t[2] : ""), period, meta: spans, project: s.meta.project || null,
           text: plain(x).slice(0, 2000) };                                 // its words, for matching a project to its page
}

// The profile as the resume and the deck read it (src/profile_loader.js), cut to what the talk's planner uses
function view(profile, lang, cfg) {
  const G = require("./profile_loader");                                     // the one loader of the documents
  const p = G.load(profile, lang, cfg);                                      // pairs picked, periods and tenures worked out
  const pick = (o, keys) => Object.fromEntries(keys.filter(k => o && o[k] != null).map(k => [k, o[k]]));   // a few fields of an object
  return {
    lang, person: pick(p.person || {}, ["name", "name_en", "name_en_ko", "tagline", "email", "phone", "location", "links", "linkedin", "github", "website"]),
    summary: pick(p.summary || {}, ["headline", "intro", "cards", "highlights", "stats", "focus", "glance"]),
    competencies: (p.competencies || []).map(c => Array.isArray(c) ? { name: c[0], text: c[1] } : pick(c, ["name", "text", "evidence"])),
    roles: (p.roles || []).map(r => ({ ...pick(r, ["key", "org", "short", "title", "titleLong", "dept", "place", "period", "start", "end", "months", "tenure", "logoId", "desc"]),
      projects: (r.projects || []).map(x => pick(x, ["id", "title", "short", "period", "summary", "tagline", "role", "context", "deck", "resume"])) })),
    education: (p.education || []).map(e => pick(e, ["school", "sub", "major", "degree", "period", "start", "end", "logoId"])),
    skills: (p.skills || []).map(s => pick(s, ["category", "items"])), motivation: p.motivation || "", total: p.total || "", totalMonths: p.totalMonths || 0,
  };
}

// ───────── the talk's own slides ─────────
const T = { lang: "ko", W: WORDS.ko, theme: null };                          // set from talk.json before drawing

// The big pale word behind the cover and the end (the portfolio's last page does the same with its glyph outlines)
const watermark = (word, fill = "#ffffff", op = 0.06) => {
  if (!word) return "";                                                      // none asked for
  const wm = outline(word, 300, true), bb = wm.bb;                           // the word as glyph paths, and their box
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" ` +
    `viewBox="${bb.x1.toFixed(1)} ${bb.y1.toFixed(1)} ${(bb.x2 - bb.x1).toFixed(1)} ${(bb.y2 - bb.y1).toFixed(1)}"><path d="${wm.d}" fill="${fill}" fill-opacity="${op}"/></svg>`);
};
const icon = (name, size = 16, color = C.navy, sw = 2) => svgIcon(name || "circle-dot", size, color, sw);   // a lucide icon by name
const tile = (file, hpx = 26) => file && fs.existsSync(file) ? `<img class="tk-tile" src="file://${esc(file)}" alt="" style="height:${hpx}px">`   // a logo tile the portfolio drew
  : `<span class="tk-tile tk-mono" style="height:${hpx}px;width:${hpx}px"></span>`;   // else an empty tile, so the rows stay aligned
const chips = list => (list || []).length ? `<span class="tk-chips">${list.map(c => `<span class="tk-chip">${icon(c.icon || "circle-dot", 14)}` +
  `<span>${c.value ? `<b>${esc(c.value)}</b> ` : ""}${esc(c.text || "")}</span></span>`).join("")}</span>` : "";   // the eyebrow's proof chips

// A content slide's head: the label and period line with chips, the big title with its grey subtitle, and the role and context line
function head(s) {
  const eb = `<div class="eyebrow"><span>${esc(s.label || "")}</span>${s.right ? `<span class="en">${esc(s.right)}</span>` : ""}${chips(s.chips)}</div>`;   // the eyebrow
  const ttl = `<div class="ttl"><h1>${rich(s.title || "")}${s.sub ? `<span class="t2">${rich(s.sub)}</span>` : ""}</h1></div>`;   // the title row
  const meta = (s.meta || []).filter(m => m && m[1]).map(([k, v]) => `<span><b>${esc(k)}</b>${esc(v)}</span>`).join("");   // role, context
  return `<div class="sec tk-head" data-en="${esc(s.label || "")}">${eb}${ttl}${meta ? `<div class="pmeta">${meta}</div>` : ""}</div>` +
    (s.lede ? `<p class="lede">${rich(s.lede)}</p>` : "");                   // and the lede under it, with its one highlight
}

// The cover: a dark poster with the name, the role line, the headline and the four facts of the day
function cover(s) {
  const cells = (s.items || []).map(([k, v, ic]) => `<div class="cc"><span class="ic">${icon(ic, 19, "#ffffff")}</span><b>${esc(k)}</b><span class="v">${esc(v)}</span></div>`).join("");
  return `<div class="end" style="background-image: url('${watermark(s.mark)}')"><div class="top"><span style="text-transform:none">${esc(s.top || "")}</span>` +
    `<span class="r">${esc(T.W.presentation)}</span></div><div class="mid"><h1>${esc(s.name || "")}${s.name2 ? `<small>${esc(s.name2)}</small>` : ""}</h1>` +
    `<div class="tag">${esc(s.tag || "")}</div>${s.headline ? `<div class="lead">${rich(s.headline)}</div>` : ""}</div><div class="bot">${cells}</div></div>`;
}

// The agenda: a time bar with one cell per part, a row per part with its slides and pages, and the talk's messages
function agenda(s, talk) {
  const parts = talk.parts || [], total = parts.reduce((a, p) => a + (p.minutes || 0), 0) || 1;   // the parts and their minutes
  const W = 1180, bar = new Svg(W, 58);                                       // the bar's canvas
  let x = 0;                                                                 // where the next cell starts
  parts.forEach(p => {                                                       // one cell per part, as wide as its share of the time
    const w = W * (p.minutes || 0) / total;                                  // the cell's width
    bar.add(P.rect(x + 1, 6, w - 2, 30, { fill: T.theme ? T.theme.frame : C.navy, r: 5 }));   // the cell
    bar.add(P.text(x + w / 2, 21, `${p.no} ${p.short || p.title}`, { size: 11, bold: true, fill: C.white, anchor: "middle", maxw: w - 12 }));   // its number and name
    bar.add(P.text(x + w / 2, 50, T.W.minutes(p.minutes), { size: 10, fill: C.grey, anchor: "middle" }));   // its minutes under it
    x += w;                                                                  // the next cell
  });
  const rows = parts.map(p => `<div class="tk-arow"><span class="tk-ano">${esc(p.no)}</span><div class="tk-atx"><b>${esc(p.title)}</b>` +
    (p.what ? `<span>${rich(p.what)}</span>` : "") +                          // what the part covers
    `<ol>${(p.slides || []).map(([n, t]) => `<li><i>${n}</i>${esc(t)}</li>`).join("")}</ol>` +   // its slides with their pages
    ((p.slides || []).length <= 6 && p.core ? `<div class="tk-core">${icon(p.icon, 16)}<span>${rich(p.core)}</span></div>` : "") + `</div></div>`).join("");   // its core line when the list is short
  const msgs = (talk.messages || []).slice(0, 3);                            // up to three messages
  return head({ label: "AGENDA", title: s.title, lede: s.lede }) + h.fig(bar.toString(), { bare: true, natural: true }) +
    `<div class="tk-agenda${parts.length > 4 ? " tk-agenda3" : ""}">${rows}</div>` +
    (msgs.length ? `<div class="tk-msg" style="grid-template-columns: auto repeat(${msgs.length}, 1fr)"><b class="tk-msgh">${esc(s.messagesTitle || "")}</b>` +
      msgs.map((m, i) => `<div class="tk-m"><span class="tk-mn">${i + 1}</span><div><b>${esc(m.title)}</b><span>${rich(m.text || "")}` +
        `${(m.pages || []).length ? ` (${pagesText(m.pages, T.lang)})` : ""}</span></div></div>`).join("") + `</div>` : "");
}

// A chapter: the portfolio's chapter divider (a dark panel with the number, name, meta and lead; the part's pages on the right)
function chapter(s, talk) {
  const p = (talk.parts || [])[s.part] || {};                                // the part it opens
  const rows = s.rows || [];                                                 // the part's slides
  const dense = rows.length > 6;                                             // a long part lists one line per slide
  return `<div class="cl"><div class="no">${esc(p.no || "")}</div><div class="kind">${T.W.chapter}</div><h1>${esc(p.title || "").split("\n").join("<br>")}</h1>` +
    `<div class="enm">${esc(p.en || "")}</div><div class="meta">${(s.meta || []).map(([k, v]) => `<b>${esc(k)}</b><span>${esc(v)}</span>`).join("")}</div>` +
    `<div class="lead">${rich(s.lead || "")}</div></div>` +
    `<div class="cr"><div class="eyebrow"><span class="no">${esc(p.no || "")}</span><span>${T.W.contents}</span><span class="en">${T.W.pages(rows.length)}</span></div>` +
    `<div class="plist${dense ? " dense" : " rich"}">${rows.map((r, i) => `<div class="p"><span class="num">${String(i + 1).padStart(2, "0")}</span>` +
      `<span class="t">${esc(r.title)}${r.tag ? `<span class="tg">${esc(r.tag)}</span>` : ""}${r.note && !dense ? `<span class="rc"><b>${esc(s.noteLabel || "")}</b>${esc(r.note)}</span>` : ""}</span>` +
      `<span class="per">${esc(r.period || "")}</span><span class="pg">${r.page || ""}</span></div>`).join("")}</div>` +
    ((s.keys || []).length ? `<div class="sp"></div><div class="skills compact"><div class="lab">${esc(s.keyLabel || "")}</div>` +
      s.keys.map(([k, v]) => `<div class="r"><b>${esc(k)}</b><span class="names">${esc(v)}</span></div>`).join("") + `</div>` : "") + `</div>`;
}

// About me: a 2 x 2 grid, so its rows line up across the columns: the career beside the overview, the education beside the skills.
// Every row of the career and the education has the same columns (logo, name, role or major, period), so their edges line up too.
function about(s) {
  const career = s.career || [], maxM = Math.max(1, ...career.map(c => c.months || 0));   // the rows, and the longest tenure for the bars
  const sh = (ic, t, r) => `<div class="tk-sh">${icon(ic, 16)}<b>${esc(t || "")}</b>${r ? `<span>${esc(r)}</span>` : ""}</div>`;   // a section's head line
  const careerHtml = career.length ? sh("briefcase-business", s.careerTitle, s.total) + `<div class="tk-rows">${career.map(c => `<div class="tk-row">${tile(c.tile)}` +
    `<div class="tk-c1"><b>${esc(c.org)}</b><span>${esc(c.place || "")}</span></div><div class="tk-c2"><b>${esc(c.role || "")}</b><span>${esc(c.dept || "")}</span></div>` +
    `<div class="tk-c3"><span>${esc(c.period || "")}</span><i style="width:${Math.round(100 * (c.months || 0) / maxM)}%"></i><b>${esc(c.tenure || "")}</b></div></div>`).join("")}</div>` : "";
  const eduHtml = (s.education || []).length ? sh("graduation-cap", s.educationTitle) + `<div class="tk-rows">${s.education.map(e => `<div class="tk-row">${tile(e.tile)}` +
    `<div class="tk-c1"><b>${esc(e.school)}</b></div><div class="tk-c2"><b>${esc(e.major || "")}</b><span>${esc(e.degree || "")}</span></div>` +
    `<div class="tk-c3"><span>${esc(e.period || "")}</span></div></div>`).join("")}</div>` : "";
  const cardsHtml = (s.cards || []).length ? sh("layers", s.overviewTitle) + `<div class="tk-ov">${s.cards.map(c => `<div class="tk-ovb"><div class="tk-ovh">${icon(c.icon, 16)}<b>${esc(c.title)}</b></div>` +
    `<p>${rich(c.text)}</p></div>`).join("")}</div>` : "";
  const skillHtml = (s.skills || []).length ? sh("wrench", s.skillsTitle) + `<div class="tk-rows">${s.skills.map(([k, v]) => `<div class="tk-srow"><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join("")}</div>` : "";
  return head({ label: T.W.about, title: s.title, sub: s.sub, lede: s.lede }) +
    `<div class="tk-about"><div class="tk-cell">${careerHtml}</div><div class="tk-cell">${cardsHtml}</div><div class="tk-cell">${eduHtml}</div><div class="tk-cell">${skillHtml}</div></div>`;
}

// Strengths: a pillar per strength, each with what it is and the work that shows it, with the talk's pages
function strengths(s) {
  const pillar = p => `<div class="tk-pillar"><div class="tk-phd">${icon(p.icon, 18, C.white)}<div><b>${esc(p.title)}</b>${p.sub ? `<span>${esc(p.sub)}</span>` : ""}</div></div>` +
    `<p class="tk-psk">${rich(p.text || "")}</p><ul>${(p.items || []).map(it => `<li><b>${rich(it.title)}</b>${rich(it.text || "")}` +
      `${(it.pages || []).length ? `<span class="tk-pp">${pagesText(it.pages, T.lang)}</span>` : ""}</li>`).join("")}</ul></div>`;   // one item per piece of work
  const n = Math.max(1, (s.pillars || []).length);                           // two to four pillars
  return head({ label: s.label || "STRENGTHS", title: s.title, sub: s.sub, lede: s.lede }) +
    `<div class="tk-pillars" style="grid-template-columns: repeat(${n}, 1fr)">${(s.pillars || []).map(pillar).join("")}</div>` +
    (s.foot ? `<div class="tk-pfoot"><b>${esc(s.foot[0])}</b>${rich(s.foot[1])}</div>` : "");
}

// Lessons: numbered principles, each with its story, what was learned and where it happened
function lessons(s) {
  const items = s.items || [];                                               // up to six
  return head({ label: s.label || "LESSONS", title: s.title, sub: s.sub, lede: s.lede }) +
    `<div class="tk-lessons${items.length <= 4 ? " tk-l4" : ""}">${items.map((l, i) => `<div class="tk-les"><span class="tk-lno">${i + 1}</span><div>` +
      `<h3>${icon(l.icon, 17)}${esc(l.title)}</h3><p>${rich(l.text || "")}</p>` +
      (l.learned ? `<span class="tk-tech"><b>${T.W.learned}</b>${esc(l.learned)}</span>` : "") +
      (l.source ? `<span class="tk-lsrc">${esc(l.source)}${(l.pages || []).length ? ` (${pagesText(l.pages, T.lang)})` : ""}</span>` : "") + `</div></div>`).join("")}</div>`;
}

// A figure of two positions that meet one open question: each side's items in its own panel, the question under both
function sidesFigure(f) {
  const W = 760, sides = (f.sides || []).slice(0, 2), rows = Math.max(1, ...sides.map(x => (x.items || []).length));   // two panels, as tall as the longer list
  const gap = 12, top = 36, room = 520 - top - 6 - (f.question ? 92 : 12);   // the figure is drawn for the deck's main frame (760 x 570)
  const bh = Math.round(Math.max(44, Math.min(120, (room - gap * (rows - 1)) / rows)));   // boxes grow when there are few, so the panels fill the frame
  const ph = top + rows * (bh + gap) + 6, H = ph + (f.question ? 92 : 12);   // the panels' height and the canvas's
  const s = new Svg(W, H), pw = (W - 30) / 2;                                 // the canvas, a panel's width
  const looks = [{ fill: C.t4, stroke: C.t2, color: C.teal }, { fill: C.a4, stroke: C.a2, color: C.amber }];   // the first side teal, the second amber
  sides.forEach((x, i) => {                                                  // each side
    const px = i * (pw + 30), lk = looks[i];                                 // its left edge and look
    s.add(D.group(px, 0, pw, ph, x.title || "", { fill: C.key, color: lk.color, mark: i + 1 }));   // its panel with its name and badge
    (x.items || []).forEach((it, k) => s.add(D.box(px + 14, top + k * (bh + gap), pw - 28, bh,   // one box per item
      { title: it.title || it, sub: it.sub || "", size: 12.5, subSize: 10.5, fill: C.white, stroke: lk.stroke, color: lk.color, icon: it.icon || undefined })));
  });
  if (sides.length === 2) {                                                  // the two positions face each other
    s.add(P.circle(W / 2, ph / 2, 13, { fill: C.white, stroke: C.rule }));   // a small round mark between the panels
    s.add(P.text(W / 2, ph / 2, "VS", { size: 9.5, bold: true, fill: C.grey, anchor: "middle" }));
  }
  if (f.question) {                                                          // the question both positions leave open
    s.add(D.conn([[W / 2, ph + 4], [W / 2, ph + 24]]));                      // down to it
    s.add(D.box(60, ph + 26, W - 120, 52, { title: f.question, sub: T.W.question, size: 12, subSize: 9.5, fill: C.b5 || C.band, stroke: C.navy, color: C.navy, mark: 3 }));
  }
  return s.toString();
}

// A figure of steps in order: a numbered column of boxes joined by a thread, the last one the outcome. A column fills the figure's
// frame beside the cards, where a row of boxes would leave the frame mostly empty.
function stepsFigure(f) {
  const steps = (f.steps || []).slice(0, 6), W = 760, gap = 20;            // up to six steps, each a row of the column
  const rh = Math.round(Math.max(60, Math.min(130, (520 - gap * (steps.length - 1)) / Math.max(1, steps.length))));   // rows grow when there are few, so the column fills the frame
  const H = steps.length * rh + (steps.length - 1) * gap + (f.note ? 34 : 4), s = new Svg(W, H);   // the canvas, as tall as the steps
  steps.forEach((st, i) => {                                                 // each step
    const y = i * (rh + gap), last = i === steps.length - 1;                 // its top, and whether it is the outcome
    if (!last) s.add(P.line(24, y + rh / 2 + 17, 24, y + rh + gap + rh / 2 - 17, { stroke: C.rule, sw: 2 }));   // the thread to the next step
    s.add(P.circle(24, y + rh / 2, 16, { fill: last ? C.teal : C.navy, stroke: "none" }));   // its number's disc
    s.add(P.text(24, y + rh / 2, String(i + 1), { size: 13, bold: true, fill: C.white, anchor: "middle" }));   // its number
    s.add(D.box(56, y, W - 56, rh, { title: st.title || "", sub: st.sub || "", size: 12.5, subSize: 10.5, fill: last ? C.t4 : C.white,
                                     stroke: last ? C.t2 : C.rule, color: C.navy, align: "left", pad: 16 }));   // what was done
  });
  if (f.note) s.add(P.text(56, H - 14, f.note, { size: 10.5, fill: C.grey, maxw: W - 56 }));   // the line under the steps
  return s.toString();
}

// The story's three slides share one look: the figure on the left with numbered cards on the right (the portfolio's split). A slide
// without a figure lays its cards over the whole width, as many columns as cards (two rows for four), each as tall as the room.
function story(s) {
  const fig = s.figure && s.figure.type === "sides" ? sidesFigure(s.figure) : s.figure && s.figure.type === "steps" ? stepsFigure(s.figure) : "";   // its figure, if any
  const list = s.cards || [], cards = list.map((c, i) => h.card(c.title, c.text, { no: c.no === false ? 0 : (c.no || i + 1) })).join("");   // numbered cards
  const scope = s.scope ? `<div class="tk-scope">${icon("user-check", 16)}<span><b>${esc(s.scope[0])}</b>${rich(s.scope[1])}</span></div>` : "";   // my part, when said
  const cols = list.length === 4 ? 2 : Math.max(1, Math.min(3, list.length));   // three in a row, four as two by two
  const label = s.label || { problem: "PROBLEM", approach: "APPROACH", result: "RESULT", story: "CHALLENGE" }[s.kind] || "";   // its eyebrow word
  return head({ label, right: s.right, chips: s.chips, title: s.title, sub: s.sub, meta: s.meta, lede: s.lede }) +
    (fig ? h.grid("split-64 tk-bigr", "", h.fig(fig, { cap: s.caption || "" }), `<div class="stack">${cards}${scope}</div>`)
      : `<div class="body tk-cards tk-fill" style="grid-template-columns: repeat(${cols}, 1fr)">${cards}</div>${scope}`);
}

// Why this job: the person's reasons (the lede), three cards (this job, the company now, what the person wants there) and the line
// the person wants remembered. A talk, never the posting's lines against the record.
function why(s) {
  const n = Math.min(3, Math.max(1, (s.cards || []).length));
  return head({ label: s.label || "WHY", title: s.title, sub: s.sub, lede: s.lede }) +
    ((s.cards || []).length ? `<div class="body tk-cards tk-fill" style="grid-template-columns: repeat(${n}, 1fr)">${s.cards.map((c, i) => h.card(c.title, c.text, { no: i + 1 })).join("")}</div>` : "") +
    (s.foot ? `<div class="tk-pfoot"><b>${esc(s.foot[0])}</b>${rich(s.foot[1])}</div>` : "");
}

// The plan: a bar of phases, then a column per phase with what to do, its output and measure, and a box of first steps
function plan(s) {
  const phases = (s.phases || []).slice(0, 3), W = 1180, F = new Svg(W, 88), n = Math.max(1, phases.length), cw = (W - 16 * (n - 1)) / n;   // the bar's canvas
  const fills = [C.b4 || C.band, C.b2 || C.blue, T.theme ? T.theme.frame : C.navy];   // lighter to darker, the last in the frame's colour
  phases.forEach((p, i) => {                                                 // one arrow cell per phase
    const x = i * (cw + 16), tip = 22, last = i === n - 1;                   // its left edge, the arrow's tip
    const pts = last ? [[x, 4], [x + cw, 4], [x + cw, 58], [x, 58]].concat(i ? [[x + tip, 31]] : []) :
      [[x, 4], [x + cw - tip, 4], [x + cw, 31], [x + cw - tip, 58], [x, 58]].concat(i ? [[x + tip, 31]] : []);   // an arrow, notched after the first
    const fill = fills[n === 1 ? 2 : Math.round(i * 2 / (n - 1))];          // its shade
    F.add(P.poly(pts, { fill }));
    F.add(P.text(x + (i ? tip + 14 : 16), 31, `${p.when}  ${p.title}`, { size: 14, bold: true, fill: fill === fills[0] ? C.navy : C.white, maxw: cw - 40 }));   // when and what
    if (p.basis) F.add(P.text(x + 16, 76, p.basis, { size: 11.5, fill: C.grey, maxw: cw - 20 }));   // what it judges by
  });
  const col = p => `<div class="tk-phase"><div class="tk-phh">${icon(p.icon || "flag", 18)}<b>${esc(p.head || p.title)}</b></div><ul>${(p.items || []).map(x => `<li>${rich(x)}</li>`).join("")}</ul>` +
    `<div class="tk-pk">${p.output ? `<div><b>${T.W.output}</b><span>${rich(p.output)}</span></div>` : ""}${p.metric ? `<div><b>${T.W.metric}</b><span>${rich(p.metric)}</span></div>` : ""}</div>` +
    ((p.box && (p.box.items || []).length) ? `<div class="tk-pbox"><b>${esc(p.box.title || "")}</b><ol>${p.box.items.map(x => `<li>${rich(x)}</li>`).join("")}</ol></div>` : "") + `</div>`;
  return head({ label: s.label || "PLAN", title: s.title, sub: s.sub, lede: s.lede }) + h.fig(F.toString(), { bare: true, natural: true }) +
    `<div class="tk-phases" style="grid-template-columns: repeat(${n}, 1fr)">${phases.map(col).join("")}</div>` +
    (s.foot ? `<div class="tk-pfoot"><b>${esc(s.foot[0])}</b>${rich(s.foot[1])}</div>` : "");
}

// A topic of the person's own: its points as cards
function points(s) {
  const n = Math.min(3, Math.max(1, (s.cards || []).length));               // up to three columns
  return head({ label: s.label || "TOPIC", title: s.title, sub: s.sub, lede: s.lede }) +
    `<div class="body tk-cards tk-fill" style="grid-template-columns: repeat(${n}, 1fr)">${(s.cards || []).map((c, i) => h.card(c.title, c.text, { no: i + 1 })).join("")}</div>` +
    (s.foot ? `<div class="tk-pfoot"><b>${esc(s.foot[0])}</b>${rich(s.foot[1])}</div>` : "");
}

// The end: the cover's poster with thanks, the messages again and the contacts
function end(s, talk) {
  const cells = (s.contacts || []).map(([k, v, link]) => `<div class="cc" style="grid-template-columns:auto 1fr"><b>${esc(k)}</b>` +
    (link ? `<a href="${esc(link)}">${esc(v)}</a>` : `<span class="v">${esc(v)}</span>`) + `</div>`).join("");   // the contacts, links clickable
  const msgs = (talk.messages || []).slice(0, 3);                            // the talk's messages, said once more
  return `<div class="end" style="background-image: url('${watermark(T.W.qa)}')"><div class="top"><span>${esc(s.top || "")}</span><span class="r">${esc(s.right || "")}</span></div>` +
    `<div class="mid"><h1>${esc(s.title || "")}</h1><div class="tag">${esc(s.tag || "")}</div>` +
    (msgs.length ? `<div class="tk-endm">${msgs.map((m, i) => `<span><i>${i + 1}</i>${esc(m.title)}</span>`).join("")}</div>` : "") + `</div>` +
    `<div class="bot">${cells}</div></div>`;
}

const DRAW = { cover, agenda, chapter, about, strengths, lessons, problem: story, approach: story, result: story, story, why, plan, points, end };   // every kind
const CLS = { cover: "eod", end: "eod", chapter: "chapter" };               // the frame's slide classes for the posters and the dividers

// A portfolio page as the talk shows it: its own chapter number and project count leave the head (the talk numbers its parts)
function pageOf(pf, n, swaps) {
  const s = pf.slides[n - 1];                                                // the portfolio's slide n
  if (!s) throw new Error(`the portfolio has no page ${n}`);                 // a plan made for another portfolio
  let html = s.html.replace(/<span class="no">[^<]*<\/span>/, "").replace(/<span class="pj">[^<]*<\/span>/, "");   // no chapter number, no 'PROJECT n / m'
  for (const [a, b] of swaps || []) html = html.split(a).join(b);            // the person's own word changes for a talk
  return { meta: { ...s.meta, rail: "", footnote: "" }, html };              // the talk's rail and foot replace the portfolio's
}

// The talk's look over the frame's: tk- classes, so nothing of the portfolio's own parts is touched
const CSS = `
.tk-head .eyebrow { flex-wrap: nowrap; } .tk-chips { display: inline-flex; gap: 6px; margin-left: auto; }
.tk-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--band, #EEF3F9); border-radius: 4px; font-size: 12px; color: var(--ink2, #222); letter-spacing: 0; text-transform: none; }
.tk-chip b { color: var(--navy); font-size: 14px; } .tk-chip svg { flex: none; }
.tk-agenda { display: grid; grid-template-columns: 1fr 1fr; grid-auto-rows: 1fr; gap: 6px 28px; margin-top: 0; flex: 1 1 auto; min-height: 0; }
.tk-agenda.tk-agenda3 { grid-template-columns: 1fr 1fr 1fr; }
.tk-msg { display: grid; align-items: stretch; gap: 10px; margin-top: 8px; flex: none; }
.tk-msgh { display: flex; align-items: center; padding: 0 14px; background: var(--navy); color: #fff; border-radius: 6px; font-size: 13.5px; }
.tk-m { display: flex; align-items: center; gap: 9px; padding: 9px 12px; background: var(--band, #EEF3F9); border-radius: 6px; }
.tk-mn { flex: none; width: 22px; height: 22px; border-radius: 11px; background: var(--navy); color: #fff; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.tk-m b { display: block; font-size: 14px; color: var(--navy); } .tk-m span { font-size: 12.5px; color: var(--g900); line-height: 1.45; } .tk-m .tk-mn { color: #fff; }
.tk-arow { display: grid; grid-template-columns: 54px 1fr; align-items: start; gap: 12px; padding: 12px 0; border-top: 1px solid var(--hair); }
.tk-ano { font-size: 30px; font-weight: 700; color: var(--navy); }
.tk-atx { display: flex; flex-direction: column; height: 100%; } .tk-atx > b { display: block; font-size: 17px; color: var(--ink2); margin-bottom: 4px; } .tk-atx > span { font-size: 13.5px; color: var(--g900); line-height: 1.5; }
.tk-atx ol { list-style: none; margin: 8px 0 10px; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 3px 16px; }
.tk-atx ol li { font-size: 13px; color: var(--g900); } .tk-atx ol li i { display: inline-block; width: 26px; font-style: normal; font-weight: 700; color: var(--navy); }
.tk-core { display: flex; align-items: center; gap: 8px; margin-top: auto; padding: 8px 10px; background: var(--band, #EEF3F9); border-radius: 6px; font-size: 13px; color: var(--ink2); }
.tk-core svg { flex: none; }
.tk-about { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: auto 1fr; gap: 14px 26px; flex: 1 1 auto; min-height: 0; margin-top: 2px; align-content: start; }
.tk-cell { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.tk-sh { display: flex; align-items: center; gap: 8px; height: 26px; border-bottom: 2px solid var(--navy); }
.tk-sh b { font-size: 15px; color: var(--navy); } .tk-sh span { margin-left: auto; font-size: 12.5px; color: var(--grey); }
.tk-rows { display: flex; flex-direction: column; }
.tk-row { display: grid; grid-template-columns: 34px 1.05fr 1.25fr 1fr; align-items: center; gap: 10px; min-height: 40px; padding: 3px 0; border-bottom: 1px solid var(--hair); }
.tk-tile { border-radius: 5px; display: inline-block; justify-self: center; } .tk-mono { background: var(--band, #EEF3F9); }
.tk-c1 b, .tk-c2 b { display: block; font-size: 13.5px; color: var(--ink2); line-height: 1.35; } .tk-c1 span, .tk-c2 span { display: block; font-size: 11.5px; color: var(--grey); line-height: 1.35; }
.tk-c3 { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 2px 8px; } .tk-c3 span { grid-column: 1 / -1; font-size: 12px; color: var(--g900); }
.tk-c3 i { display: block; height: 7px; border-radius: 4px; background: var(--navy); } .tk-c3 b { font-size: 12px; color: var(--navy); }
.tk-ov { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.tk-ovb { padding: 9px 12px; background: var(--band, #EEF3F9); border-radius: 6px; } .tk-ovh { display: flex; align-items: center; gap: 7px; margin-bottom: 4px; }
.tk-ovh b { font-size: 14px; color: var(--navy); } .tk-ovb p { margin: 0; font-size: 13px; line-height: 1.55; color: var(--g900); }
.tk-srow { display: grid; grid-template-columns: 110px 1fr; align-items: center; gap: 10px; min-height: 32px; padding: 3px 0; border-bottom: 1px solid var(--hair); font-size: 13px; color: var(--g900); }
.tk-srow b { color: var(--navy); font-size: 13px; }
.tk-pillars { display: grid; gap: 16px; flex: 1 0 auto; margin-bottom: 4px; }
.tk-pillar, .tk-phase { display: flex; flex-direction: column; border: 1px solid var(--hair); border-radius: 6px; overflow: hidden; }
.tk-pillar .tk-phd { background: var(--navy); color: #fff; padding: 9px 14px; display: flex; flex-direction: row; align-items: center; gap: 10px; }
.tk-pillar .tk-phd > div { display: flex; flex-direction: column; gap: 2px; } .tk-pillar .tk-phd b { font-size: 15px; } .tk-pillar .tk-phd span { font-size: 12.5px; opacity: .85; }
.tk-psk { margin: 10px 14px 6px; font-size: 13.5px; line-height: 1.6; color: var(--g900); min-height: 65px; }
.tk-pillar ul, .tk-phase ul { margin: 2px 14px 12px; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.tk-pillar ul { flex: 1 1 auto; justify-content: flex-start; }   /* the first evidence of every pillar on one line */
.tk-pillar li { position: relative; padding: 8px 46px 0 0; border-top: 1px solid var(--hair); font-size: 13px; line-height: 1.5; color: var(--g900); }
.tk-pillar li b { display: block; color: var(--navy); font-size: 13.5px; margin-bottom: 1px; }
.tk-pillar li .tk-pp { position: absolute; right: 0; top: 9px; font-size: 12px; color: var(--grey); }
.tk-pfoot { margin-top: 12px; padding: 10px 14px; background: var(--band, #EEF3F9); border-radius: 6px; font-size: 13.5px; color: var(--g900); line-height: 1.55; flex: none; }
.tk-pfoot b { color: var(--navy); } .tk-pfoot > b:first-child { margin-right: 10px; }
.tk-lessons { display: grid; grid-template-columns: 1fr 1fr; grid-auto-rows: 1fr; gap: 10px 26px; flex: 1 1 auto; margin-top: 4px; min-height: 0; }
.tk-les { display: grid; grid-template-columns: 34px 1fr; gap: 10px; padding-top: 12px; border-top: 1px solid var(--hair); }
.tk-les > div { display: flex; flex-direction: column; }
.tk-lno { width: 28px; height: 28px; border-radius: 14px; background: var(--navy); color: #fff; font-size: 14px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.tk-les h3 { margin: 2px 0 6px; font-size: 17.5px; color: var(--navy); } .tk-les h3 svg { vertical-align: -3px; margin-right: 7px; }
.tk-les p { margin: 0; font-size: 15px; line-height: 1.66; color: var(--g900); } .tk-l4 .tk-les p { font-size: 16px; }
.tk-tech { margin-top: auto; padding-top: 6px; font-size: 12.5px; color: var(--g900); } .tk-tech b { color: var(--teal, #137A63); margin-right: 8px; }
.tk-lsrc { padding: 2px 0 6px; font-size: 12px; color: var(--grey); }
.tk-scope { display: flex; gap: 8px; align-items: flex-start; padding: 9px 12px; background: var(--band, #EEF3F9); border-radius: 6px; font-size: 13px; line-height: 1.55; color: var(--g900); }
.tk-scope svg { flex: none; margin-top: 2px; } .tk-scope b { color: var(--navy); margin-right: 6px; }
.tk-cards { display: grid; gap: 14px; flex: 1 1 auto; align-content: start; }
.tk-fill { grid-auto-rows: 1fr; align-content: stretch; } .tk-fill .card p { font-size: 16px; line-height: 1.7; } .tk-fill .card h3 { font-size: 17px; }
.tk-fill + .tk-scope { margin-top: 10px; }
.slide[data-kind="talk"] p, .slide[data-kind="talk"] li { text-wrap: pretty; }   /* no word alone on a last line, on the talk's own slides only */
.slide[data-kind="talk"] .card p, .slide[data-kind="talk"] .tk-pfoot, .slide[data-kind="talk"] .tk-scope span { text-wrap: balance; }   /* a short card's lines even, never one word on the last */
.body.tk-bigr .stack .card p { font-size: 15px; line-height: 1.65; } .body.tk-bigr .stack .card h3 { font-size: 16px; }
.tk-phases { display: grid; gap: 16px; flex: 1 1 auto; min-height: 0; margin-top: 2px; }
.tk-phh { display: flex; align-items: center; gap: 8px; padding: 12px 14px 4px; } .tk-phh b { font-size: 16px; color: var(--navy); }
.tk-phase li { position: relative; padding-left: 14px; font-size: 14.5px; line-height: 1.66; color: var(--g900); }
.tk-phase li::before { content: ""; position: absolute; left: 1px; top: 9px; width: 6px; height: 6px; border-radius: 3px; background: var(--blue); }
.tk-pk { margin: auto 14px 10px; border-top: 1px solid var(--hair); padding-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.tk-pk > div:first-child { min-height: 39px; }   /* the output takes two lines in every phase, so the measures stand on one line */
.tk-pk div { display: grid; grid-template-columns: 52px 1fr; font-size: 13px; line-height: 1.5; color: var(--g900); } .tk-pk b { color: var(--navy); }
.tk-pbox { margin: 0 14px 14px; padding: 9px 12px; background: var(--band, #EEF3F9); border-radius: 6px; }
.tk-pbox b { display: block; font-size: 13px; color: var(--navy); margin-bottom: 4px; }
.tk-pbox ol { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.55; color: var(--g900); }
.tk-phase .tk-pbox li { padding-left: 2px; font-size: 13px; line-height: 1.55; } .tk-phase .tk-pbox li::before { content: none; }
.tk-endm { display: flex; gap: 12px; margin-top: 18px; } .tk-endm span { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border: 1px solid rgba(255,255,255,.35); border-radius: 6px; color: #fff; font-size: 15px; font-weight: 600; }
.tk-endm i { font-style: normal; width: 22px; height: 22px; border-radius: 11px; background: #fff; color: #14233A; font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }
`;

// The company's colours, lightly: the frame's posters and dividers take its dark colour, and its accent marks only order and place
// (the chapter numbers, the numbered rows and the rail's marker). Words stay neutral on both.
const themeCss = t => !t ? "" : `
.eyebrow::before, .eod .top::before { background: ${t.accent}; }
.rail .seg.on { background: ${t.frame}; } .rail .here, .rail.dark .here { border-left-color: ${t.accent}; }
.slide.eod { background: ${t.frame}; } .eod .top, .eod h1 small, .eod .tag, .eod .cc b { color: #c6c6c6; } .eod .lead { color: #f1f1f1; }
.eod .cc .ic { background: rgba(255, 255, 255, 0.14); } .eod .bot { border-top-color: rgba(255, 255, 255, 0.18); }
.slide.chapter .cl { background: ${t.frame}; } .chapter .cl .no { color: ${t.accent}; }
.chapter .cl .kind, .chapter .cl .enm, .chapter .cl .meta b { color: #c6c6c6; }
.chapter .cl .lead { color: #f1f1f1; border-top-color: rgba(255, 255, 255, 0.18); } .chapter .cl .lead b { color: #ffffff; }
.chapter .plist .p .num, .tk-ano { color: ${t.accent}; } .chapter .plist .p:first-child, .chapter .plist.two { border-top-color: ${t.frame}; }
.tk-msgh { background: ${t.frame} !important; } .tk-m .tk-mn { background: ${t.accent} !important; } .tk-endm i { color: ${t.frame} !important; }
`;

// ───────── main ─────────
function main(argv) {
  if (argv[0] === "--pages") {                                               // the planner asks what the portfolio holds
    const [, profile, jobFile, page] = argv;                                 // the edition's profile, its job.json and a page name
    const pf = portfolio(profile, jobFile, page || "talk_pages");            // caught, never written
    const cfg = jobFile && fs.existsSync(jobFile) ? JSON.parse(fs.readFileSync(jobFile, "utf-8")) : {};   // the edition's language
    process.stdout.write(JSON.stringify({ own: OWN, slides: pf.slides.map(slideInfo), view: view(profile, cfg.lang === "en" ? "en" : "ko", cfg) }));   // what each slide is, and the profile as the documents read it
    return 0;
  }
  const [talkFile, profile, jobFile, page] = argv;                           // the talk, the edition's profile and job.json, the page's name
  if (!talkFile || !profile || !page) { console.error("usage: node src/talk_slides.js <talk.json> <profile.json> <job.json> <page name>"); return 1; }
  const talk = JSON.parse(fs.readFileSync(talkFile, "utf-8"));               // everything talk.py settled
  T.lang = talk.lang === "en" ? "en" : "ko"; T.W = WORDS[T.lang]; T.theme = talk.theme || null;   // the language and the company's colours
  const needs = (talk.slides || []).some(s => s.kind === "page");            // a talk may show no portfolio page at all
  const pf = needs ? portfolio(profile, jobFile, page + "_pf") : null;       // the portfolio's slides, caught
  const deck = new Deck({ title: talk.title || "", footer: "", theme: pf ? pf.theme : undefined, lang: T.lang, look: pf ? pf.look : undefined,
                          css: CSS + themeCss(T.theme) });                   // the same colour set and look as the portfolio
  for (const s of talk.slides || []) {                                       // in the talk's order
    if (s.kind === "page") { const x = pageOf(pf, s.n, talk.swaps); deck.add({ ...x.meta, part: String(s.part ?? "") }, x.html); continue; }   // a portfolio page
    const draw = DRAW[s.kind];                                               // the template for this kind
    if (!draw) throw new Error(`unknown slide kind '${s.kind}'`);            // talk.py and this file disagree
    deck.add({ kind: s.kind === "cover" || s.kind === "end" ? "end" : s.kind === "chapter" ? "chapter" : "talk", cls: CLS[s.kind] || "",
               nofoot: s.kind === "cover", part: String(s.part ?? "") }, draw(s, talk));   // the slide, with its frame class
  }
  // The side rail: an overview tab, then one tab per part, from each part's divider to the slide before the next
  const groups = (talk.parts || []).map(p => ({ no: p.no, name: p.short || p.title, part: p.no, page: p.first })).filter(g => g.page > 1);   // each part's first page
  if (groups.length) {                                                       // a talk with parts has a rail
    const R = OWN ? STR.rails(deck.slides.length, groups) : STR.rails(deck.slides.length, groups, T.lang);   // either frame's rail
    deck.slides.forEach((sl, i) => { sl.meta.rail = sl.meta.kind === "end" ? "" : OWN ? STR.railHtml(R, i + 1, sl.meta.kind === "chapter") : STR.railHtml(R, i + 1, sl.meta.kind === "chapter", T.lang); });
  }
  const n = deck.render(path.join(ROOT, "output", page + ".html"));          // the page; talk.py prints and measures it
  console.log("slides", n);                                                  // the count for the caller
  return 0;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));   // run as a command
module.exports = { main, slideInfo, WORDS, CSS };                            // for the tests
