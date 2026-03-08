import json
from datetime import datetime, timezone
from pathlib import Path


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
MONTHLY_ROOT = DATA_DIR / "monthly"
MONTHLY_INDEX_FILE = MONTHLY_ROOT / "index.json"

CACHE_FILE = DATA_DIR / "cache" / "products_cache.json"
DERIVED_ROOT = DATA_DIR / "derived" / "monthly"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def now_iso() -> str:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_sku(raw) -> str:
    """Normalise product code into a clean SKU string."""
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def load_json(path: Path):
    """Load JSON from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    """Save JSON to disk, creating folders if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Source loading
# -----------------------------------------------------------------------------
def load_cache() -> dict:
    """Load products cache keyed by SKU."""
    if not CACHE_FILE.exists():
        raise FileNotFoundError(f"Cache file not found: {CACHE_FILE}")

    rows = load_json(CACHE_FILE)

    cache = {}
    for row in rows:
        sku = clean_sku(row.get("sku", ""))
        if sku:
            cache[sku] = row

    print(f"📦 Loaded cache: {len(cache)} products")
    return cache


def load_month_index():
    """Load monthly index.json and return month entries."""
    if not MONTHLY_INDEX_FILE.exists():
        raise FileNotFoundError(f"Monthly index file not found: {MONTHLY_INDEX_FILE}")

    data = load_json(MONTHLY_INDEX_FILE)
    months = data.get("months", [])

    if not months:
        raise ValueError("No months found in monthly index")

    return months


def resolve_month_json_path(month_entry: dict) -> Path:
    """
    Resolve the input top_products.json path for a month.
    """
    json_file = month_entry.get("json_file")
    month = month_entry.get("month")

    if json_file:
        path = Path(json_file)
        if not path.is_absolute():
            return PROJECT_ROOT / path
        return path

    if month:
        return MONTHLY_ROOT / month / "top_products.json"

    raise ValueError(f"Could not resolve month json path from entry: {month_entry}")


# -----------------------------------------------------------------------------
# Enrichment logic
# -----------------------------------------------------------------------------
def enrich_products(month_data: dict, cache: dict) -> list:
    """
    Enrich monthly products from cache.

    Each item keeps monthly review data but gains product metadata.
    """
    enriched = []

    for row in month_data.get("items", []):
        sku = clean_sku(row.get("sku", ""))
        cache_row = cache.get(sku, {})

        enriched.append(
            {
                "sku": sku,
                "name": cache_row.get("name"),
                "seller_slug": cache_row.get("seller_slug"),
                "seller_name": cache_row.get("seller_name"),
                "product_url": cache_row.get("product_url"),
                "available": cache_row.get("available"),
                "review_count_month": int(row.get("review_count_month", 0) or 0),
                "rating_month": row.get("rating_month"),
            }
        )

    enriched.sort(
        key=lambda x: (
            -(x.get("review_count_month") or 0),
            -(x.get("rating_month") or 0 if x.get("rating_month") is not None else 0),
            x.get("sku") or "",
        )
    )

    return enriched


def build_partners_summary(products: list) -> list:
    """
    Aggregate monthly products into partner summary.
    """
    partners = {}

    for item in products:
        slug = item.get("seller_slug") or "unknown"
        name = item.get("seller_name") or "Unknown brand"
        reviews = item.get("review_count_month") or 0

        if slug not in partners:
            partners[slug] = {
                "seller_slug": slug,
                "seller_name": name,
                "product_count_month": 0,
                "total_reviews_month": 0,
            }

        partners[slug]["product_count_month"] += 1
        partners[slug]["total_reviews_month"] += reviews

    rows = list(partners.values())
    rows.sort(
        key=lambda x: (
            -(x.get("total_reviews_month") or 0),
            x.get("seller_name") or "",
        )
    )

    return rows


def build_month_summary(products: list, partners: list) -> dict:
    """
    Build summary stats for a month.

    Metrics:
    - total reviews
    - products reviewed
    - products with 5+ reviews
    - average reviews per product
    - top 100 share of reviews
    """
    total_reviews_month = sum((x.get("review_count_month") or 0) for x in products)
    product_count_with_reviews = sum(1 for x in products if (x.get("review_count_month") or 0) > 0)
    products_with_5_plus_reviews = sum(1 for x in products if (x.get("review_count_month") or 0) >= 5)

    average_reviews_per_product = 0
    if product_count_with_reviews:
        average_reviews_per_product = total_reviews_month / product_count_with_reviews

    top_100_reviews = sum((x.get("review_count_month") or 0) for x in products[:100])
    top_100_share_of_reviews = 0
    if total_reviews_month:
        top_100_share_of_reviews = top_100_reviews / total_reviews_month

    summary = {
        "generated_at": now_iso(),
        "total_reviews_month": total_reviews_month,
        "product_count_with_reviews": product_count_with_reviews,
        "seller_count_with_reviews": len(partners),
        "products_with_5_plus_reviews": products_with_5_plus_reviews,
        "average_reviews_per_product": round(average_reviews_per_product, 2),
        "top_100_share_of_reviews": round(top_100_share_of_reviews, 4),
        "top_review_count": max((x.get("review_count_month") or 0) for x in products) if products else 0,
    }

    return summary


# -----------------------------------------------------------------------------
# Main build
# -----------------------------------------------------------------------------
def main():
    cache = load_cache()
    months = load_month_index()

    print(f"🗂 Months to process: {len(months)}")
    print()

    for month_entry in months:
        month = month_entry.get("month")
        input_path = resolve_month_json_path(month_entry)

        if not input_path.exists():
            print(f"⚠️ Missing monthly file, skipping: {input_path}")
            continue

        month_data = load_json(input_path)

        products = enrich_products(month_data, cache)
        partners = build_partners_summary(products)
        summary = build_month_summary(products, partners)

        out_dir = DERIVED_ROOT / month
        save_json(out_dir / "enriched_products.json", products)
        save_json(out_dir / "partners_summary.json", partners)
        save_json(out_dir / "summary.json", summary)

        print(
            f"✅ {month} | "
            f"products={summary['product_count_with_reviews']} | "
            f"5+ reviews={summary['products_with_5_plus_reviews']} | "
            f"total reviews={summary['total_reviews_month']:,}"
        )

    print()
    print("🏁 Enriched monthly datasets built.")


if __name__ == "__main__":
    main()
