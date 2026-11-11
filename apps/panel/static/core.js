// Offerowl's panel, part 1: small helpers, the API, the state and the words shared by every view.
// The server (apps/api) keeps every file and does every piece of work; this page draws its state and sends each change
// at once (autosave). Text from the person's files is always set as text, never as HTML.
"use strict";                                                                       // catches undeclared names and silent writes early

// ---------------------------------------------------------------- elements

const $ = (id) => document.getElementById(id);                                      // one element by id
function h(tag, props, ...kids) {                                                   // an element with props and children
  const el = document.createElement(tag);                                           // the element
  for (const [k, v] of Object.entries(props || {})) {                               // each prop
    if (v === null || v === undefined || v === false) continue;                     // absent
    if (k === "class") el.className = v;                                            // classes
    else if (k === "text") el.textContent = v;                                      // text, never HTML
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);                // events: onclick ...
    else if (k === "style") el.style.cssText = v;                                   // inline style
    else if (k === "value") el.value = v;                                           // a field's value
    else if (["checked", "disabled", "hidden", "selected", "multiple"].includes(k)) el[k] = !!v;  // booleans
    else el.setAttribute(k, v === true ? "" : String(v));                           // any other attribute
  }
  for (const kid of kids.flat(3)) if (kid !== null && kid !== undefined && kid !== false && kid !== "") el.append(kid);  // children
  const key = props && props["data-key"];                                           // a field the person may be typing in
  if (key && (tag === "input" || tag === "textarea" || tag === "select") && typeof UI !== "undefined" && UI.typed[key] !== undefined) el.value = UI.typed[key];  // their words, and a choice in a list, survive a redraw
  return el;                                                                        // callers nest it straight into another h()
}
function fill(el, ...kids) {                                                       // replaceChildren without empty entries
  el.replaceChildren(...kids.flat(3).filter((k) => k !== null && k !== undefined && k !== false && k !== ""));  // null would become the text "null"
  return el;                                                                        // lets callers return fill() in one expression
}
const SVGNS = "http://www.w3.org/2000/svg";                                         // icons are SVG
function icon(name, w) {                                                            // a line icon in Sidenote's hand: a 24 grid, round ends, the text's colour
  const s = document.createElementNS(SVGNS, "svg");                                 // the svg
  const filled = name === "pause";                                                  // the one solid mark
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", fill: filled ? "currentColor" : "none", stroke: filled ? "none" : "currentColor", "stroke-width": "1.8",
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" })) s.setAttribute(k, v);  // outline in the text's colour
  if (w) { s.setAttribute("width", w); s.setAttribute("height", w); }               // a size of its own; else the stylesheet's
  s.innerHTML = ICONS[name] || "";                                                  // fixed paths written here, never data
  return s;                                                                         // ready to put inside a key
}
const ICONS = {                                                                     // every icon of the page: each key that carries one is also labelled
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-2.8 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.9l.1-.1a1.7 1.7 0 0 0-1.2-2.8H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.9-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  edit: '<path d="M21.2 6.8a2.8 2.8 0 0 0-4-4L3.8 16.2 3 21l4.8-.8z"/><path d="m15 5 4 4"/>',   // a pencil: change what is shown
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-9 5.7a2 2 0 0 1-2 0L2 7"/>',   // an envelope: an email address
  phone: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',     // a handset: a phone number
  refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>',
  pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
  close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  agent: '<path d="M12 3.5v17M3.5 12h17M6 6l12 12M18 6L6 18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a13.5 13.5 0 0 1 0 18M12 3a13.5 13.5 0 0 0 0 18"/>',
  folder: '<path d="M3 7.5A2 2 0 0 1 5 5.5h4.2l2 2.3H19a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h4"/>',
  download: '<path d="M12 4v11M7.5 11 12 15.5 16.5 11M5 20h14"/>',
  upload: '<path d="M12 15.5V4.5M7.5 9 12 4.5 16.5 9M5 20h14"/>',
  send: '<path d="M21 3 10.5 13.5"/><path d="M21 3l-6.5 18-4-7.5L3 9.5z"/>',
  link: '<path d="M9 15l6-6"/><path d="M11 6l1.5-1.5a4.2 4.2 0 0 1 6 6L17 12"/><path d="M13 18l-1.5 1.5a4.2 4.2 0 0 1-6-6L7 12"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  copy: '<rect x="9" y="9" width="11.5" height="11.5" rx="2.5"/><path d="M15 5.5A2.5 2.5 0 0 0 12.5 3h-7A2.5 2.5 0 0 0 3 5.5v7A2.5 2.5 0 0 0 5.5 15"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11.2v5"/><path d="M12 7.9v.1"/>',   // a note that tells
  alert: '<path d="M12 4.2l8.6 15H3.4z"/><path d="M12 10v4.2"/><path d="M12 16.9v.1"/>',   // a note that something went wrong
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  desktop: '<rect x="2.5" y="4" width="19" height="13" rx="2"/><path d="M9 20.5h6M12 17v3.5"/>',
  person: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  chat: '<path d="M4.5 5.5h15v10h-9l-4.5 4v-4h-1.5z"/>',
  motion: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  back: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
  layers: '<path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="m3 12.5 9 4.5 9-4.5M3 16.5 12 21l9-4.5"/>',   // Make: what goes in, stacked into documents
  case: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8.5 7V5.5A1.5 1.5 0 0 1 10 4h4a1.5 1.5 0 0 1 1.5 1.5V7M3 12.5h18"/>',   // an application: a briefcase
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
  columns: '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="9.5" y="4" width="5" height="11" rx="1"/><rect x="16" y="4" width="5" height="8" rx="1"/>',   // a board of stages
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17"/><path d="M8 3v4"/><path d="M16 3v4"/>',   // a month's page: pick a day
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  slides: '<rect x="3" y="4.5" width="18" height="12" rx="1.5"/><path d="M12 16.5V20M8.5 20h7M7 9h6M7 12h10"/>',   // a deck to print
  map: '<path d="M9 4.5 3.5 6.5v13L9 17.5l6 2 5.5-2v-13L15 6.5z"/><path d="M9 4.5v13M15 6.5v13"/>',   // the question map
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',   // practice out loud
  plus: '<path d="M12 5v14M5 12h14"/>',
  chart: '<path d="M4 20h16"/><path d="M7 16v-5M12 16V7M17 16v-8"/>',   // the Insights view: columns on a baseline
  trash: '<path d="M4 7h16M9.5 7V4.5h5V7"/><path d="M6.5 7l1 13h9l1-13"/><path d="M10 11v5.5M14 11v5.5"/>',   // deleted for good: a bin, its lid lifted
  restore: '<path d="M4 4v5h5"/><path d="M4.6 15a8 8 0 1 0 .9-7.7L4 9"/>',   // put back: an arrow coming round to where it was
};
// a company's mark: its initials on a square of its own colour, so a list of applications reads by face as well as by name
const MONO_HUES = ["#2f6eba", "#0f766e", "#7c3aed", "#b45309", "#be185d", "#4d7c0f", "#475569", "#9a3412"];   // dark enough for white letters (4.5:1); never the brand navy, which the list itself is
function mono(name, size, stage) {
  const s = String(name || "?").trim();                                             // the company's name
  const words = s.split(/[\s,()]+/).filter(Boolean);                               // its words
  const ini = /^[A-Za-z0-9]/.test(s) ? (words.length > 1 ? words[0][0] + words[1][0] : s.slice(0, 2)).toUpperCase() : s.slice(0, 1);   // two Latin letters, or one Hangul syllable
  let hsh = 0; for (const ch of s) hsh = (hsh * 31 + ch.codePointAt(0)) >>> 0;       // the same name, the same colour, on every screen
  return h("span", { class: "mono" + (size ? " " + size : ""), "data-stage": stage || null, style: stage ? null : `--mc:${MONO_HUES[hsh % MONO_HUES.length]}`, "aria-hidden": "true", text: ini });   // a stage given: its colour, which means something
}
const debounce = (fn, ms) => { let tm = null; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; };  // the last call wins
function localStore(key, value) {                                                   // localStorage that may be blocked
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (_) { /* blocked */ }
  return null;                                                                      // a write, or blocked storage, gives nothing back
}
const enc = encodeURIComponent;                                                     // job ids may be Hangul
function tn(n, one, many, vars) { return t(Number(n) === 1 ? one : many, { n, ...(vars || {}) }); }  // English counts one thing differently; Korean has one form for both

