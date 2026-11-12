// Practice mode of the search view (docs/INTERVIEW.md, "Practice mode"). The server inlines this file into page.html.
// The microphone is used only between Record and Stop, and the feedback and the script appear only after an answer is
// given. It talks to /api/practice/* on the server that served the page (practice.py).
"use strict";

const PR = {  // the practice state, kept while the page is open, so a detour to the search view resumes where it was
  setup: null,  // what the server offers: {agent, stt, stt_why, kinds, default_kinds, long_pause, history}
  session: null,  // the running session: {id, interviewer, questions}
  qi: 0,  // the question being asked
  turn: 0,  // 0 for the question itself, then the follow-ups
  ask: "",  // the line being asked now
  askKo: "",  // its translation, when the scene has one
  view: "setup",  // setup, ask, busy, feedback, summary
  busy: "",  // what the page waits for, shown while busy
  fb: null,  // the last feedback: {feedback, scene, summary}
  follow: null,  // the follow-up after the last answer: {followup, from, departures}
  said: "",  // the last answer's text
  audioUrl: "",  // the last recording, for playing it back (stays in this tab)
  t0: 0,  // when the session started (ms)
  tq: 0,  // when the current question appeared or the recording started (ms)
  rec: null,  // the running recording: {mr, chunks, stream, ctx, an, levels, timer}
  count: Number(store.get("pr-count", 8)) || 8,  // questions per session, remembered
  kinds: null,  // the kinds chosen, remembered once the server says which exist
  useAgent: store.get("pr-agent", "1") !== "0",  // ask the agent when one is connected, remembered
  error: "",  // the last error, shown once
  draft: "",  // the answer being typed, kept across redraws
  pending: null,  // a recording's timing waiting for its typed words (no speech model)
  summary: null,  // the closed session's summary: {summary, file}
};
const PR_COUNTS = [5, 8, 12];  // the session lengths offered
let prTick = 0;  // the timer that redraws the clocks

async function prApi(path, body) {  // one call to the practice API; JSON in and out
  const opt = body === undefined ? { cache: "no-store" } : { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(API + "api/practice/" + path, opt);  // the server that served the page (a saved copy moves to it first)
  const j = await r.json().catch(() => ({}));  // an error page is not JSON
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));  // the server's reason
  return j;
}
const clock = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };  // m:ss
const prQ = () => (PR.session ? PR.session.questions[PR.qi] : null);  // the question being asked

async function openPractice() {  // the Practice key in the bar, or #practice in the address
  mode = "practice"; groupName = null; current = ""; $("#q").value = "";  // the search view steps aside
  show();  // draws the practice pane
  if (!PR.setup) {  // first visit: ask the server what it offers
    try { PR.setup = await prApi("setup"); } catch (e) { PR.error = location.protocol.startsWith("http") ? e.message : fmt("pr_no_server"); }
    if (PR.setup && !PR.kinds) {  // the kinds remembered from last time, else the default ones
      const saved = (store.get("pr-kinds", "") || "").split(",").filter((k) => PR.setup.kinds.includes(k));
      PR.kinds = saved.length ? saved : PR.setup.default_kinds.slice();
    }
    drawPractice();  // with what the server said
  }
}

