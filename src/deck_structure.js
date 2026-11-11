// The deck's structure: chapter dividers, the contents slide, the side rail
// and the project slide header. Every value comes
// from the normalized profile (src/profile_loader.js), so any profile gets the same structure:
//   chapter divider  logo, chapter number, company, role, period, location, clients, a lead paragraph, the chapter's projects with
//                    their page numbers, the core stack and the career timeline with this chapter's bar dark
//   contents         chapter bars sized by slide count, then each chapter with its projects, taglines and pages
//   rail             book-edge tabs on the left, one per chapter, the current one dark, a marker at the current slide
//   project header   breadcrumb (chapter number, company, PROJECT n / m, period), title with a one-line tagline, client logo plate,
//                    and a meta line (role, context, stack) with scale chips
const fs = require("fs");                         // logo size lookups
const path = require("path");                     // tile paths
const { h } = require("./portfolio/deck");        // escaping and rich text of the deck
const { tw, outline } = require("./portfolio/draw");   // font metrics and glyph outlines (rail labels are outlines, not text)

const esc = h.esc;                                // HTML escaping

// Words of the deck structure per language
const WORDS = {
  ko: { chapter: "CHAPTER", projects: "PROJECTS", project: "PROJECT", role: "직무", period: "기간", place: "근무지", clients: "고객",
        overview: "개요", contents: "목차", stack: "주요 기술", pRole: "역할", pContext: "맥락", pStack: "환경", timeline: "경력 타임라인",
        timelineNote: "진하게 칠한 막대가 이 챕터", structure: "구성", structureNote: "막대 길이는 챕터의 장 수, 아래는 쪽 번호" },
  en: { chapter: "CHAPTER", projects: "PROJECTS", project: "PROJECT", role: "Role", period: "Period", place: "Location", clients: "Clients",
        overview: "Overview", contents: "Contents", stack: "Core stack", pRole: "Role", pContext: "Context", pStack: "Stack", timeline: "Career timeline",
        timelineNote: "The dark bar is this chapter", structure: "Structure", structureNote: "Bar length shows slides per chapter, with page numbers" },
};

// PNG width and height from its header (logo plates keep their aspect)
function pngSize(file) {
  const b = fs.readFileSync(file);                // the image bytes
  return [b.readUInt32BE(16), b.readUInt32BE(20)];   // IHDR width and height
}

// The eyebrow line above a slide title: parts with classes, and an optional right-hand label
function eyebrow(parts, right) {
  return `<div class="eyebrow">${parts.map(([cls, t]) => `<span${cls ? ` class="${cls}"` : ""}>${esc(t)}</span>`).join("")}` +
    (right ? `<span class="en">${esc(right)}</span>` : "") + `</div>`;
}

// Logo plates at the end of a project title: each tile at a height that gives wide and square logos the same visual weight
function logoPlates(files) {
  const shown = files.filter(f => f && fs.existsSync(f));   // only logos that exist
  if (!shown.length) return "";
  return `<span class="logos">` + shown.map(f => {
    const [w, ht] = pngSize(f), asp = w / ht;               // aspect of the tile
    const hpx = Math.round(Math.max(14, Math.min(asp < 1.3 ? 28 : asp < 2.5 ? 30 : 26, Math.sqrt(1920 / asp))));   // the logo plate's height
    return `<span class="lg"><img src="file://${esc(f)}" alt="" style="height:${hpx}px"></span>`;
  }).join("") + `</span>`;
}

