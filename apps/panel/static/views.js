// Offerowl's panel, part 3: the views of the navigation besides the documents: the profile (your details, your files
// and the facts read from them) and the applications. An application is one job with everything it asks for, in tabs:
// its fit line by line, its documents, the form's questions, the interview (the question board and the scripts) and its
// progress (its stage, the next step and reminders on this PC). Every application at once is a list, a board by stage
// or a timeline.
"use strict";                                                                       // catches undeclared names and silent writes early

// ---------------------------------------------------------------- the profile

// typing saves on a pause; the fields typed in meanwhile go together (one pause, every field), or a quick second field would drop the first
let pendingDetails = {};
const sendDetails = debounce(() => { const fields = pendingDetails; pendingDetails = {}; act("/api/v1/details", { fields }); }, 700);
function saveDetails(fields) { Object.assign(pendingDetails, fields); sendDetails(); }
// the facts' rows: the state carries only their counts and a stamp (rev), so the poll stays small; the rows are read from
// /api/v1/facts when the stamp changes, and the ones read before are drawn until they arrive
let factCache = { rev: null, rows: [], asked: null };                               // the rows read, their stamp, and the stamp asked for
function factRows() {
  const want = S.facts.rev;                                                         // the rows the state stands for now
  if (factCache.rev !== want && factCache.asked !== want) {                         // not read yet, and not on its way
    factCache.asked = want;                                                         // one request per stamp
    fetch("/api/v1/facts", { cache: "no-store" }).then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((j) => { if (factCache.asked === want) { factCache = { rev: want, rows: j.rows || [], asked: null }; UI.docsVer++; render(); } })   // docsVer: the canvas draws again with them
      .catch(() => { if (factCache.asked === want) factCache.asked = null; });     // failed: the next draw asks again
  }
  return factCache.rows;                                                            // the rows read last (none before the first answer)
}
const trashHere = () => ((S.removed || {}).sources || 0) + ((S.removed || {}).photo || 0);   // the profile's files and photo in the Trash
function viewProfile(host) {                                                        // your details, your files, the facts
  const c = S.facts.counts, d = S.details || {};                                    // the totals and the person's own fields
  if (!UI.filter) UI.filter = c.to_confirm ? "todo" : "kept";                       // nothing to confirm: the facts kept, not an empty list
  const reading = task("ingest").state === "running";                               // a reading runs now
  const rows = factRows().filter((r) => UI.filter === "all" || (UI.filter === "todo" ? !r.status : UI.filter === "kept" ? r.status === "accepted" : r.status === "rejected"));
  fill(host,
    h("div", { class: "viewhead" }, h("h1", { text: t("Profile") }),
      h("span", { class: "sub", text: t("{kept} kept, {todo} to confirm, {dropped} dropped", { kept: c.kept, todo: c.to_confirm, dropped: c.dropped }) })),
    h("div", { class: "split" }, h("div", { class: "split-side" },                    // details and files beside the facts on a wide screen
    detailsSheet(d),
    h("section", { class: "glass viewsheet", "aria-label": t("Your files") },
      h("div", { class: "card-h" }, h("h3", { text: t("Your files") }), sentLine(agentOn(), agentOn() ? t("The text of each file goes to the agent to find facts; a profile file is read without it.") : t("With no agent on, only an Offerowl profile file is read."))),
      dropZone(reading, !c.to_confirm && !UI.factAdd && !UI.factEdit),   // its key is the main one when nothing else waits
      S.materials.length ? h("div", { class: "rows" }, S.materials.map((m) => h("div", { class: "ob-file" },
        h("span", {}, h("b", { text: m.name }), " ", h("span", { class: "hint", text: materialState(m) })),
        h("button", { class: "btn small quiet danger", "data-key": "mat-remove-" + m.id, onclick: () => removeAct("/api/v1/materials/remove", { id: m.id }, t("Removed {name}.", { name: m.name })), text: t("Remove") })))) : null,   // its facts go with it; the note's Undo, or the Trash, brings both back
      trashLine(trashHere(), tn(trashHere(), "{n} file in the trash", "{n} files in the trash")),   // what was removed here, a key away
      task("ingest").state === "error" ? band(task("ingest").error.code, { retry: () => act("/api/v1/materials/read", { ids: S.materials.map((m) => m.id) }) }) : null)),
    factsSheet(rows, c)));
}
// your details, read as they will print, so nothing waits to be typed; the fields open only on Edit. What is kept with marks
// (==highlight==) is shown drawn, never as typed marks, and the editor shows how it reads
function detailsSheet(d) {
  const any = ["name", "email", "name_en", "phone", "headline", "intro"].some((k) => String(d[k] || "").trim());   // anything to read yet
  const editing = UI.editDetails || !any;                                           // nothing yet: the fields at once
  const head = h("div", { class: "card-h" }, h("h3", { text: t("Your details") }), sentLine(false), h("span", { class: "grow" }),
    any ? h("button", { class: "btn sm", type: "button", "aria-pressed": editing ? "true" : "false", onclick: () => { UI.editDetails = !editing; render(); } },
      icon(editing ? "check" : "edit"), editing ? t("Done") : t("Edit")) : null);   // Edit opens the fields, Done closes them (each word is saved as it is typed)
  // where each field came from (a file a run read, or the person's typing), numbered as the documents number their evidence;
  // the file's words on hover
  const src = (d._src && typeof d._src === "object") ? d._src : {};                // field -> its source
  const keyOf = (w) => w.typed ? "\u0000typed" : String(w.file || "");             // a file, or the person's own typing
  const files = [];                                                                 // the sources, in the order the fields show them
  for (const k of ["name", "name_en", "email", "phone", "headline", "intro"]) {     // the order they are read in
    const w = src[k];
    if (w && String(d[k] || "").trim() && !files.some((f) => f.key === keyOf(w))) files.push({ key: keyOf(w), file: w.file, typed: !!w.typed });
  }
  const many = files.length > 1;                                                    // one source says nothing new after every field: the line under them names it
  const cite = (k) => {                                                             // the number after a field's value
    const w = src[k];
    if (!w || !many) return null;                                                   // no record (filled before sources were kept), or one source only
    return h("sup", { class: "dcite", title: w.typed ? t("Typed by you") : (w.quote ? `${w.file}: ${unmarked(w.quote)}` : w.file) },
      String(files.findIndex((f) => f.key === keyOf(w)) + 1));
  };
  if (!editing) {
    const name = h("div", { class: "dr-name" }, h("b", {}, d.name || "", cite("name")), d.name_en ? h("span", {}, d.name_en, cite("name_en")) : null);   // the name, and its English beside it
    const contact = h("div", { class: "dr-contact" }, d.email ? h("span", {}, icon("mail", 15), d.email, cite("email")) : null, d.phone ? h("span", {}, icon("phone", 15), d.phone, cite("phone")) : null);
    const headline = d.headline ? h("p", { class: "dr-headline" }, marks(d.headline, "hl"), cite("headline")) : null;   // the headline, its highlights drawn
    const intro = d.intro ? h("p", { class: "dr-intro" }, marks(d.intro, "hl"), cite("intro")) : null;   // the introduction, its highlights drawn
    return h("section", { class: "paper viewsheet", "aria-label": t("Your details") }, head,
      h("div", { class: "details-wrap" }, photoCell(),                              // the photo beside them, as the resume's header puts it
        h("div", { class: "details-read" }, name, contact, headline, intro,
          files.length ? h("div", { class: "dr-src", "aria-label": t("Where these came from") }, files.map((f, i) => h("span", {},   // the numbers' sources, one line
            many ? h("span", { class: "evn", text: String(i + 1) }) : null, f.typed ? [icon("edit", 12), t("Typed by you")] : [icon("file", 12), f.file]))) : null)));
  }
  const field = (key, label, opt = {}) => h("label", { class: "field" }, h("span", { text: t(label) }),   // a one-line field
    h("input", { "data-key": "d-" + key, type: opt.type || "text", value: d[key] || "", autocomplete: opt.auto || "off", oninput: (e) => saveDetails({ [key]: e.target.value }) }));
  const rich = (key, label, rows) => {                                              // a field that carries highlights: the words, a key, and how they read
    const view = h("p", { class: "md-preview", "aria-live": "polite" }, marks(d[key] || "", "hl"));   // drawn as the documents draw it
    const box = h("textarea", { "data-key": "d-" + key, rows, class: "short", "aria-label": t(label),
      oninput: (e) => { saveDetails({ [key]: e.target.value }); view.replaceChildren(...marks(e.target.value, "hl")); } }, d[key] || "");
    const mark = h("button", { class: "btn sm quiet", type: "button", title: t("Highlight the chosen words"), onclick: () => {   // marks the chosen words, so no mark is typed
      const a = box.selectionStart, b = box.selectionEnd;                           // the chosen words
      if (a === b) { toast(t("Choose the words to highlight first.")); return; }    // nothing chosen
      box.value = box.value.slice(0, a) + "==" + box.value.slice(a, b) + "==" + box.value.slice(b);   // wrapped as the documents keep it
      box.dispatchEvent(new Event("input")); box.focus();                           // saved and drawn
    } }, t("Highlight"));
    return h("div", { class: "field wide" }, h("span", { class: "rich-head" }, h("span", { text: t(label) }), mark), box,
      h("span", { class: "md-label", text: t("How it reads") }), view);
  };
  return h("section", { class: "paper viewsheet", "aria-label": t("Your details") }, head,
    h("div", { class: "details-wrap" }, photoCell(),
      h("div", { class: "details" }, field("name", "Name", { auto: "name" }), field("email", "Email", { type: "email", auto: "email" }),
        field("name_en", "Name in English"), field("phone", "Phone", { type: "tel", auto: "tel" }),
        rich("headline", "Headline: one line on what you build and run", 2), rich("intro", "Introduction", 4))));
}
const KIND_COLOR = { role: "var(--band-ink, var(--ink))", project: "var(--blue-bar)", education: "var(--green-bar)", skill: "var(--violet-bar)", layer: "var(--rose-bar)", competency: "var(--teal-bar)",   // a kind's colour, as its chip: the big kinds each their own
  paper: "var(--amber-bar)", patent: "var(--amber-bar)", award: "var(--amber-bar)", certificate: "var(--amber-bar)", card: "var(--orange-bar)", highlight: "var(--orange-bar)", about: "var(--orange-bar)",
  motivation: "var(--orange-bar)", profile: "var(--orange-bar)", typed: "var(--ink-2)", other: "var(--ink-3)" };   // the bars' colours (marks with no words on them), each a kind's own
