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

try:
    from rembg import remove as rembg_remove, new_session as rembg_new_session
    REMBG_OK = True
except Exception:
    REMBG_OK = False


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

TOP_N = 10

# --- Cover image design (editorial style: bold left-aligned stacked text,
# highlighter-marker emphasis, textured background, colour rotates by month
# so the Instagram grid doesn't look repetitive) ---
COVER_SIZE = (1080, 1350)  # Instagram's standard 4:5 carousel ratio
# All the fixed pixel values below (font sizes, margins, gaps) were tuned
# against a 1080-tall canvas. This scales them proportionally so the layout
# doesn't leave a large empty gap if COVER_SIZE's height ever changes again.
_SCALE = COVER_SIZE[1] / 1080
# Trend List house style, matching the brand-orders carousel (Sep 2026).
#
# Black and white is the Trend List; the purple is NOTHS's, so the one colour
# on the page belongs to the marketplace the list is about. Black appears only
# in the wordmark and its rule — everything carrying information is purple, so
# nothing competes with the ranking itself.
BG_COLOR = (255, 255, 255)
PURPLE = (81, 40, 95)        # #51285F — NOTHS's current brand purple
INK = (17, 17, 17)           # #111111 — wordmark and footer rule only
MUTED = (87, 80, 92)         # #57505C — a purple-leaning grey; a neutral one
                             # looks dirty next to the aubergine
RULE = (228, 225, 230)

# Kept so existing callers still resolve; the per-month background rotation is
# gone. A recognisable house style does more for a feed than six rotating
# backgrounds did, and the carousel is now the same look as the website.
ACCENT_PURPLE = PURPLE
HIGHLIGHT_COLOR = PURPLE
TEXT_COLOR = INK
MUTED_COLOR = MUTED

