import os
import re
import json
import random
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =========================
# DEFAULTS / PATHS
# =========================
DATA_DIR = "data"
MONTHLY_DIR = os.path.join(DATA_DIR, "monthly")
MONTHLY_INDEX = os.path.join(MONTHLY_DIR, "index.json")

CACHE_FILE = os.path.join(DATA_DIR, "cache", "products_cache.json")
PARTNERS_JSON = os.path.join("docs", "data", "partners_search.json")  # optional, if present

BASE_NOTHS = "https://www.notonthehighstreet.com"
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# =========================
# HELPERS
# =========================
def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_sku(raw):
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def make_session():
    sess = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


session = make_session()


def load_partner_lookup(partners_json_path: str):
    if os.path.exists(partners_json_path):
        try:
            with open(partners_json_path, "r", encoding="utf-8") as f:
                partners = json.load(f)
            print(f"📂 Loaded {len(partners)} partners from {partners_json_path}")
            return {p["slug"]: p["name"] for p in partners if p.get("slug") and p.get("name")}
        except Exception as e:
            print(f"⚠️ Could not load {partners_json_path}: {e}")
    return {}


partner_lookup = load_partner_lookup(PARTNERS_JSON)
seller_name_cache = {}


def get_seller_name(slug, fallback="Unknown Seller"):
    if not slug or slug in ["unknown", "Error"]:
        return fallback
    if slug in seller_name_cache:
        return seller_name_cache[slug]
    if slug in partner_lookup:
        seller_name_cache[slug] = partner_lookup[slug]
        return partner_lookup[slug]
    name = slug.replace("-", " ").title()
    seller_name_cache[slug] = name
    return name


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
        return {clean_sku(r.get("sku", "")): r for r in items if r.get("sku")}
    return {}


def save_cache(cache_by_sku: dict):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    items = list(cache_by_sku.values())
    items.sort(key=lambda r: r.get("sku", ""))
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def discover_months() -> list[str]:
    """
    Prefer data/monthly/index.json; if missing, scan folders and write it.
    """
    months = []
    if os.path.exists(MONTHLY_INDEX):
        try:
            with open(MONTHLY_INDEX, "r", encoding="utf-8") as f:
                months = [str(m).strip() for m in json.load(f) if str(m).strip()]
            months = [m for m in months if MONTH_RE.match(m)]
            months.sort(reverse=True)
            return months
        except Exception:
            pass

    # fallback scan
    if os.path.exists(MONTHLY_DIR):
        for name in os.listdir(MONTHLY_DIR):
            p = os.path.join(MONTHLY_DIR, name)
            if MONTH_RE.match(name) and os.path.isdir(p):
                months.append(name)
    months.sort(reverse=True)

    # write index for next time
    if months:
        os.makedirs(MONTHLY_DIR, exist_ok=True)
        with open(MONTHLY_INDEX, "w", encoding="utf-8") as f:
            json.dump(months, f, indent=2)
        print(f"🗓️ Wrote {MONTHLY_INDEX} ({len(months)} months)")

    return months


