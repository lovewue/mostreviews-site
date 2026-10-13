"""
Celebrity / curated NOTHS theme pages, ranked by customer reviews.

NOTHS runs curated "theme" pages (e.g. Sara Davies' Christmas picks). The
theme page itself shows a star rating but no review counts, so this script
re-publishes the same list ranked by Feefo reviews, all time and last 12
months, with every product linked through Awin.

Two halves, deliberately separate:

1. SCRAPE (this script, weekly workflow): fetch the theme page, read the
   product list out of its __NEXT_DATA__ JSON, and save a snapshot to
   data/derived/themes/<slug>.json. The snapshot holds only what NOTHS says
   (SKU, title, brand, URL, NEW tag, stock, page position). No review counts.

2. RENDER (render_theme_pages() in render_site.py): join the snapshot to the
   current leaderboard JSONs by SKU at render time. Because the counts are
   joined at render time, the monthly Site Build & Publish refreshes them
   automatically from new data without re-scraping, and the weekly run
   refreshes the product list without waiting for new data.

Why __NEXT_DATA__ and not the rendered cards: the visible page only renders
the first 12 products and lazy-loads the rest in the browser, but the
server-side JSON carries every product along with fields the cards don't
expose cleanly: `code` (the real SKU), `isNew` (NOTHS's own NEW tag),
`purchasable` (false = out of stock) and `totalPages`. Plain `requests`, no
Selenium.

Why match on SKU: product URLs go stale when a seller renames (the
mixpixie -> thegiftedit problem). The SKU never changes, and the link we
publish is the theme page's own current URL, not a cached one.

Sanity gate: a theme page that suddenly returns no products, or under half
of what the last snapshot had, is far more likely to be a block or a NOTHS
template change than a real edit, so the previous snapshot is kept and the
run exits non-zero.

Usage:
    python scripts/build_theme_picks.py                  # every theme in THEMES
    python scripts/build_theme_picks.py --theme sara-davies-christmas-picks
    python scripts/build_theme_picks.py --no-render      # snapshot only
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
THEMES_ROOT = PROJECT_ROOT / "data" / "derived" / "themes"

BASE = "https://www.notonthehighstreet.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendListBot/1.0; +https://trendlist.co.uk/)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Below this share of the previous snapshot's product count, assume the fetch
# is broken rather than that NOTHS really emptied the theme.
MIN_KEEP_SHARE = 0.5

MAX_PAGES = 10


# -----------------------------------------------------------------------------
# Themes
# -----------------------------------------------------------------------------
# One entry per theme page. Adding another theme is a new entry here plus a
# nav/sitemap line if it should be linked; the scraper and renderer are
# generic.
#
#   slug         output file names: data/derived/themes/<slug>.json and
#                docs/<slug>.html
#   path         the NOTHS theme page path
#   title        page <h1> and <title>
#   label        how the intro names the NOTHS selection (linked to it)
#   curator      who chose the products, for the intro copy
#   description  meta description
THEMES = {
    "sara-davies-christmas-picks": {
        "path": "/themes/sara-davies-christmas-picks",
        "title": "Sara Davies' Christmas Picks, Ranked by Reviews",
        "label": "Sara Davies' Christmas picks",
        "curator": "Sara Davies",
        "description": (
            "Every product in Sara Davies' Christmas picks on Not On The High "
            "Street, ranked by customer reviews."
        ),
    },
    "lottie-lauras-christmas-picks": {
        "path": "/themes/lifestyle/lottie-lauras-top-christmas-picks",
        "title": "Lottie & Laura's Christmas Picks, Ranked by Reviews",
        "label": "Lottie & Laura's top Christmas picks",
        "curator": "Lottie & Laura",
        "description": (
            "Every product in Lottie & Laura's top Christmas picks on Not On "
            "The High Street, ranked by customer reviews."
        ),
    },
}


# -----------------------------------------------------------------------------
# Scrape
# -----------------------------------------------------------------------------
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def fetch_html(url: str, attempts: int = 3) -> str:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(10, 60))
            if r.status_code == 200:
                return r.text
            last_error = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_error = str(e)
        time.sleep(3 * attempt)
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def parse_products_state(html: str) -> dict:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise RuntimeError("No __NEXT_DATA__ block on the page")

    data = json.loads(m.group(1))
    try:
        return data["props"]["pageProps"]["updatedReduxState"]["products"]
    except (KeyError, TypeError):
        raise RuntimeError(
            "__NEXT_DATA__ has no props.pageProps.updatedReduxState.products; "
            "NOTHS may have changed the page structure"
        )


def clean_product(raw: dict, position: int) -> dict:
    href = (raw.get("detailPageHref") or "").split("?")[0]
    partner = raw.get("partner") or {}
    price = raw.get("price") or {}

    amount = price.get("amount")
    exponent = price.get("exponent", 2)
    price_gbp = round(amount / (10 ** exponent), 2) if isinstance(amount, (int, float)) else None

    # images[] are templates like ".../{size}_name.jpg"; "original" is the
    # 1024px master (checked Oct 2026), used for the social carousel.
    images = [i for i in (raw.get("images") or []) if isinstance(i, str)]
    image_url = images[0].replace("{size}", "original") if images else ""

    return {
        "position": position,
        "sku": str(raw.get("code") or ""),
        "name": (raw.get("title") or "").strip(),
        "seller_name": (partner.get("name") or "").strip(),
        "seller_slug": (partner.get("shortcode") or "").strip(),
        "product_url": f"{BASE}{href}" if href.startswith("/") else href,
        "is_new": raw.get("isNew") is True,
        # `available` stays true on out-of-stock items; `purchasable` is the
        # one that flips (the card shows "OUT OF STOCK").
        "in_stock": raw.get("purchasable") is not False and raw.get("available") is not False,
        "noths_rating": raw.get("averageRating"),
        "price_gbp": price_gbp,
        "image_url": image_url,
    }


def scrape_theme(path: str) -> list:
    products = []
    seen = set()
    page = 1
    total_pages = 1

    while page <= min(total_pages, MAX_PAGES):
        url = f"{BASE}{path}" + (f"?page={page}" if page > 1 else "")
        state = parse_products_state(fetch_html(url))

        total_pages = int(state.get("totalPages") or 1)
        pages = state.get("pages") or {}
        page_items = pages.get(str(page)) or next(iter(pages.values()), [])

        for raw in page_items:
            if not isinstance(raw, dict):
                continue
            item = clean_product(raw, position=len(products) + 1)
            if not item["sku"] or item["sku"] in seen:
                continue
            seen.add(item["sku"])
            products.append(item)

        page += 1
        if page <= total_pages:
            time.sleep(2)

    return products


def snapshot_path(slug: str) -> Path:
    return THEMES_ROOT / f"{slug}.json"


def load_snapshot(slug: str):
    path = snapshot_path(slug)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_snapshot(slug: str, theme: dict, products: list):
    THEMES_ROOT.mkdir(parents=True, exist_ok=True)

    previous = load_snapshot(slug) or {}
    previous_skus = {p.get("sku") for p in previous.get("products", [])}
    current_skus = {p["sku"] for p in products}

    payload = {
        "slug": slug,
        "theme_url": f"{BASE}{theme['path']}",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "product_count": len(products),
        "added_since_last_check": sorted(current_skus - previous_skus) if previous else [],
        "removed_since_last_check": sorted(previous_skus - current_skus) if previous else [],
        "products": products,
    }

    with open(snapshot_path(slug), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload


def refresh_theme(slug: str, theme: dict) -> bool:
    print(f"🎄 {slug}: fetching {BASE}{theme['path']}")

    try:
        products = scrape_theme(theme["path"])
    except Exception as e:
        print(f"   ❌ fetch/parse failed: {e}")
        print("   Keeping the previous snapshot.")
        return False

    previous = load_snapshot(slug)
    previous_count = (previous or {}).get("product_count") or 0

    if not products:
        print("   ❌ no products found. Keeping the previous snapshot.")
        return False

    if previous_count and len(products) < previous_count * MIN_KEEP_SHARE:
        print(
            f"   ❌ only {len(products)} products vs {previous_count} last time. "
            "Looks like a block or a page change, not a real edit. "
            "Keeping the previous snapshot."
        )
        return False

    payload = save_snapshot(slug, theme, products)

    print(
        f"   ✅ {payload['product_count']} products"
        f" | NEW: {sum(p['is_new'] for p in products)}"
        f" | out of stock: {sum(not p['in_stock'] for p in products)}"
    )
    if payload["added_since_last_check"]:
        print(f"   ↳ added: {', '.join(payload['added_since_last_check'])}")
    if payload["removed_since_last_check"]:
        print(f"   ↳ removed: {', '.join(payload['removed_since_last_check'])}")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--theme", help="Only refresh this theme slug")
    parser.add_argument("--no-render", action="store_true", help="Snapshot only, skip the HTML")
    args = parser.parse_args()

    if args.theme:
        if args.theme not in THEMES:
            print(f"Unknown theme '{args.theme}'. Known: {', '.join(THEMES)}")
            return 2
        selected = {args.theme: THEMES[args.theme]}
    else:
        selected = THEMES

    ok = True
    for slug, theme in selected.items():
        ok = refresh_theme(slug, theme) and ok

    if not args.no_render:
        # Render every theme with a snapshot, including ones whose fetch
        # failed this run: their previous list still gets the current review
        # counts. Imported here so --no-render works without the templates.
        sys.path.insert(0, str(SCRIPT_DIR))
        from render_site import copy_static, render_theme_pages

        copy_static()
        render_theme_pages()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
