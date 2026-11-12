// Offerowl's panel, part 5: making. The person drops files or folders anywhere on the page, or pastes their paths, and
// may give a posting (a link or its text). The run (apps/api/autopilot.py) reads them, keeps the facts whose quotes are
// found, writes, translates, typesets and puts the PDFs on the Desktop, with nothing to click in between. A posting
// given later is tailored from the facts already kept. The view is the work itself, in three columns read from left to
// right: your files go in, the progress of the run, your documents come out.
"use strict";                                                                       // catches undeclared names and silent writes early

const READABLE = /\.(pdf|docx|pptx|txt|md|json|csv|ya?ml|png|jpe?g|tiff?|bmp|webp|zip)$/i;   // what the readers take: the server's own list (apps/api/autopilot.py READABLE), a zip too: the server opens it into its files
const SKIP_DIRS = new Set(["node_modules", "__pycache__", "venv", "site-packages", "dist", "build", "target", "out", "tmp", "temp", "cache", "caches",  // folders that hold no career
  "appdata", "application data", "local settings", "library", "programdata", "program files", "program files (x86)", "windows", "$recycle.bin", "system volume information"]);  // and a system's own, as the server skips them
const MAX_FILES = 80;                                                               // files one run reads, as the server caps it
const MAX_BYTES = 60 * 1024 * 1024;                                                 // one file's bytes, as an upload is capped
const PATHLIKE = /^\s*("?)(?:[A-Za-z]:[\\/]|\\\\|\/|~\/)[^\n]*\1\s*$/;              // a line that is a path: C:\..., \\wsl..., /..., ~/...

function wanted(f) {                                                                // a file worth sending: a kind the readers know, not hidden, not in a code folder
  const path = (f.webkitRelativePath || f._path || f.name || "").split("/");        // its folders, when it came with a folder
  if (path.some((p, i) => p.startsWith(".") || (i < path.length - 1 && SKIP_DIRS.has(p.toLowerCase())))) return false;  // hidden, or under node_modules and the like
  if (f.name.startsWith("~$")) return false;                                        // an Office lock file
  return READABLE.test(f.name) && f.size > 0 && f.size <= MAX_BYTES;                // readable and of a size an upload takes
}
async function droppedFiles(dt, kinds = READABLE, keep = wanted) {                  // the files of a drop, with every file inside a dropped folder: those of `kinds` that `keep` takes (a job's materials pass their own)
  const entries = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);  // files and folders
  if (!entries.length) return [...dt.files];                                        // a browser without folders: the files as they are
  const out = [];                                                                   // the readable files found
  let more = 0;                                                                     // readable files past the cap: only counted
  const walk = async (e, path, depth) => {                                          // one entry, and what is under it
    if (depth > 12) return;                                                         // a folder too deep to be a career's
    if (e.isFile) {                                                                 // a file
      if (!kinds.test(e.name) || e.name.startsWith(".") || e.name.startsWith("~$")) return;   // not a kind asked for: never counted
      if (out.length >= MAX_FILES) { more++; return; }                              // enough: the rest are counted for the note
      const f = await new Promise((ok) => e.file(ok, () => ok(null)));              // the file itself
      if (f) { f._path = path + f.name; if (keep(f)) out.push(f); }                 // with its folders, when it is one to send
      return;
    }
    if (!e.isDirectory || e.name.startsWith(".") || SKIP_DIRS.has(e.name.toLowerCase())) return;   // hidden, code and system folders are skipped
    const reader = e.createReader();                                                // the folder's list comes in batches
    const all = [];                                                                 // the whole list, to read in name order
    for (;;) {                                                                      // until a batch is empty
      const batch = await new Promise((ok) => reader.readEntries(ok, () => ok([])));  // the next batch
      if (!batch.length) break;                                                     // the folder is read
      all.push(...batch);                                                           // kept
    }
    all.sort((a, b) => a.name.localeCompare(b.name));                               // the same order every time, as the server walks
    for (const x of all) await walk(x, path + e.name + "/", depth + 1);             // each, in turn
  };
  for (const e of entries) await walk(e, "", 0);                                    // each dropped thing
  out.more = more;                                                                  // said with the start
  return out;                                                                       // filtered again by makeFrom
}
async function sendFiles(files) {                                                   // the files into the workspace, one request each; their ids
  const ids = [], missed = [];                                                      // the new materials, and the files that did not get in
  UI.sending = { done: 0, total: files.length }; render();                          // the sheet says how far
  for (const f of files) {                                                          // in order
    try {
      const r = await postFile("/api/v1/materials", f);                             // the raw file and its own name, asked again while the server is busy
      const j = await r.json().catch(() => ({}));                                   // a refused upload may not answer with JSON
      if (r.ok && j.material) ids.push(...(j.materials || [j.material]).map((m) => m.id));   // kept; a zip gives several
      else missed.push(f.name);                                                     // refused, or the server still busy after two tries
    } catch (_) { missed.push(f.name); }                                            // the server stopped: the band says so too
    UI.sending.done++; $("canvas")._key = null; render();                           // one more
  }
  UI.sending = null;                                                                // done
  if (missed.length) toast(tn(missed.length, "{n} file could not be added: {names}", "{n} files could not be added: {names}", { names: missed.slice(0, 3).join(", ") + (missed.length > 3 ? ` +${missed.length - 3}` : "") }), null, "warn");   // never left out unsaid
  return ids;                                                                       // for the run
}
function postingParts(text) {                                                       // a posting as the person gave it: a link, or its words
  const s = String(text || "").trim();                                              // without stray space
  return /^https?:\/\/\S+$/.test(s) ? { url: s, posting: "" } : { url: "", posting: s };  // one line that is a link is a link
}
async function makeFrom({ files = [], paths = [], posting } = {}) {                 // one run from what the person gave
  if (UI.sending) { toast(t("Wait until the files are sent.")); return; }           // one send at a time
  const take = files.filter(wanted).slice(0, MAX_FILES);                            // the files worth reading
  const left = files.length - take.length + (files.more || 0);                      // the ones skipped, and the readable ones past the cap
  const given = posting === undefined ? (UI.typed["mk-posting"] || "") : posting;   // a posting typed in its box goes with the files
  if (!take.length && !paths.length && !given.trim()) {                             // nothing to read
    toast(files.length ? t("None of these files can be read. Use PDF, Word, PowerPoint, pictures or text.") : t("Drop files or folders, or paste their paths."), null, files.length ? "bad" : "info");
    return;
  }
  if (UI.view !== "make") go("make");                                               // the run is followed here
  closeSetup();                                                                     // files dropped over the setup guide start the run it leads to: the run in sight
  const ids = take.length ? await sendFiles(take) : [];                             // sent first
  const r = await act("/api/v1/autopilot", { ids, paths, ...postingParts(given), theme: UI.theme, max_pages: UI.maxPages });  // then the run, in the colour and length picked on the canvas
  if (!r) return;                                                                   // refused: the toast said why
  const typing = document.activeElement;                                            // a box still holding what was sent
  if (typing && typing.dataset && /^mk-/.test(typing.dataset.key || "")) typing.blur();   // or its words would come back with the redraw
  forget("mk-");                                                                    // the boxes are empty again
  UI.lastStart = { files: r.files, skipped: left + (r.skipped || []).length };      // what the sheet says about this start
  toast(r.queued ? t("It starts when the run in progress ends.") : r.started ? t("Started. About {m} min, nothing to click until it ends.", { m: r.estimate.minutes }) : t("It did not start. Try again."), null, r.queued || r.started ? "info" : "bad");
  $("canvas")._key = null; render();                                                // the boxes empty on screen
}
function problemWords(code) {                                                       // one step's reason in words (an error code, or a count)
  if (!code || /^\d+$/.test(code)) return "";                                      // nothing to say
  if (["no_files", "agent_unavailable", "no_roles"].includes(code)) return runError(code).short;   // the run's own reasons
  const STEP = { failed: t("The agent stopped part way."), agent_stopped: t("The agent stopped part way."), needs_agent: t("No AI agent"),   // the steps' own codes
    needs_draft: t("Needs the resume first"), not_written: t("Not written"), bad_link: t("The link did not open"), unreachable: t("The link did not open"),
    not_text: t("The link did not open"), too_large: t("The link did not open"), empty: t("The posting is too short"), posting: t("The posting is too short"),
    answers_need_attention: t("An answer needs your fix"), checks_failed: t("Not sent: it did not pass its checks"), changed: t("Not sent: it changed after its checks"), copy_unreadable: t("Not sent: the copy did not read back") };
  if (STEP[code]) return STEP[code];                                                // said plainly
  if (refusedWords(code)) return refusedWords(code);                                // a Word or PowerPoint file kept home by its own check
  if (/^blind_leak:\d+$/.test(code)) return t("Not sent: a name the blind edition covers still shows");   // the blind edition's check, with its count
  if (code === "blind_unread") return t("Not sent: the blind edition's text could not be read");   // nothing read is never taken for clean
  const info = errorInfo(code);                                                     // the panel's reasons (name_missing, renderer_missing ...)
  return info.msg === errorInfo("unexpected").msg && code !== "unexpected" ? t("Did not work") : info.msg;   // a known one in words, else plainly (errorInfo makes a new object each time: compare the words)
}
function runError(code) {                                                           // why a run stopped, in words, and the one fix
  const E = {
    no_files: { short: t("No file to read"), msg: t("None of these files can be read. Use PDF, Word, PowerPoint, pictures or text.") },
    agent_unavailable: { short: t("No AI agent"), msg: t("The AI agent is off, so the files could not be read."), fix: t("Turn on the agent"), go: () => act("/api/v1/settings", { agent: "on" }) },
    no_roles: { short: t("No job found"), msg: t("No job you held was found in these files. Add an old resume or notes about your work.") },
  };
  return E[code] || { short: t("Stopped"), msg: errorInfo("unexpected").msg };       // anything else: the general words
}

