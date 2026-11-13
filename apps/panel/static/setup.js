// Offerowl's panel, the setup guide. Four steps over the page: the AI agent that reads the files and writes, the
// tools that typeset the PDFs, how the panel looks, and a first start (the person's own files, or the fictional example).
// Each step says how things stand in the words the panel uses elsewhere (the agent's card, the typesetting's band, the
// settings menu) and holds the one action that fixes what is missing; a step that works shows a tick. It opens by itself
// once in a browser, when the workspace holds nothing yet, and again from the settings menu. Closing it changes nothing
// that was not changed in it.

const SETUP_SEEN = "offerowl-setup-seen";                                          // this browser has seen the guide once
const SETUP_STEPS = [["agent", "AI agent", "agent"], ["typeset", "Typesetting", "typeset"], ["look", "Look", "sun"], ["start", "Start", "make"]];   // id, name, sign

function setupState(id) {                                                           // ok, warn (something to do first) or idle (optional, or not known yet)
  const a = S.agent || {};                                                          // the agent's card
  if (id === "agent") return a.state === "ready" ? "ok" : a.state === "signed_out" || a.state === "missing" ? "warn" : "idle";   // off is a choice, checking not known yet
  if (id === "typeset") return task("setup").state === "running" ? "idle" : S.engine ? "warn" : "ok";
  if (id === "look") return "ok";                                                   // it always has a choice, Auto at first
  return (S.materials || []).length ? "ok" : "idle";                                // files are in
}
function openSetup(step) {                                                          // from the menu, or by itself the first time
  UI.setup = typeof step === "number" ? step : 0;                                   // the step shown
  UI.menu = false; UI.agentPop = false;                                             // one thing open at a time
  localStore(SETUP_SEEN, "1");                                                      // never by itself again in this browser
  render();
  // the keyboard in the guide, on its title: Tab goes on to the close key, Esc closes. On the close key itself, the ring a page
  // draws for a focus it was not clicked to would be the first thing seen, and it would point at the way out
  requestAnimationFrame(() => { const k = document.getElementById("setup-title"); if (k) k.focus({ preventScroll: true }); });
}
function closeSetup() {                                                             // the close key, Esc, the last step's Done, or a run started from files
  if (UI.setup == null) return;
  UI.setup = null;
  render();
  const more = document.getElementById("more"); if (more) more.focus({ preventScroll: true });   // back to where it can be opened again
}
function setupFirst() {                                                             // by itself, once in a browser, for a workspace that holds nothing yet
  if (UI.setup != null || UI.setupChecked || !S || !S.agent) return;                // the state first (the agent's step says "checking" while its first look runs)
  UI.setupChecked = true;                                                           // asked once per page load
  const empty = !(S.materials || []).length && !((S.facts && S.facts.counts && S.facts.counts.found) || 0)
    && task("autopilot").state !== "running";                                       // no files, no facts, and no run reading a path
  let seen = true;                                                                  // with nothing to remember it by, it is not opened unasked
  try { seen = !!localStorage.getItem(SETUP_SEEN); } catch (_) { /* storage refused: it would come back with every page */ }
  if (empty && !seen) openSetup(0);
}
// one thing as the panel says it elsewhere: its name, its lamp and words, and what follows
function setupGo(i) {                                                               // another step: shown from its top, with the keyboard kept in the guide
  UI.setup = (i + SETUP_STEPS.length) % SETUP_STEPS.length;                         // the arrows go round
  render();
  const host = document.getElementById("setup");                                   // on a phone the guide scrolls as a whole
  if (!host) return;
  host.scrollTop = 0;                                                               // the redraw kept the last step's place, which is not this one's
  if (!host.contains(document.activeElement)) { const k = host.querySelector('[data-key="setup-next"]'); if (k) k.focus({ preventScroll: true }); }   // the key pressed went away (Back on the first step)
}
function setupCard(name, lamp, words, ...rest) {
  return h("div", { class: "setup-card" }, h("div", { class: "setup-card-top" }, h("b", { text: name }), pill(lamp, t(words))), ...rest);
}
function setupAgent() {                                                             // step 1: the AI agent
  const a = S.agent || {}, s = S.settings || {}, found = a.found || [], [lamp, words] = agentLamp();
  const name = a.backend === "none" || !a.backend ? t("AI agent") : t(AGENT_NAME[a.backend] || a.backend);
  // the one thing that fixes it, as the agent's card does it. Off is the backend "none" (the switch keeps what it turned off,
  // and "on" brings that back); missing names the chosen agent's own install page, which the state carries
  const local = a.backend === "openai-compat";                                       // a server at an address: the fields below are its fix
  const key = a.state === "signed_out" && !local ? h("button", { class: "btn primary", type: "button", "data-key": "setup-signin", onclick: () => act("/api/v1/agent/login", {}) }, icon("agent"), a.signing_in ? t("Signing in…") : t("Sign in"))
    : a.state === "off" ? h("button", { class: "btn primary", type: "button", "data-key": "setup-on", onclick: () => act("/api/v1/settings", { agent: "on" }) }, icon("agent"), t("Turn it on"))
    : a.state === "missing" && a.install ? h("a", { class: "btn primary", "data-key": "setup-get", href: a.install, target: "_blank", rel: "noopener" }, icon("open"), t("How to get {name}", { name }))
    : null;
  const who = a.state === "ready" ? h("p", { class: "setup-who" }, icon("person", 14), h("span", { text: a.email || t("This PC's sign-in") })) : null;
  const options = [["auto", "Find it automatically"], ["claude-code", "Claude Code"], ["codex", "Codex"], ["openai-compat", "Local model"], ["none", "No agent"]];   // as the menu lists them
  const note = a.state === "off" ? t("With no agent on, only an Offerowl profile file is read.")                 // what off means
    : local && a.state === "signed_out" ? t("Nothing answers at this address.") : "";                            // the address below is set, and dead
  return [
    h("p", { class: "setup-lede", text: t("The agent reads your files and writes the documents. Offerowl uses the one this PC is already signed in to.") }),
    setupCard(name, lamp, words, who, note ? h("p", { class: "setup-note", text: note }) : null, key ? h("div", { class: "setup-act" }, key) : null),   // what it is, then what fixes it
    h("label", { class: "field" }, h("span", { text: t("Which agent") }),   // the card above is named after the agent: the menu asks which one
      h("select", { "data-key": "s-backend", onchange: (e) => act("/api/v1/settings", { backend: e.target.value }) },
        options.map(([k, w]) => h("option", { value: k, selected: (s.backend || "auto") === k || null, text: t(w) + (found.includes(k) ? ", " + t("on this PC") : "") })))),
    s.backend === "openai-compat" ? h("div", { class: "setup-pair" },
      h("label", { class: "field" }, h("span", { text: t("Local server address") }), h("input", { "data-key": "s-url", value: s.llm_url || "", placeholder: "http://127.0.0.1:11434", onchange: (e) => act("/api/v1/settings", { llm_url: e.target.value }) })),
      h("label", { class: "field" }, h("span", { text: t("Model name") }), h("input", { "data-key": "s-model", value: s.llm_model || "", onchange: (e) => act("/api/v1/settings", { llm_model: e.target.value }) }))) : null,
  ];
}
function setupTypeset() {                                                           // step 2: the tools that make the PDFs
  const busy = task("setup").state === "running";
  const failed = !busy && S.engine === "engine_not_ready" && task("setup").state === "error";   // an install ended without the libraries: said, with its retry
  const info = failed ? errorInfo((task("setup").error || {}).code || "setup_failed") : S.engine ? errorInfo(S.engine) : null;
  const [lamp, words] = busy ? ["busy", "Installing"] : S.engine ? ["warn", S.engine === "engine_not_ready" ? "Not installed" : "Not found"] : ["ok", "Ready"];
  const fix = busy || !info || !info.fix ? null : info.href ? h("a", { class: "btn primary", "data-key": "setup-fix", href: info.href, target: "_blank", rel: "noopener" }, icon("open"), info.fix)
    : h("button", { class: "btn primary", type: "button", "data-key": "setup-fix", onclick: info.go }, icon(failed ? "refresh" : "download"), info.fix);
  return [
    h("p", { class: "setup-lede", text: S.renderer === "html" ? t("These tools make the PDFs with this PC's Chrome or Edge.")   // Windows, and a PC without Docker
      : t("These tools make the PDFs: in Docker where it is installed, otherwise with this PC's Chrome or Edge.") }),
    setupCard(t("Typesetting"), lamp, words,
      h("p", { class: "setup-note", text: busy ? t("Installing once, with the network. It takes a few minutes.") : info ? info.msg : t("The PDFs are made on this PC.") }),
      fix ? h("div", { class: "setup-act" }, fix, S.engine === "renderer_missing" ? h("button", { class: "btn", type: "button", "data-key": "setup-check", onclick: () => refresh() }, icon("refresh"), t("Check again")) : null) : null),
  ];
}
function setupLook() {                                                              // step 3: the language and the theme, as the menu sets them
  const themeNow = document.documentElement.dataset.themeChoice || "auto", langNow = langPicked();
  return [
    h("p", { class: "setup-lede", text: t("How the panel looks. The settings menu changes it any time.") }),
    h("div", { class: "setup-row" }, h("span", { class: "setup-row-name" }, icon("globe", 15), t("Language")),
      h("div", { class: "seg" }, [["auto", "Auto"], ["ko", "한국어"], ["en", "English"]].map(([k, w]) =>
        h("button", { type: "button", "data-key": "setup-lang-" + k, lang: k === "auto" ? null : k, "aria-pressed": langNow === k ? "true" : "false", onclick: () => pickLanguage(k), text: k === "auto" ? t(w) : w })))),
    h("div", { class: "setup-row" }, h("span", { class: "setup-row-name" }, icon("sun", 15), t("Theme")),
      h("div", { class: "seg" }, [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(([k, w]) =>
        h("button", { type: "button", "data-key": "setup-theme-" + k, "aria-pressed": themeNow === k ? "true" : "false", onclick: () => pickTheme(k), text: t(w) })))),   // by name: both rows have an "Auto"
  ];
}
function setupStart() {                                                             // step 4: the first start
  const n = (S.materials || []).length, running = task("autopilot").state === "running";
  return [
    h("p", { class: "setup-lede", text: t("Bring what you already have: an old resume, a portfolio, notes. Offerowl reads them and makes the rest.") }),
    h("div", { class: "setup-start" },
      h("button", { class: "btn primary", type: "button", disabled: running || null, onclick: () => { closeSetup(); go("make"); $("filepick").click(); } }, icon("file"), t("Choose files")),
      h("button", { class: "btn", type: "button", "data-act": "setup-example", disabled: running || null, onclick: () => { closeSetup(); seeExample(); } }, icon("person"), t("Try an example"))),
    n ? h("p", { class: "setup-note" }, pill("ok", tn(n, "{n} file added", "{n} files added"))) : null,
  ];
}
function drawSetup(el) {                                                            // the guide over the page, or nothing
  // the page behind is inert while the guide is open: Tab stays in the guide, and nothing behind it takes a click or the keyboard.
  // The skip link, the bar and the page; never the toast, which still says what a key in the guide did
  lockPage();                                                                       // core.js: the same rule for the panel's own question
  if (UI.setup == null) { el.hidden = true; fill(el); return; }
  el.hidden = false;
  const at = Math.max(0, Math.min(SETUP_STEPS.length - 1, UI.setup)), last = at === SETUP_STEPS.length - 1;
  // the steps as tabs: a click, or the arrow keys from the one in view (the keyboard stays on the steps)
  const move = (e) => { const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0; if (!d) return; e.preventDefault();
    setupGo(at + d); const k = document.querySelector('#setup .setup-step[aria-selected="true"]'); if (k) k.focus(); };
  const steps = h("div", { class: "setup-steps", role: "tablist", "aria-label": t("Setup steps"), onkeydown: move }, SETUP_STEPS.map(([id, name], i) => {
    const st = setupState(id);
    return h("button", { type: "button", role: "tab", class: "setup-step", "data-key": "setup-step-" + id, "data-state": st, "aria-selected": i === at ? "true" : "false", tabindex: i === at ? "0" : "-1",
      onclick: () => setupGo(i) },
      h("span", { class: "n", "aria-hidden": "true" }, st === "ok" ? icon("check", 13) : String(i + 1)), h("span", { class: "name", text: t(name) }));
  }));
  const was = el.querySelector(".setup-body"), keep = was && was.dataset.step === String(at) ? was.scrollTop : 0;   // a redraw of the same step keeps its place (a wide window scrolls the pane)
  const pane = h("div", { class: "setup-body", role: "tabpanel", "aria-labelledby": "setup-title", "data-step": String(at) }, ({ agent: setupAgent, typeset: setupTypeset, look: setupLook, start: setupStart }[SETUP_STEPS[at][0]])());
  // one main key on the sheet: the step's own (sign in, install, choose files) while it shows one, otherwise Next or Done
  const next = pane.querySelector(".btn.primary") ? "btn" : "btn primary";
  fill(el, h("div", { class: "setup-scrim", onclick: closeSetup }),
    h("section", { class: "setup", role: "dialog", "aria-modal": "true", "aria-labelledby": "setup-title" },
      h("header", { class: "setup-head" },
        h("img", { class: "setup-mark", src: "/brand/icon.svg", alt: "" }),
        h("h2", { id: "setup-title", tabindex: "-1", text: t("Set up Offerowl") }),
        h("button", { class: "btn icon sm setup-close", type: "button", "aria-label": t("Close"), title: t("Close"), onclick: closeSetup }, icon("close"))),
      steps,
      pane,
      h("footer", { class: "setup-foot" },
        at ? h("button", { class: "btn ghost", type: "button", "data-key": "setup-back", onclick: () => setupGo(at - 1) }, icon("back"), t("Back")) : h("span"),
        h("button", { class: next, type: "button", "data-key": "setup-next", onclick: () => { if (last) closeSetup(); else setupGo(at + 1); } },
          last ? t("Done") : t("Next")))));
  pane.scrollTop = keep;                                                            // where the pane was, now that it is laid out
}
