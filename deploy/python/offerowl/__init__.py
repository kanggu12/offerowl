"""The `offerowl` command as a Python package.

The package is a thin starter: the engine (the folders src/, apps/, core/, examples/, fonts/ and render/, the launcher, the
license and the third-party notices) is installed beside it as data, in the folder `engine/`, and `offerowl.cli` runs the repository's own
launcher from there. See docs/INSTALL.md, "4. The Python package".
"""

__version__ = "0.6.1"  # the one place the package version is written; pyproject.toml reads it, and tests/packaging keeps the chart and the image label equal to it
