// The profile loader.
// The resume (resume_form.js), the deck (deck_slides.js) and the figures (overview_figures.py) all read the profile through this
// one module, so the three documents cannot drift apart on names, periods, tenure or logos.
//
// It accepts two shapes of the same schema (resume-profile/0.1):
//   1. the plain fields (docs/DOCUMENTS.md "Profile fields": roles[].org, start, end, projects[].summary ...);
//   2. the ledger form (roles[].career.{start, end, ko, en}, education[].{ko, en}, service.{ko, en},
//      sections[].body_md). The loader turns it into plain fields.
// Any text field may be a language pair { ko, en }; the loader picks the build language and stops when it is missing.
//
//   node src/profile_loader.js <profile.json> [ko|en]     prints the normalized profile as JSON (overview_figures.py reads it)
const fs = require("fs");     // read the profile and probe asset files
const path = require("path"); // resolve asset paths next to the profile

const LANGS = ["ko", "en"];   // the languages a language pair may hold

// True when v is a language pair: a plain object whose keys are all language codes (at least one).
// Objects that merely contain a ko or en key next to other keys (a ledger's career block) are not pairs.
function isPair(v) {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;   // only plain objects can be pairs
  const keys = Object.keys(v);                                          // the object's keys
  return keys.length > 0 && keys.every(k => LANGS.includes(k));         // every key is a language code
}

// Pick the build language out of a value, deeply. Arrays and objects are walked; pairs collapse to one language.
// A pair without the build language stops the build with the field path, so an English edition never silently loses a section.
function pickDeep(v, lang, where) {
  if (isPair(v)) {                                                      // a language pair
    if (!(lang in v)) throw new Error(`${where} has no ${lang} text (translate it or write it in the profile)`);
    return pickDeep(v[lang], lang, where);                              // the chosen text may itself hold nested pairs
  }
  if (Array.isArray(v)) return v.map((x, i) => pickDeep(x, lang, `${where}[${i}]`));   // walk lists
  if (v && typeof v === "object")                                       // walk plain objects key by key
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, pickDeep(x, lang, `${where}.${k}`)]));
  return v;                                                             // strings, numbers, null stay as they are
}

// Year-month to a fractional year: '2022.03', '2022-03', '2022/3', '2022년 3월', '2022'. NaN when unreadable.
function ym(s) {
  const m = String(s || "").match(/((?:19|20)\d{2})(?:\s*[.\-/년]\s*(\d{1,2}))?/);   // year and optional month
  if (!m) return NaN;                                                    // not a date
  const mon = m[2] && +m[2] >= 1 && +m[2] <= 12 ? +m[2] : 1;             // month, January when missing or invalid
  return +m[1] + (mon - 1) / 12;                                         // fractional year
}

// Months between two year-months, counting both the first and the last month.
// end null means the role is ongoing, so it counts up to the current month.
function monthsBetween(start, end) {
  const a = ym(start);                                                   // start as a fractional year
  const now = new Date();                                                // today for ongoing roles
  const b = end === null ? now.getFullYear() + now.getMonth() / 12 : ym(end);   // end, or this month when ongoing
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return null;  // unknown or reversed periods have no tenure
  return Math.round((b - a) * 12) + 1;                                   // inclusive month count
}

// Tenure text: '2년 3개월' or '2 yrs 3 mos'. One month short of a year still reads in months
function tenureText(months, lang) {
  if (!months) return "";                                                // no tenure for unknown periods
  const y = Math.floor(months / 12), m = months % 12;                    // whole years and leftover months
  if (lang === "en") {                                                   // English abbreviations
    const ys = y ? `${y} ${y === 1 ? "yr" : "yrs"}` : "", ms = m ? `${m} ${m === 1 ? "mo" : "mos"}` : "";
    return [ys, ms].filter(Boolean).join(" ");
  }
  return [y ? `${y}년` : "", m ? `${m}개월` : ""].filter(Boolean).join(" ");   // Korean years and months
}

