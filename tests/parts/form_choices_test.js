// The layout choices an edition can carry (resume_form.js): the plain look, the older footer and the section names. Built in
// process from the fictional example into a scratch folder, and read back from the Word file's XML.
//   node tests/parts/form_choices_test.js     -> one line per failed check, then "form choices tests: N passed, M failed"
const fs = require("fs");                                                // the scratch folder
const os = require("os");                                                // where it goes
const path = require("path");                                            // fixture paths
const JSZip = require("jszip");                                          // a Word file is a zip
let pass = 0, fail = 0;                                                  // the counts
function ok(name, good, detail = "") {                                   // one check
  if (good) { pass++; return; }                                          // quiet when it holds
  fail++;                                                                // counted
  console.log(`FAIL ${name}${detail ? ": " + detail : ""}`);             // and said
}
const PROFILE = path.join(__dirname, "..", "..", "examples", "sample_ko.json");   // the fictional person
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), "owl-form-"));         // layout.js writes here when OFFEROWL_OUT is set
process.env.OFFEROWL_OUT = OUT;                                          // never into output/

// one edition in a fresh process state: layout.js keeps its look in module variables, so each build loads it anew
async function build(cfg) {
  for (const k of Object.keys(require.cache)) if (k.includes(path.join("src", ""))) delete require.cache[k];   // a fresh layout
  const form = require("../../src/resume_form");                         // the form under test
  await form(PROFILE, { lang: "ko", out: cfg.out, ...cfg });             // writes <out>.docx into OUT
  for (let i = 0; i < 50 && !fs.existsSync(path.join(OUT, cfg.out + ".docx")); i++) await new Promise(r => setTimeout(r, 100));   // the file is written when the packer is done
  const zip = await JSZip.loadAsync(fs.readFileSync(path.join(OUT, cfg.out + ".docx")));   // the Word file
  const body = await zip.file("word/document.xml").async("string");      // its body
  const footers = await Promise.all(Object.keys(zip.files).filter(f => /^word\/footer\d*\.xml$/.test(f)).map(f => zip.file(f).async("string")));
  return { body, footer: footers.join("") };
}

(async () => {
  const full = await build({ out: "choices_full" });                     // the default look
  const plain = await build({ out: "choices_plain", plain: true, footerLabel: "경력기술서" });   // the plain look, the older footer
  ok("the default look names its sections in English too", full.body.includes("OVERVIEW") || full.body.includes("CAREER SUMMARY"));
  ok("the plain look leaves the English names out", !plain.body.includes("CAREER SUMMARY") && !plain.body.includes("OVERVIEW"));
  ok("the default section title has its accent bar", /<w:left w:val="single" w:color="[0-9A-F]{6}" w:sz="36"/i.test(full.body));
  ok("the plain look has no accent bar", !/<w:left w:val="single" w:color="[0-9A-F]{6}" w:sz="36"/i.test(plain.body));
  ok("the older footer says the document kind", plain.footer.includes("경력기술서"));
  ok("the name footer does not", !full.footer.includes("경력기술서"));
  // The selected-project cards' row labels and the department line under a company band: a set that names cardLabel and subLine
  // (crimson, whose dark accent is black) prints them in its own tone; a set that names neither keeps its dark accent there
  const colourOf = (xml, text) => {                                      // the colour of the first run that holds exactly this text
    const m = new RegExp("<w:r>(?:(?!</w:r>).)*?<w:color w:val=\"([0-9A-Fa-f]{6})\"/>(?:(?!</w:r>).)*?<w:t[^>]*>" + text + "</w:t></w:r>", "s").exec(xml);
    return m ? m[1].toUpperCase() : null;
  };
  const sample = JSON.parse(fs.readFileSync(PROFILE, "utf8"));           // the fictional person, for a label and a department line
  const label = sample.summary.highlights[0].rows[0][0];                 // the first card's first row label
  const r0 = sample.roles[0], subLine = [[r0.dept, r0.title].filter(Boolean).join(" / "), r0.context].filter(Boolean).join(", ");   // as resume_form.js writes it
  const crimson = await build({ out: "choices_crimson", theme: "crimson" });
  const navy = await build({ out: "choices_navy", theme: "navy" });
  const sets = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "src", "themes.json"), "utf8"));   // the colour sets as shipped
  ok("a set that names cardLabel prints the card labels in it", colourOf(crimson.body, label) === sets.crimson.cardLabel, String(colourOf(crimson.body, label)));
  ok("a set that names subLine prints the department line in it", colourOf(crimson.body, subLine) === sets.crimson.subLine, String(colourOf(crimson.body, subLine)));
  ok("a set that names neither keeps its dark accent on the card labels", colourOf(navy.body, label) === sets.navy.acc, String(colourOf(navy.body, label)));
  ok("and on the department line", colourOf(navy.body, subLine) === sets.navy.acc, String(colourOf(navy.body, subLine)));
  fs.rmSync(OUT, { recursive: true, force: true });                      // nothing left behind
  console.log(`form choices tests: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log("FAIL " + e.stack); process.exit(1); });