// The project slide header: rewrites the h.sec output of a project slide with breadcrumb, tagline, logo plate and meta line
function projectHeader(html, o) {
  const W = WORDS[o.lang];
  const crumb = eyebrow([["no", o.no], ["", String(o.chapterName).toUpperCase()], ["pj", `${W.project} ${String(o.index).padStart(2, "0")} / ${String(o.total).padStart(2, "0")}`]], o.period || "");
  const meta = [[W.pRole, o.role], [W.pContext, o.context], [W.pStack, o.stack]].filter(([, v]) => v)
    .map(([k, v]) => `<span><b>${esc(k)}</b>${esc(v)}</span>`).join("") +
    (o.chips && o.chips.length ? `<span class="chips">${o.chips.map(c => `<i>${esc(c)}</i>`).join("")}</span>` : "");
  let out = html.replace("<!--EYEBROW-->", crumb);           // breadcrumb in the eyebrow slot of h.sec
  if (o.logos) out = out.replace(/(<\/h1>)(<\/div>)/, `$1${logoPlates(o.logos)}$2`);   // logo plate at the end of the title row
  if (meta) out = out.replace(/(<div class="ttl">[\s\S]*?<\/div>)(<\/div>)/, `$1<div class="pmeta">${meta}</div>$2`);   // meta line under the title row
  return out;
}

// One chapter divider: left navy panel (logo, number, name, meta, lead), right panel (projects with pages, core stack, timeline)
function chapterSlide(ch, lang) {
  const W = WORDS[lang], rows = ch.projects;                 // the edition's words and the chapter's projects
  const mode = rows.length > 10 ? "two" : rows.length > 5 ? "dense" : rows.length === 1 ? "solo" : "rich";   // the list modes
  const half = Math.ceil(rows.length / 2);                   // rows per column when the list takes two columns
  // A title on one line (the probe holds it there): the project's short name when the title is wider than the column. Measured: 736 px of panel less number, period, page and gaps
  const [room, size] = mode === "two" ? [270, 13.5] : mode === "dense" ? [510, 13.5] : [510, 15];   // the title's width and size in this list
  const title = p => (p.short && tw(String(p.title), size, true) > room && tw(String(p.short), size, true) <= room ? p.short : p.title);
  // One project line: number, title (with tagline and role and context unless the list is dense), period and page
  const row = (p, i) => mode === "two"
    ? `<div class="p"><span class="num">${String(i + 1).padStart(2, "0")}</span><span class="t">${esc(title(p))}<span class="per">${esc(p.period || "")}</span></span>` +
      `<span class="pg">${p.page}</span></div>`
    : `<div class="p"><span class="num">${String(i + 1).padStart(2, "0")}</span><span class="t">${esc(title(p))}` +
      (mode === "dense" ? "" : (p.tagline ? `<span class="tg">${esc(p.tagline)}</span>` : "") +
        ((p.role || p.context) ? `<span class="rc">${p.role ? `<b>${esc(W.pRole)}</b>${esc(p.role)}` : ""}${p.context ? `<b>${esc(W.pContext)}</b>${esc(p.context)}` : ""}</span>` : "")) +
      `</span><span class="per">${esc(p.period || "")}</span><span class="pg">${p.page}</span></div>`;
  // The core stack band: category and names per row, folded to two columns when the list is dense or the stack is long
  const skills = mode !== "two" && ch.stack && ch.stack.length
    ? `<div class="skills${mode === "dense" || ch.stack.length > 6 ? " compact" : " roomy"}${rows.length <= 2 ? " airy" : ""}"><div class="lab">${esc(W.stack.toUpperCase())}</div>` +
      ch.stack.map(([k, items]) => `<div class="r"><b>${esc(k)}</b><span class="names">${esc([].concat(items).join(", "))}</span></div>`).join("") + `</div>` : "";
  // Role, period, location and clients as label and value pairs (empty ones are left out)
  const meta = [[W.role, ch.title], [W.period, ch.period], [W.place, ch.place], [W.clients, ch.clients]].filter(([, v]) => v)
    .map(([k, v]) => `<b>${esc(k)}</b><span>${esc(v)}</span>`).join("");
  // The chapter's career timeline (this role dark), drawn by overview_figures.py; none when the resume build did not run
  const timeline = ch.timeline ? `<figure class="fig natural chrome"><div class="frame bare"><img src="file://${esc(ch.timeline)}" alt="" style="width:100%"></div>` +
    `<figcaption><b>${esc(W.timeline)}</b> ${esc(W.timelineNote)}</figcaption></figure>` : "";
  // Left panel: logo, number, CHAPTER, name, English name (unless the name holds it), meta and lead
  return `<div class="cl">` +
    (ch.logo ? `<div class="logo"><img src="file://${esc(ch.logo)}" alt=""></div>` : "") +
    `<div class="no">${esc(ch.no)}</div><div class="kind">${W.chapter}</div><h1>${esc(ch.name)}</h1>` +
    (ch.enName && !String(ch.name).toLowerCase().includes(String(ch.enName).toLowerCase()) ? `<div class="enm">${esc(String(ch.enName).toUpperCase())}</div>` : "") +
    `<div class="meta">${meta}</div>` + (ch.lead ? `<div class="lead">${esc(ch.lead)}</div>` : "") + `</div>` +
    // Right panel: project count, the project list, the stack band and the timeline, with flexible spacers between them
    `<div class="cr">${eyebrow([["no", ch.no], ["", W.projects]], `${rows.length} ${rows.length > 1 ? W.projects : W.project}`)}` +
    `<div class="plist ${mode}${rows.length <= 2 ? " few" : ""}"${mode === "two" ? ` style="grid-template-rows: repeat(${half}, auto)"` : ""}>` + rows.map(row).join("") + `</div>` +
    `<div class="sp"></div>` + skills + `<div class="sp"></div>` + timeline + `</div>`;
}

