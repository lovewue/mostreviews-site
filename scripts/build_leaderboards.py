import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
CACHE_FILE = DATA_DIR / "cache" / "products_cache.json"

# NOTE: previously hardcoded to a specific date-stamped filename, which broke
# every month once that file was no longer the latest. Now auto-discovers the
# most recent matching file instead.
ALL_TIME_PATTERN = "feefo_product_ratings_all_*.xlsx"
LAST_12_MONTHS_PATTERN = "feefo_product_ratings_year_*.xlsx"

OUT_DIR = DATA_DIR / "derived" / "leaderboards"
OUT_ALL_TIME = OUT_DIR / "top_products_all_time.json"
OUT_LAST_12 = OUT_DIR / "top_products_last_12_months.json"

ARCHIVE_ALL_TIME = OUT_DIR / "top_products_all_time_archive.json"
ARCHIVE_LAST_12 = OUT_DIR / "top_products_last_12_months_archive.json"

PARTNERS_JSON = PROJECT_ROOT / "data" / "partners_search.json"

# -----------------------------------------------------------------------------
# Availability revalidation
# -----------------------------------------------------------------------------
# Products drop off NOTHS but nothing here ever noticed: a row's "available"
# flag was carried forward from the previous leaderboard build for ever, and
# the top-100 all-time rows are mostly NOT in products_cache.json at all (that
# cache is built from the monthly data, which only goes back to Apr 2025, while
# the all-time xlsx reaches much further). So the availability of the oldest,
# highest-ranked products was never checked by anything.
#
# This re-checks the top N rows of each leaderboard directly, at most every
# REVALIDATE_DAYS days per product. The result is stamped onto the row as
# availability_checked_at and carried forward by base_row(), so a normal build
# only spends requests on rows that have gone stale.
REVALIDATE_TOP_N = 100
REVALIDATE_DAYS = 30
REVALIDATE_WORKERS = 5

# If more than this share of checked rows come back dead, assume the run was
# blocked rather than the products being gone, and change nothing.
MAX_DEAD_SHARE = 0.5

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

session = requests.Session()


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


def find_latest_file(pattern: str) -> Path:
    """
    Find the most recently-dated file in data/ matching the given glob
    pattern. Replaces the old hardcoded single-filename approach, which
    broke every month once a new file was pulled.
    """
    candidates = sorted(DATA_DIR.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"No files found matching pattern: {pattern} in {DATA_DIR}")
    return candidates[-1]


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

def is_product_live(url) -> bool:
    """
    Whether a product URL still resolves to a live NOTHS product page.

    A delisted product redirects away from /product/ (usually to search or the
    partner page), so a 200 alone is not enough.
    """
    url = clean_url(url)
    if not url:
        return False

    try:
        res = session.get(
            url,
            headers={
                "User-Agent": random.choice(UA_POOL),
                "Accept-Language": "en-GB,en;q=0.9",
            },
            allow_redirects=True,
            timeout=10,
        )

        if res.status_code >= 400:
            return False

        return "/product/" in (res.url or "").lower()

    except Exception:
        return False


def needs_revalidation(item: dict, cutoff: datetime) -> bool:
    """A listed row is due a check if it has a URL and has not been checked recently."""
    if not clean_url(item.get("product_url")):
        return False

    checked = item.get("availability_checked_at")
    if not checked:
        return True

    try:
        return datetime.fromisoformat(str(checked).replace("Z", "+00:00")) < cutoff
    except Exception:
        return True


