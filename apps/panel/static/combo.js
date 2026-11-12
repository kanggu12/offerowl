// The panel's dropdowns, drawn by the panel: a key that shows the choice, and a list of the panel's own under it.
// A browser's own <select> is a grey box with the system's arrow, and its list opens in the system's font and colours
// (gray with white words on Windows in the dark); this is the same control made of what the rest of the panel is made of.
// The <select> stays in the page, hidden, and keeps the value: the views read it and listen to its "change" as before,
// so a view never needs to know the dropdown is drawn here. Every <select> the panes draw is dressed as it appears.
(function () {
  "use strict";
  const MARK = '<svg class="combo-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9.5l6 6 6-6"/></svg>';   // the chevron
  const TICK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';   // the mark on the choice it is on now
  let open = null;                                                                  // { sel, btn, list, at }: the one list open now
  let seq = 0;                                                                      // ids for the lists, so a key can name its own

  function label(sel) {                                                             // the words of the choice it is on now
    const o = sel.options[sel.selectedIndex];                                       // the chosen option
    return o ? (o.dataset.short || o.textContent) : "";                            // its short name on the closed key when it has one (the list shows it whole); nothing chosen: an empty key
  }

  function dress(sel) {                                                             // one <select> becomes a key and a hidden list
    if (sel._combo || sel.closest(".combo")) return;                                // dressed already
    const wrap = document.createElement("span");                                    // the key's own box, where the select stood
    wrap.className = "combo" + (sel.className ? " " + sel.className.replace(/\binput\b/g, "").trim() : "");   // the select's own size classes (sm, fk) carry over
    const btn = document.createElement("button");                                  // the key
    btn.type = "button";
    btn.className = "combo-btn";
    btn.setAttribute("role", "combobox");                                          // a screen reader hears a list to choose from
    btn.setAttribute("aria-haspopup", "listbox");
    btn.setAttribute("aria-expanded", "false");
    const lab = sel.labels && sel.labels[0] ? sel.labels[0] : null;                 // a <label> around it holds its options' words too: only the label's own words name it
    const own = lab ? [...lab.childNodes].filter((n) => n !== sel && !(n.contains && n.contains(sel))).map((n) => n.textContent).join(" ").replace(/\s+/g, " ").trim() : "";
    const name = sel.getAttribute("aria-label") || own;                             // its name, as the select had it
    if (name) btn.setAttribute("aria-label", name);
    if (sel.dataset.key) btn.dataset.key = sel.dataset.key + "-combo";             // found again after a redraw (app.js keyOf)
    btn.innerHTML = '<span class="combo-val"></span>' + MARK;                       // the words, then the chevron
    btn.querySelector(".combo-val").textContent = label(sel);
    btn.disabled = sel.disabled;
    btn.addEventListener("click", (e) => { e.preventDefault(); toggle(sel, btn); });
    btn.addEventListener("keydown", (e) => keys(e, sel, btn));
    sel.insertAdjacentElement("beforebegin", wrap);                                // where the select was
    wrap.append(btn, sel);                                                          // the select stays inside, out of sight
    sel.classList.add("combo-native");                                              // hidden (skin.css), still in the form and the page
    sel.tabIndex = -1;                                                              // the key takes the keyboard instead
    sel._combo = btn;
    sel.addEventListener("change", () => { btn.querySelector(".combo-val").textContent = label(sel); });   // a change made elsewhere shows on the key
  }

  function items(sel) {                                                             // [{group} | {opt, i}] in order: a group's name, then its choices
    const out = [];
    for (const node of sel.children) {
      if (node.tagName === "OPTGROUP") {                                            // a group: its name, then its options
        out.push({ group: node.label });
        for (const o of node.children) out.push({ opt: o, i: [...sel.options].indexOf(o) });
      } else if (node.tagName === "OPTION") out.push({ opt: node, i: [...sel.options].indexOf(node) });
    }
    return out;
  }

  function toggle(sel, btn) {                                                       // open its list, or close it when it is the one open
    if (open && open.sel === sel) return close(true);
    close(false);                                                                   // one list at a time
    const list = document.createElement("ul");                                      // the list, on the page's own surface
    const id = "combo-list-" + (++seq);
    list.id = id;
    list.className = "combo-list";
    list.setAttribute("role", "listbox");
    if (btn.getAttribute("aria-label")) list.setAttribute("aria-label", btn.getAttribute("aria-label"));
    let at = -1;                                                                    // the row the keyboard is on
    for (const it of items(sel)) {
      const li = document.createElement("li");
      if (it.group !== undefined) {                                                 // a group's name: not a choice
        li.className = "combo-group";
        li.setAttribute("role", "presentation");
        li.textContent = it.group;
      } else {
        li.setAttribute("role", "option");
        li.id = id + "-" + it.i;
        li.dataset.i = String(it.i);
        const on = it.i === sel.selectedIndex;                                      // the choice it is on now
        li.setAttribute("aria-selected", on ? "true" : "false");
        if (it.opt.disabled) li.setAttribute("aria-disabled", "true");
        li.innerHTML = '<span class="combo-tick">' + TICK + "</span><span></span>";
        li.lastChild.textContent = it.opt.textContent;
        if (on) at = list.children.length;                                          // the keyboard starts on it
        li.addEventListener("mousedown", (e) => e.preventDefault());                // the key keeps the focus
        li.addEventListener("click", () => pick(li));
      }
      list.append(li);
    }
    document.body.append(list);                                                     // over everything: a pane that scrolls would cut it off
    btn.setAttribute("aria-expanded", "true");
    btn.setAttribute("aria-controls", id);
    open = { sel, btn, list, at: -1 };
    place();
    move(at >= 0 ? at : first());
  }

  function first() { return [...open.list.children].findIndex((li) => li.getAttribute("role") === "option" && !li.hasAttribute("aria-disabled")); }

  function place() {                                                                // under its key, or over it when the window has no room below
    if (!open) return;
    const r = open.btn.getBoundingClientRect(), list = open.list;
    list.style.minWidth = Math.round(r.width) + "px";                               // at least as wide as its key
    list.style.maxHeight = "";
    const h = Math.min(list.scrollHeight, 360), below = innerHeight - r.bottom - 8, above = r.top - 8;
    const up = h > below && above > below;                                          // more room above
    list.style.maxHeight = Math.max(120, Math.min(360, up ? above : below)) + "px";
    list.style.top = up ? "" : Math.round(r.bottom + 4) + "px";
    list.style.bottom = up ? Math.round(innerHeight - r.top + 4) + "px" : "";
    const w = list.offsetWidth;                                                     // its width now it has its words
    list.style.left = Math.round(Math.max(8, Math.min(r.left, innerWidth - w - 8))) + "px";   // lined up with its key, never past the window
    list.classList.toggle("up", up);
  }

  function move(i) {                                                                // the keyboard's row
    if (!open || i < 0) return;
    const rows = [...open.list.children];
    rows.forEach((li, k) => li.classList.toggle("on", k === i));
    open.at = i;
    if (rows[i]) { open.btn.setAttribute("aria-activedescendant", rows[i].id); rows[i].scrollIntoView({ block: "nearest" }); }
  }

  function step(d) {                                                                // the next choice up or down, past group names and disabled rows
    const rows = [...open.list.children];
    let i = open.at;
    for (let n = 0; n < rows.length; n++) {
      i = (i + d + rows.length) % rows.length;
      if (rows[i].getAttribute("role") === "option" && !rows[i].hasAttribute("aria-disabled")) return move(i);
    }
  }

  function pick(li) {                                                               // the choice made: the select takes it and says so, as a click on it would
    if (!open || !li || li.hasAttribute("aria-disabled")) return;
    const { sel, btn } = open;
    const i = Number(li.dataset.i);
    close(true);
    if (sel.selectedIndex !== i) {
      sel.selectedIndex = i;
      btn.querySelector(".combo-val").textContent = label(sel);
      sel.dispatchEvent(new Event("input", { bubbles: true }));
      sel.dispatchEvent(new Event("change", { bubbles: true }));                    // the view's own onchange runs
    }
  }

  function close(focus) {                                                           // the list away; the keyboard back on its key
    if (!open) return;
    const { btn, list } = open;
    list.remove();
    btn.setAttribute("aria-expanded", "false");
    btn.removeAttribute("aria-activedescendant");
    open = null;
    if (focus && btn.isConnected) btn.focus({ preventScroll: true });
  }

  function keys(e, sel, btn) {                                                      // the keyboard on a key
    if (!open || open.sel !== sel) {                                                // closed: these open it
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); toggle(sel, btn); }
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    else if (e.key === "Home") { e.preventDefault(); move(first()); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(open.list.children[open.at]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (e.key === "Tab") close(false);                                         // focus moves on; the list does not stay behind
  }

  document.addEventListener("mousedown", (e) => {                                   // a click anywhere else closes the list
    if (open && !open.list.contains(e.target) && !open.btn.contains(e.target)) close(false);
  }, true);
  addEventListener("resize", () => close(false));                                   // the window changed: the list would point at the wrong place
  addEventListener("scroll", (e) => { if (open && !open.list.contains(e.target)) place(); }, true);   // the page moved under it: it follows its key

  const seen = new MutationObserver(() => {                                         // the panes draw again: dress every new select, and let go of a list whose key is gone
    for (const sel of document.querySelectorAll("select:not(.combo-native)")) dress(sel);
    if (open && !open.btn.isConnected) close(false);
    for (const sel of document.querySelectorAll("select.combo-native")) {           // a redraw may keep the select and change its value or options
      if (!sel._combo) continue;
      const v = sel._combo.querySelector(".combo-val"), now = label(sel);
      if (v.textContent !== now) v.textContent = now;                               // only when it changed: writing the same words is a change this observer would see again
      if (sel._combo.disabled !== sel.disabled) sel._combo.disabled = sel.disabled;
    }
  });
  window.comboDress = (root) => { for (const sel of (root || document).querySelectorAll("select:not(.combo-native)")) dress(sel); };   // app.js dresses a pane right after drawing it, before the keyboard goes back
  function start() {
    for (const sel of document.querySelectorAll("select")) dress(sel);
    seen.observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
