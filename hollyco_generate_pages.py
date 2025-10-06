import os
import json
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
DATA_FILE = "data/hollyco_sellers.json"
TEMPLATE_DIR = "templates"
OUTPUT_DIR = "docs/hollyco"

A_Z_TEMPLATE = "hollyco/index.html"

# ------------------------------------------------------------
# LOAD DATA
# ------------------------------------------------------------
with open(DATA_FILE, "r", encoding="utf-8") as f:
    sellers = json.load(f)

# ------------------------------------------------------------
# NORMALISE FIRST LETTERS (group # for non-A–Z)
# ------------------------------------------------------------
for s in sellers:
    name = s.get("name", "").strip()
    if name:
        first = name[0].upper()
        s["first_letter"] = first if first.isalpha() else "#"
    else:
        s["first_letter"] = "#"

# ------------------------------------------------------------
# BUILD ACTIVE LETTERS LIST (only those that exist)
# ------------------------------------------------------------
letters_present = sorted({s["first_letter"] for s in sellers})
if "#" in letters_present:
    letters_present.remove("#")
    letters_present = ["#"] + letters_present

# ------------------------------------------------------------
# SETUP JINJA
# ------------------------------------------------------------
env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

index_template = env.get_template(A_Z_TEMPLATE)

# ------------------------------------------------------------
# ENSURE OUTPUT FOLDERS
# ------------------------------------------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ------------------------------------------------------------
# RENDER A–Z DIRECTORY (single page)
# ------------------------------------------------------------
html = index_template.render(sellers=sellers, letters=letters_present)
output_path = os.path.join(OUTPUT_DIR, "index.html")

with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ Rendered Holly & Co A–Z directory to {output_path}")
print(f"🔹 Skipped rendering individual seller pages (no longer required).")