// ---------------------------------------------------------------- state

let S = null;                                                                       // the server's state (GET /api/v1/state)
const UI = {                                                                        // what this page alone remembers
  view: localStore("offerowl-view") || "make",                                      // the navigation's choice; making comes first
  doc: "resume",                                                                    // the canvas's document: resume, cover, deck
  mode: "live",                                                                     // live (the canvas) or typeset (the PDF's pages)
  docLang: localStore("offerowl-doclang") || null,                                   // the document's language (null: the profile's own)
  theme: localStore("offerowl-doctheme") || "navy",                                 // the resume's colour pack
  maxPages: Number(localStore("offerowl-maxpages") || 3),                           // the page limit
  cover: localStore("offerowl-cover") !== "0",                                      // tailoring writes the cover letter too
  typeset: localStore("offerowl-typeset") === "1",                                  // tailoring makes the PDFs too
  tab: "evidence",                                                                  // the inspector's tab
  sel: null,                                                                        // the selected sentence id
  editing: false,                                                                   // the selected sentence is being edited
  filter: null,                                                                     // the facts shown: todo, kept, dropped, all; first the ones to confirm, else the kept ones
  factEdit: null,                                                                   // the fact being edited
  jobPhone: false,                                                                  // on a phone: one application open on its own (else the list of them)
  adding: false,                                                                    // the job form is open
  jobsMode: "list",                                                                 // the applications as a list beside the one open, a board by stage, or by date
  menu: false,                                                                      // the settings menu is open
  drawer: false,                                                                    // the inspector drawer is open (narrow windows)
  offline: false,                                                                   // the server stopped answering
  docs: {},                                                                         // fetched documents by key
  docsVer: 0,                                                                       // counts every document that arrived (the panes redraw on it)
  fits: {},                                                                         // fetched fits by job and revision
  boards: {},                                                                       // fetched interview boards by job and revision
  pending: {},                                                                      // keys being fetched now
  notified: {},                                                                     // reminders already shown as notifications
  typed: {},                                                                        // words typed in forms not sent yet, by field key
};
const DRAFT_KEYS = /^(j-|r-|i-|f-|sentence-edit$)/;                                 // forms whose words are kept until sent (the rest save as you type): i- is an interview round
document.addEventListener("input", (e) => {                                         // every keystroke in a kept form
  const k = e.target && e.target.dataset && e.target.dataset.key;                   // its field
  if (k && DRAFT_KEYS.test(k)) UI.typed[k] = e.target.value;                        // kept until the form is sent or closed
});
function forget(prefix) { for (const k of Object.keys(UI.typed)) if (k.startsWith(prefix)) delete UI.typed[k]; }  // a form was sent or closed

// ---------------------------------------------------------------- the API

