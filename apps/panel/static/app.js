// Offerowl's panel, part 6: the bar (the wordmark, the views, the agent's lamp, the run's lamp, undo and the settings
// menu), the agent's control panel (shown on the make view and from the bar's lamp), the drawing of the panes, the
// keyboard and the start. A control card holds a name, a lit pill and a switch, then name and value pairs and its
// figures. A pane is drawn again only when what it shows changed, so typing, focus
// and scrolling survive the state's polling.
"use strict";                                                                       // catches undeclared names and silent writes early

// ---------------------------------------------------------------- the bar

function drawBar(el) {                                                              // wordmark, views, job, lamps, undo, settings
  const jobs = S.jobs || [];                                                        // the jobs
  const eds = S.editions || [];                                                     // the named general editions
  const pickJob = (jobs.length || eds.length) && UI.view === "documents" ? h("label", { class: "jobpick" }, h("span", { class: "sr", text: t("Job") }),  // where a job matters
    h("select", { "aria-label": t("Job in view"), "data-key": "jobpick", onchange: (e) => act("/api/v1/jobs/select", { job: e.target.value }) },
      h("optgroup", { label: t("General editions") },                               // the documents with no posting, first
        h("option", { value: GENERAL, selected: (!job() && !named()) || null, text: t("General edition") }),
        eds.map((e) => h("option", { value: e.id, selected: e.id === S.job || null, text: e.name }))),   // each named one, by its name
      jobs.length ? h("optgroup", { label: t("Applications") },                     // then each application
        jobs.map((j) => h("option", { value: j.id, selected: j.id === S.job || null, "data-short": j.company && j.role ? j.company : null, text: [j.company, j.role].filter(Boolean).join(", ") || j.id }))) : null)) : null;   // closed, the bar shows the company: the role is in the list and in the page's own heading
  const undoText = S.undo ? undoLabel(S.undo) : "";                                 // what undo takes back
  const views = h("nav", { class: "views", "aria-label": t("Navigation") }, VIEWS.map(([k, w]) => {  // the views, as keys of one choice
    const n = viewCount(k);                                                         // a number that asks for attention
    return h("button", { "aria-current": UI.view === k ? "page" : null, onclick: () => go(k), "aria-label": n ? `${t(w)}, ${n[1]}` : t(w) },
      icon(VIEW_ICON[k] || "file"), h("span", { text: t(w) }), n ? h("span", { class: "chip count " + n[2], "aria-hidden": "true", text: String(n[0]) }) : null);
  }));
  fill(el,
    h("div", { class: "bar-in" },
      h("a", { class: "brand", href: "/", "aria-label": "offerowl", onclick: (e) => { e.preventDefault(); go("make"); } },
        h("img", { class: "logo-light", src: "/brand/logo-light.svg", alt: "" }), h("img", { class: "logo-dark", src: "/brand/logo-dark.svg", alt: "" })),
      S.version && S.version !== "0" ? h("span", { class: "brand-ver", title: t("Offerowl version {v}", { v: S.version }), text: "v" + S.version }) : null,   // the version, beside the wordmark
      views, pickJob, h("span", { class: "grow" }), h("span", { class: "saved", "aria-hidden": "true", text: t("Saved") }),
      runChip(), agentChip(),
      h("div", { class: "actions" },
        h("button", { class: "btn icon", id: "undo", disabled: !S.undo || null, title: S.undo ? t("Undo: {what}", { what: undoText }) : t("Nothing to undo."),
          "aria-label": S.undo ? t("Undo: {what}", { what: undoText }) : t("Nothing to undo."), onclick: undo }, icon("undo")),
        h("button", { class: "btn icon", id: "more", title: t("Settings"), "aria-label": t("Settings"), "aria-expanded": UI.menu ? "true" : "false", "aria-controls": "menu",
          onclick: () => { UI.menu = !UI.menu; UI.agentPop = false; render(); if (UI.menu) focusSheet("#menu"); } }, icon("gear")),
        UI.menu ? drawMenu() : null)),
    UI.offline ? h("div", { class: "bar-off" }, h("div", { class: "band", role: "alert" },   // the server is gone: said once, under the bar, whatever the view
      h("p", { text: t("Offerowl's server is not answering. What you change now is not saved.") }),
      h("button", { class: "btn small", type: "button", onclick: () => refresh() }, icon("refresh"), t("Connect again")))) : null);   // asks now, instead of waiting for the next poll
  fitBar(el.querySelector(".bar-in"));                                              // one row, or the views on a row of their own
  const note = document.getElementById("toast"); if (note && note.classList.contains("show")) placeToast(note);   // a note showing keeps its place in the bar drawn anew, and what it covers aside
}
function fitBar(bar) {                                                              // the bar on one row when it all fits; when not, the views go down whole
  if (!bar) return;                                                                 // and the wordmark, the lamps, undo and the settings keep the first row,
  bar.classList.remove("two", "tight", "tighter");                                  // never split off to the left of a second one. Measured as one row first,
  const oneRow = (els) => {                                                         // since the labels' widths depend on the language and the PC's own type
    const mids = els.filter((e) => e.offsetWidth).map((e) => e.offsetTop + e.offsetHeight / 2);   // each shown item's middle
    return !mids.length || Math.max(...mids) - Math.min(...mids) <= 10;             // items of one row share a middle (align-items: center)
  };
  if (PHONE.matches) {                                                              // a phone: the views have rows of their own; the wordmark, the version and
    const first = () => [...bar.children].filter((e) => !e.matches(".views, .jobpick, .grow"));   // the keys share the first. A window with a scroll bar
    if (!oneRow(first())) bar.classList.add("tight");                               // that takes room (Windows) has less than its width says: a smaller wordmark,
    if (!oneRow(first())) bar.classList.add("tighter");                             // then the version left to the settings' foot
    return;
  }
  if (!oneRow([...bar.children])) bar.classList.add("two");
}
const VIEW_ICON = { make: "layers", profile: "person", jobs: "case", documents: "file", insights: "chart", library: "folder" };   // each view's mark on the bar
function agentLamp() {                                                              // [lamp, words] of the agent's state
  // A local model is a server at an address: the state says "missing" while no address is set and "signed_out" while nothing
  // answers there (apps/api/agent.py, local_status), and neither is a thing to install or sign in to
  if (S.agent.backend === "openai-compat" && S.agent.state === "missing") return ["off", "No address"];
  if (S.agent.backend === "openai-compat" && S.agent.state === "signed_out") return ["warn", "Not answering"];
  return { ready: ["ok", "Ready"], signed_out: ["warn", "Not signed in"], missing: ["off", "Not installed"], off: ["off", "Off"], checking: ["busy", "Checking"] }[S.agent.state] || ["off", "Off"];
}
function agentChip() {                                                              // the agent's lamp in the bar; its control panel opens under it
  const a = S.agent, lamp = agentLamp();                                            // the card and its lamp
  const name = a.backend === "none" ? t("AI agent") : t(AGENT_NAME[a.backend] || a.backend);  // its name, in the page's language (a local model is named, the two CLIs are names)
  return h("div", { class: "barpop" },
    h("button", { class: "barchip", "aria-expanded": UI.agentPop ? "true" : "false", "aria-haspopup": "dialog", title: `${name}: ${t(lamp[1])}`, "aria-label": `${name}: ${t(lamp[1])}`,   // its name and state, said on the hover too: a narrow bar shows its lamp alone
      onclick: () => { UI.agentPop = !UI.agentPop; UI.menu = false; render(); if (UI.agentPop) focusSheet(".barpop .pop"); } }, h("span", { class: "barchip-i", "aria-hidden": "true" }, icon("agent")), h("span", { class: "lit " + lamp[0], "aria-hidden": "true" }), h("span", { class: "barchip-w", text: name })),
    UI.agentPop ? h("div", { class: "pop", role: "dialog", "aria-modal": "true", "aria-label": t("AI agent") }, agentPanel()) : null);
}
function runChip() {                                                                // the run's lamp in the bar, away from the make view
  const r = task("autopilot");                                                      // the run
  if (r.state !== "running" || UI.view === "make") return null;                     // only while it runs, and where its sheet is not in view
  const steps = r.steps || [], done = steps.filter((s) => s.state === "done").length;  // how far
  return h("button", { class: "barchip", onclick: () => go("make"), title: t("This run") },
    h("span", { class: "lit busy", "aria-hidden": "true" }), h("span", { class: "barchip-w", text: t("Making {done} / {total}", { done, total: steps.length || "…" }) }));
}
function viewCount(k) {                                                             // [number, words, chip colour] beside a view's name, or null
  const c = S.facts.counts, due = (S.due || []).length;                             // facts to confirm, reminders due
  if (k === "profile" && c.to_confirm) return [c.to_confirm, t("{n} to confirm", { n: c.to_confirm }), "warn"];
  if (k === "jobs" && due) return [due, t("{n} due", { n: due }), "pc"];
  return null;                                                                      // nothing to count
}
function pickTheme(c) {                                                             // the theme, as the menu and the setup guide pick it
  try { if (c === "auto") localStorage.removeItem("offerowl-theme"); else localStorage.setItem("offerowl-theme", c); } catch (_) { /* blocked */ }
  applyTheme(c); redrawAll();
}
function pickLanguage(k) { setLang(k); act("/api/v1/settings", { lang: LANG }); redrawAll(); }   // the language, kept in this browser and told to the server
function drawMenu() {                                                               // theme, language, the agent, the workspace's files
  const s = S.settings || {}, found = (S.agent && S.agent.found) || [];             // the settings and the CLIs this PC has
  const options = [["auto", "Find it automatically"], ["claude-code", "Claude Code"], ["codex", "Codex"], ["openai-compat", "Local model"], ["none", "No agent"]];  // the backends
  const themeNow = document.documentElement.dataset.themeChoice || "auto";          // the theme's choice
  const langNow = langPicked();                                                     // the language's choice
  const motionNow = document.documentElement.dataset.motionChoice || "on";          // the motion's choice
  const pickMotion = (m) => { try { localStorage.setItem("offerowl-motion", m); } catch (_) { /* blocked */ } applyMotion(m); redrawAll(); };
  return h("div", { class: "menu", id: "menu", role: "dialog", "aria-modal": "true", "aria-label": t("Settings") },
    h("button", { class: "item", type: "button", onclick: () => openSetup(0) }, icon("list"), t("Setup guide")),   // the four steps again (setup.js); a list of steps, not a tick a menu reads as "chosen"
    h("hr"),
    h("h3", {}, icon("sun"), t("Theme")),
    h("div", { class: "seg" }, [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(([k, w]) =>
      h("button", { type: "button", "data-key": "m-theme-" + k, "aria-pressed": themeNow === k ? "true" : "false", onclick: () => pickTheme(k), text: t(w) }))),   // found again by its key: three rows have an "Auto"
    h("h3", {}, icon("motion"), t("Motion")),
    h("div", { class: "seg", id: "motion-seg" }, [["auto", "Auto"], ["on", "On"], ["off", "Off"]].map(([k, w]) =>   // auto first, as the theme and the language; on by default
      h("button", { type: "button", "data-key": "m-motion-" + k, "aria-pressed": motionNow === k ? "true" : "false", onclick: () => pickMotion(k), text: t(w) }))),
    h("h3", {}, icon("globe"), t("Language")),
    h("div", { class: "seg" }, [["auto", "Auto"], ["ko", "한국어"], ["en", "English"]].map(([k, w]) =>
      h("button", { type: "button", "data-key": "m-lang-" + k, lang: k === "auto" ? null : k, "aria-pressed": langNow === k ? "true" : "false",
        onclick: () => pickLanguage(k), text: k === "auto" ? t(w) : w }))),
    h("h3", {}, icon("agent"), t("AI agent")),
    h("div", { class: "field" }, h("select", { "aria-label": t("AI agent"), "data-key": "m-backend", onchange: (e) => act("/api/v1/settings", { backend: e.target.value }) },
      options.map(([k, w]) => h("option", { value: k, selected: (s.backend || "auto") === k || null, text: t(w) + (found.includes(k) ? ", " + t("on this PC") : "") })))),
    s.backend === "openai-compat" ? [h("label", { class: "field" }, h("span", { text: t("Local server address") }), h("input", { "data-key": "m-url", value: s.llm_url || "", placeholder: "http://127.0.0.1:11434",
      onchange: (e) => act("/api/v1/settings", { llm_url: e.target.value }) })), h("label", { class: "field" }, h("span", { text: t("Model name") }), h("input", { "data-key": "m-model", value: s.llm_model || "",
        onchange: (e) => act("/api/v1/settings", { llm_model: e.target.value }) }))] : null,
    h("hr"),
    h("button", { class: "item", type: "button", onclick: async () => { const r = await act("/api/v1/open", { what: "workspace" }); if (r && !r.opened) toast(t("This PC has no file manager to open it with."), null, "warn"); } }, icon("folder"), t("Open the workspace folder")),
    h("a", { class: "item", href: "/api/v1/workspace/backup", download: "" }, icon("download"), t("Back up my files")),  // the browser saves it, in every way Offerowl runs
    h("label", { class: "item" }, icon("upload"), t("Restore a backup"), h("input", { type: "file", accept: ".zip", hidden: true, onchange: (e) => { const f = e.target.files[0]; e.target.value = ""; restoreBackup(f); } })),   // emptied: the same file can be picked again
    S.version && S.version !== "0" ? [h("hr"), h("p", { class: "menu-ver", text: t("Offerowl version {v}", { v: S.version }) })] : null);   // the version, also here: the bar's narrowest width has no room for it  // a label is the input's key
}
async function restoreBackup(file) {                                               // a backup in the workspace's place, once the person agrees
  if (!file) return;                                                                // nothing picked
  if (file.size > 500e6) { toast(t("This file is too large to be a backup."), null, "bad"); return; }   // over the server's limit (web.py MAX_BACKUP): said before it is sent
  if (!(await askFirst({ title: t("Restore this backup?"), ok: t("Restore"),         // nothing is sent without a yes
    text: t("Your files are replaced by the backup's. The ones you have now are not deleted: they stay in a folder beside your workspace, listed in the Library's trash.") }))) return;
  let r;                                                                            // the answer
  try {
    r = await postFile("/api/v1/workspace/restore", file);  // the raw file
  } catch (_) { toast(t("The backup could not be restored."), null, "bad"); return; }            // the server is gone: said, not silent
  const j = await r.json().catch(() => ({}));                                       // a refusal answers with its reason
  if (r.ok) {                                                                       // where the old files are, then the page reads the restored ones
    await askFirst({ title: t("Restored"), cancel: false, text: t("The files you had are in the folder {name}, beside your workspace. The Library's trash lists it, and can delete it once you no longer need it.", { name: j.kept }) });
    location.reload(); return;
  }
  toast(t({ not_a_backup: "This file is not an Offerowl backup.", busy: "Wait until the work in progress ends, then try again.", too_large: "This file is too large to be a backup." }[j.error] || "The backup could not be restored."), null, "bad");  // why, in words
}
function openAgentMenu() { UI.agentPop = true; UI.menu = false; render(); window.scrollTo({ top: 0 }); focusSheet(".barpop .pop"); }  // the agent's panel opens from the bar, the keyboard in it
async function undo() {                                                             // the bar's undo
  const r = await act("/api/v1/undo", {});                                          // the files back
  if (r) toast(r.undone ? t("Undone: {what}", { what: undoLabel(r.undone) }) : t("Nothing to undo."), null, r.undone ? "done" : "info");
}

// ---------------------------------------------------------------- the agent's control panel

function facts(pairs, one) {                                                        // name and value pairs, two to a row (one to a row for long values)
  return h("dl", { class: "facts" + (one ? " one" : "") }, pairs.filter(Boolean).map(([k, v, cls]) =>
    h("div", { class: "fact", title: `${k}: ${typeof v === "string" ? v : ""}` }, h("dt", { text: k }), h("dd", { class: cls || null }, v))));
}
function kilo(n) { return n >= 10000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : String(n || 0); }   // 26110 as 26.1k
function agentPanel() {                                                             // the agent: who it is, whether it answers, what it did today
  const a = S.agent, c = S.agent_calls || {}, lamp = agentLamp();                   // the card, the day's calls, its lamp
  const name = a.backend === "none" ? t("AI agent") : t(AGENT_NAME[a.backend] || a.backend);  // its name, in the page's language (a local model is named, the two CLIs are names)
  const on = a.backend !== "none" && a.state !== "off";                             // the switch
  const local = a.backend === "openai-compat";                                       // a server at an address, with no sign-in
  const key = a.state === "signed_out" && !local ? h("button", { class: "btn sm go", onclick: () => act("/api/v1/agent/login", {}), text: a.signing_in ? t("Signing in…") : t("Sign in") })
    : h("button", { class: "switch", role: "switch", "aria-checked": on ? "true" : "false", "aria-label": t("Use the agent"), onclick: () => act("/api/v1/settings", { agent: on ? "off" : "on" }) });
  const who = a.state === "ready" ? h("div", { class: "who-box" }, h("span", { class: "ava", "aria-hidden": "true", text: (a.email || name).trim().charAt(0).toUpperCase() }),
    h("span", { class: "mail", text: a.email || t("This PC's sign-in") }), h("span", { class: "how", text: [a.plan, a.backend === "codex" ? "Codex CLI" : a.backend === "openai-compat" ? t("Local model") : "Claude Code CLI"].filter(Boolean).join(", ") })) : null;
  const help = local && (a.state === "missing" || a.state === "signed_out") ? h("p", { class: "usage-none", style: "margin-top:8px",   // the address is the fix
      text: a.state === "missing" ? t("Set the local server's address in the settings menu.") : t("Nothing answers at the local server's address. Check it in the settings menu.") })
    : a.state === "missing" ? h("p", { class: "usage-none", style: "margin-top:8px" }, t("Reading your files needs an AI agent such as Claude Code or Codex."), " ",
    a.install ? h("a", { href: a.install, target: "_blank", rel: "noopener", text: t("How to get {name}", { name }) }) : null)   // the chosen agent's own page, as the state names it
    : a.state === "signed_out" && !local ? h("p", { class: "usage-none", style: "margin-top:8px",   // signed out: what signing in is for, and where the agent is chosen
      text: t("Offerowl writes with the agent you are signed in to on this PC: sign in once, and it reads your files and writes from them. The settings menu chooses which agent.") })
    : !on && a.state !== "signed_out" ? h("p", { class: "usage-none", style: "margin-top:8px", text: t("While it is off, only an Offerowl profile file is read. Turn it on to read your other files and write.") }) : null;   // what off means, in one line
  const sec = (v) => (v == null ? "–" : `${v} s`);                                  // an en dash where there is no figure yet
  const stats = a.state === "ready" ? h("div", { class: "usage" },
    h("div", { class: "usage-top" },
      h("span", { class: "stat" }, h("b", { text: String(c.calls || 0) }), h("span", { class: "k", text: t("Requests today") })),
      h("span", { class: "stat" }, h("b", { text: sec(c.median) }), h("span", { class: "k", text: t("Median response") })),
      h("span", { class: "stat" }, h("b", { text: sec(c.ttft_avg) }), h("span", { class: "k", text: t("Time to first token") })),
      h("span", { class: "stat" }, h("b", { text: c.tps_avg == null ? "–" : String(c.tps_avg) }), h("span", { class: "k", text: t("Tokens per second") }))),
    (c.bars || []).length ? h("div", { class: "ag-bars", "aria-hidden": "true" }, (() => { const max = Math.max(...c.bars.map((b) => b.sec || 0), 1);   // the day's calls: first token, then writing
      return c.bars.map((b) => h("i", { style: `height:${Math.max(8, (b.sec / max) * 100)}%`, title: `${b.sec} s` },
        b.ttft ? h("b", { style: `height:${Math.min(100, (b.ttft / b.sec) * 100)}%` }) : null)); })()) : null,
    h("p", { class: "usage-sub" },
      h("span", {}, t("In {i}, out {o} tokens", { i: kilo(c.tok_in), o: kilo(c.tok_out) })),
      c.cost != null ? h("b", { text: `$${Number(c.cost).toFixed(2)}` }) : h("span", { text: t("Only Offerowl's own requests") })),
    c.errors ? h("p", { class: "ag-err", text: t("{n} errors, last {code}", { n: c.errors, code: (c.last_error && c.last_error.code) || "" }) }) : null) : null;
  return h("section", { class: "card conn agentcard", "aria-label": t("AI agent") },
    h("div", { class: "src", "data-state": lamp[0] },
      h("div", { class: "src-top" }, h("span", { class: "src-name" }, icon("agent"), h("span", { text: name })), pill(lamp[0], t(lamp[1])), key),
      who, help,
      a.state === "ready" ? facts([[t("Model"), c.model || t("The agent's default")], [t("Effort"), c.effort || t("The agent's default")]]) : null,
      stats));
}
function clock(sec) { const s = Math.max(0, Math.round(sec)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }  // minutes:seconds
async function openDesktop() {                                                      // the Desktop folder in the file manager
  const r = await act("/api/v1/open", { what: "desktop" });                         // the server opens it
  if (r && !r.opened) toast(t("This PC has no file manager to open it with."), null, "warn");     // a server without one
}

// ---------------------------------------------------------------- drawing

function kitFramed() {                                                              // a kit's scripts (kit.js), its deck or its practice (interview.js) stand on the canvas: a redraw for nothing they show would cost the board its place
  return UI.view === "jobs" && !!document.querySelector("#canvas :is(.kit, .ivdeck, .ivprac)");
}
function kitFrameDocs() {                                                           // what the canvas reads from fetched documents while one is up: the job's fit, its board, and an opened material's preview
  const has = (k) => (UI.docs[k] ? 1 : 0);                                           // arrived or not: a key holds one answer for good
  const jid = (openJob() || {}).id;                                                 // the application drawn (with an edition in view, not S.job)
  return ["framed", has(`fit|${jid}|${rev()}`), has(`iv|${jid}|${docLang()}|${rev()}`), has(`ivv|${jid}|${LANG}|${rev()}`), has(`ivd|${jid}|${LANG}|${rev()}`), UI.matOpen ? UI.docsVer : 0];   // the scripts' and the deck's own data too
}
function paneKey(name) {                                                            // what a pane shows; it is drawn again only when this changes
  const look = [LANG, document.documentElement.dataset.theme, document.documentElement.dataset.themeChoice, UI.offline];   // the page's language and look
  const base = [...look, rev()];                                                    // shared by the panes that show the workspace
  if (name === "bar") return JSON.stringify([...base, UI.view, S.job, S.undo, UI.menu, UI.agentPop, S.settings, S.agent, S.agent_calls, (S.jobs || []).map((j) => [j.id, j.company, j.role]),
    S.facts.counts, S.due, task("autopilot").state, (task("autopilot").steps || []).map((s) => s.state).join()]);
  // the setup guide shows none of the workspace's history or the tasks' clocks, which change at every poll while a run goes:
  // a redraw then would close an open list and drop an address being typed
  if (name === "setup") return JSON.stringify([...look, UI.setup, S.agent, S.settings, S.engine, S.engine_needs, S.renderer, task("setup").state, task("setup").error, task("autopilot").state, (S.materials || []).length, langPicked()]);
  if (name === "insp") return JSON.stringify([...base, UI.view, UI.tab, UI.sel, UI.editing, UI.drawer, UI.docLang, UI.theme, S.settings, UI.maxPages, UI.cover, UI.typeset, S.job,
    UI.docsVer, S.engine, S.english, S.styles, task("regen:" + UI.sel),
    UI.doc, UI.mode, sentAway(), S.agent && S.agent.state]);                       // the cover tab showed the resume's evidence until another change came
  const framed = kitFramed();                                                       // a kit's page is in its frame
  return JSON.stringify([...base, UI.view, UI.doc, UI.mode, UI.view === "documents" ? "" : UI.sel, UI.editing, UI.docLang, UI.theme, S.settings && S.settings.form, S.settings && S.settings.deck_style, S.job, UI.filter, UI.factEdit, UI.factAdd, UI.editDetails, UI.jobPhone, UI.pathOpen, UI.adding, UI.jobsMode, UI.editDays, UI.tlPage, UI.dtPage, todayMarks(), UI.nextEdit, UI.jobTab, UI.ivPart, UI.ivWide, UI.roundEdit, UI.fitFilter, UI.lineOpen, UI.factQuery, UI.factKind, UI.factPage, UI.factOpen, UI.scriptOpen,
    UI.matOpen, UI.matSending, UI.libGroup, UI.libOwner, UI.libQuery, UI.libPage, (S.jobs || []).map((j) => (j.materials || []).map((m) => m.id).join()),
    (S.jobs || []).map((j) => [j.id, j.stage, j.result, j.next]),                     // a card moved on the board, or its next step changed: drawn at once   // a job's materials: one added or taken off, one opened, an upload going
    // the form's questions: removed, a new limit, an answer edited or checked again. These writes keep no undo step, so the
    // workspace's revision stays the same and the card kept showing the old list until something else changed
    (S.jobs || []).map((j) => (j.questions || []).map((q) => [q.id, q.text, q.limit, q.unit, q.answer, q.state, (q.issues || []).join(), q.at])),
    // with a kit's frame up, a document fetched for another view (Insights arrives three seconds after the page) and a window
    // dragged 40 px wider no longer count: each drew the canvas again, and the frame's page with it, emptying its search box
    framed ? kitFrameDocs() : UI.docsVer, S.materials, S.photo, S.engine, S.engine_needs, S.due, typeof Notification === "undefined" ? "" : Notification.permission, PHONE.matches,
    framed ? 0 : Math.round(($("canvas").clientWidth || 0) / 40), taskMarks(), S.runs, S.agent, S.agent_calls,
    UI.sending]);                                                                   // a run's clock moves in place (make.js data-since), not by a redraw
}
function drawPane(el, name, fn) {                                                   // one pane, kept when nothing changed
  const key = paneKey(name);                                                        // what it would show
  if (el._key === key) return;                                                      // the same: typing and focus stay
  if (UI.inplace && el.id === "canvas") return;
  if (UI.dragging && el.id === "canvas") return;                                    // a card is held on the board: a redraw would drop it from the hand                                     // a sentence is being typed on the page: drawn again when it ends
  if (UI.composing && el.contains(document.activeElement)) return;                  // a Korean syllable is being put together here: a new box would break it
  const focus = document.activeElement && el.contains(document.activeElement) ? keyOf(document.activeElement) : null;  // where the keyboard was
  const scroll = el.scrollTop;                                                      // where a scrolling pane was
  // the canvas scrolls with the page, and a resume's pages are laid out a frame after it is drawn: the same view drawn again
  // keeps its old height for that frame and the window's place, or a reader on the last page is thrown back to the top
  const same = el.id === "canvas" && el._at === `${UI.view}|${UI.doc}`;
  const winY = window.scrollY;                                                      // where the reader was
  if (same) el.style.minHeight = `${el.offsetHeight}px`;                            // held until the pages land
  fn(el);                                                                           // drawn
  if (window.comboDress) window.comboDress(el);                                     // its dropdowns dressed now (combo.js), so the keyboard can go back to one
  el._key = el.id === "canvas" && kitFramed() ? paneKey(name) : key;                // remembered; with a kit's frame just placed, as the key reads with the frame up, so the next poll finds nothing changed
  if (el.id === "canvas") el._at = `${UI.view}|${UI.doc}`;                          // what it shows, for the next draw
  afterDraw(el, name);                                                              // what is new in it moves, once (motion.js)
  el.scrollTop = scroll;                                                            // the pane stays where it was
  const back = focus ? restoreFocus(el, focus) : true;                              // the keyboard stays where it was
  if (same || !back) requestAnimationFrame(() => requestAnimationFrame(() => {      // once the pages drawn a frame later are there
    if (same) { el.style.minHeight = ""; if (Math.abs(window.scrollY - winY) > 1) window.scrollTo({ top: winY, behavior: "instant" }); }
    if (!back && !el.contains(document.activeElement)) restoreFocus(el, focus);     // a sentence those pages hold
  }));
}
function keyOf(a) {                                                                 // how to find a focused element again after a redraw
  return { id: a.id || null,                                                        // an id names it alone: the settings key and Undo are signs with no words to match by
    key: a.dataset && (a.dataset.key || a.dataset.sid) ? (a.dataset.key ? `[data-key="${a.dataset.key}"]` : `[data-sid="${CSS.escape(a.dataset.sid)}"]`) : null,
    text: a.textContent, tag: a.tagName, start: a.selectionStart, end: a.selectionEnd, value: /^(INPUT|TEXTAREA)$/.test(a.tagName) ? a.value : undefined };
}
function restoreFocus(el, f) {                                                      // the same element, or a button with the same words; true when found
  let n = f.id ? el.querySelector("#" + CSS.escape(f.id)) : null;                   // by its id
  if (!n && f.key) n = el.querySelector(f.key);                                     // by its key
  if (!n && !f.key) {                                                               // by its words, only when no other key has them: two "Drop" keys, or checkboxes with no words, would send the keyboard to the wrong one
    const same = [...el.querySelectorAll(f.tag || "button")].filter((x) => x.textContent === f.text);
    if (same.length === 1) n = same[0];
  }
  if (!n) return false;                                                             // gone
  if (f.value !== undefined && /^(INPUT|TEXTAREA)$/.test(n.tagName) && n.value !== f.value) n.value = f.value;  // the words being typed stay
  n.focus({ preventScroll: true });                                                 // back
  if (typeof f.start === "number" && n.setSelectionRange) try { n.setSelectionRange(f.start, f.end); } catch (_) { /* not a text field */ }   // the caret where it was, not at the end
  return true;
}
function render() {                                                                 // the whole page from S and UI
  if (!S) return;                                                                   // nothing yet
  document.title = "Offerowl";                                                      // the tab's name
  if (S.open === 2 && !UI.opened) { UI.opened = true; UI.view = "profile"; }       // the fact review screen (src/ui) opens on the profile
  if (UI.view === "interview" || UI.view === "tracker") go(UI.view);                // a view remembered from before: now a part of the applications
  if (!VIEWS.some(([k]) => k === UI.view)) UI.view = "make";                       // a view this page no longer has
  drawPane($("top"), "bar", drawBar);                                               // the bar
  drawPane($("canvas"), "canvas", (el) => ({ make: viewMake, profile: viewProfile, jobs: viewJobs, documents: viewDocuments, insights: viewInsights, library: viewLibrary }[UI.view] || viewMake)(el));
  $("canvas").setAttribute("aria-label", t(VIEWS.find(([k]) => k === UI.view)?.[1] || "Make"));  // the main area's name
  $("canvas").dataset.view = UI.view;                                               // the layout reads which view it is
  $("work").dataset.view = UI.view;                                                 // only a document has an inspector beside it
  $("side").hidden = UI.view !== "documents";                                       // the inspector's column
  $("dochead").hidden = UI.view !== "documents";                                    // the documents' head, over both columns
  if (UI.view === "documents") drawPane($("inspector"), "insp", drawInspector);     // drawn when it shows
  if (UI.view === "documents") markSelected();                                      // the selected sentence marked where it stands: the canvas is not drawn again for a click
  $("scrim").classList.toggle("open", UI.drawer && UI.view === "documents");        // the shade behind an open drawer
  $("skip").textContent = t("Skip to the document");                                // the first key on the page
  drawPane($("setup"), "setup", drawSetup);                                         // the setup guide over the page, when open (setup.js)
  setupFirst();                                                                     // by itself once, for a workspace that holds nothing yet
  notifyDue();                                                                      // due reminders as notifications
}

// ---------------------------------------------------------------- the keyboard and the start

document.addEventListener("keydown", (e) => {                                       // keys that work everywhere
  if (UI.confirm != null) return;                                                   // the panel's question is answered first (core.js askFirst holds its keys)
  if (e.key === "Tab" && UI.menu) { trapTab(e, document.getElementById("menu")); if (e.defaultPrevented) return; }   // the settings: the page behind is dimmed
  if (e.key === "Tab" && UI.agentPop) { trapTab(e, document.querySelector(".barpop .pop")); if (e.defaultPrevented) return; }   // the agent's panel too
  const field = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;  // typing in a field
  if (e.key === "Escape") {                                                         // close what is open
    if (UI.setup != null) { closeSetup(); return; }                                 // the setup guide, first: it lies over everything
    // each closes and gives the keyboard back to the key that opened it, not to the top of the page
    if (UI.menu || UI.agentPop) { const menu = UI.menu; UI.menu = false; UI.agentPop = false; render();   // the bar is drawn anew: its keys are found after
      const k = menu ? $("more") : document.querySelector(".barchip"); if (k) k.focus({ preventScroll: true }); return; }
    if (UI.askOpen && typeof askToggle === "function") { askToggle(false); return; }   // the command bar, wherever the keyboard is: it closes into its key, which takes the focus
    if (UI.adding && UI.view === "jobs" && (S.jobs || []).length) { UI.adding = false; render();   // the posting's form (with no job yet it is the page itself, and stays)
      const k = document.querySelector('[data-key="jobs-add"]'); if (k) k.focus({ preventScroll: true }); return; }
    if (UI.editing) { UI.editing = false; render(); const s = UI.sel && document.querySelector(`[data-sid="${CSS.escape(UI.sel)}"]`); if (s) s.focus({ preventScroll: true }); return; }   // the sentence
    if (UI.drawer) { UI.drawer = false; render(); const k = document.querySelector(".insp-toggle"); if (k) k.focus({ preventScroll: true }); return; }   // the drawer's key
    if (UI.sel) { UI.sel = null; render(); return; }                                // the selection
  }
  if (UI.setup != null) return;                                                     // the guide is modal: no undo or view change behind it, unseen
  if (e.defaultPrevented) return;                                                   // a part of the page took the key as its own (the scripts' Alt+1 to Alt+3 choose their language)
  if (!field && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); return; }  // undo outside a field
  if (!field && e.altKey && /^[1-9]$/.test(e.key) && Number(e.key) <= VIEWS.length) { e.preventDefault(); go(VIEWS[Number(e.key) - 1][0]); }  // Alt+1 and on: the views
});
document.addEventListener("click", (e) => {                                         // a click outside an open dropdown closes it
  if (UI.menu && !e.target.closest("#menu") && !e.target.closest("#more")) { UI.menu = false; render(); }
  if (UI.agentPop && !e.target.closest(".barpop")) { UI.agentPop = false; render(); }
});
$("scrim").addEventListener("click", () => { UI.drawer = false; if (UI.askOpen) askToggle(false); render(); });   // a tap beside the drawer, or beside the open command bar, closes it
$("filepick").addEventListener("change", (e) => { const f = [...e.target.files]; e.target.value = ""; if (f.length) makeFrom({ files: f }); });  // picked files start a run
$("scenepick").addEventListener("change", async (e) => {                         // interview scenes written before, into the job in view
  const files = [...e.target.files]; e.target.value = ""; if (!files.length || !UI.scenesFor) return;
  let scenes = 0, refused = 0;                                                      // what came in
  for (const f of files) {                                                          // one request each
    try {
      const r = await postFile(`/api/v1/interview/scenes?job=${enc(UI.scenesFor)}`, f);
      const j = await r.json().catch(() => ({}));                                   // its answer
      if (r.ok) scenes += j.scenes || 0; else refused++;                            // counted
    } catch (_) { refused++; }
  }
  toast(refused ? t("{n} scenes added; {m} files held no scenes.", { n: scenes, m: refused }) : tn(scenes, "{n} scene added.", "{n} scenes added."), null, refused ? "warn" : "done");
  if (typeof boardReload === "function") boardReload(UI.scenesFor);                 // the board reads them again
  refresh();
});
$("formpick").addEventListener("change", (e) => {                                 // a screenshot or a file of a form: its questions
  const f = e.target.files[0]; e.target.value = ""; if (f && UI.formFor) questionsFromFile(UI.formFor, f);
});
$("matpick").addEventListener("change", (e) => {                                  // decks, notes and briefs for the job whose interview is open
  const f = [...e.target.files]; e.target.value = ""; if (f.length && UI.matFor) addMaterials(UI.matFor, f);
});
async function questionsFromFile(jid, f) {                                          // read on the server (OCR for a picture), then added
  toast(t("Reading the questions..."));                                             // OCR takes a moment
  try {
    const r = await postFile(`/api/v1/jobs/questions/file?job=${enc(jid)}`, f);
    const j = await r.json().catch(() => ({}));                                     // its answer
    toast(r.ok ? tn(j.added, "{n} question added.", "{n} questions added.") : t("No question was found in it. Paste the form's questions as they appear."), null, r.ok ? "done" : "bad");
  } catch (_) { toast(t("No question was found in it. Paste the form's questions as they appear."), null, "bad"); }
  refresh();                                                                        // the card shows them
}
$("photopick").addEventListener("change", async (e) => {                         // the resume's photo
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;                 // one picture
  try {
    const r = await postFile("/api/v1/photo", f);
    if (!r.ok) { toast(r.status === 413 ? t("That picture is too large.") : t("Use a JPEG or PNG photo."), null, "bad"); return; }   // refused
    toast(t("The photo goes on the resume."), null, "done"); refresh();                           // kept, and drawn
  } catch (_) { /* the server stopped: the band says so */ }
});
$("stylepick").addEventListener("change", async (e) => {                         // a person's own writing rules
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;                 // one file
  let pack = null;                                                                  // its rules
  try { pack = JSON.parse(await f.text()); } catch (_) { /* not JSON */ }
  if (!pack || typeof pack !== "object" || Array.isArray(pack)) { toast(t("That file is not a rules file."), null, "bad"); return; }
  const r = await act("/api/v1/style", { name: f.name.replace(/\.json$/i, ""), pack });   // checked and kept, then in use
  if (r) toast(t("The rules {name} are in use.", { name: r.style }), null, "done");
});
$("blindpick").addEventListener("change", async (e) => {                         // a person's own table for the blind edition
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;                 // one file
  let table = null;                                                                 // its patterns
  try { table = JSON.parse((await f.text()).replace(/^\uFEFF/, "")); } catch (_) { /* not JSON */ }   // a byte-order mark from a Windows editor is not part of it
  if (!table || typeof table !== "object" || Array.isArray(table)) { toast(t("That file is not a mask table."), null, "bad"); return; }
  const r = await act("/api/v1/blind", { table });                                  // checked on the server, then kept in the workspace
  if (r && r.blind) toast(tn(r.blind.counts.mask, "Your table is in use: {n} pattern to cover.", "Your table is in use: {n} patterns to cover."), null, "done");
});
$("folderpick").addEventListener("change", (e) => { const f = [...e.target.files]; e.target.value = ""; if (f.length) makeFrom({ files: f }); });  // a picked folder, every file in it
window.addEventListener("resize", debounce(redrawAll, 200));                       // the pages are laid out for the new width
PHONE.addEventListener?.("change", () => { $("canvas")._key = null; render(); });  // the phone layout turned on or off
const underBar = () => $("top").classList.toggle("under", window.scrollY > 4);    // the bar takes its glass once the page slides under it
window.addEventListener("scroll", underBar, { passive: true });                    // as the page scrolls,
window.addEventListener("resize", underBar);                                       // and when a new window size moves the page without a scroll event (WebKit, measured)
let barFrame = 0;                                                                   // one arranging per frame, however many changes asked for it
if (window.ResizeObserver) new ResizeObserver(() => {                              // what sits under the bar starts below it, however many rows the bar takes
  if (barFrame) return;                                                             // already asked for this frame
  barFrame = requestAnimationFrame(() => {                                          // a frame later: resizing the bar inside its own observer is a loop WebKit reports as an error
    barFrame = 0;
    fitBar($("top").querySelector(".bar-in"));                                       // a bar that wrapped (its face loaded, a chip appeared) is arranged again first
    const h = $("top").offsetHeight; if (h) document.documentElement.style.setProperty("--bar-h", `${h}px`);
  });
}).observe($("top"));
if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => fitBar($("top").querySelector(".bar-in")));   // measured again with the bar's own face, wider than the stand-in
document.addEventListener("dragover", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) e.preventDefault(); });  // files may be dropped anywhere
document.addEventListener("drop", async (e) => {                                    // files or folders dropped anywhere start a run
  if (e.target.closest && e.target.closest(".drop")) return;                        // the drop zone handles its own
  if (!e.dataTransfer || !e.dataTransfer.files.length) return;                      // not files
  e.preventDefault();                                                               // the browser would open the file
  makeFrom({ files: await droppedFiles(e.dataTransfer) });                          // folders walked, then the run
});

