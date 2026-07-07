import json
import random
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

try:
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO
    PIL_OK = True
except Exception:
    PIL_OK = False


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
MONTHLY_DIR = DATA_DIR / "monthly"
MONTHLY_INDEX_FILE = MONTHLY_DIR / "index.json"
CACHE_FILE = DATA_DIR / "cache" / "products_cache.json"

LOCAL_PRODUCT_IMAGES_DIR = PROJECT_ROOT / "Product_Images"
SOCIAL_MEDIA_DIR = PROJECT_ROOT / "social_media"
LOGO_PATH = PROJECT_ROOT / "static" / "img" / "The-Trend-List-Logo.jpg"

TOP_N = 10

# --- Cover image design ---
COVER_SIZE = (1080, 1080)
COVER_BACKGROUND = (24, 60, 89)  # #183C59, site brand colour
COVER_TEXT_COLOR = (255, 255, 255)
FONT_PATHS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
FONT_PATHS_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]
TIMEOUT = 20
MAX_RETRIES = 3
SLEEP_RANGE = (0.5, 1.2)

NOTHS_HOSTS = {"www.notonthehighstreet.com", "notonthehighstreet.com"}

SESSION = requests.Session()


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


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_headers() -> dict:
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def load_months() -> list[str]:
    """All months with monthly data, oldest to newest doesn't matter — we
    process every one and skip what's already built."""
    if not MONTHLY_INDEX_FILE.exists():
        return []

    raw = load_json(MONTHLY_INDEX_FILE)
    months = []

    if isinstance(raw, dict):
        for entry in raw.get("months", []):
            if isinstance(entry, dict) and entry.get("month"):
                months.append(str(entry["month"]).strip())
    elif isinstance(raw, list):
        months = [str(m).strip() for m in raw if str(m).strip()]

    return sorted(set(months), reverse=True)


def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    rows = load_json(CACHE_FILE)
    return {clean_sku(r.get("sku", "")): r for r in rows if r.get("sku")}


def top_10_with_ties(items: list[dict]) -> list[dict]:
    """Same 'top N + ties' pattern used across the rest of the pipeline."""
    items = sorted(items, key=lambda x: x.get("review_count_month", 0) or 0, reverse=True)
    if len(items) <= TOP_N:
        return items
    cutoff = items[TOP_N - 1].get("review_count_month", 0) or 0
    return [p for p in items if (p.get("review_count_month") or 0) >= cutoff]


def month_total_reviews(month: str) -> int:
    """Sum review_count_month across ALL products that month, not just the
    top 10 — computed here directly so this script doesn't depend on
    build_enriched_monthly.py's output from the other workflow."""
    monthly_file = MONTHLY_DIR / month / "top_products.json"
    if not monthly_file.exists():
        return 0
    monthly = load_json(monthly_file)
    return sum(int(row.get("review_count_month", 0) or 0) for row in monthly.get("items", []))


def build_month_products(month: str, cache: dict) -> list[dict]:
    monthly_file = MONTHLY_DIR / month / "top_products.json"
    if not monthly_file.exists():
        return []

    monthly = load_json(monthly_file)
    products = []

    for row in monthly.get("items", []):
        sku = clean_sku(row.get("sku", ""))
        if not sku:
            continue

        meta = cache.get(sku, {})
        products.append({
            "sku": sku,
            "name": meta.get("name"),
            "seller_name": meta.get("seller_name"),
            "seller_slug": meta.get("seller_slug"),
            "product_url": meta.get("product_url"),
            "available": meta.get("available"),
            "review_count_month": int(row.get("review_count_month", 0) or 0),
        })

    return top_10_with_ties(products)


# -----------------------------------------------------------------------------
# Image sourcing (local first, then scrape as fallback)
# -----------------------------------------------------------------------------
def local_image_path(sku: str) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = LOCAL_PRODUCT_IMAGES_DIR / f"{sku}{ext}"
        if p.exists():
            return p
    return None


def resolve_noths_url(product_url: str | None) -> str | None:
    if not product_url:
        return None

    product_url = product_url.strip()

    try:
        parsed = urlparse(product_url)
    except Exception:
        return None

    host = (parsed.netloc or "").lower()

    if host in NOTHS_HOSTS:
        return product_url

    # AWIN deeplink — decode the real destination from ued=
    if "awin1.com" in host:
        qs = parse_qs(parsed.query)
        ued = qs.get("ued", [None])[0]
        if ued:
            decoded = unquote(ued)
            try:
                decoded_host = urlparse(decoded).netloc.lower()
            except Exception:
                return None
            if decoded_host in NOTHS_HOSTS:
                return decoded

    return None


def fetch_with_retries(url: str) -> requests.Response | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = SESSION.get(url, headers=get_headers(), timeout=TIMEOUT, allow_redirects=True)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            return r
        except Exception:
            if attempt == MAX_RETRIES:
                return None
            time.sleep(0.8 * attempt)
    return None


def extract_image_url_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()

    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return tw["content"].strip()

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "cdn.notonthehighstreet.com" in src or "/fs/" in src:
            return src

    return None


