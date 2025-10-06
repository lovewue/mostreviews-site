# render_hollyco.py

import os, json
from jinja2 import Environment, FileSystemLoader, select_autoescape

DATA_FILE = "data/hollyco_sellers.json"
TEMPLATE_DIR = "templates"
OUTPUT_DIR = "docs/hollyco"

A_Z_TEMPLATE = "hollyco/index.html"

# --- load data ---
with open(DATA_FILE, encoding="utf-8") as f:
    sellers = json.load(f)

for s in sellers:
    name = s.get("name", "").strip()
    s["first_letter"] = name[0].upper() if name else "#"

active_sellers = [s for s in sellers if s.get("is_active")]

# --- jinja setup ---
env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html"])
)
template = env.get_template(A_Z_TEMPLATE)

# --- output ---
os.makedirs(OUTPUT_DIR, exist_ok=True)
html = template.render(sellers=active_sellers)
with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ Rendered Holly & Co A–Z directory with {len(active_sellers)} active sellers.")
