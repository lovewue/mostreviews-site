"""
Refresh all-time brand stats from NOTHS partner pages.

Every NOTHS partner page carries a small stats strip:

    690K+ ORDERS   |   4.5/5 BRAND RATING   |   16 YEARS ON NOTHS

Those numbers are the only public signal of a brand's *sales* volume on NOTHS
(everything else in this repo is review-derived), so they get their own cache
and their own leaderboard.

Output: data/cache/brand_stats.json

    {
      "generated_at": "...",
      "brand_count": 5551,
      "brands": {
        "<slug>": {
          "slug", "name", "orders_label", "orders", "orders_tier",
          "brand_rating", "years_on_noths", "months_on_noths",
          "tenure_label", "product_count", "active", "http_status",
          "checked_at"
        }
      }
    }

Design notes
------------
* This is deliberately NOT part of Site Build & Publish. It is thousands of
  requests against a site that throttles, on a build that already runs 15+
  minutes; a slow or blocked scrape must not be able to stop the site from
  publishing. It gets its own workflow and commits only the cache.

* Rows are refreshed at most every REFRESH_DAYS days, and at most
  MAX_LOOKUPS per run, so a normal run is cheap and a cold start spreads
  itself over a few runs instead of hammering NOTHS once.

* Sanity gate, same idea as build_leaderboards.py and topup_products_cache.py:
  a scrape cannot tell "this brand is gone" from "NOTHS blocked us", so if more
  than MAX_DEAD_SHARE of the pages we actually fetched come back dead, the run
  is treated as blocked and the cache is left exactly as it was.

* Parsing is done on tag-stripped text, not CSS classes. The partner page is a
  React build whose class names are content-hashed (`sc-e3e8b7fb-3 eVmRJP`),
  so a class selector breaks on the next NOTHS deploy; the words "ORDERS",
  "BRAND RATING" and "YEARS ON NOTHS" do not.

Usage:
    python scripts/refresh_brand_stats.py                 # incremental
    python scripts/refresh_brand_stats.py --full          # ignore checked_at
    python scripts/refresh_brand_stats.py --limit 200     # cap this run
    python scripts/refresh_brand_stats.py --refresh-slugs # re-derive the slug
                                                          # list from the NOTHS
                                                          # sitemap first
"""

import argparse
import csv
import gzip
import io
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
CACHE_FILE = DATA_DIR / "cache" / "brand_stats.json"

SLUGS_CSV = DATA_DIR / "source" / "unique_seller_slugs_latest.csv"

# One-off seed so the first run isn't a cold 5,500-page scrape: the retired
# brand-directory build left a full set of partner stats behind.
LEGACY_BRANDS_JSON = DATA_DIR / "published" / "brands.json"

# Brands that have review activity but were missing from the sitemap snapshot.
BRANDS_LEADERBOARD = DATA_DIR / "derived" / "leaderboards" / "top_brands_last_12_months.json"


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
BASE = "https://www.notonthehighstreet.com"

REFRESH_DAYS = 25          # a row younger than this is left alone
MAX_LOOKUPS = 6000         # hard cap on fetches per run
MAX_WORKERS = 3
JITTER = (0.35, 1.10)      # per-request sleep, per worker

TIMEOUT_CONNECT = 6
TIMEOUT_READ = 20
RETRIES = 2

CHECKPOINT_EVERY = 250

# Over this share of fetched pages coming back dead ⇒ assume we were blocked.
MAX_DEAD_SHARE = 0.5
# Below this many fetches the share is meaningless, so the gate doesn't apply.
MIN_CHECKED_FOR_GATE = 40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendListBot/1.0; +https://trendlist.co.uk/)",
    "Accept-Language": "en-GB,en;q=0.9",
}

ALLOWED_HOSTS = {"www.notonthehighstreet.com", "notonthehighstreet.com"}

_thread_local = threading.local()


