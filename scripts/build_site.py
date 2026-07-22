#!/usr/bin/env python3
"""Create the static directory uploaded to GitHub Pages."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"

if SITE.exists():
    shutil.rmtree(SITE)

SITE.mkdir()

excluded = {
    ".git",
    ".github",
    "_site",
    "scripts",
    "tests",
    "__pycache__",
}

for item in ROOT.iterdir():
    if item.name in excluded or item.name.startswith(".update-"):
        continue

    destination = SITE / item.name

    if item.is_dir():
        shutil.copytree(item, destination)
    else:
        shutil.copy2(item, destination)

print(SITE)