function drawPractice() {  // the practice pane for the current view
  const el = $("#practicePane"); if (!el) return;
  const busy = PR.view === "busy";  // waiting for the server
  const head = `<div class="pr-head"><h2>${esc(fmt("practice_title"))}</h2>` +
    `<span class="pr-clock" title="${esc(fmt("pr_session_t"))}"><span class="lb">${esc(fmt("pr_session_t"))}</span> <b id="prSession">${PR.t0 ? clock(Date.now() - PR.t0) : "0:00"}</b></span>` +
    `<span class="pr-clock" title="${esc(fmt("pr_answer_t"))}"><span class="lb">${esc(fmt("pr_answer_t"))}</span> <b id="prAnswer">${PR.tq && PR.view === "ask" ? clock(Date.now() - PR.tq) : "0:00"}</b></span></div>`;  // the title and the two clocks
  let body = "";  // the part that changes with the view
  if (PR.error && !PR.setup) body = `<div class="pr-card"><p>${esc(PR.error)}</p></div>`;  // no server: say why
  else if (!PR.setup) body = `<div class="pr-card"><p class="pr-dim">${esc(fmt("pr_loading"))}</p></div>`;  // still asking
  else if (PR.view === "setup") body = prSetupHtml();  // choose and start
  else if (busy && !prQ()) body = `<div class="pr-card"><p class="pr-dim pr-wait">${esc(PR.busy)}</p></div>`;  // waiting for the questions themselves
  else if (PR.view === "ask" || busy) body = prAskHtml(busy);  // the question and the answer controls
  else if (PR.view === "feedback") body = prFeedbackHtml();  // what the answer was like
  else body = prSummaryHtml();  // the session's summary
  el.innerHTML = `<div class="pr-wrap">${head}${PR.error && PR.setup ? `<p class="pr-err">${esc(fmt("pr_error", { error: PR.error }))}</p>` : ""}${body}</div>`;
  PR.error = PR.setup ? "" : PR.error;  // an error is shown once
  if (PR.view === "ask") { const t = $("#prText"); if (t && !PR.rec) t.focus({ preventScroll: true }); }  // ready to type
}

const PR_NAMES = { "claude-code": "Claude Code", codex: "Codex" };  // the agents by the names their makers give them
function prWho(id) {  // who asked a session's questions, in words: an agent by its name, never its setting's id
  return id === "fixed" ? fmt("pr_fixed") : id === "openai-compat" ? fmt("pr_local") : PR_NAMES[id] || id || "";
}

function prSetupHtml() {  // the choices before a session
  const s = PR.setup;  // what the server offers
  const who = s.agent ? fmt("pr_agent", { name: prWho(s.agent) }) : fmt("pr_fixed");  // who asks the questions, by its name
  const kinds = s.kinds.map((k) => `<button type="button" data-kind="${esc(k)}" class="${PR.kinds.includes(k) ? "on" : ""}">${esc(fmt("kind_" + k))}</button>`).join("");  // one toggle per kind
  const counts = PR_COUNTS.map((n) => `<button type="button" data-count="${n}" class="${PR.count === n ? "on" : ""}">${n}</button>`).join("");  // the session lengths
  const agent = s.agent ? `<label class="pr-sw"><input type="checkbox" id="prAgent"${PR.useAgent ? " checked" : ""}> ${esc(who)}</label>` : `<span class="pr-dim">${esc(fmt("pr_no_agent"))}</span>`;  // the agent switch, or why there is none
  const hist = (s.history || []).length ? `<h3>${esc(fmt("pr_history"))}</h3><table class="pr-hist">${s.history.map((h) => `<tr><td>${esc(String(h.started || "").replace("T", " ").slice(0, 16))}</td><td>${esc(prWho(h.interviewer))}</td><td>${esc(prSumLine(h.summary))}</td></tr>`).join("")}</table>` : "";  // earlier sessions on this PC
  return `<div class="pr-card pr-setup">` +
    `<div class="pr-row"><span class="pr-lab">${esc(fmt("pr_interviewer"))}</span>${agent}</div>` +
    `<div class="pr-row"><span class="pr-lab">${esc(fmt("pr_count"))}</span><div class="seg" id="prCounts">${counts}</div></div>` +
    `<div class="pr-row"><span class="pr-lab">${esc(fmt("pr_kinds"))}</span><div class="seg pr-kinds" id="prKinds">${kinds}</div></div>` +
    `<p class="pr-dim">${esc(s.stt ? fmt("pr_stt_on") : fmt("pr_stt_off"))}</p>` +
    `<div class="pr-actions"><button type="button" class="pr-key pr-go" id="prStart">${esc(fmt("pr_start"))}</button></div>${hist}</div>`;
}

