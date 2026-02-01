import os
import re
import json
import time
import random
import warnings
from io import BytesIO
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from PIL import Image, UnidentifiedImageError


# =====================
# CONFIG
# =====================
DATA_DIR = "data"
MONTH = "2026-01"  # <-- change this each month (or I can make it auto-detect)
MONTHLY_JSON = os.path.join(DATA_DIR, "monthly", MONTH, "top_products.json")

CACHE_JSON = os.path.join(DATA_DIR, "cache", "products_cache.json")

IMAGES_DIR = "Product_Images"
OUT_PATH_TEMPLATE = os.path.join(IMAGES_DIR, "{sku}.jpg")

TIMEOUT = 15
MAX_RETRIES = 3
MAX_BYTES = 8_000_000
SLEEP_RANGE = (0.4, 1.0)
MAX_TO_FETCH = 2000  # safety

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

NOTHS_HOSTS = {"www.notonthehighstreet.com", "notonthehighstreet.com"}
NOTHS_SEARCH = "https://www.notonthehighstreet.com/search?term={sku}"


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


def image_exists_jpg(sku: str) -> bool:
    return os.path.exists(OUT_PATH_TEMPLATE.format(sku=sku))


def polite_sleep():
    time.sleep(random.uniform(*SLEEP_RANGE))


def get_headers():
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def fetch(url: str) -> requests.Response | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=get_headers(), timeout=TIMEOUT, allow_redirects=True)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            return r
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"❌ Failed: {url} ({e})")
                return None
            time.sleep(0.6 * attempt)
    return None


def fetch_bytes(url: str) -> bytes | None:
    r = fetch(url)
    if not r:
        return None

    content = r.content
    if content and len(content) > MAX_BYTES:
        # too big; still try to process first MAX_BYTES
        content = content[:MAX_BYTES]
    return content


def pick_product_url_from_cache(meta: dict) -> str | None:
    # Prefer raw product URL if you store it; else product_url; else url.
    for k in ("raw_product_url", "product_url", "url"):
        u = meta.get(k)
        if is_noths_url(u):
            return normalize_url(u)
    return None


# =====================
# IMAGE EXTRACTION
# =====================
_NOT_FOUND_PAT = re.compile(r"we couldn[’']t find anything for", re.IGNORECASE)


def search_not_found(html: str | None) -> bool:
    return bool(html and _NOT_FOUND_PAT.search(html))


def pick_from_srcset(srcset: str) -> str | None:
    if not srcset:
        return None
    pairs = []
    for part in srcset.split(","):
        part = part.strip()
        if " " in part:
            url, w = part.rsplit(" ", 1)
            try:
                width = int(w.rstrip("w"))
            except Exception:
                width = 0
            pairs.append((width, url.strip()))
        else:
            pairs.append((0, part))
    if not pairs:
        return None
    pairs.sort(key=lambda x: x[0], reverse=True)
    return pairs[0][1]


def score_url(u: str) -> int:
    s = (u or "").lower()
    score = 0
    if "cdn.notonthehighstreet.com" in s: score += 3
    if "/system/product_images/images/" in s: score += 4
    if "/fs/" in s: score += 2
    if any(k in s for k in ("original_", "standard_", "large_", "zoom", "preview_")): score += 2
    if s.endswith((".jpg", ".jpeg")): score += 2
    if "logo" in s or "seller" in s: score -= 8
    return score


def extract_image_url_from_search(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    candidates = []

    # product image paths commonly show here
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and "/system/product_images/images/" in src:
            candidates.append(urljoin(base_url, src))

    # responsive images
    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            chosen = pick_from_srcset(srcset)
            if chosen and "/system/product_images/images/" in chosen:
                candidates.append(urljoin(base_url, chosen))

    if not candidates:
        return None

    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=score_url, reverse=True)
    return candidates[0]


