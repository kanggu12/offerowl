// Offerowl's panel, the Library view: every file the person brought in and every file Offerowl made, in one table.
// Filter it by what a file is (brought in for the profile, for an application, made, sent, the interview kit), by whose
// it is, or by its name; open a file, copy it to the Desktop, or remove it. The list and the routes each row can call
// come from GET /api/v1/library, so the table offers only what the server can do, and a program can do the same.
// The Trash lists what was removed (GET /api/v1/removed), to put back or delete for good, and the folders a backup's
// restore kept beside the workspace.
"use strict";                                                                       // catches undeclared names and silent writes early

const LIB_GROUPS = [["all", "All", "list"], ["source", "Your files", "upload"], ["input", "Application files", "case"], ["made", "Made", "file"], ["sent", "Sent", "lock"], ["kit", "Interview kits", "mic"]];
const LIB_COLOR = { source: "var(--blue)", input: "var(--violet)", made: "var(--green)", sent: "var(--amber)", kit: "var(--orange)" };   // each kind's mark, as in the legend
const LIB_KIND_ICON = { pdf: "file", md: "edit", txt: "edit", json: "list", png: "person", jpg: "person", posting: "link", questions: "chat", html: "globe", pptx: "slides", docx: "file" };
const LIB_KIND_WORD = { md: "Markdown", txt: "Text", json: "JSON", html: "Web page", pdf: "PDF", pptx: "Slides", docx: "Word", png: "Picture", jpg: "Picture", py: "Code" };   // a file's kind in words
// rows to a page: as many as the window holds under the Library's head (a row is 54 px), so a tall screen is not left two
// thirds empty under 14 rows and a short one does not scroll; 8 at the least, 40 at the most
const libPageSize = () => Math.max(8, Math.min(40, Math.floor((innerHeight - 464) / 54)));   // 464 px of head, filters, pager and the foot kept clear of the AI prompt (measured)
const TRASH_ICON = { source: "upload", photo: "person", job: "case", edition: "file", material: "file", aside: "folder" };   // a removed thing's mark, by what it was
const trashKind = (k) => ({ source: t("Your file"), photo: t("Resume photo"), job: t("Application"), edition: t("Edition"), material: t("Application file"),
  aside: t("Workspace before a restore") }[k] || t("File"));                           // what it was, in words

function libraryDoc() {                                                             // the list, fetched again only when the files changed
  const key = "library|" + JSON.stringify([(S.facts || {}).rev, S.history, S.undo_id, (S.materials || []).map((m) => m.id + m.state), S.photo, (S.jobs || []).map((j) => [j.id, j.kit, j.locked && j.locked.folder, (j.materials || []).length,
    Object.values(j.builds || {}).map((b) => b.at).join()]), (S.editions || []).map((e) => Object.values(e.builds || {}).map((b) => b.at).join()), ((S.general || {}).builds && Object.values(S.general.builds).map((b) => b.at).join())]);
  if (!UI.docs[key]) {                                                              // a new list to fetch: the old one goes, and stays drawn until the new arrives
    for (const k of Object.keys(UI.docs)) if (k.startsWith("library|") && k !== key && k !== UI.libKey) delete UI.docs[k];
    getDoc(key, "/api/v1/library");
  }
  if (UI.docs[key] && !UI.docs[key].error) UI.libKey = key;
  return UI.docs[key] || (UI.libKey && UI.docs[UI.libKey]) || null;                 // the last list while a new one loads
}

function bytes(n) {                                                                 // a size in the unit that reads best
  if (!n) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB";
}
function ownerWords(o) {                                                            // whose a file is, in words
  if (!o) return t("Profile");
  if (o.job) return o.company + (o.role ? "\u00a0· " + o.role : "");               // the dot stays with the company: a wrapped line never opens with it
  return o.name || t("General edition");
}
function rowWords(r) {                                                              // what a row is, beyond its name
  const n = r.note || {};
  const lang = r.lang ? (r.lang === "ko" ? t("Korean") : t("English")) : "";
  if (r.group === "source") return n.photo ? t("Resume photo") : n.error ? t("Could not be read") : t("{n} facts", { n: n.facts || 0 });
  if (r.kind === "posting") return t("{n} characters", { n: (n.chars || 0).toLocaleString() });
  if (r.kind === "questions") return t("{a} of {n} answered", { a: n.answered || 0, n: n.total || 0 });
  if (r.group === "made") return [lang, n.count ? (r.name === "deck.pdf" ? t("{n} slides", { n: n.count }) : t("{n} pages", { n: n.count })) : "", n.stale ? t("older than your facts") : ""].filter(Boolean).join(" · ");
  if (r.group === "sent") return [lang, "sha256 " + (n.sha256 || "")].filter(Boolean).join(" · ");
  if (r.group === "kit") return n.made ? t("Made from the kit") : r.kind === "json" ? t("The kit's settings") : t("Kit note");   // a kit's JSON is how it is set up, not a note
  return t(LIB_KIND_WORD[r.kind] || r.kind || "");
}
function fileName(r) {                                                              // a file's name as a person reads it
  const words = { "resume.pdf": "Resume", "deck.pdf": "Portfolio deck", "cover.pdf": "Cover letter", "posting.md": "Posting", questions: "Form questions" }[r.name];
  return words ? t(words) : r.name;
}

