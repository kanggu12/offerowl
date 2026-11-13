// The cover letter renderer: one profile file plus one cover JSON (written by `cover.py draft`) in, one
// DOCX out. The PDF comes from the same LibreOffice step as the resume (`cover.py build` runs both inside the container).
//
//   node src/cover_form.js <profile.json> <cover.json> [job.json] [--density N]
//
// job.json keys (all optional):
//   out       name of the output file, written to output/<out>.docx (default: the cover file's name without .json)
//   lang      "ko" or "en"; the cover file's own lang when absent
//   theme     colour set from src/themes.json (default navy, like the resume)
//   tagline   line under the name; the cover file's job.tagline, then person.tagline when absent
//   person    fields that replace profile.person for this letter only (name, name_en, email, phone, links, location, tagline);
//             a replaced name also becomes the signature
//   signature the signature line itself (the cover file's signature, then the header name, when absent)
//   photo     { file, w, layout } exactly as the resume takes it; letters normally go without one
//   density   0, 1 or 2: how tightly the paragraphs are spaced. 0 is the default spacing; the build
//             step tries the next level only when the letter spills onto a second page
//
// It uses the same header (L.fheader) and the same prose paragraph (L.prose) as the resume, so the letter and the
// resume of one application read as one set. Nothing here makes up text: every word comes from the cover JSON.
const fs = require("fs");       // reads the profile and the cover JSON
const path = require("path");   // builds the output path
const L = require("./layout");  // the layout engine the resume uses, so header and prose match it exactly

// Words the letter itself supplies. The model never writes these, so they live here in both languages.
const LABEL = {
  ko: {
    footer: "자기소개서",                                            // footer text after the name
    salutation: c => (c ? `${c} 채용 담당자님께,` : "채용 담당자님께,"), // greeting line; names the company only when the posting did
    closing: "감사합니다.",                                           // line above the signature
    phone: "연락처", email: "이메일", location: "거주지",             // contact labels in the header
  },
  en: {
    footer: "Cover Letter",                                          // footer text after the name
    salutation: c => (c ? `Dear ${c} Hiring Team,` : "Dear Hiring Team,"), // greeting line
    closing: "Sincerely,",                                           // line above the signature
    phone: "Phone", email: "Email", location: "Location",            // contact labels in the header
  },
};

// Spacing per density level, in twips.
const DENSITY = [
  { after: 140, salBefore: 260, salAfter: 160, closeBefore: 200 },  // level 0: the default spacing
  { after: 110, salBefore: 220, salAfter: 120, closeBefore: 160 },  // level 1: a little tighter, for letters a few lines too long
  { after: 80, salBefore: 180, salAfter: 100, closeBefore: 120 },   // level 2: the tightest; a letter longer than this must be shortened
];

// Joins the sentences of one paragraph into the text that goes on the page.
function paragraphText(par, where) {
  // A paragraph may carry a ready `text`, or a list of sentence objects, or a list of plain strings.
  if (typeof par.text === "string" && par.text.trim()) return par.text.trim();   // a ready paragraph text wins
  const sents = (par.sentences || [])                                             // otherwise join the sentences
    .map(s => (typeof s === "string" ? s : s && s.text) || "")                    // each may be a string or an object with text
    .map(s => s.trim()).filter(Boolean);                                          // trim and drop empty ones
  if (!sents.length) throw new Error(`${where} has no sentences`); // an empty paragraph would print a blank gap, so stop
  return sents.join(" ").replace(/==/g, ""); // highlight marks belong to the resume, never to a letter
}

