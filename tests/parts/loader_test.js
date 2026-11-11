// Unit checks of the profile loader (src/profile_loader.js) and the figure templates (src/deck_figures.js).
// No rendering and no model calls: node only, so it runs in a second.
//   node tests/parts/loader_test.js     -> one line per failed check, then "loader tests: N passed, M failed"
const path = require("path");                                            // fixture paths
const G = require("../../src/profile_loader");                          // the loader under test
const CH = require("../../src/deck_figures");                          // the templates under test

let pass = 0, fail = 0;                                                   // counters for the final line
function eq(name, got, want) {                                           // one equality check
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : (fail++, console.log(`FAIL ${name}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`));
}
function throws(name, fn, part) {                                        // a check that must stop with a message containing part
  try { fn(); fail++; console.log(`FAIL ${name}: did not stop`); }
  catch (e) { String(e.message).includes(part) ? pass++ : (fail++, console.log(`FAIL ${name}: stopped with '${e.message}'`)); }
}

// Tenure counts the first and the last month (2026.04 to 2026.08 is five months)
eq("months inclusive", G.monthsBetween("2026.04", "2026.08"), 5);
eq("tenure ko years and months", G.tenureText(27, "ko"), "2년 3개월");
eq("tenure en years and months", G.tenureText(27, "en"), "2 yrs 3 mos");
eq("tenure one year", [G.tenureText(12, "ko"), G.tenureText(12, "en")], ["1년", "1 yr"]);
eq("tenure months only", [G.tenureText(11, "ko"), G.tenureText(1, "en")], ["11개월", "1 mo"]);
eq("tenure unknown", G.monthsBetween("", "2020.01"), null);

// Periods: two-digit years widen, the edition's range mark, a day-level second side inherits the year, lists stay as written
eq("period ko", G.normPeriod("26.04 ~ 26.06", "ko"), "2026.04 ~ 2026.06");
eq("period en", G.normPeriod("26.04 ~ 26.06", "en"), "2026.04 - 2026.06");
eq("period with days", G.normPeriod("22.05.09 ~ 06.10", "ko"), "2022.05 ~ 2022.06");
eq("period single month", G.normPeriod("2023.08", "en"), "2023.08");
eq("period same month twice", G.normPeriod("26.05 ~ 26.05", "ko"), "2026.05");
eq("period list kept", G.normPeriod("2022.03 ~ 2023.01, 2023.02 ~ 2024.02", "ko"), "2022.03 ~ 2023.01, 2023.02 ~ 2024.02");

// Language pairs: picked deeply, a missing language stops with the field path, an explicit null means 'none in this language'
eq("pair picked", G.pickDeep({ a: { ko: "가", en: "A" } }, "en", "x"), { a: "A" });
throws("pair missing language", () => G.pickDeep({ a: { ko: "가" } }, "en", "summary"), "summary.a has no en text");
eq("pair explicit null", G.pickDeep({ info: { ko: "가", en: null } }, "en", "person"), { info: null });
eq("not a pair", G.isPair({ ko: "x", start: "2020" }), false);

// Ledger markdown: comments, prose notes and linked bullets are dropped; tables, captions and plain bullets stay
const blocks = G.mdBlocks("<!-- note -->\nA note for the owner.\n\n## Journals\n| T | Y |\n|---|---|\n| **Paper** | 2021 |\n\n- [press] x — https://e.com\n- a talk");
eq("md blocks", blocks, [{ caption: "Journals" }, { table: { head: ["T", "Y"], rows: [["Paper", "2021"]] } }, { item: "a talk" }]);

// A ledger-form profile (fictional): names, roles, tenure, education and service come out in plain fields
const fx = path.join(__dirname, "fixtures", "export_shape.json");
const ko = G.load(fx, "ko"), en = G.load(fx, "en");
eq("name cleanup", [ko.person.name, ko.person.name_en], ["홍길동", "Gil-Dong Hong"]);
eq("links from keys", ko.person.links.map(l => l[0]), ["LinkedIn"]);
eq("roles newest first", ko.roles.map(r => r.key), ["gasang", "first"]);
eq("role fields ko", [ko.roles[0].org, ko.roles[0].short, ko.roles[0].title, ko.roles[0].dept, ko.roles[0].place, ko.roles[0].period, ko.roles[0].tenure],
  ["가상전자(Example Electronics)", "가상전자", "플랫폼 엔지니어", "플랫폼팀 / 선임", "서울", "2021.03 ~ 2023.04", "2년 2개월"]);