function prAskHtml(busy) {  // the question being asked, with the answer controls
  const q = prQ(); const n = PR.session.questions.length;  // the question and how many there are
  const kind = PR.turn ? fmt("pr_followup") : fmt("kind_" + q.kind);  // what kind of question this is
  const topic = PR.turn || !q.topic ? "" : `<p class="pr-topic">${esc(q.topic)}</p>`;  // where the question comes from (the posting line, the resume line; an earlier round's question is its own)
  const ko = PR.askKo ? `<details class="pr-ko"><summary>${esc(fmt("pr_show_ko"))}</summary><p>${esc(PR.askKo)}</p></details>` : "";  // the translation, folded
  const recording = !!PR.rec;  // the microphone is on
  const rec = recording ? `<button type="button" class="pr-key pr-stop" id="prStop"${busy ? " disabled" : ""}><span class="pr-dot"></span>${esc(fmt("pr_stop"))}</button><span class="pr-meter"><span id="prLevel"></span></span><span class="pr-dim">${esc(fmt("pr_recording"))}</span>`
    : `<button type="button" class="pr-key" id="prRecord"${busy ? " disabled" : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>${esc(fmt("pr_record"))}</button>`;  // Record, or Stop while recording
  return `<div class="pr-card pr-ask"><div class="pr-qhead"><span class="pr-chip">${esc(fmt("pr_q", { i: PR.qi + 1, n }))}</span><span class="pr-chip pr-kind">${esc(kind)}</span></div>` +
    `${topic}<p class="pr-question">${esc(PR.ask)}</p>${ko}` +
    `<div class="pr-actions">${rec}</div>` +
    `<textarea id="prText" rows="4" placeholder="${esc(fmt("pr_placeholder"))}"${busy || recording ? " disabled" : ""}>${esc(PR.draft || "")}</textarea>` +
    `<div class="pr-actions"><button type="button" class="pr-key pr-go" id="prSubmit"${busy || recording ? " disabled" : ""}>${esc(fmt("pr_submit"))}</button>` +
    `<button type="button" class="pr-key" id="prSkip"${busy || recording ? " disabled" : ""}>${esc(fmt("pr_skip"))}</button>` +
    `<button type="button" class="pr-key" id="prEnd"${busy || recording ? " disabled" : ""}>${esc(fmt("pr_end"))}</button>` +
    `${busy ? `<span class="pr-dim pr-wait">${esc(PR.busy)}</span>` : ""}</div></div>`;
}

function prDepLine(d) {  // one departure in words
  if (d.kind === "claim") return fmt(d.fact === "claim_team" ? "dep_claim_team" : "dep_claim_new", { said: d.said });  // a claim stronger than the script
  if (d.kind === "agent") return fmt("dep_agent", d);  // the agent's, with both quotes
  return fmt("dep_" + d.kind, d);  // changed, number or name
}