def download_and_save(image_url: str, out_path: Path) -> bool:
    res = fetch_with_retries(image_url)
    if not res:
        return False

    if PIL_OK:
        try:
            im = Image.open(BytesIO(res.content)).convert("RGB")
            im.save(out_path, "JPEG", quality=90, optimize=True)
            return True
        except Exception:
            pass

    try:
        with open(out_path, "wb") as f:
            f.write(res.content)
        return True
    except Exception:
        return False


def get_product_image(product: dict, out_path: Path) -> bool:
    """Try local Product_Images/ first, then scrape from the NOTHS page."""
    local = local_image_path(product["sku"])
    if local:
        shutil.copy2(local, out_path)
        return True

    noths_url = resolve_noths_url(product.get("product_url"))
    if not noths_url:
        return False

    page = fetch_with_retries(noths_url)
    if not page:
        return False

    image_url = extract_image_url_from_html(page.text)
    if not image_url:
        return False

    time.sleep(random.uniform(*SLEEP_RANGE))
    return download_and_save(image_url, out_path)


# -----------------------------------------------------------------------------
# Cover image generation
# -----------------------------------------------------------------------------
def _load_font(paths: list[str], size: int):
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _centered_text(draw, y, text, font, canvas_width, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (canvas_width - text_width) / 2
    draw.text((x, y), text, font=font, fill=fill)
    return bbox[3] - bbox[1]  # text height, for stacking the next line


def format_month_label(month: str) -> str:
    dt = datetime.strptime(month, "%Y-%m")
    return dt.strftime("%B %Y")


def build_cover_image(month: str, total_reviews: int, out_path: Path) -> bool:
    if not PIL_OK:
        return False

    canvas = Image.new("RGB", COVER_SIZE, COVER_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    width, height = COVER_SIZE

    y = 90

    # Logo, if available
    if LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_width = 420
            ratio = logo_width / logo.width
            logo = logo.resize((logo_width, int(logo.height * ratio)))
            canvas.paste(logo, (int((width - logo_width) / 2), y), logo)
            y += logo.height + 60
        except Exception:
            pass

    month_font = _load_font(FONT_PATHS_BOLD, 80)
    tagline_font = _load_font(FONT_PATHS_BOLD, 46)
    reviews_font = _load_font(FONT_PATHS_REGULAR, 34)

    y += _centered_text(draw, y, format_month_label(month), month_font, width, COVER_TEXT_COLOR)
    y += 40

    y += _centered_text(draw, y, "Top 10 Most Reviewed Products on NOTHS", tagline_font, width, COVER_TEXT_COLOR)
    y += 30

    _centered_text(draw, y, f"{total_reviews:,} reviews analysed", reviews_font, width, COVER_TEXT_COLOR)

    canvas.save(out_path, "JPEG", quality=92)
    return True


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def build_month_assets(month: str, cache: dict) -> None:
    out_dir = SOCIAL_MEDIA_DIR / month
    captions_path = out_dir / "captions.json"

    # Skip months already fully built (idempotent, matches rest of pipeline)
    if captions_path.exists():
        print(f"⏭️  {month}: already built, skipping", flush=True)
        return

    products = build_month_products(month, cache)
    if not products:
        print(f"⚠️  {month}: no product data found, skipping", flush=True)
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    total_reviews = month_total_reviews(month)
    cover_path = out_dir / "00_cover.jpg"
    cover_ok = build_cover_image(month, total_reviews, cover_path)
    if cover_ok:
        print(f"  🖼️  Cover image → 00_cover.jpg ({total_reviews:,} reviews)", flush=True)
    else:
        print("  ⚠️  Could not build cover image (Pillow unavailable or logo missing)", flush=True)

    captions = []
    rank = 0
    last_count = None

    print(f"\n=== {month} ({len(products)} products, top {TOP_N} + ties) ===", flush=True)

    for idx, product in enumerate(products, start=1):
        count = product.get("review_count_month", 0)
        if count != last_count:
            rank = idx
            last_count = count

        filename = f"{rank:02d}_{product['sku']}.jpg"
        out_path = out_dir / filename

        ok = get_product_image(product, out_path)

        if ok:
            print(f"  ✅ {rank:02d}. {product.get('name') or product['sku']} → {filename}", flush=True)
        else:
            print(f"  ❌ {rank:02d}. {product.get('name') or product['sku']} — no image found", flush=True)

        captions.append({
            "rank": rank,
            "sku": product["sku"],
            "image_file": filename if ok else None,
            "name": product.get("name"),
            "seller_name": product.get("seller_name"),
            "review_count_month": count,
            "product_url": product.get("product_url"),
        })

    save_json(captions_path, {
        "month": month,
        "generated_at": now_iso(),
        "cover_image": "00_cover.jpg" if cover_ok else None,
        "total_reviews_month": total_reviews,
        "products": captions,
    })

    found = sum(1 for c in captions if c["image_file"])
    print(f"📝 Wrote captions.json ({found}/{len(captions)} images found)", flush=True)


def main():
    cache = load_cache()
    months = load_months()

    if not months:
        print("⚠️ No months found in data/monthly/index.json", flush=True)
        return

    print(f"🗂 Months to process: {len(months)}", flush=True)

    for month in months:
        build_month_assets(month, cache)

    print("\n🏁 Social media asset build complete.", flush=True)


if __name__ == "__main__":
    main()
