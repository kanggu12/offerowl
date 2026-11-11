// Offerowl's panel, part 4: the inspector beside the canvas. Five tabs: the evidence of the selected sentence (with
// edit, regenerate from the evidence and lock), the fit to the job in view, the style of the documents, their colour
// theme, and the history of changes (undo back to any point).
"use strict";                                                                       // catches undeclared names and silent writes early

const TABS = [["evidence", "Evidence"], ["fit", "Fit"], ["style", "Style"], ["theme", "Theme"], ["history", "History"]];  // the inspector's tabs

function drawInspector(el) {                                                        // the whole inspector
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": t("Inspector") },
    TABS.map(([k, w]) => h("button", { role: "tab", id: "itab-" + k, "aria-selected": UI.tab === k ? "true" : "false", "aria-controls": "ipanel", tabindex: UI.tab === k ? "0" : "-1",
      onclick: () => { UI.tab = k; render(); }, onkeydown: tabKeys, text: t(w) })),
    h("button", { class: "btn quiet iconbtn insp-close", "aria-label": t("Close the inspector"), onclick: () => { UI.drawer = false; render(); } }, icon("close")));
  const panel = h("div", { id: "ipanel", role: "tabpanel", "aria-labelledby": "itab-" + UI.tab, style: "display:grid;gap:14px" },
    ({ evidence: inspEvidence, fit: inspFit, style: inspStyle, theme: inspTheme, history: inspHistory }[UI.tab] || inspEvidence)());   // a tab no longer there shows the evidence
  fill(el, tabs, panel);                                                            // drawn
  el.classList.toggle("open", UI.drawer);                                           // the drawer on narrow windows
  el.setAttribute("aria-label", t("Inspector"));                                    // named for screen readers
}
function tabKeys(e) {                                                               // arrows move between tabs
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;          // only these keys
  e.preventDefault();                                                               // no scrolling
  const i = TABS.findIndex(([k]) => k === UI.tab);                                  // the open tab
  const n = e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;  // the next one
  UI.tab = TABS[n][0]; render();                                                    // opened
  const b = $("itab-" + UI.tab); if (b) b.focus();                                  // the keyboard follows
}

// ---------------------------------------------------------------- evidence