function prFeedbackHtml() {  // the feedback on the last answer, the script, and what comes next
  const f = PR.fb.feedback; const L = f.length;  // the feedback and its length part
  const pct = Math.round(L.ratio * 100);  // length against the script, in percent
  const bar = `<span class="pr-bar"><span style="width:${Math.min(100, pct / 2)}%" class="${L.verdict}"></span><i style="left:50%"></i></span>`;  // 100 percent sits in the middle
  const len = `${esc(fmt("fb_length_line", { words: L.words, target: L.target_words, pct }))} <b class="v-${L.verdict}">${esc(fmt("fb_" + L.verdict))}</b>` +
    (L.seconds && f.pauses.measured ? `<br><span class="pr-dim">${esc(fmt("fb_time_line", { s: Math.round(L.seconds), ts: L.target_seconds }))}${L.wpm ? ", " + esc(fmt("fb_wpm", { wpm: L.wpm })) : ""}</span>` : "");  // words, and time when spoken
  const P = f.pauses;  // the long pauses
  const pauses = !P.measured ? `<span class="pr-dim">${esc(fmt("fb_pauses_na"))}</span>` : P.count ? esc(fmt("fb_pauses_line", { n: P.count, s: P.longest })) : esc(fmt("fb_none"));  // measured or not
  const F = f.fillers;  // the fillers
  const fillers = F.count ? esc(fmt("fb_fillers_line", { n: F.count, rate: F.per_min, list: F.used.map(([w, c]) => `${w} ${c}`).join(", ") })) : esc(fmt("fb_none"));  // which ones, how often
  const deps = f.departures.concat(((PR.follow && PR.follow.departures) || []).map((d) => ({ kind: "agent", said: d.said, fact: d.fact, why: d.why })));  // the rule's and the agent's
  const depHtml = deps.length ? `<ul class="pr-deps">${deps.map((d) => `<li>${esc(prDepLine(d))}</li>`).join("")}</ul>` : esc(fmt("fb_none"));  // one line each
  const K = f.key;  // the key phrase of this turn
  const key = !K ? `<span class="pr-dim">${esc(fmt("fb_key_na"))}</span>` : `<b class="${K.landed ? "v-ok" : "v-short"}">${esc(fmt(K.landed ? "fb_key_landed" : "fb_key_missed"))}</b> <mark class="hl">${esc(K.phrase)}</mark>`;  // landed or missed, and the phrase
  const scene = PR.fb.scene && BY_ID.has(PR.fb.scene.id) ? cardHtml({ i: BY_ID.get(PR.fb.scene.id), score: 0, kn: 0, dn: 0, sim: null, why: null }, 1) : `<p class="pr-dim">${esc(fmt("fb_no_scene"))}</p>`;  // the whole script, drawn like the board's cards
  const fu = PR.follow === null ? `<span class="pr-dim pr-wait">${esc(fmt("pr_thinking"))}</span>` : PR.follow.followup ? `<p class="pr-fu"><span class="pr-chip pr-kind">${esc(fmt("pr_followup"))}</span> ${esc(PR.follow.followup)}</p>` : "";  // the next question about this answer
  const canFollow = PR.follow && PR.follow.followup;  // there is a follow-up to answer
  const last = PR.qi + 1 >= PR.session.questions.length;  // the last question
  return `<div class="pr-card pr-fb"><table class="pr-rows">` +
    `<tr><th>${esc(fmt("fb_length"))}</th><td>${bar}<div>${len}</div></td></tr>` +
    `<tr><th>${esc(fmt("fb_pauses"))}</th><td>${pauses}</td></tr>` +
    `<tr><th>${esc(fmt("fb_fillers"))}</th><td>${fillers}</td></tr>` +
    `<tr><th>${esc(fmt("fb_departures"))}</th><td>${depHtml}</td></tr>` +
    `<tr><th>${esc(fmt("fb_key"))}</th><td>${key}</td></tr>` +
    `<tr><th>${esc(fmt("fb_said"))}</th><td><p class="pr-said">${esc(PR.said)}</p>${PR.audioUrl ? `<audio controls src="${PR.audioUrl}"></audio>` : ""}</td></tr></table>` +
    `${fu}<div class="pr-actions">${canFollow ? `<button type="button" class="pr-key pr-go" id="prFollow">${esc(fmt("pr_answer_fu"))}</button>` : ""}` +
    `${last ? "" : `<button type="button" class="pr-key${canFollow ? "" : " pr-go"}" id="prNext">${esc(fmt("pr_next"))}</button>`}` +
    `<button type="button" class="pr-key${last && !canFollow ? " pr-go" : ""}" id="prEnd">${esc(fmt("pr_end"))}</button></div></div>` +
    `<div class="pr-scene"><h3>${esc(fmt("fb_scene"))}</h3><div class="cards lang-${lang} pr-cards">${scene}</div></div>`;
}

function prSumLine(s) {  // a session's summary in one line
  if (!s) return "";  // nothing answered yet
  return [fmt("sum_answers", { n: s.answers }), fmt("sum_time", { t: clock((s.answer_seconds || 0) * 1000) }), fmt("sum_ratio", { pct: Math.round((s.ratio_mean || 0) * 100) }),
    fmt("sum_pauses", { n: s.long_pauses }), fmt("sum_fillers", { n: s.fillers }), fmt("sum_departures", { n: s.departures }), fmt("sum_keys", { a: s.keys_landed, b: s.keys_asked })].join(" · ");
}

function prSummaryHtml() {  // the end of a session
  const s = PR.summary || {};  // {summary, file}
  const ids = [...new Set((PR.session ? PR.session.questions : []).map((q) => q.scene))].join(",");  // the scenes of this session
  return `<div class="pr-card"><h3>${esc(fmt("pr_summary"))}</h3><p class="pr-sum">${esc(prSumLine(s.summary))}</p>` +
    `${s.file ? `<p class="pr-dim">${esc(fmt("pr_saved", { file: s.file }))}</p>` : ""}` +
    `<div class="pr-actions"><button type="button" class="pr-key pr-go" id="prAgain">${esc(fmt("pr_again"))}</button>` +
    `${ids ? `<a class="pr-key" href="${API}cue?ids=${encodeURIComponent(ids)}" target="_blank" rel="noopener" title="${esc(fmt("pr_cue_title"))}">${esc(fmt("pr_cue"))}</a>` : ""}</div></div>`;
}

