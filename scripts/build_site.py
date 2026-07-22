#!/usr/bin/env python3
"""Create the minimal static directory uploaded to GitHub Pages."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"
if SITE.exists():
    shutil.rmtree(SITE)
SITE.mkdir()
for name in ("index.html", "styles.css", "app.js", "data.js"):
    shutil.copy2(ROOT / name, SITE / name)
print(SITE)
