// The panel's words in the person's language. The code is written in English; Korean is a table from the English to
// its own words (i18n/ko.js adds itself to CATALOGS). The language is the one picked in the
// menu (kept in this browser), else `?lang=` in the address, else the browser's: Korean when it lists Korean first.
//
//   t("Keep")                        the word itself, or its translation
//   t("{n} facts found", { n: 3 })   placeholders by name
//   "{name|이/가}" in a Korean entry  the word, then 이 after a final consonant or 가 after a vowel
const SUPPORTED = ["en", "ko"];                                                     // languages with a table
const CATALOGS = {};                                                                // filled by i18n/<lang>.js
function browserLang() {                                                            // the browser's first language
  const first = ((navigator.languages && navigator.languages[0]) || navigator.language || "en").toLowerCase();
  return first.startsWith("ko") ? "ko" : "en";                                     // Korean or English
}
function langPicked() {                                                             // the menu's choice, else "auto"
  try { const v = localStorage.getItem("offerowl-lang"); return SUPPORTED.includes(v) ? v : "auto"; }
  catch (_) { return "auto"; }
}
let LANG = (() => {                                                                 // the language of this page
  let asked = null;                                                                 // ?lang=en or ?lang=ko
  try { asked = new URLSearchParams(location.search).get("lang"); } catch (_) { /* no query */ }
  if (SUPPORTED.includes(asked)) return asked;
  const picked = langPicked();                                                      // the menu's choice
  return picked === "auto" ? browserLang() : picked;
})();
document.documentElement.lang = LANG;                                               // for screen readers and fonts
function particle(word, pair) {                                                     // 이/가 by the last syllable
  const [withFinal, withoutFinal] = pair.split("/");                                // the two forms
  const last = String(word || "").replace(/['"’”]$/, "").replace(/\s*\([^()]*\)\s*$/, "").trim().slice(-1);
  const code = last.charCodeAt(0);                                                  // its code point
  if (!last || code < 0xac00 || code > 0xd7a3) return withFinal;                    // not Hangul: the first form
  const final = (code - 0xac00) % 28;                                               // its final consonant, 0 for none
  if (final === 8 && withFinal === "으로") return withoutFinal;                      // a final ㄹ takes 로: 제출로, 서울로
  return final ? withFinal : withoutFinal;                                          // a final consonant or not
}
function t(text, vars) {                                                            // one translated string
  const table = LANG === "en" ? null : CATALOGS[LANG];                              // English needs no table
  let out = (table && table[text]) || text;                                         // the translation, else the English
  if (vars) {
    out = out.replace(/\{(\w+)(?:\|([^}]+))?\}/g, (whole, key, pair) => {           // {name} and {name|이/가}
      if (!(key in vars)) return whole;                                             // unknown: left as written (the audit finds it)
      const value = String(vars[key]);                                              // the value
      return pair ? value + particle(value, pair) : value;
    });
  }
  return out;
}
function setLang(lang) {                                                            // the menu's choice, kept in this browser
  try { if (lang === "auto") localStorage.removeItem("offerowl-lang"); else localStorage.setItem("offerowl-lang", lang); } catch (_) { /* blocked */ }
  LANG = lang === "auto" ? browserLang() : lang;                                    // in effect now
  document.documentElement.lang = LANG;
}