def get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(HEADERS)
        _thread_local.session = s
    return _thread_local.session


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -----------------------------------------------------------------------------
# Fetch
# -----------------------------------------------------------------------------
def fetch(url: str, jitter=JITTER):
    """
    Returns (ok, status, text, note).

    Redirects are followed manually and only within NOTHS. A partner slug that
    no longer exists does not 404 — NOTHS 302s it to the homepage — so landing
    anywhere outside /partners/ counts as dead, not as a successful fetch.
    """
    for attempt in range(RETRIES):
        time.sleep(random.uniform(*jitter))
        try:
            r = get_session().get(
                url,
                timeout=(TIMEOUT_CONNECT, TIMEOUT_READ),
                allow_redirects=False,
            )

            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location")
                if not loc:
                    return False, r.status_code, None, "redirect_missing_location"
                nxt = urljoin(url, loc)
                host = urlparse(nxt).netloc.lower()
                if host and host not in ALLOWED_HOSTS:
                    return False, r.status_code, None, f"redirect_offsite:{host}"
                if "/partners/" not in urlparse(nxt).path:
                    return False, r.status_code, None, "redirect_away_from_partner"
                url = nxt
                continue

            if r.status_code == 200:
                return True, 200, r.text, ""

            return False, r.status_code, None, f"http_{r.status_code}"

        except requests.exceptions.ConnectTimeout:
            if attempt == 0:
                continue
            return False, 0, None, "connect_timeout"
        except Exception as e:  # noqa: BLE001 - any transport failure is "unknown"
            return False, 0, None, f"error:{type(e).__name__}"

    return False, 0, None, "exhausted_retries"


# -----------------------------------------------------------------------------
# Parsing
# -----------------------------------------------------------------------------
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_ORDERS_RE = re.compile(r"([0-9][0-9.,]*\s*[KMB]?)\s*\+?\s*ORDERS\b")
_RATING_RE = re.compile(r"([0-5](?:\.[0-9])?)\s*/\s*5\s*BRAND RATING\b")
_YEARS_RE = re.compile(r"([0-9]+)\s*YEARS?\s+ON\s+NOTHS\b")
_MONTHS_RE = re.compile(r"([0-9]+)\s*MONTHS?\s+ON\s+NOTHS\b")
_PRODUCTS_RE = re.compile(r"SHOWING\s+([0-9,]+)\s+PRODUCTS?\b")
_H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def strip_tags(html: str) -> str:
    text = _SCRIPT_RE.sub(" ", html or "")
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return _WS_RE.sub(" ", text).strip()


def parse_order_volume(label: str) -> int:
    """'690K+' -> 690000. Unparseable -> 0."""
    if not label:
        return 0
    s = label.strip().upper().replace("+", "").replace(",", "").replace(" ", "")
    mult = 1
    if s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("B"):
        mult, s = 1_000_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except Exception:
        return 0


def order_volume_tier(n: int) -> str:
    for threshold, label in (
        (5_000_000, "5M+"),
        (2_000_000, "2M+"),
        (1_000_000, "1M+"),
        (500_000, "500K+"),
        (250_000, "250K+"),
        (100_000, "100K+"),
        (50_000, "50K+"),
        (10_000, "10K+"),
        (1_000, "1K+"),
        (100, "100+"),
        (10, "10+"),
    ):
        if n >= threshold:
            return label
    return "<10"


def parse_partner_page(html: str) -> dict:
    text = strip_tags(html)
    upper = text.upper()

    name = ""
    m_h1 = _H1_RE.search(html or "")
    if m_h1:
        name = strip_tags(m_h1.group(1))

    orders_label = ""
    m = _ORDERS_RE.search(upper)
    if m:
        orders_label = _WS_RE.sub("", m.group(1)).upper() + "+"

    orders = parse_order_volume(orders_label)

    brand_rating = 0.0
    m = _RATING_RE.search(upper)
    if m:
        try:
            brand_rating = float(m.group(1))
        except ValueError:
            brand_rating = 0.0

    years = 0
    months = 0
    tenure_label = ""
    m = _YEARS_RE.search(upper)
    if m:
        years = int(m.group(1))
        months = years * 12
        tenure_label = "1 year" if years == 1 else f"{years} years"
    else:
        m = _MONTHS_RE.search(upper)
        if m:
            months = int(m.group(1))
            tenure_label = "1 month" if months == 1 else f"{months} months"

    product_count = 0
    m = _PRODUCTS_RE.search(upper)
    if m:
        product_count = int(m.group(1).replace(",", ""))

    return {
        "name": name,
        "orders_label": orders_label,
        "orders": orders,
        "orders_tier": order_volume_tier(orders),
        "brand_rating": brand_rating,
        "years_on_noths": years,
        "months_on_noths": months,
        "tenure_label": tenure_label,
        "product_count": product_count,
    }


# -----------------------------------------------------------------------------
# Slug sources
# -----------------------------------------------------------------------------
_PRODUCT_SLUG_RE = re.compile(r"https?://[^/]+/([^/\s]+)/product/")
_SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


