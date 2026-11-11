// Offerowl's panel, motion. Nothing moves at rest, and nothing loops but what is at work (a lamp while a step runs).
// What moves says what just changed, once: a view opens and its cards rise in turn, a step ends and its lamp pops, the
// run's bar goes on to its new length, a run's documents arrive and their tiles rise, a figure counts to its value and
// the call bars stand up, a switch's knob travels, the open job's bookmark drops, a menu opens. The page draws itself
// again on every poll, so nothing here is a CSS animation on an element that a redraw makes anew: each one is played
// once with the Web Animations API, after the draw, and only when what it shows is new.
// On by default. The menu's Motion turns it off, or makes it follow the system (theme.js sets data-motion before the
// first paint, and CSS stops every transition when it is off).
"use strict";                                                                       // catches undeclared names and silent writes early

const EASE = "cubic-bezier(.22, .61, .36, 1)";                                      // the panel's curve (tokens.css --ease)
const SPRING = "cubic-bezier(.34, 1.56, .64, 1)";                                   // a little past, then back: a knob, a lamp
const SEEN = { view: null, tab: null, made: false, steps: new Set(), runs: null, pct: null, figs: null, bars: null, ribbon: null, menu: false, pop: false, knobs: new Map(),
  viz: new Set(), jobTab: null, ivPart: null };                                    // what has been shown: the figures by their numbers, the application's tab, the interview's part

function moving() {                                                                 // motion on now
  return document.documentElement.dataset.motion !== "off";                        // theme.js resolved the choice
}
function play(el, frames, opts) {                                                   // one animation, never in the way of a click or a layout
  if (!moving() || !el || !el.animate) return null;                                 // off, or a browser without the API
  return el.animate(frames, { easing: EASE, fill: "backwards", ...opts });          // backwards: it starts where it begins, even when delayed
}
function riseIn(els, step = 45) {                                                   // cards that rise in turn
  [...els].slice(0, 24).forEach((el, i) => play(el, [{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }], { duration: 380, delay: Math.min(i, 9) * step }));
}
function numberOf(text) {                                                           // "25.6 s" -> [25.6, "", " s"], "314k" -> [314, "", "k"], "1,234" -> [1234, ...]
  const m = String(text).match(/^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$/);                 // a prefix, the number, the rest
  if (!m) return null;                                                              // no number in it
  return { pre: m[1], n: parseFloat(m[2].replace(/,/g, "")), places: (m[2].split(".")[1] || "").length, post: m[3], comma: m[2].includes(",") };
}
function countTo(el, from) {                                                        // a figure counts from where it was to what it is now
  const to = numberOf(el.textContent);                                              // the value drawn
  if (!moving() || !to || !isFinite(from) || from === to.n) return;                 // nothing to count
  const text = el.textContent, t0 = performance.now(), ms = 700;                    // the final words, the start, how long
  const show = (v) => { const s = v.toFixed(to.places); el.textContent = to.pre + (to.comma ? Number(s).toLocaleString("en-US", { minimumFractionDigits: to.places }) : s) + to.post; };
  const step = (now) => {                                                           // one frame
    if (!el.isConnected) return;                                                    // drawn again meanwhile: the new one is right
    const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);             // eased toward the end
    if (k < 1) { show(from + (to.n - from) * e); requestAnimationFrame(step); } else el.textContent = text;   // the exact words at the end
  };
  show(from); requestAnimationFrame(step);                                          // from the old value
}
function keepPhase(root) {                                                          // a lamp that pulses goes on pulsing through a redraw, rather than starting over
  for (const el of root.querySelectorAll(".pill.busy, .lit.busy")) el.style.setProperty("--ph", `-${Date.now() % 1200}ms`);
}