def revalidate_availability(items: list, label: str) -> int:
    """
    Re-check availability for the top REVALIDATE_TOP_N rows of a leaderboard.

    Runs after the rows are assembled, so it has the last word over both the
    previous leaderboard file and the archive fallback.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=REVALIDATE_DAYS)
    due = [i for i in items[:REVALIDATE_TOP_N] if needs_revalidation(i, cutoff)]

    if not due:
        print(f"OK {label}: no rows due an availability check")
        return 0

    print(f"Checking availability of {len(due)} {label} rows")

    results = {}

    with ThreadPoolExecutor(max_workers=REVALIDATE_WORKERS) as executor:
        futures = {
            executor.submit(is_product_live, item.get("product_url")): id(item)
            for item in due
        }

        for fut in as_completed(futures):
            key = futures[fut]

            try:
                results[key] = fut.result()
            except Exception as e:
                print(f"WARN availability check failed: {e}")

            time.sleep(random.uniform(0.2, 0.5))

    if not results:
        print(f"WARN {label}: every availability check failed, leaving rows untouched")
        return 0

    # Sanity gate. is_product_live() cannot tell "delisted" from "NOTHS blocked
    # us", so a rate-limit or an outage would come back as a wall of False and
    # asterisk the entire leaderboard. Genuinely dead products are a minority of
    # any top 100, so a majority-dead result means the pass itself is wrong.
    dead = sum(1 for live in results.values() if not live)
    dead_share = dead / len(results)

    if dead_share > MAX_DEAD_SHARE:
        print(
            f"WARN {label}: {dead}/{len(results)} rows came back dead "
            f"({dead_share:.0%}) - looks like a blocked or throttled run, "
            f"discarding this pass"
        )
        return 0

    changed = 0
    stamp = now_iso()

    for item in due:
        if id(item) not in results:
            continue

        live = results[id(item)]
        was = item.get("available")
        item["available"] = live
        item["availability_checked_at"] = stamp

        if was != live:
            changed += 1
            print(f"CHANGED {item.get('sku')} {was} -> {live} - {item.get('name')}")

    print(f"{label}: {changed} availability change(s) from {len(results)} checks")
    return changed


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
        # The cache is the source of truth for availability. This used to read
        # the previous leaderboard first, so once a row was written as available
        # that value won every future build and a delisted product could never
        # be corrected. The old value is kept only as a fallback for SKUs the
        # cache has no record of.
        "available": (
            cache_row.get("available")
            if cache_row.get("available") is not None
            else existing.get("available")
        ),
        "availability_checked_at": existing.get("availability_checked_at"),
        "reviews": reviews,
        "rating": rating,
        "metadata_source": existing.get("metadata_source") or ("cache" if cache_row else "missing"),
    }

    if row.get("product_url") and not row.get("seller_slug"):
        row["seller_slug"] = parse_seller_slug_from_product_url(row["product_url"])

    row["seller_name"] = resolve_seller_name(row.get("seller_slug"), row.get("seller_name"))

    return row


def build_leaderboard(path: Path, label: str, cache: dict) -> dict:
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

    # NOTE: key names below (products_with_500_plus_reviews /
    # products_with_10_plus_reviews) must match exactly what render_site.py
    # reads via data.get(...) — previously this was written as a generic
    # "threshold_count", which render_site.py never looked for, so the
    # stat always silently showed 0.
    if label == "all_time":
        threshold_key = "products_with_500_plus_reviews"
        threshold_count = int((df["reviews"] >= 500).sum())
    elif label == "last_12_months":
        threshold_key = "products_with_10_plus_reviews"
        threshold_count = int((df["reviews"] >= 10).sum())
    else:
        threshold_key = "products_with_threshold_reviews"
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

        items.append(item)

    revalidate_availability(items, label)

    output = {
        "leaderboard": label,
        "generated_at": now_iso(),
        "product_count": len(items),
        "total_products_reviewed": full_product_count,
        "total_reviews": full_total_reviews,
        "average_reviews_per_product": round(average_reviews_per_product, 2),
        "top_100_share_of_reviews": round(top_100_share_of_reviews, 4),
        threshold_key: threshold_count,
        "items": items,
    }

    return output


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    cache = load_cache()

    all_time_file = find_latest_file(ALL_TIME_PATTERN)
    last_12_months_file = find_latest_file(LAST_12_MONTHS_PATTERN)

    print(f"📄 Using all-time file: {all_time_file.name}")
    print(f"📄 Using last-12-months file: {last_12_months_file.name}")

    all_time = build_leaderboard(all_time_file, "all_time", cache)
    save_json(OUT_ALL_TIME, all_time)

    last_12 = build_leaderboard(last_12_months_file, "last_12_months", cache)
    save_json(OUT_LAST_12, last_12)

    print(f"✅ All-time leaderboard written → {OUT_ALL_TIME}")
    print(f"✅ Last-12-months leaderboard written → {OUT_LAST_12}")
    print("🏁 Leaderboards built safely.")


if __name__ == "__main__":
    main()
