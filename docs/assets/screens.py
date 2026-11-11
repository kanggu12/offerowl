"""The README's screens and the guide's banner, put together in Chrome from the panel in one run (docs/assets/scene.py):

    python3 docs/assets/scene.py /tmp/scene --guide docs/assets   # one good run of the fictional example, its views
    python3 docs/assets/screens.py /tmp/scene                       # docs/assets/screens-light.png, screens-dark.png, banner.png

screens-*.png  four views of the panel, two by two, each with a label and one line under it, on a clear background so it
               sits on GitHub's light and dark pages alike: Make (the band from your files to your documents), Profile
               (the facts read from your files), Documents (a sentence and the words of its source), Applications (a
               posting rated line by line against your evidence)
banner.png     the guide's banner: the mark, the line the README opens with, and the panel's own band of numbers

The parts are Offerowl's own: the mark, Pretendard, each view's name in bold before its line,
neutral grays, and colour only where it means something, as in the panel (apps/panel/static/tokens.css): the chain's steps
in the colours the Make view gives them. Nothing is drawn by hand: run it again after the panel changes.
"""
import argparse  # the scene's folder
import pathlib  # files
import sys  # exit codes

from PIL import Image  # the PNGs made smaller once written

HERE = pathlib.Path(__file__).resolve().parent  # docs/assets
ROOT = HERE.parent.parent  # the repository
FONTS = ROOT / "fonts"  # Pretendard, as the documents use it
CHARCOAL = "#18181B"  # the banner's ground: a neutral near black, as the panel's dark theme
# the chain's steps in the colours of the Make view's band (the panel's dark theme, on dark ground): your files stay on this PC
# (blue), the facts are the evidence (yellow), the sentences are the agent's (orange), the documents are done (green)
STEP_COLOURS = ("#A3C5FB", "#ECB22E", "#F5A262", "#5AD9A2")
# each view: its picture's state in the scene's folder, its label, the line under it
VIEWS = [("make_run", "Make", "Drop your files. The band follows them to your documents."),
         ("profile_facts", "Profile", "Every fact read from a file, kept with its words."),
         ("evidence_selected", "Documents", "Click a sentence: the words of its source beside it."),
         ("jobs_fit", "Applications", "A posting, line by line, against your evidence.")]
# the page's colours on GitHub's light and dark pages: neutral words, and each picture framed in the page's own border colour
THEME = {"light": {"label": "#27272A", "text": "#52525B", "line": "#D0D7DE"},
         "dark": {"label": "#F4F4F5", "text": "#D4D4D8", "line": "#30363D"}}
FACES = "".join(f'@font-face{{font-family:Pretendard;font-weight:{w};src:url("{(FONTS / f).as_uri()}")}}'
                for w, f in ((400, "Pretendard-Regular.ttf"), (600, "Pretendard-SemiBold.ttf"), (700, "Pretendard-Bold.ttf")))


def shot(walk: pathlib.Path, state: str, theme: str, size: str = "1440x900") -> pathlib.Path:   # the panel fills this window
    """The scene's picture of a state in English (named as the walk names its pictures)."""
    found = sorted(walk.glob(f"*_{state}_en_{theme}_{size}.png"))
    if not found:
        raise SystemExit(f"no {state} in {theme} at {size} in {walk}: run docs/assets/scene.py {walk}")
    return found[0]


def screens_page(walk: pathlib.Path, theme: str) -> str:
    """Four views of the panel, two by two, each with its label and line."""
    c = THEME[theme]
    tiles = "".join(f'<figure><img src="{shot(walk, s, theme).as_uri()}"><figcaption><b>{label}</b>{line}</figcaption></figure>'
                    for s, label, line in VIEWS)
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{FACES}"
            "html,body{margin:0;background:transparent}"
            ".grid{display:grid;grid-template-columns:1fr 1fr;gap:64px 48px;padding:24px;width:2512px;box-sizing:border-box;font-family:Pretendard}"
            "figure{margin:0}"
            f"img{{display:block;width:100%;border-radius:16px;border:2px solid {c['line']}}}"
            f"figcaption{{margin-top:22px;font-size:34px;font-weight:400;color:{c['text']};white-space:nowrap}}"
            f"b{{display:inline-block;margin-right:14px;font-weight:700;color:{c['label']}}}"
            f"</style></head><body><div class='grid'>{tiles}</div></body></html>")


# the band of the Make view, step by step: its number in the fictional example, its name, its line (as the panel words them)
CHAIN = [("1", "Source", "the file you added"), ("31", "Facts", "each kept with its source's words"),
         ("38", "Sentences", "each citing the facts it rests on"), ("4", "Documents", "checked against the facts, then exported")]


