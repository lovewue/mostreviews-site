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
# LOAD & CLEAN DATA
# ------------------------------------------------------------
with open(DATA_FILE, "r", encoding="utf-8") as f:
    sellers = json.load(f)

cleaned_sellers = []
for s in sellers:
    name = s.get("name", "").strip()
    if not name:
        continue  # skip missing names entirely

    # Derive first letter
    first_char = name[0].upper()
    if not first_char.isalpha():  # e.g. numbers or punctuation
        first_char = "#"
    s["first_letter"] = first_char

    # Only keep active sellers
    if s.get("is_active", True):
        cleaned_sellers.append(s)

# Sort by first_letter then name
cleaned_sellers.sort(key=lambda x: (x["first_letter"], x["name"].lower()))

print(f"✅ Loaded {len(cleaned_sellers)} active Holly & Co sellers")

# ------------------------------------------------------------
# SETUP JINJA
# ------------------------------------------------------------
env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)
index_template = env.get_template(A_Z_TEMPLATE)

# ------------------------------------------------------------
# ENSURE OUTPUT FOLDER EXISTS
# ------------------------------------------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ------------------------------------------------------------
# RENDER A–Z DIRECTORY
# ------------------------------------------------------------
html = index_template.render(sellers=cleaned_sellers)
output_path = os.path.join(OUTPUT_DIR, "index.html")

with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ Rendered A–Z directory to {output_path}")