// The contents slide body: chapter bars (width by slide count, page ranges below), then the chapter groups in three columns
function contentsBody(groups, lang, total) {
  const W = WORDS[lang], dash = lang === "en" ? "-" : "~"; // the edition's words and range mark
  const count = g => g.last - g.page + 1;                   // slides in a chapter, the divider included
  // One navy bar per chapter, as wide as its share of slides, with its page range under it
  const bars = `<div style="display:flex; gap:4px; margin-top:6px">` + groups.map(g =>
    `<div style="flex:${count(g)} 1 0; min-width:0"><div style="background:var(--navy); color:#fff; border-radius:4px; padding:7px 6px; font-size:12px; font-weight:700; text-align:center; white-space:nowrap; overflow:hidden">` +
    `${esc(g.no)} ${esc(g.name)}</div><div style="text-align:center; font-size:11px; color:var(--g500); margin-top:5px">${g.page}${dash}${g.last}</div></div>`).join("") + `</div>` +
    `<div class="cap" style="margin-top:2px"><b>${esc(W.structure)}</b> ${esc(W.structureNote)}</div>`;
  // The chapter groups (three balanced columns in the theme): number, name and page, then each project with its tagline and page
  const toc = `<div class="toc2">` + groups.map(g =>
    `<div class="g"><div class="gh"><span class="no">${esc(g.no)}</span><b>${esc(g.name)}</b><span class="pg">${g.page}</span></div>` +
    g.items.map(it => `<div class="it"><span class="t">${esc(it.title)}${it.tagline ? `<em>${esc(it.tagline)}</em>` : ""}</span><span class="pg">${it.page}</span></div>`).join("") +
    `</div>`).join("") + `</div>`;
  return bars + toc;                                         // the slide body under the title
}

