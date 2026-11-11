// Packer output goes through here so every paragraph carries autoSpaceDE/DN = 0.
//
// Word inserts a gap between a digit and the Hangul that follows it, so a number
// written directly before a Hangul unit word renders with a visible space. The
// OOXML switch that turns this off is w:autoSpaceDE and w:autoSpaceDN, which the
// docx package does not expose, so the attributes are written into
// word/document.xml after packing.
//
// w:pPr children are order-sensitive. Per CT_PPrBase the pair sits after
// keepNext, pBdr, tabs and the rest of the early group, and before spacing,
// ind, jc and rPr. Inserting it anywhere else makes Word repair the file.
//
// LibreOffice ignores both attributes on import, so the PDF produced by
// run.sh still shows the gap; the docx opened in Word does not. Measured at
// 300dpi, the gap is 15px against a 22px space, and character spacing down to
// -16 twips does not close it, so there is no LibreOffice-side fix to apply here.
const fs = require("fs");
const JSZip = require("jszip");
const { Packer } = require("docx");

const AUTOSPACE = '<w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/>';

// LibreOffice ignores the attributes above, so the gap is also closed from the
// text side: a WORD JOINER between a digit and the Hangul that follows it
// suppresses the automatic spacing in both renderers. Measured at 300dpi, the gap
// falls from 14px to 6px, which is the glyph's own sidebearing.
// U+2060 is used rather than U+200B because it carries no break opportunity.
// A checker that matches text in a DOCX has to strip U+2060 first, so the invisible
// character cannot hide a banned term.
const WJ = "\u2060";
// Particles after Latin words are written attached to them, so the joiner is also put between a Latin letter or a
// closing bracket and the Hangul that follows. Without it the PDF showed a gap between a Latin word and its particle
// even though the source text had none.
// The same automatic gap also appears between Hangul and a Latin letter that follows it, so a Hangul word directly
// followed by an acronym looked as if a space separated them (1.8pt at 9pt), so the joiner goes there too.
// A number and the counter after it stay on one line ("100여 개"): src/check_render.py reads a split there as a defect.
const COUNTER = /([0-9][0-9,]*\s*[만억천백십]*여?) (?=(?:시간|회|건|대|장|개|명|쪽|종|배|초|분|주|월|년|행|번|권|편)(?:[^\uAC00-\uD7A3]|$|을|를|이|가|은|는|과|와|씩|째|당|짜리|밖에|만큼|뿐))/g;
const joinDigitHangul = (t) => {
  t = t.replace(COUNTER, "$1\u00A0");
  // Hangul after a digit, a Latin letter or a closing bracket
  t = t.replace(/([0-9A-Za-z\)\]%])(?=[\uAC00-\uD7A3])/g, "$1" + WJ);
  // A Latin letter after Hangul
  return t.replace(/([\uAC00-\uD7A3])(?=[A-Za-z])/g, "$1" + WJ);
};
// first element of the group that must follow autoSpaceDN
const AFTER = /<w:(bidi|adjustRightInd|snapToGrid|spacing|ind|contextualSpacing|jc|textAlignment|outlineLvl|rPr|sectPr)[ />]/;

function withAutoSpace(pPrInner) {
  const m = pPrInner.match(AFTER);
  return m === null
    ? pPrInner + AUTOSPACE
    : pPrInner.slice(0, m.index) + AUTOSPACE + pPrInner.slice(m.index);
}

