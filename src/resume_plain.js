// The resume as plain words, for a job site that reads a file by itself or asks you to paste: one column, no table, no picture,
// and the same sentences as the typeset resume. It writes a Word file and a text file.
//   node src/resume_plain.js <profile.json> [job.json]   -> output/<out>_plain.docx and output/<out>_plain.txt
// The job file's lang and projectOrder count, as they do for the typeset resume.
const fs = require("fs");                          // the files
const path = require("path");                      // their folder
const { Document, HeadingLevel, Packer, Paragraph, TextRun } = require("docx");   // a Word file with real headings, which such a reader looks for
const G = require("./profile_loader");             // one profile loader for every document

// The headings in the edition's language
const WORDS = { ko: { overview: "개요", highlights: "대표 프로젝트", competencies: "핵심 역량", work: "경력", education: "학력", service: "병역", skills: "보유 기술", about: "자기소개", motivation: "지원 동기" },
                en: { overview: "Overview", highlights: "Selected projects", competencies: "Core competencies", work: "Experience", education: "Education", service: "Military service", skills: "Skills", about: "About me", motivation: "Motivation" } };
const plain = s => (Array.isArray(s) ? s.map(plain).filter(Boolean).join(" ") : String(s == null ? "" : s).replace(/==|\*\*/g, "").replace(/\s+/g, " ").trim());   // a text, or its paragraphs, without marks, on one line
const cell = c => plain(c && typeof c === "object" ? c.t : c);     // a table cell is a text, or an object that holds one
const joined = (...parts) => parts.map(plain).filter(Boolean).join(" | ");   // what is there, on one line
// A summary's sentences, one per line: a reader of a file keeps a bullet's words together
const sentences = s => plain(s).split(/(?<=[.!?])\s+/).filter(Boolean);

// A section's body, whichever of the profile's shapes it has: bullets, dated lines, a table, groups or blocks
function bodyLines(s) {
  const out = [];                                  // [kind, text]
  for (const it of s.items || []) out.push(["bullet", plain(it)]);   // bullets
  for (const l of s.lines || []) out.push(["bullet", joined(...[].concat(l))]);   // [main, org, date]
  for (const r of s.rows || []) out.push(["bullet", joined(...r.map(cell))]);   // a table's rows, without its head: a row's words say what they are
  for (const b of s.blocks || []) {                // a ledger's mixed blocks
    if (b.caption) out.push(["sub", plain(b.caption)]);   // a caption over what follows
    else if (b.table) for (const r of b.table.rows || []) out.push(["bullet", joined(...r.map(cell))]);   // its table's rows
    else out.push(["bullet", plain(b.item || "")]);   // one line
  }
  if (s.note) out.push(["text", plain(s.note)]);   // a note under a list
  return out.filter(([, t]) => t);                 // nothing empty
}

