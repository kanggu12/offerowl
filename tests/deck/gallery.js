// The figure gallery deck: every template of src/deck_figures.js on a slide of its own, in the light and the dark scheme, at the
// sizes the chapter layout gives it (the main figure 760 x 570 in the left frame, a side figure 470 wide in the right column), so the
// deck's browser probe measures every template exactly where the deck puts it.
//   node tests/deck/gallery.js <ko|en> <out name>   -> output/<out name>_deck.html and <out name>_deck.cut.json
const fs = require("fs");                                         // output files
const path = require("path");                                     // paths
const { Deck, h } = require("../../src/portfolio/deck");          // the slide frame the deck uses
const CH = require("../../src/deck_figures");                   // the templates under test
const G = require("./fixtures/gallery.json");                     // fictional figure data in both languages

const [lang = "ko", out = `deckw_gallery_${lang}`] = process.argv.slice(2);   // the edition and the output name
const figs = G[lang], cut = [];                                   // this edition's figures, the cut notes of every drawing
const SIDE = new Set(["pipeline", "bars", "metric", "columns", "trend", "phases", "cluster"]);   // templates that also fit the side column
// The deck's frame and line balancing, so the probe measures the same layout
const deck = new Deck({ title: "Figure gallery", footer: lang === "en" ? "Figure gallery" : "그림 모음", lang, css: "p, li, .lede, .card p { text-wrap: pretty; }" });
const words = lang === "en" ? { main: "Main figure", side: "Side figure", note: "The same data drawn for the right column" }   // slide captions in the edition's language
                            : { main: "주 그림", side: "곁 그림", note: "같은 데이터를 오른쪽 칸에 맞춰 그림" };   // the Korean edition's words
for (const scheme of ["light", "dark"]) for (const [type, f] of Object.entries(figs)) {   // every template once in light, then every template once in dark
  const main = CH.render(f, 760, 570, cut, { lang, scheme, where: `${type} ${scheme} main` });   // the left frame's figure
  const side = SIDE.has(type) ? CH.render(f, 470, 230, cut, { lang, scheme, where: `${type} ${scheme} side` }) : "";   // the right column's
  deck.add({ part: scheme, company: type },                       // the probe records the scheme as the slide's part and the template as its company
    // The title names the template and scheme; the eyebrow repeats the scheme
    h.sec(`${type}  ${scheme}`, "GALLERY").replace("<!--EYEBROW-->", `<div class="eyebrow"><span>${scheme.toUpperCase()}</span></div>`),
    `<div class="lede">${h.esc(f.caption ? f.caption.replace(/\*\*/g, "") : type)}</div>`,   // the caption as the lede, bold marks removed (the type when it has none)
    h.grid("split-64", "", h.fig(main, { cap: `**${words.main}** 760 x 570` }),   // the chapter layout's split: the main figure in the left frame
      `<div class="stack">${side ? h.fig(side, { natural: true, cap: `**${words.side}** 470 x 230` }) : ""}` +   // right column: the side drawing, when the template has one
      h.card(words.side, side ? words.note : CH.CATALOG[type].use) + `</div>`));   // a card under it as on a project slide; a main-only template shows its catalog use
}
const n = deck.render(path.join(__dirname, "..", "..", "output", `${out}_deck.html`));   // the HTML that run.py prints to PDF and probes
fs.writeFileSync(path.join(__dirname, "..", "..", "output", `${out}_deck.cut.json`), JSON.stringify(cut, null, 1));   // the cut notes; run.py fails the deck when any are present
console.log("slides", n);                                         // the slide count, printed like the deck does