const FACT_PAGE = 12;                                                               // rows on one page of facts: a long list reads in pages, never as one scroll
function factsSheet(rows, c) {                                                      // the facts: their state, a search, the kinds, one page of rows
  const q = String(UI.factQuery || "").trim().toLowerCase();                        // the words searched for
  const words = (r) => { const v = { ...r, ...(r.edit || {}) }; return [v.title, v.org, v.period, v.statement, r.quote].filter(Boolean).join(" ").toLowerCase(); };  // what a search reads
  const byKind = {};                                                                // how many of each kind the state filter leaves
  const kindOf = (r) => (r.edit && r.edit.kind) || r.kind;                          // a fact's kind as the person set it
  for (const r of rows) byKind[kindOf(r)] = (byKind[kindOf(r)] || 0) + 1;           // counted
  const kind = byKind[UI.factKind] ? UI.factKind : "";                              // a kind no longer here shows them all
  const found = rows.filter((r) => (!kind || kindOf(r) === kind) && (!q || words(r).includes(q)));   // the kind and the search
  const pages = Math.max(1, Math.ceil(found.length / FACT_PAGE));                   // how many pages
  const page = Math.min(UI.factPage || 0, pages - 1);                               // the page shown, within range
  const shown = found.slice(page * FACT_PAGE, (page + 1) * FACT_PAGE);              // its rows
  const turn = (p) => { UI.factPage = p; render(); requestAnimationFrame(() => { const s = $("canvas").querySelector(".facts-sheet"); if (s) s.scrollIntoView({ block: "start" }); }); };  // a page, read from its top
  const named = Object.entries(byKind).filter(([k]) => KIND[k] && KIND[k] !== "Other").sort((a, b) => b[1] - a[1]);   // the kinds with a name, the most first
  const rest = rows.length - named.slice(0, 5).reduce((s, [, n]) => s + n, 0);       // every other fact, the unnamed kinds with them: one "Other", never two
  return h("section", { class: "paper facts-sheet", "aria-label": t("Facts") },
    rows.length ? h("div", { class: "facts-viz" }, segBar([...named.slice(0, 5).map(([k, n]) => ({ n, words: t(KIND[k]), color: KIND_COLOR[k] || "var(--ink-3)" })),   // the five biggest named kinds, then the rest together
      ...(rest > 0 ? [{ n: rest, words: t("Other"), color: "var(--ink-3)" }] : [])],   // "Other" as Make draws it (line-2 was 1.5:1)
      { label: t("Facts by kind"), id: "kinds" })) : null,
    h("div", { class: "facts-tools" },
      h("div", { class: "seg", "aria-label": t("Show") }, [["todo", "To confirm", c.to_confirm], ["kept", "Kept", c.kept], ["dropped", "Dropped", c.dropped], ["all", "All", c.found]].map(([k, w, n]) =>
        h("button", { "aria-pressed": UI.filter === k ? "true" : "false", onclick: () => { UI.filter = k; UI.factPage = 0; render(); } }, t(w), " ", h("span", { class: "chip count", text: String(n) })))),
      h("span", { class: "grow" }),
      h("button", { class: "btn", "aria-expanded": UI.factAdd ? "true" : "false", onclick: () => { UI.factAdd = !UI.factAdd; render(); }, text: UI.factAdd ? t("Close the form") : t("Add a fact") }),
      c.to_confirm ? h("button", { class: "btn" + (UI.factAdd || UI.factEdit ? "" : " primary"), onclick: () => act("/api/v1/facts/keep-all", {}, t("Kept. Undo takes them back.")), text: t("Keep the remaining {n}", { n: c.to_confirm }) }) : null),
    rows.length > FACT_PAGE || q || kind ? h("div", { class: "facts-tools" },              // a search and the kinds, once there are more facts than one page holds
      h("input", { class: "input fq", type: "search", "data-key": "fq", value: UI.factQuery || "", placeholder: t("Search your facts"), "aria-label": t("Search your facts"),
        oninput: (e) => { UI.factQuery = e.target.value; UI.factPage = 0; render(); } }),
      h("select", { class: "input fk", "aria-label": t("Kind"), onchange: (e) => { UI.factKind = e.target.value; UI.factPage = 0; render(); } },
        h("option", { value: "", text: t("All kinds") }),
        Object.keys(byKind).map((k) => h("option", { value: k, selected: kind === k || null, text: `${t(KIND[k] || "Other")} ${byKind[k]}` }))),
      h("span", { class: "hint", text: found.length ? t("{from}–{to} of {n}", { from: page * FACT_PAGE + 1, to: page * FACT_PAGE + shown.length, n: found.length }) : "" })) : null,
    UI.factAdd ? factForm() : null,
    h("div", { class: "factlist" }, shown.length ? shown.map(factRow)                 // one page of rows
      : h("p", { class: "empty", text: q || kind ? t("No fact matches.") : UI.filter === "todo" ? t("Nothing left to confirm.") : t("No facts here yet.") })),
    pager(page, pages, turn, found.length ? t("{a}–{b} of {n}", { a: page * FACT_PAGE + 1, b: page * FACT_PAGE + shown.length, n: found.length }) : ""));   // the pages, numbered
}
function factForm() {                                                              // a fact typed by the person: its own evidence, kept at once
  const kinds = ["role", "project", "education", "skill", "certificate", "award", "paper", "patent", "other"];  // the kinds the profile knows
  const form = h("form", { class: "add-fact", "aria-label": t("Add a fact"), onsubmit: (e) => { e.preventDefault(); const f = e.target.elements;
    act("/api/v1/facts/add", { kind: f.kind.value, title: f.title.value, org: f.org.value, period: f.period.value, statement: f.statement.value }, t("Added. Undo takes it back."))
      .then((r) => { if (r) { UI.factAdd = false; forget("f-add-"); render(); } }); } },
    h("p", { class: "hint", text: t("A fact you type is its own evidence: write what you did, as you would say it.") }),
    h("div", { class: "details" },
      h("label", { class: "field" }, h("span", { text: t("Kind") }), h("select", { name: "kind", "data-key": "f-add-kind" }, kinds.map((k) => h("option", { value: k, text: t(KIND[k]) })))),
      h("label", { class: "field" }, h("span", { text: t("Title") }), h("input", { name: "title", "data-key": "f-add-title" })),
      h("label", { class: "field" }, h("span", { text: t("Company or place") }), h("input", { name: "org", "data-key": "f-add-org" })),
      h("label", { class: "field" }, h("span", { text: t("Period") }), h("input", { name: "period", "data-key": "f-add-period", placeholder: "2023.01 ~ 2023.09" })),
      h("label", { class: "field wide" }, h("span", { text: t("What it says") }), h("textarea", { name: "statement", "data-key": "f-add-statement", rows: 3 }))),
    h("div", {}, h("button", { class: "btn" + (UI.factEdit ? "" : " primary"), type: "submit", text: t("Add the fact") })));   // a fact's own Save leads while it is edited
  return form;                                                                      // under the filters
}
function photoCell() {                                                              // the resume's photo: a 3:4 cell, its keys and whether it is printed
  const ph = S.photo;                                                               // {at, on} or null
  return h("div", { class: "photo-cell" },
    ph ? h("img", { src: `/api/v1/photo?v=${ph.at}&w=240`, alt: t("Your photo") }) : h("span", { class: "photo-none", "aria-hidden": "true" }, icon("person", 30)),   // w=240: a small copy, drawn about 120 px wide (twice that on a sharp screen)
    h("div", { class: "photo-keys" },                                               // its keys on one row: change it, or take it away (as every removal, a red sign)
      h("button", { class: "btn small", onclick: () => $("photopick").click(), text: ph ? t("Change") : t("Add a photo") }),
      ph ? h("button", { class: "btn small danger", onclick: async () => {   // said in words, as every removal key; kept in the Trash: its note puts it back from there (a picture has no undo step)
        const j = await act("/api/v1/photo/remove", {});                            // the answer names it in the Trash
        if (j) toast(t("Photo removed."), j.removed ? { words: t("Undo"), run: () => act("/api/v1/removed/restore", { id: j.removed }, t("Photo put back.")) } : null);
      } }, icon("trash"), t("Remove the photo")) : null),
    ph ? h("label", { class: "toggle" }, h("input", { type: "checkbox", "data-key": "t-photo", checked: ph.on, onchange: (e) => act("/api/v1/settings", { photo: e.target.checked }) }), h("span", { class: "track" }), t("On the resume")) : null);
}
function materialState(m) {                                                         // a file's reading state in words
  return { new: t("Waiting"), reading: t("Reading"), done: tn(m.facts || 0, "{n} fact", "{n} facts"), no_text: t("No text in this file"),
    needs_agent: t("Needs the agent to read"), stopped: t("Stopped part way"), error: t("Not an Offerowl profile") }[m.state] || "";
}
function dropZone(reading, lead = true) {                                           // the place to drop files (lead: its key is the view's main one)
  const z = h("div", { class: "drop ai", role: "group", "aria-label": t("Add files") },   // the files the agent reads: the rainbow rim
    h("strong", { text: reading ? t("Reading your files…") : t("Drop your old resume, portfolio or notes here") }),
    h("div", { style: "display:flex;gap:8px;flex-wrap:wrap;justify-content:center" },
      h("button", { class: "btn" + (lead ? " primary" : ""), disabled: reading || null, onclick: () => $("filepick").click(), text: t("Choose files") }),
      ((S.facts && S.facts.counts && S.facts.counts.kept) || 0) ? null   // facts kept already: the example would only mix a fictional person into them
        : h("button", { class: "btn", disabled: reading || task("autopilot").state === "running" || null, onclick: seeExample }, icon("person"), t("Try an example"))));   // not while a run reads the person's own
  z.addEventListener("dragover", (e) => { e.preventDefault(); z.classList.add("over"); });   // a file held over it
  z.addEventListener("dragleave", () => z.classList.remove("over"));                // moved away
  z.addEventListener("drop", async (e) => { e.preventDefault(); z.classList.remove("over"); makeFrom({ files: await droppedFiles(e.dataTransfer) }); });  // dropped: one run, as on Make
  return z;                                                                         // in the view
}
function factRow(r) {                                                               // one fact on the notebook page
  const editing = UI.factEdit === r.cid;                                            // its edit form is open
  const v = { ...r, ...(r.edit || {}) };                                            // with the person's edits
  const kept = r.status === "accepted", dropped = r.status === "rejected";          // its state
  // the edit form, laid out as the add form is: the same fields two by two, the words across, keys of the same size. Its kind
  // too, for a fact read from a file or typed (the profile files them by kind); an item imported from a profile file keeps
  // its place in that profile, so its kind is not offered
  const kinds = ["role", "project", "education", "skill", "certificate", "award", "paper", "patent", "other"];
  const body = editing ? h("div", { class: "add-fact" },
    h("div", { class: "details" },
      r.origin !== "profile" ? h("label", { class: "field" }, h("span", { text: t("Kind") }), h("select", { "data-key": "f-kind" },
        kinds.map((k) => h("option", { value: k, selected: (v.kind || "other") === k || null, text: t(KIND[k]) })))) : null,
      h("label", { class: "field" }, h("span", { text: t("Title") }), h("input", { "data-key": "f-title", value: v.title || "" })),
      h("label", { class: "field" }, h("span", { text: t("Company or place") }), h("input", { "data-key": "f-org", value: v.org || "" })),
      h("label", { class: "field" }, h("span", { text: t("Period") }), h("input", { "data-key": "f-period", value: v.period || "", placeholder: "2023.01 ~ 2023.09" })),
      h("label", { class: "field wide" }, h("span", { text: t("What it says") }), h("textarea", { "data-key": "f-statement", rows: 3 }, v.statement || ""))),
    h("div", { class: "acts" }, h("button", { class: "btn primary", onclick: () => saveFact(r.cid), text: t("Save") }),
      h("button", { class: "btn", onclick: () => { UI.factEdit = null; forget("f-"); render(); }, text: t("Cancel") })))
    : null;
  const open = !editing && UI.factOpen === r.cid;                                   // its words and source shown
  const plain = (x) => unmarked(x).replace(/…$/, "").trim();                         // a text without marks, for comparing and for showing
  const said = r.quote && plain(r.quote) !== plain(v.title) ? plain(r.quote) : "";  // the source's words, unless they are the title itself
  // closed, the source's words in sight as a retrieval interface shows them, but never cut mid-way with an ellipsis: whole
  // when short, else their first sentence whole and a word that says there is more (a sentence too long to stop early stays
  // whole); the row opens all of them
  const lead = (x) => { if (x.length <= 140) return [x, false]; const first = (/^.*?[.!?。](?=\s)/.exec(x) || [x])[0]; return first.length < x.length && first.length <= 160 ? [first, true] : [x, false]; };   // up to the first stop, no lookbehind (Safari before 16.4 could not read the file)
  return h("article", { class: "fact" + (dropped ? " dropped" : "") + (open || editing ? " open" : ""), "aria-label": `${t(KIND[v.kind] || "Other")}: ${v.title || ""}` },
    h("button", { class: "fact-row", type: "button", "aria-expanded": open ? "true" : "false", disabled: editing || null,   // the row opens its words
      onclick: () => { UI.factOpen = open ? null : r.cid; render(); } },
      h("span", { class: "kind", "data-kind": v.kind || "other", text: t(KIND[v.kind] || "Other") }),   // its kind as the person set it
      h("span", { class: "fact-main" }, h("b", { class: "fact-t", text: plain(v.title || v.statement) }),
        (v.org || v.period) ? h("span", { class: "meta", text: [v.org, v.period].filter(Boolean).join(", ") }) : null,
        // its evidence in sight, as a retrieval interface shows a claim with its source: the source's own words and the file,
        // under every fact; before, they waited behind a click
        h("span", { class: "fact-ev" }, said ? (() => { const [shown, more] = open ? [said, false] : lead(said);   // all of them on hover too
          return h("q", { title: more ? said : null }, shown, more ? h("span", { class: "ev-more", text: t("Read all") }) : null); })() : null,   // the word for more at the end of the line, not a line of its own
          h("span", { class: "fact-src" }, icon("file", 12), r.source && r.source.name ? r.source.name : t("Typed by you")))),
      r.edited ? h("span", { class: "chip", text: t("Edited") }) : null),
    editing ? null : h("div", { class: "acts" },
      h("button", { class: "btn small go", "data-key": "fact-keep-" + r.cid, "aria-pressed": kept ? "true" : "false", onclick: () => act("/api/v1/facts/decide", { cid: r.cid, action: kept ? "reset" : "keep" }) }, kept ? [icon("check"), t("Kept")] : t("Keep")),   // done: green with a tick; still to do: a plain key
      h("button", { class: "btn small", "data-key": "fact-edit-" + r.cid, onclick: () => { UI.factEdit = r.cid; render(); }, text: t("Edit") }),
      h("button", { class: "btn small" + (dropped ? "" : " danger"), "data-key": "fact-drop-" + r.cid, "aria-pressed": dropped ? "true" : "false", onclick: () => act("/api/v1/facts/decide", { cid: r.cid, action: dropped ? "reset" : "drop" }), text: dropped ? t("Dropped") : t("Drop") })),
    editing ? h("div", { class: "fact-body" }, body)                                 // the edit form under its row
      : open && v.statement && plain(v.statement) !== plain(v.title) ? h("div", { class: "fact-body" }, h("p", {}, marks(v.statement, "hl")))   // its own words when they say more than its title (the source is on its row)
      : null);
}
function saveFact(cid) {                                                            // the edit form's fields to the server
  const val = (k) => (document.querySelector(`[data-key="f-${k}"]`) || {}).value;  // one field's value
  UI.factEdit = null; forget("f-");                                                 // the form closes
  const fields = { title: val("title"), org: val("org"), period: val("period"), statement: val("statement") };   // the shown fields
  if (val("kind")) fields.kind = val("kind");                                       // and its kind, where the form offers it
  act("/api/v1/facts/decide", { cid, action: "edit", fields }, t("Saved. Undo takes it back."));
}

// ---------------------------------------------------------------- jobs

