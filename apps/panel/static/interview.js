// Offerowl's panel: the interview tab's deck and practice, drawn with the panel's own parts. The contents, the search and the
// script cards are kit.js; this file draws the tab's other two parts the same way, so no page of the kit's own is framed:
//   ivDeck(j)      the printed deck's scripts in its order (GET /api/v1/jobs/<job>/interview/deck, src/interview/deck.py data)
//   ivPractice(j)  a mock interview through the kit's practice API at the panel's own address (/kit/<job>/api/practice/*,
//                  src/interview/practice.py), in the kit's own words, with its script cards (kit.js) after each answer
// The microphone is used only between Record and Stop, and the feedback and the script appear only after an answer is given.
"use strict";

// ---------------------------------------------------------------- shared

function dropDocs(prefix, keep) {                                                   // the large documents of an older revision go: one copy per kind is held
  for (const k of Object.keys(UI.docs)) if (k.startsWith(prefix) && k !== keep) delete UI.docs[k];
}
function taggedDoc(fam, path) {                                                     // a large document asked again per revision with the tag of the copy held: an unchanged one costs a 304
  const key = `${fam}|${rev()}`;                                                    // per revision: a script written or changed is read again
  if (!UI.docs[key]) { dropDocs(fam.split("|")[0] + "|", key); getDoc(key, path, fam); }   // asked once per revision (core.js getDoc sends the tag)
  return UI.docs[key] || (UI.tagged[fam] || {}).doc || null;                        // the copy held stays on screen while a newer one is on its way
}
const ivSmooth = () => (document.documentElement.dataset.motion === "off" ? "auto" : "smooth");   // a scroll that moves only when motion is on (theme.js)
function ivKitData(j) {                                                             // every script with its words, in the panel's language (megabytes for a large kit)
  return taggedDoc(`ivv|${j.id}|${LANG}`, `/api/v1/jobs/${enc(j.id)}/interview/view?lang=${LANG}`);
}
function ivKitView(j) {                                                             // the job's script view (kit.js): made when its scripts first arrive, again only when a kit file changes; null while they load
  const d = ivKitData(j);                                                           // what came
  let k = UI.kit && UI.kit.job === j.id && UI.kit.lang === LANG ? UI.kit : null;    // the view already up for this job: it stays while a newer copy is on its way, no blink, the question kept
  if (d && !d.error && (!k || k.stamp !== d.stamp || k.model !== !!d.model)) {      // the first time, or a kit file changed, or the similarity model came or went, or the language
    const q = UI.kit && UI.kit.job === j.id ? UI.kit.view.query() : "";             // the question in the box, carried over (into the other language's view too)
    if (UI.kit) UI.kit.view.destroy();                                              // the old view stops its polls
    k = UI.kit = { job: j.id, lang: LANG, stamp: d.stamp, model: !!d.model, data: d, view: kitView(d, { job: j.id }) };
    if (q) requestAnimationFrame(() => { if (UI.kit === k) k.view.search(q); });    // asked again in the new view
  }
  return k;                                                                         // null until the scripts arrive
}
function ivWait(d, waiting) {                                                       // a part that waits for its data, or says it could not have it
  return h("div", { class: "iv-wait card" }, h("p", { class: "hint", role: "status", text: d && d.error ? t("The interview kit could not start.") : waiting }));
}
function ivOpenScript(id) {                                                         // a script named in the deck: its card, in the search view
  UI.ivPart = "search"; UI.kitAsk = id; render();                                   // kit.js shows the item and the rest of its section
}

// ---------------------------------------------------------------- the deck

