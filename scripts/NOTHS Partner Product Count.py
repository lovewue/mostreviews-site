from pathlib import Path
import json
import pandas as pd
from datetime import datetime

# -------------------------------------------------
# Paths
# -------------------------------------------------
BASE = Path(__file__).resolve().parent.parent
partners_file = BASE / "data" / "source" / "partners.json"
products_file = BASE / "data" / "source" / "all_products_from_sitemap.json"
output_dir = BASE / "data" / "reports"
output_dir.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def bucket_count(n: int) -> str:
    if n == 0:
        return "0"
    elif n == 1:
        return "1"
    elif n <= 3:
        return "2–3"
    elif n <= 5:
        return "4–5"
    elif n <= 10:
        return "6–10"
    elif n <= 20:
        return "11–20"
    elif n <= 50:
        return "21–50"
    elif n <= 100:
        return "51–100"
    elif n <= 249:
        return "101–249"
    elif n <= 499:
        return "250–499"
    elif n <= 999:
        return "500–999"
    else:
        return "1000+"


# -------------------------------------------------
# Load data
# -------------------------------------------------
with open(partners_file, "r", encoding="utf-8") as f:
    partners = json.load(f)

with open(products_file, "r", encoding="utf-8") as f:
    products = json.load(f)

# -------------------------------------------------
# Count products by seller slug from sitemap
# -------------------------------------------------
product_counts = {}

for p in products:
    seller_slug = (p.get("seller_slug") or "").strip().lower()
    if not seller_slug:
        continue
    product_counts[seller_slug] = product_counts.get(seller_slug, 0) + 1

# -------------------------------------------------
# Build full partner table
# -------------------------------------------------
rows = []

for p in partners:
    slug = (p.get("slug") or "").strip().lower()
    if not slug:
        continue

    count = product_counts.get(slug, 0)

    rows.append({
        "Slug": slug,
        "Partner Name": p.get("name", ""),
        "Partner URL": p.get("url", ""),
        "Sitemap Product Count": count,
    })

df = pd.DataFrame(rows)

if df.empty:
    print("No partner rows found.")
else:
    # -------------------------------------------------
    # Full partner table
    # -------------------------------------------------
    df_all = df.sort_values(
        by=["Sitemap Product Count", "Partner Name", "Slug"],
        ascending=[False, True, True]
    ).reset_index(drop=True)

    # -------------------------------------------------
    # Add bucket labels
    # -------------------------------------------------
    df_all["Bucket"] = df_all["Sitemap Product Count"].apply(bucket_count)

    # -------------------------------------------------
    # Build distribution summary
    # -------------------------------------------------
    summary = (
        df_all.groupby("Bucket", observed=False)
        .size()
        .reset_index(name="Number of Partners")
    )

    bucket_order = [
        "0",
        "1",
        "2–3",
        "4–5",
        "6–10",
        "11–20",
        "21–50",
        "51–100",
        "101–249",
        "250–499",
        "500–999",
        "1000+",
    ]

    summary["Bucket"] = pd.Categorical(
        summary["Bucket"],
        categories=bucket_order,
        ordered=True
    )
    summary = summary.sort_values("Bucket").reset_index(drop=True)

    summary["% of Total"] = (summary["Number of Partners"] / len(df_all) * 100).round(1)

    # -------------------------------------------------
    # Zero-product subset
    # -------------------------------------------------
    df_zero = df_all[df_all["Sitemap Product Count"] == 0].reset_index(drop=True)

    # -------------------------------------------------
    # Save report
    # -------------------------------------------------
    output_file = output_dir / f"products_by_partner_{datetime.now().date()}.xlsx"

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df_all.to_excel(writer, sheet_name="All Partners", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)
        df_zero.to_excel(writer, sheet_name="Zero Products", index=False)

    # -------------------------------------------------
    # Console output
    # -------------------------------------------------
    print(f"\nReport saved to: {output_file}\n")
    print(f"Total partners checked: {len(df_all)}")
    print(f"Partners with zero products in latest sitemap: {len(df_zero)}")

    print("\n=== PRODUCT COUNT DISTRIBUTION ===\n")
    print(summary.to_string(index=False))

    print("\n=== TOP PARTNERS BY PRODUCT COUNT ===\n")
    print(df_all.head(30).to_string(index=False))

    if not df_zero.empty:
        print("\n=== SAMPLE PARTNERS WITH 0 PRODUCTS ===\n")
        print(df_zero.head(30).to_string(index=False))
