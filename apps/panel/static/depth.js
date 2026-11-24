// Offerowl's panel, the depth review (0.11.0, apps/api/services/documents/depth.py): what each project item and deck page of the edition in view
// leaves out. Documents' head holds its key, "Review each project's depth", which says what it does; its sheet opens at the
// window's right edge under the top bar (a phone: from the foot), as the command bar's does. Each finding is said in the
// page's language by its code, with the agent's own words under it in the edition's language, and offers its way on: the
// rewrite to use, or the question to answer, whose answer is kept as a fact of that project. "Leave it" keeps a finding left
// while the item's words stay the same. Units the agent rated come in groups by their verdict, thin first: a thin unit's
// missing parts are what to fill before the edition goes out, the rest are suggestions. The review never stops an export:
// it is the person's to act on.
"use strict";                                                                       // catches undeclared names and silent writes early

const DEPTH_WORDS = {                                                               // each finding's code in the page's words
  depth_scope: "What you were responsible for, and the situation, is not said.",
  depth_hard: "What made the work hard is not said.",
  depth_decision: "What you decided, and what you set aside, is not said.",
  depth_mechanism: "Why the result came about is not said.",
  depth_names: "General words stand where your evidence names the systems.",
  depth_routine: "Routine work is written as an achievement.",
  depth_circumstance: "A circumstance stands where the work should be.",
  depth_thinner: "It says less than the copy that went out." };
const DEPTH_STATE = { applied: "Used", answered: "Kept as a fact", left: "Left as it is" };   // what became of a finding
const DEPTH_VERDICT = { thin: "Thin", adequate: "Adequate", strong: "Strong" };    // a unit's verdict: how many of the three its words state
const DEPTH_PARTS = { hard: "what made it hard", decision: "the decision and its alternative", mechanism: "why it worked" };   // the three a verdict weighs
const DEPTH_GROUP = { thin: "Thin: fill these first", adequate: "Adequate: suggestions", none: "No verdict", strong: "Strong" };   // each group's heading, thin first
const DEPTH_GROUP_NOTE = {                                                          // what each group asks of the person
  thin: "Two or more of these are not said: what made it hard, the decision and its alternative, why it worked. Before this edition goes out, fix each from your evidence or answer its question.",
  adequate: "One of the three is not said.", none: "The agent did not rate these.", strong: "All three are said." };
const VERDICT_CLS = { thin: "rate none", adequate: "rate weak", strong: "rate strong" };   // the lamps the fit's lines use: not met, in part, met