// Rail tabs: an overview tab, then one tab per chapter with a height in proportion to its slide count (at least a minimum)
function rails(total, groups, lang, { top = 30, bottom = 664, gap = 4, min = 58 } = {}) {
  // The overview tab (contents and career slides) and one tab per chapter, each with its first and last page
  const segs = [{ no: "", name: WORDS[lang].overview, from: 2, to: groups[0].page - 1 },
    ...groups.map((g, i) => ({ no: g.no, name: g.name, from: g.page, to: i + 1 < groups.length ? groups[i + 1].page - 1 : total - 1 }))];
  const H = bottom - top - gap * (segs.length - 1);         // height shared by the tabs
  // A tab's minimum height: Latin names are turned and need their length, Hangul is stacked one character per line
  const need = x => (lang === "en" || /^[A-Za-z][A-Za-z .]*$/.test(x.name)) ? (x.no ? 14 : 0) + tw(x.name, 9.5, "semi") + 14 : (x.no ? 14 : 0) + [...x.name].length * 11 + 10;
  const n = segs.map(x => Math.max(1, x.to - x.from + 1)), mins = segs.map(x => Math.max(min, need(x)));   // slides per tab, minimum heights
  const fixed = new Set();                                  // tabs held at their minimum
  let hs;
  for (;;) {                                                // share the rest in proportion, fixing tabs that fall below their minimum
    const free = H - [...fixed].reduce((a, i) => a + mins[i], 0);   // height left for the tabs not held
    const nf = n.reduce((a, v, i) => a + (fixed.has(i) ? 0 : v), 0) || 1;   // their slide count
    hs = n.map((v, i) => fixed.has(i) ? mins[i] : free * v / nf);   // proportional heights
    const lack = hs.findIndex((v, i) => !fixed.has(i) && v < mins[i]);   // a tab under its minimum
    if (lack < 0) break;                                    // all fit
    fixed.add(lack);                                        // hold it at its minimum and share again
  }
  let y = top;                                               // tabs stack from the top
  segs.forEach((x, i) => { x.y = y; x.h = hs[i]; y += hs[i] + gap; });   // each tab's top and height
  const at = [];                                             // per slide: the tab index and the marker's height
  for (let p = 1; p <= total; p++) {                        // where the marker sits on each slide (none on the cover and the end)
    const k = p === 1 || p === total ? -1 : segs.findIndex(x => p >= x.from && p <= x.to);
    if (k < 0) { at.push(null); continue; }                 // the cover and the end have no rail
    const x = segs[k], slot = x.h / (x.to - x.from + 1);    // the tab's height per slide
    at.push({ k, y: x.y + slot * (p - x.from + 0.5) });     // the marker in the middle of this slide's slot
  }
  return { segs, at };                                       // tabs and markers for railHtml
}

// A tab label as glyph outlines: the number on top, the name turned to read top down (Latin) or stacked (Hangul)
function tabLabel(no, name, w, ht, lang) {
  if (lang === "en" || /^[A-Za-z][A-Za-z .]*$/.test(name)) {
    const nm = outline(name, 9.5, "semi"), num = no ? outline(no, 9, true) : null;
    const numH = num ? num.bb.y2 - num.bb.y1 : 0, g = num ? 5 : 0, len = nm.bb.x2 - nm.bb.x1;
    let y = (ht - (numH + g + len)) / 2;
    const paths = [];
    if (num) { paths.push(`<path transform="translate(${((w - (num.bb.x2 - num.bb.x1)) / 2 - num.bb.x1).toFixed(2)},${(y - num.bb.y1).toFixed(2)})" d="${num.d}"/>`); y += numH + g; }
    paths.push(`<path transform="translate(${(w / 2 + (nm.bb.y1 + nm.bb.y2) / 2).toFixed(2)},${(y - nm.bb.x1).toFixed(2)}) rotate(90)" d="${nm.d}"/>`);
    return `<svg class="lbl" viewBox="0 0 ${w} ${ht.toFixed(1)}" width="${w}" height="${ht.toFixed(1)}" fill="currentColor" aria-hidden="true">${paths.join("")}</svg>`;
  }
  const items = [...(no ? [{ s: no, size: 9, bold: true, gap: 5 }] : []), ...[...name].map(c => ({ s: c, size: 9.5, bold: "semi", gap: 1.5 }))];
  const total = items.reduce((t, it, i) => t + it.size + (i < items.length - 1 ? it.gap : 0), 0);
  let y = (ht - total) / 2;
  const paths = items.map(it => {
    const o = outline(it.s, it.size, it.bold);
    const gx = (w - (o.bb.x2 - o.bb.x1)) / 2 - o.bb.x1, gy = y + (it.size - (o.bb.y2 - o.bb.y1)) / 2 - o.bb.y1;
    y += it.size + it.gap;
    return `<path transform="translate(${gx.toFixed(2)},${gy.toFixed(2)})" d="${o.d}"/>`;
  });
  return `<svg class="lbl" viewBox="0 0 ${w} ${ht.toFixed(1)}" width="${w}" height="${ht.toFixed(1)}" fill="currentColor" aria-hidden="true">${paths.join("")}</svg>`;
}