def load_slugs_csv() -> set:
    if not SLUGS_CSV.exists():
        return set()
    slugs = set()
    with open(SLUGS_CSV, "r", encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            value = (row[0] or "").strip().lower()
            if value and value != "slug":
                slugs.add(value)
    return slugs


def load_leaderboard_slugs() -> set:
    if not BRANDS_LEADERBOARD.exists():
        return set()
    try:
        data = json.loads(BRANDS_LEADERBOARD.read_text(encoding="utf-8"))
    except Exception:
        return set()
    slugs = set()
    for item in data.get("items", []) or []:
        slug = str(item.get("seller_slug") or "").strip().lower()
        if slug:
            slugs.add(slug)
    return slugs


def refresh_slugs_from_sitemap() -> set:
    """
    Re-derive the partner slug list from the NOTHS product sitemaps.

    NOTHS publishes no partner sitemap, so slugs come out of the product URLs
    (/{slug}/product/{name}). The sitemap index is discovered from robots.txt
    rather than hardcoded, because the index filename has moved before.

    Best effort: any failure returns an empty set and the caller falls back to
    the committed slug list.
    """
    found = set()
    try:
        r = requests.get(f"{BASE}/robots.txt", headers=HEADERS, timeout=(6, 20))
        r.raise_for_status()
        indexes = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  slug refresh: could not read robots.txt ({type(e).__name__})")
        return found

    if not indexes:
        print("⚠️  slug refresh: robots.txt named no sitemap")
        return found

    sitemaps = []
    for index_url in indexes:
        try:
            body = _get_maybe_gzip(index_url)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  slug refresh: {index_url} failed ({type(e).__name__})")
            continue
        for loc in _SITEMAP_LOC_RE.findall(body):
            if "product-details-page" in loc:
                sitemaps.append(loc)

    if not sitemaps:
        print("⚠️  slug refresh: no product sitemaps found in the index")
        return found

    print(f"   slug refresh: {len(sitemaps)} product sitemaps")
    for sm in sitemaps:
        try:
            body = _get_maybe_gzip(sm)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  slug refresh: {sm} failed ({type(e).__name__})")
            continue
        for loc in _SITEMAP_LOC_RE.findall(body):
            m = _PRODUCT_SLUG_RE.match(loc)
            if m:
                found.add(m.group(1).strip().lower())

    print(f"   slug refresh: {len(found):,} partner slugs from sitemap")
    return found


def _get_maybe_gzip(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=(6, 60))
    r.raise_for_status()
    raw = r.content
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return raw.decode("utf-8", errors="replace")


# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------
def blank_row(slug: str) -> dict:
    return {
        "slug": slug,
        "name": "",
        "orders_label": "",
        "orders": 0,
        "orders_tier": "",
        "brand_rating": 0.0,
        "years_on_noths": 0,
        "months_on_noths": 0,
        "tenure_label": "",
        "product_count": 0,
        "active": False,
        "http_status": 0,
        "checked_at": "",
    }


def seed_from_legacy_brands() -> dict:
    """
    First run only: lift what the retired brand-directory build already
    scraped, so the leaderboard has real data before the first full sweep
    finishes. Rows carry no checked_at, so every one is due for a refresh.
    """
    if not LEGACY_BRANDS_JSON.exists():
        return {}

    try:
        records = json.loads(LEGACY_BRANDS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}

    brands = {}
    for rec in records or []:
        slug = str(rec.get("slug") or "").strip().lower()
        if not slug:
            continue
        stats = rec.get("stats") or {}
        row = blank_row(slug)
        row["name"] = str(rec.get("name") or "").strip() or slug
        row["orders_label"] = str(stats.get("order_volume_label") or "").strip()
        row["orders"] = int(stats.get("order_volume_numeric") or 0)
        row["orders_tier"] = str(stats.get("order_volume_tier") or "").strip()
        row["years_on_noths"] = int(stats.get("years_on_noths") or 0)
        row["months_on_noths"] = int(stats.get("months_on_noths") or 0)
        row["tenure_label"] = str(stats.get("tenure_label") or "").strip()
        row["product_count"] = int(stats.get("product_count") or 0)
        row["active"] = bool(rec.get("active"))
        brands[slug] = row

    print(f"🌱 seeded {len(brands):,} brands from {LEGACY_BRANDS_JSON.name}")
    return brands


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            return data.get("brands", {}) or {}
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  cache unreadable ({type(e).__name__}); starting fresh")
            return {}
    return seed_from_legacy_brands()


def save_cache(brands: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now_iso(),
        "brand_count": len(brands),
        "brands_with_orders": sum(1 for r in brands.values() if (r.get("orders") or 0) > 0),
        "brands": dict(sorted(brands.items())),
    }
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def is_due(row: dict, refresh_days: int) -> bool:
    checked = (row.get("checked_at") or "").strip()
    if not checked:
        return True
    try:
        when = datetime.fromisoformat(checked)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when < datetime.now(timezone.utc) - timedelta(days=refresh_days)


# -----------------------------------------------------------------------------
# Worker
# -----------------------------------------------------------------------------
def check_brand(slug: str, row: dict):
    ok, status, html, note = fetch(f"{BASE}/partners/{slug}/products")

    updated = dict(row)
    updated["http_status"] = status
    updated["checked_at"] = now_iso()

    if not (ok and html):
        updated["active"] = False
        updated["_dead"] = True
        updated["_note"] = note
        return slug, updated

    parsed = parse_partner_page(html)

    # A page that renders but carries no stats strip at all is more likely a
    # layout change or an interstitial than a real brand with no history, so
    # don't let it wipe good values.
    got_anything = bool(parsed["orders_label"] or parsed["years_on_noths"] or parsed["months_on_noths"])
    if not got_anything:
        updated["_dead"] = True
        updated["_note"] = "no_stats_on_page"
        return slug, updated

    if parsed["name"]:
        updated["name"] = parsed["name"]
    elif not updated.get("name"):
        updated["name"] = slug

    for key in (
        "orders_label",
        "orders",
        "orders_tier",
        "brand_rating",
        "years_on_noths",
        "months_on_noths",
        "tenure_label",
        "product_count",
    ):
        updated[key] = parsed[key]

    updated["active"] = True
    updated["_dead"] = False
    updated["_note"] = ""
    return slug, updated


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true", help="refresh every brand, ignoring checked_at")
    ap.add_argument("--limit", type=int, default=MAX_LOOKUPS, help="max partner pages to fetch this run")
    ap.add_argument("--refresh-days", type=int, default=REFRESH_DAYS)
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--refresh-slugs", action="store_true", help="re-derive slugs from the NOTHS sitemap first")
    args = ap.parse_args()

    brands = load_cache()

    slugs = set(brands.keys()) | load_slugs_csv() | load_leaderboard_slugs()

    if args.refresh_slugs:
        sitemap_slugs = refresh_slugs_from_sitemap()
        if sitemap_slugs:
            new = sitemap_slugs - slugs
            slugs |= sitemap_slugs
            print(f"   slug refresh: {len(new):,} brands not seen before")

    for slug in slugs:
        if slug not in brands:
            brands[slug] = blank_row(slug)

    print(f"📇 {len(brands):,} brands known")

    due = [s for s in sorted(brands) if args.full or is_due(brands[s], args.refresh_days)]
    if args.limit and len(due) > args.limit:
        # Oldest first, so a cold start works through the backlog in order
        # instead of re-checking the same alphabetical slice every run.
        due.sort(key=lambda s: (brands[s].get("checked_at") or "", s))
        due = due[: args.limit]

    if not due:
        print("✅ nothing due; cache left unchanged")
        return 0

    print(f"🔎 {len(due):,} due (workers={args.workers})")

    results = {}
    dead = 0
    checked = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(check_brand, s, brands[s]): s for s in due}
        for i, fut in enumerate(as_completed(futures), start=1):
            slug = futures[fut]
            try:
                s, updated = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"   ! {slug}: {type(e).__name__}")
                continue

            checked += 1
            if updated.pop("_dead", False):
                dead += 1
            updated.pop("_note", None)
            results[s] = updated

            if i % CHECKPOINT_EVERY == 0:
                print(f"   [{i:,}/{len(due):,}] {dead:,} dead so far")

    if checked == 0:
        print("⚠️  nothing fetched; cache left unchanged")
        return 0

    dead_share = dead / checked
    print(f"   fetched {checked:,}, dead {dead:,} ({dead_share:.1%})")

    if checked >= MIN_CHECKED_FOR_GATE and dead_share > MAX_DEAD_SHARE:
        print(
            f"🛑 {dead_share:.1%} of fetched pages came back dead, over the "
            f"{MAX_DEAD_SHARE:.0%} gate. Treating this as blocked rather than "
            f"real, and leaving the cache unchanged."
        )
        return 1

    brands.update(results)
    save_cache(brands)

    with_orders = sum(1 for r in brands.values() if (r.get("orders") or 0) > 0)
    print(f"✅ {CACHE_FILE.relative_to(PROJECT_ROOT)} — {len(brands):,} brands, {with_orders:,} with orders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