// The whole resume as lines: [kind, text], kind one of name, head, sub, text, bullet
function linesOf(prof, cfg = {}) {
  const W = WORDS[prof.lang === "en" ? "en" : "ko"], P = prof.person, S = prof.summary || {};   // the words, the person, the top
  const order = cfg.projectOrder || [];            // the job's order first, the rest as written, as on the typeset resume
  const ordered = ps => [...ps].map((p, i) => [p, i]).sort((x, y) => {
    const a = order.indexOf(x[0].id), b = order.indexOf(y[0].id);   // where the job puts each
    return (a < 0 ? 1e9 : a) - (b < 0 ? 1e9 : b) || x[1] - y[1];   // listed ones first, in the listed order
  }).map(x => x[0]);
  const out = [["name", prof.lang === "en" && P.name_en ? plain(P.name_en) : joined(P.name, P.name_en && P.name_en !== P.name ? P.name_en : "")]];   // the edition's name, and in Korean the English one beside it
  if (P.tagline) out.push(["text", plain(P.tagline)]);   // the line under the name
  out.push(["text", joined(P.phone, P.email, P.location, ...(P.links || []).map(l => (Array.isArray(l) ? l[1] : l)))]);   // the contacts, as text a reader can find
  if (S.headline) out.push(["text", plain(S.headline)]);   // what the person does
  if (S.intro) out.push(["text", plain(S.intro)]);   // who the person is
  const cards = S.cards || [];                     // the overview cards: [label, text]
  if (cards.length) {                              // what the person seeks and has
    out.push(["head", W.overview]);                // their heading
    for (const c of cards) out.push(["bullet", `${plain(c[0])}: ${plain(c[1])}`]);   // label and text
  }
  const lights = S.highlights || [];               // the selected projects: { title, where, rows: [[label, text]] }
  if (lights.length) {                             // the ones the top of the resume names
    out.push(["head", W.highlights]);              // their heading
    for (const h of lights) {                      // each one
      out.push(["sub", joined(h.title, h.where)]);   // its name and place
      for (const r of h.rows || []) out.push(["bullet", `${plain(r[0])}: ${joined(r[1], r[2])}`]);   // problem, what was done, result
    }
  }
  const weak = cfg.competencyWeak || [], drop = cfg.competencyDrop || [];   // the job's two layers, as on the typeset resume
  const comps = (prof.competencies || []).filter(c => !drop.includes(c.name));   // what stays
  if (comps.length) {                              // core competencies
    out.push(["head", W.competencies]);            // their heading
    for (const c of [...comps.filter(x => !weak.includes(x.name)), ...comps.filter(x => weak.includes(x.name))])   // the ones the job asks for first
      out.push(["bullet", `${plain(c.name)}: ${plain(c.text)}${(c.evidence || []).length ? ` (${c.evidence.map(plain).join(", ")})` : ""}`]);   // name, text and the projects it rests on
  }
  out.push(["head", W.work]);                      // the work history, newest first
  for (const r of prof.roles) {                    // each job
    out.push(["sub", joined(r.org, r.titleLong || r.title, r.dept, r.place, r.period + (r.tenure ? ` (${r.tenure})` : ""))]);   // what, where and when
    if (r.desc) out.push(["text", plain(r.desc)]);   // the company in a line
    for (const p of ordered((r.projects || []).filter(x => x.resume !== false))) {   // the projects the resume prints
      out.push(["text", joined(p.title, p.period)]);   // its name and dates
      for (const x of sentences(p.summary)) out.push(["bullet", x]);   // what was done
    }
  }
  if ((prof.education || []).length) {             // education
    out.push(["head", W.education]);               // its heading
    for (const e of prof.education) out.push(["bullet", joined(e.school, e.sub, e.major, e.majorSub, e.degree, e.period, e.note)]);   // a line per school
  }
  if (prof.service && prof.service.label) {        // military service, where it counts
    out.push(["head", W.service]);                 // its heading
    const s = prof.service;                        // its label and dates
    out.push(["bullet", joined(s.label, [s.start, s.end].filter(Boolean).join(" ~ "))]);   // one line
  }
  if ((prof.skills || []).length) {                // skills
    out.push(["head", W.skills]);                  // its heading
    const focus = cfg.skillsFocus || [];           // the categories the job asks for come first, in its order
    const rows = [...focus.map(f => prof.skills.find(s => s.category === f)).filter(Boolean), ...prof.skills.filter(s => !focus.includes(s.category))];   // then the rest
    for (const s of rows) out.push(["bullet", `${plain(s.category)}: ${(s.items || []).map(plain).join(", ")}`]);   // a category and its names
  }
  for (const s of prof.sections || []) {           // the other sections
    if (!s.resume) continue;                       // the profile marks those that stay out of resumes
    out.push(["head", plain(s.title)]);            // its own heading
    for (const g of s.groups || []) {              // groups under it
      out.push(["sub", plain(g.title)]);           // the group's heading
      out.push(...bodyLines(g));                   // its lines
    }
    out.push(...bodyLines(s));                     // or its own lines
  }
  if ((prof.about || []).length) {                 // about me
    out.push(["head", W.about]);                   // its heading
    for (const a of prof.about) {                  // [title, text or paragraphs], or a boxed { quote, text }
      out.push(["sub", plain(Array.isArray(a) ? a[0] : a.quote)]);   // its title
      for (const b of [].concat(Array.isArray(a) ? a[1] : a.text)) out.push(["text", plain(b)]);   // each paragraph
    }
  }
  const motive = cfg.motivation || prof.motivation;   // the job's own first: it differs per application
  if (motive) {                                    // motivation
    out.push(["head", W.motivation]);              // its heading
    for (const b of [].concat(motive)) out.push(["text", plain(b)]);   // each paragraph
  }
  return out.filter(([, t]) => t);                 // nothing empty
}

// The text file: a blank line before each heading, and a dash that pastes into any form
const textOf = lines => lines.map(([k, t]) => (k === "head" ? `\n${t}` : k === "sub" ? `\n${t}` : k === "bullet" ? `- ${t}` : t)).join("\n").trim() + "\n";

// The Word file: real headings and real bullets, in one column and one font
function docOf(lines, lang) {
  const font = lang === "en" ? "Arial" : "Malgun Gothic";   // on every PC that opens Word, so no reader has to substitute it
  const run = (text, o = {}) => new TextRun({ text, font, size: 21, ...o });   // 10.5 pt
  const kids = lines.map(([k, t]) => {             // one paragraph per line
    if (k === "name") return new Paragraph({ heading: HeadingLevel.TITLE, children: [run(t, { size: 32, bold: true })] });   // the document's title
    if (k === "head") return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 80 }, children: [run(t, { size: 24, bold: true })] });   // a section
    if (k === "sub") return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 160, after: 40 }, children: [run(t, { bold: true })] });   // a job or a group
    if (k === "bullet") return new Paragraph({ bullet: { level: 0 }, children: [run(t)] });   // a real list item
    return new Paragraph({ spacing: { after: 60 }, children: [run(t)] });   // a line of text
  });
  return new Document({ sections: [{ children: kids }] });   // no table, no picture, no text box
}

async function build(profilePath, cfgPath) {       // both files of one edition
  const cfg = cfgPath ? JSON.parse(fs.readFileSync(cfgPath, "utf-8")) : {};   // the job's settings
  const lang = cfg.lang || "ko";                   // the edition
  const lines = linesOf(G.load(profilePath, lang, cfg), cfg);   // the words
  const out = path.join(__dirname, "..", "output", (cfg.out || path.basename(profilePath, ".json")) + "_plain");   // beside the other documents
  fs.mkdirSync(path.dirname(out), { recursive: true });   // output/ may be new
  fs.writeFileSync(out + ".txt", textOf(lines));   // the text
  fs.writeFileSync(out + ".docx", await Packer.toBuffer(docOf(lines, lang)));   // the Word file
  return out;                                      // where they went
}

module.exports = { linesOf, textOf, docOf };       // for the tests

if (require.main === module) {                     // run as a program
  build(process.argv[2], process.argv[3]).then(out => console.log(out), e => { console.error(e.message); process.exit(1); });   // a bad profile says why
}