// Normalize one side of a period: 'YY.MM' becomes '20YY.MM', a full 'YYYY.MM(.DD)' keeps year and month.
// prevYear lets a short second side 'MM.DD' (after a first side with a day) inherit the first side's year.
function normSide(s, prevYear, firstHadDay) {
  const t = String(s || "").trim();                                      // the side as text
  let m = t.match(/^((?:19|20)\d{2})[.\-/](\d{1,2})(?:[.\-/]\d{1,2})?$/); // four-digit year form
  if (m) return { text: `${m[1]}.${m[2].padStart(2, "0")}`, year: m[1], day: /[.\-/]\d{1,2}[.\-/]\d{1,2}$/.test(t) };
  m = t.match(/^(\d{2})[.\-/](\d{1,2})([.\-/]\d{1,2})?$/);               // two-part or three-part short form
  if (m && firstHadDay && prevYear && !m[3]) return { text: `${prevYear}.${m[1].padStart(2, "0")}`, year: prevYear, day: true };   // MM.DD
  if (m) return { text: `20${m[1]}.${m[2].padStart(2, "0")}`, year: `20${m[1]}`, day: !!m[3] };   // YY.MM(.DD)
  m = t.match(/^((?:19|20)\d{2})$/);                                     // a bare year
  if (m) return { text: m[1], year: m[1], day: false };
  return { text: t, year: prevYear, day: false };                        // anything else is shown as written
}

// Normalize a period string like '26.04 ~ 26.06' or '2023.08' and join with the language's range mark
// (Korean '~', English '-')
function normPeriod(p, lang) {
  if (!p) return "";                                                     // no period
  if (/,/.test(String(p))) return String(p);                             // several ranges are already written out; keep them as given
  const parts = String(p).split(/\s*[~–—]\s*|\s+-\s+/);       // split on the range mark
  const a = normSide(parts[0], null, false);                             // first side
  const out = [a.text];                                                  // normalized sides
  if (parts.length > 1) out.push(normSide(parts[1], a.year, a.day).text);   // second side may inherit the year
  if (out.length === 2 && out[0] === out[1]) out.pop();                  // '2026.05 ~ 2026.05' reads as one month
  return out.join(lang === "en" ? " - " : " ~ ");                        // the edition's range mark
}

// A role or education period from start and end: end null means ongoing ('재직 중' or 'Present'), an empty or missing end means unknown
function periodOf(start, end, lang, nowWord) {
  if (!start) return "";                                                 // nothing known
  const mark = lang === "en" ? " - " : " ~ ";                            // range mark of the edition
  return (normSide(start).text + mark + (end === null ? nowWord : end ? normSide(end).text : "")).trimEnd();   // an open end reads '2023.03 ~'
}

// Resolve an asset path written in the profile: absolute, next to the profile, or under the repository root
function asset(p, profileDir) {
  if (!p || typeof p !== "string") return null;                          // no asset given
  const tries = [p, path.join(profileDir, p), path.join(__dirname, "..", p)];   // the places an asset may live
  return tries.find(x => path.isAbsolute(x) && fs.existsSync(x)) || null;   // the first that exists
}

// A logo spec: an image path, or a monogram { text, color } that overview_figures.py draws as a tile
function logoSpec(v, key, assets, profileDir) {
  if (v && typeof v === "object" && v.text) return { monogram: String(v.text), color: v.color || null };   // drawn initials
  const file = asset(typeof v === "string" ? v : null, profileDir) ||   // an explicit image path
    (assets.logos && key ? ["png", "jpg", "jpeg", "webp"].map(e => asset(path.join(assets.logos, `${key}.${e}`), profileDir)).find(Boolean) : null);   // a logo folder keyed by role
  return file ? { file } : null;                                         // no logo when nothing was found
}

// Split a ledger-style education title 'Degree  School' (two spaces) into its two parts
function splitTitle(t) {
  const parts = String(t || "").split(/\s{2,}/);                         // a ledger separates with two spaces
  return parts.length > 1 ? { degree: parts[0], school: parts.slice(1).join(" ") } : { degree: "", school: parts[0] || "" };
}