function fitOf(jid) {                                                               // a job's fit, fetched once per revision
  const key = `fit|${jid}|${rev()}`;                                                // per revision
  if (!UI.docs[key]) getDoc(key, `/api/v1/jobs/${enc(jid)}/fit`);                   // fetched once
  return UI.docs[key] || null;                                                      // null while it loads
}
function openJob() {                                                                // the application the applications view draws: the one in view, or while an edition is in view the first one still going
  const jobs = S.jobs || [];                                                        // the jobs, oldest first
  return jobs.find((j) => j.id === S.job) || jobs.find((j) => j.stage !== "result") || jobs[0] || null;
}
function viewJobs(host) {                                                           // every application: the list beside the one open, or all of them by stage or by date
  const jobs = S.jobs || [];                                                        // the jobs, oldest first
  const open = openJob();                                                           // the one in view
  const mode = ["list", "board", "timeline"].includes(UI.jobsMode) ? UI.jobsMode : "list";   // how they are shown
  const phone = PHONE.matches;                                                      // a phone shows the list or one application, never both squeezed
  const wide = !phone && !!open && mode === "list" && UI.jobTab === "interview" && ivWide();   // the interview over the whole width, by its own key: the list comes back with the back key
  const alone = (phone && UI.jobPhone && !!open) || wide;
  const modes = jobs.length ? h("div", { class: "seg modes", "aria-label": t("View") }, [["list", "List", "list"], ["board", "Board", "columns"], ["timeline", "Timeline", "clock"]].map(([k, w, ic]) =>
    h("button", { "aria-pressed": mode === k ? "true" : "false", onclick: () => { UI.jobsMode = k; UI.jobPhone = false; render(); } }, icon(ic), t(w)))) : null;
  const list = !jobs.length || mode !== "list" || alone ? null : h("nav", { class: "joblist paper", "aria-label": t("Applications"),   // the list beside the open one
    onscroll: () => { UI.jobListTop = list.scrollTop; } },                          // where it is scrolled, kept through a redraw
    jobs.map((j, i) => [j.stage === "result" && (i === 0 || jobs[i - 1].stage !== "result") ? h("div", { class: "jl-sep", role: "presentation" }, h("span", { text: t("Ended") }), h("span", { class: "chip count", text: String(jobs.filter((x) => x.stage === "result").length) })) : null,
      h("button", { class: "jobrow", "data-stage": j.stage, "aria-current": open && open.id === j.id ? "true" : "false", onclick: () => openApplication(j.id) },
      mono(j.company || j.role || j.id, "", j.stage), h("span", { class: "co", text: j.company || j.role || j.id }), j.company && j.role ? h("span", { class: "ro", text: j.role }) : null,
      h("span", { class: "fitcount" }, stagePill(j), j.fit && j.fit.score ? h("span", { class: "fitnum", text: t("Fit {n}", { n: j.fit.score }) }) : null))]));
  fill(host,
    alone ? null : h("div", { class: "viewhead" }, h("h1", { text: t("Applications") }),   // a phone's one application starts at its own head (its back key)
      h("span", { class: "sub", text: jobs.length ? tn(jobs.length, "{n} application", "{n} applications") : t("Paste a posting to see how your profile fits it") }),
      trashLine((S.removed || {}).jobs, tn((S.removed || {}).jobs, "{n} application in the trash", "{n} applications in the trash")),   // removed ones, a key away
      h("span", { class: "grow" }), modes,
      mode === "timeline" && jobs.length ? h("button", { class: "btn", type: "button", "aria-pressed": UI.editDays ? "true" : "false", onclick: () => { UI.editDays = !UI.editDays; render(); } },
        icon(UI.editDays ? "check" : "calendar"), UI.editDays ? t("Done") : t("Edit the days")) : null,   // every application's days in one table
      jobs.length ? h("button", { class: "btn", onclick: () => { UI.adding = !UI.adding; render(); } }, icon(UI.adding ? "close" : "plus"), UI.adding ? t("Close the form") : t("Add a job")) : null),
    jobs.length && mode !== "board" && !alone ? h("div", { class: "jobs-viz" }, stageBar(jobs)) : null,   // every application by stage, at a glance
    (S.due || []).length ? h("div", { class: "band info", role: "status" }, h("p", {}, h("b", { text: t("Due now") }), " ",   // the reminders whose time has come: whose, then what
      S.due.map((d, i) => [i ? " · " : "", h("b", { text: d.name }), " " + d.text]))) : null,
    (UI.adding || !jobs.length) ? jobForm() : null,
    !jobs.length ? null : mode === "board" ? trackBoard(jobs) : mode === "timeline" ? (UI.editDays ? daysTable(jobs) : trackTimeline()) : h("div", { class: "jobsplit" + (list ? "" : " alone") },   // the jobs on the left, the one open on the right; alone, the whole width
      list, phone && !alone ? null : jobDetail(open, phone || wide)));
  if (list) keepListPlace(list, open);                                              // where the person left the list, with the open one in sight
}
function keepListPlace(list, open) {                                                // a redraw builds the list anew, at its top
  list.scrollTop = UI.jobListTop || 0;                                              // back where it was scrolled
  const cur = list.querySelector('[aria-current="true"]');                          // the open application
  if (!cur || !open || UI.jobListShown === open.id || !list.clientHeight) return;   // brought into sight once already (the person's scrolling wins), or not laid out
  UI.jobListShown = open.id;                                                        // once per application opened
  const r = cur.getBoundingClientRect(), box = list.getBoundingClientRect();        // where it is, and the list (a phone's list does not scroll)
  const top = Math.max(box.top, 0), bottom = Math.min(box.bottom, innerHeight);     // the part of the list the window shows: its foot can sit below the window
  if (r.top < top || r.bottom > bottom) { list.scrollTop += (r.top + r.bottom) / 2 - (top + bottom) / 2; UI.jobListTop = list.scrollTop; }   // to that part's middle, as far as the list scrolls
  if (!PHONE.matches) requestAnimationFrame(() => {                                 // after go() has put the window at the top; a phone reads its list from the top
    const at = cur.isConnected ? cur.getBoundingClientRect() : null;                // where the row ended up
    if (at && (at.top < 0 || at.bottom > innerHeight)) cur.scrollIntoView({ block: "nearest" });   // the last rows under the window's edge: the page moves the rest
  });
}
const WHERE = { skills: "Skills", summary: "Overview", strengths: "Strengths", education: "Education", lists: "Lists" };  // the profile's parts a fit line may cite
const RESULT = { offer: "Offer", rejected: "Rejected", withdrawn: "Withdrawn", closed: "Closed" };   // how an application ended, once it reached its result: every word its badge can say
const RESULT_CLS = { offer: "ok", rejected: "on", withdrawn: "on", closed: "on" };   // its lamp once chosen: an offer lights green, an ended one a filled grey dot (an unchosen key keeps the hollow ring)
function ownResult(j) { return j.stage === "result" && j.result && !RESULT[j.result] ? j.result : ""; }   // a result written in the person's own words
function resultDay(j) {                                                             // the day a result in words starts with, when the card says another
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(ownResult(j));
  return m && isoDay(m[1]) === m[1] && m[1] !== (j.dates || {}).result ? m[1] : "";
}
function resultOn(j, k) {                                                           // the result key that stands for how it ended: chosen, or read from the person's words
  if (j.result === k) return true;                                                  // (the badge reads them the same way)
  const own = ownResult(j);
  return !!own && resultKind(own) === k;                                            // words that read as one of the keys press it
}
function resultKind(words) {                                                       // how an application ended, read from the person's words as the Insights read them (apps/api/insights.py)
  const w = String(words || "");
  if (/탈락|불합격|미합격|불합|합격\s*(?:하지\s*)?(?:못|안\s*됨|아님)|오퍼\s*(?:없|무산|취소)|reject|declin|not selected|no offer|not (?:moving|proceed)|hired (?:someone|another)/i.test(w)) return "rejected";
  if (/철회|포기|withdr/i.test(w)) return "withdrawn";                              // the person stepped back (Insights counts it with the closed ones)
  if (/종료|정리|마감|취소|closed|ended|cancel/i.test(w)) return "closed";             // the opening ended with no decision
  if (/합격|오퍼|입사|offer|accepted|hired/i.test(w)) return "offer";
  return "none";                                                                    // ended with no words for how
}
function stageWords(j) {                                                            // where it stands, in one word the same on every screen
  if (j.stage === "result" && RESULT[j.result]) return t(RESULT[j.result]);         // one of the three
  if (j.stage === "result") return t({ rejected: "Rejected", withdrawn: "Withdrawn", closed: "Closed", offer: "Offer", none: "No result written" }[resultKind(ownResult(j))]);   // the person's own words stay on the hover
  return t(STAGE[j.stage] || "Preparing");
}
function stagePill(j) {                                                            // where it stands: the stage's dot and its word (an offer in green), all of the person's words on hover
  return h("span", { class: "st-tag", "data-stage": j.stage, "data-result": j.stage === "result" ? (RESULT[j.result] ? j.result : resultKind(ownResult(j))) : null, title: ownResult(j) || null, text: stageWords(j) });
}
function jobForm() {                                                                // paste a posting or a link
  const form = h("form", { class: "paper viewsheet", "aria-label": t("Add a job"), onsubmit: (e) => { e.preventDefault(); addJob(form); } },
    h("div", { class: "card-h" }, h("h3", { text: t("Add a job") }), sentLine(false),
      h("span", { class: "hint", text: t("The fit is worked out on this PC. Tailoring with the agent sends the posting.") })),
    // a place to paste, not a page to type in: two rows, and a pasted link adds the job at once
    h("label", { class: "field" }, h("span", { text: t("The posting, or a link to it") }), h("textarea", { name: "posting", "data-key": "j-posting", rows: 2, class: "short", placeholder: t("Paste the posting's text or its link"),
      onpaste: (e) => { const v = (e.clipboardData || window.clipboardData).getData("text").trim(); if (/^https?:\/\/\S+$/i.test(v)) { e.preventDefault(); e.target.value = v; form.requestSubmit(); } } })),
    h("div", {}, h("button", { class: "btn primary", type: "submit", text: t("Add the job") })));
  return form;                                                                      // in the view
}
async function makeForJob(jid) {                                                    // the automatic run for a job already added, followed on Make
  if (UI.makingFor) return;                                                         // a second press while the first is on its way queues nothing
  UI.makingFor = jid;                                                               // asked once
  try {
    const r = await act("/api/v1/autopilot", { job: jid, theme: UI.theme, max_pages: UI.maxPages });   // its documents from the facts kept
    if (!r) return;                                                                 // refused: act said why
    toast(r.queued ? t("It starts when the run in progress ends.") : r.started ? t("Started. About {m} min, nothing to click until it ends.", { m: r.estimate.minutes }) : t("It did not start. Try again."), null, r.queued || r.started ? "info" : "bad");   // as Make says it
    if (r.queued || r.started) go("make");                                          // where the run shows
  } finally { UI.makingFor = null; }
}
async function addJob(form) {                                                       // the form to the server
  const v = form.elements.posting.value.trim();                                     // the one box: a link or the posting
  const link = /^https?:\/\/\S+$/i.test(v);                                        // a link alone is fetched by the server
  const r = await act("/api/v1/jobs", link ? { url: v } : { posting: v }, t("Added. Its fit is below."));
  if (r && r.job) { UI.adding = false; forget("j-"); openApplication(r.job, "fit"); }   // the new job opens on its fit (the server put it in view)
}
// ---------------------------------------------------------------- the application's own questions (apps/api/answers.py)
const qCount = (text, unit) => (unit === "words" ? String(text || "").trim().split(/\s+/).filter(Boolean).length : [...String(text || "").trim()].length);   // as the form counts, and as the server does (apps/api/answers.py count): characters, not UTF-16 halves
const qUnit = (q) => (q.unit === "words" ? t("words") : t("characters"));       // the limit's unit
function issueWords(code) {                                                         // one problem of an answer, in words
  const [k, rest] = String(code).split(/:(.*)/s);                                   // its kind, and what it names
  const [n, lim] = String(rest || "").split("/");                                   // a length and its limit
  return { too_long: t("Over the limit: {n} of {limit}", { n, limit: lim }), too_short: t("Short: {n} of {limit}, room for more", { n, limit: lim }),
    unsupported: t("Not in your facts: {what}", { what: rest }), style: rest || t("Against your rules"), empty: t("Empty"), markup: t("Marks such as ** or # show as they are in a form's box."), agent_stopped: t("The agent stopped part way.") }[k] || code;
}
async function saveQuestions(j, list) {                                             // the job's questions, in order
  await act("/api/v1/jobs/questions", { job: j.id, questions: list.map((q) => ({ text: q.text, limit: q.limit, unit: q.unit })) });
}
function answerRow(j, q) {                                                          // one question: its answer, its length, its problems, its facts
  const key = `qa-${j.id}-${q.id}`;                                                 // the answer box
  const n = UI.typed[key] !== undefined ? qCount(UI.typed[key], q.unit) : q.count;  // its length as typed
  const counter = h("span", { class: "chip" + (n > q.limit ? " bad" : ""), text: `${n} / ${q.limit} ${qUnit(q)}` });
  const limits = [...new Set([...(q.unit === "words" ? [100, 150, 200, 250, 300, 500] : [300, 500, 700, 800, 1000, 1500, 2000]), q.limit])].sort((a, b) => a - b);   // a limit is chosen, never typed
  const limitPick = h("select", { class: "sel sm", "aria-label": t("Limit"), onchange: (e) => saveQuestions(j, (j.questions || []).map((x) => (x.id === q.id ? { ...x, limit: Number(e.target.value) } : x))) },
    limits.map((l) => h("option", { value: String(l), selected: l === q.limit || null, text: String(l) })));   // the number alone: the count beside it names the unit
  const box = h("textarea", { "data-key": key, rows: 6, placeholder: t("The answer appears here. You can also write it yourself."),
    oninput: (e) => { counter.textContent = `${qCount(e.target.value, q.unit)} / ${q.limit} ${qUnit(q)}`; counter.classList.toggle("bad", qCount(e.target.value, q.unit) > q.limit); },   // the count as it is typed
    onchange: (e) => act("/api/v1/jobs/questions/edit", { job: j.id, id: q.id, answer: e.target.value }).then(() => forget(key)) });   // saved and checked when the box is left
  box.value = UI.typed[key] !== undefined ? UI.typed[key] : q.answer || "";         // the words survive a redraw
  return h("article", { class: "qa" },
    h("div", { class: "qa-head" }, h("b", { text: q.text }), counter, limitPick,
      h("button", { class: "btn sm quiet", type: "button", onclick: () => saveQuestions(j, (j.questions || []).filter((x) => x.id !== q.id)) }, icon("close", 15), t("Remove the question"))),   // said in words
    box,
    (q.issues || []).length ? h("ul", { class: "problist" }, q.issues.map((i) => h("li", { class: "lit bad", text: issueWords(i) }))) : null,
    (q.cited || []).length ? h("p", { class: "hint", text: t("From your facts: {names}", { names: q.cited.map((c) => c.title).filter(Boolean).join(", ") }) }) : null,
    h("div", { class: "qa-keys" },
      h("button", { class: "btn sm", disabled: !agentOn() || task("answers:" + j.id).state === "running" || null, onclick: () => act("/api/v1/jobs/questions/write", { job: j.id, ids: [q.id] }) }, icon("refresh"), t("Write this one again")),
      q.answer ? h("button", { class: "btn sm", onclick: () => navigator.clipboard.writeText(q.answer).then(() => toast(t("Copied."), null, "done")) }, icon("copy"), t("Copy")) : null));
}
function questionsCard(j) {                                                         // the questions a form asks, with their limits, answered from the facts
  const qs = j.questions || [], tk = task("answers:" + j.id), busy = tk.state === "running";   // the questions, their task
  const add = h("form", { class: "qa-add", onsubmit: async (e) => { e.preventDefault();       // the form's questions, pasted as it shows them
    const text = String(UI.typed["qa-new"] || "").trim(); if (!text) { toast(t("Paste the questions first.")); return; }
    const r = await act("/api/v1/jobs/questions/paste", { job: j.id, text });          // read with their limits by the server
    if (r) { forget("qa-"); toast(tn(r.added, "{n} question added.", "{n} questions added."), null, "done"); } } },
    h("label", { class: "field wide" }, h("span", { text: t("The form's questions, as it shows them") }),
      h("textarea", { "data-key": "qa-new", rows: 3, placeholder: t("1. Why this company? (700 characters)"), oninput: (e) => { UI.typed["qa-new"] = e.target.value; },
        ondragover: (e) => e.preventDefault(), ondrop: (e) => { const f = e.dataTransfer.files[0]; if (f) { e.preventDefault(); e.stopPropagation(); questionsFromFile(j.id, f); } } })),   // a screenshot dropped on the box, and only here: the page's own drop would start a run with it
    h("div", { class: "qa-keys" }, h("button", { class: "btn", type: "submit" }, icon("check"), t("Read the questions")),
      h("button", { class: "btn", type: "button", onclick: () => { UI.formFor = j.id; $("formpick").click(); } }, icon("upload"), t("Read from a screenshot or a file"))));
  return h("section", { class: "qcard", "aria-label": t("Application questions") },   // inside the job's tab: no box of its own
    h("div", { class: "card-h" }, h("h3", { text: qs.length ? tn(qs.length, "{n} question", "{n} questions") : t("No questions yet") }), sentLine(agentOn()),   // a name before the chip that says where they go
      busy ? pill("busy", t("Writing {done} of {total}", { done: (tk.done || 0) + 1, total: tk.total || qs.length })) : null),
    qs.map((q) => answerRow(j, q)), add,
    qs.length ? h("div", { class: "nextkeys" },
      h("button", { class: "btn primary", disabled: busy || !agentOn() || null, onclick: () => act("/api/v1/jobs/questions/write", { job: j.id }) }, icon("edit"), qs.some((q) => q.answer) ? t("Write every answer again") : t("Write the answers")),
      qs.some((q) => q.answer) ? h("button", { class: "btn", onclick: () => navigator.clipboard.writeText(qs.filter((q) => q.answer).map((q, i) => `${i + 1}. ${q.text}\n\n${q.answer}`).join("\n\n")).then(() => toast(t("Copied."))) }, icon("copy"), t("Copy all")) : null,
      qs.some((q) => q.answer) ? h("button", { class: "btn", onclick: async () => { const r = await act("/api/v1/jobs/questions/export", { job: j.id }); if (r && r.exported && r.exported.length) toast(t("Saved to the Desktop: {name}", { name: r.exported[0] }), null, "done"); } }, icon("download"), t("Save to the Desktop")) : null) : null,
    tk.state === "error" ? band(tk.error.code, { retry: () => act("/api/v1/jobs/questions/write", { job: j.id }) }) : null);
}
function jobDetail(j, phone) {                                                      // one application: its head, its tabs and the part open (on a phone, the way back to the list)
  const f = fitOf(j.id);                                                            // its fit
  const tk = task("tailor:" + j.id);                                                // the tailor task
  const run = task("autopilot").state === "running";                                // a whole run goes now
  const tab = ["fit", "docs", "questions", "interview", "progress"].includes(UI.jobTab) ? UI.jobTab : "fit";  // the part shown
  const parts = [["fit", "Fit", 0], ["docs", "Documents", 0], ["questions", "Application questions", (j.questions || []).length], ["interview", "Interview", 0],
    ["progress", "Progress", (j.reminders || []).filter((r) => !r.done).length]];   // the job's parts, with a count where one asks for attention
  const keys = (e) => {                                                             // arrows, Home and End move between the parts, as the inspector's tabs do
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const i = parts.findIndex(([k]) => k === tab), n = parts.length;
    UI.jobTab = parts[e.key === "Home" ? 0 : e.key === "End" ? n - 1 : (i + (e.key === "ArrowRight" ? 1 : n - 1)) % n][0]; render();
    const b = $("jtab-" + UI.jobTab); if (b) b.focus();                             // the keyboard follows
  };
  const tabs = h("div", { class: "tabs jtabs", role: "tablist", "aria-label": t("This job"), onkeydown: keys }, parts.map(([k, w, n]) =>
    h("button", { role: "tab", id: "jtab-" + k, "aria-controls": "jpane", "aria-selected": tab === k ? "true" : "false", tabindex: tab === k ? "0" : "-1",
      onclick: () => { UI.jobTab = k; render(); } }, icon(JOB_TAB_ICON[k] || "file"),
      k === "questions" ? [h("span", { class: "w-l", text: t(w) }), h("span", { class: "w-s", text: t("Questions") })] : t(w),   // a phone shows the short name: five tabs on one row
      n ? h("span", { class: "chip count", text: String(n) }) : null)));
  return h("section", { class: "jobdetail paper", "aria-label": t("Fit to {job}", { job: j.company || j.id }) },
    phone ? h("div", { class: "jd-back" }, h("button", { class: "btn sm quiet", type: "button", onclick: () => { UI.jobPhone = false; UI.ivWide = false; localStore("offerowl-ivwide", ""); render(); } }, icon("back"), t("All applications"))) : null,   // back to the list: a phone's, or the wide view's
    h("header", { class: "jd-head" },
      mono(j.company || j.role || j.id, "lg", j.stage),                             // the company's mark, in its stage's colour
      h("div", { class: "jd-title" },
        h("div", { class: "jd-name" }, h("h2", { text: j.company || j.role || j.id }),   // the name, and on its line where it stands and how it fits: never pushed off by a long role
          h("button", { class: "pillkey", type: "button", onclick: () => { UI.jobTab = "progress"; render(); }, title: t("Progress") }, stagePill(j)),   // where it stands, opening its progress
          f && !(f.lines || []).length ? null                                        // no line of the posting could be rated: no score to show (the Fit tab says why)
            : h("div", { class: "jd-score", role: "img", "aria-label": t("Fit {n} of 100", { n: f ? f.score : 0 }) }, h("span", { class: "hint", text: t("Fit") }),
              h("b", { text: String(f ? f.score : "…") }), h("small", { text: "/ 100" }))),
        j.company && j.role ? h("span", { class: "ro", text: j.role }) : null),
      h("span", { class: "grow" }),
      h("div", { class: "jd-acts" },
        j.locked ? h("button", { class: "btn", type: "button", onclick: () => { UI.doc = "resume"; go("documents"); }, text: t("See what was sent") })   // submitted: its documents are the sent copies, kept as they went
        : h("button", { class: j.stage === "result" || tab === "interview" || tab === "progress" ? "btn" : "btn primary", "data-act": "job-make", disabled: tk.state === "running" || run || null, onclick: () => makeForJob(j.id),   // the main key, unless the tab has its own (Practice, Remind me) or the application ended: one main key in sight
          text: run ? t("A run is going") : t("Make this job's documents") }))),
    todayBand(j, tab),                                                              // a round today: its hour, the time left, its call's link; once it ends, the questions to write down
    tabs,
    h("div", { class: "jd-body", role: "tabpanel", id: "jpane", "aria-labelledby": "jtab-" + tab }, tab === "fit" ? fitPart(j, f) : tab === "docs" ? docsPart(j, tk) : tab === "questions" ? questionsCard(j)
      : tab === "interview" ? interviewPart(j) : progressPart(j)));
}
function fitPart(j, f) {                                                            // the posting line by line: a row each, its evidence when opened
  if (!f || f.error) return h("p", { class: "hint", text: t("Working out the fit…") });   // loading, or refused for now (asked again with the next revision)
  if (!f.lines.length) return h("form", { class: "posting-again", onsubmit: async (e) => { e.preventDefault();   // no line found: the part with the duties pasted here, read again at once
      const box = e.target.elements.posting, v = box.value.trim();
      if (v.length < 20) { box.setCustomValidity(t("Paste the part of the posting with its duties and requirements.")); box.reportValidity(); return; }
      if (await act("/api/v1/jobs/posting", { job: j.id, posting: v }, t("The posting is read again."))) forget(`fit-posting-${j.id}`); } },
    h("p", { class: "hint", text: t("Offerowl found no duty or requirement lines in this posting. Paste the part with the duties and requirements.") }),
    h("label", { class: "field" }, h("span", { text: t("The posting's duties and requirements") }),
      h("textarea", { name: "posting", "data-key": `fit-posting-${j.id}`, rows: 5, class: "short", placeholder: t("Paste the part of the posting with its duties and requirements."),
        oninput: (e) => e.target.setCustomValidity("") })),
    h("div", { class: "part-keys" }, h("button", { class: "btn primary", type: "submit", text: t("Read the posting again") }), sentLine(false)));
  const want = ["strong", "weak", "none"].includes(UI.fitFilter) ? UI.fitFilter : "all";   // the rating shown
  const lines = f.lines.map((ln, i) => ({ ln, i })).filter(({ ln }) => want === "all" || ln.rating === want);   // the lines of that rating, with their place
  const groups = [];                                                                // the posting's own sections, in its order
  for (const x of lines) { const g = groups[groups.length - 1]; if (g && g.sec === (x.ln.section || "")) g.items.push(x); else groups.push({ sec: x.ln.section || "", items: [x] }); }
  return h("div", { class: "fitpart" },
    h("div", { class: "fit-viz" },                                                  // the posting's lines by how well the evidence answers them (the score is in the head)
      segBar(["strong", "weak", "none"].map((k) => ({ n: f.counts[k] || 0, words: t(RATING_WORD[k]), color: RATING_COLOR[k] })), { label: t("The posting's lines"), id: "fit-" + j.id })),
    h("div", { class: "fit-tools" },
      h("div", { class: "seg", "aria-label": t("Show") }, [["all", t("All {n}", { n: f.lines.length })], ...["strong", "weak", "none"].map((k) => [k, t(RATING_COUNT[k], { n: f.counts[k] })])].map(([k, w]) =>
        h("button", { "aria-pressed": want === k ? "true" : "false", onclick: () => { UI.fitFilter = k; render(); } }, k !== "all" ? h("span", { class: "lit " + RATING_CLS[k], "aria-hidden": "true" }) : null, w))),
      sentLine(false, t("Each line of the posting, rated by the evidence in your profile. Worked out on this PC by words; no agent is asked."))),   // worked out here: the state as the other parts mark it, its sentence on the hover
    groups.map((g) => h("section", { class: "fl-group", "aria-label": g.sec || t("The posting, line by line") },
      g.sec ? h("h3", { class: "fl-sec", text: g.sec }) : null,
      h("ul", { class: "fl-rows" }, g.items.map(({ ln, i }) => fitLine(j, ln, i))))),
    lines.length ? null : h("p", { class: "hint", text: t("No line of this kind.") }),
    f.gaps.length && want !== "strong" ? h("div", { class: "band gaps" }, h("b", {}, h("span", { class: "lit bad", "aria-hidden": "true" }), t("Gaps")),
      f.gaps.some((g) => /\s/.test(g)) ? h("ul", {}, f.gaps.filter((g) => /\s/.test(g)).map((g) => h("li", { text: g }))) : null,   // a requirement in words, one a line
      f.gaps.some((g) => !/\s/.test(g)) ? h("div", { class: "gap-words" }, f.gaps.filter((g) => !/\s/.test(g)).map((g) => h("span", { class: "chip", text: g }))) : null,   // a single term (UNIX, gcc): side by side
      h("span", { class: "hint", text: t("Add a fact to your profile if you have done this; the documents never claim what the evidence does not hold.") })) : null);
}
function fitLine(j, ln, i) {                                                        // one line of the posting: its rating and words; its evidence when opened
  const key = `${j.id}|${i}`, open = UI.lineOpen === key;                          // which line is open
  const n = ln.evidence.length;                                                     // how much evidence speaks to it
  return h("li", { class: "fl" + (open ? " open" : "") },
    h("button", { class: "fl-row", type: "button", "aria-expanded": open ? "true" : "false", onclick: () => { UI.lineOpen = open ? null : key; render(); } },
      pill(RATING_CLS[ln.rating], t(RATING[ln.rating])), h("span", { class: "fl-txt", text: ln.text }),
      h("span", { class: "fl-n", text: !n ? t("No evidence") : ln.rating === "none" ? tn(n, "{n} source, not enough", "{n} sources, not enough") : tn(n, "{n} source", "{n} sources") })),   // a line not met says its sources fall short
    open ? h("div", { class: "fl-ev" }, n ? ln.evidence.slice(0, 3).map((e) => h("div", { class: "note" }, h("q", { text: unmarked(e.quote) }),
      h("span", { class: "from", text: [WHERE[e.where] ? t(WHERE[e.where]) : e.where, e.file ? t("From {file}", { file: e.file }) : ""].filter(Boolean).join(", ") })))
      : h("p", { class: "hint", text: t("No evidence in your profile covers this line.") }),
      ln.missing && ln.missing.length ? h("p", { class: "hint", text: t("Not shown anywhere: {words}", { words: ln.missing.join(", ") }) }) : null) : null);
}
function docsPart(j, tk) {                                                          // this application's documents: what each one holds now, and the key that opens it
  const ap = task("autopilot"), making = ap.state === "running" && ap.job === j.id;   // a run makes them now
  const iv = boardOf(j.id);                                                         // the interview kit's board (null while it loads)
  const qs = j.questions || [], answered = qs.filter((q) => q.answer).length;       // the form's questions and the answers written
  const built = (lang) => (j.builds || {})[lang] || {};                             // an edition's record, or nothing before its first PDFs
  const made = (n, one, many) => (n ? h("span", { class: "dp-v", text: tn(n, one, many) }) : h("span", { class: "dp-v none", text: t("Not made yet") }));   // a count, or that there is none
  const openDoc = (doc) => { UI.doc = doc; UI.sel = null; if (S.job !== j.id) { S.job = j.id; act("/api/v1/jobs/select", { job: j.id }); } go("documents"); };   // on the canvas, this job's edition
  const key = (fn, words) => h("button", { class: "btn sm", type: "button", onclick: fn, text: t(words || "Open") });   // a row's key: what it does, "Open" when there is something to open
  const row = (name, cells, fn, words) => h("div", { class: "dp", role: "row" }, h("b", { role: "rowheader", text: name }), cells, key(fn, words));   // one document: its name, a cell per language or one across, its key
  const langs = [["ko", t("Korean")], ["en", t("English")]];                        // the editions' columns
  return h("div", { class: "docpart" },
    making ? h("div", { class: "band info", role: "status" }, pill("busy", t("A run is making these documents")),
      h("button", { class: "btn small", onclick: () => go("make"), text: t("Follow it on Make") })) : null,
    tk.state === "running" ? h("div", { class: "band info", role: "status" }, pill("busy", t(STEP_WORDS[tk.step] || "Working"))) : null,   // tailored from the cover letter's tab
    h("div", { class: "docparts", role: "table", "aria-label": t("Documents") },
      h("div", { class: "dp head", role: "row" }, h("span", { role: "columnheader", text: t("Document") }), langs.map(([, w]) => h("span", { role: "columnheader", text: w })), h("span", { "aria-hidden": "true" })),
      row(t("Resume"), langs.map(([l]) => made(built(l).pages, "{n} page", "{n} pages")), () => openDoc("resume")),
      row(t("Portfolio deck"), langs.map(([l]) => made(built(l).slides, "{n} slide", "{n} slides")), () => openDoc("deck")),
      row(t("Cover letter"), langs.map(([l]) => made((built(l).cover || {}).pages, "{n} page", "{n} pages")), () => openDoc("cover"),
        langs.some(([l]) => (built(l).cover || {}).pages) ? null : "Write it"),   // not made yet: the key says what it leads to
      row(t("Application questions"), h("span", { class: "dp-v across" + (qs.length ? "" : " none"), text: qs.length ? t("{a} of {n} answered", { a: answered, n: qs.length }) : t("No questions yet") }),
        () => { UI.jobTab = "questions"; render(); }, qs.length ? "" : "Add questions"),
      row(t("Interview kit"), h("span", { class: "dp-v across" + (iv && iv.ready ? "" : " none"), text: !iv ? t("Reading the interview kit…") : iv.ready ? t("{q} questions, {s} scripts", { q: iv.counts.questions, s: iv.counts.scripts }) : t("Not made yet") }),
        () => { UI.jobTab = "interview"; render(); }, iv && !iv.ready ? "Make the kit" : "")),
    tk.state === "error" ? band(tk.error.code, { retry: () => tailorJob(j.id) }) : null,
    tk.state === "done" && tk.result && (tk.result.stopped || []).length ? band("agent_stopped", { retry: () => tailorJob(j.id) }) : null);  // part of it did not come back: the same band, with a retry
}
const STEP_WORDS = { queued: "Starting", waiting_turn: "Waiting for the task before it to finish", writing_resume: "Writing the resume from your evidence", drawing_figures: "Drawing the figures from your evidence", analysis: "Ordering the resume for this job", asking_agent: "Asking the agent", matching_words: "Matching the posting by its words",  // what a running task is doing now
  typesetting_resume: "Typesetting the resume", writing_cover: "Writing the cover letter", typesetting_cover: "Typesetting the cover letter", interview_kit: "Making the interview questions" };