# Anton is the logo's own face, so it is vendored into the repo rather than
# relying on it being installed — GitHub runners do not have it, and a silent
# fallback to DejaVu would quietly undo the whole restyle.
FONT_PATHS_DISPLAY = [
    str(PROJECT_ROOT / "static" / "fonts" / "Anton.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
]
FONT_PATHS_SERIF_BOLD = FONT_PATHS_DISPLAY  # legacy alias
FONT_PATHS_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_PATHS_REGULAR = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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


def month_bg_color(month: str) -> tuple[int, int, int]:
    """
    Every month now uses the same white background.

    This used to rotate through six saturated colours so the Instagram grid
    did not look repetitive. That is the opposite of what a house style wants:
    the posts are more recognisable as a set when they look identical, and the
    carousel now matches the website. The signature is the typography and the
    purple, not a different backdrop each month.
    """
    return BG_COLOR


_REMBG_SESSION = None


def _get_rembg_session():
    """Create the background-removal model session once and reuse it across
    every image in a run, rather than reloading the model per product."""
    global _REMBG_SESSION
    if _REMBG_SESSION is None and REMBG_OK:
        _REMBG_SESSION = rembg_new_session()
    return _REMBG_SESSION


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


def _looks_like_logo_or_banner(src: str, alt: str) -> bool:
    """Filter out seller shop logos/banners, which sometimes appear earlier
    in a product page's HTML than the actual product photo and would
    otherwise get grabbed by mistake."""
    haystack = f"{src} {alt}".lower()
    return any(
        term in haystack
        for term in ("logo", "banner", "storefront", "header", "brand-image", "shop-image")
    )


def extract_image_url_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", property="og:image")
    if og and og.get("content") and not _looks_like_logo_or_banner(og["content"], ""):
        return og["content"].strip()

    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content") and not _looks_like_logo_or_banner(tw["content"], ""):
        return tw["content"].strip()

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt") or ""

        if not src:
            continue
        if "cdn.notonthehighstreet.com" not in src and "/fs/" not in src:
            continue
        if _looks_like_logo_or_banner(src, alt):
            continue

        return src

    return None


def _looks_like_logo_or_banner(src: str, alt: str) -> bool:
    """Filter out seller shop logos/banners, which sometimes appear earlier
    in a product page's HTML than the actual product photo and would
    otherwise get grabbed by mistake."""
    haystack = f"{src} {alt}".lower()
    return any(
        term in haystack
        for term in ("logo", "banner", "storefront", "header", "brand-image", "shop-image")
    )


def _normalise_for_match(text: str) -> str:
    return " ".join(text.lower().split())


def _alt_matches_product_name(alt: str, product_name: str) -> bool:
    """NOTHS product images typically have alt text like
    '{Product Name}, 1 of 10' — matching on this directly ties the image to
    this specific product, which is far more reliable than og:image (which
    can point to something else entirely on out-of-stock or otherwise
    unusual listings)."""
    if not alt or not product_name:
        return False

    alt_norm = _normalise_for_match(alt)
    name_norm = _normalise_for_match(product_name)

    if alt_norm.startswith(name_norm):
        return True

    name_words = set(name_norm.split())
    alt_words = set(alt_norm.split())
    if not name_words:
        return False
    overlap = len(name_words & alt_words) / len(name_words)
    return overlap >= 0.8


def extract_image_url_from_html(html: str, product_name: str | None = None) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    # Primary strategy: find the <img> whose alt text matches the actual
    # product name — this ties the image directly to this specific product,
    # sidestepping issues with og:image pointing elsewhere (e.g. on
    # out-of-stock listings) or picking up the wrong product entirely.
    if product_name:
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            alt = img.get("alt") or ""

            if not src:
                continue
            if "cdn.notonthehighstreet.com" not in src and "/fs/" not in src:
                continue
            if _alt_matches_product_name(alt, product_name):
                return src

    # Fallback: og:image / twitter:image / first plausible CDN image,
    # filtering out anything that looks like a seller logo or banner.
    og = soup.find("meta", property="og:image")
    if og and og.get("content") and not _looks_like_logo_or_banner(og["content"], ""):
        return og["content"].strip()

    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content") and not _looks_like_logo_or_banner(tw["content"], ""):
        return tw["content"].strip()

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt") or ""

        if not src:
            continue
        if "cdn.notonthehighstreet.com" not in src and "/fs/" not in src:
            continue
        if _looks_like_logo_or_banner(src, alt):
            continue

        return src

    return None


def _image_looks_like_logo_or_blank(im: "Image.Image", threshold: float = 0.85) -> bool:
    """Second layer of defense beyond the URL/alt-text filter: if an image
    is overwhelmingly one dominant flat colour — regardless of which colour,
    white, black, or a brand colour — it's very likely a logo graphic rather
    than real product photography (which, even on a plain background,
    normally has much more colour variation from the product itself,
    shadows, and texture).
    """
    sample = im.convert("RGB").resize((100, 100))
    pixels = list(sample.getdata())

    buckets: dict[tuple[int, int, int], int] = {}
    for r, g, b in pixels:
        key = (r // 16 * 16, g // 16 * 16, b // 16 * 16)
        buckets[key] = buckets.get(key, 0) + 1

    dominant_count = max(buckets.values())
    return (dominant_count / len(pixels)) >= threshold


def download_and_save(image_url: str, out_path: Path) -> bool:
    res = fetch_with_retries(image_url)
    if not res:
        return False

    if PIL_OK:
        try:
            im = Image.open(BytesIO(res.content)).convert("RGB")

            if _image_looks_like_logo_or_blank(im):
                return False

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


def extract_seller_name_from_title(html: str) -> str | None:
    """NOTHS product page titles follow the pattern
    '{Product Name} By {Real Brand Name}' — this is a more reliable source
    for the proper display name than the cache's seller_name field, which
    sometimes falls back to a title-cased version of the slug (e.g.
    'Butlerandgrace' instead of the real 'Butler & Grace')."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if not title_tag or not title_tag.text:
        return None

    title = title_tag.text.strip()
    if " By " not in title:
        return None

    seller_part = title.split(" By ", 1)[1]
    for sep in ("|", " - ", " – "):
        if sep in seller_part:
            seller_part = seller_part.split(sep, 1)[0]

    seller_part = seller_part.strip()
    return seller_part or None


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

    final_url = str(page.url or "")
    if "/product/" not in final_url:
        return False

    real_seller_name = extract_seller_name_from_title(page.text)
    if real_seller_name:
        product["seller_name"] = real_seller_name

    image_url = extract_image_url_from_html(page.text, product.get("name"))
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


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def format_month_label(month: str) -> str:
    dt = datetime.strptime(month, "%Y-%m")
    return dt.strftime("%B %Y")


def _draw_tracked(draw, xy, text, font, fill, tracking):
    """
    Draw text with extra letter-spacing, which Pillow has no setting for.

    The small uppercase labels need generous tracking to read as labels rather
    than shouting, so they are drawn a character at a time.
    """
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _draw_block_line(draw, x, y, text, font, pad_x, pad_y):
    """A line of white type knocked out of a solid purple block.

    #51285F is too dark to work as a highlight colour against black text, so
    the emphasis is carried by a filled field instead. It is the one device
    that repeats across every slide.
    """
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.rectangle(
        [x - pad_x, y - pad_y, x + text_w + pad_x, y + text_h + pad_y],
        fill=PURPLE,
    )
    draw.text((x, y - bbox[1]), text, font=font, fill=(255, 255, 255))
    return text_h


def _draw_footer(draw, width, height, margin, right_label="SWIPE \u2192"):
    """The wordmark lockup that closes every slide: black rule, black
    'THE TREND LIST' with the asterisk in purple, and a purple right label."""
    y_rule = height - round(150 * _SCALE)
    draw.rectangle(
        [margin, y_rule, width - margin, y_rule + round(5 * _SCALE)],
        fill=INK,
    )

    y = y_rule + round(32 * _SCALE)
    mark_font = _load_font(FONT_PATHS_DISPLAY, round(34 * _SCALE))
    draw.text((margin, y), "THE TREND LIST", font=mark_font, fill=INK)
    mark_w = draw.textlength("THE TREND LIST", font=mark_font)
    draw.text((margin + mark_w, y), "*", font=mark_font, fill=PURPLE)

    label_font = _load_font(FONT_PATHS_BOLD, round(28 * _SCALE))
    label_w = draw.textlength(right_label, font=label_font)
    draw.text((width - margin - label_w, y + round(4 * _SCALE)),
              right_label, font=label_font, fill=PURPLE)


def build_cover_image(month: str, bg_color: tuple[int, int, int], total_reviews: int, out_path: Path) -> bool:
    """
    Cover slide, same shape as the brand-orders carousel: a label, one very
    large number, a statement with its key line knocked out of a purple block,
    then the wordmark lockup.

    The number leads because it is the thing worth stopping for. The old cover
    opened with the month, which tells a scrolling reader nothing.
    """
    if not PIL_OK:
        return False

    width, height = COVER_SIZE
    canvas = Image.new("RGB", COVER_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    margin = round(76 * _SCALE)

    # Kicker
    kicker_font = _load_font(FONT_PATHS_BOLD, round(24 * _SCALE))
    _draw_tracked(draw, (margin, round(84 * _SCALE)),
                  "NOT ON THE HIGH STREET", kicker_font, MUTED, round(4.5 * _SCALE))

    # Hero number — the month's review count
    hero_font = _load_font(FONT_PATHS_DISPLAY, round(300 * _SCALE))
    hero_text = f"{total_reviews:,}"
    bbox = draw.textbbox((0, 0), hero_text, font=hero_font)
    y = round(140 * _SCALE)
    draw.text((margin, y - bbox[1]), hero_text, font=hero_font, fill=PURPLE)
    y += (bbox[3] - bbox[1]) + round(44 * _SCALE)

    # Statement, with the middle line reversed out of a purple block
    month_label = format_month_label(month).upper()
    sub_font = _load_font(FONT_PATHS_DISPLAY, round(70 * _SCALE))
    line_gap = round(26 * _SCALE)

    for text, blocked in [
        (f"REVIEWS IN {month_label}.", False),
        ("THE TOP 10 MOST REVIEWED", True),
        ("PRODUCTS ON NOTHS", False),
    ]:
        if blocked:
            h = _draw_block_line(draw, margin, y, text, sub_font,
                                 round(14 * _SCALE), round(12 * _SCALE))
            y += h + line_gap + round(10 * _SCALE)
        else:
            b = draw.textbbox((0, 0), text, font=sub_font)
            draw.text((margin, y - b[1]), text, font=sub_font, fill=PURPLE)
            y += (b[3] - b[1]) + line_gap

    # Supporting line, wrapped to the text column
    note_font = _load_font(FONT_PATHS_REGULAR, round(30 * _SCALE))
    y += round(18 * _SCALE)
    note = "Ranked by the reviews each product picked up during the month."
    words, line = note.split(), ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=note_font) > (width - margin * 2):
            draw.text((margin, y), line, font=note_font, fill=MUTED)
            y += round(44 * _SCALE)
            line = word
        else:
            line = trial
    if line:
        draw.text((margin, y), line, font=note_font, fill=MUTED)

    _draw_footer(draw, width, height, margin)

    canvas.save(out_path, "JPEG", quality=92)
    return True


# -----------------------------------------------------------------------------
# Product slide generation (cutout on branded background, matching the cover)
# -----------------------------------------------------------------------------
def _wrap_text_no_truncate(draw, text, font, max_width, max_lines):
    """Word-wrap without truncating — returns None if the text genuinely
    doesn't fit in max_lines at this font size, so the caller can try a
    smaller size instead of settling for an ellipsis."""
    words = text.split()
    lines = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                return None  # doesn't fit — caller should try a smaller size

    if current:
        lines.append(current)

    if len(lines) > max_lines:
        return None

    return lines


def fit_product_name(draw, text, font_paths, max_width, max_font_size, min_font_size=32, max_lines=2):
    """Find the largest font size that fits the full product name within
    max_lines with no truncation. Shrinking the text is much better than
    cutting it off with "..." — only truncates as a last resort if even the
    minimum size and an extra line still can't fit (very long names)."""
    size = max_font_size

    while size >= min_font_size:
        font = _load_font(font_paths, size)
        lines = _wrap_text_no_truncate(draw, text, font, max_width, max_lines)
        if lines is not None:
            return font, lines
        size -= 4

    # Last resort: minimum size, one extra line, truncate only if it still
    # doesn't fit even then.
    font = _load_font(font_paths, min_font_size)
    lines = _wrap_text_no_truncate(draw, text, font, max_width, max_lines + 1)
    if lines is not None:
        return font, lines

    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current:
        lines.append(current)
    lines = lines[:max_lines + 1]

    last = lines[-1]
    while last and draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
        last = last[:-1].rstrip()
    lines[-1] = last + "…"

    return font, lines


def remove_background(image_path: Path) -> "Image.Image | None":
    """Cut the product out from its original photo background using rembg.
    Returns an RGBA image with transparent background, or None if rembg
    isn't available or the removal fails."""
    if not REMBG_OK:
        return None

    try:
        session = _get_rembg_session()
        with open(image_path, "rb") as f:
            input_bytes = f.read()
        output_bytes = rembg_remove(input_bytes, session=session)
        return Image.open(BytesIO(output_bytes)).convert("RGBA")
    except Exception:
        return None


def build_product_slide(raw_image_path: Path, product: dict, bg_color: tuple[int, int, int], out_path: Path) -> bool:
    """Product slide in the house style: the cutout on white, product name in
    Anton purple, seller underneath, wordmark lockup at the foot.

    Still no rank number on the image — with this many tied review counts,
    numbering looks wrong more often than it looks right. The filename keeps
    the rank so the carousel uploads in order.
    """
    if not PIL_OK:
        return False

    width, height = COVER_SIZE
    canvas = Image.new("RGB", COVER_SIZE, BG_COLOR)

    cutout = remove_background(raw_image_path)

    if cutout is None:
        # Fallback: no background removal available — place the original
        # photo, uncut, rather than failing the whole slide.
        try:
            cutout = Image.open(raw_image_path).convert("RGBA")
        except Exception:
            return False

    # Fit the product into the upper portion, preserving aspect ratio.
    max_product_width = int(width * 0.72)
    max_product_height = int(height * 0.52)

    ratio = min(max_product_width / cutout.width, max_product_height / cutout.height)
    new_size = (int(cutout.width * ratio), int(cutout.height * ratio))
    cutout = cutout.resize(new_size, Image.LANCZOS)

    paste_x = (width - cutout.width) // 2
    paste_y = round(96 * _SCALE)
    canvas.paste(cutout, (paste_x, paste_y), cutout)

    draw = ImageDraw.Draw(canvas)
    margin = round(76 * _SCALE)
    max_text_width = width - margin * 2

    y = paste_y + max_product_height + round(54 * _SCALE)

    name = (product.get("name") or f"Product {product.get('sku', '')}").upper()
    name_font, name_lines = fit_product_name(
        draw, name, FONT_PATHS_DISPLAY, max_text_width,
        max_font_size=round(62 * _SCALE), min_font_size=round(34 * _SCALE),
    )

    for line in name_lines:
        bbox = draw.textbbox((0, 0), line, font=name_font)
        draw.text((margin, y - bbox[1]), line, font=name_font, fill=PURPLE)
        y += (bbox[3] - bbox[1]) + round(14 * _SCALE)

    seller_name = product.get("seller_name")
    if seller_name:
        y += round(12 * _SCALE)
        seller_font = _load_font(FONT_PATHS_REGULAR, round(32 * _SCALE))
        seller_text = f"by {seller_name}"
        bbox = draw.textbbox((0, 0), seller_text, font=seller_font)
        draw.text((margin, y - bbox[1]), seller_text, font=seller_font, fill=MUTED)

    _draw_footer(draw, width, height, margin)

    canvas.convert("RGB").save(out_path, "JPEG", quality=92)
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
    bg_color = month_bg_color(month)

    total_reviews = month_total_reviews(month)
    cover_path = out_dir / "00_cover.jpg"
    cover_ok = build_cover_image(month, bg_color, total_reviews, cover_path)
    if cover_ok:
        print(f"  🖼️  Cover image → 00_cover.jpg ({total_reviews:,} reviews)", flush=True)
    else:
        print("  ⚠️  Could not build cover image (Pillow unavailable)", flush=True)

    if not REMBG_OK:
        print("  ⚠️  rembg not installed — product cutouts will fall back to uncut photos", flush=True)

    captions = []
    rank = 0
    last_count = None

    print(f"\n=== {month} ({len(products)} products, top {TOP_N} + ties) ===", flush=True)

    for idx, product in enumerate(products, start=1):
        count = product.get("review_count_month", 0)
        if count != last_count:
            rank = idx
            last_count = count

        # Filenames still carry the rank prefix so carousel upload order is
        # correct — we just don't display "#N" on the image itself, since
        # ties mean multiple products share the same rank.
        filename = f"{rank:02d}_{product['sku']}.jpg"
        out_path = out_dir / filename
        raw_path = out_dir / f"_raw_{product['sku']}.jpg"

        got_raw = get_product_image(product, raw_path)

        if got_raw:
            styled = build_product_slide(raw_path, product, bg_color, out_path)
            raw_path.unlink(missing_ok=True)
            if styled:
                print(f"  ✅ {rank:02d}. {product.get('name') or product['sku']} → {filename}", flush=True)
            else:
                print(f"  ❌ {rank:02d}. {product.get('name') or product['sku']} — styling failed", flush=True)
                got_raw = False
        else:
            print(f"  ❌ {rank:02d}. {product.get('name') or product['sku']} — no image found", flush=True)

        captions.append({
            "rank": rank,
            "sku": product["sku"],
            "image_file": filename if got_raw else None,
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
