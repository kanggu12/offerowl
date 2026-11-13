# Draws the small badge that sits next to a company name in a company band (for example "Founded"), and measures the
# company name so the caller knows where to place the badge. layout.js calls it from fbandLogo.
# The badge is a picture, not shaded text: LibreOffice stretches the background of raised text down to the line
# below, so a shaded box drifts off the band's center. A picture sits exactly in the middle, like a logo does.
#
# Usage: python3 src/badge.py <out.png> <badge text> <company name> <name pt> <badge text pt> <badge height pt> <fill hex>
# Output (JSON): {"name_w": company name width in pt, "w": badge width in pt, "h": badge height in pt}
import json, os, sys  # the JSON answer, paths, and the command-line arguments
from PIL import Image, ImageDraw, ImageFont  # drawing the badge and measuring text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root, one level above src/
BOLD = os.path.join(ROOT, "fonts", "Pretendard-Bold.ttf")  # the same bold face the document uses for company names
S = 20                         # draw 1 pt as 20 px (1440 dpi); the document places the image at its pt size

out, text, name, name_pt, size_pt, h_pt, fill = sys.argv[1:8]  # the seven arguments, in the order of the usage line
name_pt, size_pt, h_pt = float(name_pt), float(size_pt), float(h_pt)  # sizes arrive as text

# The company name's width, in the document's face and size. Raqm layout applies kerning, so the width matches the page.
name_w = ImageFont.truetype(BOLD, round(name_pt * S)).getlength(name) / S

f = ImageFont.truetype(BOLD, round(size_pt * S))  # the badge text's face at drawing scale
pad = 0.27 * size_pt           # side padding, the width of one non-breaking space at the badge's size
w_pt = f.getlength(text) / S + 2 * pad  # the badge's width: its text plus padding on both sides
W, H = round(w_pt * S), round(h_pt * S)  # the image size in pixels
im = Image.new("RGBA", (W, H), "#" + fill)  # the filled box
d = ImageDraw.Draw(im)  # a pen for the text
# Center the text's ink, not its font box, vertically and horizontally in the badge.
x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)  # where the ink of the text falls when drawn at the origin
d.text(((W - (x1 - x0)) / 2 - x0, (H - (y1 - y0)) / 2 - y0), text, font=f, fill="white")  # white text on the fill
# Two document builds can draw the same badge at once. Writing to a temporary name and renaming at the end means a
# reader never puts a half-written file into a document.
tmp = f"{out}.{os.getpid()}.tmp"  # a name unique to this process
im.save(tmp, format="PNG")  # the whole image first
os.replace(tmp, out)  # then an atomic rename into place
print(json.dumps({"name_w": round(name_w, 2), "w": round(w_pt, 2), "h": h_pt}))  # the sizes the caller lays out with
