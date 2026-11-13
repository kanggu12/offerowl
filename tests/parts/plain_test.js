// The plain resume (src/resume_plain.js): one column, no table and no picture, with every project the typeset resume prints.
//   node tests/parts/plain_test.js     -> one line per failed check, then "plain tests: N passed, M failed"
const path = require("path");                                            // fixture paths
const JSZip = require("jszip");                                          // a Word file is a zip
const { Packer } = require("docx");                                      // writes it
const G = require("../../src/profile_loader");                           // the same loader as the documents
const P = require("../../src/resume_plain");                             // the module under test
let pass = 0, fail = 0;                                                  // the counts
function ok(name, good, detail = "") {                                   // one check
  if (good) { pass++; return; }                                          // quiet when it holds
  fail++;                                                                // counted
  console.log(`FAIL ${name}${detail ? ": " + detail : ""}`);             // and said
}

(async () => {
  for (const lang of ["ko", "en"]) {                                     // both editions of the fictional person
    const file = path.join(__dirname, "..", "..", "examples", `sample_full_${lang}.json`);   // the example
    const prof = G.load(file, lang, {}), lines = P.linesOf(prof), text = P.textOf(lines);   // its words
    const printed = prof.roles.flatMap(r => r.projects.filter(p => p.resume !== false));   // what the typeset resume prints
    ok(`${lang}: the name comes first`, lines[0][0] === "name" && lines[0][1].includes(lang === "en" ? prof.person.name_en : prof.person.name), lines[0][1]);
    ok(`${lang}: the contacts are text`, text.includes(prof.person.email));   // a reader finds them
    ok(`${lang}: every printed project is there`, printed.every(p => text.includes(String(p.title).replace(/==|\*\*/g, ""))));
    ok(`${lang}: a project kept off the resume is not`, prof.roles.flatMap(r => r.projects.filter(p => p.resume === false)).every(p => !text.includes(p.title)));
    ok(`${lang}: no highlight marks`, !/==|\*\*/.test(text));         // marks are for the typeset resume
    ok(`${lang}: every role and its dates`, prof.roles.every(r => text.includes(r.org) && text.includes(r.period)));
    ok(`${lang}: every skill`, prof.skills.every(s => s.items.every(i => text.includes(i))));
    const zip = await JSZip.loadAsync(await Packer.toBuffer(P.docOf(lines, lang)));   // the Word file
    const xml = await zip.file("word/document.xml").async("string");     // its body
    ok(`${lang}: no table`, !xml.includes("<w:tbl>"));                   // the reader of a file loses the order of a table
    ok(`${lang}: no picture`, !xml.includes("<w:drawing>") && !Object.keys(zip.files).some(f => f.startsWith("word/media/")));
    ok(`${lang}: real headings`, /w:pStyle w:val="Heading1"/.test(xml));   // what such a reader looks for
    ok(`${lang}: the same words as the text file`, printed.every(p => xml.includes(String(p.title).replace(/==|\*\*/g, "").replace(/&/g, "&amp;"))));
  }
  const shaped = P.linesOf({ lang: "en", person: { name: "A", email: "a@example.com" }, summary: {}, roles: [], skills: [{ category: "Other", items: ["x"] }, { category: "Asked", items: ["y"] }],
    competencies: [{ name: "Weak", text: "w", evidence: [] }, { name: "Gone", text: "g", evidence: [] }, { name: "Strong", text: "s", evidence: ["P"] }], education: [{ school: "S", sub: "Sub", major: "M", majorSub: "MS", period: "2000" }],
    service: { label: "Army", start: "2001.01", end: "2002.01" }, sections: [{ resume: true, title: "T", items: ["i"], note: "A note" }],
    about: [["Title", ["One.", "Two."]], { quote: "Boxed", text: "Box text" }], motivation: ["From the profile."] },
  { competencyWeak: ["Weak"], competencyDrop: ["Gone"], skillsFocus: ["Asked"], motivation: ["For this job.", "And more."] }).map(l => l[1]);   // every other shape the profile can hold
  const at = t => shaped.findIndex(x => x.includes(t));                  // where a word stands
  ok("a job's strong competency comes first, with its projects", at("Strong: s (P)") >= 0 && at("Strong") < at("Weak"));
  ok("a dropped competency is gone", at("Gone") < 0);
  ok("a job's skills come first", at("Asked: y") < at("Other: x"));
  ok("education has its second lines", shaped.includes("S | Sub | M | MS | 2000"), JSON.stringify(shaped));
  ok("service has its dates", shaped.includes("Army | 2001.01 ~ 2002.01"));
  ok("a section's note is there", at("A note") >= 0);
  ok("about's paragraphs stay apart", shaped.includes("One.") && shaped.includes("Two.") && at("One.,") < 0);
  ok("a boxed statement is there", shaped.includes("Boxed") && shaped.includes("Box text"));
  ok("the job's motivation replaces the profile's", shaped.includes("For this job.") && shaped.includes("And more.") && at("From the profile") < 0);
  const order = [...G.load(path.join(__dirname, "..", "..", "examples", "sample_full_ko.json"), "ko", {}).roles[0].projects].reverse().map(p => p.id);   // a job's order, the other way round
  const prof = G.load(path.join(__dirname, "..", "..", "examples", "sample_full_ko.json"), "ko", { projectOrder: order });   // read for that job
  const titles = P.linesOf(prof, { projectOrder: order }).map(l => l[1]);   // its lines
  const firstIn = id => titles.findIndex(t => t.startsWith(String(prof.projectIndex && prof.roles[0].projects.find(p => p.id === id).title)));   // where a project stands
  ok("a job's order counts", firstIn(order[0]) < firstIn(order[1]), `${firstIn(order[0])} ${firstIn(order[1])}`);   // the first it asks for comes first
  console.log(`plain tests: ${pass} passed, ${fail} failed`);            // the summary line
  process.exit(fail ? 1 : 0);                                            // for the runner
})();
