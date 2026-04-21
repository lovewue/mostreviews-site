from pathlib import Path
import json
import pandas as pd
from collections import defaultdict
from datetime import datetime

# -------------------------------------------------
# USER INPUTS
# -------------------------------------------------
REPORT_NAME = "robin_products"

# Product must contain ALL of these words in the slug
REQUIRED_TERMS = {"robin"}

# Buckets to count
BUCKETS = {
    "Earrings": {"earring", "earrings", "stud", "studs", "hoop", "hoops"},
    "Necklace": {"necklace", "necklaces", "pendant", "pendants"},
    "Bracelet": {"bracelet", "bracelets"},
    "Bangle": {"bangle", "bangles"},
    "Ring": {"ring", "rings"},
}

# -------------------------------------------------
# Paths
# -------------------------------------------------
BASE = Path(__file__).resolve().parent.parent
products_file = BASE / "data" / "source" / "all_products_from_sitemap.json"
output_dir = BASE / "data" / "reports"
output_dir.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def slug_words(slug: str) -> set[str]:
    return {w for w in slug.lower().split("-") if w}

def has_any(words: set[str], terms: set[str]) -> bool:
    return not words.isdisjoint(terms)

def has_all(words: set[str], terms: set[str]) -> bool:
    return terms.issubset(words)

# -------------------------------------------------
# Load products
# -------------------------------------------------
with open(products_file, "r", encoding="utf-8") as f:
    products = json.load(f)

# -------------------------------------------------
# Count by partner
# -------------------------------------------------
counts = defaultdict(lambda: {bucket: 0 for bucket in BUCKETS})
matches = []

for p in products:
    product_slug = (p.get("product_slug") or "").strip().lower()
    seller_slug = (p.get("seller_slug") or "").strip().lower()
    product_url = (p.get("product_url") or "").strip()

    if not product_slug or not seller_slug:
        continue

    words = slug_words(product_slug)

    if not has_all(words, REQUIRED_TERMS):
        continue

    for bucket_name, bucket_terms in BUCKETS.items():
        if has_any(words, bucket_terms):
            counts[seller_slug][bucket_name] += 1
            matches.append({
                "Partner Slug": seller_slug,
                "Product Slug": product_slug,
                "Bucket": bucket_name,
                "Product URL": product_url,
            })

# -------------------------------------------------
# Build summary dataframe
# -------------------------------------------------
rows = []
for partner_slug, vals in counts.items():
    total = sum(vals.values())
    if total == 0:
        continue

    row = {"Partner Slug": partner_slug}
    row.update(vals)
    row["Total"] = total
    rows.append(row)

summary_df = pd.DataFrame(rows)
matches_df = pd.DataFrame(matches)

# -------------------------------------------------
# Sort
# -------------------------------------------------
if not summary_df.empty:
    sort_cols = ["Total"] + list(BUCKETS.keys()) + ["Partner Slug"]
    ascending = [False] * (len(sort_cols) - 1) + [True]
    summary_df = summary_df.sort_values(
        by=sort_cols,
        ascending=ascending
    ).reset_index(drop=True)

if not matches_df.empty:
    matches_df = matches_df.sort_values(
        by=["Partner Slug", "Bucket", "Product Slug"]
    ).reset_index(drop=True)

# -------------------------------------------------
# Save
# -------------------------------------------------
output_file = output_dir / f"{REPORT_NAME}_{datetime.now().date()}.xlsx"

with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
    if not summary_df.empty:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
    else:
        pd.DataFrame(columns=["Partner Slug", *BUCKETS.keys(), "Total"]).to_excel(
            writer, sheet_name="Summary", index=False
        )

    if not matches_df.empty:
        matches_df.to_excel(writer, sheet_name="Matches", index=False)
    else:
        pd.DataFrame(columns=["Partner Slug", "Product Slug", "Bucket", "Product URL"]).to_excel(
            writer, sheet_name="Matches", index=False
        )

# -------------------------------------------------
# Console output
# -------------------------------------------------
print(f"\nReport saved to: {output_file}\n")
print(f"Total products scanned: {len(products)}")
print(f"Total matched rows: {len(matches_df)}")
print(f"Total matched partners: {len(summary_df)}")
print(f"Required terms: {sorted(REQUIRED_TERMS)}")

if not summary_df.empty:
    print("\n=== TOP PARTNERS ===\n")
    print(summary_df.head(20).to_string(index=False))

    print("\n=== TOTAL BY TYPE ===\n")
    totals = summary_df[list(BUCKETS.keys())].sum()
    print(totals.to_string())

if not matches_df.empty:
    print("\n=== SAMPLE MATCHES ===\n")
    print(matches_df.head(20).to_string(index=False))
else:
    print("\nNo matching products found.")
