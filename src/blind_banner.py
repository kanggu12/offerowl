"""The red band across the top of page 1 of a blind edition (the edition with names and contacts masked).

It reads like a security marking on an official document: a dark red band the full width of the page with white text,
a bold, widely tracked label, a thin vertical rule, then a short note in regular weight. It fits inside the resume's
top margin (6 mm), so the body layout does not move. The color is the table's mark_fill (src/blind.json, or the
person's own table that OFFEROWL_BLIND_TABLE names); the masking bars (mask_fill) use the same red, so masked text and
the band read as one system.

Usage: python3 src/blind_banner.py <out.png> <width pt> <height pt> <label> <note>, prints {"w": pt, "h": pt}
"""
import json  # printing the answer
import pathlib  # paths
import sys  # the command-line arguments
from PIL import Image, ImageDraw, ImageFont  # drawing the band

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository root, one level above src/
sys.path.insert(0, str(ROOT / "src"))  # blind.py beside this file, however it was started
import blind  # noqa: E402  the table this run reads
S = 8  # draw 1 pt as 8 px (576 dpi)
FILL = "#" + blind.load()["mark_fill"]  # the band's red, from the table this edition is made with
out, W, H, label, note = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5]  # the arguments
bold = ImageFont.truetype(str(ROOT / "fonts" / "Pretendard-Bold.ttf"), int(6.8 * S))  # the label's face
reg = ImageFont.truetype(str(ROOT / "fonts" / "Pretendard-Regular.ttf"), int(6.8 * S))  # the note's face
TRACK, GAP = 1.4 * S, 9 * S  # extra space between the label's letters, and the space on each side of the rule
im = Image.new("RGB", (int(W * S), int(H * S)), FILL)  # the band
d = ImageDraw.Draw(im)  # a pen
lw = sum(bold.getlength(c) for c in label) + TRACK * (len(label) - 1)  # the tracked label's width
nw = reg.getlength(note)  # the note's width
x = (im.width - (lw + 2 * GAP + nw)) / 2  # start so that label, rule and note together are centered
asc, desc = bold.getmetrics()  # the face's ascent and descent
y = (im.height - (asc + desc)) / 2  # the text's top, centered vertically
for c in label:  # the label one letter at a time, to apply the tracking
    d.text((x, y), c, font=bold, fill="#FFFFFF")  # white
    x += bold.getlength(c) + TRACK  # the next letter after the extra space
x += GAP - TRACK  # the space before the rule (the last letter added one TRACK too many)
d.line([(x, im.height * 0.3), (x, im.height * 0.7)], fill=(255, 255, 255), width=max(1, S // 5))  # the thin rule
x += GAP  # the space after the rule
d.text((x, y), note, font=reg, fill=(255, 236, 234))  # the note, a little softer than pure white
im.save(out, dpi=(72 * S, 72 * S))  # the image with its real resolution recorded
print(json.dumps({"w": W, "h": H}))  # the size the caller places it at