function tailorJob(jid) {                                                           // one action for all three documents
  return act("/api/v1/jobs/tailor", { job: jid, lang: docLang(), theme: UI.theme, maxPages: UI.maxPages, cover: UI.cover, typeset: UI.typeset && !S.engine });
}

// ---------------------------------------------------------------- the interview studio's entry

function boardOf(jid) {                                                             // the studio's board of a job, per revision; the last one stands while a newer one loads
  const fam = `iv|${jid}|${docLang()}`, key = `${fam}|${rev()}`;                    // per revision: any task's step or autosave makes a new one
  UI.boards = UI.boards || {};                                                      // the last board of each job and language
  if (UI.docs[key] && !UI.docs[key].error) UI.boards[fam] = UI.docs[key];           // kept as the one to show next time
  if (!UI.docs[key]) {                                                              // fetched once per revision; the older revisions' copies go
    for (const k of Object.keys(UI.docs)) if (k.startsWith(fam + "|") && k !== key) delete UI.docs[k];
    getDoc(key, `/api/v1/jobs/${enc(jid)}/interview?lang=${docLang()}`);
  }
  return UI.docs[key] || UI.boards[fam] || null;                                    // null only the first time: a part on screen never gives way to "Reading…" for a newer board
}
function speech(text) {                                                             // a scripted line with its speech marks drawn as the interview view draws them
  const thought = (part) => {                                                       // one thought: stress, the key phrase and breaths
    const out = [];                                                                 // nodes
    part.split(/(\s\/\s|==[^=]+==|\*\*[^*]+\*\*|`[^`]+`|\([^()]*[\uac00-\ud7a3][^()]*\))/).forEach((p) => {   // breath, key phrase, stress, code, a stage note
      if (p === " / ") out.push(" ", h("span", { class: "br", "aria-hidden": "true", text: "/" }), " ");  // a short breath: a faint slash
      else if (/^==[^=]+==$/.test(p)) out.push(h("mark", { class: "hl" }, thought(p.slice(2, -2))));   // the key phrase: its stress and breaths drawn too, never its marks
      else if (/^\*\*[^*]+\*\*$/.test(p)) out.push(h("strong", { text: p.slice(2, -2) }));         // stress
      else if (/^`[^`]+`$/.test(p)) out.push(h("code", { text: p.slice(1, -1) }));                  // a command or a file name, in its own letters
      else if (/^\([^()]*[\uac00-\ud7a3][^()]*\)$/.test(p)) out.push(h("span", { class: "dir", text: p }));   // a stage note in Korean brackets: not spoken, in grey as the kit draws it
      else if (p) out.push(document.createTextNode(p));                             // plain words
    });
    return out;                                                                     // for the thought's line
  };
  const parts = String(text || "").split(/\s+\/\/\s*/).filter((p) => p.trim());     // ' // ' ends a thought
  return parts.length > 1 ? parts.map((p) => h("span", { class: "th" }, thought(p))) : thought(parts[0] || "");  // a line per thought
}
const JOB_TAB_ICON = { fit: "check", docs: "file", questions: "edit", interview: "chat", progress: "clock" };   // each tab of an application, its mark
const RATING_WORD = { strong: "Met", weak: "In part", none: "Not met" };           // a rating in words, for the figures' legends (as Insights says it)
const RATING_COLOR = { strong: "var(--met-strong)", weak: "var(--met-weak)", none: "var(--met-none)" };   // its colour, as its lamp
const COVERAGE = { strong: "A script answers it", weak: "A script answers part of it", none: "No script yet", draft: "A draft by the agent answers it" };  // a question's lamp, in words
const COVERAGE_CLS = { strong: "ok", weak: "warn", none: "off", draft: "ai" };     // its lamp: a question with no script yet is still to do, not stopped
function interviewPart(j) {                                                         // an application's interview: its question board, then its scripts beside the one read, then the person's own materials
  const b = boardOf(j.id);                                                          // its board
  const practice = !!(b && b.ready && b.practice && b.practice.available);       // practice can start: the tab's main key
  // the keys of the part in view only: the wide view and a window beside the search, the deck's print beside the deck, the
  // cue cards and scenes beside the scripts; Practice, the tab's main key, on every part but the practice and the talk.
  // Every part is drawn in the panel (kit.js, interview.js); only the print keys open the kit's printable pages
  const wideKeys = PHONE.matches ? null : [                                            // a phone shows one application alone already
    h("button", { class: "btn", type: "button", "data-key": "iv-wide", "aria-pressed": ivWide() ? "true" : "false", onclick: () => { UI.ivWide = !ivWide(); localStore("offerowl-ivwide", UI.ivWide ? "1" : ""); render(); } }, icon("wide"), t("Wide view")),
    h("button", { class: "btn", type: "button", onclick: () => window.open(`/?job=${enc(j.id)}&show=scripts`, "_blank", "noopener") }, icon("open"), t("Open in a window"))];   // the panel itself, on the scripts
  const keysFor = (part) => h("div", { class: "part-keys" },
    b && b.ready && part === "search" ? wideKeys : null,                              // the scripts over the whole width, and in a window of their own: both stay in the panel
    b && b.ready && part === "deck" && b.deck && b.deck.available ? h("button", { class: "btn", onclick: () => openKit(j.id, "deck?lang=" + LANG) }, icon("slides"), t("Interview deck to print")) : null,   // the deck's printable pages in the panel's language
    b && b.ready && part === "map" && b.cue && b.cue.available ? h("button", { class: "btn", onclick: () => openKit(j.id, "cue") }, icon("copy"), t("Cue cards to print")) : null,
    !(b && b.ready) || part === "map" ? h("button", { class: "btn", onclick: () => { UI.scenesFor = j.id; $("scenepick").click(); } }, icon("upload"), t("Add scenes you wrote")) : null,   // scripts written before, in the kit's markdown
    practice && part !== "talk" && part !== "practice" ? h("button", { class: "btn primary", onclick: () => { UI.ivPart = "practice"; render(); } }, icon("mic"), t("Practice")) : null);   // the main key, last: the practice part
  const keys = keysFor(null);                                                        // before the kit: what can be added already
  if (!b || b.error) return h("div", { class: "ivpart" }, keys, h("p", { class: "hint", text: t("Reading the interview kit…") }), materialsPart(j));   // loading, or refused for now (never read as "no kit"); the materials need no kit
  if (!b.ready && UI.ivPart === "talk") return h("div", { class: "ivpart" }, keys, talkPart(j), materialsPart(j));   // a talk needs no question map
  if (!b.ready) return h("div", { class: "ivpart" }, keys, h("div", { class: "empty glass" }, h("h3", { text: t("No interview kit for this job yet") }),
    h("p", { text: t("The question map comes from the posting and your resume, on this PC. Scripts are written by the agent.") }),
    sendNote(t("Tailoring sends the posting and your evidence to the agent.")),
    h("div", { class: "part-keys" }, h("button", { class: "btn", onclick: () => makeForJob(j.id), text: t("Make this job's documents") }),
      h("button", { class: "btn", onclick: () => { UI.ivPart = "talk"; render(); }, text: t("Prepare a presentation") }),   // a talk the interviewers asked for, without the map
      h("button", { class: "btn primary", onclick: () => act("/api/v1/interview/kit", { job: j.id, lang: docLang() }), text: t("Make the question map") }))), materialsPart(j));
  const tk = task("scripts:" + j.id);                                                // the writing task, when one runs
  const writing = tk.state === "running";                                           // writing now
  const parts = [["search", t("Search the scripts"), "search"], ["deck", t("Interview deck"), "slides"], practice ? ["practice", t("Practice"), "mic"] : null,
    ["map", t("Question map and scripts"), "map"], ["talk", t("Presentation"), "chart"]].filter(Boolean);   // practice when the kit has it
  const part = parts.some(([k]) => k === UI.ivPart) ? UI.ivPart : "search";         // what the tab shows: the search view, the deck, practice, the map and its scripts, or the talk
  const switcher = h("div", { class: "seg ivseg", role: "tablist", "aria-label": t("Interview") },
    parts.map(([k, w, ic]) => h("button", { type: "button", role: "tab", "aria-selected": part === k ? "true" : "false", onclick: () => { UI.ivPart = k; render(); } }, icon(ic), w)));
  if (part === "talk") return h("div", { class: "ivpart" }, h("div", { class: "ivtop" }, switcher, keysFor(part)), talkPart(j), materialsPart(j));   // the presentation interview
  if (part !== "map") return h("div", { class: "ivpart" }, h("div", { class: "ivtop" }, switcher, keysFor(part)),
    part === "deck" ? ivDeck(j) : part === "practice" ? ivPractice(j) : ivKit(j),   // each drawn by the panel itself: the deck and practice (interview.js), the contents, the search and the scripts (kit.js)
    materialsPart(j));                                                              // and the person's own files for this job under them, as on every part
  return h("div", { class: "ivpart" }, h("div", { class: "ivtop" }, switcher, keysFor(part)),
    h("p", { class: "hint", text: t("{q} likely questions, {u} without a script yet, {s} scripts.", { q: b.counts.questions, u: b.counts.uncovered, s: b.counts.scripts }) +
      (b.counts.drafted ? " " + t("{n} of them are drafts by the agent.", { n: b.counts.drafted }) : "") }),
    S.agent.state === "ready" && b.counts.uncovered > 0 ? h("div", { class: "band info" },   // a submitted application still gets ready for its interview
      h("button", { class: "btn" + (practice ? " agent" : " primary"), disabled: writing || null, onclick: () => act("/api/v1/interview/scripts", { job: j.id, lang: docLang() }) }, icon("agent"), writing ? t("Writing…") : t("Write 10 more scripts")),
      writing ? h("span", { class: "hint", role: "status", text: t("{done} of {total} written. The search view shows each one as it is finished.", { done: tk.done || 0, total: tk.total || 0 }) })
        : h("span", { class: "hint", text: t("The likeliest questions come first. It takes the agent about ten minutes.") })) : null,
    tk.state === "done" && tk.result && tk.result.stopped ? band("agent_stopped", { retry: () => act("/api/v1/interview/scripts", { job: j.id, lang: docLang() }) }) : null,
    tk.state === "error" ? band(tk.error.code, { retry: () => act("/api/v1/interview/scripts", { job: j.id, lang: docLang() }) }) : null,
    h("div", { class: "qboard" }, b.categories.map((c) => h("section", { class: "qcol glass", "aria-label": t(CATEGORY[c.kind] || c.kind) },
      h("div", { class: "card-h" }, h("h3", { text: t(CATEGORY[c.kind] || c.kind) }), h("span", { class: "chip count", text: String(c.questions.length) })),
      segBar([["strong", "var(--green)"], ["draft", "var(--orange)"], ["weak", "var(--amber)"], ["none", "var(--rule-2)"]].map(([k, color]) =>   // how many of its questions a script answers
        ({ n: c.questions.filter((q) => (q.coverage || "none") === k).length, words: t(COVERAGE[k]), color })), { label: t(CATEGORY[c.kind] || c.kind), id: "cov-" + c.kind, compact: true }),
      h("ol", {}, c.questions.slice(0, 5).map((q) => h("li", {}, h("span", { class: "lit " + (COVERAGE_CLS[q.coverage] || "off"), title: t(COVERAGE[q.coverage] || COVERAGE.none) }, h("span", { class: "sr", text: t(COVERAGE[q.coverage] || COVERAGE.none) })),
        h("span", { text: (docLang() === "en" ? q.ask_en : q.ask_ko) || q.text })))),
      c.questions.length > 5 ? h("span", { class: "hint", text: t("and {n} more in the search view", { n: c.questions.length - 5 }) }) : null))),
    b.scripts.length ? scriptsPart(b.scripts) :
      h("div", { class: "empty glass" }, h("h3", { text: t("No scripts yet") }), h("p", { text: S.agent.state === "ready" ? t("Write scripts to let the agent answer the likeliest questions first.") : t("Scripts are written by the agent. Turn it on to draft them.") })),
    materialsPart(j));                                                              // the person's own files, under what the kit made
}

