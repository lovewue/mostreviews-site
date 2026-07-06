import os
import json
from jinja2 import Environment, FileSystemLoader
from collections import defaultdict

# --- PATHS ---
DATA_PATH = "data/hollyco_sellers.json"   # your JSON file with seller data
OUTPUT_DIR = "docs/hollyco"
TEMPLATE_DIR = "templates"

# --- LOAD SELLERS ---
with open(DATA_PATH, "r", encoding="utf-8") as f:
    sellers = json.load(f)

# --- CLEAN SELLERS ---
cleaned_sellers = []
for s in sellers:
    if not s.get("name"):
        continue
    cleaned_sellers.append({
        "name": s["name"].strip(),
        "slug": s.get("slug", ""),
        "url": s.get("url", ""),  # external link to Holly & Co
    })

# --- GROUP BY FIRST LETTER ---
sellers_by_letter = defaultdict(list)
for seller in cleaned_sellers:
    first_char = seller["name"][0].upper()
    if not first_char.isalpha():
        first_char = "#"
    sellers_by_letter[first_char].append(seller)

# Sort dictionary A–Z with '#' first
sellers_by_letter = dict(sorted(sellers_by_letter.items(), key=lambda x: (' ' if x[0] == '#' else x[0])))


# --- JINJA ENVIRONMENT ---
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
index_template = env.get_template("hollyco/index.html")

# --- RENDER INDEX PAGE ---
os.makedirs(OUTPUT_DIR, exist_ok=True)

html = index_template.render(
    sellers_by_letter=sellers_by_letter
)

with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ Holly & Co A–Z index generated successfully with {len(cleaned_sellers)} sellers.")
