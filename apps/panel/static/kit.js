// The interview kit's contents, search and script cards, drawn by the panel itself in an application's Interview tab.
// The kit's own page (src/interview/page.html) stays for `serve` and for a saved copy; this draws the same scripts with
// the same ranking in the panel's own parts, theme and layout, so the person never leaves Offerowl's page to read them.
// The lines between ">>> engine" and "<<< engine" are the page's own, byte for byte (tests/packaging/test_kit_engine.py):
// a question finds the same card in both, and a script reads the same.
//
//   kitView(data, host) -> { el, query(), search(q), attached(), card(id), destroy() }
//     data  GET /api/v1/jobs/<job>/interview/view: items, alts, kit, syn, str (the view's words in the panel's language),
//           model (a similarity model can be switched on), api (where its questions go: /kit/<job>/), stamp
//     host  { job }: the application's id, for the search box's own key

function kitView(data, host) {                                                      // one view for one application's kit
  const DATA = data;                                                                // as the page names it
  const ITEMS = (DATA && DATA.items) || [];                                         // every question with its script
  const ALTS = (DATA && DATA.alts) || {};                                           // other ways each question may be asked
  const KIT = (DATA && DATA.kit) || {};                                             // the job's settings from kit.json: section names, fallback item, hidden notes
  const STR = (DATA && DATA.str) || {};                                             // the view's words in the panel's language (src/interview/i18n.json)
  const fmt = (k, v) => String(STR[k] || k).replace(/\{(\w+)\}/g, (m, n) => (v && v[n] !== undefined ? v[n] : m));   // a string with {name} slots filled
  const BY_ID = new Map(ITEMS.map((it, i) => [it.id, i]));                          // id -> position
  const BY_ID_LC = new Map(ITEMS.map((it, i) => [it.id.toLowerCase(), i]));         // typed ids are matched without case
  const API = (DATA && DATA.api) || "";                                             // the job's kit server at the panel's own address: similarity and its switch
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));   // HTML-safe text
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));                           // keep x within [a, b]
  const cat = (id) => (/^[A-Z]/.test(id || "") ? id[0] : "");                       // the section letter an id starts with, for its hue
  const store = {                                                                   // per-viewer settings, the same names as the kit's own page keeps (one type size in both)
    get(k, d) { const v = localStore("offerowl-interview:" + k); return v === null || v === undefined ? d : v; },
    set(k, v) { localStore("offerowl-interview:" + k, String(v)); },
  };

