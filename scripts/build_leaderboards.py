import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
CACHE_FILE = DATA_DIR / "cache" / "products_cache.json"

ALL_TIME_FILE = DATA_DIR / "feefo_product_ratings_all_20260501.xlsx"
LAST_12_MONTHS_FILE = DATA_DIR / "feefo_product_ratings_year_20260501.xlsx"

OUT_DIR = DATA_DIR / "derived" / "leaderboards"
OUT_ALL_TIME = OUT_DIR / "top_products_all_time.json"
OUT_LAST_12 = OUT_DIR / "top_products_last_12_months.json"

ARCHIVE_ALL_TIME = OUT_DIR / "top_products_all_time_archive.json"
ARCHIVE_LAST_12 = OUT_DIR / "top_products_last_12_months_archive.json"

PARTNERS_JSON = PROJECT_ROOT / "data" / "partners_search.json"


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
HEADLESS = False
CHROMEDRIVER_PATH = None


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_sku(raw) -> str:
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def clean_text(value):
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None


def clean_url(url):
    if not url:
        return None
    url = str(url).strip()
    if url.lower() in {"", "not found", "error", "none", "null"}:
        return None
    return url


def is_blank(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in {
        "",
        "none",
        "null",
        "unknown",
        "unknown brand",
        "unknown seller",
        "not found",
        "error",
    }


def parse_seller_slug_from_product_url(url):
    url = clean_url(url)
    if not url:
        return None

    try:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if len(parts) >= 3 and parts[1] == "product":
            return parts[0].lower()
    except Exception:
        return None

    return None


def normalise_placeholder(value):
    if is_blank(value):
        return None
    return value


def safe_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def safe_int(value, default=0):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Partner lookup
# -----------------------------------------------------------------------------
def load_partner_lookup() -> dict:
    if not PARTNERS_JSON.exists():
        return {}

    try:
        partners = load_json(PARTNERS_JSON)
        return {
            p["slug"]: p["name"]
            for p in partners
            if p.get("slug") and p.get("name")
        }
    except Exception:
        return {}


partner_lookup = load_partner_lookup()


def resolve_seller_name(slug, existing_name=None):
    existing_name = clean_text(existing_name)

    if slug and slug in partner_lookup:
        return partner_lookup[slug]

    if existing_name:
        return existing_name

    if slug:
        return slug.replace("-", " ").title()

    return None


# -----------------------------------------------------------------------------
# Cache / existing leaderboards
# -----------------------------------------------------------------------------
def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}

    rows = load_json(CACHE_FILE)
    cleaned = {}

    for row in rows:
        sku = clean_sku(row.get("sku", ""))
        if not sku:
            continue

        row = {k: normalise_placeholder(v) for k, v in row.items()}
        row["sku"] = sku
        cleaned[sku] = row

    return cleaned


def load_existing_leaderboard(path: Path) -> dict:
    if not path.exists():
        print(f"⚠️ Leaderboard file not found: {path}")
        return {}

    try:
        data = load_json(path)

        if isinstance(data, dict):
            rows = data.get("items", [])
        elif isinstance(data, list):
            rows = data
        else:
            rows = []

        out = {
            clean_sku(row.get("sku", "")): row
            for row in rows
            if isinstance(row, dict) and row.get("sku")
        }

        print(f"📂 Loaded {len(out)} rows from {path.name}")
        return out

    except Exception as e:
        print(f"⚠️ Could not load leaderboard file: {path}")
        print(e)
        return {}


# -----------------------------------------------------------------------------
# Selenium setup
# -----------------------------------------------------------------------------
def make_driver() -> webdriver.Chrome:
    options = Options()

    if HEADLESS:
        options.add_argument("--headless=new")

    if CHROMEDRIVER_PATH:
        service = Service(CHROMEDRIVER_PATH)
        return webdriver.Chrome(service=service, options=options)

    return webdriver.Chrome(options=options)


# -----------------------------------------------------------------------------
# Feefo scraping placeholder
# -----------------------------------------------------------------------------
def get_feefo_data_selenium(driver: webdriver.Chrome, sku: str) -> dict:
    # Keep this safe while Feefo recovery is unreliable.
    # Returning empty dict means "do not change existing item".
    return {}


# -----------------------------------------------------------------------------
# Leaderboard helpers
# -----------------------------------------------------------------------------
def merge_archive_fallback(item: dict, archive_rows: dict) -> dict:
    sku = clean_sku(item.get("sku", ""))
    archived = archive_rows.get(sku)

    if not archived:
        return item

    fields_to_restore = [
        "name",
        "seller_slug",
        "seller_name",
        "product_url",
        "available",
        "metadata_source",
    ]

    for key in fields_to_restore:
        current_value = item.get(key)
        archive_value = archived.get(key)

        if is_blank(current_value) and not is_blank(archive_value):
            item[key] = archive_value

    return item