const NOT_SAVED = /^\/api\/v1\/(interview\/start|jobs\/select|open|ask|agent\/[a-z_-]+)$/;   // writes that keep none of the person's work: the kit started, a job in view, a folder opened, an ask begun, the agent checked
async function api(path, body) {                                                    // one request; writes return the new state
  let r;                                                                            // declared outside try so the checks below can read it
  try {                                                                             // only a network failure throws here, not an HTTP error
    r = await fetch(path, body === undefined ? { cache: "no-store" } :              // no body means a read, never served from the cache
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });  // JSON only
  } catch (_) {                                                                     // fetch itself failed: no server at all
    setOffline(true);                                                               // the server is not answering
    throw new Error("offline");                                                     // callers stop here; the band already says why
  }
  setOffline(false);                                                                // any answer at all means the server is back
  const j = await r.json().catch(() => ({ error: "unexpected" }));                  // the answer
  if (j && j.state) { S = j.state; render(); }                                      // every write sends the state back
  if (!r.ok) throw Object.assign(new Error(j.error || "unexpected"), { info: j });  // a refused request
  if (body !== undefined && !NOT_SAVED.test(path)) flashSaved();                   // autosave: say it was kept (a request that keeps nothing says nothing)
  return j;                                                                         // callers read extra fields such as started or undone
}
async function act(path, body, okText) {                                            // a write from a button: errors become a toast
  try { const j = await api(path, body); if (okText) toast(okText, null, "done"); schedule(); return j; }  // done, and polled while a task runs
  catch (e) { if (e.message !== "offline") toast(errorText(e), null, "bad"); return null; }      // the reason in words
}
let stateTag = { tag: "", of: null };                                               // the ETag of the state drawn, and that very state object
async function refresh() {                                                          // the state again
  // the tag is sent only while S is still the state it came with: a write, or another read, that put a newer S in place
  // asks for the whole state again, or a 304 could keep that S beside a server that went back to the tagged one
  const tag = stateTag.of === S && S ? stateTag.tag : "";                           // "" asks for the whole state
  try {
    const r = await fetch("/api/v1/state", { cache: "no-store", headers: tag ? { "If-None-Match": tag } : {} });  // no-store: the tag is ours, not the browser cache's
    setOffline(false);                                                              // any answer at all means the server is back
    if (r.ok) {                                                                     // a new state (a 304 is not ok: nothing changed, nothing to draw)
      S = await r.json();                                                           // unpacked by the browser when it came compressed
      stateTag = { tag: r.headers.get("ETag") || "", of: S };                       // for the next poll
      render();                                                                     // drawn
    }
  } catch (_) { setOffline(true); }                                                 // no server at all: the band says so
  schedule();                                                                       // and again later
}
let pollTimer = null;                                                               // the next refresh
function schedule() {                                                               // fast while something runs
  clearTimeout(pollTimer);                                                          // one pending refresh at a time, never a pile
  // a hidden tab does not poll: it asks once when it is shown again (below). Only with notifications on does it keep a slow
  // poll, so a reminder that falls due still shows while the tab is in the background (views.js notifyDue)
  const notes = typeof Notification !== "undefined" && Notification.permission === "granted";   // reminders can show as notifications
  if (document.hidden && !notes) return;                                            // nothing to show anyone until the tab is back
  const running = S && (Object.values(S.tasks || {}).some((x) => x.state === "running") || S.agent.state === "checking" || S.agent.signing_in);  // anything in progress
  pollTimer = setTimeout(refresh, document.hidden ? 60000 : running ? 900 : 8000);  // a minute in the background, else a second or eight
  document.documentElement.dataset.working = running ? "on" : "";                    // the owl's eyes glow while something is made (skin.css)
  const hr = new Date().getHours();                                                 // the hour on this PC
  document.documentElement.dataset.hour = hr >= 20 || hr < 6 ? "night" : "day";     // after dark the desk's lamp is on (skin.css)
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });   // shown again: the state now, then the poll goes on
function setOffline(off) {                                                          // the band that says the server is gone
  if (UI.offline === off) return;                                                   // no redraw when nothing changed
  UI.offline = off;                                                                 // the views read this flag
  if (S) render();                                                                  // nothing to draw before the first state arrives
}
async function getDoc(key, path) {                                                  // a fetched document, cached by key
  if (UI.docs[key] || UI.pending[key]) return UI.docs[key] || null;                 // cached, or on its way
  UI.pending[key] = true;                                                           // one fetch per key
  try { const r = await fetch(path, { cache: "no-store" }); UI.docs[key] = await r.json(); }  // the answer, whatever its status
  catch (_) { UI.docs[key] = { error: "offline" }; }                                // shown as an error
  delete UI.pending[key];                                                           // done
  UI.docsVer++;                                                                     // something new arrived
  render();                                                                         // drawn with it
  return UI.docs[key];                                                              // for callers that wait
}

// ---------------------------------------------------------------- words shared by several places

const KIND = { role: "Employment", project: "Project", education: "Education", skill: "Skills", paper: "Paper", patent: "Patent",  // fact kinds; t() translates them
  award: "Award", certificate: "Certificate", other: "Other", card: "Overview", highlight: "Key project", layer: "Stack",
  competency: "Strength", about: "About me", motivation: "Motivation", typed: "Typed by you", profile: "Profile" };
const STAGE = { preparing: "Preparing", submitted: "Submitted", interview: "Interview", result: "Result" };  // the tracker's columns
const RATING = { strong: "Strong", weak: "Weak", none: "None" };                    // how well a posting line is covered
const RATING_CLS = { strong: "rate strong", weak: "rate weak", none: "rate none", draft: "ai" };   // its lamp: met, in part, not met, as the figures colour them
const CATEGORY = { posting: "Posting lines", resume: "Resume lines", portfolio: "Portfolio pages", term: "Terms", behavioral: "Behavioral",  // the question map's kinds
  company: "Company", opening: "Opening", scenario: "Scenarios", technical: "Technical questions" };
const AGENT_NAME = { "claude-code": "Claude Code", codex: "Codex", "openai-compat": "Local model", none: "No agent", standin: "Stand-in" };  // names a person knows
const VIEWS = [["make", "Make"], ["profile", "Profile"], ["jobs", "Applications"], ["documents", "Documents"], ["insights", "Insights"], ["library", "Library"]];   // an application holds its fit, questions, interview and progress  // the navigation, in order: making first
const ISSUE = { number: "a number the evidence does not have: {w}", number_word: "a counted word the evidence does not have: {w}",  // why a sentence is stopped
  latin: "a tool or name the evidence does not have: {w}", org: "a company the evidence does not have: {w}", no_evidence: "no fact backs this sentence",
  claim: "it says {w}, the evidence says {said}", other: "something the evidence does not say: {w}" };
const GENERAL = "-general";                                                         // the edition with no job (apps/api/app.py has the same name)
const job = () => (S.jobs || []).find((j) => j.id === S.job) || null;               // the job in view (none while the general edition is)
const named = () => (S.editions || []).find((e) => e.id === S.job) || null;       // the named general edition in view, if one is
const jobId = () => (job() || named() ? S.job : undefined);                         // the job or named edition a request names: none for the general edition
const edition = () => job() || named() || S.general || null;                        // what PDFs are made for: the job in view, a named edition, else the general edition
const task = (key) => (S.tasks || {})[key] || {};                                   // one task's state
const docLang = () => UI.docLang || (typeof job === "function" && job() && job().locked && job().locked.lang) || S.profile_lang || "ko";   // the document's language: chosen, else what a submitted application went out in
const taskMarks = () => Object.entries(S.tasks || {}).map(([k, v]) => [k, Object.entries(v || {}).filter(([f]) => f !== "t")]);   // the tasks without their clocks
const rev = () => [S.history, S.undo_id, (S.facts || {}).counts && JSON.stringify(S.facts.counts), (S.facts || {}).rev,  // what changes when the profile changes (rev: any fact's rows; undo_id: a new or rewritten step)
  JSON.stringify((S.jobs || []).map((j) => [j.id, j.plan && j.plan.at, j.plan && (j.plan.projectOrder || []).join(), j.kit])),
  JSON.stringify(taskMarks())].join("|");                                          // each task as it reads, not