document.addEventListener("compositionstart", () => { UI.composing = true; }, true);   // an input method starts a syllable
document.addEventListener("compositionend", () => { UI.composing = false; setTimeout(render, 0); }, true);   // done: what waited is drawn
let addressRead = false;                                                            // the window's own address is read once, with the first state
function fromAddress() {                                                            // /?job=<id>&show=scripts: a window opened from an application's Interview tab, on its scripts over the whole width
  if (addressRead) return;
  addressRead = true;
  const q = new URLSearchParams(location.search), jid = q.get("job");
  if (!jid || q.get("show") !== "scripts") return;                                  // any other address: the view this browser was on
  history.replaceState(null, "", location.pathname);                                // read once: a reload stays where the person is by then
  if (!(S.jobs || []).some((j) => j.id === jid)) return;                            // an application that is gone
  UI.ivWide = true; UI.ivPart = "search"; UI.jobsMode = "list";                     // its scripts, the list folded away (this window only: the choice kept in the browser is the other window's)
  (S.job === jid ? Promise.resolve() : act("/api/v1/jobs/select", { job: jid })).then(() => go("interview"));
}
function redrawAll() {                                                              // every pane again (a new size or look)
  for (const id of ["top", "canvas", "inspector"]) if (!(id === "canvas" && kitFramed())) $(id)._key = null;   // but a canvas that holds a kit's frame: the frame's page lays itself out, and a new look still redraws it by its key
  render();
}
refresh();                                                                          // the first state, then polling
