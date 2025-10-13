import json
from collections import defaultdict

# === Config ===
INPUT_FILE = "data/top_products_12months.json"
OUTPUT_FILE = "data/top_product_per_partner.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    products = json.load(f)

# Group products by partner slug
partners_best = {}
for p in products:
    if p.get("review_count", 0) >= 5:
        slug = p.get("seller_slug") or p.get("partner_slug")
        if not slug:
            continue
        # Keep only the most reviewed product per partner
        if slug not in partners_best or p["review_count"] > partners_best[slug]["review_count"]:
            partners_best[slug] = p

# Sort descending by review_count
sorted_products = sorted(partners_best.values(), key=lambda x: x["review_count"], reverse=True)

# Assign rank numbers
for i, p in enumerate(sorted_products, start=1):
    p["rank"] = i

# Write output
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(sorted_products, f, indent=2, ensure_ascii=False)

print(f"✅ Saved {len(sorted_products)} top products (≥5 reviews) to {OUTPUT_FILE}")
