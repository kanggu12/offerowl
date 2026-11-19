// The corners setting on the JavaScript side. OFFEROWL_CORNERS=square draws every box of the built-in deck with square corners:
// the figures' boxes (portfolio/draw.js), the simple templates' boxes (deck_slides.js), the boxes written into the slides
// (deck_structure.js) and the stylesheet's (portfolio/style_square.css, added by portfolio/deck.js). src/corners.py reads the
// same switch for the figures and the logo tiles. Unset, or any other value ("round"), every box keeps the rounded corners it
// always had, so the deck's page is the same bytes as before the setting existed.
const SQUARE = process.env.OFFEROWL_CORNERS === "square";   // read once: one build runs with one setting
// The corner radius of a box w by h whose own radius is r: r as it was, or 0 under square corners. A dot (a square box whose
// radius is half its side or more) is a circle drawn as a box, and stays a circle.
const corner = (w, h, r) => (SQUARE && !(w === h && r >= w / 2) ? 0 : r);
module.exports = { SQUARE, corner };