// its clock: the clock moves at every report of a run, and a redraw for it (the canvas, the documents fetched again) stalled the
// page for a tenth of a second or more; a step, a result, a run's steps and every write's undo step still count

const PARTS = { browser: "Chrome or Edge", node: "Node.js", pillow: "Pillow for Python", node_modules: "the typesetting libraries" };   // what PDFs need without Docker
function partWords(needs) {                                                         // those parts in words, each once (fonts are named one by one)
  return [...new Set((needs || []).map((n) => t(PARTS[n] || (String(n).startsWith("fonts:") ? "the font files" : n))))].join(", ") || t(PARTS.browser);
}
function errorInfo(code, ctx = {}) {                                                // what went wrong, in words, and the one fix for it
  const agent = t(AGENT_NAME[(S && S.agent && S.agent.backend) || "claude-code"]);  // the agent's name, in the page's language
  const E = {
    agent_unavailable: { msg: t("No agent is turned on, so the agent could not do this."), fix: t("Turn on the agent"), go: () => openAgentMenu() },
    agent_stopped: { msg: t("The agent stopped part way."), fix: t("Try again"), go: ctx.retry },
    talk_failed: { msg: t("The talk could not be made. Check the brief's topics and that this job has a resume made."), fix: t("Try again"), go: ctx.retry },
    needs_draft: { msg: t("The slides use the resume's sentences. Write the resume first."), fix: t("Write the resume"), go: () => { const ed = edition(); if (ed) writeResume(ed.id); } },
    needs_translation: { msg: t("The English edition needs your profile in English."), fix: t("Translate with the agent"), sent: t("Translating sends the words of your profile that a draft does not hold to the agent."), go: () => act("/api/v1/translate", { job: jobId() }) },
    own_lang: { msg: t("The resume you brought in for this one has no edition in this language."), fix: null },   // an own edition, in its languages only
    own_file_type: { msg: t("Bring in a PDF or a Word file for a resume or a cover letter, and a PDF for a portfolio."), fix: null },   // what an own file may be
    name_missing: { msg: t("Your name is missing."), fix: t("Fill in your details"), go: () => go("profile") },
    email_missing: { msg: t("Your email address is missing."), fix: t("Fill in your details"), go: () => go("profile") },
    no_roles: { msg: t("Keep at least one job you held."), fix: t("Open your profile"), go: () => go("profile") },
    engine_not_ready: { msg: t("The typesetting tools are not installed yet."), fix: t("Install them"), go: () => act("/api/v1/engine/setup", {}) },
    renderer_missing: { msg: (S.engine_needs || []).length ? t("Making PDFs needs Docker on this PC. Without it they need: {parts}. The live canvas shows the same document.", { parts: partWords(S.engine_needs) })
      : t("Making PDFs needs Docker on this PC for now. The live canvas shows the same document."), fix: t("Get Docker"), href: "https://docs.docker.com/get-docker/" },
    browser_missing: { msg: t("Making PDFs on this PC needs: {parts}. The live canvas shows the same document.", { parts: partWords(S.engine_needs) }), fix: t("Check again"), go: () => refresh() },   // Windows: no Docker path
    locked: { msg: t("This sentence is locked. Unlock it to change it."), fix: null },
    regen_rejected: { msg: t("The agent's new words said something the evidence does not, so they were not used."), fix: t("Try again"), go: ctx.retry },
    no_evidence: { msg: t("There is no evidence to write from."), fix: null },
    build_failed: { msg: t("The documents could not be made.") + (ctx.detail ? " " + ctx.detail : ""), fix: t("Try again"), go: ctx.retry },
    blind_table: { msg: t("Your table for the blind edition cannot be read. Pick it again in the inspector's Style tab."), fix: t("Open the Style tab"),   // a table changed by hand since it was kept
      go: () => { UI.tab = "style"; UI.drawer = true; render(); } },
    setup_failed: { msg: t("The typesetting tools could not be installed."), fix: t("Try again"), go: () => act("/api/v1/engine/setup", {}) },
    unexpected: { msg: t("Something went wrong on this PC's side. It is written in the log."), fix: t("Try again"), go: ctx.retry },
  };
  return E[code] || E.unexpected;                                                   // an unknown code is a general error
}
function refusedWords(why) {                                                        // why a Word or PowerPoint file stayed home while its PDF went, in words
  const [code, a, b] = String(why || "").split(":");                                // word_pages:7:6, ppt_slides:12:13, or a code alone
  if (code === "word_pages") return t("Word file not exported: Word gives it {word} pages, the PDF has {pdf}.", { word: a, pdf: b });   // Word breaks the pages elsewhere
  if (code === "ppt_slides") return t("PowerPoint file not exported: PowerPoint gives it {slides} slides, the PDF has {pages} pages.", { slides: a, pages: b });
  const W = { word_unopened: t("Word file not exported: Word did not open it."), docx_unready: t("Word file not exported: it could not be made ready for Word."),
    ppt_unopened: t("PowerPoint file not exported: PowerPoint did not open it."), pptx_unmade: t("PowerPoint file not exported: it could not be made from the PDF.") };
  return W[code] || "";                                                             // another code: nothing to add
}
function errorText(e) {                                                             // a refused request as one sentence
  const what = (e.info && e.info.what) || e.message || "";                          // the server's own word
  if (/^unsupported:(\d+)/.test(what)) return tn(what.split(":")[1], "{n} sentence has no evidence. Fix it before exporting.", "{n} sentences have no evidence. Fix them before exporting.");
  if (/^blind_leak:(\d+)/.test(what)) return tn(what.split(":")[1], "{n} pattern of your table still shows in the blind edition, so nothing was exported. Add it to what the table covers and make the PDFs again.",   // a covered name in a PDF's text, title or link
    "{n} patterns of your table still show in the blind edition, so nothing was exported. Add them to what the table covers and make the PDFs again.");
  if (/^blind_pattern:\w+:\d+$/.test(what)) { const [, list, n] = what.split(":"); return t("Pattern {n} of {list} in that table cannot be used. Fix it and pick the file again.", { n, list }); }   // the first pattern Python or JavaScript would read otherwise
  const words = { posting: t("Paste the whole posting: it is too short to read."), bad_link: t("That link cannot be read. Paste the posting's text instead."),
    unreachable: t("The page did not answer. Paste the posting's text instead."), not_text: t("That link is not a web page. Paste the posting's text instead."),
    empty: t("That page has no text Offerowl can read. Paste the posting's text instead."), too_large: t("That page is too large. Paste the posting's text instead."),
    not_built: t("Make the PDFs first."), locked: t("This application was submitted and locked."), edit_in_korean: t("Edit the Korean sentence, then translate again."),
    no_fact: t("Change this part in your profile."), at: t("Pick a date for the reminder."), text: t("Write what to be reminded of."), sentence: t("That sentence changed. Pick it again."),
    style: t("That file is not a rules file."), photo: t("Use a JPEG or PNG photo."), answers_need_attention: t("An answer still needs your fix. Its problems are under it."),
    questions: t("Write the question first."), no_questions: t("No question was found in it. Paste the form's questions as they appear."), question: t("That question changed. Open the job again."),
    checks_failed: t("These documents did not pass their checks, so they stay here. The list above the document says what failed."),
    changed: t("The PDFs changed after they were checked. Make the PDFs again."), copy_unreadable: t("The copy on the Desktop did not read back, so it was taken away. Try again."),
    material_changed: t("This file changed after you added it, so no copy was made."), material: t("That file is no longer in the list. Open the job again."),
    removed: t("That was put back or deleted already. The list shows how things are now."), busy: t("Wait until the work in progress ends, then try again."),
    delete_failed: t("Some of its files could not be deleted: another program may have them open. Close it and try again."),
    blind_table: t("That file is not a mask table."), blind_unread: t("The blind edition's text could not be read, so nothing was exported. Make the PDFs again.") };
  return words[what] || errorInfo(e.message === "bad_request" ? "unexpected" : e.message).msg;  // a known refusal, else the general words
}

