import os
import re
import json
import time
import random
from io import BytesIO
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False


# =====================
# CONFIG
# =====================
DATA_DIR = "data"
CACHE_JSON = os.path.join(DATA_DIR, "cache", "products_cache.json")

# If you want a specific month:
MONTH = "2026-01"
MONTHLY_JSON = os.path.join(DATA_DIR, "monthly", MONTH, "top_products.json")

# Optional fallback source of SKUs:
TOP_12M_JSON = os.path.join(DATA_DIR, "top_products_last_12_months.json")

# Where your images live (you said you already have this folder)
IMAGES_DIR = "Product_Images"
OUT_EXT = ".jpg"  # keep consistent with your templates

MAX_TO_FETCH = 5000          # safety limit
SLEEP_RANGE = (0.4, 1.1)     # be gentle
TIMEOUT = 15
MAX_RETRIES = 3


UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

NOTHS_HOSTS = {"www.notonthehighstreet.com", "notonthehighstreet.com"}


# =====================
# HELPERS
# =====================
def clean_sku(raw) -> str:
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def normalize_url(u: str | None) -> str | None:
    if not u:
        return None
    u = str(u).strip()
    if not u:
        return None
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    # strip query/fragment
    u = u.split("?", 1)[0].split("#", 1)[0]
    return u


def is_noths_url(u: str | None) -> bool:
    u = normalize_url(u)
    if not u:
        return False
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        return False
    return host in NOTHS_HOSTS


def make_session() -> requests.Session:
    s = requests.Session()
    return s


SESSION = make_session()


def get_headers() -> dict:
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def polite_sleep():
    time.sleep(random.uniform(*SLEEP_RANGE))


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_skus_from_monthly(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    data = load_json(path)
    items = data.get("items", [])
    return [clean_sku(x.get("sku")) for x in items if x.get("sku")]


def load_skus_from_12m(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    data = load_json(path)
    out = []
    for r in data:
        sku = r.get("sku")
        if sku:
            out.append(clean_sku(sku))
    return out


def image_exists(sku: str) -> bool:
    return os.path.exists(os.path.join(IMAGES_DIR, f"{sku}{OUT_EXT}"))


def pick_product_url(meta: dict) -> str | None:
    # Prefer raw_product_url if you have it, else product_url
    for k in ("raw_product_url", "product_url", "url"):
        u = meta.get(k)
        if is_noths_url(u):
            return normalize_url(u)
    return None


def extract_image_url_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    # 1) OpenGraph is often present
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()

    # 2) Twitter image fallback
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return tw["content"].strip()

    # 3) Common NOTHS product image patterns in img tags
    # Look for large-ish images hosted on their CDN
    candidates = []
    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if "cdn.notonthehighstreet.com" in src or "/fs/" in src:
            candidates.append(src)

    # Some pages lazy-load via data-src / srcset
    for img in soup.find_all("img"):
        for attr in ("data-src", "data-original", "data-lazy", "data-srcset"):
            v = img.get(attr)
            if not v:
                continue
            v = str(v).strip()
            if "cdn.notonthehighstreet.com" in v or "/fs/" in v:
                # srcset can be multiple; take first URL-like token
                first = v.split(",")[0].strip().split(" ")[0].strip()
                candidates.append(first)

    # pick the "best" candidate (often longest URL contains 'original_')
    if candidates:
        candidates = list(dict.fromkeys(candidates))  # dedupe preserving order
        candidates.sort(key=lambda u: ("original_" in u, len(u)), reverse=True)
        return candidates[0]

    return None


def fetch_with_retries(url: str, is_binary: bool = False) -> requests.Response | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = SESSION.get(url, headers=get_headers(), timeout=TIMEOUT, allow_redirects=True)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            return r
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"❌ Failed: {url} ({e})")
                return None
            time.sleep(0.8 * attempt)
    return None


def save_as_jpg(content: bytes, out_path: str) -> bool:
    """
    Save bytes as jpg. Uses Pillow if available; otherwise saves raw bytes.
    (If no Pillow, and the source isn't JPG, it may not render.)
    """
    if PIL_OK:
        try:
            im = Image.open(BytesIO(content)).convert("RGB")
            im.save(out_path, "JPEG", quality=90, optimize=True)
            return True
        except Exception:
            return False
    else:
        # best effort: write raw
        try:
            with open(out_path, "wb") as f:
                f.write(content)
            return True
        except Exception:
            return False


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)

    if not os.path.exists(CACHE_JSON):
        print(f"❌ Missing cache: {CACHE_JSON}")
        return

    cache = load_json(CACHE_JSON)
    cache_by_sku = {clean_sku(r.get("sku")): r for r in cache if r.get("sku")}

    skus = []
    skus += load_skus_from_monthly(MONTHLY_JSON)
    if not skus:
        print(f"⚠️ No SKUs found in monthly file: {MONTHLY_JSON}")

    # Optional: uncomment if you want to also ensure 12-month products always have images
    # skus += load_skus_from_12m(TOP_12M_JSON)

    # De-dupe, keep order
    seen = set()
    skus = [s for s in skus if not (s in seen or seen.add(s))]

    missing = [s for s in skus if not image_exists(s)]
    print(f"🖼️ Total SKUs checked: {len(skus)}")
    print(f"➕ Missing images: {len(missing)}")

    if not missing:
        print("✅ Nothing to do.")
        return

    missing = missing[:MAX_TO_FETCH]

    ok = 0
    skipped_no_url = 0
    failed = 0

    for i, sku in enumerate(missing, start=1):
        meta = cache_by_sku.get(sku)
        if not meta:
            print(f"⏭️ {i}/{len(missing)} SKU {sku}: not in cache (skipping)")
            failed += 1
            continue

        product_url = pick_product_url(meta)
        if not product_url:
            print(f"⏭️ {i}/{len(missing)} SKU {sku}: no NOTHS URL in cache (skipping)")
            skipped_no_url += 1
            continue

        print(f"🔎 {i}/{len(missing)} SKU {sku}: {product_url}")

        page = fetch_with_retries(product_url)
        if not page:
            failed += 1
            continue

        img_url = extract_image_url_from_html(page.text)
        if not img_url:
            print(f"   ❌ Could not find image on page for {sku}")
            failed += 1
            continue

        img_url = normalize_url(img_url)
        if not img_url:
            print(f"   ❌ Bad image URL for {sku}")
            failed += 1
            continue

        img_res = fetch_with_retries(img_url, is_binary=True)
        if not img_res:
            failed += 1
            continue

        out_path = os.path.join(IMAGES_DIR, f"{sku}{OUT_EXT}")
        if save_as_jpg(img_res.content, out_path):
            print(f"   ✅ Saved {out_path}")
            ok += 1
        else:
            print(f"   ❌ Failed to save image for {sku} (try installing Pillow)")
            failed += 1

        polite_sleep()

    print("\n📊 Image top-up report")
    print(f"   ✅ Saved: {ok}")
    print(f"   ⏭️ No URL: {skipped_no_url}")
    print(f"   ❌ Failed: {failed}")


if __name__ == "__main__":
    main()