// Person name cleanup: a ledger may write '홍 길 동 (Gil-Dong Hong)'. Single Hangul syllables spaced apart are joined,
// and a Latin name in parentheses becomes name_en when the profile does not give one
function cleanName(name, nameEn) {
  let n = String(name || "").trim(), en = nameEn || "";                   // the name as written and the English name
  const m = n.match(/^(.*?)\s*\(([A-Za-z][A-Za-z .,'-]+)\)$/);           // 'Name (Latin Name)'
  if (m) { n = m[1].trim(); en = en || m[2].trim(); }                    // split off the Latin name
  if (/^[가-힣](\s[가-힣])+$/.test(n)) n = n.replace(/\s/g, "");          // '홍 길 동' to '홍길동'
  return { name: n, name_en: en };
}

// Markdown body of a ledger section to blocks: tables (head and rows), bullet items and sub captions.
// HTML comments, prose notes and links are dropped: a ledger section holds notes for its owner that must not reach a resume
function mdBlocks(md) {
  const text = String(md || "").replace(/<!--[\s\S]*?-->/g, "");         // drop comments first (they may span lines)
  const blocks = [];                                                     // the blocks in reading order
  let table = null;                                                      // the table being collected
  const cells = ln => ln.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim().replace(/\*\*(.+?)\*\*/g, "$1").replace(/`/g, ""));   // a table row's cells
  for (const ln of text.split("\n")) {                                   // line by line
    if (/^\s*\|/.test(ln)) {                                             // a table line
      const c = cells(ln);
      if (c.every(x => /^:?-{2,}:?$/.test(x))) continue;                 // the separator row
      if (!table) { table = { head: c, rows: [] }; blocks.push({ table }); }   // the first line is the head
      else table.rows.push(c);                                           // later lines are rows
      continue;
    }
    table = null;                                                        // any other line ends the table
    const h = ln.match(/^#{2,4}\s+(.+)$/);                               // a sub heading
    if (h) { blocks.push({ caption: h[1].trim() }); continue; }
    const b = ln.match(/^\s*[-*]\s+(.+)$/);                              // a bullet item
    if (b && !/https?:\/\//.test(b[1])) blocks.push({ item: b[1].replace(/\*\*(.+?)\*\*/g, "$1").replace(/`/g, "") });   // linked items (press lists) are dropped
  }
  return blocks.filter(x => !x.table || x.table.rows.length);            // tables without rows say nothing
}

// Competencies: [head, body] pairs or { name, text, evidence: [project ids or names] }.
// Evidence names the projects behind a competency, in parentheses at the end of the line (four to six
// competencies, each line with its evidence projects)
function competencies(list, projectIndex) {
  return (list || []).map((c, i) => {
    if (Array.isArray(c)) return { name: c[0], text: c[1] || "", evidence: [] };   // the older pair form
    if (!c || !c.name) throw new Error(`competencies[${i}] needs name`);   // an unnamed competency cannot be ordered or weakened
    const ev = (c.evidence || []).map(e => {                              // evidence ids become short project names
      const p = projectIndex[e];                                          // a project id written in the profile
      return p ? (p.short || p.title) : String(e);                        // otherwise the evidence is a name already
    });
    return { name: c.name, text: c.text || "", evidence: ev };
  });
}

// Load and normalize a profile for one language. cfg is the job config (out name, language)
function load(profilePath, lang = "ko", cfg = {}) {
  const raw = JSON.parse(fs.readFileSync(profilePath, "utf-8"));        // the profile as written
  if (raw.schema !== "resume-profile/0.1") throw new Error("unknown profile schema: " + raw.schema);
  if (!LANGS.includes(lang)) throw new Error("lang must be ko or en");
  const dir = path.dirname(path.resolve(profilePath));                   // assets resolve next to the profile
  const nowWord = lang === "en" ? "Present" : "재직 중";                  // the ongoing end of a role
  const assets = raw.assets || {};                                       // asset folders (logos, photo)

  // Person: name and contacts. The ledger form keeps LinkedIn and Scholar as separate keys; they become links
  const P0 = pickDeep(raw.person || {}, lang, "person");
  const nm = cleanName(P0.name, P0.name_en);
  const links = [...(P0.links || [])];                                   // [label, shown text, address]
  for (const [k, label] of [["linkedin", "LinkedIn"], ["github", "GitHub"], ["scholar", "Scholar"], ["homepage", "Web"]])
    if (P0[k] && !links.some(l => l[0] === label)) links.push([label, String(P0[k]).replace(/^https?:\/\/(www\.)?/, ""), P0[k]]);
  const person = { ...P0, ...nm, links };
  for (const k of ["name", "email"]) if (!person[k]) throw new Error("person." + k + " is missing");

  // Summary blocks shared by the resume and the deck (one source so the two documents say the same thing)
  const S = pickDeep(raw.summary || {}, lang, "summary");

  // Roles: plain fields first, a ledger's career block fills what is missing
  const roles = (raw.roles || []).filter(r => r && (r.org || r.career)).map((r0, ri) => {
    const c = r0.career || {};                                           // a ledger's career block (may be absent)
    const cl = c[lang] || {};                                            // its language half
    const full = c.full ? (c.full[lang] || {}) : {};                     // a longer job title some roles carry
    const r = pickDeep({ ...r0, career: undefined, projects: undefined, context: undefined }, lang, `roles[${ri}]`);   // the role's own text fields
    const key = r.key || c.key || `role${ri + 1}`;                       // a stable key for logos and chapters
    // null end means ongoing, and an empty one says nothing: the panel's facts write "" beside a ledger's career block, whose end must still count
    const start = r.start || c.start || "", end = r.end === null ? null : (r.end || ("end" in c ? c.end : ""));
    const months = monthsBetween(start, end);                            // inclusive tenure in months
    const projects = (r0.projects || []).filter(p0 => !p0.lang || p0.lang === lang).map((p0, pi) => {   // a project written for one language prints in that edition only
      const p = pickDeep(p0, lang, `roles[${ri}].projects[${pi}]`);      // the project's text fields
      return { ...p, id: p.id || `${key}-${pi + 1}`, period: normPeriod(p.period, lang),   // periods read the same everywhere
        logo: p0.logo ? logoSpec(p0.logo, null, assets, dir) : null };   // a client logo for the deck's title plate
    });
    return {
      ...r, key, start, end, months,
      org: r.org || cl.name || r.heading || key,                         // the shown company name
      short: r.short || cl.short || r.org || cl.name || key,             // a short name for evidence, rails and timeline
      title: r.title || cl.role || c.title || "",                        // the role shown in tables and bands
      titleLong: r.titleLong || (full.role) || c.title || r.title || cl.role || "",   // the long title (export: English job title)
      dept: r.dept || cl.dept || "", place: r.place || cl.place || "",
      enName: r.enName || (c.en && c.en.name) || "",                     // the English company name a Korean chapter divider shows under the name
      chart: r.chart || (cfg.titleView === "full" && full.chart) || cl.chart || r.title || cl.role || "",   // the timeline's sub label (cfg.titleView "full" reads the long one)
      badge: "badge" in r ? (r.badge || "") : cl.badge || "",            // a small mark next to the name (co-founder and the like); an empty one written in the profile hides the career's
      note: r.note || "",                                                // a grey second line under the name in the career table
      period: periodOf(start, end, lang, nowWord),                       // the shown period
      tenure: cfg.tenure === false ? "" : tenureText(months, lang),      // the shown tenure
      logo: logoSpec(r0.logo, key, assets, dir),                         // the company logo (image or monogram)
      logoId: "role_" + String(key).replace(/[^\w-]/g, "_"),            // the tile name overview_figures.py writes
      projects,
    };
  });
  // Newest first (by start); equal starts keep the written order
  roles.sort((a, b) => (ym(b.start) || 0) - (ym(a.start) || 0));

  // Project index for evidence lookups (ids and titles)
  const projectIndex = {};
  for (const r of roles) for (const p of r.projects) { projectIndex[p.id] = p; projectIndex[p.title] = p; }

  // Education: plain fields, or the ledger form's { key, start, end, logo, ko: { title, sub, chart } }
  const education = (raw.education || []).map((e0, i) => {
    const el = e0[lang] || {};                                           // the ledger's language half
    const e = pickDeep({ ...e0, ko: undefined, en: undefined }, lang, `education[${i}]`);
    const t = splitTitle(el.title);                                      // 'Degree  School' from a ledger
    // A bar that fades out (an unfinished degree) has no end date and is not ongoing: show the start only, like '2023.03 ~'
    const fadeTo = e.fadeTo || e0.chart_fade_to || null, end = fadeTo && e.end === null ? "" : e.end;
    return {
      ...e,
      school: e.school || t.school, degree: e.degree || t.degree,
      major: e.major || el.sub || "", sub: e.sub || "", majorSub: e.majorSub || "", note: e.note || "",
      chart: e.chart || el.chart || [e.degree || t.degree, e.school || t.school].filter(Boolean).join("  "),
      chartTitle: e.chartTitle || el.title || "", chartSub: e.chartSub || el.sub || "",   // the timeline's own labels (shorter than the table)
      timeline: e.timeline !== false,                                    // false keeps an entry (high school) off the timeline
      chartShort: e.chartShort || el.chart_short || "", fadeTo, end,
      period: periodOf(e.start, end, lang, lang === "en" ? "Present" : "재학 중"),
      logo: logoSpec(e0.logo, typeof e0.logo === "string" && !/[./]/.test(e0.logo) ? e0.logo : e0.key, assets, dir),
      logoId: "edu_" + String(e0.key || i + 1).replace(/[^\w-]/g, "_"),   // the tile name overview_figures.py writes
    };
  }).filter(e => e.school || e.degree);                                  // an entry with neither says nothing

  // Service (military or similar): { label, start, end } or the ledger form's { start, end, ko: { chart } }
  let service = null;
  if (raw.service && typeof raw.service === "object") {
    const s0 = raw.service, sl = s0[lang] || {};
    const s = pickDeep({ ...s0, ko: undefined, en: undefined }, lang, "service");
    service = { label: s.label || sl.chart || "", start: s.start, end: s.end };
  }

  // Sections: item lists, dated lines, tables, groups of those, or a ledger markdown body (tables and bullets only).
  // cfg.sections (a list of titles) picks and orders them; a ledger body is skipped when the profile marks it resume: false
  let sections = (raw.sections || []).filter(s0 => !s0.lang || s0.lang === lang).map((s0, i) => {   // a section written for one language prints in that edition only
    const s = pickDeep(s0, lang, `sections[${i}]`);
    const some = a => (Array.isArray(a) && a.length ? a : null);         // an empty list is no list: it must not hide the ledger body
    const out = { title: s.title, title_en: s.title_en || "", items: some(s.items), lines: some(s.lines),
      head: s.head || null, rows: some(s.rows), groups: some(s.groups), widths: s.widths || null, align: s.align || null,
      note: s.note || null, resume: s.resume !== false };
    if (!out.items && !out.lines && !out.rows && !out.groups && s.body_md) out.blocks = mdBlocks(s.body_md);   // ledger body
    return out;
  });
  const skillsLike = /^(기술\s*스택|기술|보유\s*기술|skills?|technical skills|tech stack)$/i;   // a section that repeats the skills table
  if (!Array.isArray(cfg.sections) && (raw.skills || []).length)          // no pick: the skills table already says it once
    sections = sections.filter(s => !skillsLike.test(String(s.title || "").trim()));
  if (Array.isArray(cfg.sections)) {                                     // the job picks sections by title
    const unknown = cfg.sections.filter(t => !sections.some(s => s.title === t));
    if (unknown.length) throw new Error("cfg.sections names sections the profile does not have: " + unknown.join(", "));
    sections = cfg.sections.map(t => sections.find(s => s.title === t));
  }

  return {
    lang, person, summary: S, roles, education, service,
    skills: pickDeep((raw.skills || []).filter(s0 => !s0 || !s0.lang || s0.lang === lang), lang, "skills"),   // a row written for one language prints in that edition only
    sections,
    competencies: competencies(pickDeep(raw.competencies || [], lang, "competencies"), projectIndex),
    about: pickDeep(raw.about || [], lang, "about"),
    motivation: pickDeep(raw.motivation || null, lang, "motivation"),
    motivationTitle: pickDeep(raw.motivationTitle || null, lang, "motivationTitle"),   // the person's own name for the last section ("커리어 목표" in a general edition)
    motivationTitleEn: raw.motivationSub || pickDeep(raw.motivationTitle || null, "en", "motivationTitle"),   // the section's small English subtitle: written, or the English name
    totalMonths: roles.reduce((a, r) => a + (r.months || 0), 0),         // the sum shown next to the career summary title
    total: tenureText(roles.reduce((a, r) => a + (r.months || 0), 0), lang),
    projectIndex,
  };
}

module.exports = { load, pickDeep, isPair, ym, monthsBetween, tenureText, normPeriod, mdBlocks };
if (require.main === module) {                                           // command line: print the normalized profile
  const [prof, lang, cfgPath] = process.argv.slice(2);
  if (!prof) { console.error("usage: node src/profile_loader.js <profile.json> [ko|en] [job.json]"); process.exit(1); }
  const cfg = cfgPath ? JSON.parse(fs.readFileSync(cfgPath, "utf-8")) : {};   // the edition's choices the loader reads (titleView, tenure)
  const out = load(prof, lang || "ko", cfg);
  delete out.projectIndex;                                               // the index repeats projects; the figures do not need it
  process.stdout.write(JSON.stringify(out));
}