// ---------------------------------------------------------------- small shared pieces

// ---------------------------------------------------------------- addresses in words a person or the agent wrote
// A meeting's link, a booking page, a posting's address: written into a next step, a round's notes, a reminder or a file
// the person added, each shows as a link that opens in a new tab, named for its service (Google Meet, Zoom, Calendly) or
// its site, the whole address on hover. Only http and https; nothing of this page is passed on (noopener, noreferrer).
const LINK_RE = /\bhttps?:\/\/[^\s<>"'`]+/gi;                                          // an address, up to a space or a quote
const LINK_END = /[.,;:!?)\]}>'"’”…]+$/;                                            // the stop or bracket that ends a sentence, not the address
const LINK_NAMES = [[/(^|\.)meet\.google\.com$/, "Google Meet"], [/(^|\.)zoom\.(us|com)$/, "Zoom"], [/(^|\.)teams\.(microsoft|live)\.com$/, "Microsoft Teams"],
  [/(^|\.)webex\.com$/, "Webex"], [/(^|\.)calendly\.com$/, "Calendly"], [/^cal\.com$/, "Cal.com"], [/^calendar\.(google\.com|app\.google)$/, "Google Calendar"],
  [/^forms\.gle$/, "Google Forms"]];                                                // the services a meeting or a booking usually comes through
