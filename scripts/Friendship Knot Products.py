from pathlib import Path
import json
import pandas as pd
from collections import defaultdict
from datetime import datetime

# -------------------------------------------------
# Paths
# -------------------------------------------------
BASE = Path(__file__).resolve().parent.parent
products_file = BASE / "data" / "source" / "all_products_from_sitemap.json"
output_dir = BASE / "data" / "reports"
output_dir.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------
# Load products from sitemap dataset
# -------------------------------------------------
with open(products_file, "r", encoding="utf-8") as f:
    products = json.load(f)

# -------------------------------------------------
# Keyword groups
# -------------------------------------------------
friendship_terms = {"friendship", "friend"}
knot_terms = {"knot", "knotted"}

earring_terms = {"earring", "earrings", "stud", "studs", "hoop", "hoops"}
necklace_terms = {"necklace", "necklaces", "pendant", "pendants"}
bracelet_terms = {"bracelet", "bracelets"}
bangle_terms = {"bangle", "bangles"}
ring_terms = {"ring", "rings"}

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def slug_words(slug: str) -> set[str]:
    return {w for w in slug.lower().split("-") if w}

def has_any(words: set[str], terms: set[str]) -> bool:
    return not words.isdisjoint(terms)

# -------------------------------------------------
# Count by partner
# -------------------------------------------------
counts = defaultdict(
    lambda: {
        "Earrings": 0,
        "Necklace": 0,
        "Bracelet": 0,
        "Bangle": 0,
        "Ring": 0,
    }
)

matches = []

for p in products:
    product_slug = (p.get("product_slug") or "").strip().lower()
    seller_slug = (p.get("seller_slug") or "").strip().lower()
    product_url = (p.get("product_url") or "").strip()

    if not product_slug or not seller_slug:
        continue

    words = slug_words(product_slug)

    if not has_any(words, friendship_terms):
        continue
    if not has_any(words, knot_terms):
        continue

    matched_any = False

    if has_any(words, earring_terms):
        counts[seller_slug]["Earrings"] += 1
        matches.append({
            "Partner Slug": seller_slug,
            "Product Slug": product_slug,
            "Bucket": "Earrings",
            "Product URL": product_url,
        })
        matched_any = True

    if has_any(words, necklace_terms):
        counts[seller_slug]["Necklace"] += 1
        matches.append({
            "Partner Slug": seller_slug,
            "Product Slug": product_slug,
            "Bucket": "Necklace",
            "Product URL": product_url,
        })
        matched_any = True

    if has_any(words, bracelet_terms):
        counts[seller_slug]["Bracelet"] += 1
        matches.append({
            "Partner Slug": seller_slug,
            "Product Slug": product_slug,
            "Bucket": "Bracelet",
            "Product URL": product_url,
        })
        matched_any = True

    if has_any(words, bangle_terms):
        counts[seller_slug]["Bangle"] += 1
        matches.append({
            "Partner Slug": seller_slug,
            "Product Slug": product_slug,
            "Bucket": "Bangle",
            "Product URL": product_url,
        })
        matched_any = True

    if has_any(words, ring_terms):
        counts[seller_slug]["Ring"] += 1
        matches.append({
            "Partner Slug": seller_slug,
            "Product Slug": product_slug,
            "Bucket": "Ring",
            "Product URL": product_url,
        })
        matched_any = True

# -------------------------------------------------
# Build summary dataframe
# -------------------------------------------------
rows = []
for partner_slug, vals in counts.items():
    total = (
        vals["Earrings"]
        + vals["Necklace"]
        + vals["Bracelet"]
        + vals["Bangle"]
        + vals["Ring"]
    )

    if total == 0:
        continue

    rows.append({
        "Partner Slug": partner_slug,
        "Earrings": vals["Earrings"],
        "Necklace": vals["Necklace"],
        "Bracelet": vals["Bracelet"],
        "Bangle": vals["Bangle"],
        "Ring": vals["Ring"],
        "Total": total,
    })

summary_df = pd.DataFrame(rows)
matches_df = pd.DataFrame(matches)

# -------------------------------------------------
# Sort
# -------------------------------------------------
if not summary_df.empty:
    summary_df = summary_df.sort_values(
        by=["Total", "Earrings", "Necklace", "Bracelet", "Bangle", "Ring", "Partner Slug"],
        ascending=[False, False, False, False, False, False, True]
    ).reset_index(drop=True)

if not matches_df.empty:
    matches_df = matches_df.sort_values(
        by=["Partner Slug", "Bucket", "Product Slug"]
    ).reset_index(drop=True)

# -------------------------------------------------
# Save report
# -------------------------------------------------
output_file = output_dir / f"friendship_knot_summary_{datetime.now().date()}.xlsx"

with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
    if not summary_df.empty:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
    else:
        pd.DataFrame(
            columns=["Partner Slug", "Earrings", "Necklace", "Bracelet", "Bangle", "Ring", "Total"]
        ).to_excel(writer, sheet_name="Summary", index=False)

    if not matches_df.empty:
        matches_df.to_excel(writer, sheet_name="Matches", index=False)
    else:
        pd.DataFrame(
            columns=["Partner Slug", "Product Slug", "Bucket", "Product URL"]
        ).to_excel(writer, sheet_name="Matches", index=False)

# -------------------------------------------------
# Console output
# -------------------------------------------------
print(f"\nReport saved to: {output_file}\n")
print(f"Total products scanned: {len(products)}")
print(f"Total matched rows: {len(matches_df)}")
print(f"Total matched partners: {len(summary_df)}")

if not summary_df.empty:
    print("\n=== TOP PARTNERS (Friendship + Knot Products) ===\n")
    print(summary_df.head(20).to_string(index=False))

    print("\n=== TOTAL BY TYPE ===\n")
    totals = summary_df[["Earrings", "Necklace", "Bracelet", "Bangle", "Ring"]].sum()
    print(totals.to_string())

if not matches_df.empty:
    print("\n=== SAMPLE MATCHES ===\n")
    print(matches_df.head(20).to_string(index=False))
else:
    print("\nNo matching products found.")
