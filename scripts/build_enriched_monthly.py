import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
MONTHLY_ROOT = DATA_DIR / "monthly"
DERIVED_ROOT = DATA_DIR / "derived" / "monthly"

CACHE_FILE = DATA_DIR / "cache" / "products_cache.json"
MONTHLY_INDEX_FILE = MONTHLY_ROOT / "index.json"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def clean_sku(raw):
    """Normalise SKU values into clean strings."""
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def load_json(path: Path):
    """Load JSON from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    """Save JSON to disk, creating parent folders if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def safe_number(value, default=0):
    """Convert numeric-ish values safely."""
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    """Convert integer-ish values safely."""
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


# -----------------------------------------------------------------------------
# Load product cache
# -----------------------------------------------------------------------------
def load_cache():
    """
    Load the product cache into a dict keyed by SKU for fast lookups.
    """
    items = load_json(CACHE_FILE)

    cache = {}
    for row in items:
        sku = clean_sku(row.get("sku"))
        if sku:
            cache[sku] = row

    print(f"📦 Loaded cache: {len(cache)} products")
    return cache


# -----------------------------------------------------------------------------
# Load monthly index
# -----------------------------------------------------------------------------
def load_months():
    """
    Load the monthly index created by the monthly JSON builder.
    """
    data = load_json(MONTHLY_INDEX_FILE)
    months = data.get("months", [])

    if not months:
        raise ValueError("No months found in monthly index")

    return months


# -----------------------------------------------------------------------------
# Partner summary builder
# -----------------------------------------------------------------------------
def build_partner_summary(enriched_rows):
    """
    Group enriched product rows by seller and create a monthly partner summary.
    """
    grouped = defaultdict(list)

    for row in enriched_rows:
        seller_slug = row.get("seller_slug") or "unknown"
        grouped[seller_slug].append(row)

    partners = []

    for seller_slug, rows in grouped.items():
        seller_name = None

        for row in rows:
            if row.get("seller_name"):
                seller_name = row["seller_name"]
                break

        total_reviews_month = sum(safe_int(r.get("review_count_month")) for r in rows)
        product_count_with_reviews = len(rows)
        available_product_count = sum(1 for r in rows if r.get("available") is True)
        products_with_5_plus_reviews = sum(
            1 for r in rows if safe_int(r.get("review_count_month")) >= 5
        )

        ratings = [
            safe_number(r.get("rating_month"))
            for r in rows
            if r.get("rating_month") is not None
        ]
        average_rating_month = round(sum(ratings) / len(ratings), 2) if ratings else None

        top_product = max(
            rows,
            key=lambda r: (
                safe_int(r.get("review_count_month")),
                safe_number(r.get("rating_month")),
                r.get("sku") or "",
            ),
        )

        partners.append(
            {
                "seller_slug": seller_slug,
                "seller_name": seller_name,
                "product_count_with_reviews": product_count_with_reviews,
                "available_product_count": available_product_count,
                "total_reviews_month": total_reviews_month,
                "products_with_5_plus_reviews": products_with_5_plus_reviews,
                "average_rating_month": average_rating_month,
                "top_product_sku": top_product.get("sku"),
                "top_product_name": top_product.get("name"),
                "top_product_reviews_month": safe_int(top_product.get("review_count_month")),
            }
        )

    # Sort sellers by total monthly reviews, then product count, then name/slug
    partners.sort(
        key=lambda r: (
            -safe_int(r.get("total_reviews_month")),
            -safe_int(r.get("product_count_with_reviews")),
            r.get("seller_name") or "",
            r.get("seller_slug") or "",
        )
    )

    return partners


# -----------------------------------------------------------------------------
# Monthly build
# -----------------------------------------------------------------------------
def build_month(month_entry, cache):
    """
    Build enriched data files for a single month.

    Outputs:
    - enriched_products.json
    - partners_summary.json
    - summary.json
    """
    month = month_entry["month"]

    json_file = month_entry.get("json_file")
    if json_file:
        monthly_file = Path(json_file)
        if not monthly_file.is_absolute():
            monthly_file = PROJECT_ROOT / json_file
    else:
        monthly_file = MONTHLY_ROOT / month / "top_products.json"

    if not monthly_file.exists():
        print(f"⚠️ Missing monthly file: {monthly_file}")
        return

    data = load_json(monthly_file)
    items = data.get("items", [])

    enriched = []

    for row in items:
        sku = clean_sku(row.get("sku"))
        cache_row = cache.get(sku, {})

        enriched.append(
            {
                "sku": sku,
                "name": cache_row.get("name"),
                "seller_slug": cache_row.get("seller_slug"),
                "seller_name": cache_row.get("seller_name"),
                "product_url": cache_row.get("product_url"),
                "available": cache_row.get("available"),
                "review_count_month": row.get("review_count_month"),
                "rating_month": row.get("rating_month"),
            }
        )

    # -------------------------------------------------------------------------
    # Keep the month complete, but sort it into ranking order
    # -------------------------------------------------------------------------
    enriched.sort(
        key=lambda r: (
            -safe_int(r.get("review_count_month")),
            -safe_number(r.get("rating_month")),
            r.get("sku") or "",
        )
    )

    # -------------------------------------------------------------------------
    # Build partner summary
    # -------------------------------------------------------------------------
    partners_summary = build_partner_summary(enriched)

    # -------------------------------------------------------------------------
    # Summary stats
    # -------------------------------------------------------------------------
    review_counts = [
        safe_int(r["review_count_month"])
        for r in enriched
        if r.get("review_count_month") is not None
    ]

    summary = {
        "month": month,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "product_count_with_reviews": len(enriched),
        "products_with_name": sum(1 for r in enriched if r.get("name")),
        "products_with_seller": sum(1 for r in enriched if r.get("seller_name")),
        "products_available": sum(1 for r in enriched if r.get("available") is True),
        "products_missing_metadata": sum(1 for r in enriched if not r.get("name")),
        "seller_count_with_reviews": len(partners_summary),
        "top_review_count": max(review_counts) if review_counts else 0,
        "products_with_5_plus_reviews": sum(1 for x in review_counts if x >= 5),
        "products_with_10_plus_reviews": sum(1 for x in review_counts if x >= 10),
        "top_seller_reviews_month": (
            partners_summary[0]["total_reviews_month"] if partners_summary else 0
        ),
    }

    # -------------------------------------------------------------------------
    # Write files
    # -------------------------------------------------------------------------
    out_dir = DERIVED_ROOT / month

    save_json(out_dir / "enriched_products.json", enriched)
    save_json(out_dir / "partners_summary.json", partners_summary)
    save_json(out_dir / "summary.json", summary)

    print(
        f"✅ {month} | products={len(enriched)} "
        f"| sellers={len(partners_summary)} "
        f"| missing metadata={summary['products_missing_metadata']} "
        f"| 5+ reviews={summary['products_with_5_plus_reviews']}"
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    """
    Build enriched monthly datasets for all months in the index.
    """
    cache = load_cache()
    months = load_months()

    print(f"🗂 Months to process: {len(months)}")
    print()

    for month_entry in months:
        build_month(month_entry, cache)

    print()
    print("🏁 Enriched monthly datasets built.")


if __name__ == "__main__":
    main()