function ivDeck(j) {                                                                // the deck: who it is for, the posting line by line, the scripts part by part, the lines that buy time
  const d = taggedDoc(`ivd|${j.id}|${LANG}`, `/api/v1/jobs/${enc(j.id)}/interview/deck?lang=${LANG}`);   // in the panel's language
  if (!d) return ivWait(null, t("Reading the interview deck…"));                    // on its way
  if (d.error) return h("div", { class: "iv-wait card" }, h("p", { class: "hint", role: "status", text: t("The interview deck could not be read.") }));
  if (UI.deckView && UI.deckView.doc === d) return UI.deckView.el;                  // drawn once per copy: a redraw of the panel around it keeps it
  const el = deckView(j, d);                                                        // drawn
  UI.deckView = { doc: d, el };                                                     // kept for the next redraw
  return el;
}
function deckView(j, d) {                                                           // the deck in the panel's parts: paper for what is read, the panel's chips, lamps and keys
  const w = d.words || {};                                                          // the deck's own words, in the panel's language (src/interview/i18n.json)
  const partName = (p) => (w.parts || {})[p] || p;                                  // a part of the deck in words; a file-ordered deck names its file's heading
  if (!(d.scenes || []).length) return h("section", { class: "ivdeck" }, h("div", { class: "empty glass" }, h("p", { text: w.empty || t("No scripts yet") })));   // no script yet
  const who = (x) => (x === "me" ? t("You") : t("Interviewer"));                    // a speaker in the panel's words
  const anchor = (x) => "deck-" + j.id + "-" + x;                                   // a place in the deck the keys go to
  const goTo = (x) => { const el = document.getElementById(anchor(x)); if (el) el.scrollIntoView({ behavior: ivSmooth(), block: "start" }); };   // under the panel's bar (scroll-margin)
  const flash = (el) => { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); };   // the card gone to says so with its edge
  const inDeck = new Set(d.scenes.map((s) => s.id));                                // the scripts this deck prints
  const toScript = (id) => {                                                        // a script named in the posting's table
    if (!inDeck.has(id)) { ivOpenScript(id); return; }                              // not printed here: the search view has every script
    goTo(id); const el = document.getElementById(anchor(id)); if (el) flash(el);    // printed further down
  };
  const fig = (n, label) => h("div", { class: "stat" }, h("b", { text: String(n) }), h("span", { class: "k", text: label }));   // one figure of the cover
  const head = h("header", { class: "deck-head paper" },                            // the cover: the company, the role, what the deck holds
    h("div", { class: "deck-who" }, h("span", { class: "deck-eye", text: w.title || t("Interview deck") }), h("h2", { text: d.company || "" }),
      d.role ? h("p", { class: "sub", text: d.role }) : null),
    h("div", { class: "deck-figs" }, fig(d.counts.scripts, w.scripts), fig(d.counts.questions, w.questions),
      d.counts.parts.map((p) => fig(p.n, partName(p.part)))));                      // the scripts per part
  const groups = [];                                                                // the scripts by part, in the deck's order
  for (const s of d.scenes) { const g = groups[groups.length - 1]; if (g && g.part === s.part) g.items.push(s); else groups.push({ part: s.part, items: [s] }); }
  const nav = h("nav", { class: "deck-nav", "aria-label": w.title || t("Interview deck") },   // a key to each part of the deck
    d.posting.length ? h("button", { class: "btn small", type: "button", onclick: () => goTo("posting"), text: w.posting_title }) : null,
    groups.map((g, i) => h("button", { class: "btn small", type: "button", onclick: () => goTo("part-" + i) }, partName(g.part), h("span", { class: "n", text: String(g.items.length) }))),
    d.stall.length ? h("button", { class: "btn small", type: "button", onclick: () => goTo("stall"), text: w.stall_title }) : null);
  const posting = d.posting.length ? h("section", { class: "deck-sec paper", id: anchor("posting"), "aria-label": w.posting_title },   // the posting line by line, with the script for each line
    h("h3", { text: w.posting_title }),
    h("div", { class: "deck-table" }, h("table", { class: "deck-lines" },
      h("thead", {}, h("tr", {}, (w.posting_cols || []).map((c) => h("th", { scope: "col", text: c })))),
      h("tbody", {}, d.posting.map((r) => h("tr", {},
        h("td", { text: r.text }),                                                  // the posting's own line
        h("td", { class: "by" }, r.script ? h("button", { class: "deck-ref-key", type: "button", onclick: () => toScript(r.script) },   // the script that answers it
          h("span", { class: "chip id", text: r.script }), h("span", { class: "t", text: r.title })) : h("span", { class: "hint", text: w.none })),
        h("td", { class: "cov" }, h("span", { class: "lit " + (COVERAGE_CLS[r.coverage] || "off") }, h("span", { text: (w.cov || {})[r.coverage] || r.coverage })))))))))   // how well
    : null;
  const scene = (s) => {                                                            // one script: the question, the dialogue, then the notes beside it
    const tr = s.turns.filter((x) => x.ko);                                         // the translated lines
    const side = [                                                                  // what is read beside the dialogue: the translation as one note, the notes, the other questions
      tr.length ? h("div", { class: "deck-note tr" }, h("h5", { text: w.translation }), tr.map((x) => h("p", { class: x.who }, h("b", { text: who(x.who) }), " ", speech(x.ko)))) : null,
      s.notes.length ? h("div", { class: "deck-note" }, h("h5", { text: w.notes }), s.notes.map((n) => h("p", {}, speech(n)))) : null,
      s.also.length ? h("div", { class: "deck-note" }, h("h5", { text: w.also }), h("ul", {}, s.also.map((q) => h("li", { text: q })))) : null].filter(Boolean);
    return h("article", { class: "deck-scene paper", id: anchor(s.id), "data-id": s.id, "aria-label": s.ask },
      h("header", { class: "deck-sh" },
        h("div", { class: "deck-q" }, h("h4", { text: s.ask }), s.sub ? h("p", { class: "q-ko", text: s.sub }) : null),   // as the interviewer asks it, its Korean under it
        h("div", { class: "deck-ref" }, s.draft ? h("span", { class: "chip ai", text: w.draft }) : null,   // an agent's draft says so
          h("button", { class: "deck-ref-key", type: "button", title: t("Open in the search view"), onclick: () => ivOpenScript(s.id) },
            h("span", { class: "t", text: s.title }), h("span", { class: "chip id", text: s.id })))),
      h("div", { class: "deck-body" + (side.length ? "" : " one") },
        h("div", { class: "deck-talk" }, s.turns.map((x) => h("div", { class: "turn " + x.who }, h("span", { class: "who", text: who(x.who) }), h("span", { class: "en" }, speech(x.en))))),
        side.length ? h("div", { class: "deck-side" }, side) : null));
  };
  const parts = groups.map((g, i) => h("section", { class: "deck-part", id: anchor("part-" + i), "aria-label": partName(g.part) },
    h("h3", { class: "deck-ph" }, h("span", { text: partName(g.part) }), h("span", { class: "chip count", text: String(g.items.length) })),
    g.items.map(scene)));
  const stall = d.stall.length ? h("section", { class: "deck-sec paper", id: anchor("stall"), "aria-label": w.stall_title },   // an English interview: the lines that ask again and buy time
    h("h3", { text: w.stall_title }),
    h("div", { class: "deck-stall" }, d.stall.map((x) => h("div", { class: "turn me" }, h("span", { class: "en" }, speech(x.en)), h("span", { class: "hint", text: x.use })))))
    : null;
  return h("section", { class: "ivdeck", "aria-label": w.title || t("Interview deck") }, head, nav, posting, parts, stall);
}

// ---------------------------------------------------------------- the talk's script