// ---------------------------------------------------------------- an application's own materials (apps/api/materials.py): decks, notes, briefs, answers and code, kept as they came

const MAT_KINDS = /\.(pdf|pptx|docx|md|html|txt|py|png|jpe?g)$/i;                 // what a job keeps: the server's own list (a .jpeg is kept as .jpg)
const MAT_MAX = 50 * 1000 * 1000;                                                   // bytes of one file, as the server caps it
const MAT_KIND = [["pdf", "PDF"], ["pptx", "PowerPoint"], ["docx", "Word"], ["md", "Markdown"], ["html", "Web page"], ["txt", "Text"], ["py", "Python"],  // each kind in words
  ["png", "Picture"], ["jpg", "Picture"]];
function matKind(k) { const x = MAT_KIND.find(([key]) => key === k); return x ? t(x[1]) : k; }   // a kind in the page's language
function matSize(n) {                                                               // a size as people say it: kilobytes, or megabytes with one decimal under ten
  if (n < 1000 * 1000) return t("{n} KB", { n: Math.max(1, Math.round(n / 1000)) });   // a few bytes still read as 1 KB
  return t("{n} MB", { n: (n / 1000 / 1000).toFixed(n < 10 * 1000 * 1000 ? 1 : 0) });
}
const matUrl = (jid, mid) => `/api/v1/jobs/${enc(jid)}/materials/${mid}`;          // one material's address
function materialsPart(j) {                                                         // the files the person brought in for this job: a place to drop them, then a row each
  const list = j.materials || [];                                                   // in the order they came
  const sending = UI.matSending && UI.matSending.job === j.id ? UI.matSending : null;   // an upload of this job in progress
  const zone = h("div", { class: "drop mat-drop", role: "group", "aria-label": t("Add materials") },
    h("strong", { text: sending ? t("Adding {done} of {total} files…", { done: sending.done, total: sending.total }) : t("Drop files here") }),
    h("span", { class: "hint", text: t("PDF, PowerPoint, Word, Markdown, HTML, text, Python, PNG or JPG, up to 50 MB each") }),
    h("button", { class: "btn", type: "button", disabled: sending || null, onclick: () => { UI.matFor = j.id; $("matpick").click(); } }, icon("upload"), t("Choose files")));
  const sec = h("section", { class: "mats", "aria-label": t("Your materials") },
    h("div", { class: "card-h" }, h("h2", { class: "scripts-h", text: t("Your materials") }), list.length ? h("span", { class: "chip count", text: String(list.length) }) : null, sentLine(false)),
    zone,
    list.length ? h("ul", { class: "mat-rows", "aria-label": t("Your materials") },   // the files: the columns' names, then a row each
      h("li", { class: "mt head", "aria-hidden": "true" }, h("div", { class: "mt-row" }, h("span", { text: t("Name") }), h("span", { text: t("Kind") }),
        h("span", { text: t("Size") }), h("span", { text: t("Added") }))),
      list.map((m) => matRow(j, m))) : null);
  sec.addEventListener("dragover", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); zone.classList.add("over"); } });   // files held over the part: they come here
  sec.addEventListener("dragleave", (e) => { if (!sec.contains(e.relatedTarget)) zone.classList.remove("over"); });   // moved away from the whole part
  sec.addEventListener("drop", async (e) => {                                       // dropped here: this job's materials, not a run of Make
    if (!e.dataTransfer || !e.dataTransfer.files.length) return;                    // not files
    e.preventDefault(); e.stopPropagation(); zone.classList.remove("over");         // the page's own drop would read them as your career files
    addMaterials(j.id, await droppedFiles(e.dataTransfer, /./, () => true));        // folders walked; each file's kind is checked when it is sent
  });
  return sec;
}
function matRow(j, m) {                                                             // one material: its name, kind, size and day; opened, its preview and its keys
  const key = `${j.id}|${m.id}`, open = UI.matOpen === key;                         // which one is open
  return h("li", { class: "mt" + (open ? " open" : "") },
    h("button", { class: "mt-row", type: "button", "aria-expanded": open ? "true" : "false", onclick: () => { UI.matOpen = open ? null : key; render(); } },
      h("b", { class: "mt-name", text: m.title }), h("span", { class: "mt-kind", text: matKind(m.kind) }),
      h("span", { class: "mt-size", text: matSize(m.size) }), h("span", { class: "mt-day", text: m.added })),
    open ? matView(j, m) : null);                                                   // the preview under its row
}
function matView(j, m) {                                                            // an open material: what to do with it, then what it holds
  const key = `mat|${j.id}|${m.id}|${m.sha256}`;                                    // its preview, fetched once
  if (!UI.docs[key]) getDoc(key, matUrl(j.id, m.id) + "/preview");                 // a deck takes a few seconds the first time
  return h("div", { class: "mt-view", role: "region", "aria-label": m.title },
    h("div", { class: "part-keys" },
      h("a", { class: "btn sm", href: matUrl(j.id, m.id), target: "_blank", rel: "noopener" }, icon("open"), t("Open the file")),   // the browser shows it, or saves it
      h("button", { class: "btn sm", type: "button", onclick: () => saveMaterial(j.id, m) }, icon("desktop"), t("Save to the Desktop")),   // the Desktop's own sign, as the Library and Export carry it
      h("button", { class: "btn sm quiet danger", type: "button", onclick: () => removeAct("/api/v1/jobs/materials/remove", { job: j.id, id: m.id }, t("Removed {name}.", { name: m.title })) }, t("Remove"))),
    matBody(j, m, UI.docs[key] || null));
}
function matBody(j, m, p) {                                                         // what a material holds, drawn by its kind; the person's words are always set as text
  if (!p) return h("p", { class: "hint", role: "status", text: t("Making the preview…") });   // on its way
  if (p.error || p.missing) return h("p", { class: "hint", text: { no_tools: t("Its pages cannot be shown on this PC. Open the file instead."),   // why, and the key above that still works
    too_large: t("This file is too large to show here. Open the file instead.") }[p.missing] || t("This file cannot be shown here. Open the file instead.") });
  const cut = p.cut ? h("p", { class: "hint", text: t("The preview shows the start of the file. Open the file to read it all.") }) : null;   // a long text file
  if (p.view === "pages") return [p.more ? h("p", { class: "hint", text: p.of > p.pages ? t("The preview shows the first {n} of {m} pages.", { n: p.pages, m: p.of })
    : t("The preview shows the first {n} pages.", { n: p.pages }) }) : null,
  h("div", { class: "shots" + (p.wide ? " deck" : "") }, Array.from({ length: p.pages }, (_, i) =>   // every page drawn, read as they load
    h("img", { src: `${matUrl(j.id, m.id)}/pages/${i + 1}.png`, loading: "lazy", alt: t("{doc}, page {n} of {m}", { doc: m.title, n: i + 1, m: p.of }) })))];
  if (p.view === "image") return h("img", { class: "mat-pic", src: matUrl(j.id, m.id), alt: m.title });   // the picture itself
  if (p.view === "text") return [h("textarea", { class: "mat-raw" + (m.kind === "py" ? " code" : ""), readonly: true, spellcheck: "false", "aria-label": m.title,   // as written, to read and copy
    rows: Math.min(18, Math.max(4, String(p.text || "").split("\n").length + 1)) }, p.text), cut];   // as tall as the file, up to a screenful; it scrolls past that
  if (p.view === "blocks") return [h("div", { class: "mat-doc" }, matBlocks(p.blocks)), cut];   // a note's headings, lists, tables and code
  if (p.view === "frame") return h("iframe", { class: "mat-frame", sandbox: "", title: m.title, srcdoc: p.html, referrerpolicy: "no-referrer" });   // a saved page that runs nothing
  return null;                                                                      // a view this page does not know
}
function matBlocks(blocks) {                                                        // a note's blocks as text: headings, paragraphs, list items, tables, quotes, code and rules
  const out = [];                                                                   // the nodes in order
  let table = null;                                                                 // the table rows are going into
  for (const b of blocks || []) {                                                   // each block the server read
    if (b.t !== "row") table = null;                                                // a table ends where its rows do
    if (b.t === "h") out.push(h(b.n <= 2 ? "h3" : "h4", { text: b.text }));         // two sizes of heading are enough in a preview
    else if (b.t === "p") out.push(h("p", {}, linked(b.text)));                      // a paragraph, its links live
    else if (b.t === "li") out.push(h("div", { class: "mli", style: `--d:${b.depth || 0}` }, h("span", { class: "mk", "aria-hidden": "true", text: b.mark || "•" }), h("span", {}, linked(b.text))));   // a list item, stepped in by its depth
    else if (b.t === "quote") out.push(h("blockquote", {}, linked(b.text)));         // a quote
    else if (b.t === "code") out.push(h("pre", { class: "mat-code", "aria-label": t("Code") }, h("code", { text: b.text })));   // code as written, to read: a block of the page, not a box to type in
    else if (b.t === "hr") out.push(h("hr", {}));                                   // a rule between parts
    else if (b.t === "row") {                                                       // a table row
      if (!table) { table = h("table", {}); out.push(h("div", { class: "mtab" }, table)); }   // a table starts, in a box that scrolls when it is wide
      table.append(h("tr", {}, (b.cells || []).map((c) => h(b.head ? "th" : "td", { text: c }))));   // its cells
    }
  }
  return out;
}
async function addMaterials(jid, files) {                                           // files into a job's materials, one request each; what stayed out is said
  if (UI.matSending) { toast(t("Wait until the files are sent.")); return; }        // one send at a time
  if (!files.length) return;                                                        // nothing dropped
  const said = [];                                                                  // why a file stayed out, one sentence each
  const refused = (f, why) => said.push(why === "kind" ? t("{name} was not added: this kind of file is not kept.", { name: f.name })
    : why === "empty" ? t("{name} could not be added: the file is empty.", { name: f.name })
      : why === "large" ? t("{name} could not be added: it is larger than 50 MB.", { name: f.name }) : t("{name} could not be added.", { name: f.name }));
  const take = [];                                                                  // what the server keeps
  for (const f of files) {                                                          // checked here first, so nothing is sent for nothing
    if (!MAT_KINDS.test(f.name)) refused(f, "kind"); else if (!f.size) refused(f, "empty"); else if (f.size > MAT_MAX) refused(f, "large"); else take.push(f);
  }
  UI.matSending = { job: jid, done: 0, total: take.length };                        // the drop zone says how far
  render();
  let added = 0;                                                                    // kept
  for (const f of take) {                                                           // in order
    try {
      const r = await postFile(`/api/v1/jobs/materials?job=${enc(jid)}`, f);        // the raw file and its own name, asked again while the server is busy
      const j = await r.json().catch(() => ({}));                                   // a refused upload may not answer with JSON
      if (r.ok) added++; else refused(f, j.error === "material_kind" ? "kind" : j.error === "empty" ? "empty" : r.status === 413 ? "large" : "");
    } catch (_) { refused(f, ""); }                                                 // the server stopped: the band says so
    UI.matSending.done++;                                                           // one more
    render();
  }
  UI.matSending = null;                                                             // done
  toast([added ? tn(added, "{n} file added.", "{n} files added.") : "", said[0] || "",   // what came in, and the first reason one did not
    said.length > 1 ? tn(said.length - 1, "{n} more file was not added.", "{n} more files were not added.") : ""].filter(Boolean).join(" "), null, added ? (said.length ? "warn" : "done") : "bad");
  refresh();                                                                        // the list shows them
}
async function saveMaterial(jid, m) {                                               // a copy on the Desktop, byte for byte
  const r = await act("/api/v1/jobs/materials/export", { job: jid, id: m.id });     // refused when the file changed since it came in
  if (r && r.exported && r.exported.length) toast(t("Saved to the Desktop: {name}", { name: r.exported[0] }), null, "done");
}
function scriptsPart(list) {                                                        // the scripts: every title on the left, the one open read on the right
  const at = Math.min(Math.max(0, UI.scriptOpen || 0), list.length - 1);            // the open one, within range
  const s = list[at];                                                               // its scenes
  return h("section", { class: "scripts", "aria-label": t("Script cards") },
    h("h2", { class: "scripts-h", text: t("Script cards") }),
    h("nav", { class: "scriptlist paper", "aria-label": t("Script cards") }, list.map((x, i) => h("button", { class: "scriptrow", "aria-current": i === at ? "true" : "false",
      onclick: () => { UI.scriptOpen = i; render(); } },
      h("b", { text: x.title_en || x.title_ko }), x.title_en && x.title_ko ? h("span", { class: "ro", text: x.title_ko }) : null,
      x.draft ? h("span", { class: "chip ai", text: t("Draft by the agent") }) : null))),
    h("article", { class: "script paper", "aria-label": s.title_en || s.title_ko },
      h("div", {}, h("div", { class: "t-en", text: s.title_en || s.title_ko }), s.title_en && s.title_ko ? h("div", { class: "t-ko", text: s.title_ko }) : null,
        s.draft ? h("span", { class: "chip ai", text: t("Draft by the agent") }) : null),
      s.key ? h("p", { class: "key" }, h("b", { text: t("Key") + " " }), speech(s.key)) : null,
      s.turns.map((tn) => h("div", { class: "turn " + tn.who }, h("span", { class: "who", text: tn.who === "me" ? t("You") : t("Interviewer") }),
        h("span", { class: "en" }, speech(tn.en)))),
      s.turns.some((tn) => tn.ko) ? h("div", { class: "notes", "aria-label": t("Translation") },   // the translation after the dialogue, as a note: the spoken lines come first
        s.turns.filter((tn) => tn.ko).map((tn) => h("p", { class: tn.who }, h("b", { text: (tn.who === "me" ? t("You") : t("Interviewer")) + " " }), tn.ko.replace(/\*\*|==/g, "")))) : null));
}
// ---------------------------------------------------------------- the presentation interview (src/interview/talk.py): its brief, then its deck and script

