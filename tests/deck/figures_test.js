// Unit checks of the figure library (src/deck_figures.js): every template in both languages and both schemes at the sizes the deck
// uses draws a clean SVG (no NaN or 'undefined', the static audit finds nothing, nothing cut), bad data stops with the field named,
// over-long text is shortened and reported instead of overflowing, and the catalog covers every template. Node only, no browser.
//   node tests/deck/figures_test.js     -> one line per failed check, then "figure tests: N passed, M failed"
const CH = require("../../src/deck_figures");                   // the library under test
const G = require("./fixtures/gallery.json");                     // fictional figure data in both languages

let pass = 0, fail = 0;                                           // counters for the final line
function ok(name, cond, detail = "") {                            // one check
  cond ? pass++ : (fail++, console.log(`FAIL ${name}${detail ? ": " + detail : ""}`));   // a failure prints its name and detail; passes stay quiet
}
function throws(name, fn, part) {                                 // a check that must stop with a message containing part
  try { fn(); fail++; console.log(`FAIL ${name}: did not stop`); }   // returning normally is a failure
  catch (e) { String(e.message).includes(part) ? pass++ : (fail++, console.log(`FAIL ${name}: stopped with '${e.message}'`)); }   // it must stop for the expected reason, not just any error
}

// Every template, every edition, both schemes, at the main, wide and side sizes it is drawn at
const SIDE = new Set(["pipeline", "bars", "metric", "columns", "trend", "phases", "cluster"]);   // the templates that fit the side column
for (const lang of ["ko", "en"]) for (const [type, f] of Object.entries(G[lang])) for (const scheme of ["light", "dark"]) {   // every template in each edition and scheme
  const sizes = [[760, 570], ...(type === "panels" ? [] : [[700, 488]]), ...(SIDE.has(type) ? [[470, 230]] : [])];   // main; wide unless a composite; side for the side templates
  for (const [W, H] of sizes) {                                   // each size the deck draws it at
    const where = `${type} ${lang} ${scheme} ${W}x${H}`, cut = [];   // names the case in failures; its own cut list
    let svg = "";                                                 // the drawing, if it draws
    // The data check and the drawing must both go through
    try { CH.check(f, where); svg = CH.render(f, W, H, cut, { lang, scheme }); } catch (e) { ok(`${where} draws`, false, e.message); continue; }
    const vb = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);       // the canvas the deck places
    ok(`${where} canvas`, vb && +vb[1] === W && +vb[2] <= H && +vb[2] > 40, vb ? vb.slice(1).join("x") : "no viewBox");   // full width, no taller than the frame, not collapsed
    ok(`${where} values`, !/NaN|undefined|Infinity|\[object/.test(svg));   // broken data shows up as these words in the markup
    ok(`${where} described`, /role="img"[^>]*aria-label="[^"]+"/.test(svg) && new RegExp(`data-figure="${type}`).test(svg));   // a label for readers (CONTRIBUTING.md), the template named
    const issues = CH.audit(svg);                                 // the static layout audit
    ok(`${where} audit`, !issues.length, issues.slice(0, 3).join("; "));   // no text outside, over text or across a box edge
    ok(`${where} nothing cut`, !cut.length, cut.slice(0, 2).join("; "));   // the fixture data fits without shortening
    // Dark paints its page and uses the dark arrowheads
    if (scheme === "dark") ok(`${where} dark page and arrows`, /fill="#0F1722"/.test(svg) && (!/marker-end/.test(svg) || /url\(#ah-d/.test(svg)));
    if (scheme === "light") ok(`${where} light arrows`, !/url\(#ah-d/.test(svg));   // light never borrows a dark arrowhead
  }
}

// Kinds carry meaning only with a legend: a figure that uses one draws its word, a default look draws none
const arch = CH.render(G.en.architecture, 760, 570, [], { lang: "en" });
ok("legend names the kinds used", ["My part", "Data", "External"].every(w => arch.includes(`>${w}<`)));   // the kinds the architecture fixture uses
const pipe = CH.render(G.en.pipeline, 760, 570, [], { lang: "en" });   // a figure with no kinds in its data
ok("no legend without kinds", !/My part|Core/.test(pipe));        // the default outcome color adds no legend
ok("legend words follow the edition", CH.render(G.ko.architecture, 760, 570, [], { lang: "ko" }).includes(">맡은 부분<"));   // the Korean word for my part
// A figure's legend field renames a kind
ok("legend words can be renamed", CH.render({ ...G.en.architecture, legend: { mine: "Rebuilt by me" } }, 760, 570, [], { lang: "en" }).includes(">Rebuilt by me<"));

// Natural heights: a short figure ends under its content, a composite fills its frame
const natural = svg => +svg.match(/viewBox="0 0 [\d.]+ ([\d.]+)"/)[1];
ok("short figures end under their content", natural(CH.render(G.en.metric, 760, 570, [], {})) < 400 && natural(pipe) < 300);   // a metric and a one-row pipeline trim their canvas
ok("panels fill the frame", natural(CH.render(G.en.panels, 760, 570, [], {})) === 570);   // a composite keeps the full frame height
ok("panels carry figure-to-card marks", (CH.render(G.en.panels, 760, 570, [], {}).match(/data-badge="mark"/g) || []).length === 3);   // the fixture's three panels each carry a badge

// Over-long text is shortened and reported, never drawn past its box
const longCut = [], longSvg = CH.render({ type: "pipeline", steps: [["A very long step name that cannot possibly fit one narrow box in a six step row", "note"], ["B"], ["C"], ["D"], ["E"], ["F"]] }, 470, 230, longCut, {});
ok("long text is reported", longCut.length > 0);                  // shortening is never silent
ok("long text stays inside", !CH.audit(longSvg).length, CH.audit(longSvg).join("; "));   // the shortened text fits its box
const hangul = [], hsvg = CH.render({ type: "bars", rows: [["띄어쓰기없이아주길게이어지는막대이름이라칸을넘는경우", 3], ["짧은 이름", 1]] }, 470, 230, hangul, {});   // one long Korean word with no space to break at
ok("a long word without spaces is shortened by characters", hangul.length > 0 && !CH.audit(hsvg).length);   // trimmed letter by letter, and it fits

// A room too narrow for one letter and the ellipsis gets nothing, never text wider than the room
ok("fit never returns text wider than its room", CH.fit("Long label", 10.5, false, 6, [], "x") === "" && CH.fit("Label", 10.5, false, 200, [], "x") === "Label");

// Pipelines: a band may start on a later row of the snake, and a short frame keeps the steps on one row
const bandFig = { type: "pipeline", steps: [["Collect", "logs"], ["Check rule", "per type"], ["Fix", "script"], ["Report", "form"], ["Review", "weekly"]], groups: [["First", 0, 1], ["Later", 3, 4]] };
const bandCut = [], bandSvg = CH.render(bandFig, 470, 300, bandCut, { lang: "en" });   // two rows at the side width
ok("a band on the second row is drawn", !bandCut.length && />Later</.test(bandSvg) && />First</.test(bandSvg), bandCut.join("; "));   // both bands, nothing reported
ok("a band on the second row draws clean", !CH.audit(bandSvg).length, CH.audit(bandSvg).join("; "));   // no text outside, over text or across an edge
const short = { type: "pipeline", steps: [["Audit", "dashboards", "mine"], ["Revive", "panels", "mine"], ["Repair", "alerts", "mine"], ["Alert", "blind spots", "key"]] };   // four steps with kinds and a legend
const shortCut = [], shortSvg = CH.render(short, 470, 120, shortCut, { lang: "en" });   // a side room of 120 px
const shortH = +shortSvg.match(/viewBox="0 0 [\d.]+ ([\d.]+)"/)[1];   // the height it drew to
ok("a short frame keeps the steps on one row", !shortCut.length && shortH <= 120 && !CH.audit(shortSvg).length, `${shortH} ${shortCut.join("; ")} ${CH.audit(shortSvg).join("; ")}`);
const tall = CH.render(short, 470, 400, [], { lang: "en" });      // the same steps with room for the snake
ok("a tall frame still snakes", +tall.match(/viewBox="0 0 [\d.]+ ([\d.]+)"/)[1] > shortH);   // two rows of wider boxes are taller

// Phases: a note that fits neither inside nor after its bar goes before it when there is more room there
const late = { type: "phases", rows: [["Plan", "2024.01", "2024.02"], ["Run", "2024.11", "2024.12", "A long note that cannot fit after its bar"]] };
const lateCut = [], lateSvg = CH.render(late, 470, 160, lateCut, { lang: "en" });   // the last bar ends at the frame's edge
ok("a phase note goes before a late bar", !lateCut.length && /text-anchor="end"[^>]*>A long note/.test(lateSvg) && !CH.audit(lateSvg).length, lateCut.join("; "));

// Architecture: links into one node get their own end points, and a link to an unknown node is reported
const fan = { type: "architecture", zones: [{ title: "A", nodes: [{ id: "a1", title: "One" }, { id: "a2", title: "Two" }, { id: "a3", title: "Three" }] }, { title: "B", nodes: [{ id: "b", title: "Hub", sub: "Many inputs" }] }],
  links: [["a1", "b"], ["a2", "b"], ["a3", "b"], ["a1", "nowhere"]] };   // three links into one node and one to a missing id
const fanCut = [], fanSvg = CH.render(fan, 760, 570, fanCut, {});   // drawn with its own cut list
const tips = [...fanSvg.matchAll(/<path d="M[^"]* L([\d.]+),([\d.]+)"[^>]*marker-end/g)].map(m => +m[2]);   // the end height of every arrow
ok("incoming links do not share an end point", new Set(tips.map(v => Math.round(v))).size === tips.length, tips.join(","));   // every arrow ends at its own height
ok("links to unknown nodes are reported", fanCut.some(c => /unknown nodes/.test(c)));   // the missing id is named, not drawn
// Four links into a one-line node: the node grows so each arrow keeps its own point
const fan4 = { type: "architecture", zones: [{ title: "A", nodes: ["One", "Two", "Three", "Four"].map(t => ({ id: t, title: t })) }, { title: "B", nodes: [{ id: "hub", title: "Hub" }] }],
  links: ["One", "Two", "Three", "Four"].map(t => [t, "hub"]) };
const fan4Cut = [], fan4Svg = CH.render(fan4, 760, 570, fan4Cut, {});   // drawn with its own cut list
ok("a node grows for the links that reach one side", !fan4Cut.length && !CH.audit(fan4Svg).length, fan4Cut.join("; "));

// Bad data stops with the field named
throws("bars need numbers", () => CH.check({ type: "bars", rows: [["a", "x"]] }, "f"), "bars rows");
throws("matrix needs one cell per column", () => CH.check({ type: "matrix", cols: ["a", "b"], rows: [["r", "yes"]] }, "f"), "one cell per column");   // a short row would leave cells undrawn
throws("beforeAfter needs both sides", () => CH.check({ type: "beforeAfter", before: { items: ["a"] } }, "f"), "before.items and after.items");   // a side with no items has nothing to draw
throws("phases need dates", () => CH.check({ type: "phases", rows: [["a", "soon", "later"]] }, "f"), "YYYY.MM");   // a start that is not a date has no place on the axis
// A period that ends before it starts has a negative width
throws("timeline ends after it starts", () => CH.check({ type: "timeline", phases: [["a", "2024.05", "2024.01"]] }, "f"), "end not before");
// More rows than this do not fit the frame
throws("gantt rows are capped", () => CH.check({ type: "gantt", groups: [{ name: "g", tasks: Array(16).fill(["t", "2024.01", "2024.02"]) }] }, "f"), "sixteen rows");
// Links find nodes by id, so ids must not repeat
throws("architecture ids are unique", () => CH.check({ type: "architecture", zones: [{ title: "a", nodes: [{ id: "x", title: "x" }] }, { title: "b", nodes: [{ id: "x", title: "y" }] }] }, "f"), "unique");
throws("rack units are capped", () => CH.check({ type: "rack", racks: [{ name: "r", units: Array(13).fill(["u"]) }] }, "f"), "one to twelve units");   // more units than this crowd the rack
throws("metric needs two numbers", () => CH.check({ type: "metric", rows: [["m", 1]] }, "f"), "metric rows");   // a metric is a before and an after value
throws("columns need one value per series", () => CH.check({ type: "columns", series: ["a", "b"], groups: [["g", 1]] }, "f"), "one per value");   // each group needs one value per named series
throws("trend needs one value per point", () => CH.check({ type: "trend", x: ["a", "b"], series: [["s", [1]]] }, "f"), "one value per x label");   // each line needs one value per x label
throws("tree needs children", () => CH.check({ type: "tree", root: ["r"] }, "f"), "root and children");   // a root alone is not a hierarchy
throws("panels do not nest", () => CH.check({ type: "panels", panels: [{ figure: { type: "panels", panels: [] } }] }, "f"), "not another panels");   // a panel inside a panel is refused
throws("panel figures are checked", () => CH.check({ type: "panels", panels: [{ figure: { type: "bars", rows: [] } }] }, "f"), "rows is empty");   // a panel's figure gets its own type's checks
throws("unknown types stop", () => CH.check({ type: "pie" }, "f"), "unknown figure type");   // a type the library cannot draw

// The catalog the drafting step and docs/DOCUMENTS.md use covers every template, and every example shape parses
ok("catalog covers every template", Object.keys(CH.TEMPLATES).every(t => CH.CATALOG[t]) && Object.keys(CH.CATALOG).every(t => CH.TEMPLATES[t]));
ok("catalog shapes are JSON", Object.values(CH.CATALOG).every(c => { try { JSON.parse(c.shape); return true; } catch { return false; } }));   // the prompt shows these shapes, so they must parse

console.log(`figure tests: ${pass} passed, ${fail} failed`);      // the summary line run.py reads
process.exit(fail ? 1 : 0);                                       // a failure fails the run
