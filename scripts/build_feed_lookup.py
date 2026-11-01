#!/usr/bin/env python3
"""
Build data/cache/feed_products.json from the Awin NOTHS product feed.

Why
---
Product thumbnails on the site come from the Awin feed, not from NOTHS product
pages. The feed is published to affiliates for promoting the products, so the
permission is clear, and the images are linked (Awin-hosted), never copied into
the repo — docs/ is already over GitHub Pages' 1 GB artifact limit.

Feed: Awin Create-a-Feed, advertiser Not On The High Street (programme 18484),
datafeed "Default" (37219), CSV, gzip. ~255k rows, ~130 MB compressed.
`merchant_product_id` is the NOTHS SKU — the same key Trendlist already uses.

Only the SKUs the site actually renders are kept (leaderboards, month pages,
theme picks), so the output stays small (a few hundred KB) however big the feed.

Source, in order:
  --feed PATH               a downloaded .csv.gz (or .csv)
  AWIN_FEED_URL env var     the Create-a-Feed "manual download URL"

The URL contains the Awin API key. It must only ever live in the
AWIN_FEED_URL GitHub secret — never in the repo, never in logs.

Safety, same idea as the rest of the pipeline: a feed that fails to download or
comes back implausibly small (< MIN_FEED_ROWS) changes nothing — the previous
lookup is kept and the script exits 0, so the site still builds. A product that
drops out of a good feed loses its image, which is correct: the feed only
lists live, in-stock products.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUT_PATH = DATA_DIR / "cache" / "feed_products.json"

LEADERBOARD_DIR = DATA_DIR / "derived" / "leaderboards"
MONTHLY_DIR = DATA_DIR / "monthly"
THEMES_DIR = DATA_DIR / "derived" / "themes"
PICKS_PATH = DATA_DIR / "picks.json"

# The site renders top 100 (+ ties) on the leaderboards, top 50 (+ ties) on a
# month page, top 20 on the homepage. Keep a margin so ties and next month's
# movement are covered.
LEADERBOARD_DEPTH = 200
MONTH_DEPTH = 200

# The Default feed is ~255k rows. Anything far below that is a truncated
# download or an error page, not a real feed.
MIN_FEED_ROWS = 100_000

LEGACY_IMAGE_HOST = "assets-notonthehighstreet-com.s3.eu-west-1.amazonaws.com"
CURRENT_IMAGE_HOST = "cdn.notonthehighstreet.com"

csv.field_size_limit(10**8)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def product_path(url: str) -> str:
    """'https://www.notonthehighstreet.com/wue/product/x?utm=..' -> 'wue/product/x'"""
    u = (url or "").split("?")[0].split("#")[0].strip()
    if "notonthehighstreet.com/" in u:
        u = u.split("notonthehighstreet.com/", 1)[1]
    return u.strip("/").lower()


def wanted_pick_paths() -> set[str]:
    """Product paths listed in data/picks.json (the homepage 'Featured by
    NOTHS' strip). Those products are looked up by URL, since picks.json holds
    the links from Awin's promo emails, not SKUs."""
    d = _load(PICKS_PATH) or {}
    return {product_path(i.get("url")) for i in d.get("items") or [] if i.get("url")}


def wanted_skus() -> set[str]:
    """Every SKU the site can render a row for."""
    skus: set[str] = set()

    for path in LEADERBOARD_DIR.glob("top_products_*.json"):
        if "archive" in path.name:
            continue
        d = _load(path) or {}
        for item in (d.get("items") or [])[:LEADERBOARD_DEPTH]:
            if item.get("sku"):
                skus.add(str(item["sku"]).strip())

    for path in MONTHLY_DIR.glob("*/top_products.json"):
        d = _load(path) or {}
        items = d.get("items") or d.get("products") or []
        items = sorted(items, key=lambda x: -(x.get("review_count_month") or 0))
        for item in items[:MONTH_DEPTH]:
            if item.get("sku"):
                skus.add(str(item["sku"]).strip())

    for path in THEMES_DIR.glob("*.json"):
        d = _load(path) or {}
        for item in d.get("products") or []:
            if isinstance(item, dict) and item.get("sku"):
                skus.add(str(item["sku"]).strip())

    return skus


def open_feed(feed_path: str | None, url: str | None = None, label: str = "feed"):
    """Return a text stream over the feed CSV, or None."""
    if feed_path:
        p = Path(feed_path)
        if not p.exists():
            print(f"⚠️  feed file not found: {p}")
            return None
        raw = open(p, "rb")
    else:
        url = (url if url is not None else os.environ.get("AWIN_FEED_URL", "")).strip()
        if not url:
            print(f"⚠️  {label}: no file and no URL — keeping existing data")
            return None
        try:
            import requests
        except ImportError:
            print("⚠️  requests not installed — keeping existing lookup")
            return None
        try:
            # Never print the URL: it carries the API key.
            r = requests.get(url, stream=True, timeout=(30, 600))
            if r.status_code != 200:
                print(f"⚠️  {label} download returned HTTP {r.status_code} — keeping existing data")
                return None
            tmp = tempfile.TemporaryFile()
            for chunk in r.iter_content(chunk_size=1 << 20):
                tmp.write(chunk)
            tmp.seek(0)
            raw = tmp
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  {label} download failed ({type(e).__name__}) — keeping existing data")
            return None

    head = raw.read(2)
    raw.seek(0)
    stream = gzip.GzipFile(fileobj=raw) if head == b"\x1f\x8b" else raw
    return io.TextIOWrapper(stream, encoding="utf-8", newline="")


def clean_price(value: str):
    try:
        return round(float(value), 2) if value not in ("", None) else None
    except ValueError:
        return None


def row_to_entry(d: dict):
    """Feed row -> lookup entry, or None if not usable. Returns (entry, legacy_fixed)."""
    if (d.get("in_stock") or "1").strip() not in ("1", "yes", "true", "True"):
        return None, False
    thumb = (d.get("aw_image_url") or "").strip()
    image = (d.get("merchant_image_url") or "").strip()
    if not (thumb or image):
        return None, False
    # ~0.8% of the feed (2,141 of 255k on 1 Nov 2026 — older listings,
    # Wue's Friendship Knot Earrings among them) still carries NOTHS's
    # retired S3 image host. That host is dead, so Awin's resizer serves a
    # 70×70 "no image" placeholder, which is also why those products show no
    # picture in the Awin and NOTHS seller dashboards. The same path is live
    # on NOTHS's CDN. Awin's thumbnail URLs are signed, so the host can't be
    # swapped inside them; use the CDN original instead.
    legacy = LEGACY_IMAGE_HOST in image
    if legacy:
        image = image.replace(LEGACY_IMAGE_HOST, CURRENT_IMAGE_HOST)
        thumb = image
    return {
        "thumb": thumb,
        "image": image,
        "price": clean_price(d.get("search_price")),
        "currency": (d.get("currency") or "GBP").strip(),
        "name": (d.get("product_name") or "").strip(),
        "url": (d.get("merchant_deep_link") or "").strip(),
    }, legacy


# -----------------------------------------------------------------------------
# NOTHS "New, Best Selling & HC Products" feed (datafeed 100570)
# -----------------------------------------------------------------------------
# ~2,100 products NOTHS itself flags as bestsellers. Feeds the homepage
# "NOTHS bestsellers" tab. Its download URL is the main feed's URL with the
# datafeed id swapped, so no second secret is needed (AWIN_BESTSELLERS_URL
# overrides). We keep only the BESTSELLER_KEEP products with the most reviews
# in the last 12 months — NOTHS's list, ordered by our data.
MAIN_FEED_ID = "37219"
BESTSELLERS_FEED_ID = "100570"
BESTSELLER_KEEP = 24
MIN_BESTSELLER_ROWS = 200


def bestsellers_url() -> str:
    explicit = os.environ.get("AWIN_BESTSELLERS_URL", "").strip()
    if explicit:
        return explicit
    main = os.environ.get("AWIN_FEED_URL", "").strip()
    if f"/fid/{MAIN_FEED_ID}/" in main:
        return main.replace(f"/fid/{MAIN_FEED_ID}/", f"/fid/{BESTSELLERS_FEED_ID}/")
    return ""


def twelve_month_reviews() -> dict:
    d = _load(LEADERBOARD_DIR / "top_products_last_12_months.json") or {}
    return {str(i.get("sku")).strip(): (i.get("reviews") or 0) for i in d.get("items") or [] if i.get("sku")}


def build_bestsellers(feed_path: str | None):
    """[(sku, entry), ...] ordered by 12-month reviews, or None to keep the old list."""
    text = open_feed(feed_path, url=None if feed_path else bestsellers_url(), label="bestsellers feed")
    if text is None:
        return None
    reviews = twelve_month_reviews()
    rows = 0
    found = []
    try:
        for d in csv.DictReader(text):
            rows += 1
            sku = (d.get("merchant_product_id") or "").strip()
            if not reviews.get(sku):
                continue
            entry, _ = row_to_entry(d)
            if entry:
                found.append((reviews[sku], sku, entry))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  bestsellers feed could not be parsed ({type(e).__name__}) — keeping existing list")
        return None
    if rows < MIN_BESTSELLER_ROWS:
        print(f"⚠️  bestsellers feed has only {rows:,} rows — keeping existing list")
        return None
    found.sort(key=lambda x: (-x[0], x[1]))
    print(f"🏆 bestsellers feed: {rows:,} products, {len(found):,} with 12-month reviews, keeping top {BESTSELLER_KEEP}")
    return [(sku, entry) for _, sku, entry in found[:BESTSELLER_KEEP]]


def build(feed_path: str | None, bestsellers_path: str | None = None) -> int:
    skus = wanted_skus()
    pick_paths = wanted_pick_paths()
    print(f"🔎 {len(skus):,} SKUs rendered by the site, {len(pick_paths)} featured picks")

    text = open_feed(feed_path)
    if text is None:
        return 0

    products: dict[str, dict] = {}
    rows = 0
    legacy_fixed = 0
    try:
        reader = csv.DictReader(text)
        for d in reader:
            rows += 1
            sku = (d.get("merchant_product_id") or "").strip()
            if sku not in skus and (
                not pick_paths or product_path(d.get("merchant_deep_link")) not in pick_paths
            ):
                continue
            entry, legacy = row_to_entry(d)
            if not entry:
                continue
            legacy_fixed += legacy
            products[sku] = entry
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  feed could not be parsed ({type(e).__name__}) — keeping existing lookup")
        return 0

    if rows < MIN_FEED_ROWS:
        print(f"⚠️  feed has only {rows:,} rows (< {MIN_FEED_ROWS:,}) — looks truncated, keeping existing lookup")
        return 0

    # Bestsellers: a failed or missing download keeps the previous list (and
    # its product entries), so the tab doesn't vanish because of one bad fetch.
    previous = _load(OUT_PATH) or {}
    bestsellers = build_bestsellers(bestsellers_path)
    if bestsellers is None:
        prev_products = previous.get("products") or {}
        bestseller_skus = [s for s in previous.get("bestsellers") or [] if s in prev_products]
        for s in bestseller_skus:
            products.setdefault(s, prev_products[s])
    else:
        bestseller_skus = [s for s, _ in bestsellers]
        for s, entry in bestsellers:
            products.setdefault(s, entry)

    payload = {
        "generated_at": now_iso(),
        "source": "awin:18484:37219",
        "feed_rows": rows,
        "skus_wanted": len(skus),
        "skus_matched": len(products),
        "bestsellers": bestseller_skus,
        "products": dict(sorted(products.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT_PATH)

    print(f"🖼️  {len(products):,} of {len(skus):,} SKUs matched in a {rows:,}-row feed → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    if legacy_fixed:
        print(f"   ↳ {legacy_fixed:,} used NOTHS's retired S3 image host — switched to the CDN original")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--feed", help="path to a downloaded feed (.csv.gz or .csv)")
    ap.add_argument("--bestsellers-feed", help="path to a downloaded bestsellers feed (datafeed 100570)")
    args = ap.parse_args()
    return build(args.feed, args.bestsellers_feed)


if __name__ == "__main__":
    sys.exit(main())