function talkOf(jid) {                                                              // the job's talk: its brief, and the talk when made
  const tk = task("talk:" + jid);                                                   // a run changes it
  const key = `talk|${jid}|${rev()}|${tk.run || 0}|${tk.state || ""}`;              // fetched again after each run
  if (!UI.docs[key]) getDoc(key, `/api/v1/jobs/${enc(jid)}/talk`);
  return UI.docs[key] || null;                                                      // null while it loads
}
function talkDraft(jid, st) {                                                       // the form's words: what the person typed, else the brief as kept
  UI.talkDraft = UI.talkDraft || {};
  if (!UI.talkDraft[jid]) {                                                         // first drawn from the brief
    const b = (st && st.brief) || {};
    UI.talkDraft[jid] = { topics: (b.topics || []).map((x) => (typeof x === "string" ? x : x.title || "")).filter(Boolean).join("\n"),
      minutes: b.minutes || 30, when: b.when || "", format: b.format || "", request: b.request || "" };
  }
  return UI.talkDraft[jid];
}
function talkBrief(jid) {                                                           // the form as the API keeps it
  const d = UI.talkDraft[jid];
  return { topics: d.topics.split("\n").map((x) => x.trim()).filter(Boolean).map((title) => ({ title })), minutes: Number(d.minutes) || 30,
    when: d.when.trim(), format: d.format.trim(), request: d.request.trim(), lang: docLang() };
}
async function talkMake(jid) {                                                      // keep the brief, then make the talk
  const kept = await act("/api/v1/interview/talk/brief", { job: jid, brief: talkBrief(jid) });
  if (kept) act("/api/v1/interview/talk", { job: jid, lang: docLang() });
}
function talkPart(j) {                                                              // the brief on the left, the made talk beside it
  const st = talkOf(j.id);
  if (!st) return h("p", { class: "hint", text: t("Reading the presentation…") });
  const tk = task("talk:" + j.id), making = tk.state === "running";                 // a run in progress
  const d = talkDraft(j.id, st);
  const field = (label, k, attrs) => h("label", { class: "field" }, h("span", { text: label }),
    h(attrs.rows ? "textarea" : "input", { ...attrs, value: d[k], "data-key": `talk-${k}-${j.id}`, oninput: (e) => { d[k] = e.target.value; } }));
  const form = h("div", { class: "talk-brief card" }, h("h3", { text: t("What the interviewers asked for") }),
    field(t("Topics, one a line, in their order"), "topics", { rows: 4, placeholder: t("e.g. {x}", { x: t("About me and my strengths\nWhat my work taught me\nThe hardest problem I solved\nWhy this role, and my plan") }) }),   // an example, marked as one: never read as filled in
    h("div", { class: "talk-row" }, field(t("Minutes"), "minutes", { type: "number", min: 5, max: 120 }), field(t("Day and time"), "when", { placeholder: t("e.g. {x}", { x: "2026-11-20 14:00" }) }),
      field(t("Format"), "format", { placeholder: t("e.g. {x}", { x: t("Presentation + Q&A, video call") }) })),
    field(t("Their words, pasted (optional)"), "request", { rows: 3 }),
    sendNote(t("Making the talk sends the brief, your evidence and the posting to the agent.")),
    h("div", { class: "part-keys" }, h("button", { class: "btn", disabled: making || null, onclick: () => act("/api/v1/interview/talk/brief", { job: j.id, brief: talkBrief(j.id) }, t("Saved.")) }, t("Save the brief")),
      h("button", { class: "btn primary", disabled: making || null, onclick: () => talkMake(j.id) }, icon("agent"), st.made ? t("Make the talk again") : t("Make the talk"))));
  const status = making ? h("div", { class: "band info", role: "status" }, h("span", { text: t("Making the talk: the agent writes from your evidence, then the slides are drawn and printed. It takes a few minutes.") }))
    : tk.state === "error" ? band(tk.error.code === "talk" ? "talk_failed" : tk.error.code, { retry: () => talkMake(j.id) }) : null;
  if (!st.made) return h("div", { class: "talk" }, status, form);
  // the script's own title line, in the frame below, gives the slides and the minutes: beside the keys only what needs a look
  const sum = [st.layout ? t("{n} layout defects.", { n: st.layout }) : "", st.pace ? t("{n} slides whose words do not fit their time.", { n: st.pace }) : ""].filter(Boolean).join(" ");
  return h("div", { class: "talk" }, status,
    h("div", { class: "part-keys" }, sum ? h("span", { class: "hint", text: sum }) : null,
      h("button", { class: "btn", onclick: () => openKit(j.id, "talk/deck.pdf") }, icon("slides"), t("Slides (PDF)")),
      h("button", { class: "btn", onclick: () => openKit(j.id, "talk/script.pdf") }, icon("file"), t("Script (PDF)")),
      h("button", { class: "btn", onclick: () => act("/api/v1/interview/talk/deliver", { job: j.id }).then((r) => { if (r && r.files) toast(t("On the Desktop: {names}", { names: r.files.join(", ") }), null, "done"); }) }, icon("desktop"), t("Save to the Desktop"))),
    ivTalkScript(j, st), form);                                                       // the script, drawn by the panel (interview.js)
}

const ivWide = () => { if (UI.ivWide === undefined) UI.ivWide = localStore("offerowl-ivwide") === "1"; return UI.ivWide; };   // the interview over the whole width, as last chosen in this browser
function ivKit(j) {                                                                 // the kit's contents, search and script cards, drawn by the panel itself (kit.js): no page of the kit's own in a frame
  const k = ivKitView(j);                                                           // made once per kit (interview.js)
  if (!k) return ivWait(ivKitData(j), t("Opening the interview kit…"));             // the scripts on their way, or why they could not come
  if (UI.kitAsk) { const q = UI.kitAsk; UI.kitAsk = null; requestAnimationFrame(() => { if (UI.kit === k) k.view.search(q); }); }   // a script asked for from the deck
  requestAnimationFrame(() => { if (UI.kit === k) k.view.attached(); });           // once it stands in the page: fitted to its room, its board where it stood
  return k.view.el;
}
async function openKit(jid, hash) {                                                 // the kit's own page, started when nothing answers there
  const tab = window.open("", "_blank");                                            // opened in the click itself: after the waits below the browser would block it
  if (tab) tab.opener = null;                                                       // the kit's page cannot reach back into this one
  const r = await act("/api/v1/interview/start", { job: jid });                     // started (or already up)
  if (!r || !r.started) { if (tab) tab.close(); toast(t("The interview kit could not start."), null, "bad"); return; }
  const to = `/kit/${enc(jid)}/` + (hash === "cue" ? "cue" : hash || "");          // the kit, at the panel's own address (web.py kit_proxy)
  if (to && tab) tab.location.href = to;                                            // the tab opened in the click
  else if (to) window.open(to, "_blank", "noopener");                               // a browser that gave none: a tab of its own now
  else if (tab) tab.close();                                                        // nothing to show
}

// ---------------------------------------------------------------- an application's progress: its stage, its next step, its reminders