// >>> engine:words
// ---------- tokenising (keyword half) ----------
// Korean particles and endings stripped from the end of a word, longest first.
const JOSA = ["에서부터", "으로부터", "이라고", "에게서", "으로서", "으로써", "에서는", "에서도", "으로는", "이라는", "까지는",
  "습니까", "습니다", "했나요", "하나요", "인가요", "였나요", "했는지", "하는지", "입니다", "합니다", "했어요", "해요",
  "에서", "에게", "한테", "께서", "까지", "부터", "보다", "처럼", "마다", "이나", "이랑", "하고", "으로", "라고", "라는", "이란",
  "했다", "하다", "한다", "했던", "하는", "인데", "는데", "은데", "나요", "가요", "죠",
  "로", "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "와", "과", "랑", "요", "란"];
// Words that carry no topic in an interviewer's question.
const STOP_KO = new Set(["어떻게", "무엇", "무엇을", "뭐", "뭘", "어떤", "있나", "있나요", "있습니까", "있었나", "해주세요", "해주시겠어요",
  "말씀", "주세요", "설명", "대해", "대해서", "그리고", "그럼", "혹시", "본인", "지원자", "하셨나", "했나", "건가", "인가", "좀", "한번",
  "그런", "이런", "저런", "어느", "얼마나", "정도", "가장", "제일", "때", "것", "수", "등"]);
const STOP_EN = new Set(("a an the of to in on for and or is are was were be been being i you we it its this that these those with as at by " +
  "from my your our me do does did how what why when which who whom can could would should will about into than then there their they " +
  "them he she his her tell describe explain please us so if any some have has had time times example give talk walk through ever " +
  "kind much many more most really just like also still even well way thing things something").split(" "));
// Cross-language and same-meaning groups; a query word also matches the rest of its group, at lower weight.
// The built-in groups are in synonyms.json, a job adds its own in kit.json; the server sends both.
const SYN = (DATA && DATA.syn) || [];

function stemKo(w) {  // strip one particle or ending, keeping at least two syllables
  for (const j of JOSA) if (w.length >= j.length + 2 && w.endsWith(j)) return w.slice(0, -j.length);
  return w;
}
function stemEn(w) {  // a light English stemmer: plurals and -ing, -ed
  if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
  if (w.length > 5 && w.endsWith("ing")) return w.slice(0, -3);
  if (w.length > 4 && w.endsWith("ed")) return w.slice(0, -2);
  if (w.length > 3 && w.endsWith("s") && !w.endsWith("ss") && !/\d/.test(w)) return w.slice(0, -1);
  return w;
}
const WORD = /[a-z0-9]+(?:[./+\-][a-z0-9]+)*|[가-힣]+/g;  // Latin words (with ci/cd, load-tests) or Hangul runs

function terms(s, forQuery) {  // [{t, w, whole}] for a text: whole words, Korean bigrams, word parts
  const out = [];  // weighted terms
  for (const m of String(s).normalize("NFKC").toLowerCase().matchAll(WORD)) {
    const tok = m[0];  // one word
    if (/^[가-힣]/.test(tok)) {  // Hangul
      if (forQuery && (STOP_KO.has(tok) || JOSA.includes(tok))) continue;  // drop question filler and particles typed after a space ("Kubernetes 에서")
      const st = stemKo(tok);  // word without its particle
      if (forQuery && STOP_KO.has(st)) continue;  // filler after stripping too
      out.push({ t: st, w: 1, whole: true });  // the word itself
      if (st.length === 2) out.push({ t: "#" + st, w: 0.45 });  // lets a two-syllable query word match inside longer words
      for (let i = 0; i + 2 <= st.length && st.length > 2; i++) out.push({ t: "#" + st.slice(i, i + 2), w: 0.45 });  // syllable bigrams
    } else {  // Latin, digits
      if (STOP_EN.has(tok)) continue;  // function words
      if (tok.length < 2 && !/\d/.test(tok)) continue;  // single letters say nothing
      out.push({ t: stemEn(tok), w: 1, whole: true });  // the word itself
      if (/[./+\-]/.test(tok)) for (const p of tok.split(/[./+\-]/)) if (p.length >= 2 && !STOP_EN.has(p)) out.push({ t: stemEn(p), w: 0.6 });  // its parts
    }
  }
  return out;
}

// Synonym lookup built once from SYN, keyed by the stemmed form of each word.
const SYN_OF = new Map();  // stem -> list of other stems in its group
for (const g of SYN) {
  const stems = g.map((w) => (/^[가-힣]/.test(w) ? stemKo(w) : stemEn(w.toLowerCase())));  // normalise like the index does
  stems.forEach((s, i) => SYN_OF.set(s, (SYN_OF.get(s) || []).concat(stems.filter((_, j) => j !== i))));
}

// ---------- BM25 over weighted fields ----------
const K1 = 1.2, B = 0.5;  // term saturation and a mild length penalty (scripts vary a lot in length)
const DOCS = ITEMS.map((it) => {  // one bag of weighted terms per item
  const tf = new Map(); let len = 0;  // term -> weighted count, total weight
  const add = (text, boost) => { for (const { t, w } of terms(text, false)) { const v = boost * w; tf.set(t, (tf.get(t) || 0) + v); len += v; } };
  add(`${it.id} ${it.tko} ${it.ten}`, 3);  // the question counts most
  add(it.key, 2);  // then the one-line core
  add((ALTS[it.id] || []).join(" \n "), 1.2);  // other phrasings
  add(it.text, 1);  // every word of the script and notes
  return { tf, len };
});
const AVG = DOCS.reduce((a, d) => a + d.len, 0) / Math.max(1, DOCS.length);  // average weighted length
const DF = new Map();  // term -> number of items containing it
for (const d of DOCS) for (const t of d.tf.keys()) DF.set(t, (DF.get(t) || 0) + 1);
const idf = (t) => { const df = DF.get(t) || 0; return Math.log(1 + (DOCS.length - df + 0.5) / (df + 0.5)); };  // rarer terms count more

function queryTerms(q) {  // query terms with synonyms added at half weight, merged by term
  const m = new Map();  // term -> weight
  const base = terms(q, true);  // the words as typed
  for (const { t, w } of base) m.set(t, Math.max(m.get(t) || 0, w));
  for (const { t, whole } of base) if (whole) for (const s of SYN_OF.get(t) || []) if (!m.has(s)) m.set(s, 0.5);  // group members
  return { m, words: base.filter((x) => x.whole).map((x) => x.t) };
}
function bm25(qm) {  // score of every item for a query term map
  const s = new Float64Array(DOCS.length);  // one score per item
  for (const [t, qw] of qm) {
    if (!DF.has(t)) continue;  // no item has it
    const w = idf(t) * qw;  // term importance
    DOCS.forEach((d, i) => { const f = d.tf.get(t); if (f) s[i] += w * (f * (K1 + 1)) / (f + K1 * (1 - B + B * d.len / AVG)); });
  }
  return s;
}

// <<< engine:words
// >>> engine:script
// ---------- markdown for the cards ----------
const FIELD = /^(?:-\s+)?\*\*(핵심|KO|EN|국문|주의|꼬리 대비|면접관|나|해석)(?:\(([^)]*)\))?\*\*\s*[:：]?\s*(.*)$/;  // labelled field line
const FIELD_CLASS = { "핵심": "key", KO: "ko", "국문": "ko", EN: "en", "주의": "note", "꼬리 대비": "note", "면접관": "en iv", "나": "en me", "해석": "ko tr" };  // dialogue: the interviewer's and my English lines, each with its 해석 under it
const LABELS = STR.labels || {};  // how each field label is shown in the page's language (the files always use the Korean labels)
const labelOf = (k) => (k ? LABELS[k] || k : "");  // a shown label; an empty speaker stays empty
// Cross-references for the writer, such as "(see project 2)", mean nothing in the live moment. The job's kit.json lists them as
// regular expressions ("strip"); they are removed from titles and text before showing.
const REF = (KIT.strip || []).length ? new RegExp(KIT.strip.join("|"), "g") : null;
const unref = (s) => (REF ? String(s).replace(REF, "") : String(s));  // text without the writer's cross-references
ITEMS.forEach((it) => { it.tko = unref(it.tko).replace(/==|\*\*|`/g, ""); });  // titles: no cross-references, no marks
function inline(s) {  // highlight, bold, italic, inline code on escaped text, without the writer's cross-references
  let h = esc(unref(s));
  h = h.replace(/`([^`]+)`/g, "<code>$1</code>");  // inline code
  h = h.replace(/==(.+?)==/g, '<mark class="hl">$1</mark>');  // the phrase to say, in yellow
  h = h.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");  // bold
  h = h.replace(/(^|[\s(“"'])\*(?!\s)(.+?)(?<!\s)\*(?=$|[\s).,!?;:”"'])/g, "$1<i>$2</i>");  // italic
  return h;
}
function joinLines(lines) {  // source lines are wrapped for the editor: run them on, except a quoted line, which keeps its own line
  return lines.map((l, k) => (k && /^[*"“]/.test(l) ? "<br>" : k ? " " : "") + inline(l)).join("");
}
function render(md, lead) {  // a small block parser: fields, tables, lists, code, paragraphs
  const L = md.split("\n"); const out = []; let i = 0; let led = !lead; let who = "";  // who: the speaker of the last English line, for its Korean line; lead: bold the first sentence of the first KO block
  const isList = (s) => /^\s*(?:[-*]|\d+\.)\s+/.test(s);  // bullet or numbered line
  while (i < L.length) {
    const ln = L[i];
    if (!ln.trim() || /^-{3,}\s*$/.test(ln)) { i++; continue; }  // blank lines and rules
    if (ln.startsWith("```")) {  // fenced code
      const buf = []; i++;
      while (i < L.length && !L[i].startsWith("```")) buf.push(L[i++]);
      i++; out.push(`<pre>${esc(buf.join("\n"))}</pre>`); continue;
    }
    const f = ln.trim().match(FIELD);
    if (f) {  // a labelled field and its continuation lines
      const buf = [f[3]]; i++;
      while (i < L.length && L[i].trim() && !FIELD.test(L[i].trim()) && !(isList(L[i]) && !/^\s{2,}/.test(L[i]))) buf.push(L[i++].trim());
      if (f[1] === "면접관" || f[1] === "나") who = f[1];
      const cls = f[1] === "해석" ? "ko tr " + (who === "면접관" ? "iv" : "me") : FIELD_CLASS[f[1]];  // a Korean line wears its speaker's colour
      const lab = f[1] === "해석" ? labelOf(who) : labelOf(f[1] === "국문" || f[1] === "KO" ? "해석" : f[1]) + (f[2] ? ` (${f[2]})` : "");  // the Korean text is the 해석 of the English script
      let html = joinLines(buf);
      if (cls === "ko" && !led) {  // the conclusion comes first; skipped when the script already marks its own phrases
        if (!/<mark class="hl">/.test(html)) html = html.replace(/^(.+?[.?!])(\s|$)/, (m0, s1, s2) => (s1.length <= 80 ? `<span class="lead">${s1}</span>${s2}` : m0));
        led = true;
      }
      if (cls.startsWith("en") || (cls === "note" && /\s\/\/\s/.test(html))) html = scriptHtml(html);  // English answers and follow-up answers read as a script, line by line
      out.push(`<div class="fld ${cls}"><p>${lab ? `<span class="lab">${esc(lab)}</span>` : ""}${html}</p></div>`);
      continue;
    }
    if (ln.trim().startsWith("|")) {  // a table
      const rows = [];
      while (i < L.length && L[i].trim().startsWith("|")) rows.push(L[i++].trim());
      const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\|?[\s:|-]+\|?$/.test(r));  // drop the separator row
      const head = body.shift() || "";
      out.push(`<table><thead><tr>${cells(head).map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>` +
        body.map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("") + "</tbody></table>");
      continue;
    }
    if (isList(ln)) {  // a list, nested by indentation
      const lines = [];
      while (i < L.length && (isList(L[i]) || (/^\s{2,}\S/.test(L[i]) && lines.length))) lines.push(L[i++]);
      out.push(list(lines)); continue;
    }
    const buf = [];  // a paragraph runs until a blank line or another block
    while (i < L.length && L[i].trim() && !isList(L[i]) && !L[i].trim().startsWith("|") && !FIELD.test(L[i].trim()) && !L[i].startsWith("```")) buf.push(L[i++].trim());
    out.push(`<p>${joinLines(buf)}</p>`);
  }
  // English is the main text in an English interview: the English scene, then its 해석, the key line, then the rest in file order.
  // The whole English scene comes first and the same scene in Korean comes under it as one block, not line by line.
  const rankOf = (h) => (h.startsWith('<div class="fld en') ? 0 : h.startsWith('<div class="fld ko') ? 1 : h.startsWith('<div class="fld key') ? 2 : 3);
  const sorted = out.map((h, k) => [rankOf(h), k, h]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((x) => x[2]);
  // The Korean scene is not main text either: it is the 해석 note under the scene, drawn differently.
  const tr = sorted.filter((h) => h.startsWith('<div class="fld ko tr'));
  if (!tr.length) return sorted.join("\n");
  const k0 = sorted.findIndex((h) => h.startsWith('<div class="fld ko tr'));
  const rest = sorted.filter((h) => !h.startsWith('<div class="fld ko tr'));
  const head = tr[0].replace("<p>", '<p><span class="nh">' + esc(labelOf("해석")) + "</span>");  // the badge rides on the first Korean line, so it can never sit alone at a column foot
  rest.splice(k0, 0, `<div class="ko-note">${[head, ...tr.slice(1)].join("")}</div>`);
  return rest.join("\n");
}
// Bullets whose bold label is one of the kit's hidden labels (evidence notes for the writer) are left out of the cards.
const escRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");  // a literal inside a regular expression
const HIDDEN = (KIT.hidden_labels || []).length ? new RegExp("^\\*\\*(" + KIT.hidden_labels.map(escRe).join("|") + ")\\*\\*") : null;
function list(lines) {  // nested <ul>/<ol> from indented list lines; the writer's source notes are left out
  const root = { kids: [] }; const stack = [{ ind: -1, node: root }];
  let skip = -1;  // indentation of a skipped bullet, so its children are skipped too
  for (const ln of lines) {
    const m = ln.match(/^(\s*)(?:([-*])|(\d+)\.)\s+(.*)$/);
    if (!m) { if (skip < 0) { const top = stack[stack.length - 1].node; if (top.text !== undefined) top.text += (/^[*"“]/.test(ln.trim()) ? "<br>" : " ") + inline(ln.trim()); } continue; }  // continuation line
    const ind = m[1].length;
    if (skip >= 0 && ind > skip) continue;  // still inside a skipped bullet
    skip = HIDDEN && HIDDEN.test(m[4]) ? ind : -1;  // where a fact came from is not something to say aloud
    if (skip >= 0) continue;
    const node = { text: inline(m[4]), kids: [], ordered: !!m[3] };
    while (stack.length > 1 && stack[stack.length - 1].ind >= ind) stack.pop();  // climb to the parent level
    stack[stack.length - 1].node.kids.push(node); stack.push({ ind, node });
  }
  const html = (n) => n.kids.length ? `<${n.kids[0].ordered ? "ol" : "ul"}>${n.kids.map((k) => `<li>${k.text}${html(k)}</li>`).join("")}</${n.kids[0].ordered ? "ol" : "ul"}>` : "";
  return html(root);
}

// ---------- the query's words ----------
function markQuery(el, ws0) {  // underline the query's words inside an element's text (yellow stays for the marked phrases)
  const ws = [...new Set(ws0.filter((w) => w.length >= 2 || /\d/.test(w)))].sort((a, b) => b.length - a.length);
  if (!ws.length) return;
  const re = new RegExp("(" + ws.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");  // longest first
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);  // text nodes only
  const nodes = []; while (walk.nextNode()) nodes.push(walk.currentNode);
  for (const n of nodes) {
    if (n.parentElement && n.parentElement.closest(".lab, pre, .id, .short")) continue;  // never inside a label, an id or a code block
    if (!re.test(n.nodeValue)) { re.lastIndex = 0; continue; } re.lastIndex = 0;
    const span = document.createElement("span");
    // Find the query's words in the raw text and escape each piece on its own. Searching the escaped text split entities
    // apart ('3 a.m.' matched the 3 inside &#39; and the quote showed as text). With a capturing group, odd pieces are the words
    span.innerHTML = n.nodeValue.split(re).map((p, k) => (k % 2 ? `<mark class="qm">${esc(p)}</mark>` : esc(p))).join("");
    n.replaceWith(...span.childNodes);
  }
}
// <<< engine:script
// >>> engine:lines
function scriptHtml(html) {  // script lines: ' // ' ends a thought (a new line), ' / ' is a short breath (a faint slash), Korean brackets are unspoken stage notes
  const dir = (t) => t.replace(/\(([^()<>]*[\uac00-\ud7a3][^()<>]*)\)/g, '<span class="dir">($1)</span>');
  if (!/\s\/\/?\s/.test(html)) return dir(html);  // prose without marks stays prose
  return html.split(/\s+\/\/\s+/).map((t) => `<span class="th">${dir(t).replace(/ \/ /g, ' <span class="br">/</span> ')}</span>`).join("");
}
// <<< engine:lines
// >>> engine:groups
// ---------- groups and the section menu ----------
// Each reference file (notes, stories) is one group, and items with no section of their own form the "remember first" group.
const FIRST = fmt("first_group");  // that group's name
const groupOf = (it) => (it.role === "reference" ? it.src : it.cat === it.src ? FIRST : it.cat);
// Short menu names for the lettered sections, from the job's kit.json (short enough for one row of tabs at 1400 px).
const SHORT = KIT.sections || {};
const GROUPS = []; const GROUP_OF = new Map();  // groups in file order, and group name -> group
ITEMS.forEach((it, i) => { const g = groupOf(it); if (!GROUP_OF.has(g)) { GROUP_OF.set(g, { name: g, items: [], role: it.role }); GROUPS.push(GROUP_OF.get(g)); } GROUP_OF.get(g).items.push(i); });
const isRow = (g) => g.role === "deep" || g.role === "terms";  // long groups (resume deep dives, terms): one row in the contents
const isRef = (g) => g.role === "reference";  // reference material: one row as well
function letterOf(g) {  // the letter most of a group's ids start with, for its hue and its row in the contents
  const n = new Map(); for (const i of g.items) { const c = cat(ITEMS[i].id); if (c) n.set(c, (n.get(c) || 0) + 1); }
  let best = "", most = 0; for (const [c, k] of n) if (k > most) { best = c; most = k; }  // ties keep the first letter seen
  return best;
}
function menuLabel(name) {  // "D. Behavioral, career, HR" -> "D" + short name
  const m = name.match(/^([A-Z])\.\s/);
  return m ? `<span class="k">${m[1]}</span>${esc(SHORT[m[1]] || name.slice(3))}` : esc(name);
}
// <<< engine:groups

  // ---------------------------------------------------------------- the sections' names on the keys
  const REF_NAME = { stories: t("Your stories"), english: t("English phrases") };  // the kit's reference files by what they hold (a raw file name read as a section)
  const refName = (g) => REF_NAME[String(g.name).replace(/\.md$/, "")] || g.name;
  // a section's key in a few words: "Phone screen: career, motive, terms" says "Phone screen"; when several sections open with
  // the same words ("Projects: Acme search, ranking", "Projects: Globex billing (SRE, …)"), each says the first thing after its colon
  const headOf = (name) => { const m = String(name).match(/^(?:[A-Z]\.\s+)?(.{2,24}?):\s+(.*)$/); return m ? { head: m[1], tail: m[2] } : null; };
  const HEADS = new Map(); GROUPS.forEach((g) => { const x = headOf(g.name); if (x) HEADS.set(x.head, (HEADS.get(x.head) || 0) + 1); });
  function keyLabel(g) {                                                            // a section's key: its letter and a few words; its hover keeps the whole name
    if (isRef(g)) return esc(refName(g));
    const m = g.name.match(/^([A-Z])\.\s+(.*)$/); if (!m) return esc(g.name);
    const x = headOf(g.name);
    const words = SHORT[m[1]] || (!x ? m[2] : HEADS.get(x.head) > 1 ? x.tail.split(/,\s|\s\(/)[0] : x.head);
    return `<span class="k">${m[1]}</span>${esc(words)}`;
  }

  // ---------------------------------------------------------------- the parts, in the panel's own components
  const sw = DATA && DATA.model ? h("button", { class: "switch", type: "button", role: "switch", "aria-checked": "false", "aria-label": fmt("engine_title") }) : null;   // the similarity switch, when the server has a model
  const lamp = sw ? h("span", { class: "lit off", "aria-hidden": "true" }) : null;  // its lamp: off, loading, on, or out of reach
  const examples = KIT.examples ? (typeof KIT.examples === "string" ? KIT.examples : KIT.examples[STR.lang] || "") : "";   // the job's own example questions
  const qIn = h("input", { type: "search", class: "kit-q", "data-key": "kit-q-" + host.job, autocomplete: "off", spellcheck: "false",
    placeholder: fmt("placeholder", { examples: examples || STR.examples || "" }), "aria-label": fmt("placeholder", { examples: examples || STR.examples || "" }) });
  const homeKey = h("button", { class: "btn kit-home", type: "button", title: fmt("home_title") }, icon("grid"), fmt("home"));   // back to the contents
  const langSeg = h("div", { class: "seg kit-lang", role: "group", "aria-label": fmt("lang_group") },
    [["both", fmt("lang_both"), "Alt+1"], ["ko", "KO", "Alt+2"], ["en", "EN", "Alt+3"]].map(([v, w, key]) =>
      h("button", { type: "button", "data-lang": v, "aria-pressed": "false", title: key, text: w })));
  const prefsKey = h("button", { class: "btn icon kit-prefs-key", type: "button", "aria-expanded": "false", title: fmt("prefs"), "aria-label": fmt("prefs") }, icon("sliders"));
  const prefsRow = h("div", { class: "kit-prefs", hidden: true },                    // the one type size and the column width, in a row under the keys (nothing floats over the scripts)
    h("span", { class: "kit-pref" }, h("span", { class: "hint", text: fmt("text_size") }),
      h("div", { class: "seg", role: "group", "data-pref": "fs", "aria-label": fmt("text_size") }, [12, 13, 14, 15].map((v) => h("button", { type: "button", "data-v": String(v), "aria-pressed": "false", text: String(v) })))),
    h("span", { class: "kit-pref" }, h("span", { class: "hint", text: fmt("col_width") }),
      h("div", { class: "seg", role: "group", "data-pref": "colw", "aria-label": fmt("col_width") }, [[22, fmt("col_narrow")], [25, fmt("col_normal")], [29, fmt("col_wide")]].map(([v, w]) =>
        h("button", { type: "button", "data-v": String(v), "aria-pressed": "false", text: w })))));
  const elMenu = h("nav", { class: "kit-menu", "aria-label": fmt("menu_aria") });   // the sections, a key each
  const elRank = h("nav", { class: "kit-rank", "aria-label": fmt("rank_aria") });   // the answers on the board, in reading order
  const elCards = h("section", { class: "kit-cards", "aria-live": "polite" });      // the contents, or the answers
  const elMain = h("div", { class: "kit-main" }, elRank, elCards);
  const root = h("section", { class: "kit", "aria-label": t("Search the scripts") },
    h("div", { class: "kit-bar" }, homeKey,
      h("label", { class: "field lib-q kit-search" }, icon("search"), qIn),
      langSeg,
      sw ? h("span", { class: "kit-engine" }, lamp, h("span", { class: "kit-engine-lab", text: fmt("engine_label") }), sw) : null,
      prefsKey),
    prefsRow, elMenu, elMain);
  const narrow = () => root.clientWidth > 0 && root.clientWidth <= 700;             // a phone, or a narrow column: one column of answers that scrolls down
  // measured once per draw, first, before anything is written: read again after the board was emptied or a class changed, the
  // width made the browser lay out the whole old board (300 ms of a question, measured)
  let narrowNow = false;

  // ---------------------------------------------------------------- similarity half (the job's kit server)
  let dense = null;                                                                 // {q, map: id -> [score, label, text], med, max} for the last answered query
  let denseOk = null;                                                               // null unknown, true reachable, false down
  let inflight = null;                                                              // AbortController of the running request
  let engine = "unknown";                                                           // the server's model: on, off, loading, or down when the server cannot be reached
  let tHealth = 0;                                                                  // the next poll while the model loads
  let gone = false;                                                                 // the view was let go: no more polls or draws
  function setEngine(state, info) {                                                 // show the switch as the server reports it; similarity is used only while on
    engine = state; denseOk = state === "on";
    if (!sw) return;                                                                // no model on this server: no switch
    sw.setAttribute("aria-checked", String(state === "on"));
    sw.disabled = state === "down" || state === "loading";                          // nothing to switch while loading or with no server
    lamp.className = "lit " + ({ on: "ok", loading: "busy", down: "bad" }[state] || "off");
    const mem = info && info.rss_mb ? fmt("engine_mem", { mb: info.rss_mb }) : "";  // how light the idle server is
    sw.title = fmt("engine_" + state, { mem }) + (info && info.error ? fmt("engine_error", { error: info.error }) : "");   // on, off, loading or down
  }
  async function health() {                                                         // ask the server how the model is; poll while it loads
    clearTimeout(tHealth);
    if (gone) return;
    try {
      const r = await fetch(API + "api/health", { cache: "no-store" });
      if (!r.ok) throw new Error("kit " + r.status);                                // the panel's own refusal (no kit, the kit gone, busy) is not the model's state
      const j = await r.json(); const was = engine;
      setEngine(j.state || "on", j);
      if (was !== "on" && engine === "on" && mode === "search" && current && !BY_ID_LC.has(current.toLowerCase())) fetchDense(current);   // a question asked before the state was known: ranked again with similarity
      if (j.state === "loading") tHealth = setTimeout(health, 1000);
    } catch (e) { setEngine("down"); tHealth = setTimeout(health, 15000); }         // look again now and then
  }
  async function switchEngine() {                                                   // the switch: load the model, or drop it once the panel's own question is answered
    if (engine !== "on" && engine !== "off") return;
    const want = engine === "on" ? "off" : "on";
    if (want === "off" && !(await askFirst({ title: t("Turn semantic search off?"), text: t("Turning it on again takes a few seconds."), ok: t("Turn off") }))) return;   // a stray click must not drop the model mid-interview
    setEngine(want === "on" ? "loading" : "off");                                   // answer the click at once
    try { await fetch(API + "api/model/" + want, { method: "POST", cache: "no-store" }); } catch (e) { /* health says what happened */ }
    health();
  }
  async function fetchDense(q) {                                                    // ask the server for every item's similarity to q
    if (inflight) inflight.abort();                                                 // only the newest query matters
    const ctl = new AbortController(); inflight = ctl;
    try {
      const r = await fetch(API + "api/dense?q=" + encodeURIComponent(q), { signal: ctl.signal, cache: "no-store" });
      if (!r.ok) throw new Error("similarity off");                                 // the model was switched off: the catch falls back to keywords
      const j = await r.json();                                                     // {scores: [[id, s, label, text]], ms}
      const map = new Map(j.scores.map((x) => [x[0], x.slice(1)]));                 // id -> [s, label, text]
      const vals = j.scores.map((x) => x[1]).sort((a, b) => a - b);                 // ascending scores
      dense = { q, map, med: vals[Math.floor(vals.length / 2)] || 0, max: vals[vals.length - 1] || 0 };
      if (engine !== "on") setEngine("on");
      if (q === current) { clearTimeout(tKey); show(); }                            // the fused ranking replaces the keyword fallback timer
    } catch (e) {
      if (e.name === "AbortError") return;                                          // a newer query took over
      denseOk = false;                                                              // keywords at once for this query
      health();                                                                     // and ask the server how the model is
      if (q === current) { clearTimeout(tKey); show(); }
    }
  }

// >>> engine:rank
// ---------- fusion ----------
function rank(q) {  // fused ranking for a query: {list: [{i, score, kn, dn, sim, why}], words, weak}
  const { m, words } = queryTerms(q);
  const kw = bm25(m);  // keyword scores
  let kmax = 0; for (const v of kw) kmax = Math.max(kmax, v);
  const d = dense && dense.q === q ? dense : null;  // similarity only if it answers this exact query
  // Similarity leads; keywords break ties and matter most for one-word queries. The weights were tuned on a 61-question
  // eval set (top-1 60/61 blended, 59/61 for similarity alone and 52/61 for keywords alone, without phrasings).
  let wk = words.length <= 1 ? 0.3 : words.length === 2 ? 0.2 : 0.15;
  if (!d) wk = 1;  // keyword-only when the server cannot answer
  if (d && kmax === 0) wk = 0;  // nothing matched literally: similarity decides alone
  const span = d ? Math.max(1e-6, d.max - d.med) : 1;  // items at or below the median score get no similarity credit
  const out = [];
  // Term entries (role "terms") come first for a "What is X?" question or a single word, and step back for a scenario question,
  // so a long list of terms does not push the scenes down (on a 30-question eval set, top-1 fell from 29/30 to 25/30 without it)
  const defQ = words.length <= 1 || /\bwhat\s*(is|are|'s)\b|\bwhat\s+does\b.*\b(mean|stand)|\bstands?\s+for\b|\bdefin|\bexplain\s+\S+\s*\??$|뭐야|뭔가요|뭐예요|무엇인가|무슨\s*뜻|이란\b|란\s*\??$/i.test(q);
  ITEMS.forEach((it, i) => {
    const kn = kmax > 0 ? kw[i] / kmax : 0;  // keyword, 0..1
    const ds = d ? d.map.get(it.id) : null;  // [s, label, text]
    const dn = ds ? clamp((ds[0] - d.med) / span, 0, 1) : 0;  // similarity, 0..1
    const score = (wk * kn + (1 - wk) * dn) * (it.role === "terms" ? (defQ ? 1.25 : 0.6) : 1);  // convex blend; terms lead for "what is X" and step back for scenario questions
    if (score > 0.04) out.push({ i, score, kn, dn, sim: ds ? ds[0] : null, why: ds && dn > 0.55 ? ds : null });
  });
  out.sort((a, b) => b.score - a.score);  // best first
  const weak = d ? d.max < 0.6 : kmax === 0;  // with bge-m3, off-topic questions top out near 0.5 to 0.6, on-topic ones above 0.62
  return { list: out.slice(0, 40), words, weak };
}
// <<< engine:rank

  // ---------------------------------------------------------------- view
  let mode = "toc";                                                                 // toc, search or group
  let current = "";                                                                 // query being shown
  let groupName = null;                                                             // the group being shown in group mode
  let results = [];                                                                 // ranked [{i, score, kn, dn, sim, why}]
  let lang = store.get("lang", "both");                                             // which scripts the cards show
  let words = [];                                                                   // query words for underlining
  let weak = false;                                                                 // nothing close to the query
  const GAP = 16, VGAP = 12, BOARD_MAX = 24;                                        // gaps in px (the panel's own between cards), answers on a board
  let FSB = clamp(Number(store.get("fs", 13)) || 13, 12, 15);                       // the one type size, from the settings (12 to 15 px)
  let COLW = [22, 25, 29].includes(Number(store.get("colw", 25))) ? Number(store.get("colw", 25)) : 25;   // column width in ems

  function tip(r) {                                                                 // tooltip text with the two halves of the score
    const parts = [fmt("tip_keywords", { n: Math.round(r.kn * 100) })];
    if (r.sim !== null && r.sim !== undefined) parts.push(fmt("tip_similarity", { s: r.sim.toFixed(2) }));
    return mode === "search" && r.score ? parts.join(", ") : "";
  }
  const HINT = KIT.weak_hint ? (typeof KIT.weak_hint === "string" ? KIT.weak_hint : KIT.weak_hint[STR.lang] || "") : "";   // the job's advice for questions without a script
  const WEAK_LINE = `<div class="kit-weak"><b>${esc(fmt("weak"))}</b>${HINT ? " " + esc(HINT) : ""}</div>`;   // said under the best card when nothing is close
  let secStarts = new Set();                                                        // board positions whose card starts another section (an item number's board runs on past its section)
  function cardHtml(r, n) {                                                         // one item in full: header, then its script
    const it = ITEMS[r.i]; const best = n === 0 && mode === "search";
    const g = secStarts.has(n) ? GROUP_OF.get(groupOf(it)) : null;                   // the section this card starts, said over it
    return `<article class="kit-card${best ? " best" : ""}" data-id="${esc(it.id)}" data-src="${esc(it.src)}" data-c="${cat(it.id)}">` +
      (g ? `<div class="kit-sec" data-c="${cat(isRef(g) ? letterOf(g) : g.name[0])}">${keyLabel(g)}</div>` : "") +
      `<div class="kit-ch" title="${esc(tip(r))}"><span class="kit-id id">${esc(it.id)}</span><span class="kit-t">${esc(it.tko)}</span>` +
      `${it.ten ? `<span class="kit-te">${esc(it.ten)}</span>` : ""}</div>` +
      `${best && weak ? WEAK_LINE : ""}<div class="kit-body">${render(it.md, !it.key)}</div></article>`;   // the scene only
  }
  let measureBox = null;                                                            // an off-screen copy of the board for measuring cards before placing them
  function measurer() {                                                             // the off-screen box, with the board's type and language
    if (!measureBox) { measureBox = h("div", { "aria-hidden": "true" }); root.appendChild(measureBox); }
    measureBox.className = "kit-cards measure lang-" + lang;
    return measureBox;
  }
  function heightIn(html, width) {                                                  // a card's height in one column of this width
    const box = measurer(); box.innerHTML = `<div class="kit-slot" style="width:${width}px">${html}</div>`;
    return box.querySelector(".kit-card").offsetHeight;
  }
  function fitsBlock(html, width, n, height, whole) {                               // does a card fit in n inner columns of this width and height?
    const box = measurer(); box.innerHTML = `<div class="kit-block${whole ? " whole" : ""}" style="width:${width}px;--h:${height}px;--n:${n}">${html}</div>`;   // same title rule as on the board
    const c = box.querySelector(".kit-card"); return c.scrollWidth <= c.clientWidth + 1 && c.scrollHeight <= c.clientHeight + 1;   // the translation note can also run off the foot
  }
  // card heights and block widths, kept across questions and keyed by everything that changes them: a card measured once at a
  // width is not measured again (most of a question's 400 to 800 ms went to measuring the same cards again)
  const measured = new Map();
  let board = [];                                                                   // the answers on the board, best first
  let boardOrder = [];                                                              // board positions in the order they were placed (reading order)
  let geo = { cw: 0, C: 1 };                                                        // column width and columns per screen of the last layout
  // Placing the board: short answers stack in a column, a long one takes a block of columns. The plan can stop after some
  // columns and go on later: the first two screens are drawn at once and the rest a moment after, so a question shows its
  // best answers without waiting for twenty more cards to be measured and laid out.
  function planStart(cForce, cache, strict, W, H) {                                 // the plan's state, nothing placed yet
    // columns on one screen: as many of the normal width (25 em) as fit, one more for narrow and one fewer for wide, so each
    // choice changes the board (at 15 px, 25 and 29 em gave the same four)
    const base = Math.max(1, Math.floor((W + GAP) / (25 * FSB + GAP)));
    const C = cForce || (COLW === 22 ? base + 1 : COLW === 29 ? Math.max(1, base - 1) : base);
    const cw = Math.floor((W - (C - 1) * GAP) / C);                                 // a screen holds whole columns
    const keyOf = (k) => [board[k].i, cw, lang, FSB, k === 0 && mode === "search" && weak ? "w" : "", secStarts.has(k) ? "s" : ""].join("|");   // what a card's size depends on
    const heightOf = (k) => { const key = keyOf(k); if (!cache.has(key)) cache.set(key, heightIn(cardHtml(board[k], k), cw)); return cache.get(key); };
    return { H, C, cw, cache, strict, keyOf, heightOf, slots: [], order: [], cur: null, used: 0, queue: board.map((_, k) => k) };
  }
  function planRun(st, upto) {                                                      // place cards until `upto` columns are taken or the board ends
    const { H, C, cw, cache, strict, keyOf, heightOf, slots, order, queue } = st;
    // the cards this run will likely place, measured in one off-screen pass: one layout for all of them (a card at a time laid
    // the box out once per card)
    const todo = queue.slice(0, upto === Infinity ? queue.length : upto * 3 + 4).filter((k) => !cache.has(keyOf(k)));
    if (todo.length > 1) {
      const box = measurer(); box.innerHTML = todo.map((k) => `<div class="kit-slot" style="width:${cw}px">${cardHtml(board[k], k)}</div>`).join("");
      const cards = box.querySelectorAll(".kit-slot > .kit-card"); todo.forEach((k, j) => cache.set(keyOf(k), cards[j].offsetHeight));
    }
    const fillColumn = () => {                                                      // the room left at the foot of this column takes one of the next few short answers
      if (strict) return;                                                           // a section's own order: the card after this one never comes before it
      for (let more = true; more && st.cur;) {
        more = false;
        for (let i = 0; i < Math.min(8, queue.length); i++) {                       // the next eight: a column's foot left empty under a short card was the most of a screen's blank
          const j = queue[i], hj = heightOf(j);
          if (hj <= H && st.cur.used + VGAP + hj <= H) { st.cur.items.push(j); st.cur.used += VGAP + hj; order.push(j); queue.splice(i, 1); more = true; break; }
        }
      }
    };
    while (queue.length && st.used < upto) {
      const k = queue.shift(); const hk = heightOf(k);
      if (hk <= H && st.cur && st.cur.used + VGAP + hk <= H) { st.cur.items.push(k); st.cur.used += VGAP + hk; order.push(k); continue; }
      fillColumn();
      if (hk <= H) { st.cur = { kind: "col", items: [k], used: hk }; slots.push(st.cur); st.used += 1; order.push(k); continue; }
      const nkey = "n|" + H + "|" + keyOf(k); let n = cache.get(nkey);              // a long answer: the fewest inner columns that hold it at full height
      if (n === undefined) { n = Math.max(2, Math.ceil(hk / H)); const html = cardHtml(board[k], k); while (n < 60 && !fitsBlock(html, n * cw + (n - 1) * GAP, n, H, n <= C)) n++; cache.set(nkey, n); }
      const left = (C - (st.used % C)) % C;                                         // columns left on this screen
      if (left > 0 && left < n && !strict) {                                        // the card would run off this screen: give the rest of the screen to short answers, so it starts a screen (a section's own order runs on across the screens instead)
        for (let c = 0; c < left; c++) {
          const i = queue.findIndex((j, idx) => idx < 8 && heightOf(j) <= H); if (i < 0) break;
          const j = queue.splice(i, 1)[0]; st.cur = { kind: "col", items: [j], used: heightOf(j) }; slots.push(st.cur); st.used += 1; order.push(j);
          fillColumn();
        }
      }
      slots.push({ kind: "block", items: [k], n }); st.used += n; order.push(k); st.cur = null;
    }
    if (queue.length) { fillColumn(); st.cur = null; }                              // stopped: the last column takes what fits now, and the next run starts a column of its own
    return st;
  }
  const slotHtml = (sl, st) => (sl.kind === "block"                                 // one placed column or block, as the board draws it
    ? `<div class="kit-block${sl.n <= st.C ? " whole" : ""}" style="width:${sl.n * st.cw + (sl.n - 1) * GAP}px;--n:${sl.n}">${cardHtml(board[sl.items[0]], sl.items[0])}</div>`
    : `<div class="kit-slot" style="width:${st.cw}px">${sl.items.map((k) => cardHtml(board[k], k)).join("")}</div>`);
  function layoutNarrow(el) {                                                       // a narrow view: every answer in one column, in rank order, and the page scrolls
    el.className = "kit-cards phone lang-" + lang;
    el.innerHTML = board.map((r, k) => cardHtml(r, k)).join("");                    // no measuring: the column grows with the cards
    if (words.length) el.querySelectorAll(".kit-card").forEach((c) => markQuery(c, words));   // the query's words underlined
    boardOrder = board.map((_, k) => k);
  }
  let lastTop = -1;                                                                 // the top answer last drawn, so the rise does not replay for the same answer
  let tRest = 0;                                                                    // the board's later screens, placed after the first two are on screen
  function layout() {                                                               // the board for the current results, scrolled to its start
    clearTimeout(tRest);                                                            // the last board's later screens are not wanted any more
    const el = elCards; el.innerHTML = ""; el.className = "kit-cards lang-" + lang; el.style.overflowY = "";   // the old board goes first: measuring the room under it laid the old board out again
    const asked = mode === "search" && !BY_ID_LC.has(current.toLowerCase());        // a question, ranked
    if (!results.length) {                                                          // nothing matched: the script for questions without a script
      const k = KIT.fallback ? BY_ID.get(KIT.fallback) : undefined; board = k === undefined ? [] : [{ i: k, score: 0, kn: 0, dn: 0, sim: null, why: null }];   // the kit's "what to say when you do not know" item
    } else if (asked) board = results.slice(0, BOARD_MAX);                          // a question: the best answers first, more screens to the right
    else if (mode === "group") board = results;                                     // a section from its key: that section, in its own order, and nothing of the next
    else {                                                                          // an item number: its section, then the items that follow it in the files
      const last = Math.max(...results.map((r) => r.i));
      board = results.concat(ITEMS.slice(last + 1, last + 21).map((_, j) => ({ i: last + 1 + j, score: 0, kn: 0, dn: 0, sim: null, why: null }))).slice(0, 60);
    }
    secStarts = new Set();                                                          // where a board read in the files' order enters another section, said on that card
    if (!asked) board.forEach((r, k) => { if (k && groupOf(ITEMS[r.i]) !== groupOf(ITEMS[board[k - 1].i])) secStarts.add(k); });
    if (narrowNow) { layoutNarrow(el); drawRank(); return; }                        // a narrow view scrolls down instead of sliding sideways
    const W = el.clientWidth, H = el.clientHeight;                                  // the room, measured on an empty board
    if (!W || !H) return;                                                           // not laid out (the view is off the page): drawn when it is back (attached)
    if (measured.size > 4000) measured.clear();                                     // a long session: the oldest sizes go
    const cache = measured; const cols = (q) => q.slots.reduce((a, x) => a + (x.kind === "block" ? x.n : 1), 0);   // columns a plan takes
    const strict = !asked;                                                          // a section or an item number reads in the files' order
    let p = planRun(planStart(0, cache, strict, W, H), 0);                          // the plan's frame: its columns per screen
    p = planRun(p, 2 * p.C);                                                        // the first two screens now
    if (!p.queue.length) {                                                          // the whole board fitted: fewer, wider columns until the answers fill them (never wider than about 1.7 columns)
      const c0 = p.C;
      for (let i = 0; i < 5 && cols(p) < p.C; i++) { const c2 = Math.max(cols(p), Math.ceil(c0 * 0.6)); if (c2 === p.C) break; p = planRun(planStart(c2, cache, strict, W, H), Infinity); }
    }
    geo = { cw: p.cw, C: p.C }; boardOrder = p.order;
    el.innerHTML = p.slots.map((sl) => slotHtml(sl, p)).join("");
    if (measureBox) measureBox.innerHTML = "";                                      // nothing left off-screen
    if (p.queue.length) {                                                           // the later screens, a moment after the first two are on screen
      const placed = p.slots.length, run = board;
      tRest = setTimeout(() => {
        if (gone || board !== run) return;                                          // another question came meanwhile
        planRun(p, Infinity);
        const tmp = h("div"); tmp.innerHTML = p.slots.slice(placed).map((sl) => slotHtml(sl, p)).join("");
        const added = [...tmp.children]; el.append(...added);
        if (measureBox) measureBox.innerHTML = "";
        if (words.length) added.forEach((x) => x.querySelectorAll(".kit-card").forEach((c) => markQuery(c, words)));
        boardOrder = p.order; drawRank(); markVisible();
      }, 0);
    }
    if (words.length) el.querySelectorAll(".kit-card").forEach((c) => markQuery(c, words));   // underlines only; sizes do not change
    el.style.scrollBehavior = "auto"; el.scrollLeft = 0; el.style.scrollBehavior = ""; keepLeft = 0;
    const topNow = board.length ? board[0].i : -1;                                  // the rise plays only when the top answer changes
    if (topNow !== lastTop) { el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter"); lastTop = topNow; }   // a short rise for the new answers
    drawRank(); markVisible();
    lastW = el.clientWidth; lastH = el.clientHeight;                                // fitted to this room: the watcher below need not fit it again (the side list's coming narrowed it, and the board was drawn twice)
  }
  function drawRank() {                                                             // the side list: every answer on the board in reading order; the ones on screen are marked
    const el = elRank;
    const rowOf = (k) => { const it = ITEMS[board[k].i];
      return `<button type="button" class="kit-row" data-id="${esc(it.id)}" data-src="${esc(it.src)}" data-c="${cat(it.id)}" title="${esc(tip(board[k]))}">` +
        `<span class="kit-id">${esc(it.id)}</span><span class="kit-t">${esc(it.tko)}</span></button>`; };
    el.innerHTML = boardOrder.map(rowOf).join("");
    if (!el.clientHeight || el.scrollHeight <= el.clientHeight + 1) return;         // it all fits (one layout)
    // whole rows only, never a cut-off line, and the last place says how many more there are; it goes to the first of them.
    // Every row's foot is read once and the list written once (a row taken off at a time laid the list out again each time)
    const top = el.getBoundingClientRect().top + el.clientTop, room = el.clientHeight - parseFloat(getComputedStyle(el).paddingBottom || "0");
    const rows = [...el.children], foot = rows.map((r) => r.getBoundingClientRect().bottom - top), lineH = rows[0] ? rows[0].offsetHeight : 28;
    let keep = rows.length; while (keep > 0 && foot[keep - 1] + lineH > room) keep--;   // room for the count's own line under the rows kept
    const more = boardOrder.length - keep, first = ITEMS[board[boardOrder[keep]].i];
    el.innerHTML = boardOrder.slice(0, keep).map(rowOf).join("") +
      `<button type="button" class="kit-row kit-more" data-id="${esc(first.id)}">${esc(t("and {n} more", { n: more }))}</button>`;
  }
  function markVisible() {                                                          // mark the side rows whose cards are on screen
    const el = elCards; const a = el.scrollLeft, b = a + el.clientWidth;
    const on = new Set();
    el.querySelectorAll(".kit-card").forEach((c) => { const x = c.offsetLeft + (c.offsetParent === el ? 0 : c.parentElement.offsetLeft); if (x + c.offsetWidth > a + 4 && x < b - 4) on.add(c.dataset.id); });
    elRank.querySelectorAll(".kit-row").forEach((r) => r.setAttribute("aria-current", on.has(r.dataset.id) ? "true" : "false"));
  }
  function drawToc() {                                                              // the contents: every item with its full title; in a small view the largest groups fold into one row each until it all fits
    const el = elCards; el.className = "kit-cards tocv"; el.style.overflow = "";
    root.classList.remove("short");                                                 // measured against the whole screenful first
    if (narrowNow) { tocHtml(el, new Set()); return; }                              // a narrow view: one column of every group, and the page scrolls
    if (!el.clientWidth || !el.clientHeight) { tocHtml(el, new Set()); return; }    // not laid out yet: every group, fitted when the view is on the page
    const folded = new Set();                                                       // script groups shown as one row instead of their items
    const openGroups = () => GROUPS.filter((g) => !isRow(g) && !isRef(g) && !folded.has(g.name)).sort((a, b) => b.items.length - a.items.length);
    tocHtml(el, folded);
    while (!tocFits(el) && openGroups().length > 1) { folded.add(openGroups()[0].name); tocHtml(el, folded); }   // fold the largest open group
    fitToc();
    const toc = el.querySelector(".kit-toc");                                       // a small kit: the view ends where its contents end, with no empty screen under them
    if (toc && toc.offsetHeight < (el.clientHeight - 4) * 0.7) { toc.style.setProperty("--row-pad", ".28em"); root.classList.add("short"); }
    lastW = el.clientWidth; lastH = el.clientHeight;                                // fitted to this room: not fitted again for the same room
  }
  function tocHtml(el, folded) {                                                    // the contents boxes: open groups with their items, then the folded groups as rows
    const title = (it, g) => it.tko.startsWith(g + ":") ? it.tko.slice(g.length + 1).trim() : it.tko;   // no heading repeated in its own rows
    const row = (g) => {                                                            // one row that opens a whole group
      const k = isRef(g) ? letterOf(g) : g.name[0];                                 // the letter its items start with
      const hd = headOf(g.name), plain = g.name.replace(/^[A-Z]\.\s+/, "");        // its name without its letter (the row shows the letter)
      const short = SHORT[g.name[0]] || (isRow(g) && hd ? hd.tail : plain);         // a deep dive's row says what follows its colon: "이력 {name}" doubled the heading's own words
      const label = g.role === "terms" ? fmt("toc_terms") : isRow(g) ? fmt("toc_deep", { name: short }) : isRef(g) ? refName(g) : short;
      return `<button type="button" data-g="${esc(g.name)}" data-c="${cat(k)}"><span class="kit-id">${esc(k)}</span><span>${esc(fmt("toc_count", { name: label, n: g.items.length }))}</span></button>`;
    };
    el.innerHTML = `<div class="kit-toc">${tocBoxes(folded).map((b) => `<div class="kit-tg${(b.items || b.rows).length <= 12 ? " keep" : ""}"${b.items ? ` data-c="${cat(ITEMS[b.items[0]].id)}"` : ""}><h3>${esc(b.name)}</h3>` +
        (b.rows ? b.rows.map(row).join("")
          : b.items.map((i) => { const it = ITEMS[i]; return `<button type="button" data-id="${esc(it.id)}" data-src="${esc(it.src)}" data-c="${cat(it.id)}"><span class="kit-id">${esc(it.id)}</span><span>${esc(title(it, b.name))}</span></button>`; }).join("")) +
        `</div>`).join("")}</div>`;
  }
  function headContinued(el) {                                                      // a section that runs on into the next column says its name again at that column's top (B11 started a column with no B above it)
    const toc = el.querySelector(".kit-toc"); if (!toc) return;
    const room = el.clientHeight - 4, added = [];
    for (const box of toc.querySelectorAll(".kit-tg")) {
      const parts = box.getClientRects(), head = box.querySelector("h3");             // one rectangle per column the box runs through
      if (parts.length < 2 || !head) continue;
      const rows = [...box.querySelectorAll(":scope > button")].map((b) => [b, b.getBoundingClientRect()]);
      for (let f = 1; f < parts.length; f++) {
        const at = rows.find(([, r]) => r.left >= parts[f].left - 1 && r.left < parts[f].right && r.top >= parts[f].top - 1);   // the first row in that column
        if (!at) continue;
        const again = document.createElement("h3"); again.className = "kit-cont"; again.setAttribute("aria-hidden", "true");   // said once to a screen reader, at the section's start
        again.textContent = head.textContent; at[0].before(again); added.push(again);
      }
    }
    if (added.length && toc.offsetHeight > room) added.forEach((x) => x.remove());   // no room for the names: the columns as they were
  }
  function tocBoxes(folded) {                                                       // one box per open script group; folded groups, deep dives and reference material become rows that open their section
    const out = [], fold = [], rows = [];
    for (const g of GROUPS) (isRow(g) || isRef(g) ? rows : folded.has(g.name) ? fold : out).push(g);
    if (fold.length) out.push({ name: fmt("toc_folded"), rows: fold });
    if (rows.length) out.push({ name: fmt("toc_rows"), rows });
    return out;
  }
  const TOC_COLS = [30, 26, 22, 19, 17, 15, 13];                                    // column widths in ems to try, widest first: fewer wrapped titles when it still fits
  function tocSizer(el) {                                                           // a setter for the contents' column count that also says whether it then fits the area
    const toc = el.querySelector(".kit-toc"); const room = el.clientHeight - 4; const width = toc.clientWidth;
    return (colEm) => {
      toc.style.columnCount = String(Math.max(1, Math.floor((width + GAP) / (colEm * FSB + GAP))));   // as many columns as the width holds
      return toc.offsetHeight <= room;
    };
  }
  function tocFits(el) { const set = tocSizer(el); return TOC_COLS.some((c) => set(c)); }   // fits at some column width?
  function fitToc() {                                                               // the widest columns at which the whole contents fit; otherwise a vertical scroll, never cut text
    const el = elCards; if (!el.querySelector(".kit-toc")) return;
    const set = tocSizer(el);
    const toc = el.querySelector(".kit-toc"); const room = el.clientHeight - 4;
    for (const colEm of TOC_COLS) if (set(colEm)) {                                 // it fits: spread the rows over the height instead of leaving the foot empty
      headContinued(el);                                                            // first, with the rows tight: a section split between columns names itself again at the next one's top
      let lo = 0.16, hi = 0.5;                                                      // row padding in ems, capped: rows spread a little, never into a sparse list
      for (let k = 0; k < 7; k++) { const mid = (lo + hi) / 2; toc.style.setProperty("--row-pad", mid + "em"); if (toc.offsetHeight <= room) lo = mid; else hi = mid; }
      toc.style.setProperty("--row-pad", lo + "em");
      if (toc.offsetHeight > room) { toc.style.setProperty("--row-pad", ".16em"); set(colEm); }   // safety: back to the tight rows
      return;
    }
    set(15); el.style.overflowY = "auto";
  }
  function drawMenu() {                                                             // the section keys in one row, with the open section pressed and in sight
    elMenu.innerHTML = GROUPS.map((g) => {
      const on = mode === "group" && groupName === g.name ? "true" : "false";
      return g.name === FIRST ? `<button type="button" class="btn small" data-g="${esc(g.name)}" aria-pressed="${on}" title="${esc(g.name)}">${esc(fmt("first_group_short"))}</button>`
        : `<button type="button" class="btn small" data-g="${esc(g.name)}" data-c="${cat(isRef(g) ? letterOf(g) : g.name[0])}" aria-pressed="${on}" title="${esc(isRef(g) ? refName(g) : g.name)}">${keyLabel(g)}</button>`;
    }).join("");
    const on = elMenu.querySelector('[aria-pressed="true"]');                       // the row slides to the open section, never the page
    requestAnimationFrame(() => {
      if (on && (on.offsetLeft < elMenu.scrollLeft || on.offsetLeft + on.offsetWidth > elMenu.scrollLeft + elMenu.clientWidth)) elMenu.scrollLeft = on.offsetLeft - 8;
      edgeFade(elMenu);                                                             // its edges say where more sections are
    });
  }
  function show() {                                                                 // rank (or pick the group), then draw everything on one screen
    narrowNow = narrow();                                                           // first, before anything is written
    clearTimeout(tRest);                                                            // a board's later screens are not placed over the contents
    if (mode !== "toc" && elCards.classList.contains("tocv")) elCards.innerHTML = "";   // the contents go before the board's classes come: laid out under them, the contents took 170 ms
    root.classList.toggle("browse", mode === "toc");                                // the contents take the whole width: no side list
    root.classList.toggle("narrow", narrowNow);                                     // one column that scrolls down
    homeKey.setAttribute("aria-pressed", mode === "toc" ? "true" : "false");        // on the contents now
    drawMenu();
    if (mode === "toc") { results = []; words = []; elRank.innerHTML = ""; drawToc(); return; }
    root.classList.remove("short");                                                 // answers take the whole screenful
    if (mode === "group") {                                                         // a section from the keys: its items in file order
      results = GROUP_OF.get(groupName).items.map((i) => ({ i, score: 0, kn: 0, dn: 0, sim: null, why: null })); words = []; weak = false;
      layout(); return;
    }
    const r = rank(current); words = r.words; weak = r.weak;
    let list = r.list;
    const hit = BY_ID_LC.get(current.toLowerCase());                                // a typed or clicked item number
    if (hit !== undefined) {                                                        // that item first, then the rest of its group
      const g = groupOf(ITEMS[hit]);
      list = [hit, ...GROUP_OF.get(g).items.filter((i) => i !== hit)].map((i) => ({ i, score: 0, kn: 0, dn: 0, sim: null, why: null }));
      weak = false; words = [];
    }
    results = list;
    layout();
  }
  function page(d) {                                                                // slide the board one screen to the right or left
    if (mode === "toc") return;
    elCards.scrollBy({ left: d * (elCards.clientWidth + GAP), behavior: "smooth" });
  }
  function pick(id) {                                                               // bring a card on the board into view and mark it for a moment
    const el = elCards; const c = [...el.querySelectorAll(".kit-card")].find((x) => x.dataset.id === id); if (!c) return;
    if (narrowNow) { c.scrollIntoView({ block: "start", behavior: "smooth" }); }    // the page scrolls to it
    else {
      const holder = c.parentElement; const x = holder.offsetLeft + (holder.classList.contains("kit-slot") || holder.classList.contains("kit-block") ? 0 : c.offsetLeft);
      const a = el.scrollLeft, b = a + el.clientWidth;
      if (x < a || x + c.offsetWidth > b) el.scrollTo({ left: Math.floor(x / (geo.cw + GAP)) * (geo.cw + GAP), behavior: "smooth" });
    }
    c.classList.remove("flash"); void c.offsetWidth; c.classList.add("flash");
    qIn.focus({ preventScroll: true }); qIn.select();                               // the next question replaces the old one
  }
  function goHome() {                                                               // back to the contents
    qIn.value = ""; current = ""; mode = "toc"; groupName = null;
    if (inflight) inflight.abort();
    show(); qIn.focus({ preventScroll: true });
  }
  function openGroup(name) {                                                        // a section from the keys
    qIn.value = ""; current = ""; mode = "group"; groupName = name;
    show(); settle(); qIn.focus({ preventScroll: true });
  }
  function setLang(v) {                                                             // KO, EN or both; the board is fitted again since the text length changes
    lang = v; store.set("lang", v);
    langSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.lang === v ? "true" : "false"));
    if (mode !== "toc") layout();
  }
  function search(q) {                                                              // put a query in the box and run it
    qIn.value = q; qIn.dispatchEvent(new Event("input")); qIn.focus({ preventScroll: true });
  }
  function settle() {                                                               // the whole view on the screen, under the panel's bar: a question is read without scrolling
    if (narrowNow || !root.isConnected) return;                                     // a narrow view scrolls with the page
    const barH = (document.getElementById("top") || { offsetHeight: 0 }).offsetHeight;   // the panel's bar stays above it
    const top = root.getBoundingClientRect().top, want = barH + 12;
    if (Math.abs(top - want) > 24) window.scrollTo({ top: Math.max(0, window.scrollY + top - want), behavior: "smooth" });
  }

  // ---------------------------------------------------------------- events
  let tKey = 0, tDense = 0;                                                         // the keyword fallback timer and the similarity request timer
  qIn.addEventListener("input", (e) => {
    // A syllable still being composed shows as a lone jamo at the end ("느려ㅈ"); it is not part of the question yet.
    const q = e.target.value.replace(/[ㄱ-ㆎ]+$/, "").trim();
    clearTimeout(tKey); clearTimeout(tDense);
    if (q === current && e.target.value.trim()) return;                             // only the half-typed syllable changed
    current = q;
    if (!q) { if (mode === "search") goHome(); return; }                            // an emptied box goes back to the contents
    mode = "search"; groupName = null;
    if (BY_ID_LC.has(q.toLowerCase())) { show(); return; }                          // an item number needs no ranking
    if (engine !== "on") { tKey = setTimeout(() => { if (current === q) show(); }, 80); return; }   // the model is off: keywords only
    // Draw once, with both halves, when the server answers; keywords alone only if it is slow. One draw, no swap.
    tDense = setTimeout(() => fetchDense(q), 220);                                  // a pause in the typing asks the server (each key would ask it again)
    tKey = setTimeout(() => { if (current === q) show(); }, 420);
  });
  qIn.addEventListener("focus", settle);                                            // about to type a question: the board is brought whole onto the screen
  homeKey.addEventListener("click", goHome);
  elMenu.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) openGroup(b.dataset.g); });
  elMenu.addEventListener("wheel", (e) => {                                          // a mouse's wheel slides the one row of sections
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX) || elMenu.scrollWidth <= elMenu.clientWidth + 1) return;
    elMenu.scrollLeft += e.deltaY; e.preventDefault();
  }, { passive: false });
  elRank.addEventListener("click", (e) => { const b = e.target.closest(".kit-row"); if (b) pick(b.dataset.id); });
  elCards.addEventListener("click", (e) => {
    const b = e.target.closest(".kit-tg button"); if (!b) return;                   // a contents entry
    if (b.dataset.g) openGroup(b.dataset.g); else { search(b.dataset.id); settle(); }
  });
  langSeg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setLang(b.dataset.lang); });
  if (sw) sw.addEventListener("click", switchEngine);
  function applyPrefs() {                                                           // the one type size and the column width, everywhere in the view at once
    root.style.setProperty("--kit-fs", FSB + "px");
    prefsRow.querySelectorAll('[data-pref="fs"] button').forEach((b) => b.setAttribute("aria-pressed", Number(b.dataset.v) === FSB ? "true" : "false"));
    prefsRow.querySelectorAll('[data-pref="colw"] button').forEach((b) => b.setAttribute("aria-pressed", Number(b.dataset.v) === COLW ? "true" : "false"));
  }
  function refit() { if (gone) return; narrowNow = narrow(); root.classList.toggle("narrow", narrowNow); if (mode === "toc") drawToc(); else layout(); }   // drawn again for the room there is
  prefsRow.addEventListener("click", (e) => {                                       // remember a setting and redraw with it
    const b = e.target.closest("button"); if (!b) return;
    const name = b.parentElement.dataset.pref, v = Number(b.dataset.v);
    if (name === "fs") { FSB = v; store.set("fs", v); } else { COLW = v; store.set("colw", v); }
    applyPrefs(); refit();
  });
  prefsKey.addEventListener("click", () => {                                        // the settings row under the keys
    prefsRow.hidden = !prefsRow.hidden; prefsKey.setAttribute("aria-expanded", String(!prefsRow.hidden));
    refit();                                                                        // the board gives up or takes back the row's height
  });
  let lastWheel = 0;                                                                // time of the last screen turned by the wheel
  elCards.addEventListener("wheel", (e) => {                                        // a vertical wheel turns the board a screen at a time
    if (mode === "toc" || narrowNow || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;   // the contents and a narrow view scroll as the page does
    if (elCards.scrollWidth <= elCards.clientWidth + 1) return;                     // one screen of answers: the wheel is the page's
    e.preventDefault();
    const now = Date.now(); if (now - lastWheel < 420) return; lastWheel = now;
    page(e.deltaY > 0 ? 1 : -1);
  }, { passive: false });
  let tScroll = 0, keepLeft = 0;                                                    // one mark update per frame while sliding; where the board stands, for a redraw of the panel around it
  elCards.addEventListener("scroll", () => { keepLeft = elCards.scrollLeft; cancelAnimationFrame(tScroll); tScroll = requestAnimationFrame(markVisible); });
  let lastEsc = 0;                                                                  // time of the previous Escape
  root.addEventListener("keydown", (e) => {                                         // the keyboard, while it is inside the view
    if (e.altKey && !e.ctrlKey) {                                                   // language shortcuts; Alt+letters open browser menus on Windows, so digits
      const v = { "1": "both", "2": "ko", "3": "en" }[e.code.replace("Digit", "")] || null;
      if (v) { setLang(v); e.preventDefault(); e.stopPropagation(); } return;           // the view's own keys: the panel's Alt+1 and on (its views) do not also run
    }
    const inBox = document.activeElement === qIn;
    if (e.key === "Enter" && inBox && current) {                                    // Enter: search now (after pasting a question)
      clearTimeout(tKey); clearTimeout(tDense); if (engine === "on") fetchDense(current); else show(); e.preventDefault(); return;
    }
    if (["ArrowDown", "PageDown", "ArrowUp", "PageUp"].includes(e.key) && mode !== "toc" && !narrowNow) { page(/Down/.test(e.key) ? 1 : -1); e.preventDefault(); return; }   // a narrow view scrolls by itself
    if (e.key === "Escape") {                                                       // once: keep the answers and select the question so the next one replaces it; twice: back to the contents
      if (mode === "toc" && !qIn.value) return;                                     // nothing of the view's to leave: the panel's own Escape
      const now = Date.now();
      if (now - lastEsc < 600 || (!qIn.value && mode !== "group")) { goHome(); lastEsc = 0; } else { qIn.focus({ preventScroll: true }); qIn.select(); lastEsc = now; }
      e.preventDefault(); e.stopPropagation(); return;
    }
    if (e.key === "/" && !inBox) { qIn.focus({ preventScroll: true }); qIn.select(); e.preventDefault(); return; }
    if (!inBox && e.key.length === 1 && e.key !== " " && !e.ctrlKey && !e.metaKey && !e.target.closest("input, textarea, select")) { qIn.focus({ preventScroll: true }); qIn.select(); }   // a new question replaces the old one (Space stays a key's own: it presses the key in focus)
  });
  let lastW = 0, lastH = 0, tSize = 0;                                              // the room last fitted, and the wait before fitting again
  const watch = window.ResizeObserver ? new ResizeObserver(() => {                  // the view's own room changed: the window, the panel's list folded away, the settings row
    const w = elCards.clientWidth, hh = elCards.clientHeight;
    if (!w || (w === lastW && hh === lastH)) return;                                // off the page, or the same room
    lastW = w; lastH = hh;
    clearTimeout(tSize); tSize = setTimeout(refit, 120);
  }) : null;
  if (watch) watch.observe(elCards);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { measured.clear(); if (root.isConnected) refit(); });   // fitted again once the fonts are in, measured again in them

  // ---------------------------------------------------------------- start
  langSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.lang === lang ? "true" : "false"));   // remembered language
  applyPrefs();                                                                     // remembered type size and column width
  show();                                                                           // the contents
  if (sw) health();                                                                 // how the similarity model is, only when the server has one
  return {
    el: root,                                                                       // placed by the panel wherever the tab is drawn
    query: () => qIn.value,                                                         // the question in the box, carried over when the kit's files change
    search,                                                                         // put a question in the box and run it
    attached() {                                                                    // the panel drew itself again around the view: the board back where it stood
      if (gone) return;
      if (elCards.clientWidth !== lastW || elCards.clientHeight !== lastH || !elCards.childElementCount) { lastW = elCards.clientWidth; lastH = elCards.clientHeight; refit(); }   // another room, or a board emptied while the view was off the page
      else if (mode !== "toc" && keepLeft) { const left = keepLeft; elCards.style.scrollBehavior = "auto"; elCards.scrollLeft = left; elCards.style.scrollBehavior = ""; }
    },
    card(id) {                                                                      // one script as the board draws it, for practice's feedback (interview.js): in a box of the view's type and language
      const i = BY_ID.get(id); if (i === undefined) return null;                    // not a script of this kit
      const box = h("div", { class: "kit kit-one" }); box.style.setProperty("--kit-fs", FSB + "px");   // the hues and the type the view has
      const starts = secStarts; secStarts = new Set();                              // a card alone starts no section
      box.innerHTML = `<div class="kit-cards phone lang-${lang}">${cardHtml({ i, score: 0, kn: 0, dn: 0, sim: null, why: null }, 1)}</div>`;   // escaped by the engine, as on the board
      secStarts = starts;
      return box;
    },
    destroy() { gone = true; clearTimeout(tHealth); clearTimeout(tKey); clearTimeout(tDense); clearTimeout(tSize); clearTimeout(tRest); if (inflight) inflight.abort(); if (watch) watch.disconnect(); },
  };
}