eq("role fields en", [en.roles[0].org, en.roles[0].period, en.roles[0].tenure, en.roles[1].badge], ["Example Electronics", "2021.03 - 2023.04", "2 yrs 2 mos", "Co-founder"]);
eq("total tenure", [ko.total, en.total], ["3년 10개월", "3 yrs 10 mos"]);   // 26 and 20 months
eq("project periods", ko.roles[0].projects.map(p => p.period), ["2021.03 ~ 2022.01", "2022.05 ~ 2022.06"]);
eq("education split", ko.education.map(e => [e.degree, e.school, e.major]), [["석사", "가상대", "컴퓨터공학"], ["박사과정(중퇴)", "가상대", "컴퓨터공학"]]);
eq("withdrawn degree has an open end", ko.education[1].period, "2021.03 ~");
eq("service label", [ko.service.label, en.service.label], ["산업기능요원 복무", "Alternative service"]);
eq("ledger section blocks", ko.sections[0].blocks, [{ table: { head: ["구분", "취득일"], rows: [["가상 자격 1급", "2018.05"]] } }, { item: "가상 강연" }]);
eq("logo ids", [ko.roles[0].logoId, ko.education[0].logoId], ["role_gasang", "edu_ms"]);

// Competencies: evidence ids become short project names; unknown ids stay as written
const comp = G.load(path.join(__dirname, "..", "..", "examples", "sample_full_ko.json"), "ko").competencies;
eq("evidence names", comp[2].evidence, ["주문 이벤트", "조회 캐시"]);

// Figure templates: data checks stop with the field, the drawings are SVG and fit their canvas
throws("bars need numbers", () => CH.check({ type: "bars", rows: [["a", "x"]] }, "f"), "bars rows");
throws("matrix needs one cell per column", () => CH.check({ type: "matrix", cols: ["a", "b"], rows: [["r", "yes"]] }, "f"), "one cell per column");
throws("beforeAfter needs both sides", () => CH.check({ type: "beforeAfter", before: { items: ["a"] } }, "f"), "before.items and after.items");
throws("phases need dates", () => CH.check({ type: "phases", rows: [["a", "soon", "later"]] }, "f"), "YYYY.MM");
for (const [t, f] of Object.entries({
  pipeline: { steps: [["A", "a"], ["B", "b"], ["C", "c"]] }, beforeAfter: { before: { items: ["a"] }, after: { items: ["b", "c"] } },
  bars: { rows: [["a", 1], ["b", 3]] }, matrix: { cols: ["x", "y"], rows: [["r", "yes", "no"]] },
  phases: { rows: [["a", "2020.01", "2020.06"], ["b", "2020.06", "2021.02"]] }, cluster: { groups: [["g", 4], ["h", 2]] },
})) {
  const cut = [], s = CH.TEMPLATES[t]({ type: t, ...f }, 700, 440, cut);
  eq(`${t} draws svg`, /^<svg[^>]*viewBox="0 0 700 \d+(\.\d+)?"/.test(s) && !/NaN|undefined|Infinity/.test(s), true);
  eq(`${t} cuts nothing`, cut, []);
}

// A role the panel's facts wrote: empty dates beside a ledger's career block. The block's end must count, or a finished job prints as still running
{
  const fs = require("fs"), os = require("os");                          // a file for the loader to read
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "offerowl-loader-")), "profile.json");   // removed below
  const career = (key, end) => ({ key, start: "2021.08", end, ko: { name: "에이크미", role: "엔지니어" }, en: { name: "Acme", role: "Engineer" } });   // the ledger's block
  fs.writeFileSync(f, JSON.stringify({ schema: "resume-profile/0.1", person: { name: "가상", name_en: "Ka", email: "ka@example.com" }, roles: [
    { org: "", title: "", start: "", end: "", career: career("done", "2024.02"), projects: [] },   // as the facts write it
    { org: "", title: "", start: "", end: "", career: career("open", null), projects: [] },   // still running, by the block
    { key: "now", org: "Now", title: "T", start: "2025.01", end: null, projects: [] },   // still running, by the role itself
    { key: "own", org: "Then", title: "T", start: "2020.01", end: "2021.01", career: career("own", "1999.01"), projects: [] }] }));   // the role's own date wins over the block
  const rs = Object.fromEntries(G.load(f, "ko", {}).roles.map(r => [r.key, r]));   // through the same reader as the documents, by key
  eq("an empty end leaves the career block's", rs.done.end, "2024.02");
  eq("and the period says it", /2024\.02/.test(String(rs.done.period)), true);
  eq("a career block's null end means ongoing", rs.open.end, null);
  eq("a role's null end means ongoing", rs.now.end, null);
  eq("a role's own end comes first", rs.own.end, "2021.01");
  fs.rmSync(path.dirname(f), { recursive: true, force: true });          // nothing left
}

console.log(`loader tests: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