// The rail of slide p (1-based); chapter dividers are navy, so their rail is drawn in the dark variant
function railHtml(R, p, dark, lang) {
  const a = R.at[p - 1];
  if (!a) return "";
  return `<nav class="rail${dark ? " dark" : ""}">` + R.segs.map((x, i) => {
    const on = i === a.k, w = on ? 27 : 22;
    return `<div class="seg${on ? " on" : ""}" data-name="${esc(x.name)}" style="top:${x.y.toFixed(1)}px;height:${x.h.toFixed(1)}px">` + tabLabel(x.no, x.name, w, x.h, lang) + `</div>`;
  }).join("") + `<i class="here" style="top:${a.y.toFixed(1)}px"></i></nav>`;
}

// The cover's career path: one station per role from the oldest to the newest on a line that darkens toward today. Above a station
// its phase and years, below it the logo and short name, the title, one line on the work and the key projects (roles[].journey)
function journey(stations) {
  const n = stations.length;
  if (!n) return "";
  const shade = i => (n === 1 ? 1 : i / (n - 1));                       // 0 oldest, 1 newest
  const col = t => `color-mix(in srgb, var(--navy) ${Math.round(t * 100)}%, var(--b3))`;   // the colour set's pale step to its dark one
  const cells = stations.map((s, i) => `<div style="display:flex; flex-direction:column; align-items:center; text-align:center; min-width:0">` +
    `<div style="font-size:11.5px; font-weight:700; color:var(--blue); letter-spacing:0.6px; height:16px">${esc(s.phase || "")}</div>` +
    `<div style="font-size:11.5px; font-weight:700; color:var(--g500); margin-top:4px">${esc(s.years || "")}</div>` +
    `<div style="width:14px; height:14px; border-radius:7px; background:${col(shade(i))}; margin:9px 0 10px 0; position:relative; z-index:1"></div>` +
    `<div style="display:flex; align-items:center; gap:7px; font-size:15px; font-weight:700; color:var(--ink2)">` +
    (s.logo ? `<img src="file://${esc(s.logo)}" alt="" style="height:20px; width:20px">` : "") + `<span>${esc(s.name)}</span></div>` +
    (s.title ? `<div style="font-size:11.5px; color:var(--blue); margin-top:4px">${esc(s.title)}</div>` : "") +
    (s.line ? `<div style="font-size:11.5px; color:var(--g900); margin-top:4px">${esc(s.line)}</div>` : "") +
    (s.key ? `<div style="font-size:11.5px; font-weight:700; color:var(--ink2); margin-top:4px">${esc(s.key)}</div>` : "") + `</div>`).join("");
  // The line joins the first and the last dot (it runs between the centers of the outer columns, behind the dots)
  const inset = 50 / n;
  return `<div class="journey" style="position:relative"><div style="position:absolute; left:${inset}%; right:${inset}%; top:47px; height:3px; ` +
    `background:linear-gradient(90deg, var(--b3), var(--navy)); border-radius:2px"></div>` +
    `<div style="display:grid; grid-template-columns:repeat(${n}, minmax(0, 1fr)); column-gap:12px">${cells}</div></div>`;
}

module.exports = { WORDS, eyebrow, logoPlates, projectHeader, chapterSlide, contentsBody, rails, railHtml, journey };
