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
  fs.rmSync(OUT, { recursive: true, force: true });                      // nothing left behind
  console.log(`form choices tests: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log("FAIL " + e.stack); process.exit(1); });