// ---------- the session ----------

async function prStart() {  // Start: ask the server for the questions
  PR.view = "busy"; PR.busy = fmt("pr_loading"); PR.session = { questions: [] }; drawPractice();  // the wait is shown at once
  try {
    PR.session = await prApi("start", { n: PR.count, kinds: PR.kinds, agent: PR.useAgent });  // the questions, phrased by the agent when wanted
  } catch (e) { PR.error = e.message; PR.view = "setup"; drawPractice(); return; }
  if (!PR.session.questions.length) { PR.error = fmt("pr_no_questions"); PR.view = "setup"; drawPractice(); return; }  // a kit with no scenes yet
  PR.t0 = Date.now(); PR.qi = 0; prAsk(0, PR.session.questions[0].ask, PR.session.questions[0].ask === PR.session.questions[0].fixed ? PR.session.questions[0].ask_ko : "");  // the first question
  clearInterval(prTick); prTick = setInterval(prClocks, 250);  // the clocks run while practising
}
function prAsk(turn, line, ko) {  // show a question (turn 0) or a follow-up
  PR.turn = turn; PR.ask = line; PR.askKo = ko || ""; PR.view = "ask"; PR.tq = Date.now(); PR.draft = ""; PR.follow = undefined;  // a fresh answer
  if (PR.audioUrl) { URL.revokeObjectURL(PR.audioUrl); PR.audioUrl = ""; }  // the last recording is let go
  drawPractice();
}
function prClocks() {  // redraw the two clocks without redrawing the pane
  if (mode !== "practice") return;  // nothing to redraw while away
  const a = $("#prSession"), b = $("#prAnswer");  // the two readings
  if (a && PR.t0) a.textContent = clock(Date.now() - PR.t0);  // the session so far
  if (b) b.textContent = PR.view === "ask" && PR.tq ? clock(Date.now() - PR.tq) : b.textContent;  // the answer so far
}

async function prSubmit(extra) {  // send an answer (typed, or the transcript of a recording) and show the feedback
  const q = prQ(); const t = $("#prText");  // the question and the answer box
  const text = (extra && extra.text !== undefined ? extra.text : (t ? t.value : "")).trim();  // what was said or typed
  if (!text) { if (t) t.focus(); return; }  // nothing to check
  const seconds = (extra && extra.seconds) || (Date.now() - PR.tq) / 1000;  // the answer's time
  PR.view = "busy"; PR.busy = fmt("pr_checking"); PR.said = text; drawPractice();  // the wait is shown
  try {
    PR.fb = await prApi("answer", { sid: PR.session.id, qid: q.qid, turn: PR.turn, question: PR.ask, text, typed: !(extra && extra.spoken), seconds,
      speech_seconds: extra && extra.speech, pauses: extra && extra.pauses ? extra.pauses : (extra && extra.spoken ? [] : null), words: extra && extra.words });  // the rule-made feedback
  } catch (e) { PR.error = e.message; PR.view = "ask"; PR.draft = text; drawPractice(); return; }
  PR.view = "feedback"; PR.follow = null; drawPractice();  // the feedback at once; the follow-up comes after
  try { PR.follow = await prApi("followup", { sid: PR.session.id, qid: q.qid, turn: PR.turn }); }  // the agent's (one call) or the script's
  catch (e) { PR.follow = { followup: "", from: "", departures: [] }; }  // no follow-up is not an error worth stopping for
  if (mode === "practice" && PR.view === "feedback") drawPractice();  // drawn unless the page moved on
}
function prNext() {  // the next question of the session
  if (PR.qi + 1 >= PR.session.questions.length) { prEnd(); return; }  // none left
  PR.qi += 1; const q = prQ();  // the next one
  prAsk(0, q.ask, q.ask === q.fixed ? q.ask_ko : "");  // the scene's translation fits only the scene's own wording
}
async function prEnd() {  // Finish: close the session and show its summary
  prStopRecording(true);  // a recording in progress is dropped
  clearInterval(prTick);  // the clocks stop
  if (!PR.session || !PR.session.id) { PR.view = "setup"; drawPractice(); return; }  // nothing started
  try { PR.summary = await prApi("end", { sid: PR.session.id, seconds: (Date.now() - PR.t0) / 1000 }); } catch (e) { PR.summary = { summary: PR.fb ? PR.fb.summary : null }; }  // the saved summary
  PR.view = "summary"; drawPractice();
  try { PR.setup = await prApi("setup"); } catch (e) { /* the history refreshes next time */ }  // the history now holds this session
}

