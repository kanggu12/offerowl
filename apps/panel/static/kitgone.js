// The page of the interview kit that is not there (apps/api/web.py missing_page): its words in the language the person chose
// in the panel (i18n.js reads the choice kept in this browser), so it never reads half in one language and half in another.
"use strict";
const GONE = { head: t("This page of the interview kit is not there."), back: t("Open the Interview tab"),   // the page's words, by their place (web.py MISSING)
  talk: t("No presentation made yet."), scripts: t("No script to print yet.") };   // the talk before it is made, the deck and cue cards before the first script
document.querySelectorAll("[data-w]").forEach((el) => { if (GONE[el.dataset.w]) el.textContent = GONE[el.dataset.w]; });   // each in the person's language
document.title = t("{company} interview kit", { company: document.body.dataset.company || "Offerowl" });   // the tab says whose kit it is