function linksIn(text) {                                                            // each address in the words: [start, end, address]
  const s = String(text || ""), out = [];
  for (const m of s.matchAll(LINK_RE)) {
    let u = m[0]; const tail = LINK_END.exec(u); if (tail) u = u.slice(0, tail.index);   // "...meet.google.com/abc." ends before the stop
    if (u.length > 10) out.push([m.index, m.index + u.length, u]);                  // "http://" alone is not an address
  }
  return out;
}
function linkName(u) {                                                              // what a link is called: its service, else its site
  let host = ""; try { host = new URL(u).hostname.replace(/^www\./, ""); } catch (_) { return u; }
  const known = LINK_NAMES.find(([re]) => re.test(host));
  return known ? known[1] : host;
}
function linkKey(u) {                                                               // one link: its name and the mark of a new tab, the address on hover
  return h("a", { class: "xlink", href: u, target: "_blank", rel: "noopener noreferrer", title: u, draggable: "false",
    onclick: (e) => e.stopPropagation() }, linkName(u), icon("open"));              // a click opens it, not the card it is on
}
function linked(text) {                                                             // words with their addresses as links
  const s = String(text || ""), out = []; let at = 0;
  for (const [a, b, u] of linksIn(s)) { if (a > at) out.push(s.slice(at, a)); out.push(linkKey(u)); at = b; }
  if (at < s.length) out.push(s.slice(at));
  return out;
}
function unlinked(text) {                                                           // the words with each address as its name: inside a key, where a link cannot be
  const s = String(text || ""); let out = "", at = 0;
  for (const [a, b, u] of linksIn(s)) { out += s.slice(at, a) + linkName(u); at = b; }
  return out + s.slice(at);
}
function linkKeys(text) {                                                           // the links alone, to stand beside a key that holds the words
  const ls = linksIn(text);
  return ls.length ? h("span", { class: "xlinks" }, ls.map(([, , u]) => linkKey(u))) : null;
}
function placeToast(el) {                                                          // a note never lies across a box: on a wide window it shows in the bar, in the room between the views and the keys
  document.querySelectorAll(".under-toast").forEach((x) => x.classList.remove("under-toast"));   // what the last note covered shows again
  el.classList.remove("inbar");
  const bar = document.querySelector("#top .bar-in");                              // the sticky bar
  if (!bar) return;
  if (!matchMedia("(min-width: 861px)").matches) return stepAside(el, bar, ".brand, .brand-ver, .barpop, .actions, .views");   // a phone's bar scrolls away: its note is a band across the window's top (skin.css)
  const keys = [...bar.children].filter((x) => x.matches(".barchip, .barpop, .actions") && x.getBoundingClientRect().width);   // the bar's own keys, at its right
  const mark = bar.querySelector(".brand-ver") || bar.querySelector(".brand");     // the wordmark and its version, at its left
  if (!keys.length || !mark) return;
  const k = keys[0].getBoundingClientRect(), m = mark.getBoundingClientRect();
  el.classList.add("inbar");
  const most = m.right + 16;                                                        // no further left than the wordmark
  const v = bar.querySelector(".views")?.getBoundingClientRect();                   // the views, when they share the keys' row
  const from = v && v.width && Math.abs(v.top + v.height / 2 - (k.top + k.height / 2)) < 8 ? v.right + 12 : most;   // where the room beside them starts
  const last = keys[keys.length - 1].getBoundingClientRect();                       // Undo and the settings: never under a note
  const chipFree = !bar.querySelector(".barpop .pop");                              // the agent's chip may step aside, unless its panel is open
  const rooms = [[from, k.left - 12], chipFree && keys.length > 1 ? [from, last.left - 12] : null, [most, (chipFree ? last : k).left - 12]].filter(Boolean);
  const fit = ([l, r]) => {                                                         // in a room: its size there, against the room's right end
    el.style.setProperty("--toast-right", `${Math.round(innerWidth - r)}px`);
    el.style.setProperty("--toast-max", `${Math.round(Math.max(240, r - l))}px`);
    return [el.offsetWidth, el.offsetHeight];
  };
  let wid = 0, hgt = 0, room = rooms[rooms.length - 1];
  for (const r of rooms) {                                                          // the room the views leave, then with the agent's chip aside, then over the views
    [wid, hgt] = fit(r); room = r;
    if (r[1] - r[0] >= 200 && hgt <= k.height + 12) break;                          // two lines at most, within the bar's row
  }
  el.style.setProperty("--toast-right", `${Math.round(innerWidth - (room[0] + room[1]) / 2 - wid / 2)}px`);   // centred in its room, as Sidenote's notes stand
  el.style.setProperty("--toast-top", `${Math.max(4, Math.round(k.top + k.height / 2 - hgt / 2))}px`);   // its middle on the keys' row, never above the window
  stepAside(el, bar, ".views, .jobpick, .saved, .barpop");                         // the views' track whole: a note never lies across its rim
}
function stepAside(el, bar, what) {                                                 // laid out: what of the bar the note lies over steps aside while it shows (its glass would show it blurred)
  requestAnimationFrame(() => {
    const t = { left: el.offsetLeft, top: el.offsetTop, right: el.offsetLeft + el.offsetWidth, bottom: el.offsetTop + el.offsetHeight };   // where it comes to rest, not where its slide in has it now
    for (const x of bar.querySelectorAll(what)) {
      const r = x.getBoundingClientRect();
      if (r.width && r.right > t.left - 6 && r.left < t.right + 6 && r.bottom > t.top && r.top < t.bottom) x.classList.add("under-toast");
    }
  });
}
function toast(text, key, kind) {                                                   // a short note in the bar (at the top on a phone); key {words, run, icon}: one key in it (Undo)
  const el = $("toast");                                                            // the one toast
  clearTimeout(toast.tm);                                                           // the newest note decides how long
  const hide = () => { el.classList.remove("show", "keyed"); document.querySelectorAll(".under-toast").forEach((x) => x.classList.remove("under-toast")); };   // gone, no longer in the way of a click, and what it covered back
  const k = kind || (key ? "done" : "info");                                        // what kind of note: done (it can be undone), warn (it held back), bad (it failed), or info
  el.dataset.kind = k;                                                              // its mark's colour (skin.css)
  fill(el, h("span", { class: "toast-mark", "aria-hidden": "true" }, icon({ done: "check", bad: "alert", warn: "alert" }[k] || "info")),   // the kind at a glance, its words say the rest
    h("span", { class: "toast-w", text }),                                          // the words, as text
    key ? h("button", { class: "btn small toast-key", type: "button", onclick: () => { clearTimeout(toast.tm); hide(); key.run(); } }, icon(key.icon || "undo"), key.words) : null);
  el.classList.toggle("keyed", !!key);                                              // a note with a key takes clicks (skin.css); the others let them through
  placeToast(el);                                                                   // inside the bar on a wide window, at the foot on a phone
  el.classList.add("show");                                                         // shown
  const words = String(text || "").split(/\s+/).length;                            // a long message, an error's reason and its fix, needs the time to be read
  const stay = key ? 10000 : Math.min(12000, Math.max(3600, words * 350));          // a key needs the time to be reached as well
  const later = () => { toast.tm = setTimeout(() => {                               // gone after it can be read, but never under the pointer or the keyboard
    if (el.matches(":hover") || el.contains(document.activeElement)) later(); else hide(); }, stay); };
  later();
}
async function removeAct(path, body, words) {                                       // a removal: done at once, and its note holds Undo (it asks nothing first: it comes back)
  try {
    const j = await api(path, body);                                                // done; the new state is drawn
    schedule();                                                                     // polled while a task runs, as act() does
    toast(words, j.step ? { words: t("Undo"), run: () => undoOnly(j.step) } : null);   // the step the answer names: this change, never one another writer made just after it
    return j;
  } catch (e) { if (e.message !== "offline") toast(errorText(e), null, "bad"); return null; }    // the reason in words
}
async function undoOnly(id) {                                                       // a note's Undo: the change it named, only while it is still the newest
  const r = await act("/api/v1/undo", { only: id });                                // the server compares the names under its lock
  if (r) toast(r.moved ? t("A later change came first, so nothing was undone. The history lists both.")
    : r.undone ? t("Undone: {what}", { what: undoLabel(r.undone) }) : t("Nothing to undo."));
}