const BLOCKS = ".rhead, .card.chain, .active-card, .flow-col > .colhead, .flow-cards > .card, .viewsheet, .facts-sheet, .joblist, .jobdetail, .col, .jobs-viz, .dochead, .pagewrap, .ins-persona, .ins-kpi, .ins-grid > .ins-tile, .lib-top, .lib-table";   // what rises when a view opens
function afterDraw(el, name) {                                                      // drawPane calls this after it draws a pane
  keepPhase(el);                                                                    // lamps first: they show at once
  if (name === "bar") return barMotion(el);                                         // the bar's own
  if (name !== "canvas") return vizMotion(el);                                      // the inspector: its figures only
  if (SEEN.view !== UI.view) {                                                      // a view opened: its blocks rise in turn, once
    SEEN.view = UI.view;                                                            // remembered
    play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 180 });                  // the view itself
    SEEN.viz.clear();                                                               // its figures stand up again with it
    riseIn(el.querySelectorAll(BLOCKS), 35);                                        // then its blocks, one after another
    countIn(el);                                                                    // and its figures count up to their values
  } else if (UI.view === "jobs" && (SEEN.jobTab !== UI.jobTab || SEEN.ivPart !== UI.ivPart)) {   // an application's other tab, or the interview's other part
    const body = el.querySelector(".jd-body, .jobdetail");                          // what changed
    if (body && SEEN.jobTab !== null) play(body, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 240 });
  }
  SEEN.jobTab = UI.jobTab; SEEN.ivPart = UI.ivPart;                                 // remembered
  vizMotion(el);                                                                    // the figures that are new or changed
  landMotion(el);                                                                   // a card just moved on the board
  if (UI.view === "make") makeMotion(el);                                           // the run's own
  ribbonMotion(el);                                                                 // the open job's bookmark
}