function ivRich(text) {                                                             // a line with its **stress** in bold and its ==key phrase== marked, as the printed script draws it
  return String(text || "").split(/(==.+?==|\*\*.+?\*\*)/).filter(Boolean).map((p) =>
    /^==.+==$/.test(p) ? h("mark", { class: "hl" }, ivRich(p.slice(2, -2))) : /^\*\*.+\*\*$/.test(p) ? h("strong", { text: p.slice(2, -2) }) : document.createTextNode(p));
}
function ivTalkScript(j, st) {                                                      // the talk's speaker script, drawn by the panel: the parts' times, then every slide with its picture and its words
  const key = `talks|${j.id}|${st.at || 0}`;                                        // per talk made
  if (!UI.docs[key]) { dropDocs("talks|", key); getDoc(key, `/api/v1/jobs/${enc(j.id)}/talk/script`); }   // asked once per talk
  const d = UI.docs[key];                                                           // what came
  if (!d) return ivWait(null, t("Reading the presentation script…"));               // on its way
  if (d.error) return h("div", { class: "iv-wait card" }, h("p", { class: "hint", role: "status", text: t("The presentation script could not be read.") }));
  if (UI.talkView && UI.talkView.doc === d) return UI.talkView.el;                  // drawn once per talk: a redraw of the panel around it keeps it
  const el = talkScriptView(j, d);
  UI.talkView = { doc: d, el };
  return el;
}
function talkScriptView(j, d) {                                                     // the printed script's parts, in the panel's: paper for what is read, its chips and tables
  const w = d.words || {};                                                          // the script's own words, in the talk's language
  const head = h("header", { class: "ts-head paper" }, h("h3", { text: d.title }), h("p", { class: "sub", text: d.sub }),
    d.notes.map((n) => h("p", { class: "ts-warn", role: "note" }, icon("alert"), h("span", { text: n }))));   // what the checks found
  const top = h("div", { class: "ts-top" },                                         // the parts' times, and how to speak
    h("div", { class: "ts-parts paper" }, h("table", {}, h("thead", {}, h("tr", {}, [w.part, w.pages, w.time, w.run].map((x) => h("th", { scope: "col", text: x })))),
      h("tbody", {}, d.parts.map((r) => h("tr", {}, h("td", { text: r.name }), h("td", { text: r.pages }), h("td", { class: "tm", text: r.time }), h("td", { class: "tm", text: r.run })))))),
    h("div", { class: "ts-tips paper" }, h("h4", { text: w.late }), h("p", { text: w.late_tip }), h("h4", { text: w.speak }), h("p", { text: w.speak_tip })));
  const mark = (label, kind, ...kids) => h("p", { class: "ts-cue" + (kind ? " " + kind : "") }, h("span", { class: "ts-lab", text: label }), kids);   // a labelled line: where to point, when late, what they may ask, as the cards label their fields
  const slide = (s, i) => h("article", { class: "ts-slide paper", "aria-label": `${s.page} ${s.title}` },
    h("div", { class: "ts-l" },
      s.picture ? h("img", { src: `/api/v1/jobs/${enc(j.id)}/talk/slides/${i + 1}.png?v=${d.at || 0}`, alt: "", loading: "lazy", decoding: "async" }) : h("div", { class: "ts-noimg" }),   // the slide as it prints
      h("div", { class: "ts-tm" }, h("b", { text: s.time }), h("span", { text: `${w.run} ${s.run}` }))),   // its time and the running total
    h("div", { class: "ts-r" }, h("h4", {}, h("span", { class: "n", text: String(s.page) }), h("span", { text: s.title })),
      s.cue ? mark(w.point, "", ivRich(s.cue)) : null,
      s.lines.map((x) => h("p", {}, ivRich(x))),                                    // what to say
      s.short ? mark(w.short, "warn", ivRich(s.short)) : null,
      s.ask.map((q) => mark(w.ask, "pc", ivRich(q))),
      s.draft ? mark(w.draft, "ai", w.draft_tip) : null));                           // words made from the slide itself
  const qa = d.qa.length ? h("section", { class: "ts-qa paper", "aria-label": w.qa }, h("h3", { text: w.qa }),
    d.qa.map((q) => h("div", { class: "ts-q" }, h("div", { class: "ts-qh" }, h("b", {}, ivRich(q.q)), h("span", { class: "hint", text: String(w.page || "{n}").replace("{n}", q.page) })),
      h("p", {}, ivRich(q.a))))) : null;
  return h("section", { class: "talkscript", "aria-label": d.title }, head, top, d.slides.map(slide), qa);
}

// ---------------------------------------------------------------- practice

