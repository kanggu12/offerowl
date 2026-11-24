# -*- coding: utf-8 -*-
"""The corners setting on the Python side. OFFEROWL_CORNERS=square draws every box of the figures (the timeline's bars, the
hierarchy figure's boxes), the logo tiles and a blind edition's bars with square corners: src/overview_figures.py and
src/blind.py ask here. src/corners.js reads the same switch for the built-in deck. Unset, or any other value ("round"), every
box keeps the rounded corners it always had, so the pictures are the same bytes as before the setting existed.

The panel hands the switch to each build from the person's setting `corners` (apps/api/services/documents/task_build.py blind_env); on the command
line it is set by hand: OFFEROWL_CORNERS=square ./offerowl build profile.json job.json
"""
import os  # the switch


def square(env=None) -> bool:
    """Does this run draw square corners (OFFEROWL_CORNERS=square)? env: the environment the run was given, else this process's."""
    return (os.environ if env is None else env).get("OFFEROWL_CORNERS") == "square"  # only the one word turns it on


def box(d, xy, radius, **kw) -> None:
    """A box drawn on a Pillow ImageDraw d over xy: with corners of the given radius, as the figures always drew it, or square
    when the run asks. kw (fill, outline, width) goes to Pillow as given."""
    if square():  # square corners: a plain rectangle over the same box
        d.rectangle(xy, **kw)
    else:  # the rounded box, asked for exactly as before, so its pixels are the same too
        d.rounded_rectangle(xy, radius=radius, **kw)