function makeMotion(el) {                                                           // the make view: steps, the bar, the tiles, the figures
  const r = task("autopilot"), run = r.started || r.run || 0;                       // the run in progress or last (a queued run has a start of its own)
  const first = !SEEN.made;                                                         // the page's first look at Make: what is there was there
  SEEN.made = true;
  for (const li of el.querySelectorAll(".stepper li.ok")) {                         // each step done
    const key = `${run}:${li.dataset.step}`;                                        // this run's step
    if (SEEN.steps.has(key)) continue;                                              // shown before
    if (!first && moving() && li.animate)                                           // done since the page opened: its lamp lights with a little weight
      li.animate([{ transform: "scale(.2)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 360, easing: SPRING, pseudoElement: "::before" });
    SEEN.steps.add(key);                                                            // remembered
  }
  const bar = el.querySelector(".meter i");                                         // the run's bar
  if (bar) {
    const pct = parseFloat(bar.style.width) || 0;                                   // its length now
    if (!first && SEEN.pct !== null && pct !== SEEN.pct) play(bar, [{ width: SEEN.pct + "%" }, { width: pct + "%" }], { duration: 600, fill: "none" });   // on from where it was
    SEEN.pct = pct;
  }
  const runs = (S.runs || []).map((x) => x.at).join();                              // the runs listed
  if (SEEN.runs === null) SEEN.runs = runs;                                         // the page's first look: they were there already
  else if (runs !== SEEN.runs) {                                                    // a run ended since: its documents arrive
    SEEN.runs = runs;
    riseIn(el.querySelectorAll(".tiles:not(.ghost) > .tile"), 60);                  // tile by tile
  }
  const figs = [...el.querySelectorAll(".agentcard .usage-top .stat b")];           // the agent's figures
  const now = figs.map((b) => b.textContent).join("|");                             // as drawn
  if (now !== SEEN.figs) {                                                          // first drawn, or changed
    const was = SEEN.figs === null ? null : SEEN.figs.split("|");                   // the old values
    figs.forEach((b, i) => { const old = was ? numberOf(was[i]) : { n: 0 }; if (!was || was[i] !== b.textContent) countTo(b, old ? old.n : 0); });
    SEEN.figs = now;
  }
}

function ribbonMotion(el) {                                                         // the bookmark falls onto the job opened
  const rib = el.querySelector(".ribbon");                                          // the open job's
  const key = rib ? (rib.closest("[data-job]") || {}).dataset?.job || S.job : null;  // which job
  if (rib && SEEN.ribbon !== null && key !== SEEN.ribbon) play(rib, [{ transform: "translateY(-105%)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 380, easing: "cubic-bezier(.3, 1.35, .6, 1)" });
  SEEN.ribbon = key;
}

function barMotion(el) {                                                            // the bar: the menu and the agent's panel open, a switch's knob travels
  const tab = el.querySelector('.views [aria-current="page"]');                     // the view's key
  if (tab && SEEN.tab !== UI.view && tab.parentElement.scrollWidth > tab.parentElement.clientWidth)   // on a phone the row of views scrolls: the view comes into it
    tab.scrollIntoView({ block: "nearest", inline: "nearest", behavior: moving() ? "smooth" : "auto" });
  SEEN.tab = UI.view;
  const menu = el.querySelector(".menu"), pop = el.querySelector(".pop");           // open now
  if (menu && !SEEN.menu) play(menu, [{ opacity: 0, transform: "translateY(-6px) scale(.98)" }, { opacity: 1, transform: "none" }], { duration: 170 });
  if (pop && !SEEN.pop) play(pop, [{ opacity: 0, transform: "translateY(-6px) scale(.98)" }, { opacity: 1, transform: "none" }], { duration: 170 });
  SEEN.menu = !!menu; SEEN.pop = !!pop;                                             // remembered
  knobMotion(el);
}
function knobMotion(root) {                                                         // a switch drawn in its new place travels there from the old one
  for (const sw of root.querySelectorAll(".switch[aria-label]")) {                  // each switch, by its name
    const name = sw.getAttribute("aria-label"), on = sw.getAttribute("aria-checked") === "true";
    const was = SEEN.knobs.get(name);                                               // as drawn before
    if (was !== undefined && was !== on && moving() && sw.animate)                  // turned since: the knob slides with a little weight
      sw.animate([{ transform: `translateX(${on ? 0 : 16}px)` }, { transform: `translateX(${on ? 16 : 0}px)` }], { duration: 260, easing: SPRING, pseudoElement: "::after" });
    SEEN.knobs.set(name, on);
  }
}

function countIn(el) {                                                              // a view's figures count up from nothing when it opens
  for (const b of el.querySelectorAll(".chain-n, .ps-n, .rhead-facts .figs em, .ins-kpi-n")) countTo(b, 0);
}
function vizMotion(el) {                                                            // a figure's bars stand up when they are new or their numbers changed, once
  for (const fig of el.querySelectorAll(".viz[data-viz], .ins-tile[data-viz], .ins-persona[data-viz]")) {
    const key = fig.dataset.viz;                                                    // its name and numbers
    if (SEEN.viz.has(key)) continue;                                                // shown with these numbers before
    SEEN.viz.add(key);
    fig.querySelectorAll(".vb-seg, .fn-bar, .ar-bar i, .pa-bar i, .rd-seg i, .lane .mk, .ins-mini i").forEach((seg, i) =>   // part by part, from the left
      play(seg, [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], { duration: 520, delay: 60 + Math.min(i, 14) * 45 }));
    fig.querySelectorAll(".col .mk").forEach((seg, i) =>                            // a week's column, from the axis up
      play(seg, [{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }], { duration: 460, delay: 60 + Math.min(i, 14) * 40 }));
    fig.querySelectorAll(".dot circle.mk").forEach((dot, i) =>                       // a dot of the map or the strip, settling in
      play(dot, [{ opacity: 0, transform: "scale(.3)" }, { opacity: 1, transform: "none" }], { duration: 340, delay: 80 + Math.min(i, 16) * 30 }));
  }
}
function landMotion(el) {                                                           // a card dropped into another column settles there
  if (!UI.justMoved) return;
  const card = el.querySelector(`.tcard[data-job="${CSS.escape(UI.justMoved)}"]`);  // where it went
  UI.justMoved = null;                                                              // once
  if (card) play(card, [{ opacity: .4, transform: "translateY(-8px) scale(.98)" }, { opacity: 1, transform: "none" }], { duration: 320, easing: SPRING });
}