def base_row(sku, reviews, rating, rank, cache, existing_rows):
    existing = existing_rows.get(sku, {})
    cache_row = cache.get(sku, {})

    row = {
        "rank": rank,
        "sku": sku,
        "name": existing.get("name") or cache_row.get("name"),
        "seller_slug": existing.get("seller_slug") or cache_row.get("seller_slug"),
        "seller_name": existing.get("seller_name") or cache_row.get("seller_name"),
        "product_url": existing.get("product_url") or cache_row.get("product_url"),
        "available": (
            existing.get("available")
            if existing.get("available") is not None
            else cache_row.get("available")
        ),
        "reviews": reviews,
        "rating": rating,
        "metadata_source": existing.get("metadata_source") or ("cache" if cache_row else "missing"),
    }

    if row.get("product_url") and not row.get("seller_slug"):
        row["seller_slug"] = parse_seller_slug_from_product_url(row["product_url"])

    row["seller_name"] = resolve_seller_name(row.get("seller_slug"), row.get("seller_name"))

    return row


def needs_feefo_enrichment(row: dict) -> bool:
    return (
        is_blank(row.get("name"))
        or is_blank(row.get("product_url"))
        or is_blank(row.get("seller_slug"))
        or is_blank(row.get("seller_name"))
    )


def build_leaderboard(path: Path, label: str, cache: dict, driver: webdriver.Chrome | None = None) -> dict:
    df = pd.read_excel(path)

    df["sku"] = df["Product Code"].apply(clean_sku)
    df["reviews"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0).astype(int)
    df["rating_value"] = pd.to_numeric(df.get("rating"), errors="coerce")

    existing_rows = load_existing_leaderboard(
        OUT_ALL_TIME if label == "all_time" else OUT_LAST_12
    )

    archive_rows = load_existing_leaderboard(
        ARCHIVE_ALL_TIME if label == "all_time" else ARCHIVE_LAST_12
    )

    full_product_count = len(df)
    full_total_reviews = int(df["reviews"].sum())
    average_reviews_per_product = full_total_reviews / full_product_count if full_product_count else 0

    df_sorted_for_stats = df.sort_values("reviews", ascending=False)
    top_100_reviews = int(df_sorted_for_stats.head(100)["reviews"].sum())
    top_100_share_of_reviews = top_100_reviews / full_total_reviews if full_total_reviews else 0

    if label == "all_time":
        threshold_count = int((df["reviews"] >= 500).sum())
    elif label == "last_12_months":
        threshold_count = int((df["reviews"] >= 10).sum())
    else:
        threshold_count = None

    df = df.sort_values(
        ["reviews", "rating_value", "sku"],
        ascending=[False, False, True]
    )

    items = []

    for rank, row in enumerate(df.itertuples(index=False), start=1):
        sku = getattr(row, "sku")
        reviews = safe_int(getattr(row, "reviews"))
        rating = safe_float(getattr(row, "rating_value"))

        item = base_row(sku, reviews, rating, rank, cache, existing_rows)

        # Restore old/manual metadata before trying any live recovery
        item = merge_archive_fallback(item, archive_rows)

        # Safe Feefo enrichment: only fills blanks, never downgrades good data
        if needs_feefo_enrichment(item) and driver is not None:
            recovered = get_feefo_data_selenium(driver, sku)

            if isinstance(recovered, dict):
                for key in ["name", "seller_slug", "seller_name", "product_url", "available"]:
                    if is_blank(item.get(key)) and not is_blank(recovered.get(key)):
                        item[key] = recovered[key]

        # Final fallback again in case Feefo added nothing
        item = merge_archive_fallback(item, archive_rows)

        items.append(item)

    output = {
        "leaderboard": label,
        "generated_at": now_iso(),
        "product_count": len(items),
        "total_products_reviewed": full_product_count,
        "total_reviews": full_total_reviews,
        "average_reviews_per_product": round(average_reviews_per_product, 2),
        "top_100_share_of_reviews": round(top_100_share_of_reviews, 4),
        "threshold_count": threshold_count,
        "items": items,
    }

    return output


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    cache = load_cache()

    # Driver retained for compatibility, but Feefo recovery is disabled safely above.
    driver = None

    all_time = build_leaderboard(ALL_TIME_FILE, "all_time", cache, driver)
    save_json(OUT_ALL_TIME, all_time)

    last_12 = build_leaderboard(LAST_12_MONTHS_FILE, "last_12_months", cache, driver)
    save_json(OUT_LAST_12, last_12)

    print(f"✅ All-time leaderboard written → {OUT_ALL_TIME}")
    print(f"✅ Last-12-months leaderboard written → {OUT_LAST_12}")
    print("🏁 Leaderboards built safely.")


if __name__ == "__main__":
    main()
