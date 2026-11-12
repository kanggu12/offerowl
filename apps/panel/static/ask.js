// Offerowl's panel, the command bar: "Ask the AI", a closed prompt floating at the bottom right of every view (on a phone or a
// tablet, a bar along the foot of the screen), as the owner asked: a box like a coding agent's prompt, where the person writes
// to the AI agent ("Gamma Cloud's first call is done, write it down", "make a resume for this posting: ..."). It opens a sheet
// at the window's right edge. The agent acts through Offerowl's own tools (POST /api/v1/ask, apps/api/ask.py) and its answer
// comes back there with the tools that ran. Ctrl+K or Cmd+K opens and closes it; Enter sends, Shift+Enter starts a new line.
"use strict";                                                                       // catches undeclared names and silent writes early

const MAC = /mac|iphone|ipad/i.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "");   // the key's name on this keyboard

const ASK_WORDS = {                                                                // the answers that are the panel's own words, not the agent's
  needs_tool_agent: "The command bar needs Claude Code or Codex: a local model cannot act through Offerowl's tools.",
  ask_timeout: "The agent took more than 15 minutes and was stopped. Nothing it had not finished was kept.",
  ask_no_start: "The agent's command would not start on this PC. The agent's card says what it needs.",
  ask_failed: "The agent stopped without an answer. Try again, or look at the agent's card.",
};