// ---------- recording ----------

async function prRecord() {  // Record: the microphone, a level meter, and the silences for the pause measure
  let stream;  // the microphone
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }  // asks for permission the first time
  catch (e) { PR.error = fmt("pr_mic_denied"); drawPractice(); return; }  // denied, or no secure context (a page on another address)
  const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";  // what this browser records
  const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);  // the recorder
  const chunks = []; mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };  // the recording in pieces
  const ctx = new (window.AudioContext || window.webkitAudioContext)();  // the level meter
  const an = ctx.createAnalyser(); an.fftSize = 2048; ctx.createMediaStreamSource(stream).connect(an);  // reads the microphone level
  const buf = new Float32Array(an.fftSize); const levels = [];  // one level per 50 ms frame
  const timer = setInterval(() => {  // the level every 50 ms
    an.getFloatTimeDomainData(buf); let s = 0; for (const v of buf) s += v * v;  // the frame's energy
    const rms = Math.sqrt(s / buf.length); levels.push(rms);  // kept for the pause measure
    const bar = $("#prLevel"); if (bar) bar.style.width = Math.min(100, rms * 400) + "%";  // the meter
  }, 50);
  PR.rec = { mr, chunks, stream, ctx, an, levels, timer, type: type || mr.mimeType, t0: Date.now() };  // the running recording
  mr.start(1000); PR.tq = Date.now();  // a piece every second; the answer clock starts with the recording
  drawPractice();
}
function prPauses(levels) {  // silences inside the answer, from the levels: [[start s, length s]], and the voiced span in seconds
  if (levels.length < 10) return { pauses: [], speech: 0 };  // too short to tell
  const sorted = levels.slice().sort((a, b) => a - b);  // for the noise floor
  const floor = sorted[Math.floor(sorted.length * 0.2)];  // the quietest fifth is the room
  const thr = Math.max(0.012, floor * 2.5);  // speech is well above the room
  const voiced = levels.map((v) => v > thr);  // per frame
  const first = voiced.indexOf(true), lastV = voiced.lastIndexOf(true);  // the answer runs from the first to the last voiced frame
  if (first < 0) return { pauses: [], speech: 0 };  // nothing was said
  const out = []; let run = 0;  // silences of a second or more; the current silent run
  for (let k = first; k <= lastV; k++) {  // inside the answer only: the lead-in and the tail are not pauses
    if (!voiced[k]) { run++; continue; }  // still silent
    if (run * 0.05 >= 1) out.push([+((k - run) * 0.05).toFixed(1), +(run * 0.05).toFixed(1)]);  // a silence of a second or more ended here
    run = 0;
  }
  return { pauses: out, speech: +((lastV - first + 1) * 0.05).toFixed(1) };  // the server keeps the long ones
}
function prStopRecording(drop) {  // stop the microphone; returns a promise of the recording, or null when dropped
  const r = PR.rec; if (!r) return Promise.resolve(null);  // nothing recording
  PR.rec = null; clearInterval(r.timer);  // the meter stops
  return new Promise((res) => {
    r.mr.onstop = () => {  // the last piece has arrived
      r.stream.getTracks().forEach((t) => t.stop()); r.ctx.close();  // the microphone is released at once
      res(drop ? null : { blob: new Blob(r.chunks, { type: r.type || "audio/webm" }), levels: r.levels, seconds: (Date.now() - r.t0) / 1000 });
    };
    try { r.mr.stop(); } catch (e) { res(null); }  // already stopped
  });
}
async function prStop() {  // Stop and submit: transcribe when a speech model is installed, else ask for the words
  const got = await prStopRecording(false); if (!got) { drawPractice(); return; }  // nothing recorded
  const { pauses, speech } = prPauses(got.levels);  // the silences inside the answer
  PR.audioUrl = URL.createObjectURL(got.blob);  // for playing it back, in this tab only
  if (!PR.setup.stt) {  // no speech model: the timing is kept and the words are typed
    PR.pending = { spoken: true, seconds: got.seconds, speech, pauses }; PR.view = "ask"; drawPractice();
    const t = $("#prText"); if (t) { t.disabled = false; t.focus(); } return;
  }
  PR.view = "busy"; PR.busy = fmt("pr_transcribing"); drawPractice();  // the wait is shown
  let tr = null;  // the transcript
  try {
    const r = await fetch(API + "api/practice/transcribe", { method: "POST", body: got.blob, headers: { "Content-Type": got.blob.type || "audio/webm" } });  // the recording, raw
    tr = await r.json(); if (!r.ok) throw new Error(tr.error || "HTTP " + r.status);
  } catch (e) { PR.error = e.message; PR.pending = { spoken: true, seconds: got.seconds, speech, pauses }; PR.view = "ask"; drawPractice(); return; }  // type it instead
  await prSubmit({ text: tr.text || "", spoken: true, seconds: got.seconds, speech, pauses, words: tr.words });  // the transcript is the answer
}