function openApplication(jid, tab) {                                                // one application, opened in the list (on a phone, on its own)
  UI.jobsMode = "list"; UI.jobPhone = true; UI.lineOpen = null; if (tab) UI.jobTab = tab;   // its page
  if (S.job !== jid) { S.job = jid; act("/api/v1/jobs/select", { job: jid }); }     // the job in view everywhere: drawn at once, kept by the server
  render();                                                                         // drawn
  if (PHONE.matches) window.scrollTo({ top: 0, behavior: "instant" });              // on a phone it reads from its top
}
function stageDaysBack(j, reached) {                                                // the first stage whose day comes before the stage's before it (an import's guessed day, a typo)
  const days = reached.map((st) => [st, ((j.dates || {})[st] || "").slice(0, 10)]).filter(([, d]) => d);   // the days given, in the stages' order
  const i = days.findIndex(([, d], k) => k && d < days[k - 1][1]);
  return i < 0 ? null : h("p", { class: "hint warn", role: "note", text: t("The {a} day comes before the {b} day, so the {b} day is left out of the timeline and the charts.", { a: t(STAGE[days[i][0]]), b: t(STAGE[days[i - 1][0]]) }) });
}
function progressPart(j) {                                                          // where one application stands, what is next, how it ended
  const stages = S.stages || [];                                                    // the four stages, in order
  const reached = stages.slice(0, stages.indexOf(j.stage) + 1);                     // the stages it went through, the one it is in last
  return h("div", { class: "progress" },
    h("div", { class: "seg stages", role: "group", "aria-label": t("Stage") }, stages.map((st) =>   // its stage, chosen in place
      h("button", { "aria-pressed": j.stage === st ? "true" : "false", onclick: () => act("/api/v1/tracker/edit", { job: j.id, stage: st }) },
        t(STAGE[st]), (j.days || j.dates || {})[st] ? h("span", { class: "when", text: shortDay((j.days || j.dates)[st]) }) : null))),   // the days that count (tracker.stage_days)
    h("div", { class: "pdates", role: "group", "aria-label": t("Days of the stages") }, reached.map((st) =>   // each stage's day, each its own field (a card added late keeps the real ones)
      h("label", { class: "field" }, h("span", { text: t("{stage} day", { stage: t(STAGE[st]) }) }), dayField({ "data-key": `p-${j.id}-date-${st}` }, (j.dates || {})[st] || "",
        (v) => act("/api/v1/tracker/edit", { job: j.id, dates: { [st]: v } }))))),
    stageDaysBack(j, reached),                                                      // a later stage's day before an earlier one's: said, so it can be fixed
    h("div", { class: "prow nodate" + (j.stage === "result" ? " with-result" : "") },   // the result once there is one, the next step: one row
      j.stage === "result" ? h("div", { class: "field" }, h("span", { text: t("Result") }), h("div", { class: "seg results", role: "group", "aria-label": t("Result") },
        Object.keys(RESULT).map((k) => { const on = resultOn(j, k); return h("button", { type: "button", "aria-pressed": on ? "true" : "false",   // a second press takes it back
          onclick: () => { if (on && j.result !== k) return; act("/api/v1/tracker/edit", { job: j.id, result: on ? "" : k }); } }, h("span", { class: "lit " + (on ? RESULT_CLS[k] : "off"), "aria-hidden": "true" }), t(RESULT[k])); }))) : null,   // lit when chosen: an unchosen offer is no green
      h("label", { class: "field" }, h("span", { text: t("Next step") }), h("input", { "data-key": `p-${j.id}-next`, value: j.next || "", placeholder: t("Add a next step"),
        oninput: debounce((e) => act("/api/v1/tracker/edit", { job: j.id, next: e.target.value }), 700) }))),
    linksIn(j.next).length ? h("p", { class: "next-links" }, linkKeys(j.next)) : null,   // the next step's links, to open from here
    ownResult(j) ? h("p", { class: "hint own-result" }, t("Result") + ": " + ownResult(j),   // a result the person wrote in words: a key above replaces it, undo brings it back
      resultDay(j) ? h("button", { class: "btn small", type: "button", onclick: () => act("/api/v1/tracker/edit", { job: j.id, dates: { result: resultDay(j) } }),
        text: t("Set the result's day to {d}", { d: resultDay(j) }) }) : null) : null,   // its words start with the day it ended, the card says another
    roundsPart(j),
    reminders([j], j),
    h("div", { class: "jd-foot" }, h("button", { class: "btn small quiet danger", onclick: () => removeAct("/api/v1/jobs/remove", { job: j.id }, t("Removed the job {name}. It waits in the trash.", { name: j.company || j.role || j.id })), text: t("Remove this job") })));   // what takes it away, apart from the rest
}

// ---------------------------------------------------------------- every application at once: by stage, or by date

function trackBoard(jobs) {                                                         // four columns of cards
  const board = h("div", { class: "board", onscroll: (e) => { UI.boardLeft = e.target.scrollLeft; } });   // on a phone the columns slide sideways (skin.css); where the person slid it is kept
  requestAnimationFrame(() => {                                                     // laid out: where the person left it, or on the first look the open application's column
    if (!board.isConnected || board.scrollWidth <= board.clientWidth + 1) return;   // no sideways room
    const f = UI.boardFollow, moved = f && board.querySelector(`.col[data-stage="${f.to}"] .tcard[data-job="${CSS.escape(f.id)}"]`);   // a note just moved on by its key
    if (moved) { UI.boardFollow = null; board.scrollLeft = moved.closest(".col").offsetLeft - board.children[0].offsetLeft; UI.boardLeft = board.scrollLeft; return; }   // its new column comes into view: the note never seems to vanish off the side
    if (typeof UI.boardLeft === "number") { board.scrollLeft = UI.boardLeft; return; }   // a redraw (a move, a poll) never jumps the board
    const cols = [...board.children], open = (jobs.find((j) => j.id === S.job) || {}).stage;
    const at = cols.find((c) => c.dataset.stage === open && c.querySelector(".tcard")) || cols.find((c) => c.querySelector(".tcard"));
    if (at && at !== cols[0]) board.scrollLeft = at.offsetLeft - cols[0].offsetLeft;  // its column at the left edge
    UI.boardLeft = board.scrollLeft;                                                // from now on the person's own place
  });
  return fill(board, (S.stages || []).map((st) => {
    const col = h("section", { class: "col glass", "aria-label": t(STAGE[st]), "data-stage": st },
      h("div", { class: "card-h" }, h("h3", { text: t(STAGE[st]) }), h("span", { class: "chip count", text: String(jobs.filter((j) => j.stage === st).length) })),
      jobs.filter((j) => j.stage === st).map((j) => h("article", { class: "tcard paper", draggable: "true", "data-job": j.id, "data-stage": st, "aria-label": j.company || j.role || j.id,
        ondragstart: (e) => { e.dataTransfer.setData("text/plain", j.id); e.dataTransfer.effectAllowed = "move"; UI.dragging = j.id;   // held: the page stops redrawing until it lands
          requestAnimationFrame(() => e.target.classList && e.target.classList.add("lifted")); },
        ondragend: (e) => { if (e.target.classList) e.target.classList.remove("lifted"); UI.dragging = null; document.querySelectorAll(".col.over").forEach((c) => c.classList.remove("over")); render(); } },
        h("div", { class: "tc-top" }, mono(j.company || j.role || j.id, "sm", j.stage), h("button", { class: "co tco", type: "button", onclick: () => openApplication(j.id), text: j.company || j.role || j.id }),   // its mark; the name opens the application
          st === "result" && j.result ? stagePill(j) : null),   // how it ended, on the name's line: a long role never pushes it down
        j.company && j.role ? h("span", { class: "ro", text: j.role }) : null,
        UI.nextEdit === j.id ? h("input", { class: "tnext", "data-key": `b-${j.id}-next`, value: j.next || "", placeholder: t("Add a next step"), "aria-label": t("Next step"), draggable: "false",   // a box only while it is typed in
          oninput: debounce((e) => { j.next = e.target.value; act("/api/v1/tracker/edit", { job: j.id, next: e.target.value }); }, 700),
          onblur: () => { UI.nextEdit = null; render(); }, onkeydown: (e) => { if (e.key === "Enter" || e.key === "Escape") e.target.blur(); } })
          : h("button", { class: "tnext-view" + (j.next ? "" : " none"), type: "button", title: t("Next step"),   // words the card can be lifted by; a click opens the box
            onclick: () => { UI.nextEdit = j.id; render(); requestAnimationFrame(() => { const i = document.querySelector(`[data-key="b-${CSS.escape(j.id)}-next"]`); if (i) i.focus(); }); },
            text: unlinked(j.next) || t("Add a next step") }),
        UI.nextEdit === j.id ? null : linkKeys(j.next),                             // its links beside the words, to open at once
        h("div", { class: "tfoot" }, (j.days || {})[st] ? h("span", { class: "when", text: t("Since {date}", { date: j.days[st] }) }) : h("span", { class: "when" }),   // the stage's day as counted; none known, no day (the day it was added is not when it got here)
          st !== "result" ? h("button", { class: "btn small move", "data-to": S.stages[S.stages.indexOf(st) + 1], onclick: () => { UI.boardFollow = { id: j.id, to: S.stages[S.stages.indexOf(st) + 1] }; act("/api/v1/tracker/next", { job: j.id }); }, text: t("Move to {stage}", { stage: t(STAGE[S.stages[S.stages.indexOf(st) + 1]]) }) }) : null))),
      jobs.some((j) => j.stage === st) ? null : h("p", { class: "hint col-empty", text: t("Nothing here yet.") }));   // an empty stage says so
    const card = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("text/plain") && ![...e.dataTransfer.types].includes("Files");   // a card, not files
    col.addEventListener("dragover", (e) => { if (!card(e)) return; e.preventDefault(); col.classList.add("over"); });      // a card held over it
    col.addEventListener("dragleave", (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove("over"); });   // left the column itself, not a card inside it
    col.addEventListener("drop", (e) => { if (!card(e)) return; e.preventDefault(); e.stopPropagation(); col.classList.remove("over");   // dropped here: its card moves
      const job = e.dataTransfer.getData("text/plain"), j = (S.jobs || []).find((x) => x.id === job);
      UI.dragging = null;                                                           // landed
      if (!j || j.stage === st) { render(); return; }                               // the same column: nothing to save
      j.stage = st; j.dates = { ...(j.dates || {}), [st]: S.today || "" };           // moved on the page at once; the server's answer confirms it
      UI.justMoved = job;                                                           // it settles into its new column (motion.js)
      render();
      act("/api/v1/tracker/edit", { job, stage: st }, t("Moved to {stage}", { stage: t(STAGE[st]) })); });
    return col;                                                                     // one column
  }));
}
const ownWords = (words, day) => (String(words).startsWith(day) ? String(words).slice(day.length).replace(/^[\s,:·-]+/, "") || words : words);   // a result written after its own day: the row says the day once
function trackTimeline() {                                                          // every dated step, the newest first
  const tl = [];                                                                    // from the jobs' dates and reminders
  for (const j of S.jobs) {                                                         // each job
    const days = j.days || j.dates || {};                                            // the days that count: none left from a move taken back (tracker.stage_days)
    for (const r of j.rounds || []) tl.push({ at: r.at, kind: "round", st: "interview", job: j.id, name: jobName(j), text: t(ROUND_KIND[r.kind] || "Other round") });   // each interview round, on its day
    for (const st of S.stages) if (days[st]) tl.push({ at: days[st], kind: "stage", st, job: j.id, name: jobName(j),
      text: st === "result" && j.result ? (RESULT[j.result] ? t(RESULT[j.result]) : ownWords(j.result, days[st])) : t(STAGE[st]) });   // the result says how it ended, in the person's words when they wrote them
    for (const r of j.reminders || []) tl.push({ at: r.at, kind: "reminder", job: j.id, name: jobName(j), text: r.text, done: r.done,
      due: S.due.some((d) => d.job === j.id && d.id === r.id) });
  }
  const order = (e) => (e.kind === "round" ? S.stages.indexOf("interview") : e.st ? S.stages.indexOf(e.st) : -1);   // within a day: the later step first, as the days go
  tl.sort((a, b) => String(b.at).slice(0, 10).localeCompare(String(a.at).slice(0, 10)) || String(a.name).localeCompare(String(b.name)) || order(b) - order(a) || String(b.at).localeCompare(String(a.at)));
  const days = [];                                                                  // one row a day: a day with twenty steps is one line of chips, not twenty rows
  for (const e of tl) {
    const d = String(e.at).slice(0, 10), last = days[days.length - 1], row = last && last.day === d ? last : (days.push({ day: d, items: [] }), days[days.length - 1]);
    const same = row.items[row.items.length - 1];                                   // the same application's steps that day are one chip: its name once, its steps after it
    if (same && same.job === e.job && e.kind !== "reminder" && same.kind !== "reminder") { same.text += ", " + e.text; same.st = same.st || e.st; } else row.items.push({ ...e });
  }
  const dateless = S.jobs.filter((j) => !Object.keys(j.days || {}).length && !(j.rounds || []).length && !(j.reminders || []).length);   // nothing to place on a day
  const none = dateless.length ? h("p", { class: "hint tl-none" }, tn(dateless.length, "{n} application has no day yet:", "{n} applications have no day yet:") + " " + dateless.map(jobName).join(", ") + " ",
    h("button", { class: "linkish", type: "button", onclick: () => { UI.editDays = true; render(); }, text: t("Edit the days") })) : null;   // said, never left out without a word
  return h("div", { class: "tl-wrap" }, none, h("ol", { class: "timeline paper", style: "list-style:none;margin:0" }, days.map((d) => h("li", { class: "tl day" + (d.items.some((e) => e.due) ? " due" : "") },
    h("time", { text: d.day }), h("i", { "aria-hidden": "true" }),                    // the day, then its node on the line
    h("span", { class: "tl-day" }, d.items.map((e) => [h("button", { class: "tl-ev", type: "button", "data-stage": e.st || null, "data-kind": e.kind,   // each step: the company and what happened, in the stage's colour
      onclick: () => openApplication(e.job, "progress"), title: String(e.at).replace("T", " ") },   // the name opens its progress; the time on hover
      h("b", { text: e.name }), e.kind === "reminder" ? h("span", { class: "chip pc", text: e.done ? t("Done") : e.due ? t("Due") : t("Reminder") }) : null,
      h("span", { class: "tl-what", text: unlinked(e.text) })), linkKeys(e.text)]))))));   // a link beside the step's key, never inside it
}
// ---------------------------------------------------------------- every application's days in one table
// The progress tab sets one application's days; this sets them all at once, a row each, the stages each went through. A day
// that comes after a later step's is left out of the timeline and the charts (tracker.stage_days) and wears the warning colour
// here, for the person to set. When five or more applications were added on one day and carry it as a stage's day (a list
// brought in: the adding stamped its own day), one key clears that day from them, in one undo step
function batchDay(jobs) {                                                           // as tracker.batch_day: {day, ids} or null
  const by = new Map();                                                             // the day added -> the cards whose stamp of it a later step's earlier day disproves
  const day = (v) => String(v || "").slice(0, 10);
  for (const j of jobs) {
    const made = day(j.created), d = j.dates || {};
    const stamped = made && S.stages.some((s, i) => day(d[s]) === made && S.stages.slice(i + 1).some((x) => d[x] && day(d[x]) < made));   // a card added by hand never is
    if (stamped) by.set(made, [...(by.get(made) || []), j.id]);
  }
  let best = null; for (const [day, ids] of by) if (!best || ids.length > best.ids.length) best = { day, ids };
  return best && best.ids.length >= 5 ? best : null;
}
function daysTable(jobs) {
  const batch = batchDay(jobs);
  const clear = async () => {                                                       // asked first: many cards change at once (undo brings them back)
    if (!(await askFirst({ title: tn(batch.ids.length, "Clear {day} from {n} application?", "Clear {day} from {n} applications?", { day: batch.day }), ok: t("Clear"),
      text: t("The stages that carry that day lose it and leave the timeline and the charts. Undo brings it back.") }))) return;
    await act("/api/v1/tracker/clear_day", { day: batch.day }, tn(batch.ids.length, "Cleared {day} from {n} application.", "Cleared {day} from {n} applications.", { day: batch.day }));
  };
  const reached = (j) => S.stages.slice(0, S.stages.indexOf(j.stage) + 1);         // the stages it went through
  const offAny = jobs.some((j) => reached(j).some((st) => (j.dates || {})[st] && !(j.days || {})[st]));   // a day out of order somewhere: its mark is said in words
  const inBatch = (j, st) => !!batch && batch.ids.includes(j.id) && String((j.dates || {})[st] || "").slice(0, 10) === batch.day;   // a day the band's key clears
  return h("section", { class: "daystable paper", "aria-label": t("Edit the days") },
    batch ? h("div", { class: "band info dt-batch", role: "status" },
      h("p", {}, h("b", { text: tn(batch.ids.length, "{n} application added on {day}", "{n} applications added on {day}", { day: batch.day }) }),   // what, in bold,
        tn(batch.ids.length, " carries that day as a stage's day.", " carry that day as a stage's day.")),   // then what it means, one sentence
      h("button", { class: "btn small", type: "button", onclick: clear }, t("Clear that day"))) : null,
    offAny || batch ? h("p", { class: "hint dt-legend" },                           // the marks in words, for a phone too (no hover)
      offAny ? h("span", { class: "dt-key" }, h("span", { class: "dt-swatch", "aria-hidden": "true" }), t("A day in amber comes after a later step's day: the timeline and the charts leave it out.")) : null,
      batch ? h("span", { class: "dt-key" }, h("span", { class: "dt-swatch batch", "aria-hidden": "true" }), t("A dashed day is the one the key above clears.")) : null) : null,
    h("div", { class: "dt-row dt-head", role: "row" }, h("span", { role: "columnheader", text: t("Application") }),
      S.stages.map((st) => h("span", { role: "columnheader", text: t(STAGE[st]) }))),
    jobs.map((j) => h("div", { class: "dt-row", role: "row", "data-stage": j.stage },
      h("span", { class: "dt-name", role: "cell" }, mono(j.company || j.role || j.id, "sm", j.stage),
        h("button", { class: "linkish", type: "button", onclick: () => openApplication(j.id, "progress"), text: jobName(j) })),
      S.stages.map((st) => {
        if (!reached(j).includes(st)) return h("span", { class: "dt-none", role: "cell", text: "–" });   // a stage it has not reached
        const kept = (j.dates || {})[st] || "", off = kept && !(j.days || {})[st];     // a day out of order: kept, not counted
        return h("span", { class: "dt-cell" + (off ? " off" : "") + (inBatch(j, st) ? " batch" : ""), role: "cell", title: off ? t("It comes after a later step's day, so the timeline and the charts leave it out.") : null },
          h("span", { class: "dt-lab", "aria-hidden": "true", text: t(STAGE[st]) }),   // its stage's name, where the head row is not shown (a phone)
          dayField({ "data-key": `dt-${j.id}-${st}`, "aria-label": `${jobName(j)}: ${t(STAGE[st])}`, placeholder: "" }, kept,   // an empty day stays empty: sixty "YYYY-MM-DD" hid the days there are
            (v) => act("/api/v1/tracker/edit", { job: j.id, dates: { [st]: v } })));
      }))));
}
// ---------------------------------------------------------------- the interview rounds of one application (tracker.set_round)
const ROUND_KIND = { call: "Recruiter call", first: "First interview", second: "Second interview", third: "Third interview", final: "Final interview",
  coding: "Coding test", assignment: "Assignment", culture: "Culture fit", other: "Other round" };