function depthFor() { const ed = edition(); return ed ? `${ed.id}|${docLang()}` : ""; }   // the edition and language a sheet is about
function depthDoc() {                                                               // the edition's review, fetched again when its task or the workspace moves on
  const ed = edition(); if (!ed) return null;
  const key = `depth|${ed.id}|${docLang()}|${rev()}`;                               // rev() holds the tasks' states and the undo steps
  if (!UI.docs[key]) { for (const k of Object.keys(UI.docs)) if (k.startsWith("depth|") && k !== key) { if (UI.docs[k] && k.startsWith(`depth|${ed.id}|${docLang()}|`)) UI.depthLast = UI.docs[k]; delete UI.docs[k]; }   // the last one stands while a new one loads; older copies go
    getDoc(key, `/api/v1/jobs/${enc(ed.id)}/depth?lang=${docLang()}`); }
  return UI.docs[key] || (UI.depthLast && UI.depthLast.job === ed.id && UI.depthLast.lang === docLang() ? UI.depthLast : null);
}
function depthBusy() {                                                              // a review of the edition in view runs now: on its own, or as a draft's last stage
  const ed = edition(); if (!ed) return false;
  return task("depth:" + ed.id).state === "running" || ["write:", "tailor:"].some((k) => task(k + ed.id).state === "running" && task(k + ed.id).step === "reviewing_depth");
}
function depthKey() {                                                               // Documents' key: words that say what it does
  const ed = edition();
  if (!ed || UI.doc === "cover") return null;                                       // a review reads the resume's items and the deck's pages
  const on = agentOn();                                                             // whether anything goes to the agent
  return h("button", { class: "btn" + (on ? " agent" : ""), type: "button", "data-key": "depth-open", "aria-haspopup": "dialog", "aria-expanded": UI.depthOpen ? "true" : "false",
    title: on ? t("Reviewing sends each project's words and evidence to the agent.") : t("With no agent on, only the checks that need none run."),
    onclick: () => depthOpen() }, icon("search"), depthBusy() ? t("Reviewing each project's depth") : t("Review each project's depth"));
}
async function depthOpen() {                                                        // the sheet, and a first review when there is none yet
  const ed = edition(); if (!ed) return;
  if (UI.askOpen && typeof askToggle === "function") askToggle(false);             // one sheet at the edge at a time
  UI.depthOpen = depthFor(); render(); focusSheet("#depthpanel");                   // shown at once, with what is kept
  let got = null;
  try { got = await api(`/api/v1/jobs/${enc(ed.id)}/depth?lang=${docLang()}`); } catch (_) { return; }   // the sheet says what it can
  if (got && got.none && !depthBusy()) depthRun();                                  // never reviewed: the key's words are what it does
}
function depthClose() {                                                             // closed, and the keyboard back on the key that opened it
  UI.depthOpen = null; render();
  const k = document.querySelector('[data-key="depth-open"]'); if (k) k.focus({ preventScroll: true });
}
function depthRun() {                                                               // the review again
  const ed = edition(); if (!ed) return null;
  return act("/api/v1/jobs/depth", { job: ed.id, lang: docLang() });                // the task starts; the sheet follows it
}
function depthApply(f) { const ed = edition(); return act("/api/v1/jobs/depth/apply", { job: ed.id, lang: docLang(), finding: f.id }, t("The sentence is in place.")); }
function depthLeave(f) { const ed = edition(); return act("/api/v1/jobs/depth/leave", { job: ed.id, lang: docLang(), finding: f.id }, t("Left as it is. A later review keeps it so while the words stay the same.")); }
async function depthAnswer(u, f) {                                                  // the person's words, kept as a fact of that project
  const ed = edition(), words = String((UI.depthDrafts || {})[f.id] || "").trim();
  if (!words) { toast(t("Write your answer first."), null, "info"); const b = document.querySelector(`[data-key="depth-answer-${f.id}"]`); if (b) b.focus(); return; }
  const project = u.pid || (UI.depthProject || {})[u.id] || "";                     // a page that names no project: the one the person picked
  if (!project) { toast(t("Pick the project this page is about first: the answer is kept with it."), null, "info"); const b = document.querySelector(`[data-key="depth-project-${u.id}"]`); if (b) b.focus(); return; }
  const r = await act("/api/v1/jobs/depth/answer", { job: ed.id, lang: docLang(), finding: f.id, text: words, project }, t("Kept as a fact of this project: the next draft can use it."));
  if (r) delete UI.depthDrafts[f.id];                                               // kept: the box goes
}
function depthProjectPick(u, rec) {                                                 // a page that names no project: which project its answers belong to
  const opts = (rec && rec.projects) || [];
  return h("label", { class: "field depth-project" }, h("span", { text: t("This page names no project. The project it is about") }),
    h("select", { "data-key": `depth-project-${u.id}`, onchange: (e) => { (UI.depthProject = UI.depthProject || {})[u.id] = e.target.value; } },
      h("option", { value: "", text: t("Pick a project") }),
      ...opts.map((o) => h("option", { value: o.pid, selected: (UI.depthProject || {})[u.id] === o.pid || null, text: o.title || o.pid }))));
}
function depthNotes(rec) {                                                          // what the review could not do, said above its findings
  const out = [], notes = rec.notes || [];
  if (notes.includes("no_agent")) out.push(h("div", { class: "band info", role: "note" },
    h("p", { text: t("The agent is off, so only the checks that need none ran: circumstances written as work, and what the copy that went out said.") }),
    h("button", { class: "btn small", type: "button", onclick: () => { depthClose(); openAgentMenu(); }, text: t("Turn on the agent") })));
  if (rec.stale) out.push(h("div", { class: "band", role: "status" }, h("p", { text: t("Some items were written again since this review.") }),
    h("button", { class: "btn small" + (agentOn() ? " agent" : ""), type: "button", disabled: depthBusy() || null, onclick: () => depthRun(), text: t("Review again") })));
  const unread = notes.find((n) => n.startsWith("unreviewed:"));                    // units the agent never read
  if (unread) {                                                                     // said with the reason it had: the call limit, a stop, or an answer that left them out
    const n = Number(unread.split(":")[1]);
    out.push(h("p", { class: "hint", text: notes.includes("limit") ? tn(n, "{n} part was not read by the agent: the review reached its call limit.", "{n} parts were not read by the agent: the review reached its call limit.")
      : notes.includes("stopped") ? tn(n, "{n} part was not read by the agent.", "{n} parts were not read by the agent.")   // the stop says why below
      : tn(n, "{n} part was not read: the agent's answer left it out. Review again to have it read.", "{n} parts were not read: the agent's answer left them out. Review again to have them read.") }));
  }
  if (notes.includes("stopped")) out.push(band("agent_stopped", { retry: () => depthRun() }));
  if (notes.includes("no_deck")) out.push(h("p", { class: "hint", text: t("The deck was not read: make the PDFs and review again to have its pages read too.") }));
  return out;
}
function depthFinding(u, f) {                                                       // one finding: what is missing, and its way on
  const lang = docLang(), open = f.state === "open";
  const head = [h("p", { class: "depth-code" }, f.gate && open ? h("span", { class: "depth-gate", text: t("Fill first") }) : null,   // a thin unit's missing part: the gate
      h("span", { text: t(DEPTH_WORDS[f.code] || "Something is missing.") })),
    f.missing ? h("p", { class: "depth-missing", lang, text: f.missing }) : null,  // the agent's own words, in the edition's language
    (f.lost || []).length ? h("p", { class: "depth-missing", text: t("What went out named: {names}", { names: f.lost.join(", ") }) }) : null];
  if (!open) return h("div", { class: "depth-f done" }, ...head, h("p", { class: "depth-state" }, h("span", { class: "lit " + (f.state === "left" ? "off" : "ok"), "aria-hidden": "true" }),
    h("span", { text: t(DEPTH_STATE[f.state] || "Done") }), f.answer ? h("span", { class: "depth-missing", lang, text: f.answer }) : null));
  if (f.way === "rewrite" && f.rewrite) {                                           // the evidence holds it: words to use
    const item = u.kind === "item";                                                 // a deck page's words live in its source
    return h("div", { class: "depth-f" }, ...head,
      h("blockquote", { class: "depth-rw", lang, text: String(f.rewrite.text || "").replace(/==/g, "") }),
      h("p", { class: "hint", text: item ? (f.rewrite.replaces ? t("In place of: {words}", { words: String(f.rewrite.replaces).replace(/==/g, "") }) : t("After the item's last sentence."))
        : t("Words for this page of your deck: change it where the deck is made.") }),
      h("div", { class: "depth-keys" }, item ? h("button", { class: "btn small", type: "button", "data-key": `depth-use-${f.id}`, disabled: u.changed || sentAway() || null,
        title: u.changed ? t("The item was written again since this review.") : null, onclick: () => depthApply(f), text: t("Use this sentence") }) : null,
        h("button", { class: "btn small quiet", type: "button", onclick: () => depthLeave(f), text: t("Leave it") })));
  }
  return h("div", { class: "depth-f" }, ...head,                                    // the evidence does not hold it: the person is asked
    h("p", { class: "depth-q", lang, text: f.question || "" }),
    h("label", { class: "field" }, h("span", { class: "sr", text: t("Your answer") }),
      h("textarea", { rows: 3, "data-key": `depth-answer-${f.id}`, placeholder: t("Your answer, in your own words"), value: (UI.depthDrafts || {})[f.id] || "",
        oninput: (e) => { (UI.depthDrafts = UI.depthDrafts || {})[f.id] = e.target.value; } })),
    h("div", { class: "depth-keys" }, h("button", { class: "btn small", type: "button", onclick: () => depthAnswer(u, f), text: t("Keep the answer as a fact") }),
      sentLine(false, t("Your answer is kept with your facts on this PC.")),
      h("button", { class: "btn small quiet", type: "button", onclick: () => depthLeave(f), text: t("Leave it") })));
}
function depthVerdict(u) {                                                          // a rated unit's verdict, and which of the three its words do not say
  const parts = (u.missing || []).map((p) => t(DEPTH_PARTS[p] || p)).join(", ");
  const passed = u.verdict === "thin" && !(u.findings || []).some((f) => f.gate && f.state === "open");   // each missing one used, answered or left
  return h("p", { class: "depth-verdict" }, pill(VERDICT_CLS[u.verdict] || "", t(DEPTH_VERDICT[u.verdict] || "No verdict")),
    parts ? h("span", { text: t("Not said: {parts}", { parts }) }) : null,
    passed ? h("span", { class: "depth-passed", text: t("Filled: what was missing is used, answered or left.") }) : null);
}
function depthCard(u, rec) {                                                        // one item or page with its verdict and findings
  const asks = (u.findings || []).some((f) => f.state === "open" && f.way !== "rewrite");   // a question to answer here
  return h("section", { class: "depth-unit" + (u.verdict ? " " + u.verdict : ""), "aria-label": u.title || "" },
    h("h3", { text: u.title || "" }), h("p", { class: "depth-where", text: [u.kind === "slide" ? t("Deck page {n}", { n: u.page }) : u.where, u.changed ? t("written again since") : ""].filter(Boolean).join(" · ") }),
    u.verdict ? depthVerdict(u) : null,
    u.kind === "slide" && !u.pid && asks ? depthProjectPick(u, rec) : null,           // its answers belong to a project the person names
    ...(u.findings || []).map((f) => depthFinding(u, f)));
}
function depthFailed() {                                                            // the last review of this edition in this language that could not run, as a band with its fix
  const ed = edition(); if (!ed || depthBusy()) return null;
  const tk = task("depth:" + ed.id), e = tk.error || {};
  if (tk.state !== "error" || (e.lang && e.lang !== docLang())) return null;        // the error of another language's review is said on that sheet
  return band(e.code || "unexpected", { retry: () => depthRun() });                 // needs a translation, no agent, or a failure with a retry
}
function depthBody(rec) {                                                           // the review's findings, thin units first
  const busy = depthBusy(), failed = depthFailed();
  if (!rec || rec.error) return [failed, h("p", { class: "hint", text: t("Reading the review…") })];
  if (rec.none) return [failed, busy ? pill("busy", t("Reviewing each project's depth")) : h("p", { class: "depth-empty", text: t("This edition has no review yet.") }),
    busy ? null : h("button", { class: "btn" + (agentOn() ? " agent" : ""), type: "button", onclick: () => depthRun(), text: t("Review each project's depth") })];
  const units = rec.units || [];                                                    // thin first, as the API lists them
  const rated = units.some((u) => u.verdict);                                       // the agent gave verdicts: the units come in groups
  const withF = units.filter((u) => (u.findings || []).length), clean = units.filter((u) => !(u.findings || []).length && u.reviewed !== false);   // a part the agent never read shows nothing: the note above counts it
  const groups = rated ? ["thin", "adequate", "none", "strong"] : ["none"];         // with no verdict at all, one list as before
  const tally = ["thin", "adequate", "strong"].map((v) => [v, units.filter((u) => u.verdict === v).length]).filter(([, n]) => n);   // how many of each
  return [
    busy ? pill("busy", t("Reviewing each project's depth")) : null,
    failed,                                                                          // the last run failed: the review below is the one before it
    h("p", { class: "depth-sum", text: [t("Reviewed {at}", { at: rec.at || "" }), rec.agent ? t("by the agent") : t("by the checks alone"),
      tn(units.reduce((n, u) => n + (u.findings || []).filter((f) => f.state === "open").length, 0), "{n} finding to act on", "{n} findings to act on")].join(" · ") }),   // counted now: a used or answered one is done
    tally.length ? h("p", { class: "depth-tally" }, ...tally.map(([v, n]) => pill(VERDICT_CLS[v], `${t(DEPTH_VERDICT[v])} ${n}`))) : null,   // the verdicts at a glance
    ...depthNotes(rec),
    ...groups.flatMap((g) => {                                                      // each verdict's units under its heading
      const these = withF.filter((u) => (u.verdict || "none") === g);
      if (!these.length) return [];
      return [rated ? h("div", { class: "depth-group " + g }, h("h2", { text: t(DEPTH_GROUP[g]) }), h("p", { class: "hint", text: t(DEPTH_GROUP_NOTE[g]) })) : null, ...these.map((u) => depthCard(u, rec))];
    }),
    clean.length ? h("p", { class: "hint depth-clean", text: tn(clean.length, "{n} more part shows its depth: {names}", "{n} more parts show their depth: {names}", { names: clean.map((u) => u.title).join(", ") }) }) : null];
}
function drawDepth() {                                                              // the sheet at the edge, when open; drawn again only when what it shows moved on
  let host = document.getElementById("depthsheet");
  if (!host) { host = document.createElement("div"); host.id = "depthsheet"; document.body.append(host); }
  if (typeof S === "undefined" || !S) return;                                       // the state comes first
  const open = !!UI.depthOpen && UI.view === "documents" && UI.depthOpen === depthFor();   // about the edition in view, in its language
  const rec = open ? depthDoc() : null;
  const tk = (typeof edition === "function" && edition()) ? task("depth:" + edition().id) : {};   // a review that failed at once draws its band with no busy state between
  const key = JSON.stringify([open, LANG, docLang(), rec && rec.at, rec && rec.none, rec && rec.stale, depthBusy(), agentOn(), sentAway(), tk.state, tk.error || null,   // what it shows: a typed answer never draws it again
    rec && (rec.units || []).map((u) => [u.id, u.changed, (u.findings || []).map((f) => [f.id, f.state])])]);
  if (host._key === key) return;                                                    // nothing new: the words being typed stay
  host._key = key;
  if (!open) { fill(host); return; }                                                // closed: nothing at the edge
  const ed = edition(), name = job() ? [job().company, job().role].filter(Boolean).join(", ") : named() ? named().name : t("General edition");
  const keep = document.activeElement && host.contains(document.activeElement) ? document.activeElement.dataset.key : null;   // where the keyboard was
  const panel = h("section", { id: "depthpanel", class: "depth-panel" + (host.querySelector("#depthpanel") ? " stay" : ""), role: "dialog", "aria-modal": "true",
    "aria-label": t("Depth of each project"), onkeydown: (e) => { if (e.key === "Escape") { e.stopPropagation(); depthClose(); } else trapTab(e, e.currentTarget); } },
    h("header", { class: "depth-head" }, icon("search"), h("b", { text: t("Depth of each project") }),
      h("span", { class: "depth-sub", text: `${name} · ${t(docLang() === "en" ? "English" : "Korean")}` }), h("span", { class: "grow" }),
      h("button", { class: "btn icon small", type: "button", "aria-label": t("Close"), onclick: () => depthClose() }, icon("close"))),
    h("div", { class: "depth-body" }, ...depthBody(rec)),
    rec && !rec.none ? h("footer", { class: "depth-foot" }, h("button", { class: "btn small" + (agentOn() ? " agent" : ""), type: "button", disabled: depthBusy() || null,
      onclick: () => depthRun(), text: t("Review again") }), sendNote(t("Reviewing sends each project's words and evidence to the agent."))) : null);
  fill(host, panel);                                                                // open: a sheet at the window's right edge
  if (keep) { const k = host.querySelector(`[data-key="${CSS.escape(keep)}"]`); if (k) k.focus({ preventScroll: true }); }   // the keyboard stays where it was
  if (ed && !keep && !panel.classList.contains("stay")) focusSheet("#depthpanel");  // just opened: the keyboard goes in
}
const renderBeforeDepth = render;                                                   // the page's own drawing (and the command bar's), then the sheet
render = function () { renderBeforeDepth(); try { drawDepth(); } catch (_) { /* the sheet never stops the page */ } };   // eslint-disable-line no-global-assign