// ---------- events ----------

$("#practicePane").addEventListener("click", (e) => {  // every key of the pane
  const b = e.target.closest("button"); if (!b || b.disabled) return;  // only enabled keys
  if (b.dataset.kind) {  // a kind toggled
    const k = b.dataset.kind; PR.kinds = PR.kinds.includes(k) ? PR.kinds.filter((x) => x !== k) : PR.kinds.concat(k);  // on or off
    if (!PR.kinds.length) PR.kinds = [k];  // at least one kind
    store.set("pr-kinds", PR.kinds.join(",")); drawPractice(); return;
  }
  if (b.dataset.count) { PR.count = Number(b.dataset.count); store.set("pr-count", PR.count); drawPractice(); return; }  // a session length
  const id = b.id;  // the key's job
  if (id === "prStart") prStart();
  else if (id === "prRecord") prRecord();
  else if (id === "prStop") prStop();
  else if (id === "prSubmit") { const p = PR.pending; PR.pending = null; prSubmit(p ? Object.assign({}, p, { text: $("#prText").value }) : undefined); }  // a typed answer, with the recording's timing when there was one
  else if (id === "prSkip") prNext();
  else if (id === "prNext") prNext();
  else if (id === "prFollow") prAsk(PR.turn + 1, PR.follow.followup, "");
  else if (id === "prEnd") prEnd();
  else if (id === "prAgain") { PR.view = "setup"; PR.session = null; PR.fb = null; PR.t0 = 0; PR.tq = 0; drawPractice(); }
});
$("#practicePane").addEventListener("change", (e) => {  // the agent switch
  if (e.target.id === "prAgent") { PR.useAgent = e.target.checked; store.set("pr-agent", PR.useAgent ? "1" : "0"); }
});
$("#practicePane").addEventListener("input", (e) => { if (e.target.id === "prText") PR.draft = e.target.value; });  // the draft survives a redraw
$("#practicePane").addEventListener("keydown", (e) => {  // Ctrl+Enter submits a typed answer
  if (e.target.id === "prText" && e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("#prSubmit").click(); }
});
$("#practiceBtn").addEventListener("click", () => { if (mode === "practice") goHome(); else openPractice(); });  // the bar key toggles practice
window.addEventListener("pagehide", () => {  // a closed tab still records the session's end
  if (PR.session && PR.session.id && PR.view !== "summary" && navigator.sendBeacon) navigator.sendBeacon(API + "api/practice/end", JSON.stringify({ sid: PR.session.id, seconds: (Date.now() - PR.t0) / 1000 }));
  prStopRecording(true);  // the microphone is never left on
});
if (location.hash === "#practice") openPractice();  // the panel's link opens practice directly