const ROUND_NEXT = { call: "first", first: "second", second: "third", third: "final" };   // the round that usually follows
const weekdayOf = (day) => {                                                        // 2026-11-12 as 목 or Thu
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(String(day || "")); if (!m) return "";
  const d = new Date(+m[1], +m[2] - 1, +m[3]).getDay();
  return (LANG === "ko" ? ["일", "월", "화", "수", "목", "금", "토"] : ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])[d];
};
const whenWords = (at) => { const [d, tm] = String(at || "").split("T"); return `${shortDay(d)} (${weekdayOf(d)})` + (tm ? " " + tm : ""); };   // 11-12 (목) 14:00
function roundsPart(j) {                                                            // what each round asked and how it went, kept round by round
  const rs = j.rounds || [], edit = UI.roundEdit && UI.roundEdit.job === j.id ? UI.roundEdit.id : null;   // the round being written, "new" for a new one
  return h("section", { class: "rounds", "aria-label": t("Interview rounds") },
    h("div", { class: "card-h" }, h("h3", { text: t("Interview rounds") }), sentLine(false),
      edit ? null : h("button", { class: "btn small", type: "button", onclick: () => { UI.roundEdit = { job: j.id, id: "new" }; render(); } }, icon("plus"), t("Add a round"))),
    rs.length ? h("ol", { class: "round-list" }, rs.map((r) => edit === r.id ? h("li", { class: "round editing" }, roundForm(j, r)) : roundRow(r, j))) : null,
    !rs.length && edit !== "new" ? h("p", { class: "hint", text: t("No round recorded yet.") }) : null,   // the state, in words
    edit === "new" ? roundForm(j, null) : null);
}
function roundRow(r, j) {                                                           // one round, read
  return h("li", { class: "round" },
    h("div", { class: "round-h" }, h("b", { text: t(ROUND_KIND[r.kind] || "Other round") }), h("span", { class: "when", text: whenWords(r.at) }), h("span", { class: "grow" }),
      h("button", { class: "btn small quiet", type: "button", onclick: () => { UI.roundEdit = { job: j.id, id: r.id }; render(); } }, icon("edit"), t("Edit"))),
    roundAsked(r, j),
    r.notes ? h("p", { class: "round-notes" }, linked(r.notes)) : null);
}
function roundAsked(r, j) {                                                         // a round's questions, each with the script that answers it: they lead the question map (plan.py, kind "asked")
  const lines = String(r.asked || "").split("\n").map((x) => x.trim()).filter(Boolean);   // as written, one a line
  if (!lines.length) return null;
  const head = h("span", { class: "k", text: tn(lines.length, "{n} question asked", "{n} questions asked") });
  const b = boardOf(j.id);                                                          // the job's interview board, read once per revision
  const cat = b && b.ready ? (b.categories || []).find((c) => c.kind === "asked") : null;
  const qs = cat ? cat.questions.filter((q) => (q.rounds || []).includes(r.id)) : [];   // this round's questions as the map read them, a question asked again among them
  if (!qs.length) return h("div", { class: "round-asked" }, head, h("ul", {}, lines.map((q) => h("li", { text: q }))),   // no kit yet (or still read): the words as written
    b && b.ready === false ? h("div", { class: "round-kit" }, h("span", { class: "hint", text: t("A question map shows which of them a script answers.") }),
      h("button", { class: "btn small", type: "button", onclick: () => act("/api/v1/interview/kit", { job: j.id, lang: docLang() }) }, icon("map"), t("Make the question map"))) : null);
  const tk = task("scripts:" + j.id), writing = tk.state === "running";            // the agent writing this job's scripts now
  const missing = qs.filter((q) => ["none", "weak"].includes(q.coverage || "none")).map((q) => q.id).slice(0, 30);   // no script answers them, or one only in part (30 a press, as the route takes)
  const open = (id) => { UI.jobTab = "interview"; ivOpenScript(id); };              // the script in the scripts' search, on the interview tab
  const titleOf = (id) => { const s = (b.scripts || []).find((x) => x.id === id); return s ? (LANG === "ko" ? s.title_ko || s.title_en : s.title_en || s.title_ko) : ""; };
  return h("div", { class: "round-asked" }, h("span", { class: "k", text: tn(qs.length, "{n} question asked", "{n} questions asked") }),   // as many as are listed: a line asked twice is one
    h("ul", { class: "asked-list" }, qs.map((q) => { const by = (q.covered_by || [])[0], c = q.coverage || "none";
      return h("li", {}, h("span", { class: "lit " + (COVERAGE_CLS[c] || "off"), title: t(COVERAGE[c] || COVERAGE.none) }, h("span", { class: "sr", text: t(COVERAGE[c] || COVERAGE.none) })),
        h("span", { class: "asked-q", text: q.text }),
        by ? h("button", { class: "btn small quiet asked-by", type: "button", title: titleOf(by) || t(COVERAGE[c] || ""), onclick: () => open(by) }, t(c === "draft" ? "Draft {id}" : "Script {id}", { id: by }))   // the script's own title on the hover: a match can be checked
          : h("span", { class: "asked-none", text: t("No script yet") })); })),
    missing.length ? h("div", { class: "round-kit" },
      S.agent.state === "ready" ? h("button", { class: "btn small agent", type: "button", disabled: writing || null,
          onclick: () => act("/api/v1/interview/scripts", { job: j.id, lang: docLang(), ids: missing }) }, icon("agent"),
          writing ? t("Writing… {done} of {total}", { done: tk.done || 0, total: tk.total || 0 }) : tn(missing.length, "Write a new script", "Write {n} new scripts"))
        : null,
      h("span", { class: "hint", text: S.agent.state === "ready" ? t("For the questions no script answers, or answers only in part.") : t("Scripts are written by the agent. Turn it on to draft them.") })) : null);
}
function roundForm(j, r) {                                                          // a round written or changed: its kind, day, time, the questions, notes
  const last = (j.rounds || []).slice(-1)[0];
  const kind = r ? r.kind : (last ? ROUND_NEXT[last.kind] || "other" : "first");    // a new round: the one that usually comes next
  const [d, tm] = String(r ? r.at : "").split("T");
  const key = `i-${j.id}-${r ? r.id : "new"}-`;                                     // kept across redraws until saved or closed (core.js DRAFT_KEYS)
  const close = () => { UI.roundEdit = null; forget(key); render(); };
  return h("form", { class: "round-form", onsubmit: async (e) => { e.preventDefault(); const f = e.target;
      const day = isoDay(f.elements.day.value), time = isoTime(f.elements.time.value);   // read the way the fields read them
      if (!day) { f.elements.day.setCustomValidity(t("Write the day as 2026-11-09.")); f.elements.day.reportValidity(); return; }
      if (time === null) { f.elements.time.setCustomValidity(t("Write the time as 19:00.")); f.elements.time.reportValidity(); return; }
      const body = { job: j.id, kind: f.elements.kind.value, at: day + (time ? "T" + time : ""), asked: f.elements.asked.value, notes: f.elements.notes.value };
      if (r) body.id = r.id;
      if (await act("/api/v1/tracker/round", body, t("Round kept."))) close(); } },
    h("div", { class: "round-top" },
      h("label", { class: "field" }, h("span", { text: t("Kind") }), h("select", { name: "kind", "data-key": key + "kind" },
        Object.keys(ROUND_KIND).map((k) => h("option", { value: k, selected: k === kind || null, text: t(ROUND_KIND[k]) })))),
      h("label", { class: "field" }, h("span", { text: t("Day") }), dayField({ name: "day", "data-key": key + "day" }, d || S.today)),
      h("label", { class: "field" }, h("span", { text: t("Time") }), timeField({ name: "time", "data-key": key + "time" }, tm || ""))),
    h("label", { class: "field" }, h("span", { text: t("Questions asked, one a line") }), h("textarea", { name: "asked", "data-key": key + "asked", rows: 3, class: "short",
      placeholder: t("Tell me about a time you…") }, r ? r.asked || "" : "")),
    h("label", { class: "field" }, h("span", { text: t("How it went") }), h("textarea", { name: "notes", "data-key": key + "notes", rows: 2, class: "short",
      placeholder: t("What landed, where you got stuck, what to prepare next") }, r ? r.notes || "" : "")),
    h("div", { class: "part-keys" }, h("button", { class: "btn primary", type: "submit", text: r ? t("Save") : t("Keep the round") }),
      h("button", { class: "btn", type: "button", onclick: close, text: t("Cancel") }), h("span", { class: "grow" }),
      r ? h("button", { class: "btn small quiet danger", type: "button", onclick: async () => { if (await removeAct("/api/v1/tracker/round", { job: j.id, id: r.id, remove: true }, t("Round removed."))) close(); }, text: t("Remove") }) : null));
}
function reminders(jobs, one) {                                                     // add a reminder; let the PC show them (one: the application they belong to)
  const form = h("form", { onsubmit: (e) => { e.preventDefault(); const f = e.target;
    const day = isoDay(f.elements.day.value), time = isoTime(f.elements.time.value);   // read the way the fields read them
    if (!day) { f.elements.day.setCustomValidity(t("Write the day as 2026-11-09.")); f.elements.day.reportValidity(); return; }   // a reminder needs its day
    if (time === null) { f.elements.time.setCustomValidity(t("Write the time as 19:00.")); f.elements.time.reportValidity(); return; }
    const at = day + (time ? "T" + time : "");
    act("/api/v1/reminders", { job: one ? one.id : f.elements.job.value, at, text: f.elements.text.value }, t("Reminder kept.")).then((r) => { if (r) forget("r-text"); }); } },
    h("label", { class: "field" }, h("span", { text: t("What") }), h("input", { name: "text", "data-key": "r-text", placeholder: t("Reply to the invitation") })),
    one ? null : h("label", { class: "field" }, h("span", { text: t("Job") }), h("select", { name: "job", "data-key": "r-job" }, jobs.map((j) => h("option", { value: j.id, selected: j.id === S.job || null, text: jobName(j) })))),
    h("label", { class: "field" }, h("span", { text: t("Day") }), dayField({ name: "day", "data-key": "r-day" }, S.today)),
    h("label", { class: "field" }, h("span", { text: t("Time") }), timeField({ name: "time", "data-key": "r-time" }, "")),
    h("button", { class: one && one.stage === "result" ? "btn" : "btn primary", type: "submit", text: t("Remind me") }));   // an ended application's reminder is a plain key: nothing is due on it
  const perm = typeof Notification === "undefined" ? "unsupported" : Notification.permission;  // can this browser show notifications
  return h("section", { class: "remind" + (one ? " one" : " glass"), "aria-label": t("Reminders") },
    h("div", { class: "card-h" }, h("h3", { text: t("Reminders") }), sentLine(false)),
    form,
    h("div", { class: "part-keys" },
      perm === "default" ? h("button", { class: "btn small", onclick: () => Notification.requestPermission().then(() => render()), text: t("Show reminders as notifications on this PC") }) : null,
      perm === "granted" ? h("span", { class: "pill ok", text: t("Notifications are on") }) : null,
      h("a", { class: "btn small", href: "/api/v1/reminders.ics", download: "offerowl-reminders.ics", text: t("Add them to your calendar") })),
    jobs.some((j) => (j.reminders || []).length) ? h("div", { class: "rows" }, jobs.flatMap((j) => (j.reminders || []).map((r) => h("div", { class: "remrow" },
      h("span", {}, one ? null : h("b", { text: jobName(j) + " " }), linked(r.text), " ", h("span", { class: "when", text: String(r.at).replace("T", " ") })),
      h("span", { class: "part-keys" }, h("button", { class: "btn small", "data-key": "rem-done-" + r.id, "aria-pressed": r.done ? "true" : "false", onclick: () => act("/api/v1/reminders", { job: j.id, id: r.id, done: !r.done }), text: r.done ? t("Done") : t("Mark done") }),
        h("button", { class: "btn small quiet danger", "data-key": "rem-remove-" + r.id, onclick: () => removeAct("/api/v1/reminders", { job: j.id, id: r.id, remove: true }, t("Reminder removed.")), text: t("Remove") })))))) : null);
}
function notifyDue() {                                                              // due reminders as the browser's notifications, once each
  if (!S || typeof Notification === "undefined" || Notification.permission !== "granted") return;  // only when allowed
  for (const d of S.due || []) {                                                    // each due reminder
    const key = `${d.job}:${d.id}`;                                                 // its identity
    if (UI.notified[key]) continue;                                                 // shown already
    UI.notified[key] = true;                                                        // once
    try { new Notification("Offerowl", { body: `${d.name}: ${d.text}`, tag: key }); } catch (_) { /* a browser without the constructor */ }
  }
}
