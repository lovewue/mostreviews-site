import json
from pathlib import Path
from openai import OpenAI

client = OpenAI()

# project root
ROOT = Path(__file__).resolve().parents[1]

# monthly folder
base = ROOT / "data/derived/monthly"

# find latest month
latest = sorted(base.iterdir())[-1]

file = latest / "enriched_products.json"

print("Using:", file)

with open(file, "r", encoding="utf-8") as f:
    products = json.load(f)

top20 = products[:20]

for p in top20:
    print(p["name"], "-", p["review_count_month"])