const PR_COUNTS = [5, 8, 12];                                                       // the session lengths offered, as the kit's own page offers them
function ivPractice(j) {                                                            // the job's mock interview: its words and script cards come with the scripts (kit.js)
  const k = ivKitView(j);                                                           // the kit's words and cards
  if (!k) return ivWait(ivKitData(j), t("Opening the interview kit…"));             // on their way
  UI.prac = UI.prac || {};                                                          // one practice per job, kept while the page is open: a detour to the deck resumes where it was
  const p = UI.prac[j.id] || (UI.prac[j.id] = practiceView(j, k));
  const fresh = p.kit !== k; p.kit = k;                                             // the job's scripts as drawn now: their words and their cards (made again when a kit file changed)
  if (fresh || p.lang !== LANG) p.draw();                                           // the panel's language or the scripts changed: its words again
  p.open();                                                                         // asks the kit what it offers, the first time
  return p.el;
}
function practiceView(j, kit0) {                                                    // the practice part of one job: its state, its element and its draw
  const api = `/kit/${enc(j.id)}/api/practice/`;                                    // the job's kit, at the panel's own address (web.py kit_proxy)
  const store = {                                                                   // per-viewer choices, the same names as the kit's own page keeps
    get(k, d) { const v = localStore("offerowl-interview:" + k); return v === null || v === undefined ? d : v; },
    set(k, v) { localStore("offerowl-interview:" + k, String(v)); },
  };
  const PR = {                                                                      // the practice state
    setup: null,                                                                    // what the kit offers: {agent, stt, stt_why, kinds, default_kinds, long_pause, history}
    session: null,                                                                  // the running session: {id, interviewer, questions}
    qi: 0, turn: 0,                                                                 // the question being asked, and 0 for it or the follow-up's number
    ask: "", askKo: "",                                                             // the line being asked now, and its translation when the scene has one
    view: "setup", busy: "",                                                        // setup, ask, busy, feedback, summary; what the page waits for
    fb: null, follow: undefined, said: "", audioUrl: "",                            // the last feedback, its follow-up, the answer, its recording (in this tab only)
    t0: 0, tq: 0,                                                                   // when the session started, when the question appeared or the recording started (ms)
    rec: null,                                                                      // the running recording: {mr, chunks, stream, ctx, levels, timer, type, t0}
    starting: false,                                                                // the browser is opening the microphone
    count: Number(store.get("pr-count", 8)) || 8,                                   // questions per session, remembered
    kinds: null,                                                                    // the kinds chosen, remembered once the kit says which exist
    useAgent: store.get("pr-agent", "1") !== "0",                                   // ask the agent when one is connected, remembered
    error: "", draft: "", pending: null, summary: null,                             // the last error (shown once), the answer being typed, a recording's timing waiting for its words, the summary
  };
  const el = h("section", { class: "ivprac" });                                     // placed by the panel wherever the tab is drawn
  const view = { el, lang: "", draw, open, opened: false, kit: kit0 };              // what ivPractice keeps; kit: the job's scripts (kit.js), set by ivPractice each time it draws the part
  const here = () => UI.view === "jobs" && UI.jobTab === "interview" && UI.ivPart === "practice" && (openJob() || {}).id === j.id;   // this job's practice is the part on screen
  let STR = {};                                                                     // the kit's own words in the panel's language (src/interview/i18n.json), taken at each draw
  const fmt = (key, vars) => String(STR[key] || key).replace(/\{(\w+)\}/g, (m, n) => (vars && vars[n] !== undefined ? vars[n] : m));   // with {name} slots filled
  const clock = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };   // m:ss
  const prQ = () => (PR.session ? PR.session.questions[PR.qi] : null);              // the question being asked
  async function call(path, body) {                                                 // one call to the practice API; JSON in and out
    const opt = body === undefined ? { cache: "no-store" } : { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch(api + path, opt);                                         // through the panel to the job's kit
    const got = await r.json().catch(() => ({}));                                   // an error page is not JSON
    if (!r.ok) throw new Error(got.error || ("HTTP " + r.status));                  // the kit's reason
    return got;
  }
  async function open() {                                                           // the first time the part is shown: what the kit offers
    if (view.opened) return; view.opened = true;
    try { PR.setup = await call("setup"); } catch (e) { PR.error = e.message; view.opened = false; }   // the kit could not be reached: said in the part, and asked again when the part is drawn again
    if (PR.setup && !PR.kinds) {                                                    // the kinds remembered from last time, else the kit's default ones
      const saved = String(store.get("pr-kinds", "") || "").split(",").filter((x) => PR.setup.kinds.includes(x));
      PR.kinds = saved.length ? saved : PR.setup.default_kinds.slice();
    }
    draw();
  }

  // ---- drawing
  const keyBtn = (label, onclick, opts = {}) => h("button", { class: "btn" + (opts.primary ? " primary" : "") + (opts.quiet ? " quiet" : ""), type: "button", disabled: opts.disabled || null, onclick },
    opts.icon ? icon(opts.icon) : null, label);                                     // one of the part's keys
  function draw() {                                                                 // the part for the current view
    view.lang = LANG;                                                               // drawn in this language
    const kit = view.kit;                                                           // the job's scripts as the part last drew them: never made here, so another job's view is never taken
    if (kit && kit.data && kit.data.str) STR = kit.data.str;                        // their words in the panel's language
    const busy = PR.view === "busy";                                                // waiting for the kit
    const head = h("div", { class: "pr-head" }, h("h3", { text: fmt("practice_title") }),   // the title and the two clocks
      h("span", { class: "pr-clock" }, h("span", { class: "k", text: fmt("pr_session_t") }), h("b", { "data-clock": "session", text: PR.t0 ? clock(Date.now() - PR.t0) : "0:00" })),
      h("span", { class: "pr-clock" }, h("span", { class: "k", text: fmt("pr_answer_t") }), h("b", { "data-clock": "answer", text: PR.tq && PR.view === "ask" ? clock(Date.now() - PR.tq) : "0:00" })));
    const note = h("p", { class: "hint", text: fmt("pr_note") });                   // what the microphone does and when the script shows
    const err = PR.error && PR.setup ? h("div", { class: "band", role: "alert" }, h("p", { text: fmt("pr_error", { error: PR.error }) })) : null;   // said once
    let body;                                                                       // the part that changes with the view
    if (PR.error && !PR.setup) body = h("div", { class: "card" }, h("p", { text: t("The interview kit could not start.") }));   // no kit to talk to
    else if (!PR.setup) body = h("div", { class: "card" }, h("p", { class: "hint", role: "status", text: fmt("pr_loading") }));   // still asking
    else if (PR.view === "setup") body = setupCard();                               // choose and start
    else if (busy && !prQ()) body = h("div", { class: "card" }, h("p", { class: "hint", role: "status", text: PR.busy }));   // waiting for the questions themselves
    else if (PR.view === "ask" || busy) body = askCard(busy);                       // the question and the answer keys
    else if (PR.view === "feedback") body = feedbackCard();                         // what the answer was like, then the script
    else body = summaryCard();                                                      // the session's summary
    fill(el, head, note, err, body);
    if (PR.setup) PR.error = "";                                                    // an error is shown once
    if (PR.view === "ask" && !PR.rec && el.isConnected) { const box = el.querySelector("textarea"); if (box && !box.disabled) box.focus({ preventScroll: true }); }   // ready to type
  }
  function setupCard() {                                                            // the choices before a session
    const s = PR.setup;                                                             // what the kit offers
    const sw = s.agent ? h("button", { class: "switch", type: "button", role: "switch", "aria-checked": PR.useAgent ? "true" : "false", "aria-label": fmt("pr_agent", { name: s.agent }),
      onclick: () => { PR.useAgent = !PR.useAgent; store.set("pr-agent", PR.useAgent ? "1" : "0"); draw(); } }) : null;   // the agent asks, or the scripts' own questions
    const row = (label, ...kids) => h("div", { class: "pr-row" }, h("span", { class: "pr-lab", text: label }), h("div", { class: "pr-val" }, kids));   // one setting
    const hist = (s.history || []).length ? h("div", { class: "pr-hist" }, h("h4", { text: fmt("pr_history") }),   // earlier sessions on this PC
      h("table", {}, h("tbody", {}, s.history.map((x) => h("tr", {}, h("td", { text: String(x.started || "").replace("T", " ").slice(0, 16) }),
        h("td", { text: x.interviewer || "" }), h("td", { text: sumLine(x.summary) })))))) : null;
    return h("div", { class: "card pr-setup" },
      row(fmt("pr_interviewer"), sw, h("span", { class: s.agent ? "" : "hint", text: s.agent ? fmt("pr_agent", { name: s.agent }) : fmt("pr_no_agent") })),
      row(fmt("pr_count"), h("div", { class: "seg", role: "group", "aria-label": fmt("pr_count") }, PR_COUNTS.map((n) => h("button", { type: "button", "aria-pressed": PR.count === n ? "true" : "false",
        onclick: () => { PR.count = n; store.set("pr-count", n); draw(); }, text: String(n) })))),
      row(fmt("pr_kinds"), h("div", { class: "seg pr-kinds", role: "group", "aria-label": fmt("pr_kinds") }, s.kinds.map((x) => h("button", { type: "button", "aria-pressed": PR.kinds.includes(x) ? "true" : "false",
        onclick: () => { PR.kinds = PR.kinds.includes(x) ? PR.kinds.filter((y) => y !== x) : PR.kinds.concat(x); if (!PR.kinds.length) PR.kinds = [x]; store.set("pr-kinds", PR.kinds.join(",")); draw(); },   // at least one kind
        text: fmt("kind_" + x) })))),
      h("p", { class: "hint", text: s.stt ? fmt("pr_stt_on") : fmt("pr_stt_off") }),   // whether a spoken answer is written down here
      h("div", { class: "part-keys" }, keyBtn(fmt("pr_start"), start, { primary: true, icon: "mic" })),
      hist);
  }
  function askCard(busy) {                                                          // the question being asked, with the answer keys
    const q = prQ(), n = PR.session.questions.length;                               // the question and how many there are
    const recording = !!PR.rec;                                                     // the microphone is on
    const shut = busy || recording;                                                 // keys that wait while the kit works or the microphone runs
    const rec = recording                                                           // Record, or Stop while recording
      ? [keyBtn(fmt("pr_stop"), stop, { primary: true, disabled: busy, icon: "stop" }), h("span", { class: "pr-meter", "aria-hidden": "true" }, h("span", { "data-level": "1" })), h("span", { class: "hint", role: "status", text: fmt("pr_recording") })]
      : [keyBtn(fmt("pr_record"), record, { disabled: busy || PR.starting, icon: "mic" })];   // held while the browser opens the microphone
    const box = h("textarea", { rows: 5, "data-key": "pr-text-" + j.id, placeholder: fmt("pr_placeholder"), "aria-label": fmt("pr_placeholder"), disabled: shut || null, value: PR.draft || "",
      oninput: (e) => { PR.draft = e.target.value; },                               // the draft survives a redraw
      onkeydown: (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submitTyped(); } } });   // Ctrl+Enter sends a typed answer
    return h("div", { class: "card pr-ask" },
      h("div", { class: "pr-qhead" }, h("span", { class: "chip count", text: fmt("pr_q", { i: PR.qi + 1, n }) }), h("span", { class: "chip pc", text: PR.turn ? fmt("pr_followup") : fmt("kind_" + q.kind) })),
      PR.turn ? null : h("p", { class: "hint pr-topic", text: q.topic }),          // where the question comes from: the posting's line, the resume's
      h("p", { class: "pr-question", text: PR.ask }),                                // as the interviewer asks it
      PR.askKo ? h("details", { class: "pr-ko" }, h("summary", { text: fmt("pr_show_ko") }), h("p", { text: PR.askKo })) : null,   // its translation, folded
      h("div", { class: "part-keys pr-rec" }, rec),
      h("label", { class: "field" }, box),
      h("div", { class: "part-keys" }, keyBtn(fmt("pr_submit"), submitTyped, { primary: true, disabled: shut }), keyBtn(fmt("pr_skip"), next, { disabled: shut }),
        keyBtn(fmt("pr_end"), end, { quiet: true, disabled: shut }), busy ? h("span", { class: "hint", role: "status", text: PR.busy }) : null));
  }
  const depLine = (d) => (d.kind === "claim" ? fmt(d.fact === "claim_team" ? "dep_claim_team" : "dep_claim_new", { said: d.said }) : d.kind === "agent" ? fmt("dep_agent", d) : fmt("dep_" + d.kind, d));   // one departure in words
  function feedbackCard() {                                                         // the feedback on the last answer, what comes next, then the script
    const f = PR.fb.feedback, L = f.length, pct = Math.round(L.ratio * 100);        // the feedback, its length part, the length against the script in percent
    const bar = h("span", { class: "pr-bar", role: "img", "aria-label": fmt("fb_length_line", { words: L.words, target: L.target_words, pct }) },   // the script's length sits in the middle
      h("span", { class: "fill " + L.verdict, style: `width:${Math.min(100, pct / 2)}%` }), h("i", {}));
    const P = f.pauses, F = f.fillers, K = f.key;                                    // the long pauses, the fillers, the key phrase
    const deps = f.departures.concat(((PR.follow && PR.follow.departures) || []).map((d) => ({ kind: "agent", said: d.said, fact: d.fact, why: d.why })));   // the rule's and the agent's
    const row = (label, ...kids) => h("tr", {}, h("th", { scope: "row", text: label }), h("td", {}, kids));
    const scene = PR.fb.scene && view.kit ? view.kit.view.card(PR.fb.scene.id) : null;   // the whole script, drawn as the search view's cards
    const canFollow = PR.follow && PR.follow.followup;                              // a follow-up to answer
    const last = PR.qi + 1 >= PR.session.questions.length;                          // the last question
    return [h("div", { class: "card pr-fb" },
      h("table", { class: "pr-rows" }, h("tbody", {},
        row(fmt("fb_length"), bar, h("div", {}, fmt("fb_length_line", { words: L.words, target: L.target_words, pct }), " ", h("b", { class: "v-" + L.verdict, text: fmt("fb_" + L.verdict) })),
          L.seconds && P.measured ? h("div", { class: "hint", text: fmt("fb_time_line", { s: Math.round(L.seconds), ts: L.target_seconds }) + (L.wpm ? ", " + fmt("fb_wpm", { wpm: L.wpm }) : "") }) : null),
        row(fmt("fb_pauses"), !P.measured ? h("span", { class: "hint", text: fmt("fb_pauses_na") }) : P.count ? fmt("fb_pauses_line", { n: P.count, s: P.longest }) : fmt("fb_none")),
        row(fmt("fb_fillers"), F.count ? fmt("fb_fillers_line", { n: F.count, rate: F.per_min, list: F.used.map(([x, c]) => `${x} ${c}`).join(", ") }) : fmt("fb_none")),
        row(fmt("fb_departures"), deps.length ? h("ul", { class: "pr-deps" }, deps.map((d) => h("li", { text: depLine(d) }))) : fmt("fb_none")),
        row(fmt("fb_key"), !K ? h("span", { class: "hint", text: fmt("fb_key_na") }) : [h("b", { class: K.landed ? "v-ok" : "v-short", text: fmt(K.landed ? "fb_key_landed" : "fb_key_missed") }), " ", h("mark", { class: "hl", text: K.phrase })]),
        row(fmt("fb_said"), h("p", { class: "pr-said", text: PR.said }), PR.audioUrl ? h("audio", { controls: true, src: PR.audioUrl }) : null))),
      PR.follow === null ? h("p", { class: "hint", role: "status", text: fmt("pr_thinking") })   // the next question about this answer
        : canFollow ? h("p", { class: "pr-fu" }, h("span", { class: "chip pc", text: fmt("pr_followup") }), " ", PR.follow.followup) : null,
      h("div", { class: "part-keys" }, canFollow ? keyBtn(fmt("pr_answer_fu"), () => ask(PR.turn + 1, PR.follow.followup, ""), { primary: true }) : null,
        last ? null : keyBtn(fmt("pr_next"), next, { primary: !canFollow }), keyBtn(fmt("pr_end"), end, { primary: last && !canFollow, quiet: !(last && !canFollow) }))),
    h("div", { class: "pr-scene" }, h("h4", { text: fmt("fb_scene") }), scene || h("p", { class: "hint", text: fmt("fb_no_scene") }))];
  }
  function sumLine(s) {                                                             // a session's summary in one line
    if (!s) return "";                                                              // nothing answered yet
    return [fmt("sum_answers", { n: s.answers }), fmt("sum_time", { t: clock((s.answer_seconds || 0) * 1000) }), fmt("sum_ratio", { pct: Math.round((s.ratio_mean || 0) * 100) }),
      fmt("sum_pauses", { n: s.long_pauses }), fmt("sum_fillers", { n: s.fillers }), fmt("sum_departures", { n: s.departures }), fmt("sum_keys", { a: s.keys_landed, b: s.keys_asked })].join(" · ");
  }
  function summaryCard() {                                                          // the end of a session: its summary is kept with the job's earlier sessions
    const s = PR.summary || {};                                                     // {summary, file}
    const ids = [...new Set((PR.session ? PR.session.questions : []).map((q) => q.scene).filter(Boolean))].join(",");   // the scripts of this session
    return h("div", { class: "card pr-sum" }, h("h4", { text: fmt("pr_summary") }), h("p", { text: sumLine(s.summary) }),
      h("div", { class: "part-keys" }, keyBtn(fmt("pr_again"), () => { PR.view = "setup"; PR.session = null; PR.fb = null; PR.t0 = 0; PR.tq = 0; draw(); }, { primary: true }),
        ids ? keyBtn(t("Cue cards to print"), () => openKit(j.id, "cue?ids=" + enc(ids)), { icon: "copy" }) : null));   // these questions' scripts as cue cards
  }

  // ---- the session
  let tick = 0;                                                                     // the timer that moves the clocks
  function clocks() {                                                               // the two clocks, in place: the part is not drawn again for them
    if (!here()) { if (PR.rec) stopRecording(true).then(draw); return; }            // the part was left (another part, tab, view or job): the microphone is never left on
    const a = el.querySelector('[data-clock="session"]'), b = el.querySelector('[data-clock="answer"]');
    if (a && PR.t0) a.textContent = clock(Date.now() - PR.t0);                      // the session so far
    if (b && PR.view === "ask" && PR.tq) b.textContent = clock(Date.now() - PR.tq); // the answer so far
  }
  async function start() {                                                          // Start: the kit picks the questions
    PR.view = "busy"; PR.busy = fmt("pr_loading"); PR.session = { questions: [] }; draw();   // the wait is shown at once
    try { PR.session = await call("start", { n: PR.count, kinds: PR.kinds, agent: PR.useAgent }); }   // phrased by the agent when wanted
    catch (e) { PR.error = e.message; PR.view = "setup"; draw(); return; }
    if (!PR.session.questions.length) { PR.error = fmt("pr_no_questions"); PR.view = "setup"; draw(); return; }   // a kit with no scenes yet
    PR.t0 = Date.now(); PR.qi = 0;                                                  // the session's clock
    const q = PR.session.questions[0]; ask(0, q.ask, q.ask === q.fixed ? q.ask_ko : "");   // the scene's translation fits only the scene's own wording
    clearInterval(tick); tick = setInterval(clocks, 250);                           // the clocks run while practising
  }
  function ask(turn, line, ko) {                                                    // show a question (turn 0) or a follow-up
    PR.turn = turn; PR.ask = line; PR.askKo = ko || ""; PR.view = "ask"; PR.tq = Date.now(); PR.draft = ""; PR.follow = undefined; PR.pending = null;   // a fresh answer
    delete UI.typed["pr-text-" + j.id];                                             // the box starts empty
    if (PR.audioUrl) { URL.revokeObjectURL(PR.audioUrl); PR.audioUrl = ""; }        // the last recording is let go
    draw();
  }
  function submitTyped() {                                                          // Submit: the typed words, with a recording's timing when there was one
    const p = PR.pending; PR.pending = null;
    send(p ? Object.assign({}, p, { text: PR.draft }) : undefined);
  }
  async function send(extra) {                                                      // an answer (typed, or a recording's words) to the kit, then its feedback
    const q = prQ();                                                                // the question
    const text = (extra && extra.text !== undefined ? extra.text : PR.draft || "").trim();   // what was said or typed
    if (!text) { const box = el.querySelector("textarea"); if (box) box.focus(); return; }   // nothing to look at
    const seconds = (extra && extra.seconds) || (Date.now() - PR.tq) / 1000;        // the answer's time
    PR.view = "busy"; PR.busy = fmt("pr_checking"); PR.said = text; draw();         // the wait is shown
    try {
      PR.fb = await call("answer", { sid: PR.session.id, qid: q.qid, turn: PR.turn, question: PR.ask, text, typed: !(extra && extra.spoken), seconds,
        speech_seconds: extra && extra.speech, pauses: extra && extra.pauses ? extra.pauses : (extra && extra.spoken ? [] : null), words: extra && extra.words });   // the rules' feedback
    } catch (e) { PR.error = e.message; PR.view = "ask"; PR.draft = text; draw(); return; }
    PR.view = "feedback"; PR.follow = null; draw();                                 // the feedback at once; the follow-up comes after
    const asked = [PR.session.id, PR.qi, PR.turn];                                  // which answer the follow-up is about
    let fu;                                                                         // the follow-up
    try { fu = await call("followup", { sid: PR.session.id, qid: q.qid, turn: PR.turn }); }   // the agent's (one call) or the script's
    catch (e) { fu = { followup: "", from: "", departures: [] }; }                  // no follow-up is not an error worth stopping for
    if (!PR.session || [PR.session.id, PR.qi, PR.turn].join() !== asked.join() || PR.view !== "feedback") return;   // the person moved on: it belongs to an answer no longer on screen
    PR.follow = fu; draw();
  }
  function next() {                                                                 // the next question of the session
    if (PR.qi + 1 >= PR.session.questions.length) { end(); return; }               // none left
    PR.qi += 1; const q = prQ(); ask(0, q.ask, q.ask === q.fixed ? q.ask_ko : "");
  }
  async function end() {                                                            // Finish: the session is closed and its summary kept
    await stopRecording(true);                                                      // a recording in progress is dropped
    clearInterval(tick);                                                            // the clocks stop
    if (!PR.session || !PR.session.id) { PR.view = "setup"; draw(); return; }       // nothing started
    try { PR.summary = await call("end", { sid: PR.session.id, seconds: (Date.now() - PR.t0) / 1000 }); }   // the summary as kept
    catch (e) { PR.summary = { summary: PR.fb ? PR.fb.summary : null }; }
    PR.view = "summary"; draw();
    try { PR.setup = await call("setup"); } catch (e) { /* the earlier sessions show this one next time */ }
  }

  // ---- recording
  async function record() {                                                         // Record: the microphone, a level meter, and the silences for the pause measure
    if (PR.rec || PR.starting) return;                                              // one recording at a time: a second press while it opens does nothing
    PR.starting = true; draw();                                                     // the key waits while the browser opens the microphone (it asks the first time)
    let stream;                                                                     // the microphone
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch (e) { PR.starting = false; PR.error = fmt("pr_mic_denied"); draw(); return; }   // refused, or a page on another address
    PR.starting = false;
    if (PR.rec || PR.view !== "ask" || !here()) { stream.getTracks().forEach((x) => x.stop()); draw(); return; }   // the part or the question was left while it opened: the microphone goes off at once
    const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((x) => window.MediaRecorder && MediaRecorder.isTypeSupported(x)) || "";   // what this browser records
    const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);    // the recorder
    const chunks = []; mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };   // the recording in pieces
    const ctx = new (window.AudioContext || window.webkitAudioContext)();           // the level meter
    const an = ctx.createAnalyser(); an.fftSize = 2048; ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize); const levels = [];                    // one level per 50 ms
    const timer = setInterval(() => {                                               // the level, every 50 ms
      an.getFloatTimeDomainData(buf); let s = 0; for (const v of buf) s += v * v;   // the frame's energy
      const rms = Math.sqrt(s / buf.length); levels.push(rms);                      // kept for the pause measure
      const bar = el.querySelector("[data-level]"); if (bar) bar.style.width = Math.min(100, rms * 400) + "%";   // the meter
    }, 50);
    PR.rec = { mr, chunks, stream, ctx, levels, timer, type: type || mr.mimeType, t0: Date.now() };
    mr.start(1000); PR.tq = Date.now();                                             // a piece every second; the answer's clock starts with the recording
    draw();
  }
  function pausesOf(levels) {                                                       // silences inside the answer, from the levels: [[start s, length s]], and the voiced span in seconds
    if (levels.length < 10) return { pauses: [], speech: 0 };                       // too short to tell
    const sorted = levels.slice().sort((a, b) => a - b);                            // for the room's noise
    const floor = sorted[Math.floor(sorted.length * 0.2)];                          // the quietest fifth is the room
    const thr = Math.max(0.012, floor * 2.5);                                       // speech is well above it
    const voiced = levels.map((v) => v > thr);                                      // per frame
    const first = voiced.indexOf(true), lastV = voiced.lastIndexOf(true);           // the answer runs from the first to the last voiced frame
    if (first < 0) return { pauses: [], speech: 0 };                                // nothing was said
    const out = []; let run = 0;                                                    // silences of a second or more; the current silent run
    for (let k = first; k <= lastV; k++) {                                          // inside the answer only: the lead-in and the tail are not pauses
      if (!voiced[k]) { run++; continue; }
      if (run * 0.05 >= 1) out.push([+((k - run) * 0.05).toFixed(1), +(run * 0.05).toFixed(1)]);   // a silence of a second or more ended here
      run = 0;
    }
    return { pauses: out, speech: +((lastV - first + 1) * 0.05).toFixed(1) };       // the kit keeps the long ones
  }
  function stopRecording(drop) {                                                    // the microphone off; the recording, or null when dropped
    const r = PR.rec; if (!r) return Promise.resolve(null);                         // nothing recording
    PR.rec = null; clearInterval(r.timer);                                          // the meter stops
    return new Promise((res) => {
      const release = () => { r.stream.getTracks().forEach((x) => x.stop()); try { r.ctx.close(); } catch (_) { /* closed already */ } };   // the microphone is let go at once
      const done = () => res(drop || !r.chunks.length ? null : { blob: new Blob(r.chunks, { type: r.type || "audio/webm" }), levels: r.levels, seconds: (Date.now() - r.t0) / 1000 });
      if (r.mr.state === "inactive") { release(); done(); return; }                // it stopped by itself (the device gone, the permission taken back): its stop would never come
      r.mr.onstop = () => { release(); done(); };                                   // the last piece has come
      try { r.mr.stop(); } catch (e) { release(); res(null); }                      // stopped in between
    });
  }
  async function stop() {                                                           // Stop and submit: written down when a speech model is installed, else typed
    const got = await stopRecording(false); if (!got) { draw(); return; }           // nothing recorded
    const { pauses, speech: spoken } = pausesOf(got.levels);                        // the silences inside the answer
    PR.audioUrl = URL.createObjectURL(got.blob);                                    // to play it back, in this tab only
    if (!PR.setup.stt) { PR.pending = { spoken: true, seconds: got.seconds, speech: spoken, pauses }; PR.view = "ask"; draw(); return; }   // no speech model: the timing is kept, the words are typed
    PR.view = "busy"; PR.busy = fmt("pr_transcribing"); draw();                     // the wait is shown
    let tr = null;                                                                  // the words
    try {
      const r = await fetch(api + "transcribe", { method: "POST", body: got.blob, headers: { "Content-Type": got.blob.type || "audio/webm" } });   // the recording itself
      tr = await r.json(); if (!r.ok) throw new Error(tr.error || "HTTP " + r.status);
    } catch (e) { PR.error = e.message; PR.pending = { spoken: true, seconds: got.seconds, speech: spoken, pauses }; PR.view = "ask"; draw(); return; }   // typed instead
    await send({ text: tr.text || "", spoken: true, seconds: got.seconds, speech: spoken, pauses, words: tr.words });   // the words are the answer
  }
  window.addEventListener("pagehide", () => {                                       // a closed page still closes the session, and never leaves the microphone on
    if (PR.session && PR.session.id && PR.view !== "summary") {                     // a session not yet closed
      try { fetch(api + "end", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sid: PR.session.id, seconds: (Date.now() - PR.t0) / 1000 }) }); }   // keepalive: it goes even as the page does (a beacon went out with no origin in Firefox, which the panel refuses)
      catch (_) { /* the page is going */ }
    }
    stopRecording(true);
  });
  draw();                                                                           // the first look: the kit is asked when the part opens
  return view;
}