async function libDo(r, what) {                                                     // a row's action: the route the list named
  if (what === "export") {
    const a = await act(r.export.path, r.export.body);                              // copied to the Desktop
    const names = a ? [].concat(a.exported || []).map((x) => String(x).split(/[\\/]/).pop()).filter(Boolean) : [];
    if (a) toast(names.length ? t("On the Desktop: {name}", { name: names.join(", ") }) : t("Nothing was copied."), null, names.length ? "done" : "info");
    return;
  }
  if (what === "remove") {                                                          // removed at once, never asked: it waits in the Trash
    if (r.remove.undo) return removeAct(r.remove.path, r.remove.body, t("Removed {name}.", { name: fileName(r) }));   // its note holds Undo
    const a = await act(r.remove.path, r.remove.body);                              // the photo: no undo step (a picture is no text)
    if (a) toast(t("Removed {name}.", { name: fileName(r) }), a.removed ? { words: t("Undo"), run: () => act("/api/v1/removed/restore", { id: a.removed }, t("Put back.")) } : null);   // the answer names it in the Trash, which puts it back
  }
}

// ---------------------------------------------------------------- the Trash
function trashForget() { for (const k of Object.keys(UI.docs)) if (k.startsWith("trash|")) delete UI.docs[k]; UI.trashKey = null; UI.trashVer = (UI.trashVer || 0) + 1; render(); }   // read the list again: a folder deleted, or a refusal that found the list out of date, changes no count
function trashDoc() {                                                               // what was removed, fetched again when the Trash or the history changed
  const key = "trash|" + JSON.stringify([S.removed, S.undo_id, S.history, UI.trashVer || 0]);
  if (!UI.docs[key]) {                                                              // a new list to fetch: the old one stays drawn until it arrives
    for (const k of Object.keys(UI.docs)) if (k.startsWith("trash|") && k !== key && k !== UI.trashKey) delete UI.docs[k];
    getDoc(key, "/api/v1/removed");
  }
  if (UI.docs[key] && !UI.docs[key].error) UI.trashKey = key;
  return UI.docs[key] || (UI.trashKey && UI.docs[UI.trashKey]) || null;
}
const trashCount = () => (S.removed && S.removed.all) || 0;                         // what the Trash holds, from the state: no fetch for a count
function openTrash() { UI.libGroup = "trash"; UI.libPage = 0; UI.libQuery = ""; go("library"); }   // the Library, on its Trash
function trashLine(n, words) {                                                      // a quiet key where things were removed: how many wait in the Trash
  return n ? h("button", { class: "btn small quiet trash-line", type: "button", onclick: openTrash }, icon("trash"), words) : null;
}
function trashName(r) { return r.kind === "photo" ? t("Resume photo") : r.name; }    // a removed thing's name as a person reads it
function trashWhat(r) {                                                             // what it was, under its name
  const kind = trashKind(r.kind);
  return r.kind === "job" && (r.note || {}).role ? kind + " · " + r.note.role : kind;   // an application says its role too
}
function trashWhose(r) {                                                            // whose it was: an application's file names it, a file of the profile says so
  if (r.kind === "material" && r.owner) return h("span", { class: "trash-own" }, mono(r.owner.company, "sm"), h("span", { text: r.owner.company }));
  if (r.kind === "source" || r.kind === "photo") return h("span", { class: "trash-own" }, h("span", { class: "lib-ownic", "aria-hidden": "true" }, icon("person")), h("span", { text: t("Profile") }));
  return h("span", { class: "lib-slot", "aria-hidden": "true" });                   // an application or an edition is its own
}
function trashAbout(r) {                                                            // what comes back with it
  const n = r.note || {};
  if (r.kind === "source") return n.facts ? t("{n} facts", { n: n.facts }) : t(LIB_KIND_WORD[n.ext] || "File");
  if (r.kind === "job") return n.stage ? t(STAGE[n.stage] || n.stage) : "";
  if (r.kind === "aside") return n.more ? t("More than this") : "";
  return t(LIB_KIND_WORD[n.ext] || "");
}
function goneWords(r) {                                                             // what deleting it for good takes, in one sentence
  return ({ source: t("The file and the facts read from it are deleted, also from the history, so undo cannot bring them back."),
    photo: t("The photo is deleted."), job: t("Its posting, documents, files, interview kit and progress are deleted, also from the history, so undo cannot bring them back."),
    edition: t("Its documents are deleted, also from the history, so undo cannot bring them back."), material: t("The file is deleted, also from the history, so undo cannot bring it back."),
    aside: t("The whole folder is deleted: your workspace as it was before that restore.") }[r.kind]) || t("It is deleted.");
}
function staysLines(sources) {                                                      // what deleting for good never touches, said before it happens
  return [sources ? t("Documents and drafts already made from its facts, and the details it filled in, stay as they are.") : null,   // a file of the profile fed other documents; an application's own go with it
    t("Copies on your Desktop and backups you saved stay as they are."), t("The command bar's history stays until you clear it there.")].filter(Boolean);
}
async function trashDo(r, what) {                                                   // put back, or delete for good once the person agrees
  if (what === "restore") {
    const j = await act(r.restore.path, r.restore.body);                            // back where it was; one undo step takes it off again
    if (!j) { trashForget(); return; }                                              // refused: the list is read again, so it shows how things are
    if (j.read_again) toast(t("{name} is back. Read it again to bring back its facts.", { name: trashName(r) }),   // its facts could not come back whole
      { words: t("Read it"), icon: "refresh", run: () => act("/api/v1/materials/read", { ids: [j.source] }, t("Reading it…"), "info") }, "warn");   // back, but its facts not whole: a note that asks for care
    else toast(t("{name} is back.", { name: trashName(r) }), j.step ? { words: t("Undo"), run: () => undoOnly(j.step) } : null);   // its note takes it back to the Trash (the photo makes no step)
    return;
  }
  const ok = await askFirst({ title: t("Delete {name} for good?", { name: trashName(r) }), text: goneWords(r), ok: t("Delete for good"), danger: true,
    lines: ["photo", "aside"].includes(r.kind) ? null : staysLines(r.kind === "source") });
  if (!ok) return;
  const j = await act(r.delete.path, r.delete.body);                                // gone, also from the undo steps
  trashForget();                                                                    // read again: a folder kept aside counts nowhere, so no count would say it went
  if (j) toast(t("{name} was deleted for good.", { name: trashName(r) }), null, "done");
}
async function emptyTrash(rows) {                                                   // every row of the Trash for good, once the person agrees (the asides one by one)
  const n = rows.length;                                                            // what goes
  const ok = await askFirst({ title: t("Empty the trash?"), ok: t("Delete all for good"), danger: true, lines: staysLines(rows.some((r) => r.kind === "source")),
    text: tn(n, "{n} thing is deleted for good, also from the history, so undo cannot bring it back.", "{n} things are deleted for good, also from the history, so undo cannot bring them back.") });
  if (!ok) return;
  const j = await act("/api/v1/removed/delete", { all: true });
  trashForget();                                                                    // read again, whatever the answer
  if (j) toast(tn((j.deleted || []).length, "{n} thing was deleted for good.", "{n} things were deleted for good."), null, "done");
}
function trashRow(r) {                                                              // one removed thing: its name, what it was, the day it went, and its two keys
  const ic = TRASH_ICON[r.kind] || "folder";                                       // its mark, in grey
  const name = trashName(r);
  return h("div", { class: "lib-row trash-row", role: "row", "data-kind": r.kind },
    h("span", { class: "lib-file", role: "cell" }, h("span", { class: "lib-ic trash-ic", "aria-hidden": "true" }, icon(ic)),
      h("span", { class: "lib-name" }, h("b", { text: name, title: r.name }), h("small", { text: trashWhat(r) }))),
    h("span", { class: "lib-own", role: "cell" }, trashWhose(r)),
    h("span", { class: "lib-about", role: "cell", text: trashAbout(r) }),
    h("span", { class: "lib-size", role: "cell", text: bytes(r.size) }),
    h("span", { class: "lib-date", role: "cell", title: r.at || t("Before the day was kept"), text: r.at ? [shortDay(r.at), hourOf(r.at)].filter(Boolean).join(" ") : "–" }),   // the day and hour it went: many go on one day; one removed by an older Offerowl has none
    h("span", { class: "lib-keys trash-keys", role: "cell" },
      r.restore ? h("button", { class: "btn small", type: "button", "data-key": "put-back-" + r.id, "aria-label": t("Put {name} back", { name }), onclick: () => trashDo(r, "restore") }, icon("restore"), h("span", { text: t("Put back") }))
        : h("span", { class: "lib-slot", "aria-hidden": "true" }),
      h("button", { class: "btn small danger", type: "button", "data-key": "delete-" + r.id, "aria-label": t("Delete {name} for good", { name }), onclick: () => trashDo(r, "delete") }, icon("trash"), h("span", { text: t("Delete for good") }))));
}
function viewTrash(d, q, setUI) {                                                  // the Trash in the Library's table, and the folders restores kept aside
  if (!d) return h("div", { class: "lib-table", "aria-busy": "true" }, h("p", { class: "ins-none", text: t("Listing what you removed…") }));
  if (d.error) return h("p", { class: "ins-none", text: t("The list could not be read.") });
  const rows = (d.rows || []).filter((r) => !q || [trashName(r), trashWhat(r), trashAbout(r), r.name].join(" ").toLowerCase().includes(q));
  const LIB_PAGE = libPageSize();                                                  // this window's page
  const pages = Math.max(1, Math.ceil(rows.length / LIB_PAGE)), page = Math.min(UI.libPage || 0, pages - 1);
  const shown = rows.slice(page * LIB_PAGE, page * LIB_PAGE + LIB_PAGE);
  const asides = d.asides || [];
  return [
    h("div", { class: "trash-head" },
      h("p", { text: (d.rows || []).length ? tn(d.rows.length, "{n} thing removed.", "{n} things removed.")   // the count; what each key does is on the key
        : asides.length ? t("Nothing you removed waits here. Below are the folders a restore kept beside your workspace.")   // only folders: never "empty" above a list
        : t("The trash is empty. What you remove waits here, so you can put it back.") }),
      (d.rows || []).length ? h("button", { class: "btn small danger", type: "button", "data-key": "trash-empty", onclick: () => emptyTrash(d.rows || []) }, icon("trash"), t("Empty the trash")) : null),
    (d.rows || []).length ? h("div", { class: "lib-table", role: "table", "aria-label": t("Trash") },
      h("div", { class: "lib-row lib-headrow", role: "row" }, [t("Name"), t("Whose"), t("About it"), t("Size"), t("Removed"), ""].map((w) => h("span", { role: "columnheader", text: w }))),
      shown.length ? shown.map(trashRow) : h("p", { class: "ins-none lib-none", text: t("Nothing matches.") })) : null,
    (d.rows || []).length ? pager(page, pages, (p) => setUI("libPage", p), rows.length ? t("{a}–{b} of {n}", { a: page * LIB_PAGE + 1, b: page * LIB_PAGE + shown.length, n: rows.length }) : "") : null,
    asides.length ? h("section", { class: "trash-asides" },
      h("h3", { text: t("Folders kept at a restore") }),
      h("p", { class: "hint", text: t("Each holds your workspace as it was before you restored a backup. Nothing in Offerowl reads them.") }),
      h("div", { class: "lib-table", role: "table", "aria-label": t("Folders kept at a restore") },
        asides.map((a) => h("div", { class: "lib-row trash-row", role: "row", "data-kind": "aside" },
          h("span", { class: "lib-file", role: "cell" }, h("span", { class: "lib-ic trash-ic", "aria-hidden": "true" }, icon("folder")),
            h("span", { class: "lib-name" }, h("b", { text: a.name }), h("small", { text: trashKind("aside") }))),
          h("span", { class: "lib-own", role: "cell" }, h("span", { class: "trash-own" }, h("span", { class: "lib-ownic", "aria-hidden": "true" }, icon("folder")), h("span", { text: t("Beside your workspace") }))),
          h("span", { class: "lib-about", role: "cell", text: trashAbout(a) }),
          h("span", { class: "lib-size", role: "cell", text: bytes(a.size) }),
          h("span", { class: "lib-date", role: "cell", title: a.at, text: [shortDay(a.at), hourOf(a.at)].filter(Boolean).join(" ") }),   // the day and the hour of that restore
          h("span", { class: "lib-keys trash-keys", role: "cell" }, h("span", { class: "lib-slot", "aria-hidden": "true" }),
            h("button", { class: "btn small danger", type: "button", "data-key": "delete-" + a.id, "aria-label": t("Delete {name} for good", { name: a.name }), onclick: () => trashDo(a, "delete") }, icon("trash"), h("span", { text: t("Delete for good") }))))))) : null];
}

