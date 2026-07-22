#!/usr/bin/env python3
"""Build a portable one-file version from the GitHub Pages source files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "styles.css").read_text(encoding="utf-8")
data_js = (ROOT / "data.js").read_text(encoding="utf-8")
app_js = (ROOT / "app.js").read_text(encoding="utf-8")

html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n</style>")
html = html.replace('<script src="data.js"></script>', f"<script>\n{data_js}\n</script>")
html = html.replace('<script src="app.js"></script>', f"<script>\n{app_js}\n</script>")
(ROOT / "cg-conference-timeline.html").write_text(html, encoding="utf-8")
print(ROOT / "cg-conference-timeline.html")