// ---------------------------------------------------------------- the panel's own question
// Asked before what cannot be taken back (deleting for good, emptying the Removed list, restoring a backup, undoing several
// changes at once), on the panel's own sheet instead of the browser's grey box: its title says what happens, its lines what
// stays. The safe key holds the keyboard: Enter on it, Esc and a click beside the sheet all say no. With no cancel it is a
// notice to read (in place of alert()). Resolves true for its main key.
function askFirst({ title, text, lines, ok, danger, cancel = true }) {
  return new Promise((resolve) => {
    const host = $("confirm"), back = document.activeElement;                       // the sheet's place, and the key that asked
    const keys = (e) => {                                                           // the keyboard while it is open, before any other handler
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); close(false); return; }   // no
      if (e.key !== "Tab") return;                                                  // Enter is the focused key's own
      const ks = [...host.querySelectorAll("button")], i = ks.indexOf(document.activeElement);   // the keyboard goes round the sheet's keys only
      e.preventDefault(); if (ks.length) ks[(i + (e.shiftKey ? ks.length - 1 : 1)) % ks.length].focus();
    };
    const close = (yes) => {                                                        // answered: the sheet goes, the keyboard goes back to the key that asked
      document.removeEventListener("keydown", keys, true);
      UI.confirm = null; lockPage(); host.hidden = true; fill(host);
      const again = back && !back.isConnected && back.dataset && back.dataset.key ? document.querySelector(`[data-key="${CSS.escape(back.dataset.key)}"]`) : null;   // a poll drew that key anew meanwhile
      const to = back && back.isConnected ? back : again;
      if (to && to.focus) to.focus({ preventScroll: true });
      resolve(yes);
    };
    const no = cancel ? h("button", { class: "btn", type: "button", "data-key": "confirm-no", onclick: () => close(false) }, t("Cancel")) : null;
    const yes = h("button", { class: "btn " + (danger ? "danger-solid" : "primary"), type: "button", "data-key": "confirm-yes", onclick: () => close(true) },
      danger ? icon("trash") : null, ok || t("OK"));                                // what it does, in the words of the action
    UI.confirm = true; lockPage();                                                  // the page behind takes nothing
    fill(host, h("div", { class: "confirm-scrim", onclick: () => close(false) }),
      h("section", { class: "confirm" + (danger ? " danger" : ""), role: cancel ? "alertdialog" : "dialog", "aria-modal": "true", "aria-labelledby": "confirm-title", "aria-describedby": "confirm-text" },
        h("h2", { id: "confirm-title", text: title }),
        h("div", { id: "confirm-text", class: "confirm-text" }, text ? h("p", { text }) : null,
          (lines || []).length ? h("ul", { class: "confirm-lines" }, lines.map((l) => h("li", {}, icon("check", 14), h("span", { text: l })))) : null),
        h("footer", { class: "confirm-keys" }, no, yes)));
    host.hidden = false;
    document.addEventListener("keydown", keys, true);                               // first: Esc here never also closes what lies behind
    (no || yes).focus({ preventScroll: true });                                     // the safe key, so a quick Enter says no
  });
}
function lockPage() {                                                               // the page behind a sheet takes no click and no key: the setup guide, or a question over all
  const sheet = UI.setup != null || UI.confirm != null;                             // a sheet is open
  for (const id of ["skip", "top", "work", "askbar"]) { const n = document.getElementById(id); if (n) n.inert = sheet; }   // never the toast, which says what a key did
  const guide = document.getElementById("setup"); if (guide) guide.inert = UI.confirm != null;   // a question over the guide: the guide waits too
}
function flashSaved() {                                                             // "Saved" in the bar for a moment
  const el = document.querySelector(".saved");                                      // drawn by the bar
  if (!el) return;                                                                  // not drawn yet
  el.classList.add("show");                                                         // shown
  clearTimeout(flashSaved.tm);                                                      // the newest save decides
  flashSaved.tm = setTimeout(() => el.classList.remove("show"), 1600);              // faded
}
function pill(cls, text) { return h("span", { class: "pill " + cls, text }); }      // a lamp and a word
function band(code, ctx) {                                                          // an error band with its one fix
  const e = errorInfo(code, ctx);                                                   // the words
  return h("div", { class: "band", role: "alert" }, h("p", { text: e.msg }), e.sent ? sendNote(e.sent) : null,
    e.fix ? (e.href ? h("a", { class: "btn small", href: e.href, target: "_blank", rel: "noopener", text: e.fix })
      : h("button", { class: "btn small" + (e.sent ? " agent" : ""), onclick: () => e.go && e.go(), text: e.fix })) : null);   // a fix that sends to the agent is orange
}
function agentOn() { return !!(S && S.agent && S.agent.state === "ready"); }         // an agent that would answer now: the only case in which anything is sent
function sendNote(what) {                                                           // the line beside a button that asks the agent: what goes to it
  return agentOn() ? h("p", { class: "hint" }, sentLine(true), " ", what) : null;    // with no agent nothing is sent, so there is nothing to say
}
function sentLine(sent, why) {                                                      // what an action sends to the agent, or that nothing leaves the PC; its sentence on hover
  return sent ? h("span", { class: "chip ai", title: why || null, text: t("Goes to the agent") }) : h("span", { class: "chip pc", title: why || null, text: t("Stays on this PC") });
}
function ago(ts) {                                                                  // a time as "3 min ago"
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));                        // seconds since
  if (s < 60) return t("just now");                                                 // under a minute
  if (s < 3600) return t("{n} min ago", { n: Math.round(s / 60) });                 // minutes
  if (s < 86400) return t("{n} h ago", { n: Math.round(s / 3600) });                // hours
  return t("{n} d ago", { n: Math.round(s / 86400) });                              // days
}
// the words of a quote or a sentence without the marks the documents keep (==highlight==, **bold**): a source's own words carry them
// when the file was written in Markdown, and every place that shows those words as plain text drops them
const unmarked = (text) => String(text || "").replace(/==|\*\*/g, "");
function marks(text, cls = "dochl") {                                               // ==phrase== as the highlighter, the rest as text
  const out = [];                                                                   // text and marks
  String(text || "").split(/(==[^=]+==)/).forEach((part) => {                       // marks never nest
    if (/^==[^=]+==$/.test(part)) out.push(h("mark", { class: cls, text: part.slice(2, -2) }));  // the highlighted phrase
    else if (part) out.push(document.createTextNode(part.replace(/\*\*/g, "")));    // plain text, stray bold marks dropped
  });
  return out;                                                                       // nodes for an element
}
function go(view) {                                                                 // open a view of the navigation
  if (view === "interview") { UI.jobTab = "interview"; view = "jobs"; }              // the interview is a part of each application
  else if (view === "tracker") { UI.jobsMode = "board"; view = "jobs"; }             // the tracker is every application by stage
  UI.view = view; localStore("offerowl-view", view);                                // remembered in this browser
  UI.drawer = false;                                                                // the drawer closes on a move
  render();                                                                         // drawn
  const c = $("canvas"); if (c) c.focus({ preventScroll: true });                   // the keyboard follows
  window.scrollTo({ top: 0, behavior: "instant" });                                 // the view starts at its top
}