// Blind edition, for a copy to show in public (OFFEROWL_BLIND=1). Text that matches the mask patterns of src/blind.json is
// replaced by square glyphs, and that run gets a background (w:shd) in the mask_fill color, so it reads as a solid bar.
// The original characters remain neither in the docx nor in the PDF text layer. When a run is split, the original run
// properties (w:rPr) carry over to each piece.
const BL = require("./blind");
const unesc = s => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
// Elements of CT_RPr that must come after w:shd; the shading is inserted before the first of them (a wrong order makes
// Word repair the file)
const SHD_AFTER = /<w:(fitText|vertAlign|rtl|cs|em|lang|eastAsianLayout|specVanish|oMath)[ />]/;
// Elements of CT_RPr that must come after w:color. The square glyph of a bar is colored like its background
const COLOR_AFTER = /<w:(spacing|w|kern|position|sz|szCs|highlight|u|effect|bdr|shd|fitText|vertAlign|rtl|cs|em|lang|eastAsianLayout|specVanish|oMath)[ />]/;
// Elements of CT_RPr that must come after w:w (horizontal scale)
const W_AFTER = /<w:(kern|position|sz|szCs|highlight|u|effect|bdr|shd|fitText|vertAlign|rtl|cs|em|lang|eastAsianLayout|specVanish|oMath)[ />]/;
const put = (inner, el, after) => { const m = inner.match(after); return m ? inner.slice(0, m.index) + el + inner.slice(m.index) : inner + el; };
// Run properties of a bar piece: the original properties plus a mask_fill background, the square glyph in that same
// color, and a horizontal scale (%) that makes the bar as wide as the original text
function maskRPr(rPr, scale) {
  let inner = (rPr || "<w:rPr></w:rPr>").replace(/^<w:rPr>|<\/w:rPr>$/g, "")
    .replace(/<w:shd [^>]*\/>|<w:highlight [^>]*\/>|<w:spacing [^>]*\/>|<w:w [^>]*\/>|<w:color [^>]*\/>/g, "");
  inner = put(inner, `<w:color w:val="${BL.T.mask_fill}"/>`, COLOR_AFTER);
  inner = put(inner, `<w:w w:val="${scale}"/>`, W_AFTER);
  inner = put(inner, `<w:shd w:val="clear" w:color="auto" w:fill="${BL.T.mask_fill}"/>`, SHD_AFTER);
  return "<w:rPr>" + inner + "</w:rPr>";
}
// LibreOffice automatically adds a gap of 0.2 of the font size where Latin letters and Hangul touch (department names,
// for example): measured 1.8pt at 9pt and 1.7pt at 8.5pt. The square glyph counts as a Hangul-side character, so that
// gap vanished and the text after a bar moved closer. The bar width therefore gets one such gap for each boundary
// inside the masked text and between it and the characters next to it in the same run. A digit next to Hangul is not
// counted, because joinDigitHangul removes that gap.
function maskRuns(xml) {
  return xml.replace(/<w:r>(<w:rPr>[\s\S]*?<\/w:rPr>)?<w:t( xml:space="preserve")?>([^<]*)<\/w:t><\/w:r>/g, (all, rPr, sp, txt) => {
    const t = unesc(txt);
    if (!BL.hit(t)) return all;
    const bold = /<w:b(?: w:val="(?:true|1|on)")?\/>/.test(rPr || "");
    // Font size (in half points) and the original character spacing (in twips). The original width is the font width
    // plus the character count times the spacing
    const pt = Number(((rPr || "").match(/<w:sz w:val="(\d+)"\/>/) || [0, 18])[1]) / 2;
    const sp0 = Number(((rPr || "").match(/<w:spacing w:val="(-?\d+)"\/>/) || [0, 0])[1]);
    const segs = BL.segments(t);
    return segs.map(([s, m], i) => {
      if (!m) return `<w:r>${rPr || ""}<w:t xml:space="preserve">${esc(s)}</w:t></w:r>`;
      const prev = i > 0 ? segs[i - 1][0].slice(-1) : "", next = i + 1 < segs.length ? segs[i + 1][0][0] : "";
      // The width is matched with a horizontal scale (w:w) rather than character spacing. LibreOffice applies character
      // spacing only between characters (n-1 places), and a negative spacing stops at about 1/6 of the font size, so
      // the bars came out too wide (measured: two bars were 2.9pt and 3.7pt too wide and pushed a department line onto
      // a second line).
      const w = BL.widthEm(s, bold) + (sp0 / 20) * [...s].length / pt;
      const box = BL.M[bold ? "bold" : "regular"].box;
      // A bar is one square glyph stretched horizontally (w:w goes up to 600%, and only a longer bar is split into
      // several squares). In a Korean document LibreOffice groups a square that follows Hangul with the Hangul
      // characters, so it may break the line between squares, and it ignores U+2060 and U+FEFF as well. A bar of
      // several squares was split across lines, one square at the end of a line and two on the next (four variants were
      // converted and compared). With a single square the bar moves to the next line as a whole, like the original
      // word.
      const n = Math.max(1, Math.ceil(w / (box * 6) - 1e-9)), scale = Math.round(w / (n * box) * 100);
      return `<w:r>${maskRPr(rPr, scale)}<w:t xml:space="preserve">${BL.FIG.repeat(n)}</w:t></w:r>`;
    }).join("");
  });
}

