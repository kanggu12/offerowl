// The theme before the first paint, so the page never flashes the wrong one. "auto" follows the system and is kept
// as a choice like the other two; it is written out as what the system says now, so every rule that names a theme
// holds for it too. Storage may be blocked: then it follows the system.
const AUTO_THEME = window.matchMedia("(prefers-color-scheme: dark)");             // the system's choice
function themePicked() {                                                            // what this browser chose last
  try { const t = localStorage.getItem("offerowl-theme"); return t === "light" || t === "dark" ? t : "auto"; }
  catch (_) { return "auto"; }                                                      // storage blocked
}
function applyTheme(choice) {                                                       // write the theme on <html>
  const c = choice || themePicked();                                                // the choice
  document.documentElement.dataset.theme = c === "auto" ? (AUTO_THEME.matches ? "dark" : "light") : c;  // resolved
  document.documentElement.dataset.themeChoice = c;                                 // what the menu shows as picked
}
applyTheme();                                                                       // now, before anything draws
AUTO_THEME.addEventListener?.("change", () => { if (themePicked() === "auto") applyTheme("auto"); });  // the system turned over
// Motion, before the first paint too: on unless the menu turned it off. "auto" follows the system's request for less;
// it is not the default, because a system set that way would hide every motion the panel has (Sidenote learned this).
const LESS_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");          // the system's request
function motionPicked() {                                                           // on, auto or off, as this browser chose
  try { const m = localStorage.getItem("offerowl-motion"); return m === "off" || m === "auto" ? m : "on"; }
  catch (_) { return "on"; }                                                        // storage blocked: on
}
function applyMotion(choice) {                                                      // write it on <html>
  const m = choice || motionPicked();                                               // the choice
  document.documentElement.dataset.motion = m === "off" || (m === "auto" && LESS_MOTION.matches) ? "off" : "on";   // resolved
  document.documentElement.dataset.motionChoice = m;                                // what the menu shows as picked
}
applyMotion();                                                                      // now, before anything draws
LESS_MOTION.addEventListener?.("change", () => applyMotion());                      // the system changed while open
