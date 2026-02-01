import os
import re
import json
import random
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================
# CONFIG
# =========================
CACHE_FILE = "data/cache/products_cache.json"
MONTHLY_FILE = "data/monthly/2026-01/top_products.json"
MONTH = "2026-01"  # used for first_seen/last_seen updates
PARTNERS_JSON = "partners_search.json"  # optional

BASE_NOTHS = "https://www.notonthehighstreet.com"
MAX_WORKERS = 5

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

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
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess

session = make_session()

def load_partner_lookup():
    if os.path.exists(PARTNERS_JSON):
        try:
            with open(PARTNERS_JSON, "r", encoding="utf-8") as f:
                partners = json.load(f)
            print(f"📂 Loaded {len(partners)} partners from {PARTNERS_JSON}")
            return {p["slug"]: p["name"] for p in partners if p.get("slug") and p.get("name")}
        except Exception as e:
            print(f"⚠️ Could not load {PARTNERS_JSON}: {e}")
    return {}

partner_lookup = load_partner_lookup()
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

# =========================
# NOTHS SCRAPE
# =========================
def get_noths_data(sku: str):
    """
    Find the product via NOTHS search, follow first product link, scrape title and seller slug.
    Returns: (product_name, product_url, seller_slug)
    """
    search_url = f"{BASE_NOTHS}/search?term={sku}"
    headers = {
        "User-Agent": random.choice(UA_POOL),
        "Accept-Language": "en-GB,en;q=0.9",
    }

    try:
        res = session.get(search_url, headers=headers, timeout=10)
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
            # Sometimes search redirects straight to a product
            if "/product/" in res.url:
                product_link = res.url
            else:
                return "Not found", "Not found", "unknown"

        prod_res = session.get(product_link, headers=headers, timeout=10)
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

def is_product_live(url: str) -> bool:
    try:
        if not url or url in ["Not found", "Error"]:
            return False
        res = session.get(
            url,
            headers={"User-Agent": random.choice(UA_POOL)},
            allow_redirects=True,
            timeout=10,
        )
        if res.status_code >= 400:
            return False

        final_url = (res.url or "").lower()
        if "/product/" not in final_url:
            return False

        return True
    except Exception:
        return False

def build_meta(sku: str) -> dict | None:
    name, url, seller_slug = get_noths_data(sku)
    seller_name = get_seller_name(seller_slug)
    available = is_product_live(url)

    # Don’t poison cache with hard failures
    if name == "Error" and (url in ["Error", None, ""]):
        return None

    return {
        "sku": sku,
        "name": name,
        "seller_slug": seller_slug,
        "seller_name": seller_name,
        "product_url": url,
        "available": available,
        "updated_at": now_iso(),
        "first_seen_month": MONTH,
        "last_seen_month": MONTH,
    }

# =========================
# CACHE I/O
# =========================
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

def load_monthly_skus() -> set:
    if not os.path.exists(MONTHLY_FILE):
        raise FileNotFoundError(f"Monthly file not found: {MONTHLY_FILE}")
    with open(MONTHLY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    skus = set()
    for r in data.get("items", []):
        sku = clean_sku(r.get("sku", ""))
        if sku:
            skus.add(sku)
    return skus

# =========================
# MAIN
# =========================
def main():
    cache = load_cache()
    monthly_skus = load_monthly_skus()

    missing = sorted([s for s in monthly_skus if s not in cache])

    print(f"📦 Cache SKUs:   {len(cache)}")
    print(f"🗓️ Monthly SKUs: {len(monthly_skus)}")
    print(f"➕ Missing:      {len(missing)}")

    # Update last_seen_month for SKUs already in cache
    ts = now_iso()
    for sku in monthly_skus:
        if sku in cache:
            cache[sku]["last_seen_month"] = MONTH
            cache[sku]["updated_at"] = ts

    if not missing:
        save_cache(cache)
        print("✅ No missing SKUs. Cache updated (last_seen_month).")
        return

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(build_meta, sku): sku for sku in missing}

        for i, fut in enumerate(as_completed(futures), 1):
            sku = futures[fut]
            try:
                meta = fut.result()
                if not meta:
                    print(f"❌ {i}: {sku} failed (skipping)")
                    continue

                existing = cache.get(sku)

                # Preserve original first_seen_month if it already exists
                if existing and existing.get("first_seen_month"):
                    meta["first_seen_month"] = existing["first_seen_month"]

                cache[sku] = {**(existing or {}), **meta}

                print(f"✅ {i}: cached {sku} – {meta.get('name')} (Avail={meta.get('available')})")
                time.sleep(random.uniform(0.4, 1.0))

            except Exception as e:
                print(f"⚠️ {i}: error caching {sku}: {e}")

    save_cache(cache)
    print(f"✅ Saved updated cache → {CACHE_FILE}")

if __name__ == "__main__":
    main()
