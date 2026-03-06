import json
import random
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
# This makes the script work no matter where it is run from.
# Assumes this file lives in the project root or can resolve relative paths
# safely from the current project structure.
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
MONTHLY_ROOT = DATA_DIR / "monthly"
MONTHLY_INDEX_FILE = MONTHLY_ROOT / "index.json"
CACHE_FILE = DATA_DIR / "cache" / "products_cache.json"
PARTNERS_JSON = PROJECT_ROOT / "partners_search.json"  # optional helper file


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# This script:
# 1. Reads all monthly JSON files listed in data/monthly/index.json
# 2. Collects every SKU that appears across all months
# 3. Updates first_seen_month / last_seen_month from observed month appearances
# 4. Scrapes SKUs that are missing or due for retry using NOTHS search only
# 5. Writes / updates:
#       data/cache/products_cache.json
#
# Feefo recovery is now handled separately by:
#       scripts/recover_cache_feefo_selenium.py
# -----------------------------------------------------------------------------

BASE_NOTHS = "https://www.notonthehighstreet.com"

MAX_WORKERS = 5
SAVE_EVERY = 50

# Retry weak / unresolved records only after this many days
RETRY_DAYS_BY_STATUS = {
    "not_found": 30,
    "maybe_removed": 60,
    "error": 7,
}

# These are treated as complete enough for normal runs
GOOD_STATUSES = {
    "ok",
}

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------
def now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_sku(raw) -> str:
    """Normalise product codes into a clean string SKU."""
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def parse_iso_datetime(value: str | None):
    """Parse an ISO datetime string safely."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def clean_text(value: str | None) -> str | None:
    """Normalise whitespace in text."""
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def clean_url(url: str | None) -> str | None:
    """Normalise URLs and reject obvious junk values."""
    if not url:
        return None
    url = url.strip()
    if url.lower() in {"not found", "error", ""}:
        return None
    return url


def parse_seller_slug_from_product_url(url: str | None) -> str | None:
    """
    Extract seller slug from URLs like:
    https://www.notonthehighstreet.com/liviandbelle/product/extra-large-personalised-snowy-wreath
    """
    url = clean_url(url)
    if not url:
        return None

    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 3 and parts[1] == "product":
            return parts[0].lower()
    except Exception:
        return None

    return None


def normalise_placeholder(value):
    """
    Convert legacy placeholder values into None so they do not keep polluting
    later runs.
    """
    if isinstance(value, str) and value.strip().lower() in {
        "not found",
        "unknown",
        "unknown seller",
        "error",
        "",
    }:
        return None
    return value


# -----------------------------------------------------------------------------
# HTTP session
# -----------------------------------------------------------------------------
def make_session() -> requests.Session:
    """Create a requests session with retry behaviour."""
    sess = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["GET", "HEAD"],
    )

    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)

    return sess


def random_headers() -> dict:
    """Generate a browser-like header set."""
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept-Language": "en-GB,en;q=0.9",
    }


session = make_session()


# -----------------------------------------------------------------------------
# Retry logic
# -----------------------------------------------------------------------------
def should_retry_record(record: dict) -> bool:
    """
    Decide whether an existing cache record should be retried.

    Rules:
    - Missing record -> retry
    - name is NULL -> retry
    - Good statuses -> skip
    - Weak statuses -> retry after configured delay
    """
    if not record:
        return True

    # Always retry unresolved products
    if not record.get("name"):
        return True

    status = record.get("lookup_status")

    if status in GOOD_STATUSES:
        return False

    retry_days = RETRY_DAYS_BY_STATUS.get(status)
    if retry_days is None:
        return False

    last_checked = parse_iso_datetime(
        record.get("last_checked_at") or record.get("updated_at")
    )
    if not last_checked:
        return True

    age_days = (datetime.now(timezone.utc) - last_checked).days
    return age_days >= retry_days


# -----------------------------------------------------------------------------
# Optional seller name lookup
# -----------------------------------------------------------------------------
def load_partner_lookup() -> dict:
    """
    Load an optional partner slug -> seller name lookup.

    Expected structure:
        [
          {"slug": "wue", "name": "Wue"},
          ...
        ]
    """
    if PARTNERS_JSON.exists():
        try:
            with open(PARTNERS_JSON, "r", encoding="utf-8") as f:
                partners = json.load(f)

            lookup = {
                p["slug"]: p["name"]
                for p in partners
                if p.get("slug") and p.get("name")
            }

            print(f"📂 Loaded {len(lookup)} partners from {PARTNERS_JSON}")
            return lookup

        except Exception as e:
            print(f"⚠️ Could not load {PARTNERS_JSON}: {e}")

    return {}


partner_lookup = load_partner_lookup()
seller_name_cache = {}


def get_seller_name(slug: str | None, fallback: str | None = None) -> str | None:
    """
    Resolve a seller name from slug.

    Priority:
    1. in-memory cache
    2. partners_search.json lookup
    3. title-cased slug fallback
    """
    if not slug or slug in {"unknown", "Error"}:
        return fallback

    if slug in seller_name_cache:
        return seller_name_cache[slug]

    if slug in partner_lookup:
        seller_name_cache[slug] = partner_lookup[slug]
        return partner_lookup[slug]

    name = slug.replace("-", " ").title()
    seller_name_cache[slug] = name
    return name


# -----------------------------------------------------------------------------
# Cache I/O
# -----------------------------------------------------------------------------
def load_cache() -> dict:
    """Load the product cache into a dict keyed by SKU."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)

        cleaned = {}
        for r in items:
            sku = clean_sku(r.get("sku", ""))
            if not sku:
                continue

            r = {k: normalise_placeholder(v) for k, v in r.items()}
            r["sku"] = sku
            cleaned[sku] = r

        return cleaned

    return {}


