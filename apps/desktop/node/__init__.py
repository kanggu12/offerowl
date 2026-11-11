"""Node.js for the one-file app. pins.json says which release; bundle.py (at build time) packs it with the production
libraries; runtime.py (inside the app) unpacks it once into the data folder and puts it on the server's PATH."""