function viewLibrary(host) {
  const d = libraryDoc();                                                           // the files
  if (!d) return fill(host, h("div", { class: "lib loading", "aria-busy": "true" }, h("p", { class: "ins-none", text: t("Listing your files…") })));
  if (d.error) return fill(host, h("div", { class: "lib" }, h("p", { class: "ins-none", text: t("The list could not be read.") })));
  const rows = d.rows || [];
  const group = UI.libGroup || "all", owner = UI.libOwner || "", q = (UI.libQuery || "").trim().toLowerCase();
  const trash = group === "trash";                                                  // the Trash in place of the files
  const owners = [];                                                                // every owner once, in the list's order
  for (const r of rows) { const k = r.owner ? (r.owner.job ? "job:" + r.owner.job : "ed:" + r.owner.edition) : "profile"; if (!owners.some((o) => o[0] === k)) owners.push([k, ownerWords(r.owner), r.owner]); }
  const keyOfOwner = (r) => r.owner ? (r.owner.job ? "job:" + r.owner.job : "ed:" + r.owner.edition) : "profile";
  const match = rows.filter((r) => (group === "all" || r.group === group) && (!owner || keyOfOwner(r) === owner) &&
    (!q || [r.name, fileName(r), ownerWords(r.owner), rowWords(r), r.kind].join(" ").toLowerCase().includes(q)));
  const LIB_PAGE = libPageSize();                                                  // this window's page
  const pages = Math.max(1, Math.ceil(match.length / LIB_PAGE)), page = Math.min(UI.libPage || 0, pages - 1);
  const shown = match.slice(page * LIB_PAGE, page * LIB_PAGE + LIB_PAGE);
  const setUI = (k, v) => { UI[k] = v; if (k !== "libPage") UI.libPage = 0; render(); };   // a new filter starts at the first page
  const counts = d.counts || {};
  const goOwner = (o) => { if (o && o.job) { S.job = o.job; UI.jobTab = "fit"; act("/api/v1/jobs/select", { job: o.job }); go("jobs"); } else if (o && o.edition) { act("/api/v1/jobs/select", { job: o.edition }); go("documents"); } else go("profile"); };
  fill(host, h("div", { class: "lib" },
    h("div", { class: "lib-top" },
      h("div", { class: "lib-sum" }, h("span", { class: "ins-ic", "aria-hidden": "true" }, icon("folder")),
        h("div", {}, h("h2", { text: t("Library") }), h("p", { text: t("{n} files, {size}", { n: rows.length, size: bytes(d.bytes) }) }))),
      segBar(LIB_GROUPS.slice(1).map(([k, w]) => ({ n: counts[k] || 0, words: t(w), color: LIB_COLOR[k] })), { label: t("Files by kind"), id: "lib", compact: true }),
      h("div", { class: "lib-acts" },
        h("a", { class: "btn small", href: "/api/v1/workspace/backup", download: "" }, icon("download"), t("Back up my files")),
        h("label", { class: "btn small" }, icon("upload"), t("Restore a backup"), h("input", { type: "file", accept: ".zip", hidden: true, onchange: (e) => { const f = e.target.files[0]; e.target.value = ""; restoreBackup(f); } })),
        h("button", { class: "btn small", type: "button", onclick: async () => { const r = await act("/api/v1/open", { what: "workspace" }); if (r && !r.opened) toast(t("This PC has no file manager to open it with."), null, "warn"); } }, icon("folder"), t("Open the folder")))),
    h("div", { class: "lib-filters" },
      h("div", { class: "seg lib-groups", role: "group", "aria-label": t("What the files are") }, LIB_GROUPS.map(([k, w, ic]) =>
        h("button", { type: "button", "data-key": "lib-g-" + k, "aria-pressed": group === k ? "true" : "false", onclick: () => setUI("libGroup", k) },
          icon(ic), h("span", { text: t(w) }), h("span", { class: "chip count", text: String(k === "all" ? rows.length : counts[k] || 0) }))),
        h("button", { type: "button", class: "lib-trash", "data-key": "lib-g-trash", "aria-pressed": trash ? "true" : "false", onclick: () => setUI("libGroup", "trash") },   // apart from the kinds: what was removed
          icon("trash"), h("span", { text: t("Trash") }), h("span", { class: "chip count", text: String(trashCount()) }))),
      trash ? null : h("label", { class: "field lib-owner" }, h("span", { class: "sr", text: t("Whose") }),
        h("select", { "aria-label": t("Whose"), "data-key": "lib-owner", onchange: (e) => setUI("libOwner", e.target.value) },
          h("option", { value: "", selected: !owner || null, text: t("Every owner") }),
          owners.map(([k, w]) => h("option", { value: k, selected: owner === k || null, text: w })))),
      h("label", { class: "field lib-q" }, h("span", { class: "sr", text: t("Find a file") }), icon("search"),
        h("input", { type: "search", "data-key": "lib-q", placeholder: trash ? t("Find what you removed by its name") : t("Find a file by its name or whose it is"), value: UI.libQuery || "",
          oninput: debounce((e) => setUI("libQuery", e.target.value), 180) }))),
    trash ? viewTrash(trashDoc(), q, setUI) : h("div", { class: "lib-table", role: "table", "aria-label": t("Library") },
      h("div", { class: "lib-row lib-headrow", role: "row" }, [t("File"), t("Whose"), t("About it"), t("Size"), t("Date"), ""].map((w) => h("span", { role: "columnheader", text: w }))),
      shown.length ? shown.map((r) => h("div", { class: "lib-row", role: "row", "data-group": r.group },
        h("span", { class: "lib-file", role: "cell" }, h("span", { class: "lib-ic", style: `--c:${LIB_COLOR[r.group]}`, "aria-hidden": "true" }, icon(LIB_KIND_ICON[r.kind] || "file")),
          h("span", { class: "lib-name" }, h("b", { text: fileName(r), title: r.name }), h("small", { text: t(LIB_GROUPS.find((g) => g[0] === r.group)[1]) + (r.name !== fileName(r) ? " · " + r.name : "") }))),
        h("span", { class: "lib-own", role: "cell" }, h("button", { class: "lib-ownkey", type: "button", title: t("Open"), onclick: () => goOwner(r.owner) },
          r.owner && r.owner.job ? mono(r.owner.company, "sm", r.owner.stage) : h("span", { class: "lib-ownic", "aria-hidden": "true" }, icon(r.owner ? "file" : "person")), h("span", { text: ownerWords(r.owner) }))),
        h("span", { class: "lib-about", role: "cell", text: rowWords(r) }),
        h("span", { class: "lib-size", role: "cell", text: bytes(r.size) }),
        h("span", { class: "lib-date", role: "cell", title: String(r.date || ""), text: shortDay(r.date) }),   // the day as 11-09; the hour shows on a hover
        h("span", { class: "lib-keys", role: "cell" },                               // three fixed places: open, to the Desktop, take off, each in words; a row without one keeps its place empty
          r.open ? h("a", { class: "btn small", href: r.open, target: "_blank", rel: "noopener", "aria-label": t("Open {name}", { name: fileName(r) }) }, icon("open"), h("span", { text: t("Open") })) : h("span", { class: "lib-slot", "aria-hidden": "true" }),
          r.export ? h("button", { class: "btn small", type: "button", title: t("Save to the Desktop"), "aria-label": t("Save {name} to the Desktop", { name: fileName(r) }), onclick: () => libDo(r, "export") }, icon("desktop"), h("span", { text: t("Export") })) : h("span", { class: "lib-slot", "aria-hidden": "true" }),
          r.remove ? h("button", { class: "btn small danger", type: "button", "aria-label": t("Remove {name}", { name: fileName(r) }), onclick: () => libDo(r, "remove") }, icon("close"), h("span", { text: t("Remove") })) : h("span", { class: "lib-slot", "aria-hidden": "true" }))))
        : h("p", { class: "ins-none lib-none", text: t("No file matches.") })),
    trash ? null : pager(page, pages, (p) => setUI("libPage", p), match.length ? t("{a}–{b} of {n}", { a: page * LIB_PAGE + 1, b: page * LIB_PAGE + shown.length, n: match.length }) : "")));   // the pages, numbered
}