function inspEvidence() {                                                           // the selected sentence and where it came from
  const coverDoc = UI.doc === "cover";                                              // the cover letter has sentences and evidence of its own
  const m = coverDoc ? coverModel() : resumeModel();                                // the document in view (the deck prints the resume's sentences)
  if (coverDoc && !jobId()) return [h("div", { class: "ins-sec" }, h("h3", { text: t("A cover letter is written for one job") }))];   // the general edition has none
  if (coverDoc && m && m.state === "none") return [h("div", { class: "ins-sec" }, h("h3", { text: t("Evidence") }),   // nothing to count yet (the page beside says there is no letter)
    h("p", { class: "hint", text: t("Its sentences and the evidence of each show here once it is written.") }))];
  const counts = (m && m.counts) || {};                                             // its totals
  const rec = UI.sel ? sentenceOf(UI.sel) : null;                                   // the selected sentence
  if (ownFileIn(edition(), UI.doc)) return [h("div", { class: "ins-sec" }, h("h3", { text: t("Your own file") }),   // a document the person made: no sentence of Offerowl's to trace
    h("p", { class: "hint", text: t("This document is the file you brought in, shown and exported as it is. Evidence is shown for the editions Offerowl writes.") }))];
  const src = m && !coverDoc ? sourcesOf(m) : [];                                   // the document's sources (the resume's files; a letter cites facts sentence by sentence)
  const sources = src.length ? h("div", { class: "ins-sec" }, h("h3", { text: t("Sources of this document") }),   // what it was retrieved from
    // the files, each with a file sign (the numbers after the sentences count the facts they rest on, not these files)
    h("ol", { class: "srclist" }, src.map((x) => h("li", {}, h("span", { class: "srcn", "aria-hidden": "true" }, icon(x.typed ? "edit" : "file", 13)),
      h("span", { class: "nm", text: x.file }), h("span", { class: "hint", text: tn(x.n, "{n} sentence", "{n} sentences") }))))) : null;
  if (!rec) return [sources, h("div", { class: "ins-sec" }, h("h3", { text: t("Click a sentence to see its evidence") })),
    m && m.draft && m.draft.counts && m.draft.at ? h("div", { class: "ins-sec" }, h("p", { class: "hint", text: t("Written by the agent on {at}: {n} texts, {r} rewritten after a check stopped them, {d} dropped.", { at: m.draft.at, n: m.draft.counts.written || 0, r: m.draft.counts.rewritten || 0, d: m.draft.counts.dropped || 0 }) }),
      agentOn() && edition() ? h("div", {}, h("button", { class: "btn small", onclick: () => writeResume(edition().id), text: t("Write it again") })) : null) : null,
    m && m.counts && m.counts.sentences ? segBar([{ n: m.counts.sentences - (m.counts.unsupported || 0), words: t("With evidence"), color: "var(--violet-bar)" },   // the document's sentences by their evidence, in the chain's own colours (Make)
      { n: m.counts.unsupported || 0, words: t("Without evidence"), color: "var(--red-bar)" }], { label: t("Sentences"), id: "ev", compact: true }) : null,
    m && m.counts ? h("dl", { class: "kv" }, h("dt", { text: t("Sentences") }), h("dd", { text: String(counts.sentences || 0) }),
      counts.edited !== undefined ? [h("dt", { text: t("Edited by you") }), h("dd", { text: String(counts.edited) })] : null,   // the resume counts these; a letter does not
      counts.locked !== undefined ? [h("dt", { text: t("Locked") }), h("dd", { text: String(counts.locked) })] : null,
      h("dt", { text: t("Without evidence") }), h("dd", {}, counts.unsupported ? h("button", { class: "btn small", onclick: selectNextBad, text: t("{n}: show the first", { n: counts.unsupported }) }) : "0")) : null];
  const cover = UI.sel.startsWith("cover.");                                        // a cover letter sentence
  const st = { ok: ["ok", "As your evidence says"], typed: ["pc", "Your own words"], edited: ["pc", "Edited, still within the evidence"], unsupported: ["bad", "No evidence for this"] }[rec.state] || ["off", ""];
  const regen = task("regen:" + UI.sel);                                            // a regeneration of this sentence
  const busy = regen.state === "running";                                           // the agent is writing it
  const editor = UI.editing ? h("form", { style: "display:grid;gap:8px", onsubmit: (e) => { e.preventDefault(); saveSentence(e.target.elements.s.value); } },
    ...sentenceEditor(rec.text),
    h("div", { class: "ev-actions" }, h("button", { class: "btn primary small", type: "submit", text: t("Save") }), h("button", { class: "btn small", type: "button", onclick: () => { UI.editing = false; forget("sentence-edit"); render(); }, text: t("Cancel") }))) : null;
  return [
    h("div", { class: "ins-sec" }, h("div", { class: "ev-state" }, pill(st[0], t(st[1])), rec.locked ? h("span", { class: "chip" }, icon("lock", 12), t("Locked")) : null,
      rec.drafted ? h("span", { class: "chip ai", text: t("Written by the agent") }) : rec.kind ? h("span", { class: "chip", text: t(KIND[rec.kind] || "Other") }) : null),
      UI.editing ? editor : h("p", { class: "ev-sentence" }, marks(rec.text, "hl")),
      (rec.issues || []).length ? h("ul", { class: "band issues" }, rec.issues.map((i) => { const why = t(ISSUE[i.code] || ISSUE.other, { w: i.words, said: i.said || "" }); return h("li", { text: why.charAt(0).toUpperCase() + why.slice(1) }); })) : null),   // a list item starts as a sentence does
    cover || UI.editing ? null : h("div", { class: "ev-actions" },
      h("button", { class: "btn small", disabled: rec.locked || null, onclick: () => { UI.editing = true; render(); const f = document.querySelector('[data-key="sentence-edit"]'); if (f) f.focus(); }, text: t("Edit") }),
      h("button", { class: "btn small", disabled: rec.locked || busy || null, onclick: () => regenerate(UI.sel), text: busy ? t("Writing…") : t("Regenerate from the evidence") }),
      ...[["shorter", "Shorter"], ["plainer", "Plainer"], ["result", "Result first"]].map(([way, w]) =>   // a direction picked with one press, never typed
        h("button", { class: "btn small", disabled: rec.locked || busy || null, onclick: () => regenerate(UI.sel, way), text: t(w) })),
      h("button", { class: "btn small", "aria-pressed": rec.locked ? "true" : "false", onclick: () => act("/api/v1/sentences/lock", { sid: UI.sel, locked: !rec.locked, lang: docLang(), job: jobId() }, rec.locked ? t("Unlocked.") : t("Locked: Edit and Regenerate leave it alone.")) },
        icon("lock", 13), rec.locked ? t("Unlock") : t("Lock"))),
    cover ? null : sendNote(t("Regenerating sends this sentence's evidence to the agent.")),
    regen.state === "error" ? band(regen.error.code, { retry: () => regenerate(UI.sel) }) : null,
    h("div", { class: "ins-sec" }, h("h3", { text: t("Evidence") }),
      (rec.evidence || []).length ? h("div", { class: "ev-list" }, rec.evidence.map((e) => e.where === "details" ? h("div", { class: "note", text: t("You wrote this in Your details.") })
        : h("div", { class: "note ev-note" }, m && evidenceIndex(m).has(evKey(e)) ? h("span", { class: "evn", text: String(evidenceIndex(m).get(evKey(e))) }) : null,   // the number the canvas shows
          h("q", {}, evidenceQuote(e.quote, rec.text)),
          h("span", { class: "from", text: [e.where && e.where !== "profile" ? bars(e.where) : "", e.file ? t("From {file}", { file: e.file }) : ""].filter(Boolean).join(", ") }))))
        : h("p", { class: "hint", text: t("No fact backs this sentence. Edit it to say what your evidence says, regenerate it, or add the fact to your profile.") })),
  ];
}
// the sentence's words, a key that highlights the chosen ones (kept as ==...==, never typed), and how it reads: the marks the
// documents keep are never shown as raw characters
function sentenceEditor(text) {
  const view = h("p", { class: "md-preview", "aria-live": "polite" }, marks(text, "hl"));   // drawn as the page draws it
  const box = h("textarea", { name: "s", "data-key": "sentence-edit", rows: 4, "aria-label": t("Your wording"), oninput: (e) => view.replaceChildren(...marks(e.target.value, "hl")) }, text);
  const mark = h("button", { class: "btn sm", type: "button", title: t("Highlight the chosen words"), onclick: () => {   // a key with its rim: beside the field's name it read as a second name
    const a = box.selectionStart, b = box.selectionEnd;                             // the chosen words
    if (a === b) { toast(t("Choose the words to highlight first.")); return; }
    box.value = box.value.slice(0, a) + "==" + box.value.slice(a, b) + "==" + box.value.slice(b);
    box.dispatchEvent(new Event("input")); box.focus();
  } }, t("Highlight"));
  return [h("div", { class: "field" }, h("span", { class: "rich-head" }, h("span", { text: t("Your wording") }), mark), box),
    h("span", { class: "md-label", text: t("How it reads") }), view,
    h("p", { class: "hint", text: t("A number, tool or name that the evidence does not have stops the export.") })];
}
const bars = (s) => String(s || "").replace(/\s+\|\s+/g, " · ");                 // a unit's fields joined by bars (the form the model reads) shown as the profile shows them, with middle dots
function evidenceQuote(quote, sentence) {                                           // the quote with the sentence's own words on the highlighter
  const words = new Set(unmarked(sentence).split(/[\s,.;:()·]+/).filter((w) => w.length >= 2));  // the sentence's words
  return bars(unmarked(quote)).split(/(\s+)/).map((w) => {                         // each word of the quote, its marks dropped
    const bare = w.replace(/[,.;:()·]+$/g, "");                                     // without its punctuation
    return words.has(bare) || [...words].some((x) => x.length >= 3 && bare.startsWith(x.slice(0, -1))) ? h("mark", { text: w }) : document.createTextNode(w);  // shared words marked
  });
}
async function saveSentence(text) {                                                 // the edit form to the server
  const r = await act("/api/v1/sentences/edit", { sid: UI.sel, text, lang: docLang(), job: jobId() });  // checked against the evidence there
  if (!r) return;                                                                   // refused: the toast says why
  UI.editing = false; forget("sentence-edit");                                      // the form closes
  const st = (r.sentence || {}).state;                                              // what the check found
  toast(st === "unsupported" ? t("Saved, but the evidence does not cover it: it will not be exported until it does.") : t("Saved. Undo takes it back."), null, st === "unsupported" ? "warn" : "done");
  render();                                                                         // drawn
}
async function regenerate(sid, way) {                                               // new words from the evidence, in a direction when one was picked
  if (S.agent.state !== "ready") { toast(errorInfo("agent_unavailable").msg, null, "warn"); return; }  // no agent, said plainly
  await act("/api/v1/sentences/regenerate", { sid, lang: docLang(), job: jobId(), way: way || undefined });   // the task starts
}

