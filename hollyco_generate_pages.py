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
SELLER_TEMPLATE = "hollyco/seller.html"

# ------------------------------------------------------------
# LOAD DATA
# ------------------------------------------------------------
with open(DATA_FILE, "r", encoding="utf-8") as f:
    sellers = json.load(f)

# Derive first_letter for A–Z grouping
for s in sellers:
    name = s.get("name", "").strip()
    s["first_letter"] = name[0].upper() if name else "#"

# Split active/inactive
active_sellers = [s for s in sellers if s.get("is_active")]
inactive_sellers = [s for s in sellers if not s.get("is_active")]

# ------------------------------------------------------------
# SETUP JINJA
# ------------------------------------------------------------
env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

index_template = env.get_template(A_Z_TEMPLATE)
seller_template = env.get_template(SELLER_TEMPLATE)

# ------------------------------------------------------------
# ENSURE OUTPUT FOLDERS
# ------------------------------------------------------------
os.makedirs(os.path.join(OUTPUT_DIR, "seller"), exist_ok=True)

# ------------------------------------------------------------
# RENDER A–Z DIRECTORY (include all for completeness)
# ------------------------------------------------------------
html = index_template.render(sellers=sellers)
with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)
print(f"✅ Rendered A–Z directory to {OUTPUT_DIR}/index.html")

# ------------------------------------------------------------
# RENDER INDIVIDUAL SELLER PAGES (only active)
# ------------------------------------------------------------
for s in active_sellers:
    slug = s["slug"]
    out_path = os.path.join(OUTPUT_DIR, "seller", f"{slug}.html")
    html = seller_template.render(seller=s)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

print(f"✅ Rendered {len(active_sellers)} active seller pages "
      f"(skipped {len(inactive_sellers)} inactive) in {OUTPUT_DIR}/seller/")
