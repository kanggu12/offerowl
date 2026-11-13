// A career-description resume from one profile file (docs/DOCUMENTS.md, "Profile fields").
// It uses the layout functions of layout.js, the themes and the job's two-layer options, and it draws these
// parts: overview timeline and hierarchy figures, overview cards, selected project cards, a career summary with logos,
// place, department and tenure, an education table with logos, core competencies with their evidence projects, the skills
// table, company bands with logo, badge and description, structured sections (dated lines, tables, groups), about-me bands,
// motivation and a name footer.
//   node src/resume_form.js <profile.json> [job.json]
//   job fields: out, lang ("ko"|"en"), theme, form ("detailed", "compact" or "table"), skillsFocus, skillsStrong, skillsHighlight, skillsEdit, competencyWeak,
//   competencyDrop, projectOrder, motivation, photo, sections (titles to include, in order), tenure (false hides it),
//   titleView ("full" reads a role's long title), competencyFigure (false leaves the hierarchy figure out),
//   footerLabel (the older footer: the name and this word for the document kind, as an edition the person made had it),
//   plain (true: section titles with a rule only, no accent bars, English names, rails or outer card borders)
// The detailed form's order: header, headline and intro, overview, career summary, education,
// core competencies, skills, professional experience, other sections, about me, motivation. FORMS below lists the others.
const fs = require("fs");               // file checks
const path = require("path");           // paths
const L = require("./layout");          // the layout engine
const G = require("./profile_loader"); // one profile loader for the resume, deck and figures

// Section names per language. The faint right-hand label is English in both editions
const LABEL = {
  ko: { resume: "이 력 서", name: "성명", service: "병역사항", kind: "구분", career: "경력요약", skills: "보유기술", detail: "상세경력사항", edu: "학력사항", cat: "분류", tech: "기술",
        org: "회사(소재)", period: "기간", dept: "부서 / 직급", role: "직무(포지션)", tenure: "재직", school: "학교", major: "전공",
        degree: "학위와 비고", overview: "개요", highlights: "대표 프로젝트", comp: "핵심역량", about: "자기소개",
        motivation: "지원 동기", total: "총경력", phone: "연락처", email: "이메일", location: "거주지", info: "인적사항" },
  en: { resume: "Resume", name: "Name", service: "Military Service", kind: "Type", career: "Career Summary", skills: "Technical Skills", detail: "Professional Experience", edu: "Education", cat: "Category", tech: "Skills",
        org: "Company (Location)", period: "Period", dept: "Department / Title", role: "Role", tenure: "Tenure", school: "School", major: "Major",
        degree: "Degree", overview: "Overview", highlights: "Selected Projects", comp: "Core Competencies", about: "About Me",
        motivation: "Motivation", total: "total", phone: "Phone", email: "Email", location: "Location", info: "Personal" },
};

// Column widths for a table from its content: wider columns for longer text, every column at least a minimum,
// the sum equal to the body width (layout.js stops on any other sum)
function autoWidths(head, rows, fixed) {
  const W = L.CONTENT_W;                                                 // body width in twips
  if (fixed) {                                                           // the profile may give fractions or twips
    const tw = fixed.map(f => f <= 1 ? Math.round(f * W) : f);
    tw[tw.length - 1] = W - tw.slice(0, -1).reduce((a, b) => a + b, 0); // the last column takes the rounding
    return tw;
  }
  const len = s => [...String(s || "")].reduce((a, c) => a + (/[ㄱ-힣]/.test(c) ? 2 : 1), 0);   // Hangul is about two Latin letters wide
  const n = head.length;                                                 // number of columns
  const need = head.map((h, i) => Math.max(len(h), ...rows.map(r => Math.min(60, len(r[i])))));   // the longest cell, capped
  const min = 900;                                                       // no column narrower than this (about 6 Hangul characters)
  const sum = need.reduce((a, b) => a + b, 0) || 1;
  const w = need.map(x => Math.max(min, Math.round(W * x / sum)));       // proportional, floored
  const over = w.reduce((a, b) => a + b, 0) - W;                         // the floor may push the sum over the width
  const widest = w.indexOf(Math.max(...w));                              // take the excess from the widest column
  w[widest] -= over;
  return n ? w : [];
}