# the banner's sizes in pixels, at its size of 2560 x 800
SIZES = {"logo": 720, "tag": 50, "num": 66, "numw": 112, "name": 34, "line": 26, "pad": 150, "py": 26, "px": 44, "gap": 26, "r": 22}


def banner_page(w: int, h: int) -> str:
    """The mark and the opening line on a neutral near black, and the Make view's band as a chain of its four steps, in the
    panel's parts: a large number in its step's colour, the step's name and its line, a chevron drawn between them (no arrow
    characters)."""
    z = SIZES  # its sizes
    mark = (HERE / "logo-dark.svg").read_text(encoding="utf-8")  # the lockup for dark ground
    steps = "".join(f'<div class="step" style="--c:{c}"><b>{n}</b><span><i>{name}</i><em>{line}</em></span></div>'
                    for (n, name, line), c in zip(CHAIN, STEP_COLOURS))
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{FACES}"
            f"html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:{CHARCOAL};font-family:Pretendard}}"
            f"body{{display:flex;align-items:center;justify-content:space-between;box-sizing:border-box;padding:0 {z['pad']}px}}"
            f".left svg{{width:{z['logo']}px;height:auto;display:block}}"
            f"p{{margin:{round(z['tag'] * 0.9)}px 0 0;color:#FFFFFF;font-weight:600;font-size:{z['tag']}px;line-height:1.35}}"
            f"p i{{font-style:normal;color:{STEP_COLOURS[1]}}}"   # the evidence's yellow: every sentence cites its facts
            f".chain{{background:#222226;border:2px solid #34343A;border-radius:{z['r']}px;padding:{z['py']}px {z['px']}px}}"
            f".step{{display:flex;align-items:baseline;position:relative;padding:{round(z['gap'] / 2)}px 0}}"
            f".step + .step{{margin-top:{z['gap']}px}}"
            f".step + .step::before{{content:'';position:absolute;left:{round(z['num'] * 0.3)}px;top:-{z['gap']}px;width:{round(z['num'] * 0.2)}px;"
            f"height:{round(z['num'] * 0.2)}px;border-right:3px solid #63636E;border-bottom:3px solid #63636E;transform:rotate(45deg)}}"
            f".step b{{flex:0 0 {z['numw']}px;font-size:{z['num']}px;font-weight:700;color:var(--c);line-height:1;font-variant-numeric:tabular-nums}}"
            f".step i{{display:block;font-style:normal;font-size:{z['name']}px;font-weight:700;color:#FFFFFF;white-space:nowrap}}"
            f".step em{{display:block;font-style:normal;font-size:{z['line']}px;color:#A1A1AA;margin-top:4px;white-space:nowrap}}"
            f"</style></head><body><div class='left'>{mark}<p>Your files in.{' ' if w / h >= 3 else '<br>'}The whole application out.<br>"   # three lines where it is narrow
            f"<i>Every sentence cites them.</i></p></div>"
            f"<div class='chain'>{steps}</div></body></html>")


def render(html: str, out: pathlib.Path, w: int, h: int | None = None, clear: bool = False) -> None:
    """The page in Chrome, as a PNG of its full height (or the size given), made smaller without loss."""
    from playwright.sync_api import sync_playwright  # only here: the rest of the docs need no browser
    page_file = out.with_suffix(".html")  # Chrome reads the screenshots from file:// beside it
    page_file.write_text(html, encoding="utf-8")
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            p = b.new_page(viewport={"width": w, "height": h or 800}, device_scale_factor=1)
            p.goto(page_file.as_uri())
            p.evaluate("document.fonts.ready")  # Pretendard before the picture
            p.wait_for_timeout(300)  # the screenshots decoded
            p.screenshot(path=str(out), full_page=h is None, omit_background=clear)
            b.close()
    finally:
        page_file.unlink(missing_ok=True)  # only the picture stays
    Image.open(out).save(out, optimize=True)  # the same pixels in fewer bytes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="screens.py", description="The README's screens and the guide's banner, from the panel in one run.")
    ap.add_argument("walk", type=pathlib.Path, help="the folder docs/assets/scene.py wrote")
    a = ap.parse_args(argv)
    for theme in THEME:  # both looks, as the README picks one per reader
        render(screens_page(a.walk, theme), HERE / f"screens-{theme}.png", 2560, clear=True)
    render(banner_page(2560, 800), HERE / "banner.png", 2560, 800)
    for f in ("screens-light.png", "screens-dark.png", "banner.png"):
        im = Image.open(HERE / f)
        print(f"{f}: {im.size[0]} x {im.size[1]}, {(HERE / f).stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