def load_monthly_skus(month: str) -> set[str]:
    monthly_file = os.path.join(MONTHLY_DIR, month, "top_products.json")
    if not os.path.exists(monthly_file):
        raise FileNotFoundError(f"Monthly file not found: {monthly_file}")

    with open(monthly_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    skus = set()
    for r in data.get("items", []):
        sku = clean_sku(r.get("sku", ""))
        if sku:
            skus.add(sku)
    return skus


# =========================
# NOTHS SCRAPE
# =========================
def get_noths_data(sku: str):
    """
    Find product via NOTHS search, follow first /product/ link,
    scrape title and seller slug.
    Returns: (product_name, product_url, seller_slug)
    """
    search_url = f"{BASE_NOTHS}/search?term={sku}"
    headers = {"User-Agent": random.choice(UA_POOL), "Accept-Language": "en-GB,en;q=0.9"}

    try:
        res = session.get(search_url, headers=headers, timeout=12)
        if res.status_code >= 400:
            return "Error", "Error", "Error"

        soup = BeautifulSoup(res.text, "html.parser")

        product_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product/" in href:
                if href.startswith("/"):
                    href = BASE_NOTHS + href
                product_link = href
                break

        if not product_link:
            if "/product/" in (res.url or ""):
                product_link = res.url
            else:
                return "Not found", "Not found", "unknown"

        prod_res = session.get(product_link, headers=headers, timeout=12)
        if prod_res.status_code >= 400:
            return "Error", "Error", "Error"

        prod_soup = BeautifulSoup(prod_res.text, "html.parser")
        h1 = prod_soup.find("h1")
        product_name = h1.get_text(strip=True) if h1 else "Not found"

        seller_slug = "unknown"
        partner_a = prod_soup.select_one('a[href^="/partners/"]')
        if partner_a and partner_a.has_attr("href"):
            m = re.search(r"/partners/([a-z0-9-]+)", partner_a["href"].lower(), re.I)
            if m:
                seller_slug = m.group(1)

        return product_name, product_link, seller_slug

    except Exception as e:
        print(f"⚠️ Error fetching {sku}: {e}")
        return "Error", "Error", "Error"


def build_meta(sku: str, month: str) -> dict | None:
    name, url, seller_slug = get_noths_data(sku)
    seller_name = get_seller_name(seller_slug)
    available = (name not in ["Not found", "Error"] and url not in ["Not found", "Error"])

    # Don’t poison cache with hard failures
    if name == "Error" and (url in ["Error", None, ""]):
        return None

    return {
        "sku": sku,
        "name": name,
        "seller_slug": seller_slug,
        "seller_name": seller_name,
        "product_url": url,
        "available": bool(available),
        "updated_at": now_iso(),
        "first_seen_month": month,
        "last_seen_month": month,
    }


# =========================
# MAIN
# =========================
def main():
    ap = argparse.ArgumentParser(description="Top up products_cache.json for ALL monthly top_products.json files.")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--months", nargs="*", default=None, help="Optional list like 2026-01 2025-12 ...")
    ap.add_argument("--sleep-min", type=float, default=0.4)
    ap.add_argument("--sleep-max", type=float, default=1.0)
    args = ap.parse_args()

    cache = load_cache()
    print(f"📦 Cache loaded: {len(cache)} SKUs")

    months = discover_months()
    if args.months:
        wanted = [m for m in args.months if MONTH_RE.match(m)]
        months = [m for m in months if m in set(wanted)]
    if not months:
        print("⚠️ No months found. Make sure data/monthly/YYYY-MM/top_products.json exists.")
        return

    print(f"🗓️ Months to process: {months}")

    total_missing = 0

    for month in months:
        try:
            monthly_skus = load_monthly_skus(month)
        except Exception as e:
            print(f"\n❌ {month}: {e}")
            continue

        # Update last_seen_month for anything already cached
        ts = now_iso()
        for sku in monthly_skus:
            if sku in cache:
                cache[sku]["last_seen_month"] = month
                cache[sku]["updated_at"] = ts

        missing = sorted([s for s in monthly_skus if s not in cache])
        total_missing += len(missing)

        print(f"\n=== {month} ===")
        print(f"🧾 Monthly SKUs: {len(monthly_skus)}")
        print(f"➕ Missing SKUs to fetch: {len(missing)}")

        if not missing:
            continue

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(build_meta, sku, month): sku for sku in missing}

            for i, fut in enumerate(as_completed(futures), 1):
                sku = futures[fut]
                try:
                    meta = fut.result()
                    if not meta:
                        print(f"❌ {i}: {sku} failed (skipping)")
                        continue

                    existing = cache.get(sku)

                    # preserve first_seen_month if already present
                    if existing and existing.get("first_seen_month"):
                        meta["first_seen_month"] = existing["first_seen_month"]

                    cache[sku] = {**(existing or {}), **meta}

                    print(f"✅ {i}: cached {sku} – {meta.get('name')} (Avail={meta.get('available')})")
                    time.sleep(random.uniform(args.sleep_min, args.sleep_max))

                except Exception as e:
                    print(f"⚠️ {i}: error caching {sku}: {e}")

        # Save after each month (safer if something crashes mid-run)
        save_cache(cache)
        print(f"💾 Saved cache after {month} → {CACHE_FILE}")

    print(f"\n✅ Done. Cache size now: {len(cache)} SKUs")
    print(f"ℹ️ Total newly fetched (missing) across months: {total_missing}")


if __name__ == "__main__":
    main()
