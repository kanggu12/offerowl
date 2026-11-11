// Offerowl's panel, small figures: what a count already says, drawn so it reads at a glance. Each figure draws only the
// numbers the view already has and keeps their words beside it (the legend), so nothing is said by the picture alone.
// The bars stand up once when they are new or their numbers change (motion.js, vizMotion); nothing moves at rest.
"use strict";                                                                       // catches undeclared names and silent writes early

// A bar of parts, each as wide as its count, and a legend of the same parts with their words and numbers.
// parts: [{ n, words, color, key }]; opts: { label, id, total, compact }. A part of 0 keeps its place in the legend only.
function segBar(parts, opts = {}) {
  const sum = opts.total || parts.reduce((s, p) => s + (p.n || 0), 0);              // what the bar's full length stands for
  const words = parts.map((p) => `${p.words} ${p.n}`).join(", ");                   // the whole figure in words, for a screen reader
  const fig = h("figure", { class: "viz segbar" + (opts.compact ? " compact" : ""), role: "img", "aria-label": (opts.label ? opts.label + ": " : "") + words,
    "data-viz": (opts.id || opts.label || "bar") + ":" + parts.map((p) => p.n).join("/") });   // its name and numbers: motion.js plays it again when they change
  const track = h("div", { class: "vb-track", "aria-hidden": "true" },              // the bar
    sum ? parts.filter((p) => p.n > 0).map((p) => h("span", { class: "vb-seg", style: `flex-grow:${p.n};--c:${p.color}`, title: `${p.words} ${p.n}` }))
      : h("span", { class: "vb-empty" }));                                          // nothing yet: an empty track, not a missing figure
  const legend = h("div", { class: "vb-legend", "aria-hidden": "true" }, parts.map((p) =>   // the same parts in words
    h("span", { class: "vb-key" + (p.n ? "" : " zero"), style: `--c:${p.color}` }, h("i", {}), h("span", { text: p.words }), h("b", { text: opts.unit ? opts.unit(p.n) : String(p.n) }))));   // a count with its unit where the bar's own name does not say it
  fig.append(track, legend);
  return fig;
}

// The stages of the applications as one bar: preparing, submitted, interview, result.
function stageBar(jobs, opts = {}) {
  const n = (st) => jobs.filter((j) => j.stage === st).length;                      // how many in a stage
  return segBar((S.stages || ["preparing", "submitted", "interview", "result"]).map((st) => ({ n: n(st), words: t(STAGE[st]), color: `var(--stage-${st})` })),
    { label: t("Applications by stage"), id: "stages", ...opts });
}