// Page number fields. The docx package writes PAGE and NUMPAGES as one run holding begin, instruction, separate and end
// with no result text, and LibreOffice then draws the number in the document default (9pt, near black) instead of the
// run's 7pt grey. Writing the field the way Word does, one run per part with a result run between separate and end,
// keeps the formatting (in LibreOffice only this form worked). Applied to documents with the name footer (the
// fieldResults option).
function splitFieldRuns(xml) {
  // One run at a time: a pattern spanning runs picked up the previous run's formatting.
  return xml.replace(/<w:r>((?:(?!<\/w:r>)[\s\S])*)<\/w:r>/g, (whole, inner) => {
    if (!inner.includes('<w:fldChar w:fldCharType="begin"/>')) return whole;
    const rPr = (inner.match(/^<w:rPr>[\s\S]*?<\/w:rPr>/) || [""])[0], body = inner.slice(rPr.length);
    const parts = body.match(/<w:fldChar w:fldCharType="(?:begin|separate|end)"\/>|<w:instrText[^>]*>[^<]*<\/w:instrText>|<w:t[^>]*>[^<]*<\/w:t>/g) || [];
    const r = inner => `<w:r>${rPr}${inner}</w:r>`;
    return parts.map(p => p === '<w:fldChar w:fldCharType="separate"/>' ? r(p) + r("<w:t>1</w:t>") : r(p)).join("");
  });
}

async function save(doc, outPath, o = {}) {
  const zip = await JSZip.loadAsync(await Packer.toBuffer(doc));
  if (o.fieldResults) {
    for (const f of Object.keys(zip.files).filter(n => /^word\/footer\d*\.xml$/.test(n))) {
      zip.file(f, splitFieldRuns(await zip.file(f).async("string")));
    }
  }
  if (BL.on) {                                                                     // a blind edition: the footers and headers are covered too
    for (const f of Object.keys(zip.files).filter(n => /^word\/(?:footer|header)\d*\.xml$/.test(n))) {   // the name in every footer, when the table covers it
      zip.file(f, maskRuns(await zip.file(f).async("string")));
    }
  }
  let xml = await zip.file("word/document.xml").async("string");
  if (BL.on) xml = maskRuns(xml);
  xml = xml.replace(/<w:t( xml:space="preserve")?>([^<]*)<\/w:t>/g,
    (_, sp, txt) => "<w:t" + (sp || "") + ">" + joinDigitHangul(txt) + "</w:t>");
  xml = xml
    .replace(/<w:pPr>([\s\S]*?)<\/w:pPr>/g, (_, inner) => "<w:pPr>" + withAutoSpace(inner) + "</w:pPr>")
    .replace(/<w:p>(?!<w:pPr>)/g, "<w:p><w:pPr>" + AUTOSPACE + "</w:pPr>");
  zip.file("word/document.xml", xml);
  fs.writeFileSync(outPath, await zip.generateAsync({ type: "nodebuffer" }));
  console.log("written");
}
module.exports = { save };