// ---------------------------------------------------------------- the view: files in, the progress, documents out

const RUN_STEPS = { collect: "Find the files", read: "Read the files", keep: "Sort the career facts", contact: "Find the name and contact", analyze: "Read the posting", answers: "Answer the questions",  // a run's steps, in the person's words
  write: "Write the resume", english: "Make the English edition", figures: "Draw the figures", typeset: "Make the PDFs", interview: "Write interview scripts", export: "Save to the Desktop" };
function viewMake(host) {                                                           // the chain from your files to your documents, then the three columns
  const r = task("autopilot"), runs = (S.runs || []).filter((x) => x.state === "done");  // the run, the ones that finished
  const done = runs.length ? resultCard(runs[0]) : madeCard();                      // the third column's first card, made first:
  const fixing = !!(done && done.querySelector && done.querySelector(".fixform"));    // its form to finish the PDFs is the main key then
  fill(host, heroCard(), chainCard(), r.state === "running" ? runBand(r) : null, activeStrip(), h("div", { class: "flow" },   // a run going: in sight under the chain
    // each column: its head, then its cards stacked at their own height (the heads share a row, so the first cards start on one line)
    h("div", { class: "flow-col" }, colHead(1, t("Add your sources"), t("Nothing to type: the files are the input")), h("div", { class: "flow-cards" }, inCard(r.state === "running", !fixing), materialsCard())),
    // the run's card stands only while there is a run to show (an empty "waiting" card was one more block of words)
    h("div", { class: "flow-col" }, colHead(2, t("Grounded writing"), t("Facts from your files, and sentences from those facts only")), h("div", { class: "flow-cards" }, agentPanel(),
      r.state === "running" || r.state === "error" || (r.steps || []).length ? runPanel(r) : null)),
    h("div", { class: "flow-col" }, colHead(3, t("Finished documents"), t("Each sentence cites its source; the PDFs go to your Desktop")),
      h("div", { class: "flow-cards" }, done, runs.length > 1 ? olderRuns(runs.slice(1, 5)) : null))));
}
function heroCard() {                                                               // the front door: the resume's own head, the name on the band and where things stand beside it
  const d = S.details || {}, jobs = S.jobs || [];                                   // the person, the applications
  const open = jobs.filter((j) => j.stage !== "result");                            // still going
  const next = open.find((j) => j.stage === "interview" && j.next) || open.find((j) => j.next);   // the next date the person wrote down, an interview's first
  const today = S.today || "";
  const ahead = open.flatMap((j) => (j.rounds || []).filter((r) => String(r.at).slice(0, 10) >= today).map((r) => ({ j, r })))   // the interview rounds ahead,
    .sort((a, b) => String(a.r.at).localeCompare(String(b.r.at))).slice(0, 3);     // the nearest first: the morning's agenda
  const made = editionsMade().sort((a, b) => b.at.localeCompare(a.at))[0];          // the newest edition with PDFs
  const goJob = (j, tab) => { S.job = j.id; UI.jobTab = tab; act("/api/v1/jobs/select", { job: j.id }); go("jobs"); };   // that application, on its tab
  return h("section", { class: "rhead", "aria-label": t("Where things stand") },
    h("div", { class: "rhead-name" },
      S.photo && S.photo.on && S.photo.at ? h("img", { class: "rhead-photo", src: `/api/v1/photo?w=240&v=${S.photo.at}`, alt: "" }) : null,   // the resume's own photo, as its head prints it
      d.name ? h("div", { class: "n" }, d.name, d.name_en ? h("small", { text: d.name_en }) : null)
        : h("div", { class: "n none" }, h("button", { class: "linkish", type: "button", onclick: () => {   // no name yet: where to write it, never the app's own name in its place
          UI.editDetails = true; go("profile"); setTimeout(() => { const f = document.querySelector('[data-key="d-name"]'); if (f) f.focus(); }, 80); }, text: t("Add your name") })),
      d.tagline ? h("div", { class: "tagline", text: d.tagline }) : null),
    h("div", { class: "rhead-facts" },
      h("b", { text: t("Applications") }),
      jobs.length ? stageBar(jobs, { compact: true }) : h("span", { text: t("None yet") }),   // every application by stage, its words and numbers beside it
      ahead.length || next ? h("b", { text: t("Next") }) : null,
      ahead.length ? h("span", { class: "agenda" }, ahead.map(({ j, r }) => h("button", { class: "next", type: "button", onclick: () => goJob(j, "progress"),   // each round ahead opens its application
        text: `${whenWords(r.at)} ${jobName(j)}, ${t(ROUND_KIND[r.kind] || "Other round")}` })))
      : next ? h("span", {}, linksIn(next.next).length                              // the next step's links open where they stand; its company opens the application
          ? h("span", { class: "next-line" }, h("button", { class: "next", type: "button", onclick: () => goJob(next, next.stage === "interview" ? "interview" : "progress"),
              text: jobName(next) }), ", ", linked(next.next))
          : h("button", { class: "next", type: "button", onclick: () => goJob(next, next.stage === "interview" ? "interview" : "progress"),
              text: `${jobName(next)}, ${next.next}` }), untilWords(next) ? h("span", { class: "until", "data-until-job": next.id, text: untilWords(next) })
        : isPast(next) ? h("button", { class: "until past", type: "button", onclick: () => goJob(next, "progress"), text: t("Passed, write the result") }) : null) : null,   // how long until it, kept current (untilWords)
      made ? h("b", { text: t("Latest documents") }) : null,
      made ? h("span", {}, `${made.name}, ${made.lang === "en" ? t("English") : t("Korean")}, `, h("span", { class: "nowrap", text: made.at })) : null));   // its day and time never broken
}
function isPast(j) {                                                                // the interview's day is behind us
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(((j && (j.days || j.dates)) || {}).interview || "");   // a day left from a move taken back is not one
  if (!m) return false;
  const now = new Date();
  return new Date(+m[1], +m[2] - 1, +m[3]) < new Date(now.getFullYear(), now.getMonth(), now.getDate());
}
function untilWords(j) {                                                            // how long until an application's interview, or "" when none is ahead
  const d = ((j && (j.days || j.dates)) || {}).interview || "";                     // the interview's day, as the board counts it (tracker.stage_days)
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(d);
  if (!m) return "";
  const now = new Date(), day = new Date(+m[1], +m[2] - 1, +m[3]);                  // its day, and today
  const days = Math.round((day - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);   // by the calendar
  if (days < 0) return "";                                                          // passed
  const next = String(j.next || ""), md = new RegExp(`(?:^|\\D)0?${+m[2]}[-./]0?${+m[3]}(?!\\d)`);   // the next step written for that very day
  const tm = md.test(next) ? /(\d{1,2}):(\d{2})/.exec(next.slice(next.search(md))) : null;   // its hour, when written with the day
  if (tm && days <= 1) {                                                            // today or tomorrow, at an hour: the hours left
    const left = new Date(+m[1], +m[2] - 1, +m[3], +tm[1], +tm[2]) - now;
    if (left <= 0) return "";
    const hours = Math.floor(left / 3600000), mins = Math.floor((left % 3600000) / 60000);
    return hours ? t("{h}h {m}m left", { h: hours, m: mins }) : t("{m}m left", { m: mins });
  }
  return days === 0 ? t("Today") : t("D-{n}", { n: days });                         // the days left
}
setInterval(() => {                                                                 // a run's clock moves on without a redraw
  for (const el of document.querySelectorAll("[data-since]")) {
    const w = clock(Date.now() / 1000 - Number(el.dataset.since));                 // counted from the run's start
    if (el.textContent !== w) el.textContent = w;
  }
}, 1000);
setInterval(() => {                                                                 // the time left moves on without a redraw
  for (const el of document.querySelectorAll("[data-until-job]")) {
    const w = untilWords(((S && S.jobs) || []).find((x) => x.id === el.dataset.untilJob));
    if (el.textContent !== w) el.textContent = w;
  }
}, 30000);
const STAGE_ORDER = { interview: 0, submitted: 1, preparing: 2 };                  // what needs the person first
function activeStrip() {                                                            // the applications still going, as cards: stage, company, role, next step
  const list = (S.jobs || []).filter((j) => j.stage !== "result").sort((a, b) => (STAGE_ORDER[a.stage] ?? 3) - (STAGE_ORDER[b.stage] ?? 3) || String(b.created || "").localeCompare(String(a.created || ""))).slice(0, 12);   // every one still going (a dozen at most), as dense cards
  if (!list.length) return null;                                                    // nothing going: no strip
  const goJob = (j, tab) => { S.job = j.id; UI.jobTab = tab; act("/api/v1/jobs/select", { job: j.id }); go("jobs"); };
  return h("section", { class: "active", "aria-label": t("Applications in progress") },
    h("div", { class: "active-h" }, h("h2", {}, t("Applications in progress"), h("span", { class: "chip count", text: String(list.length) })), h("button", { class: "btn ghost sm", type: "button", onclick: () => { UI.jobsMode = "board"; go("jobs"); } }, icon("columns"), t("See the board"))),
    h("div", { class: "active-row" + (list.length > 1 ? " many" : "") }, list.map((j) => h("article", { class: "card active-card", "data-stage": j.stage },   // square notes, as many as fit a row (skin.css); on a phone one row that slides
      h("div", { class: "ac-name" }, mono(j.company || j.id, "", j.stage), h("div", {}, h("b", { class: "ac-co", text: j.company || j.id }), h("span", { class: "ac-role", text: j.role || "" }))),
      j.next ? h("p", { class: "ac-next" }, linked(j.next)) : null,                    // its next step, when one is written, its links live
      stageTrack(j),                                                                   // where it stands, across the card's foot: every card's at one height
      h("div", { class: "ac-keys" },
        h("button", { class: "btn sm", type: "button", onclick: () => goJob(j, "docs") }, icon("file"), t("Docs")),   // the short word: a note's two keys and its fit share one line
        h("button", { class: "btn sm", type: "button", onclick: () => goJob(j, "interview") }, icon("chat"), t("Interview")),
        (j.fit && j.fit.score) ? h("span", { class: "ac-fit", title: t("Fit {n}", { n: j.fit.score }) }, h("b", { text: String(j.fit.score) }), h("small", { text: t("Fit") })) : null)))));   // its fit, across from its keys
}
const TRACK = ["preparing", "submitted", "interview", "result"];                    // an application's way, in order
function stageTrack(j) {                                                            // the stage as four steps across a card: the ones passed, the one it is at, the rest
  const at = Math.max(0, TRACK.indexOf(j.stage));                                   // where it is
  const day = shortDay((j.days || j.dates || {})[j.stage]);                         // the day it got there, as 11-09
  return h("div", { class: "ac-track", role: "img", "aria-label": t("Stage: {s}", { s: t(STAGE[j.stage] || "Preparing") }) },
    h("span", { class: "ac-steps", "aria-hidden": "true" }, TRACK.map((st, i) => h("i", { class: i < at ? "done" : i === at ? "now" : null }))),
    h("span", { class: "ac-stage", "aria-hidden": "true" }, t(STAGE[j.stage] || "Preparing"), day ? h("small", { text: day }) : null));
}
function editionsMade() {                                                           // every edition with PDFs: the jobs, the named editions and the general one
  const all = [...(S.jobs || []).map((j) => ({ id: j.id, name: [j.company, j.role].filter(Boolean).join(", ") || j.id, builds: j.builds })),
    ...(S.editions || []).map((e) => ({ id: e.id, name: e.name, builds: e.builds })),
    ...(S.general ? [{ id: GENERAL, name: t("General edition"), builds: S.general.builds }] : [])];
  return all.flatMap((e) => Object.entries(e.builds || {}).map(([lang, b]) => ({ ...e, lang, at: b.at || "",   // one row per language made
    n: ["r", "d", "c"].filter((k) => ((b.previews || {})[k] || 0) > 0).length })))                       // its resume, deck and letter, when each has pages
    .filter((x) => x.n);                                                            // only what has a PDF
}
function bandEdition() {                                                            // the edition the third column is about: the last run's, else the one in view
  const run = (S.runs || []).find((x) => x.state === "done");                       // the newest finished run (newest first)
  return run ? (run.job === GENERAL ? "" : run.job) : jobId() || "";                // "" is the general edition
}
function bandModel(jid) {                                                           // the resume model of that edition, in the document's language
  if (jid === (jobId() || "")) return resumeModel();                                // the one in view: the canvas's own model
  const lang = docLang(), key = resumeKey(lang, UI.theme, jid);                     // its cache key, beside the canvas's
  if (!UI.docs[key]) getDoc(key, `/api/v1/documents/resume?lang=${lang}&theme=${UI.theme}` + (jid ? `&job=${enc(jid)}` : ""));   // fetched once, drawn when it lands
  return UI.docs[key] || null;                                                      // nothing yet while it loads
}
function chainCard() {                                                              // the evidence's way from your files to your documents: each step's count and what it is made of
  const mats = (S.materials || []).filter((m) => !m.removed);                       // the sources added
  const writing = task("autopilot").state === "running";                            // a run is writing: its counts are not final
  const kept = (S.facts && S.facts.counts && S.facts.counts.kept) || 0;             // the facts kept, each with its quote
  const kinds = {};                                                                 // the kept facts by kind (the rows come from /api/v1/facts, views.js)
  for (const r of factRows()) if (r.status === "accepted") { const k = (r.edit && r.edit.kind) || r.kind; kinds[k] = (kinds[k] || 0) + 1; }   // the kind as the person set it, as Profile counts it
  const jid = bandEdition(), m = bandModel(jid), c = (m && m.counts) || {};         // the sentences of the edition the result is about
  const made = editionsMade();                                                      // every edition with PDFs, a row per language
  const per = { r: 0, d: 0, c: 0 }, langs = { ko: 0, en: 0 };                       // the documents by kind and the editions by language
  for (const x of made) {
    const pv = ((x.builds || {})[x.lang] || {}).previews || {};                     // what that edition printed
    for (const k of ["r", "d", "c"]) if ((pv[k] || 0) > 0) per[k]++;
    langs[x.lang === "en" ? "en" : "ko"]++;
  }
  const docs = per.r + per.d + per.c;                                               // the PDFs made so far
  const open = () => { const want = jid || GENERAL; if (S.job !== want) { S.job = want; act("/api/v1/jobs/select", { job: want }); } go("documents"); };   // that edition, on its canvas
  const step = (kind, ic, n, label, body, where, bad, of) => h("button", { class: "pipe-step" + (n > 0 ? " has" : "") + (bad ? " bad" : ""), "data-kind": kind, type: "button",
    onclick: () => (typeof where === "function" ? where() : go(where)) },
    h("span", { class: "ps-head" }, h("span", { class: "ps-icon", "aria-hidden": "true" }, icon(ic)),
      h("span", { class: "ps-label" }, label, of ? h("small", { class: "ps-of", text: of }) : null), h("b", { class: "ps-n", text: String(n) })),   // what is counted, and of which edition when it is one
    body);
  const bandName = !jid || jid === GENERAL ? t("General edition")                   // the sentences counted are this edition's: said, as the count changes with it
    : ((S.editions || []).find((e) => e.id === jid) || {}).name || jobNameOf(jid, t("General edition"));   // a named edition by its name, a job by its company
  const top = Object.entries(kinds).filter(([k]) => KIND[k] && KIND[k] !== "Other").sort((a, b) => b[1] - a[1]);   // the kinds with a name, the most first: split as Profile splits them
  const rest = Object.values(kinds).reduce((s, v) => s + v, 0) - top.slice(0, 5).reduce((s, [, v]) => s + v, 0);   // every other fact, the unnamed kinds with them: one "Other"
  return h("section", { class: "card chain pipe", "aria-label": t("From your sources to your documents") },
    step("sources", "folder", mats.length, tn(mats.length, "Source", "Sources"),   // each file as long as the facts it gave
      mats.length ? segBar([...mats.slice(0, 4).map((x, i) => ({ n: x.facts || 0, words: sameName(mats, i), color: `color-mix(in srgb, var(--blue-bar) ${[100, 70, 48, 32][i]}%, var(--surface))` })),
        ...(mats.length > 4 ? [{ n: mats.slice(4).reduce((s, x) => s + (x.facts || 0), 0), words: t("and {n} more", { n: mats.length - 4 }), color: "var(--ink-3)" }] : [])],
        { label: t("Facts by source"), id: "chain-files", compact: true, unit: (n) => tn(n, "{n} fact", "{n} facts") }) : h("p", { class: "ps-none", text: t("Drop your files below.") }), "profile"),   // a file's number is its facts: said
    step("facts", "check", kept, tn(kept, "Fact", "Facts"),
      top.length || rest ? segBar([...top.slice(0, 5).map(([k, v]) => ({ n: v, words: t(KIND[k] || "Other"), color: KIND_COLOR[k] || "var(--ink-3)" })),
        ...(rest ? [{ n: rest, words: t("Other"), color: "var(--ink-3)" }] : [])], { label: t("Facts by kind"), id: "chain-kinds", compact: true })
        : h("p", { class: "ps-none", text: t("Kept facts show here by kind.") }), "profile"),
    step("sentences", "edit", c.sentences || 0, tn(c.sentences || 0, "Sentence", "Sentences"),
      // while a run writes, a sentence without evidence yet is one still being checked: grey, not the red of a stopped one
      c.sentences ? segBar([{ n: c.sentences - (c.unsupported || 0), words: t("With evidence"), color: "var(--violet-bar)" }, { n: c.unsupported || 0, words: t("Without evidence"), color: writing ? "var(--ink-3)" : "var(--red-bar)" }],
        { label: t("Sentences"), id: "chain-ev", compact: true }) : h("p", { class: "ps-none", text: t("Each sentence cites its facts.") }), open, c.unsupported > 0 && !writing, bandName),
    step("documents", "file", docs, tn(docs, "Document", "Documents"),
      docs ? h("div", { class: "ps-docs" }, segBar([["r", t("Resume"), 100], ["d", t("Portfolio deck"), 66], ["c", t("Cover letter"), 40]].map(([k, w, pc]) =>   // the documents by kind
        ({ n: per[k], words: w, color: `color-mix(in srgb, var(--aqua-bar) ${pc}%, var(--surface))` })), { label: t("Documents"), id: "chain-docs", compact: true }),
        h("span", { class: "ps-langs", text: t("{n} editions: Korean {k}, English {e}", { n: langs.ko + langs.en, k: langs.ko, e: langs.en }) })) : h("p", { class: "ps-none", text: t("The PDFs show here.") }), "documents"));
}
function sameName(mats, i) {                                                        // a file's name, told apart from another file of the same name by its number
  const name = mats[i].name, same = mats.filter((x) => x.name === name);
  return same.length > 1 ? `${name} (${same.indexOf(mats[i]) + 1})` : name;         // notes.txt (1), notes.txt (2): two files, not one counted twice
}
function madeCard() {                                                               // with no run of this session: the documents made so far, newest first
  const all = editionsMade(), rows = all.sort((a, b) => b.at.localeCompare(a.at)).slice(0, 7);  // the latest editions with PDFs: as many as sit beside the other columns' first cards
  if (!rows.length) return emptyOut();                                              // before the first run: what will come out
  const open = async (id) => { await act("/api/v1/jobs/select", { job: id }); go("documents"); };   // that edition, in Documents
  return h("section", { class: "card", "aria-label": t("Your documents") },
    h("h2", {}, t("Editions made"), h("span", { class: "n", text: String(all.length) })),
    h("ul", { class: "matlist made" }, rows.map((x) => h("li", {},
      h("button", { class: "linkish nm", type: "button", onclick: () => open(x.id), text: x.name }),
      h("span", { class: "lang", text: x.lang === "en" ? t("English") : t("Korean") }),
      h("span", { class: "hint", text: x.at })))),
    all.length > rows.length ? h("button", { class: "btn ghost sm more", type: "button", onclick: () => { UI.libGroup = "made"; UI.libQuery = ""; go("library"); } },   // the rest, where every made file is listed
      t("All {n} in the Library", { n: all.length })) : null);
}
function colHead(n, title, sub) {                                                   // a column's number, name and one line
  return h("div", { class: "colhead", title: sub || null }, h("div", {}, h("h2", { text: title })));   // its line on hover; its step's colour (app.css)
}
function inCard(running, lead = true) {                                             // the place to put things in (lead: its key is the view's main one)
  const sending = UI.sending;                                                       // files on their way to the server
  const zone = h("div", { class: "drop ai", role: "group", "aria-label": t("Add files or folders") },   // the files the agent reads: the rainbow rim
    icon("upload", 30), h("strong", { text: sending ? t("Sending {done} of {total} files…", sending) : t("Drop files or folders here") }),
    h("span", { class: "hint", text: t("Old resumes, portfolios, notes about your work, pictures of pages, a posting's link") }),
    h("div", { class: "drop-keys" },
      h("button", { class: "btn" + (lead ? " primary" : ""), disabled: !!sending || null, onclick: () => $("filepick").click() }, icon("file"), t("Choose files")),
      h("button", { class: "btn", disabled: !!sending || null, onclick: () => $("folderpick").click() }, icon("folder"), t("Choose a folder"))));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });   // a file held over it
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));          // moved away
  zone.addEventListener("drop", async (e) => { e.preventDefault(); zone.classList.remove("over"); makeFrom({ files: await droppedFiles(e.dataTransfer) }); });  // dropped
  const sendPaths = () => {                                                         // the paths in the box, one a line
    const lines = String(UI.typed["mk-paths"] || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    if (lines.length) makeFrom({ paths: lines });                                    // a run from them
  };
  const paths = field("mk-paths", t("Or paste the path of a folder or a file"), sendPaths, (text) => {  // a pasted path starts at once
    const lines = text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);         // the pasted lines
    if (lines.length && lines.every((x) => PATHLIKE.test(x))) { UI.typed["mk-paths"] = lines.join("\n"); sendPaths(); return true; }  // every line is a path
    return false;                                                                   // words: typed into the box as usual
  }, false, true);                                                                  // the files the agent reads: the rainbow rim
  const career = S.facts.counts.kept > 0;                                           // a career is kept: a posting alone can be tailored
  const sendPosting = () => { const p = String(UI.typed["mk-posting"] || "").trim(); if (!p) return; if (career) makeFrom({ posting: p }); else toast(t("Kept. It is used with the next files you add.")); };
  // one line to paste into, not a box to type in: a link starts at once, pasted text keeps its lines
  const posting = field("mk-posting", t("Paste a posting's link or text (optional)"), sendPosting, (text) => {   // a pasted link starts at once
    if (career && /^https?:\/\/\S+$/.test(text.trim())) { UI.typed["mk-posting"] = text.trim(); sendPosting(); return true; }
    return false;                                                                   // text: the person sends it when it is all there
  });
  const pathOpen = UI.pathOpen || !!String(UI.typed["mk-paths"] || "").trim();      // the path box, once asked for or while it holds words
  const pathKey = h("button", { class: "btn sm quiet mk-pathkey", type: "button", "aria-expanded": "false",   // a key that opens it: most people drop files
    onclick: () => { UI.pathOpen = true; render(); requestAnimationFrame(() => { const b = document.querySelector('[data-key="mk-paths"]'); if (b) b.focus(); }); } }, icon("folder"), t("Paste a path instead"));
  return h("section", { class: "card make-in", "aria-label": t("Add files or folders") }, zone,
    pathOpen ? [h("label", { class: "mk-label", text: t("Path") }), paths] : pathKey,
    posting,
    h("div", { class: "sentrow" }, sentLine(agentOn(), agentOn() ? t("The text of your files and the posting go to your AI agent.") : t("With no agent on, only an Offerowl profile file is read."))));
}
async function seeExample() {                                                       // the fictional person, read and kept, then their resume
  const ex = await act("/api/v1/example", { lang: LANG });                          // read as a profile file: no agent
  if (!ex) return;
  for (let i = 0; i < 120; i++) {                                                   // a profile reads in a moment
    try { S = await api("/api/v1/state"); } catch (_) { return; }                   // the state now
    if (task("ingest").state !== "running") break;                                  // read
    await new Promise((ok) => setTimeout(ok, 250));                                 // a quarter of a second
  }
  if (S.facts.counts.to_confirm) await act("/api/v1/facts/keep-all", { material: ex.material && ex.material.id });   // the example's facts kept, never the person's own still to confirm; one undo takes them back
  UI.doc = "resume"; UI.mode = "live"; go("documents");                             // its resume on the canvas
}
function field(key, placeholder, send, onPaste, tall, ai) {                         // a text box with its start key (ai: what it takes goes to the agent: the rainbow rim)
  const box = h("textarea", { "data-key": key, rows: tall ? 3 : 1, placeholder, "aria-label": placeholder,
    onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } },   // Enter sends, Shift+Enter is a new line
    onpaste: (e) => { const text = (e.clipboardData || window.clipboardData).getData("text"); if (onPaste && onPaste(text)) e.preventDefault(); } });  // some pastes start at once
  box.value = UI.typed[key] || "";                                                  // the words survive a redraw
  box.addEventListener("input", () => { UI.typed[key] = box.value; });              // kept as they are typed
  return h("div", { class: "sendbox" + (tall ? " tall" : "") + (ai ? " ai" : "") }, box, h("button", { class: "btn icon", type: "button", "aria-label": t("Start"), title: t("Start"), onclick: send }, icon("send")));
}
function materialsCard() {                                                          // the files already in, with what each gave
  const mats = (S.materials || []).filter((m) => !m.removed);                       // the files kept
  const c = S.facts.counts;                                                         // the facts
  return h("section", { class: "card", "aria-label": t("Files read") },
    h("h2", {}, t("Files added"), h("span", { class: "n", text: String(mats.length) })),
    mats.length ? h("ul", { class: "matlist" }, mats.slice(0, 8).map((m) => h("li", {}, h("span", { class: "nm", text: m.name, title: m.name }),
      m.state === "reading" ? pill("busy", t("Reading")) : h("span", { class: "chip" + (m.state === "done" ? " ok" : ""), text: materialState(m) }))),
      mats.length > 8 ? h("li", { class: "more" }, h("button", { class: "btn sm ghost", onclick: () => go("profile"), text: t("{n} more in your profile", { n: mats.length - 8 }) })) : null)
      : h("p", { class: "usage-none", text: t("Nothing read yet.") }),
    h("div", { class: "fill", "aria-hidden": "true" }),                                       // the foot line sits on the card's foot
    null);                                                                            // each file's row already says how many facts it gave
}
function runBand(r) {                                                               // a run going, under the chain where the eye is: its step and its stop (every step is on its card below)
  const steps = r.steps || [], at = steps.findIndex((s) => s.state === "running");  // the step in progress
  const n = at < 0 ? steps.filter((s) => s.state === "done").length : at;           // or how far it got
  const now = at < 0 ? t("Working") : t(RUN_STEPS[steps[at].id] || steps[at].id);  // in the person's words
  return h("div", { class: "band info run-band", role: "status" }, pill("busy", steps.length ? t("Step {n} of {m}: {step}", { n: Math.min(n + 1, steps.length), m: steps.length, step: now }) : now),
    h("span", { class: "grow" }),
    h("button", { class: "btn sm", type: "button", onclick: () => { const c = document.querySelector('[aria-label="' + t("Automatic run") + '"]'); if (c) c.scrollIntoView({ block: "center", behavior: "smooth" }); } }, t("See every step")),
    h("button", { class: "btn sm", type: "button", onclick: () => act("/api/v1/autopilot/stop", {}, t("It stops after the step in progress.")) }, icon("stop"), t("Stop")));
}
function runPanel(r) {                                                              // the run as it goes: its steps, its clock, its stop
  const steps = r.steps || [];                                                      // its steps
  const running = r.state === "running";                                            // in progress
  const done = steps.filter((s) => s.state === "done").length;                      // finished steps
  const err = r.state === "error" ? runError((r.error || {}).code) : null;          // why it stopped
  const halted = !running && (r.result || {}).stopped;                              // the person stopped it
  const lamp = running ? ["busy", t("Working")] : err ? ["bad", t("Stopped")] : halted ? ["warn", t("Stopped")] : steps.length ? ["ok", t("Done")] : ["off", t("Waiting")];
  const stop = running ? h("button", { class: "btn sm", onclick: () => act("/api/v1/autopilot/stop", {}, t("It stops after the step in progress.")) }, icon("stop"), t("Stop")) : null;
  const word = { running: t("Working"), done: t("Done"), failed: t("Did not work"), skipped: t("Skipped"), waiting: t("Waiting") };   // a step's state
  const unit = { collect: ["{n} file", "{n} files"], read: ["{n} fact", "{n} facts"], keep: ["{n} fact", "{n} facts"], contact: ["{n} filled", "{n} filled"],
    answers: ["{n} answer", "{n} answers"], interview: ["{n} script", "{n} scripts"], export: ["{n} file", "{n} files"] };   // what a step's number counts, one and many
  const detail = (s) => {                                                           // its number with what it counts, or why it stopped
    if (s.state === "failed") return s.detail ? problemWords(s.detail) || runError(s.detail).short : "";   // the reason
    if (s.state !== "done" || !/^\d+$/.test(s.detail || "")) return "";             // no number to show
    const n = Number(s.detail);                                                     // the number
    if (s.id === "contact" && !n) return "";                                        // nothing new to fill in: no zero to puzzle over
    return unit[s.id] ? tn(n, unit[s.id][0], unit[s.id][1]) : String(n);              // with its unit, "1 file" and "2 files"
  };
  const lampOf = { running: "busy", done: "ok", failed: "bad", skipped: "skip", waiting: "" };   // its lamp
  const pct = steps.length ? Math.round((100 * done) / steps.length) : 0;           // how far
  const head = h("div", { class: "src-top" }, h("span", { class: "src-name" }, icon("refresh"), h("span", { text: t("This run") })), pill(lamp[0], lamp[1]), stop);
  if (!steps.length && !err) return h("section", { class: "card conn", "aria-label": t("Automatic run") }, h("div", { class: "src", "data-state": lamp[0] }, head,
    h("p", { class: "usage-none", style: "margin-top:8px", text: t("Drop files and the run shows here, step by step.") })));
  const secs = running ? Date.now() / 1000 - (r.started || r.t || Date.now() / 1000) : (r.result || {}).seconds || 0;   // its time
  return h("section", { class: "card conn", "aria-label": t("Automatic run") }, h("div", { class: "src", "data-state": lamp[0] }, head,
    err ? h("div", { class: "band", role: "alert", style: "margin-top:8px" }, h("p", { text: err.msg }), err.fix ? h("button", { class: "btn small", onclick: err.go, text: err.fix }) : null) : null,
    h("div", { class: "meter", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct), "aria-label": t("Steps") }, h("i", { style: `width:${pct}%` })),
    h("ol", { class: "stepper" }, steps.map((s) => h("li", { class: "lit " + (lampOf[s.state] || ""), "data-step": s.id, "aria-current": s.state === "running" ? "step" : null },
      h("b", { text: t(RUN_STEPS[s.id] || s.id) }), h("span", { text: [word[s.state] || "", detail(s)].filter(Boolean).join(", ") })))),
    h("div", { class: "fill", "aria-hidden": "true" }),                                       // the figures sit on the card's foot
    h("div", { class: "usage" }, h("div", { class: "usage-top" },
      h("span", { class: "stat" }, h("b", { text: clock(secs), "data-since": running && r.started ? String(r.started) : null }), h("span", { class: "k", text: t("Time") })),
      h("span", { class: "stat" }, h("b", { text: `${done} / ${steps.length}` }), h("span", { class: "k", text: t("Steps") })),
      h("span", { class: "stat" }, h("b", { text: String(((r.result || {}).files || []).length) }), h("span", { class: "k", text: t("On the Desktop") }))),
      h("p", { class: "usage-sub" }, h("span", { text: running ? t("It finishes on its own; nothing to click") : halted ? t("Stopped. What was read waits in your profile.") : t("Ended") })))));
}
const DOC_KINDS = [["r", "resume.pdf", "Resume"], ["d", "deck.pdf", "Portfolio"], ["c", "cover.pdf", "Cover letter"]];   // the documents, in their columns
function docTiles(run) {                                                            // the documents the run made, a row per language and a column per document
  const general = run.job === GENERAL;                                           // no posting
  const j = general ? S.general : (S.jobs || []).find((x) => x.id === run.job);     // the edition it made
  const made = Array.isArray(run.langs) ? run.langs : ["ko", "en"];                // the editions this run made (an older record lists none: both)
  const rows = [];                                                                  // [{lang, cells: {kind: [href, picture, what, language]}}]
  for (const lang of made) {                                                        // each one made
    const b = j && j.builds && j.builds[lang];                                      // its record
    if (!b) continue;                                                               // not made
    const p = b.previews || {}, base = `/api/v1/jobs/${enc(run.job)}/files/${lang}/`, v = `?v=${enc(b.at || "")}`;   // its files, and a stamp so a new run's pictures show
    const L = lang === "ko" ? t("Korean") : t("English");                           // the language's name
    const cells = {};                                                               // its documents
    for (const [k, file, what] of DOC_KINDS) if (p[k]) cells[k] = [base + file, base + `preview/${k}-1.png` + ((b.hashes || {})[file] ? `?v=${enc(b.hashes[file])}` : v), t(what), L];   // the PDF's hash, when the build kept one: a page made again within a minute is new
    rows.push({ lang, cells });
  }
  const kinds = DOC_KINDS.map(([k]) => k).filter((k) => rows.some((r) => r.cells[k]));   // the columns: a document either language has
  return { rows, kinds };                                                           // Korean first
}
function resultCard(run) {                                                          // the last run: its documents and where the copies are
  const general = run.job === GENERAL;                                           // no posting
  const j = general ? S.general : (S.jobs || []).find((x) => x.id === run.job);     // the edition it made
  const name = general ? t("General edition") : j ? [j.company, j.role].filter(Boolean).join(", ") || j.id : run.job;  // its name
  const at = new Date((run.at || 0) * 1000);                                        // when it ended
  const grid = docTiles(run);                                                       // the PDFs, by language and document
  const tiles = grid.rows.length && grid.kinds.length;                              // anything to show
  const files = run.files || [];                                                    // the copies on the Desktop
  const probs = (run.problems || []).filter((p) => p.step !== "export" || ["checks_failed", "changed", "copy_unreadable", "answers_need_attention", "blind_unread"].includes(p.why) || /^blind_leak:\d+$/.test(p.why) || refusedWords(p.why));   // what went wrong; the copying only when it was refused, a Word or PowerPoint file too
  const det = S.details || {};                                                      // what "Your details" holds now
  const asked = probs.map((p) => p.why).filter((w) => w === "name_missing" || w === "email_missing");   // what the run said it lacked: the first it met
  const needs = asked.length ? ["name_missing", "email_missing"].filter((k) => asked.includes(k) || !String(det[k.replace("_missing", "")] || "").trim()) : [];   // and the other one when it is empty too, so one fix is enough
  const fix = needs.length && run === (S.runs || []).filter((x) => x.state === "done")[0] ? h("form", { class: "fixform", onsubmit: async (e) => {   // the missing fields, then the PDFs again
    e.preventDefault();
    const fields = {}; for (const k of needs) { const box = e.target.querySelector(`[data-key="mk-fix-${k}"]`); fields[k.replace("_missing", "")] = String(box ? box.value : UI.typed["mk-fix-" + k] || "").trim(); }   // what the boxes show, a value filled in from the profile included
    if (Object.values(fields).some((v) => !v)) { toast(t("Fill in both.")); return; }
    await act("/api/v1/details", { fields }); forget("mk-fix-");
    await act("/api/v1/autopilot", { again: run.job, theme: UI.theme, max_pages: UI.maxPages }, t("Making the PDFs again."), "info");   // started, not done
  } },
    h("p", { class: "hint", style: "grid-column:1/-1", text: t("Your files do not give these. Fill them in and the PDFs are made again.") }),
    needs.includes("name_missing") ? h("label", { class: "field" }, h("span", { text: t("Your name") }), h("input", { "data-key": "mk-fix-name_missing", value: det.name || "", autocomplete: "name",
      oninput: (e) => { UI.typed["mk-fix-name_missing"] = e.target.value; } })) : null,
    needs.includes("email_missing") ? h("label", { class: "field" }, h("span", { text: t("Email") }), h("input", { "data-key": "mk-fix-email_missing", type: "email", value: det.email || "", autocomplete: "email",
      oninput: (e) => { UI.typed["mk-fix-email_missing"] = e.target.value; } })) : null,
    h("button", { class: "btn primary", type: "submit" }, icon("refresh"), t("Make the PDFs again"))) : null;
  const ivDone = !general && (run.problems || []).every((p) => p.step !== "interview");   // the scripts were written
  return h("section", { class: "card", "aria-label": t("Your documents") },
    h("h2", {}, t("Made"), h("span", { class: "n", text: dayTime(at) })),   // 2026-11-10 04:37, as every day and time on the panel
    h("p", { class: "jobline", text: name, title: name }),                          // which edition: a job's name, or the general one
    fix,
    tiles ? h("div", { class: "tiles matrix", style: `--cols:${grid.kinds.length}` },   // rows by language, columns by document: each lines up with its pair
      grid.rows.map((r) => grid.kinds.map((k) => { const c = r.cells[k]; if (!c) return h("span", { class: "tile gap", "aria-hidden": "true" });   // a document this language lacks keeps its place
        const [href, pic, what, L] = c;
        return h("a", { class: "tile", href, target: "_blank", rel: "noopener", title: `${what} (${L})` },
          h("span", { class: "thumb" }, h("img", { src: pic, alt: "", loading: "lazy" })), h("b", { text: what }), h("span", { class: "sub", text: L })); })),
      ivDone ? h("button", { class: "tile tile-iv", onclick: () => { openApplication(run.job, "interview"); go("jobs"); } },   // a row of its own, across: the application's interview
        h("span", { class: "thumb" }, icon("chat", 22)), h("span", { class: "iv-words" }, h("b", { text: t("Interview scripts") }), h("span", { class: "sub", text: t("Search and practice") })), icon("open", 16)) : null)
      : h("p", { class: "usage-none", text: t("No PDF was made.") }),
    probs.length && !needs.length ? h("p", { class: "hint", text: t("What the run of {at} could not do:", { at: dayTime(at) }) }) : null,   // that run's, not now's: the agent may be on since
    probs.length && !needs.length ? h("ul", { class: "problist" }, probs.map((p) => h("li", { class: "lit bad", text: [t(RUN_STEPS[p.step] || p.step), p.lang ? (p.lang === "ko" ? t("Korean") : t("English")) : "", problemWords(p.why)].filter(Boolean).join(", ") }))) : null,
    h("div", { class: "fill", "aria-hidden": "true" }),                                       // the Desktop line and the keys sit on the card's foot
    h("div", { class: "usage-sub" }, h("span", { text: files.length ? tn(files.length, "{n} file saved to your Desktop", "{n} files saved to your Desktop") : t("Nothing was copied.") }),
      files.length ? h("button", { class: "btn sm", onclick: openDesktop }, icon("folder"), t("Open the Desktop folder")) : null),
    h("div", { class: "nextkeys" }, h("button", { class: "btn", onclick: () => { S.job = run.job; act("/api/v1/jobs/select", { job: run.job }); go("documents"); } },   // the edition it made, the general one too
      icon("file"), t("Read and change the documents"))));
}
function emptyOut() {                                                               // before the first run: what will come out
  const kept = (S.facts && S.facts.counts && S.facts.counts.kept) || 0;             // facts kept: the resume already reads in Documents
  if (kept) return h("section", { class: "card", "aria-label": t("Your documents") },   // the next step, not the example again
    h("h2", {}, t("Nothing made yet")),
    h("p", { class: "usage-none", text: t("Your resume already reads in Documents, each sentence with its evidence. Make the PDFs there once it reads right.") }),
    h("div", { class: "fill", "aria-hidden": "true" }),
    h("div", { class: "nextkeys" }, h("button", { class: "btn", type: "button", onclick: () => go("documents") }, icon("file"), t("Open the resume"))));
  return h("section", { class: "card", "aria-label": t("Your documents") },
    h("h2", {}, t("Nothing made yet")),
    h("p", { class: "usage-none", text: t("A resume and a portfolio in Korean and English; with a posting, a cover letter and interview scripts too.") }),
    h("div", { class: "fill", "aria-hidden": "true" }),                                       // the key sits on the card's foot
    h("div", { class: "nextkeys" }, h("button", { class: "btn", "data-act": "example", disabled: task("autopilot").state === "running" || null, onclick: seeExample }, icon("person"), t("Try an example"))));   // what comes out, before any file of one's own; not while a run reads the person's own
}
function olderRuns(runs) {                                                          // the runs before, one line each
  return h("section", { class: "card", "aria-label": t("Earlier runs") },
    h("h2", {}, t("Earlier runs")),
    h("ul", { class: "matlist" }, runs.map((x) => {
      const j = x.job === GENERAL ? null : (S.jobs || []).find((y) => y.id === x.job);   // its job
      return h("li", {}, h("span", { class: "nm", text: x.job === GENERAL ? t("General edition") : j ? [j.company, j.role].filter(Boolean).join(", ") : x.job }),
        h("span", { class: "chip", text: tn((x.files || []).length, "{n} file", "{n} files") }));
    })));
}
