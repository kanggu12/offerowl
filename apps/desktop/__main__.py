"""The one-file app's entry (build.py) and `python3 -m desktop` with apps/ on the path."""
# An absolute import: PyInstaller runs this file as a plain script, with no package around it.
from desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