// ---------------------------------------------------------------- fit, style, theme, history

function inspFit() {                                                                // the fit to the job in view
  const j = job();                                                                  // the job
  if (!j) return [h("div", { class: "ins-sec" }, h("h3", { text: t("No job in view") }), h("p", { class: "hint", text: t("Add a job to see how your profile fits its posting, line by line.") }),
    h("div", {}, h("button", { class: "btn small", onclick: () => go("jobs"), text: t("Add a job") })))];
  const f = fitOf(j.id);                                                            // its fit
  if (!f) return [h("p", { class: "hint", text: t("Working out the fit…") })];      // loading
  return [h("div", { class: "ins-sec" }, h("h3", { text: j.company || j.role || j.id }),
    h("span", { class: "num", "aria-label": t("Fit {n} of 100", { n: f.score }) }, String(f.score), h("small", { text: " / 100" })),
    segBar(["strong", "weak", "none"].map((k) => ({ n: f.counts[k] || 0, words: t(RATING_WORD[k]), color: RATING_COLOR[k] })), { label: t("The posting's lines"), id: "ifit-" + j.id })),
    f.gaps.length ? h("div", { class: "ins-sec" }, h("h3", { text: t("Gaps") }), h("ul", { style: "margin:0;padding-left:18px;display:grid;gap:4px;font-size:var(--fs-sm)" }, f.gaps.slice(0, 6).map((g) => h("li", { text: g })))) : null,
    sendNote(t("Tailoring sends the posting and your evidence to the agent.")),
    h("div", { class: "ev-actions" }, h("button", { class: "btn small", onclick: () => { openApplication(j.id, "fit"); go("jobs"); }, text: t("See every line") }),
      h("button", { class: "btn small", onclick: () => makeForJob(j.id), disabled: task("autopilot").state === "running" || null, text: t("Make this job's documents") }))];
}
const RATING_COUNT = { strong: "{n} strong", weak: "{n} weak", none: "{n} none" };  // the fit's counts, each a sentence of its own
function setDoc(key, value, store) { UI[key] = value; localStore(store, String(value)); render(); }  // a document setting, kept in this browser
function inspStyle() {                                                              // the documents' language, length and parts
  const seg = (label, key, store, options, now = UI[key]) => h("div", { class: "ins-sec" }, h("h3", { text: t(label) }), h("div", { class: "seg" }, options.map(([v, w]) =>
    h("button", { "aria-pressed": now === v ? "true" : "false", onclick: () => setDoc(key, v, store), text: t(w) }))));   // pressed: the value in force, chosen or not
  const rulesNow = (S.settings && S.settings.style) || "default";                   // the writing rules in use
  const rules = h("div", { class: "ins-sec" }, h("h3", { text: t("Writing rules") }),  // the style pack every sentence is written and checked by
    (S.styles || []).length ? h("div", { class: "seg" }, [["default", t("Offerowl's own")], ...(S.styles || []).map((n) => [n, n])].map(([k, w]) =>
      h("button", { "aria-pressed": rulesNow === k ? "true" : "false", onclick: () => act("/api/v1/settings", { style: k }), text: w })))
      : h("dl", { class: "kv" }, h("dt", { text: t("In use") }), h("dd", { text: t("Offerowl's own") })),   // one set of rules: said, as the blind table's is, not a choice of one
    h("button", { class: "btn small", onclick: () => $("stylepick").click() }, icon("upload"), t("Add your own rules")),   // a JSON file of rules
    h("p", { class: "hint", text: t("Your rules come first in every draft and every check: words to avoid, numbers or none, how long each part is.") }));
  const bl = S.blind || {}, bc = bl.counts || {};                                   // the blind edition's table in use, and its lists' sizes
  const blind = h("div", { class: "ins-sec" }, h("h3", { text: t("Blind edition") }),   // what a blind edition covers with bars
    h("dl", { class: "kv" }, h("dt", { text: t("Table") }), h("dd", { text: bl.own ? t("Your own") : t("Offerowl's own, which covers nothing") }),
      h("dt", { text: t("Covered") }), h("dd", { text: tn(bc.mask || 0, "{n} pattern", "{n} patterns") }),   // names, contacts and figures under bars
      h("dt", { text: t("Hidden whole") }), h("dd", { text: tn(bc.mask_whole || 0, "{n} pattern", "{n} patterns") }),   // values under one bar with their spaces
      h("dt", { text: t("Never shown") }), h("dd", { text: tn(bc.leak || 0, "{n} word", "{n} words") })),   // words the export refuses to let through, matched as written
    h("button", { class: "btn small", onclick: () => $("blindpick").click() }, icon("upload"), t("Use your own table")),   // a JSON file of patterns
    bl.own ? h("button", { class: "btn small", onclick: () => act("/api/v1/blind", { table: null }, t("Offerowl's own table is in use again.")), text: t("Use Offerowl's own") }) : null,   // back to the shipped one
    h("p", { class: "hint", text: t("The names, contacts and figures a blind edition covers with bars, as patterns in a JSON file. It is kept in your workspace on this PC.") }));
  return [rules, blind, seg("Document language", "docLang", "offerowl-doclang", [["ko", "Korean"], ["en", "English"]], docLang()),   // the language shown, even before one is chosen
    seg("Pages at most", "maxPages", "offerowl-maxpages", [[2, "2 pages"], [3, "3 pages"], [4, "4 pages"], [5, "5 pages"], [6, "6 pages"], [7, "7 pages"]]),   // a long career's description runs to six, in English to seven
    h("div", { class: "ins-sec" }, h("h3", { text: t("Tailoring makes") }),
      h("label", { class: "toggle" }, h("input", { type: "checkbox", "data-key": "t-cover", checked: UI.cover, onchange: (e) => setDoc("cover", e.target.checked, "offerowl-cover") }), h("span", { class: "track" }), t("The cover letter")),
      h("label", { class: "toggle" }, h("input", { type: "checkbox", "data-key": "t-typeset", checked: UI.typeset, disabled: !!S.engine || null, onchange: (e) => setDoc("typeset", e.target.checked, "offerowl-typeset") }), h("span", { class: "track" }), t("The PDFs too")),
      h("label", { class: "toggle" }, h("input", { type: "checkbox", "data-key": "t-export_extras", checked: !!(S.settings && S.settings.export_extras), onchange: (e) => act("/api/v1/settings", { export_extras: e.target.checked }) }), h("span", { class: "track" }), t("Word and text files on the Desktop too")),   // PDFs alone unless asked
      h("label", { class: "toggle" }, h("input", { type: "checkbox", "data-key": "t-export_pptx", checked: !!(S.settings && S.settings.export_pptx), onchange: (e) => act("/api/v1/settings", { export_pptx: e.target.checked }) }), h("span", { class: "track" }), t("The portfolio as a PowerPoint file too")),   // each page as a picture, its links kept
      h("label", { class: "toggle" }, h("input", { type: "checkbox", "data-key": "t-desk_portfolio", checked: !!(S.settings && S.settings.desk_portfolio), onchange: (e) => act("/api/v1/settings", { desk_portfolio: e.target.checked }) }), h("span", { class: "track" }), t("The latest portfolio kept on the Desktop")),   // replaced after each build of the general edition that passes
      S.settings && S.settings.desk_portfolio && S.desk && (S.desk.kept || []).length ? h("p", { class: "hint", text: t("On your Desktop: {names}", { names: S.desk.kept.join(", ") }) }) : null,   // its names there, never a path
      S.engine ? h("p", { class: "hint", text: errorInfo(S.engine).msg }) : null),
    docLang() === "en" && S.profile_lang === "ko" && !S.english ? band("needs_translation") : null];
}
function inspTheme() {                                                              // the resume's colour pack
  const packs = [["navy", "Navy", "#1B2E4B"], ["teal", "Teal", "#1D5C63"], ["mono", "Grey", "#E4E4E4"], ["wine", "Wine", "#5E2233"], ["forest", "Forest", "#1F4D3A"], ["slate", "Slate", "#2F3B47"]];  // src/themes.json's packs and their name band colour
  const set = S.settings || {};                                                     // the saved form and look
  const choice = (key, now, list) => h("div", { class: "seg" }, list.map(([k, w]) => h("button", { "aria-pressed": now === k ? "true" : "false", onclick: () => act("/api/v1/settings", { [key]: k }), text: t(w) })));  // one of a few
  return [h("div", { class: "ins-sec" }, h("h3", { text: t("Form of the resume") }),
    choice("form", set.form || "detailed", [["detailed", "Detailed"], ["compact", "One column"], ["table", "Tables"]]),
    h("p", { class: "hint", text: t({ detailed: "A career description with an overview, for readers who look closely.", compact: "One column with no table or figure: short, and read well by a job site's program.", table: "Tables like a standard Korean application form, then the work in detail." }[set.form || "detailed"]) })),
    h("div", { class: "ins-sec" }, h("h3", { text: t("Look of the deck") }),
      choice("deck_style", set.deck_style || "classic", [["classic", "Classic"], ["clean", "Clean"]]),   // not "Light": that is this app's own theme, a menu away
      h("p", { class: "hint", text: t("Make the PDFs again to see a new form or look in the typeset pages.") })),
    h("div", { class: "ins-sec" }, h("h3", { text: t("Colour of the resume and the deck") }),
    h("div", { class: "swatches" }, packs.map(([k, w, c]) => h("button", { class: "swatch", "aria-pressed": UI.theme === k ? "true" : "false", onclick: () => setDoc("theme", k, "offerowl-doctheme") },
      h("i", { style: `background:${c}`, "aria-hidden": "true" }), t(w)))),
    h("p", { class: "hint", text: t("One accent colour for headings and the name band; the text stays dark grey on white, as printed.") })),
    h("div", { class: "ins-sec" }, h("h3", { text: t("This app") }), h("div", { class: "seg" }, [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(([k, w]) =>
      h("button", { "aria-pressed": (document.documentElement.dataset.themeChoice || "auto") === k ? "true" : "false", onclick: () => { localStore("offerowl-theme", k); if (k === "auto") try { localStorage.removeItem("offerowl-theme"); } catch (_) { /* blocked */ } applyTheme(k); render(); }, text: t(w) }))))];
}
function inspHistory() {                                                            // every change, newest first, with undo back to it
  const key = `hist|${rev()}`;                                                      // per revision
  if (!UI.docs[key]) getDoc(key, "/api/v1/history");                                // fetched once
  const steps = (UI.docs[key] || {}).steps;                                         // newest first
  if (!steps) return [h("p", { class: "hint", text: t("Reading the history…") })];  // loading
  if (!steps.length) return [h("p", { class: "hint", text: t("Nothing changed yet. Every change you make is kept here, and can be taken back.") })];
  // the same change made again and again in a row (a card moved, then moved on) is one line with its count; undoing it takes
  // back all of them. The list is the whole workspace's, as undo is one for the whole workspace
  const rows = [];
  steps.forEach((s, i) => { const w = undoLabel(s.label), last = rows[rows.length - 1];
    if (last && last.w === w) { last.n += 1; last.to = i; } else rows.push({ w, n: 1, to: i, t: s.t }); });
  return [h("p", { class: "hint", text: t("Every change in Offerowl, newest first. Click one to undo it and everything after it.") }),
    h("div", { class: "hist" }, rows.map((r) => h("button", { onclick: async () => {   // asked first on the panel's own sheet: there is no redo
      if (await askFirst({ title: tn(r.to + 1, "Undo {n} change?", "Undo {n} changes?"), ok: t("Undo"),
        text: r.to ? t("Everything from \"{what}\" to the newest change is taken back.", { what: r.w }) : t("\"{what}\" is taken back.", { what: r.w }) }))
        act("/api/v1/history/undo", { steps: r.to + 1 }, t("Undone.")); } },
      h("span", { text: r.n > 1 ? `${r.w} ×${r.n}` : r.w }), h("time", { text: r.t ? ago(r.t) : "" }))))];
}
function undoLabel(l) {                                                             // an undo step in words
  const x = l || {}, what = x.title || x.company || "";                             // the name it carries; a thing deleted for good leaves none
  // with a name, and without one: older steps, and steps whose thing was deleted for good, carry none
  const L = { undo_keep: ["Kept {what}", "Kept a fact"], undo_drop: ["Dropped {what}", "Dropped a fact"], undo_edit: ["Edited {what}", "Edited a fact"],
    undo_reset: ["Set {what} to confirm again", "Put a fact back to confirm"], undo_keep_all: ["Kept {n} facts"], undo_typed: ["Added {what}", "Added a fact"],
    undo_details: ["Typed in your details"], undo_remove_material: ["Removed {what}", "Removed a file"], undo_add_material: ["Added files"],
    undo_add_job: ["Added the job {what}", "Added a job"], undo_add_edition: ["Added the edition {what}", "Added an edition"], undo_analysis: ["Ordered the resume for a job"],
    undo_draft: ["Wrote the resume"], undo_figures: ["Drew the deck's figures"], undo_board: ["Changed the card of {what}", "Changed a card"], undo_lock: ["Locked the submitted copies"],
    undo_sentence: ["Changed a sentence"], undo_lock_sentence: ["Locked a sentence"], undo_unlock_sentence: ["Unlocked a sentence"],
    undo_reminder: ["Changed a reminder of {what}", "Changed a reminder"], undo_round: ["Changed an interview round of {what}", "Changed an interview round"],
    undo_remove_job_material: ["Removed {what}", "Removed a file"], undo_blind: ["Changed the blind edition's table"], undo_remove_job: ["Removed the job {what}", "Removed a job"],
    undo_remove_edition: ["Removed the edition {what}", "Removed an edition"], undo_put_back: ["Put back {what}", "Put back from the trash"] };
  const words = L[x.code] || ["A change"];                                          // an unknown step still reads
  return t(what || words.length === 1 ? words[0] : words[1], { what, n: x.n || 0 });   // with its name when it has one
}