def save_cache(cache_by_sku: dict) -> None:
    """Save the cache back to disk in a stable order."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    items = list(cache_by_sku.values())
    items.sort(key=lambda r: r.get("sku", ""))

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Monthly JSON loading
# -----------------------------------------------------------------------------
def load_monthly_index() -> list:
    """Load the monthly index and return the month entries."""
    if not MONTHLY_INDEX_FILE.exists():
        raise FileNotFoundError(f"Monthly index not found: {MONTHLY_INDEX_FILE}")

    with open(MONTHLY_INDEX_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    months = data.get("months", [])
    if not months:
        raise ValueError(f"No months found in: {MONTHLY_INDEX_FILE}")

    return months


def resolve_month_json_path(month_entry: dict) -> Path:
    """
    Resolve the path to a month's top_products.json.

    Prefers the json_file field from index.json, but falls back to the
    standard folder layout if needed.
    """
    json_file = month_entry.get("json_file")
    month = month_entry.get("month")

    if json_file:
        path = Path(json_file)
        if not path.is_absolute():
            return path

    if month:
        return MONTHLY_ROOT / month / "top_products.json"

    raise ValueError(f"Could not resolve monthly JSON path from entry: {month_entry}")


def load_monthly_sku_map() -> tuple[dict, set]:
    """
    Load all monthly JSON files and return:

    1. sku_months
    2. all_skus
    """
    months = load_monthly_index()

    sku_months = defaultdict(set)
    all_skus = set()

    for entry in months:
        month = entry.get("month")
        month_file = resolve_month_json_path(entry)

        if not month_file.exists():
            print(f"⚠️ Monthly file missing, skipping: {month_file}")
            continue

        with open(month_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data.get("items", []):
            sku = clean_sku(item.get("sku", ""))
            if not sku:
                continue

            all_skus.add(sku)
            if month:
                sku_months[sku].add(month)

    return sku_months, all_skus


# -----------------------------------------------------------------------------
# NOTHS lookup
# -----------------------------------------------------------------------------
def get_noths_data(sku: str) -> dict:
    """
    Find the product via NOTHS search, follow the first product link,
    and scrape product title + seller slug.

    Returns a structured lookup result.
    """
    search_url = f"{BASE_NOTHS}/search?term={sku}"

    try:
        res = session.get(search_url, headers=random_headers(), timeout=10)
        if res.status_code >= 400:
            return {
                "status": "error",
                "source": "noths_search",
                "name": None,
                "product_url": None,
                "seller_slug": None,
            }

        soup = BeautifulSoup(res.text, "html.parser")

        product_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product/" in href:
                if href.startswith("/"):
                    href = BASE_NOTHS + href
                product_link = href
                break

        # Sometimes search redirects straight to a product page
        if not product_link:
            if "/product/" in (res.url or ""):
                product_link = res.url
            else:
                return {
                    "status": "not_found",
                    "source": "noths_search",
                    "name": None,
                    "product_url": None,
                    "seller_slug": None,
                }

        prod_res = session.get(product_link, headers=random_headers(), timeout=10)
        if prod_res.status_code >= 400:
            return {
                "status": "error",
                "source": "noths_search",
                "name": None,
                "product_url": clean_url(product_link),
                "seller_slug": parse_seller_slug_from_product_url(product_link),
            }

        prod_soup = BeautifulSoup(prod_res.text, "html.parser")

        h1 = prod_soup.find("h1")
        product_name = clean_text(h1.get_text(strip=True) if h1 else None)

        seller_slug = None
        partner_a = prod_soup.select_one('a[href^="/partners/"]')
        if partner_a and partner_a.has_attr("href"):
            match = re.search(r"/partners/([a-z0-9-]+)", partner_a["href"], re.I)
            if match:
                seller_slug = match.group(1).lower()

        if not seller_slug:
            seller_slug = parse_seller_slug_from_product_url(product_link)

        if not product_name and not product_link:
            return {
                "status": "not_found",
                "source": "noths_search",
                "name": None,
                "product_url": None,
                "seller_slug": None,
            }

        return {
            "status": "ok",
            "source": "noths_search",
            "name": product_name,
            "product_url": clean_url(product_link),
            "seller_slug": seller_slug,
        }

    except Exception as e:
        print(f"⚠️ NOTHS error for {sku}: {e}")
        return {
            "status": "error",
            "source": "noths_search",
            "name": None,
            "product_url": None,
            "seller_slug": None,
        }


# -----------------------------------------------------------------------------
# Availability / live checks
# -----------------------------------------------------------------------------
def is_product_live(url: str | None) -> bool:
    """Check whether a product URL still resolves to a live product page."""
    url = clean_url(url)
    if not url:
        return False

    try:
        res = session.get(
            url,
            headers=random_headers(),
            allow_redirects=True,
            timeout=10,
        )

        if res.status_code >= 400:
            return False

        final_url = (res.url or "").lower()
        return "/product/" in final_url

    except Exception:
        return False


# -----------------------------------------------------------------------------
# Metadata build / merge logic
# -----------------------------------------------------------------------------
def merge_with_existing(existing: dict | None, fresh: dict) -> dict:
    """
    Merge fresh metadata into any existing cache record without wiping out
    good historical fields unnecessarily.
    """
    existing = existing or {}
    existing = {k: normalise_placeholder(v) for k, v in existing.items()}

    merged = dict(existing)

    for key in ["name", "seller_slug", "seller_name", "product_url"]:
        if fresh.get(key):
            merged[key] = fresh[key]

    for key in [
        "available",
        "updated_at",
        "last_checked_at",
        "lookup_status",
        "lookup_method",
        "lookup_attempts",
        "first_seen_month",
        "last_seen_month",
        "sku",
    ]:
        if key in fresh:
            merged[key] = fresh[key]

    return merged


def build_meta(
    sku: str,
    first_seen_month: str,
    last_seen_month: str,
    existing: dict | None = None,
) -> dict:
    """
    Build or refresh a cache record for a SKU using NOTHS only.

    Unresolved products are left for the Selenium Feefo recovery script.
    """
    existing = existing or {}
    previous_attempts = int(existing.get("lookup_attempts", 0) or 0)

    noths = get_noths_data(sku)

    if noths["status"] == "ok" and (noths.get("name") or noths.get("product_url")):
        seller_slug = noths.get("seller_slug")
        seller_name = get_seller_name(seller_slug)

        url = noths.get("product_url")
        available = is_product_live(url)

        timestamp = now_iso()
        fresh = {
            "sku": sku,
            "name": noths.get("name"),
            "seller_slug": seller_slug,
            "seller_name": seller_name,
            "product_url": url,
            "available": available,
            "lookup_status": "ok",
            "lookup_method": "noths_search",
            "lookup_attempts": previous_attempts + 1,
            "updated_at": timestamp,
            "last_checked_at": timestamp,
            "first_seen_month": existing.get("first_seen_month") or first_seen_month,
            "last_seen_month": last_seen_month,
        }
        return merge_with_existing(existing, fresh)

    # Could not recover via NOTHS fast path
    has_historical_good_data = any(
        existing.get(k) for k in ["name", "product_url", "seller_slug", "seller_name"]
    )

    timestamp = now_iso()
    fresh = {
        "sku": sku,
        "available": False if has_historical_good_data else existing.get("available", False),
        "lookup_status": "maybe_removed" if has_historical_good_data else "not_found",
        "lookup_method": "noths_search",
        "lookup_attempts": previous_attempts + 1,
        "updated_at": timestamp,
        "last_checked_at": timestamp,
        "first_seen_month": existing.get("first_seen_month") or first_seen_month,
        "last_seen_month": last_seen_month,
    }

    return merge_with_existing(existing, fresh)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> None:
    """Main cache rebuild / top-up process."""
    cache = load_cache()
    sku_months, all_skus = load_monthly_sku_map()
    months = load_monthly_index()

    to_process = sorted(
        [
            sku
            for sku in all_skus
            if sku not in cache or should_retry_record(cache.get(sku))
        ]
    )

    print(f"📦 Cache SKUs:      {len(cache)}")
    print(f"🗓️ Monthly SKUs:    {len(all_skus)}")
    print(f"🔄 To process:      {len(to_process)}")
    print(f"🗂️ Months scanned:   {len(months)}")
    print()

    # Update existing cache records based on observed month appearances
    ts = now_iso()

    for sku, months_seen in sku_months.items():
        if sku not in cache:
            continue

        first_seen = min(months_seen)
        last_seen = max(months_seen)

        cache[sku]["first_seen_month"] = cache[sku].get("first_seen_month") or first_seen
        cache[sku]["last_seen_month"] = last_seen
        cache[sku]["updated_at"] = ts

    if not to_process:
        save_cache(cache)
        print("✅ No SKUs need processing. Cache updated from monthly data.")
        return

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                build_meta,
                sku,
                min(sku_months[sku]),
                max(sku_months[sku]),
                cache.get(sku),
            ): sku
            for sku in to_process
        }

        for i, fut in enumerate(as_completed(futures), 1):
            sku = futures[fut]

            try:
                meta = fut.result()
                cache[sku] = meta

                print(
                    f"✅ {i}: cached {sku} – "
                    f"{meta.get('name') or '[no name]'} "
                    f"(status={meta.get('lookup_status')}, "
                    f"method={meta.get('lookup_method')}, "
                    f"avail={meta.get('available')})"
                )

                if i % SAVE_EVERY == 0:
                    save_cache(cache)
                    print(f"💾 Progress saved ({i} items)")

                time.sleep(random.uniform(0.4, 1.0))

            except Exception as e:
                print(f"⚠️ {i}: error caching {sku}: {e}")

    save_cache(cache)
    print()
    print(f"✅ Saved updated cache → {CACHE_FILE}")
    print("🏁 Cache top-up complete.")


if __name__ == "__main__":
    main()