function build(profilePath, coverPath, cfg = {}) {
  const prof = JSON.parse(fs.readFileSync(profilePath, "utf-8")); // the person's profile
  const cover = JSON.parse(fs.readFileSync(coverPath, "utf-8"));  // the drafted letter
  if (!/^(resume|offerowl)-profile\//.test(String(prof.schema))) throw new Error("unknown profile schema: " + prof.schema); // refuse files this renderer cannot read (the profile schema may be renamed)
  if (cover.schema !== "offerowl-cover/0.1") throw new Error("unknown cover schema: " + cover.schema); // same for the letter
  const lang = cfg.lang || cover.lang || "ko";                    // the language of the labels and of the header order
  const T = LABEL[lang];                                          // labels for that language
  if (!T) throw new Error("lang must be ko or en");               // any other language has no labels here
  const dens = DENSITY[cfg.density === undefined ? 0 : cfg.density]; // spacing level
  if (!dens) throw new Error("density must be 0, 1 or 2");        // an unknown level would otherwise fail later with a vague error
  const P = { ...(prof.person || {}), ...(cfg.person || {}) };    // per-letter overrides win over the profile
  for (const k of ["name", "email"]) if (!P[k]) throw new Error("person." + k + " is missing"); // the header needs both
  if (!Array.isArray(cover.paragraphs) || !cover.paragraphs.length) throw new Error("the cover file has no paragraphs"); // nothing to print

  L.setFont("Pretendard");                                        // same font as the resume
  L.setTheme(cfg.theme || "navy");                                // same colour set as the resume (OFFEROWL_THEME still wins)
  L.setLangKo(lang === "ko");                                     // Korean runs get the ko-KR language tag
  // English letters put the English name first, Korean letters the Korean name, as the resume does.
  const [N1, N2] = lang === "en" && P.name_en ? [P.name_en, P.name] : [P.name, P.name_en || ""];
  L.setDocMeta({ title: `${N1} ${lang === "ko" ? "자기소개서" : "Cover Letter"}`, author: N1 });   // the file's title and author, never its build name
  L.setFooterLabel(N1 + "  " + T.footer);                         // footer: name and document kind, then the page number

  const contacts = [];                                            // right-hand block of the header
  if (P.location) contacts.push([T.location, P.location]);        // place first
  if (P.phone) contacts.push([T.phone, P.phone]);                 // the phone only when the person gave one
  contacts.push([T.email, P.email, "mailto:" + P.email]);         // the email is always there and always a link
  for (const l of P.links || []) contacts.push(l);                // [label, shown text, address]
  const tagline = cfg.tagline || (cover.job || {}).tagline || P.tagline || ""; // line under the name
  const ch = [].concat(L.fheader(N1, N2, tagline, contacts, cfg.photo || null)); // same header as the resume (a table, or table plus tape)

  const company = (cover.job || {}).company || "";                // the greeting names the company when the posting did
  ch.push(L.p(cover.salutation || T.salutation(company), { size: 21, bold: true, color: L.INK, before: dens.salBefore, after: dens.salAfter })); // greeting
  cover.paragraphs.forEach((par, i) => ch.push(L.prose(paragraphText(par, `paragraph ${par.id || i + 1}`), { after: dens.after, line: 264 }))); // body, one paragraph each
  ch.push(L.p(cover.closing || T.closing, { size: 19, color: L.INK, before: dens.closeBefore, after: 40 })); // closing line
  // The signature is the cover file's, unless the job file replaces the person: then the replaced name is the one on the header and here too.
  const signature = cfg.signature || (cfg.person && (cfg.person.name || cfg.person.name_en) ? N1 : cover.signature) || N1;
  ch.push(L.p(signature, { size: 21, bold: true, color: L.INK, after: 0 })); // signature line

  const out = cfg.out || path.basename(coverPath, ".json");       // output name, also used by the build step
  L.render(ch, path.join(__dirname, "..", "output", out + ".docx")); // writes the DOCX (and the sidecar files the checks read)
}

module.exports = build;                                           // other scripts may call it directly
if (require.main === module) {                                    // command line use
  const args = process.argv.slice(2);                             // drop node and the script name
  const di = args.indexOf("--density");                           // optional spacing override
  const density = di >= 0 ? Number(args.splice(di, 2)[1]) : undefined; // remove the flag and its value from the positionals
  const [prof, cover, cfgPath] = args;                            // what is left: profile, cover, optional job file
  if (!prof || !cover) { console.error("usage: node src/cover_form.js <profile.json> <cover.json> [job.json] [--density N]"); process.exit(1); } // both inputs are required
  const cfg = cfgPath ? JSON.parse(fs.readFileSync(cfgPath, "utf-8")) : {}; // render settings, when given
  if (density !== undefined) cfg.density = density;               // the flag wins over the file
  build(prof, cover, cfg);                                        // render
}
