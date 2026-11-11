"""Started by tests/desktop/e2e.py with the built app as its interpreter: read a PDF with what the app carries, as the app does
for a person's old PDFs, and print the reader and the first words."""
import pathlib  # the engine's folder
import sys  # the arguments and the module path

sys.path.insert(0, str(pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "src"))  # the engine inside the one-file app
import ingest  # noqa: E402  how a person's files become text
import pdftools  # noqa: E402  which reader that used

print(pdftools.reader(), ingest.to_text(pathlib.Path(sys.argv[1]))[:80])  # the reader, and the start of the text