def extract_image_url_from_pdp(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")

    # JSON-LD product image
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if isinstance(node, dict) and node.get("@type", "").lower() == "product":
                    img = node.get("image")
                    if isinstance(img, list) and img:
                        return urljoin(base_url, img[0])
                    if isinstance(img, str) and img:
                        return urljoin(base_url, img)
        except Exception:
            continue

    # og:image fallback
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(base_url, og["content"])

    # last resort: any CDN img
    urls = []
    for srcset in [s.get("srcset") for s in soup.find_all("source") if s.get("srcset")]:
        chosen = pick_from_srcset(srcset)
        if chosen:
            urls.append(urljoin(base_url, chosen))

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            urls.append(urljoin(base_url, src))

    urls = [u for u in urls if "cdn.notonthehighstreet.com" in (u or "").lower()]
    if not urls:
        return None

    urls = list(dict.fromkeys(urls))
    urls.sort(key=score_url, reverse=True)
    return urls[0]


def save_as_jpg(sku: str, content: bytes, out_dir: str) -> str | None:
    os.makedirs(out_dir, exist_ok=True)
    out_path = OUT_PATH_TEMPLATE.format(sku=sku)
    try:
        img = Image.open(BytesIO(content)).convert("RGB")
        img.save(out_path, "JPEG", quality=90, optimize=True)
        return out_path
    except UnidentifiedImageError:
        return None
    except Exception:
        return None


# =====================
# MAIN
# =====================
def main():
    if not os.path.exists(MONTHLY_JSON):
        print(f"❌ Monthly file not found: {MONTHLY_JSON}")
        return

    if not os.path.exists(CACHE_JSON):
        print(f"❌ Cache file not found: {CACHE_JSON}")
        return

    with open(MONTHLY_JSON, "r", encoding="utf-8") as f:
        monthly = json.load(f)

    items = monthly.get("items", [])
    skus = [clean_sku(x.get("sku")) for x in items if x.get("sku")]
    skus = list(dict.fromkeys(skus))

    with open(CACHE_JSON, "r", encoding="utf-8") as f:
        cache = json.load(f)
    cache_by_sku = {clean_sku(p.get("sku")): p for p in cache if p.get("sku")}

    missing = [s for s in skus if not image_exists_jpg(s)]
    print(f"🗓️ Month: {MONTH}")
    print(f"🖼️ Total SKUs: {len(skus)}")
    print(f"➕ Missing .jpg images: {len(missing)}")

    if not missing:
        print("✅ Nothing to do.")
        return

    os.makedirs(IMAGES_DIR, exist_ok=True)

    ok = 0
    no_url = 0
    no_img = 0
    unavailable = 0
    failed = 0

    for i, sku in enumerate(missing[:MAX_TO_FETCH], start=1):
        meta = cache_by_sku.get(sku, {})
        product_url = pick_product_url_from_cache(meta)

        print(f"\n[{i}/{len(missing)}] SKU {sku}")

        img_url = None

        # Prefer PDP if we have a proper URL
        if product_url:
            r = fetch(product_url)
            if r:
                img_url = extract_image_url_from_pdp(r.text, product_url)

        # Fallback to search-by-sku
        if not img_url:
            search_url = NOTHS_SEARCH.format(sku=sku)
            r = fetch(search_url)
            if not r:
                failed += 1
                continue

            if search_not_found(r.text):
                print("   ⛔ NOT FOUND in search (unavailable)")
                unavailable += 1
                polite_sleep()
                continue

            img_url = extract_image_url_from_search(r.text, search_url)

        if not img_url:
            print("   ⚠️ No image URL found")
            no_img += 1
            polite_sleep()
            continue

        print(f"   🔗 Image: {img_url}")
        content = fetch_bytes(img_url)
        if not content:
            print("   ❌ Download failed")
            failed += 1
            polite_sleep()
            continue

        saved = save_as_jpg(sku, content, IMAGES_DIR)
        if saved:
            print(f"   ✅ Saved: {saved}")
            ok += 1
        else:
            print("   ❌ Could not decode/save image (PIL)")
            failed += 1

        polite_sleep()

    print("\n📊 Monthly image top-up report")
    print(f"   ✅ Saved: {ok}")
    print(f"   ⛔ Unavailable (search): {unavailable}")
    print(f"   ⚠️ No image found: {no_img}")
    print(f"   ❌ Failed: {failed}")
    print("\nDone.")


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    main()