// ---------------------------------------------------------------- pages of a long list
function pager(page, pages, turn, info) {                                           // where the list stands on the left; the pages, numbered, on the right
  if (pages <= 1) return info ? h("div", { class: "pgr" }, h("span", { class: "pgr-info", text: info })) : null;
  const shown = new Set([0, pages - 1, page - 1, page, page + 1].filter((p) => p >= 0 && p < pages));   // the ends, and the pages around this one
  const nums = [...shown].sort((a, b) => a - b), keys = [];
  nums.forEach((p, i) => {
    if (i && p - nums[i - 1] > 1) keys.push(h("span", { class: "pgr-gap", "aria-hidden": "true", text: "…" }));   // pages left out
    keys.push(h("button", { type: "button", class: "pgr-n", "aria-current": p === page ? "page" : null, "aria-label": t("Page {n}", { n: p + 1 }), onclick: () => turn(p), text: String(p + 1) }));
  });
  return h("nav", { class: "pgr", "aria-label": t("Pages") }, info ? h("span", { class: "pgr-info", text: info }) : null,
    h("div", { class: "pgr-keys" },
      h("button", { type: "button", class: "pgr-n pgr-arrow", disabled: page <= 0 || null, "aria-label": t("Previous page"), onclick: () => turn(page - 1) }, icon("back")),
      keys,
      h("button", { type: "button", class: "pgr-n pgr-arrow flip", disabled: page >= pages - 1 || null, "aria-label": t("Next page"), onclick: () => turn(page + 1) }, icon("back"))));
}

// ---------------------------------------------------------------- days and times, written one way across the panel
// A day reads 2026-11-09, a month and day 11-09 and a time 19:00 wherever the panel shows one, so the fields where one is
// typed show it the same way, never the browser's own pattern (11/09/2026 on one PC, 2026. 11. 09. on another, a 12-hour
// clock on a third). The browser's calendar and clock are still a key away: a hidden native field opens and hands its
// value back. Typed days are read in the usual ways (2026.11.9, 2026/11/09, 20261109, 2026년 11월 9일) and shown back as one.
function isoDay(text) {                                                             // the day as YYYY-MM-DD; "" for nothing; null for what is no day
  const s = String(text || "").trim();
  if (!s) return "";
  const m = /^(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*[.일]?$/.exec(s) || /^(\d{4})(\d{2})(\d{2})$/.exec(s);
  if (!m) return null;
  const y = +m[1], mo = +m[2], d = +m[3], dt = new Date(y, mo - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;   // 2026-02-30 is no day
  return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}
function isoTime(text) {                                                            // the time as HH:MM on a 24-hour clock; "" for nothing; null for what is no time
  const s = String(text || "").trim().toLowerCase();
  if (!s) return "";
  const pm = /pm|오후/.test(s), am = /am|오전/.test(s);                             // a 12-hour time says which half
  const digits = s.replace(/pm|am|오후|오전/g, "").trim();
  const m = /^(\d{1,2})\s*(?:[:.시 ]\s*(?:(\d{1,2})\s*분?)?)?$/.exec(digits) || /^(\d{2})(\d{2})$/.exec(digits);   // 19:00, 19.00, 19시, 19시 30분, 1900, 7
  if (!m) return null;
  let hh = +m[1];
  const mm = +(m[2] || 0);
  if (pm && hh < 12) hh += 12;                                                      // 7 pm is 19
  if (am && hh === 12) hh = 0;                                                      // 12 am is midnight
  if (hh > 23 || mm > 59) return null;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}
const shortDay = (day) => String(day || "").slice(5, 10);                           // 2026-11-09 as 11-09: a month and a day on a card or an axis
const pad2 = (n) => String(n).padStart(2, "0");
const dayTime = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;   // a Date as 2026-11-10 04:37, this PC's time
function pickField(kind, attrs, value, onValue) {                                   // a day or a time typed the panel's way, or picked from the browser's own
  const read = kind === "date" ? isoDay : isoTime;
  const box = h("input", Object.assign({ type: "text", inputmode: "decimal", autocomplete: "off", spellcheck: "false", maxlength: 16,
    placeholder: kind === "date" ? "YYYY-MM-DD" : "HH:MM", value: read(value) || "" }, attrs));   // the words a person types (or kept from a redraw: h restores them)
  const key = attrs && attrs["data-key"];                                           // a kept form's field remembers what was typed (UI.typed)
  const show = (v, chosen) => {                                                     // one value, written the panel's way, everywhere it is kept
    box.value = v; pick.value = v;
    if (chosen && key && DRAFT_KEYS.test(key)) UI.typed[key] = v;                   // typed or picked in a kept form: a redraw brings it back (picking types nothing)
  };
  const pick = h("input", { type: kind, class: "pick", tabindex: "-1", "aria-hidden": "true",   // the browser's calendar or clock, never seen itself
    onchange: (e) => { show(e.target.value, true); box.setCustomValidity(""); if (onValue) onValue(e.target.value); } });   // its answer, written the panel's way
  const now = read(box.value);                                                      // what the field holds now, read
  if (now !== null) show(now);                                                      // a kept 2026/11/12 comes back as 2026-11-12
  box.addEventListener("change", () => {                                            // typed: read in any common way
    const v = read(box.value);
    if (v === null) { box.setCustomValidity(t(kind === "date" ? "Write the day as 2026-11-09." : "Write the time as 19:00.")); box.reportValidity(); return; }
    box.setCustomValidity(""); show(v, true);                                        // shown back as the panel writes it
    if (onValue) onValue(v);
  });
  box.addEventListener("input", () => box.setCustomValidity(""));                   // a new try clears the last complaint
  const word = kind === "date" ? t("Pick a day") : t("Pick a time");
  const opener = h("button", { type: "button", class: "btn icon pick-key", title: word, "aria-label": word,
    onclick: () => { try { pick.showPicker(); } catch (_) { pick.focus(); } } }, icon(kind === "date" ? "calendar" : "clock"));   // opens the browser's own
  return h("span", { class: "pickfield" }, box, opener, pick);
}
const dayField = (attrs, value, onDay) => pickField("date", attrs, value, onDay);   // a day: 2026-11-09
const timeField = (attrs, value, onTime) => pickField("time", attrs, value, onTime);   // a time: 19:00