function build(profilePath, cfg = {}) {
  const lang = cfg.lang || "ko", T = LABEL[lang];                        // section names of the edition
  if (!T) throw new Error("lang must be ko or en");
  const prof = G.load(profilePath, lang, cfg);                           // normalized profile for this language
  const P = prof.person, S = prof.summary || {};
  const W = L.CONTENT_W, ch = [];                                        // body width, the document's paragraphs
  L.setFont("Pretendard");                                               // the resume's body font
  L.setTheme(cfg.theme || "navy");                                       // theme (OFFEROWL_THEME, OFFEROWL_THEME_FILE win)
  L.setLangKo(lang === "ko");
  L.setPlain(!!cfg.plain);                                               // the plain look, when the edition was made in it
  // Names: the English edition puts the English name first, the Korean edition the Korean name
  const [N1, N2] = lang === "en" && P.name_en ? [P.name_en, P.name] : [P.name, P.name_en_ko || P.name_en || ""];   // name_en_ko: how the Korean edition writes the English name ("Hong, Gildong")
  // Footer: name and page number only (a document-kind word is not repeated on every page).
  // The Korean edition adds the English name after the Korean one; the English edition shows the English name alone.
  // cfg.footerLabel: an edition the person made with the older footer keeps it (the name, then a word for the document kind)
  if (cfg.footerLabel) { L.setFooterName(null); L.setFooterLabel(N1 + "  " + cfg.footerLabel); }
  else L.setFooterName(N1, lang === "ko" ? N2 || null : null);
  L.setDocMeta({ title: `${N1} ${lang === "ko" ? "이력서" : "Resume"}`, author: N1 });   // the file's title and author, never its build name
  const out = cfg.out || path.basename(profilePath, ".json");            // output name (figure and tile names too)
  const figDir = path.join(__dirname, "..", "output", "_figures");   // overview_figures.py writes here before the build
  const fig = kind => path.join(figDir, `${out}_${kind}${lang === "en" ? "_en" : ""}.png`);
  const tile = id => { const f = path.join(figDir, `${out}_logo_${id}.png`); return id && fs.existsSync(f) ? f : null; };   // logo tiles are language-free
  // Section heading. The faint English label on the right is for the Korean edition only; an English title needs no echo
  const sec = (title, note, en) => L.fsec(title, note, lang === "ko" ? en : null);

  // Header: name, English name, tagline, contact rows (personal info and location first)
  const contacts = [];
  if (P.info) contacts.push([T.info, P.info]);
  if (P.location) contacts.push([T.location, P.location]);
  if (P.phone) contacts.push([T.phone, P.phone]);
  contacts.push([T.email, P.email, "mailto:" + P.email]);
  for (const l of P.links || []) contacts.push(l);                       // [label, shown text, address]
  const parts = {};                                                      // the parts of a resume; a form lists the ones it prints, in its order
  parts.header = () => ch.push(...[].concat(L.fheader(N1, N2, P.tagline || "", contacts, cfg.photo || null)));

  parts.top = () => {
  // Headline: a line break in the text is kept (a long English headline can break after its colon so no word is left alone)
  if (S.headline) {
    const ho = { size: 24, bold: true, color: L.INK };
    const runs = String(S.headline).split("\n").map((t, i) => L.run(t, { ...ho, br: i ? 1 : 0 }));
    ch.push(L.p(runs.length > 1 ? runs : S.headline, { ...ho, before: 160, after: 60 }));
  }
  if (S.intro && typeof S.intro === "string") ch.push(L.prose(S.intro, { after: 50 }));   // the next section title brings its own room
  };

  parts.overview = () => {
  // Overview: timeline figure, two-column cards (summary.cards, an even count) and selected project cards (summary.highlights)
  const cards = S.cards || [], hl = S.highlights || [];
  hl.forEach((c, i) => {                                                 // a malformed card crashed deep inside the layout engine
    if (!c || typeof c !== "object" || !c.title || !Array.isArray(c.rows) || !c.rows.every(r => Array.isArray(r) && r.length >= 2))
      throw new Error(`summary.highlights[${i}] must be { title, where, rows: [[label, text], ...] }`);
  });
  if (fs.existsSync(fig("timeline")) || cards.length || hl.length) {
    ch.push(sec(T.overview, null, "OVERVIEW"));
    if (fs.existsSync(fig("timeline"))) ch.push(L.fimage(fig("timeline"), { after: 20 }));
    if (cards.length) {
      if (cards.length % 2) throw new Error("summary.cards needs an even count (two per row)");
      ch.push(L.fcards(cards));
    }
    if (hl.length) {
      if (hl.length > 4) throw new Error("summary.highlights takes four at most (one row)");
      ch.push(L.tcap(T.highlights));
      ch.push(L.fhighlights(hl.map(c => ({ ...c, where: c.where || "" }))));
    }
  }
  };

  // Project order: the job's projectOrder (ids from the JD analysis) first in that order, the rest as written
  const order = cfg.projectOrder || [];
  const ordered = ps => [...ps].map((p, i) => [p, i]).sort((x, y) => {
    const a = order.indexOf(x[0].id), b = order.indexOf(y[0].id);
    return (a < 0 ? 1e9 : a) - (b < 0 ? 1e9 : b) || x[1] - y[1];
  }).map(x => x[0]);
  const roles = prof.roles;                                              // newest first (the loader sorts)
  const logoCell = (text, id) => {                                       // a name cell with the logo on its left and grey lines below
    const f = tile(id);
    return f ? { t: text, logoLeft: f, subSize: 16 } : text;
  };
  const anyRoleLogo = roles.some(r => tile(r.logoId));                   // logo columns need a wider name column

  parts.career = () => {
  // Career summary: period, company with place (and note), department / title, role, tenure. Total tenure next to the title
  if (roles.length) {
    const showTenure = roles.some(r => r.tenure);
    ch.push(sec(T.career, prof.total && showTenure ? `  (${T.total} ${prof.total})` : null, "CAREER SUMMARY"));
    const anyDept = roles.some(r => r.dept);
    const cols = [T.period, T.org, ...(anyDept ? [T.dept] : []), T.role, ...(showTenure ? [T.tenure] : [])];
    // Column widths that hold common content (Korean with logos: period 1850, company 2850, department 2600, role 2100;
    // English: 1700, 3300, 2550, 1650, so a long university name stays on one line). cfg.widths.career overrides
    const full = lang === "en" ? [1700, 3300, 2550, 1650] : anyRoleLogo ? [1850, 2850, 2600, 2100] : [1850, 2400, 3000, 2100];
    const preset = anyDept
      ? (showTenure ? full : [full[0], full[1] + 350, full[2] + 300])
      : (showTenure ? [full[0], full[1] + 750, full[2] + full[3] - 750] : [full[0], full[1] + 1350]);
    const widths = (cfg.widths && cfg.widths.career) || [...preset, W - preset.reduce((a, b) => a + b, 0)];
    ch.push(L.ftable(widths, roles.map(r => [
      r.period,
      logoCell([r.org, [r.place, r.note].filter(Boolean).join(", ")].filter(Boolean).join("\n"), r.logoId),
      ...(anyDept ? [r.dept || ""] : []),
      r.title || "",
      ...(showTenure ? [r.tenure || ""] : []),
    ]), { split: true, head: cols, align: ["c", "l", "l", "l", "c"].slice(0, cols.length - 1).concat(showTenure ? ["c"] : ["l"]) }));
  }
  };

  parts.education = () => {
  // Education: period, school (with a grey second line), major (with a sub major), degree and notes
  if (prof.education.length) {
    ch.push(sec(T.edu, null, "EDUCATION"));
    const anyEduLogo = prof.education.some(e => tile(e.logoId));
    // Korean 1650, 3200, 3000 with logos; English 1630, 3530, 2715 so a long graduate school
    // name fits one line. cfg.widths.education overrides
    const preset = lang === "en" ? [1630, 3530, 2715] : anyEduLogo ? [1650, 3200, 3000] : [1650, 2850, 3300];
    const widths = (cfg.widths && cfg.widths.education) || [...preset, W - preset.reduce((a, b) => a + b, 0)];
    ch.push(L.ftable(widths, prof.education.map(e => [
      e.period,
      logoCell([e.school, e.sub].filter(Boolean).join("\n"), e.logoId),
      [e.major, e.majorSub].filter(Boolean).join("\n"),
      [e.degree, e.note].filter(Boolean).join("\n"),
    ]), { split: true, head: [T.period, T.school, T.major, T.degree], align: ["c", "l", "l", "l"] }));
  }
  };

  parts.competencies = () => {
  // Core competencies: hierarchy figure and competency bullets. Each competency ends with its evidence projects in parentheses.
  // competencyWeak moves names to the back (JD two layers, nothing is dropped or faded); competencyDrop leaves names out
  const weak = cfg.competencyWeak || [], drop = cfg.competencyDrop || [];
  const comps = prof.competencies.filter(c => !drop.includes(c.name));
  const unknown = [...weak, ...drop].filter(w => !prof.competencies.some(c => c.name === w));
  if (unknown.length) throw new Error("competencyWeak or competencyDrop names a competency the profile does not have: " + unknown.join(", "));
  const stack = cfg.competencyFigure !== false && fs.existsSync(fig("stack"));   // the hierarchy figure, unless the edition leaves it out
  if (stack || comps.length) {
    ch.push(sec(T.comp, null, "CORE COMPETENCIES"));
    if (stack) ch.push(L.fimage(fig("stack"), { after: 80 }));
    [...comps.filter(c => !weak.includes(c.name)), ...comps.filter(c => weak.includes(c.name))]
      .forEach(c => ch.push(L.fbul(c.name, c.text + (c.evidence.length ? ` (${c.evidence.join(", ")})` : ""), { after: 50, weak: weak.includes(c.name) })));
  }
  };

  parts.skills = () => {
  // Skills table (JD layers: skillsFocus orders categories, skillsStrong bolds names, skillsHighlight marks a few of those)
  if (prof.skills.length) {
    ch.push(sec(T.skills, null, "TECHNICAL SKILLS"));
    const rows = prof.skills.map(s => [s.category, (s.items || []).join(", ")]);
    ch.push(L.ftable([2000, W - 2000], L.focusRows(rows, cfg.skillsFocus, cfg.skillsStrong, cfg.skillsHighlight, cfg.skillsEdit),
      { key: true, split: true, head: [T.cat, T.tech] }));
  }
  };

  parts.experience = () => {
  // Professional experience: company band (logo, name, badge, place, period and tenure), department line, grey description,
  // project bullets 'Title (period): summary' where ==phrase== is the yellow highlight
  if (roles.length) ch.push(sec(T.detail, null, "PROFESSIONAL EXPERIENCE"));
  // layout.js draws a badge next to a logo with src/badge.py; without that file the badge stays off rather than crashing
  const badgeOk = fs.existsSync(path.join(__dirname, "badge.py"));
  for (const r of roles) {
    const logo = tile(r.logoId);
    const band = L.fband(r.org, r.period + (r.tenure ? ` (${r.tenure})` : ""), { boldRight: true, title: r.titleLong || r.title, place: r.place,
      logo, badge: logo && !badgeOk ? "" : r.badge });
    ch.push(...[].concat(band));
    const sub = r.sub || [[r.dept, r.title].filter(Boolean).join(" / "), r.context].filter(Boolean).join(", ");
    if (sub) ch.push(L.fsub(sub));
    if (r.desc) ch.push(L.p(r.desc, { size: 16, color: L.GREY, after: 60, keepNext: true }));   // kept with the first item
    for (const x of ordered((r.projects || []).filter(x => x.resume !== false))) {   // resume: false keeps a deck-only project out
      const head = x.title + (x.period ? " (" + x.period + ")" : "");
      // A project without a summary (a ledger that has not been drafted yet) shows its title only, without a dangling colon
      ch.push(x.summary ? L.fbul(head, x.summary, { after: 90 }) : L.fbul("", head, { after: 50 }));
    }
  }
  };

  parts.others = () => {
  // Other sections: items (bullets), lines ([main, org, date] dated lines), rows with head (a table), groups of those under
  // captions, or the tables and bullets of a ledger markdown body
  const block = b => {
    if (b.caption) return [L.tcap(b.caption)];
    if (b.item) return [L.fbul("", b.item, { after: 40 })];
    if (b.table) return b.table.rows.length ? [L.ftable(autoWidths(b.table.head, b.table.rows, b.widths), b.table.rows, { split: true, head: b.table.head })] : [];
    return [];
  };
  // A table cell is text or { t, bold, accent }: accent draws the text in the theme's accent color (a first-author mark, say)
  const cell = c => (c && typeof c === "object" ? { t: String(c.t ?? ""), bold: !!c.bold, ...(c.accent ? { color: L.accent2() } : {}) } : String(c ?? ""));
  const text = c => (c && typeof c === "object" ? String(c.t ?? "") : String(c ?? ""));   // the cell's text for column widths
  const bodyOf = s => [
    ...(s.items || []).map(it => L.fbul("", it, { after: 40 })),
    // Dated lines keep together within a group so one line never drops alone to the next page
    ...(s.lines || []).map((l, i, all) => L.fline(l[0], l[1] || "", l[2] || "", i < all.length - 1)),
    ...(s.rows && s.rows.length ? [L.ftable(autoWidths(s.head || s.rows[0].map(() => ""), s.rows.map(r => r.map(text)), s.widths), s.rows.map(r => r.map(cell)),
      { split: true, ...(s.head ? { head: s.head } : {}), ...(s.align ? { align: s.align } : {}) })] : []),
    ...(s.blocks || []).flatMap(block),
    ...(s.note ? [L.p(s.note, { size: 16, color: L.GREY, before: 50, after: 40 })] : []),   // a grey note under a table or list
  ];
  for (const s of prof.sections) {
    if (!s.resume) continue;                                             // the profile marks sections that stay out of resumes
    const body = s.groups ? s.groups.flatMap(g => [L.tcap(g.title), ...bodyOf(g)]) : bodyOf(s);
    if (!body.length) continue;                                          // an empty section gets no heading
    ch.push(sec(s.title, null, (s.title_en || "").toUpperCase()));
    ch.push(...body);
  }
  };

  parts.about = () => {
  // About me: stage bands joined by a thin rail (about: [[title, paragraph or paragraphs], ...]); an entry { quote, text } is a
  // boxed statement with a small heading (a 'how I work' box) placed where it is listed
  const about = prof.about || [];
  if (about.length) {
    ch.push(sec(T.about, null, "ABOUT ME"));
    for (const item of about) {
      if (item && !Array.isArray(item) && item.quote) { ch.push(...[].concat(L.fquote(item.quote, item.text || ""))); continue; }
      const [t, body] = item;
      ch.push(L.fband(t, "", { before: 100, rail: true }));
      [].concat(body).forEach(b => ch.push(L.prose(b, { rail: true })));
    }
  }
  };

  parts.motivation = () => {
  // Motivation: the job's motivation first (it differs per application), else the profile's
  const motive = cfg.motivation || prof.motivation;
  if (motive) {
    const own = !cfg.motivation && prof.motivationTitle;                             // the person's own name for it, in a general edition
    ch.push(sec(own ? prof.motivationTitle : T.motivation, null, own ? String(prof.motivationTitleEn || prof.motivationTitle).toUpperCase() : "MOTIVATION"));   // a job's motivation keeps the usual title
    [].concat(motive).forEach(b => ch.push(L.prose(b)));
  }
  };

  // One column, the form most tech resumes take and the one a program reads best: name, one contact line, what the person does, then
  // the work, skills, education and other lists. No figure, no table, no logo; the same bullets as the detailed form
  parts.plainHead = () => {
    ch.push(L.p([L.run(N1, { size: 40, bold: true, color: L.INK }), ...(N2 ? [L.run("  " + N2, { size: 20, color: L.GREY })] : [])], { before: 0, after: 20 }));   // the name, and the other spelling small
    if (P.tagline) ch.push(L.p(P.tagline, { size: 17, bold: true, color: L.accent2(), after: 20 }));   // what the person is
    ch.push(L.p(contacts.map(c => c[1]).filter(Boolean).join("   |   "), { size: 17, color: L.GREY, after: 40 }));   // one line a reader's eye and a program both find
  };
  parts.plainWork = () => {
    if (roles.length) ch.push(sec(T.detail, null, "PROFESSIONAL EXPERIENCE"));   // the same heading as the detailed form
    for (const r of roles) {                         // newest first
      const role = lang === "en" ? r.titleLong || r.title : r.title || r.titleLong;   // the edition's own word for the role
      ch.push(L.frow(r.org, [role, r.place].filter(Boolean).join(", "), r.period));   // company, role and place, dates on the right
      if (r.desc) ch.push(L.p(r.desc, { size: 16, color: L.GREY, after: 40, keepNext: true }));   // the company in a line
      for (const x of ordered((r.projects || []).filter(y => y.resume !== false))) {   // the printed projects, in the job's order
        const head = x.title + (x.period ? " (" + x.period + ")" : "");   // its name and dates
        ch.push(x.summary ? L.fbul(head, x.summary, { after: 70 }) : L.fbul("", head, { after: 40 }));   // as in the detailed form
      }
    }
  };
  parts.plainSkills = () => {
    if (!prof.skills.length) return;                 // none to list
    ch.push(sec(T.skills, null, "TECHNICAL SKILLS"));   // its heading
    const focus = cfg.skillsFocus || [];             // the categories the job asks for come first, in its order
    const rows = [...focus.map(f => prof.skills.find(x => x.category === f)).filter(Boolean), ...prof.skills.filter(x => !focus.includes(x.category))];   // then the rest
    for (const x of rows) ch.push(L.fbul(x.category, (x.items || []).join(", "), { after: 30 }));   // a line per category
  };
  parts.plainEducation = () => {
    if (!prof.education.length) return;              // none to list
    ch.push(sec(T.edu, null, "EDUCATION"));          // its heading
    for (const e of prof.education) ch.push(L.frow(e.school, [e.major, e.degree, e.note].filter(Boolean).join(", "), e.period));   // a line per school
  };
  // The other lists of the profile, with no table: a row becomes a dated line, as a program reads it in order
  parts.plainOthers = () => {
    const say = c => String(c && typeof c === "object" ? c.t ?? "" : c ?? "");   // a table cell's words
    const row = r => L.fline(say(r[0]), r.slice(1, -1).map(say).filter(Boolean).join(", "), r.length > 1 ? say(r[r.length - 1]) : "");   // first cell, the middle ones, the last one on the right
    const body = s => {                              // one list, whichever shape it has
      for (const it of s.items || []) ch.push(L.fbul("", it, { after: 40 }));   // bullets
      for (const l of s.lines || []) ch.push(L.fline(l[0], l[1] || "", l[2] || "", false));   // dated lines
      for (const r of s.rows || []) ch.push(row(r));   // a table's rows
      for (const b of s.blocks || []) {              // a ledger's mixed blocks
        if (b.caption) ch.push(L.tcap(b.caption));   // a caption over what follows
        else if (b.item) ch.push(L.fbul("", b.item, { after: 40 }));   // a bullet
        else if (b.table) for (const r of b.table.rows) ch.push(row(r));   // a table's rows
      }
    };
    for (const s of prof.sections) {                 // each section the resume takes
      if (!s.resume) continue;                       // the profile marks those that stay out
      ch.push(sec(s.title, null, s.title_en));       // its heading
      if (s.groups) for (const g of s.groups) { ch.push(L.tcap(g.title)); body(g); }   // its groups
      else body(s);                                  // or its own list
    }
  };
  // The Korean table form: what the public standard application asks for, each as a table, then the work in detail
  parts.tableHead = () => {
    ch.push(L.p(T.resume, { size: 36, bold: true, color: L.INK, align: "center", before: 0, after: 120 }));   // the document's name
    const rows = [[T.name, [N1, N2].filter(Boolean).join("  ")], ...contacts.map(c => [c[0], c[1]])];   // who, and how to reach them
    ch.push(L.ftable([2000, W - 2000], rows, { key: true, split: true }));   // a label and its value
  };
  parts.service = () => {
    const s = prof.service;                          // the record, where it counts
    if (!s || !s.label) return;                      // not everyone has one
    ch.push(sec(T.service, null, "MILITARY SERVICE"));   // its heading
    ch.push(L.ftable([2000, W - 2000], [[[s.start, s.end].filter(Boolean).join(" ~ "), s.label]], { split: true, head: [T.period, T.kind], align: ["c", "l"] }));   // when, and what
  };

  // The forms. Each lists its parts in print order
  const FORMS = {
    detailed: ["header", "top", "overview", "career", "education", "competencies", "skills", "experience", "others", "about", "motivation"],
    compact: ["plainHead", "top", "plainWork", "plainSkills", "plainEducation", "plainOthers"],
    table: ["tableHead", "education", "career", "others", "service", "skills", "experience", "about", "motivation"],
  };
  const form = FORMS[cfg.form || "detailed"];        // the job's choice
  if (!form) throw new Error(`unknown resume form '${cfg.form}': use ${Object.keys(FORMS).join(", ")}`);   // a typo must not print the wrong form
  for (const name of form) parts[name]();            // printed in order

  L.render(ch, path.join(__dirname, "..", "output", out + ".docx"));
}

module.exports = build;
if (require.main === module) {                                           // command line
  const [prof, cfgPath] = process.argv.slice(2);
  if (!prof) { console.error("usage: node src/resume_form.js <profile.json> [job.json]"); process.exit(1); }
  build(prof, cfgPath ? JSON.parse(fs.readFileSync(cfgPath, "utf-8")) : {});
}
