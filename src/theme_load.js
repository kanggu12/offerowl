// One loader for the color sets, so that the docx and the deck load and validate them in the same way (separate loaders
// once failed in three different ways on the same file). It adds the sets of OFFEROWL_THEME_FILE to the built-in sets of
// src/themes.json, or overrides sets of the same name, and strips a leading '#' from values. A missing required field
// or an unknown set name stops with a message that says what is wrong. layout.js (the resume) and portfolio/deck.js
// (the deck) use it; the figure script (overview_figures.py) reads the same files in Python.
const fs = require("fs"); // file access

const REQUIRED = ["nameFill", "nameText", "sec", "rule", "band", "bandText", "head", "headText", "key", "acc"]; // the fields the resume uses
const HEX = /^[0-9A-Fa-f]{6}$/; // shape of a color value

function clean(name, t) {
  if (!t || typeof t !== "object") throw new Error(`colour set '${name}' is not an object`);
  const out = {};
  for (const [k, v] of Object.entries(t)) {
    if (k.startsWith("_")) continue;                                  // comment field
    const x = String(v).replace(/^#/, "").toUpperCase();              // '#1D5C63' is accepted too
    if (!HEX.test(x)) throw new Error(`colour set '${name}': the value of ${k} is not a colour: ${v}`);
    out[k] = x;
  }
  const miss = REQUIRED.filter(k => !out[k]);
  if (miss.length) throw new Error(`colour set '${name}' lacks: ${miss.join(", ")}`);
  return out;
}

function load() {
  const base = require("./themes.json");
  const user = process.env.OFFEROWL_THEME_FILE ? JSON.parse(fs.readFileSync(process.env.OFFEROWL_THEME_FILE, "utf-8")) : {};
  const all = {};
  for (const [k, v] of Object.entries({ ...base, ...user })) if (!k.startsWith("_")) all[k] = clean(k, v);
  return all;
}

const THEMES = load();
// One set by name. An unknown name stops with the list of names that can be chosen
function theme(name) {
  if (!THEMES[name]) throw new Error(`unknown colour set '${name}' (the sets: ${Object.keys(THEMES).join(", ")})`);
  return THEMES[name];
}

module.exports = { THEMES, theme, fromFile: !!process.env.OFFEROWL_THEME_FILE };