function inline(text) {                                                             // **bold** and `code` inside a line, as elements (never HTML from the answer)
  const out = [];
  for (const part of String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/)) {
    if (!part) continue;
    if (part.startsWith("**") && part.endsWith("**")) out.push(h("b", { text: part.slice(2, -2) }));
    else if (part.startsWith("`") && part.endsWith("`")) out.push(h("code", { text: part.slice(1, -1) }));
    else out.push(part);
  }
  return out;
}
function answerView(text) {                                                         // an answer in Markdown as the agent writes it: paragraphs, lists, tables
  const blocks = [], lines = String(text).split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*\|.*\|\s*$/.test(line)) {                                             // a table: its rows until the first line that is not one
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i]); i++; }
      i--;
      const cells = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r)).map((r) => r.trim().slice(1, -1).split("|").map((c) => c.trim()));
      if (cells.length) blocks.push(h("table", { class: "ask-table" }, h("thead", {}, h("tr", {}, cells[0].map((c) => h("th", {}, inline(c))))),
        h("tbody", {}, cells.slice(1).map((r) => h("tr", {}, r.map((c) => h("td", { class: c.length <= 16 ? "nw" : null }, inline(c))))))));   // a date or a number never broken at its hyphen
    } else if (/^\s*[-*] /.test(line)) {                                             // a list
      const items = [];
      while (i < lines.length && /^\s*[-*] /.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*] /, "")); i++; }
      i--;
      blocks.push(h("ul", {}, items.map((x) => h("li", {}, inline(x)))));
    } else if (line.trim()) blocks.push(h("p", {}, inline(line.replace(/^#+\s*/, ""))));   // a paragraph (a heading reads as one)
  }
  return blocks;
}

function askDoc() {                                                                 // the history, fetched again when an ask starts or ends
  const tk = task("ask");                                                           // the ask now
  const key = "ask|" + [tk.state || "", tk.t || "", tk.run || ""].join(":");
  if (!UI.docs[key]) { for (const k of Object.keys(UI.docs)) if (k.startsWith("ask|") && k !== key && k !== UI.askKey) delete UI.docs[k]; getDoc(key, "/api/v1/ask"); }
  if (UI.docs[key] && !UI.docs[key].error) UI.askKey = key;
  return UI.docs[key] || (UI.askKey && UI.docs[UI.askKey]) || { history: [] };     // the last one while a new one loads
}

async function askSend(box) {                                                       // the words to the agent
  const text = box.value.trim();
  if (!text || task("ask").state === "running") return;                            // nothing to send, or one is still working
  UI.askDraft = ""; box.value = "";                                                 // the box is free at once: the redraw the request makes draws it empty
  UI.askHistLen = (askDoc().history || []).length;                                  // the asks kept before this one: its working note goes once the history holds it
  const r = await act("/api/v1/ask", { text });                                     // started, or refused with its reason
  if (!(r && r.started)) { UI.askDraft = text; const b = document.getElementById("askbox"); if (b) b.value = text; }   // not taken: the words come back, to send again
  if (r && r.started === false) toast(t("The agent is still working on the last request."));
  const now = document.getElementById("askbox"); if (now) now.focus({ preventScroll: true });   // the keyboard stays in the box the sheet now has
}

async function askClear() {                                                         // the history emptied, once the person agrees: it cannot come back
  const n = (askDoc().history || []).length;                                        // what goes
  if (!(await askFirst({ title: t("Clear the command bar's history?"), ok: t("Clear"), danger: true,
    text: tn(n, "{n} request and its answer are deleted. What the agent did through Offerowl stays, and undo still takes it back.", "{n} requests and their answers are deleted. What the agent did through Offerowl stays, and undo still takes it back.") }))) return;
  const r = await act("/api/v1/ask/clear", {});                                     // refused while an ask runs
  if (r) { for (const k of Object.keys(UI.docs)) if (k.startsWith("ask|")) delete UI.docs[k]; UI.askKey = null; drawAsk(); toast(t("The command bar's history was cleared.")); }
}

function askToggle(open) {                                                          // the bar opened in its key's place, or closed back into it
  if (open && !UI.askOpen) UI.askBack = document.activeElement;                    // where the person was, to go back to
  UI.askOpen = open;
  drawAsk();
  if (open) { setTimeout(() => { const b = document.getElementById("askbox"); if (b) b.focus(); }, 30); return; }   // straight to the words
  const back = UI.askBack; UI.askBack = null;                                       // the field it was opened from, else the key that stands again
  const key = document.querySelector("#askbar .ask-fab");                          // the closed prompt, standing again
  const to = back && back.isConnected && back !== document.body ? back : key;
  if (to) to.focus({ preventScroll: true });
}

function askKey() {                                                                 // the closed prompt: words that say what it is for, the agent's lamp, its key
  const working = task("ask").state === "running", lamp = agentLamp();              // a request on its way, and the agent's lamp
  return h("button", { class: "ask-fab" + (working ? " working" : ""), type: "button", "data-lamp": working ? "busy" : lamp[0], "aria-haspopup": "dialog", "aria-controls": "askpanel",
    title: t("Ask the AI ({key})", { key: MAC ? "\u2318K" : "Ctrl+K" }), onclick: () => askToggle(true) },   // its key on this keyboard, said on the hover
    h("span", { class: "ask-fab-i", "aria-hidden": "true" }, icon("agent")),        // the agent's mark, lit by its lamp
    h("span", { class: "ask-fab-w", text: t("Ask the AI") }),                      // the box's own words: what it is for
    h("kbd", { class: "ask-fab-k", "aria-hidden": "true", text: MAC ? "\u2318K" : "Ctrl K" }));   // its key at the end, as a command box shows it (a phone has none: skin.css)
}

// what each of Offerowl's tools (apps/mcp/server.py) did, in words: a request's answer lists the steps it took
const TOOL_WORDS = { status: "Read the status", list_jobs: "Read the applications", get_job: "Read an application", job_fit: "Read the fit",
  read_document: "Read a document", document_file: "Opened a document's file", deck: "Read the deck", interview_board: "Read the interview board",
  interview_search: "Searched the scripts", form_answers: "Read the form answers", tracker: "Read the board", insights: "Read the insights",
  library: "Read the library", task: "Read a task", add_job: "Added a posting", make_documents: "Made the documents", build_pdfs: "Made the PDFs",
  export_documents: "Exported the documents", make_interview_kit: "Made the interview kit", write_interview_scripts: "Wrote the interview scripts",
  move_job: "Moved an application", log_round: "Recorded an interview", add_fact: "Put in a fact", reminder: "Set a reminder" };
function toolWords(x) {                                                             // a tool's step in words; another tool keeps its own name, spaced
  const name = String(x).replace(/^.*__/, "");                                      // mcp__offerowl__list_jobs: the tool's own part
  return TOOL_WORDS[name] ? t(TOOL_WORDS[name]) : name.replace(/_/g, " ");
}
function drawAsk() {                                                                // the key and, when open, the bar
  let host = document.getElementById("askbar");
  if (!host) { host = document.createElement("div"); host.id = "askbar"; document.body.append(host); }
  if (typeof S === "undefined" || !S) return;                                       // the state comes first
  const tk = task("ask"), working = tk.state === "running";
  const lamp = agentLamp(), name = S.agent.backend === "none" ? t("AI agent") : t(AGENT_NAME[S.agent.backend] || S.agent.backend);
  const hist = UI.askOpen ? (askDoc().history || []) : [];                           // asked first, so a history that just arrived draws the bar again
  const last = hist.length ? hist[hist.length - 1] : {};                            // the newest ask: a new answer changes its time, words or outcome
  const key = JSON.stringify([UI.askOpen, working, tk.t, hist.length, last.at, last.text, last.seconds, last.ok, String(last.answer || "").length, LANG, lamp, name]);
  if (host._key === key) return;                                                    // nothing new: the words being typed stay
  host._key = key;
  if (!UI.askOpen) return fill(host, askKey());                                     // closed: the prompt at the bottom right (a phone: the bar along the foot)
  const items = hist.slice(-12);                                                    // the last asks, oldest first
  const log = h("div", { class: "ask-log", role: "log", "aria-live": "polite" },
    items.length ? items.map((it) => h("div", { class: "ask-item" },
      h("p", { class: "ask-me", text: it.text }),
      h("div", { class: "ask-ans" + (it.ok ? "" : " bad") },
        ASK_WORDS[it.answer] || !it.answer ? h("p", { text: t(ASK_WORDS[it.answer] || "No answer came back.") }) : answerView(it.answer),
        (it.tools || []).length ? h("div", { class: "ask-tools" }, [...new Set(it.tools)].map((x) => h("span", { class: "pill on", title: x, text: toolWords(x) }))) : null,   // a tool by what it did, its own name on the hover
        h("small", { text: [it.at, it.backend ? t(AGENT_NAME[it.backend] || it.backend) : "", it.seconds ? t("{n} s", { n: it.seconds }) : ""].filter(Boolean).join(" · ") }))))   // the agent by its name, not its setting's id
      : h("p", { class: "ask-empty", text: t("Write it as you would to Claude Code or Codex: an interview's result to record, a posting to make a resume for, a question about your applications.") }),
    working && hist.length <= (UI.askHistLen ?? hist.length) ? h("div", { class: "ask-item" }, h("p", { class: "ask-me", text: UI.askLast || "" }), h("div", { class: "ask-ans" }, pill("busy", t("Working with Offerowl's tools…")))) : null);   // until the history holds it: then it is there once
  const box = h("textarea", { id: "askbox", "data-key": "ask-text", rows: 2, placeholder: t("Write what the AI should do, or what to ask it"), value: UI.askDraft || "", "aria-label": t("Ask the AI"),
    oninput: (e) => { UI.askDraft = e.target.value; },
    onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); UI.askLast = e.target.value.trim(); askSend(e.target); } else if (e.key === "Escape") { e.stopPropagation(); askToggle(false); } } });   // Escape closes the top layer only: the drawer or selection under the bar stays
  const able = ["claude-code", "codex"].includes(S.agent.backend) && S.agent.state === "ready";   // an agent that can act through Offerowl's tools, on and signed in
  const panel = h("section", { id: "askpanel", class: "ask-panel", role: "dialog", "aria-label": t("Ask the AI") },
    h("header", { class: "ask-head" }, icon("agent"), h("b", { text: t("Ask the AI") }),   // what the sheet is for, as its key says
      h("span", { class: "ask-sub" }, h("span", { class: "lit " + (working ? "busy" : lamp[0]), "aria-hidden": "true" }), h("span", { text: `${name} · ${t(lamp[1])}` })),   // which agent answers, and its state
      h("span", { class: "grow" }),
      hist.length ? h("button", { class: "btn small quiet", type: "button", "data-key": "ask-clear",
        disabled: working || null, onclick: askClear }, icon("trash"), t("Clear this history")) : null,   // the asks and answers kept in the workspace, emptied: said in words
      h("button", { class: "btn icon small", type: "button", "aria-label": t("Close"), onclick: () => askToggle(false) }, icon("close"))),
    able || working ? null : h("div", { class: "band info ask-need", role: "note" },   // said before anything is typed: a request needs an agent that can use the tools
      h("p", { text: t("Requests need Claude Code or Codex, switched on and signed in.") }),
      h("button", { class: "btn small", type: "button", onclick: (e) => { e.stopPropagation(); askToggle(false); UI.agentPop = true; UI.menu = false; render(); } }, t("Open the AI agent"))),   // the agent's own panel, where it is turned on (the click goes no further: a click outside the agent's panel closes it)
    log,
    h("div", { class: "ask-input" }, box,
      h("button", { class: "btn primary", type: "button", disabled: working || null, "aria-label": t("Send"), onclick: () => { UI.askLast = box.value.trim(); askSend(box); } }, icon("send"))),
    h("p", { class: "ask-hint" }, h("kbd", { text: "Enter" }), t("send"), h("kbd", { text: "Shift+Enter" }), t("new line")));   // the two keys, as a prompt shows them: no sentence
  if (document.getElementById("askpanel")) panel.classList.add("stay");            // drawn again while open: it slides in once, on opening, never at each answer
  fill(host, panel);                                                                // open: a sheet at the window's right edge, under the top bar (a phone: from the foot)
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });             // the newest in view
}

addEventListener("keydown", (e) => {                                               // Ctrl+K or Cmd+K: the bar, from anywhere
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && UI.confirm == null) {   // never from behind the panel's question
    e.preventDefault(); askToggle(!UI.askOpen);
  }
});
const renderBeforeAsk = render;                                                     // the page's own drawing, then the bar's
render = function () { renderBeforeAsk(); try { drawAsk(); } catch (_) { /* the bar never stops the page */ } };   // eslint-disable-line no-global-assign
