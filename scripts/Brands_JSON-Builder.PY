"""
NOTHS Brands Builder (CSV-first, resumable)

Outputs:
- data/working/brands_working.csv
- data/published/brands.csv
- data/published/brands.json
- data/archive/brands/brands_YYYY-MM-DD_HH-MM.csv
- data/archive/brands/brands_YYYY-MM-DD_HH-MM.json

Inputs:
- data/source/unique_seller_slugs_latest.csv
- data/source/all_product_urls.csv
- data/source/partners.json   (optional)

Notes:
- Pass A: /partners/{slug}/products => product_count, orders label, tenure
- Pass B: sample product URL => brand_review_count + location
          location fallback => partner page Returns address
- Loop-safe: stops retrying reviews/location after a few blanks.
"""

import re
import csv
import json
import time
import random
import shutil
import datetime
import threading
from pathlib import Path
from urllib.parse import urlparse, urljoin, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from bs4 import BeautifulSoup

# =========================
# CONFIG
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

SOURCE_DIR = PROJECT_ROOT / "data" / "source"
WORKING_DIR = PROJECT_ROOT / "data" / "working"
PUBLISHED_DIR = PROJECT_ROOT / "data" / "published"
ARCHIVE_DIR = PROJECT_ROOT / "data" / "archive" / "brands"

UNIQUE_SLUGS_CSV = SOURCE_DIR / "unique_seller_slugs_latest.csv"
ALL_PRODUCTS_CSV = SOURCE_DIR / "data" / "source" / "all_product_urls.csv"
LEGACY_PARTNERS_JSON = SOURCE_DIR / "partners.json"  # optional

WORKING_CSV = WORKING_DIR / "brands_working.csv"
PUBLISHED_CSV = PUBLISHED_DIR / "brands.csv"
PUBLISHED_JSON = PUBLISHED_DIR / "brands.json"

BASE = "https://www.notonthehighstreet.com"

RUN_MODE = "passB"   # "passA" | "passB" | "update"
PASSA_LIMIT = None    # None = all
PASSB_LIMIT = None    # None = all (not recommended)

MAX_WORKERS_PASSA = 2
MAX_WORKERS_PASSB = 1

JITTER_PASSA = (0.35, 1.1)
JITTER_PASSB = (1.5, 4.0)

TIMEOUT_CONNECT = 6
TIMEOUT_READ = 18
RETRIES = 2

CHECKPOINT_EVERY = 25

MAX_REVIEWS_BLANK = 3
MAX_LOCATION_BLANK = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendListBot/1.0; +https://trendlist.co.uk/)",
    "Accept-Language": "en-GB,en;q=0.9",
}

ALLOWED_HOSTS = {"www.notonthehighstreet.com", "notonthehighstreet.com"}

# =========================
# HTTP session per thread
# =========================
_thread_local = threading.local()

def get_session():
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(HEADERS)
        _thread_local.session = s
    return _thread_local.session

def normalize(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("http://"):
        url = "https://" + url[7:]
    if url.startswith("https://notonthehighstreet.com/"):
        url = "https://www.notonthehighstreet.com/" + url.split("notonthehighstreet.com/", 1)[1]
    return url

def today_date():
    return datetime.date.today().strftime("%Y-%m-%d")

def archive_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")

def fetch(url: str, jitter):
    """
    Returns: (ok, status, html, note, final_url)
    """
    url = normalize(url)

    for attempt in range(RETRIES):
        time.sleep(random.uniform(*jitter))
        try:
            r = get_session().get(
                url,
                timeout=(TIMEOUT_CONNECT, TIMEOUT_READ),
                allow_redirects=False
            )

            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location")
                if not loc:
                    return False, r.status_code, None, "redirect_missing_location", url
                next_url = normalize(urljoin(url, loc))
                host = urlparse(next_url).netloc.lower()
                if host in ALLOWED_HOSTS:
                    url = next_url
                    continue
                return False, 0, None, f"redirect_disallowed_host:{host}", url

            if r.status_code == 200:
                return True, 200, r.text, "", url

            if r.status_code in (403, 404, 429):
                return False, r.status_code, None, f"http_{r.status_code}", url

            return False, r.status_code, None, f"http_{r.status_code}", url

        except requests.exceptions.ConnectTimeout:
            if attempt == 0:
                continue
            return False, 0, None, "connect_timeout", url
        except Exception as e:
            return False, 0, None, f"error:{type(e).__name__}", url

    return False, 0, None, "exhausted_retries", url

# =========================
# Parsing helpers
# =========================
slug_from_url_re = re.compile(r"^https?://[^/]+/([^/]+)/product/")
location_gb_re = re.compile(r"\b([A-Za-z0-9 .'\-]+,\s*GB)\b")
returns_h2_re = re.compile(r"^\s*Returns\s*$", re.IGNORECASE)

def extract_slug_from_url(url: str):
    m = slug_from_url_re.match((url or "").strip())
    return m.group(1).lower() if m else None

def parse_order_volume(label: str) -> int:
    if not label:
        return 0
    s = label.strip().upper().replace("+", "").replace(",", "")
    mult = 1
    if s.endswith("K"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1_000_000
        s = s[:-1]
    elif s.endswith("B"):
        mult = 1_000_000_000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except:
        return 0

def order_volume_tier(n: int) -> str:
    if n >= 5_000_000: return "5M+"
    if n >= 2_000_000: return "2M+"
    if n >= 1_000_000: return "1M+"
    if n >= 500_000:   return "500K+"
    if n >= 250_000:   return "250K+"
    if n >= 100_000:   return "100K+"
    if n >= 50_000:    return "50K+"
    if n >= 10_000:    return "10K+"
    if n >= 1_000:     return "1K+"
    if n >= 100:       return "100+"
    if n >= 10:        return "10+"
    return "<10"

def scrape_orders_label_from_products_page(soup: BeautifulSoup) -> str:
    for li in soup.find_all("li"):
        li_txt = li.get_text(" ", strip=True).upper()
        if "ORDERS" in li_txt:
            b = li.find("b")
            if b:
                return b.get_text(strip=True).upper()
            m = re.search(r"([0-9]+(?:\.[0-9]+)?[KMB]?\+?)", li_txt)
            return m.group(1).upper() if m else ""
    return ""

def scrape_products_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    txt = soup.get_text(" ", strip=True).upper()

    h1 = soup.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else ""

    prod_match = re.search(r"SHOWING\s+(\d+)\s+PRODUCTS?", txt)
    product_count = int(prod_match.group(1)) if prod_match else 0

    orders_label = scrape_orders_label_from_products_page(soup)
    orders_num = parse_order_volume(orders_label)
    tier = order_volume_tier(orders_num)

    years = 0
    months = 0
    tenure_label = ""

    m_years = re.search(r"(\d+)\s*YEAR(?:S)?\s+ON\s+NOTHS", txt)
    if m_years:
        years = int(m_years.group(1))
        months = years * 12
        tenure_label = "1 year" if years == 1 else f"{years} years"
    else:
        m_months = re.search(r"(\d+)\s*MONTH(?:S)?\s+ON\s+NOTHS", txt)
        if m_months:
            months = int(m_months.group(1))
            years = 0
            tenure_label = "1 month" if months == 1 else f"{months} months"

    return name, product_count, orders_label, orders_num, tier, years, months, tenure_label

def extract_brand_reviews_count(soup: BeautifulSoup) -> int:
    li = soup.find("li", attrs={"data-testid": re.compile(r"PartnerMiniModule-.*brand-rating", re.IGNORECASE)})
    if li:
        t = li.get_text(" ", strip=True)
        m = re.search(r"\(([\d,]+)\s*(?:Brand\s+)?reviews?\)", t, re.IGNORECASE)
        if m:
            return int(m.group(1).replace(",", ""))

    full_txt = soup.get_text(" ", strip=True)
    m = re.search(r"\(([\d,]+)\s*(?:Brand\s+)?reviews?\)", full_txt, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))

    m = re.search(r"([\d,]+)\s*(?:Brand\s+)?reviews?\b", full_txt, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))

    return 0

def extract_location_from_product_soup(soup: BeautifulSoup) -> str:
    for li in soup.find_all("li"):
        if li.find(string=re.compile(r"\bFrom\b", re.IGNORECASE)):
            strong = li.find("strong")
            if strong:
                v = strong.get_text(" ", strip=True)
                m = location_gb_re.search(v or "")
                if m:
                    return m.group(1).strip()
            t = li.get_text(" ", strip=True)
            m = location_gb_re.search(t)
            if m:
                return m.group(1).strip()

    for li in soup.find_all("li"):
        t = li.get_text(" ", strip=True)
        m = location_gb_re.search(t)
        if m:
            return m.group(1).strip()

    return ""

def page_has_brand_reviews_text(html: str) -> bool:
    t = (html or "").lower()
    return ("brand reviews" in t) or ("brand review" in t)

def scrape_product_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    loc = extract_location_from_product_soup(soup)
    reviews = extract_brand_reviews_count(soup)
    return loc, reviews

def location_from_returns_address(addr: str) -> str:
    if not addr:
        return ""
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) >= 2:
        country = parts[-1]
        town = parts[-3] if len(parts) >= 3 else parts[-2]
        if re.search(r"\b[A-Z]{1,2}\d", town, re.IGNORECASE) and len(parts) >= 4:
            town = parts[-4]
        return f"{town}, {country}"
    return parts[0].strip()

def scrape_location_from_partner_page(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for h in soup.find_all(["h2", "h3"]):
        if returns_h2_re.match(h.get_text(" ", strip=True) or ""):
            p = h.find_next("p")
            if p:
                full_addr = p.get_text(" ", strip=True)
                return location_from_returns_address(full_addr), full_addr
    return "", ""

# =========================
# Load slug + sample URL maps
# =========================
def load_master_slugs_and_product_map():
    slugs_df = pd.read_csv(UNIQUE_SLUGS_CSV)
    slug_col = slugs_df.columns[0]
    sitemap_slugs = sorted(set(slugs_df[slug_col].dropna().astype(str).str.strip().str.lower().tolist()))

    prod_map = {}
    if ALL_PRODUCTS_CSV.exists():
        df = pd.read_csv(ALL_PRODUCTS_CSV)
        col = "URL" if "URL" in df.columns else df.columns[0]
        for url in df[col].dropna().astype(str):
            slug = extract_slug_from_url(url)
            if slug and slug not in prod_map:
                prod_map[slug] = url.strip()

    legacy_slugs = []
    if LEGACY_PARTNERS_JSON.exists():
        try:
            with open(LEGACY_PARTNERS_JSON, "r", encoding="utf-8") as f:
                legacy = json.load(f)
            if isinstance(legacy, list):
                for p in legacy:
                    s = str(p.get("slug", "")).strip().lower()
                    if s:
                        legacy_slugs.append(s)
        except Exception:
            pass

    master = sorted(set(sitemap_slugs) | set(prod_map.keys()) | set(legacy_slugs))
    return master, prod_map

# =========================
# CSV store (resumable)
# =========================
CSV_COLUMNS = [
    "slug",
    "name",
    "active",
    "product_count",
    "order_volume_label",
    "order_volume_numeric",
    "order_volume_tier",
    "years_on_noths",
    "months_on_noths",
    "tenure_label",
    "brand_review_count",
    "brand_reviews_available",
    "location",
    "returns_address_full",
    "sample_product_url",
    "passA_status",
    "passB_status",
    "reviews_blank_count",
    "location_blank_count",
    "fail_count",
    "last_error",
    "last_updated",
]

def new_row(slug: str, sample_url: str):
    return {
        "slug": slug,
        "name": slug,
        "active": False,
        "product_count": 0,
        "order_volume_label": "",
        "order_volume_numeric": 0,
        "order_volume_tier": "",
        "years_on_noths": 0,
        "months_on_noths": 0,
        "tenure_label": "",
        "brand_review_count": 0,
        "brand_reviews_available": True,
        "location": "",
        "returns_address_full": "",
        "sample_product_url": sample_url or "",
        "passA_status": 0,
        "passB_status": 0,
        "reviews_blank_count": 0,
        "location_blank_count": 0,
        "fail_count": 0,
        "last_error": "",
        "last_updated": today_date(),
    }

def load_working_csv() -> dict:
    if not WORKING_CSV.exists():
        return {}
    df = pd.read_csv(WORKING_CSV, dtype=str).fillna("")
    rows = {}
    for _, r in df.iterrows():
        slug = (r.get("slug") or "").strip().lower()
        if not slug:
            continue
        row = {c: (r.get(c, "") if c in r else "") for c in CSV_COLUMNS}
        rows[slug] = row
    return rows

def coerce_types(row: dict) -> dict:
    def to_int(v):
        try:
            return int(str(v).strip() or "0")
        except:
            return 0

    def to_bool(v):
        s = str(v).strip().lower()
        return s in ("true", "1", "yes", "y")

    row["active"] = to_bool(row.get("active", False))
    row["product_count"] = to_int(row.get("product_count", 0))
    row["order_volume_numeric"] = to_int(row.get("order_volume_numeric", 0))
    row["years_on_noths"] = to_int(row.get("years_on_noths", 0))
    row["months_on_noths"] = to_int(row.get("months_on_noths", 0))
    row["brand_review_count"] = to_int(row.get("brand_review_count", 0))
    row["passA_status"] = to_int(row.get("passA_status", 0))
    row["passB_status"] = to_int(row.get("passB_status", 0))
    row["reviews_blank_count"] = to_int(row.get("reviews_blank_count", 0))
    row["location_blank_count"] = to_int(row.get("location_blank_count", 0))
    row["fail_count"] = to_int(row.get("fail_count", 0))
    row["brand_reviews_available"] = to_bool(row.get("brand_reviews_available", True))
    row["last_updated"] = row.get("last_updated") or today_date()
    return row

def write_working(rows: dict):
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    tmp = WORKING_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for slug in sorted(rows.keys()):
            r = rows[slug]
            out = {}
            for c in CSV_COLUMNS:
                out[c] = r.get(c, "")
            years = int(out.get("years_on_noths", 0) or 0)
            if years != 0:
                out["months_on_noths"] = ""
            w.writerow(out)
    tmp.replace(WORKING_CSV)

# =========================
# JSON publisher
# =========================
def clean_str(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s

def to_int(v):
    try:
        return int(float(str(v).strip() or "0"))
    except:
        return 0

def to_bool(v):
    return str(v).strip().lower() in ("true", "1", "yes", "y")

def build_affiliate_url(brand_url: str, clickref: str = "TrendList") -> str:
    encoded_destination = quote(brand_url, safe="")
    return (
        "https://www.awin1.com/cread.php?"
        f"awinmid=18484&awinaffid=1018637&clickref={clickref}&ued={encoded_destination}"
    )

def build_published_json_from_df(df: pd.DataFrame):
    records = []

    for _, r in df.iterrows():
        slug = clean_str(r.get("slug", "")).lower()
        if not slug:
            continue

        name = clean_str(r.get("name", "")) or slug
        brand_url = f"{BASE}/partners/{slug}"
        products_url = f"{BASE}/partners/{slug}/products"

        years_on_noths = to_int(r.get("years_on_noths", 0))
        months_on_noths = to_int(r.get("months_on_noths", 0))

        record = {
            "slug": slug,
            "canonical_slug": slug,
            "aliases": [],
            "name": name,
            "active": to_bool(r.get("active", False)),
            "urls": {
                "brand": brand_url,
                "products": products_url,
                "affiliate": build_affiliate_url(brand_url, clickref="TrendList"),
            },
            "stats": {
                "product_count": to_int(r.get("product_count", 0)),
                "brand_review_count": to_int(r.get("brand_review_count", 0)),
                "brand_reviews_available": to_bool(r.get("brand_reviews_available", True)),
                "order_volume_label": clean_str(r.get("order_volume_label", "")),
                "order_volume_numeric": to_int(r.get("order_volume_numeric", 0)),
                "order_volume_tier": clean_str(r.get("order_volume_tier", "")),
                "years_on_noths": years_on_noths,
                "months_on_noths": months_on_noths,
                "tenure_label": clean_str(r.get("tenure_label", "")),
            },
            "location": {
                "display": clean_str(r.get("location", "")),
            },
            "meta": {
                "returns_address_full": clean_str(r.get("returns_address_full", "")),
            }
        }

        records.append(record)

    return records

# =========================
# Archive helpers
# =========================
def archive_existing_published_files():
    stamp = archive_stamp()

    if PUBLISHED_CSV.exists():
        archive_csv = ARCHIVE_DIR / f"brands_{stamp}.csv"
        shutil.copy2(PUBLISHED_CSV, archive_csv)
        print(f"🗄 Archived previous CSV → {archive_csv}")

    if PUBLISHED_JSON.exists():
        archive_json = ARCHIVE_DIR / f"brands_{stamp}.json"
        shutil.copy2(PUBLISHED_JSON, archive_json)
        print(f"🗄 Archived previous JSON → {archive_json}")

# =========================
# Pass A / Pass B processors
# =========================
def do_passA(slug: str, row: dict):
    ok, status, html, note, final_url = fetch(f"{BASE}/partners/{slug}/products", JITTER_PASSA)
    row["passA_status"] = status
    row["last_updated"] = today_date()

    if ok and html:
        name, product_count, orders_label, orders_num, tier, years, months, tenure_label = scrape_products_page(html)
        if name:
            row["name"] = name
        row["active"] = True
        row["product_count"] = product_count
        row["order_volume_label"] = orders_label
        row["order_volume_numeric"] = orders_num
        row["order_volume_tier"] = tier
        row["years_on_noths"] = years
        row["months_on_noths"] = months
        row["tenure_label"] = tenure_label
        row["last_error"] = ""
    else:
        row["fail_count"] = int(row.get("fail_count", 0) or 0) + 1
        row["last_error"] = note or f"passA_failed_{status}"

    return slug, row

def do_passB(slug: str, row: dict):
    row["last_updated"] = today_date()

    if int(row.get("product_count", 0) or 0) == 0:
        return slug, row
    if not bool(row.get("brand_reviews_available", True)):
        return slug, row

    sample = (row.get("sample_product_url") or "").strip()
    if not sample:
        row["reviews_blank_count"] = min(MAX_REVIEWS_BLANK, int(row.get("reviews_blank_count", 0) or 0) + 1)
        row["location_blank_count"] = min(MAX_LOCATION_BLANK, int(row.get("location_blank_count", 0) or 0) + 1)
        row["last_error"] = row.get("last_error") or "no_sample_product_url"
        return slug, row

    ok, status, html, note, final_url = fetch(sample, JITTER_PASSB)
    row["passB_status"] = status

    if ok and html:
        loc, reviews = scrape_product_page(html)

        if reviews:
            row["brand_review_count"] = reviews
            row["brand_reviews_available"] = True
            row["reviews_blank_count"] = 0
        else:
            if not page_has_brand_reviews_text(html):
                row["reviews_blank_count"] = int(row.get("reviews_blank_count", 0) or 0) + 1
                if row["reviews_blank_count"] >= 2:
                    row["brand_reviews_available"] = False
                    row["reviews_blank_count"] = MAX_REVIEWS_BLANK
            else:
                row["reviews_blank_count"] = int(row.get("reviews_blank_count", 0) or 0) + 1
                if row["reviews_blank_count"] >= MAX_REVIEWS_BLANK:
                    row["brand_reviews_available"] = False

        if loc:
            row["location"] = loc
            row["location_blank_count"] = 0
        else:
            ok2, status2, html2, note2, _ = fetch(f"{BASE}/partners/{slug}", JITTER_PASSB)
            if ok2 and html2:
                loc2, full_addr = scrape_location_from_partner_page(html2)
                if loc2:
                    row["location"] = loc2
                    row["returns_address_full"] = full_addr
                    row["location_blank_count"] = 0
                else:
                    row["location_blank_count"] = int(row.get("location_blank_count", 0) or 0) + 1
            else:
                row["location_blank_count"] = int(row.get("location_blank_count", 0) or 0) + 1

        row["last_error"] = ""
    else:
        row["fail_count"] = int(row.get("fail_count", 0) or 0) + 1
        row["last_error"] = row.get("last_error") or note or f"passB_failed_{status}"
        row["reviews_blank_count"] = min(MAX_REVIEWS_BLANK, int(row.get("reviews_blank_count", 0) or 0) + 1)
        row["location_blank_count"] = min(MAX_LOCATION_BLANK, int(row.get("location_blank_count", 0) or 0) + 1)

    return slug, row

def row_needs_passB(row: dict) -> bool:
    if int(row.get("product_count", 0) or 0) == 0:
        return False

    reviews_needed = (
        bool(row.get("brand_reviews_available", True)) and
        int(row.get("brand_review_count", 0) or 0) == 0 and
        int(row.get("reviews_blank_count", 0) or 0) < MAX_REVIEWS_BLANK
    )

    location_needed = (
        (row.get("location", "") or "").strip() == "" and
        int(row.get("location_blank_count", 0) or 0) < MAX_LOCATION_BLANK
    )

    return reviews_needed or location_needed

# =========================
# Main
# =========================
def main():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)

    master_slugs, prod_map = load_master_slugs_and_product_map()
    rows = load_working_csv()

    for slug in master_slugs:
        slug = slug.strip().lower()
        if slug not in rows:
            rows[slug] = new_row(slug, prod_map.get(slug, ""))
        else:
            rows[slug] = coerce_types(rows[slug])
            if prod_map.get(slug) and not (rows[slug].get("sample_product_url") or "").strip():
                rows[slug]["sample_product_url"] = prod_map[slug]

    if RUN_MODE in ("passA", "update"):
        slugs = list(rows.keys())
        slugs.sort()
        if PASSA_LIMIT is not None:
            slugs = slugs[: int(PASSA_LIMIT)]

        print(f"passA → {len(slugs)} to process (workers={MAX_WORKERS_PASSA})")
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_PASSA) as ex:
            futures = {ex.submit(do_passA, slug, rows[slug]): slug for slug in slugs}
            for i, fut in enumerate(as_completed(futures), start=1):
                slug = futures[fut]
                try:
                    s, updated = fut.result()
                    rows[s] = updated
                except Exception as e:
                    rows[slug]["fail_count"] = int(rows[slug].get("fail_count", 0) or 0) + 1
                    rows[slug]["last_error"] = f"passA_exception:{type(e).__name__}"
                done += 1
                if done % CHECKPOINT_EVERY == 0:
                    write_working(rows)
                    print(f"[{i}/{len(slugs)}] ✅ checkpoint")
                else:
                    print(f"[{i}/{len(slugs)}] {slug}")

    if RUN_MODE in ("passB", "update"):
        candidates = [s for s, r in rows.items() if row_needs_passB(r)]
        candidates.sort(key=lambda s: -int(rows[s].get("order_volume_numeric", 0) or 0))
        if PASSB_LIMIT is not None:
            candidates = candidates[: int(PASSB_LIMIT)]

        print(f"passB → {len(candidates)} to process (workers={MAX_WORKERS_PASSB})")
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_PASSB) as ex:
            futures = {ex.submit(do_passB, slug, rows[slug]): slug for slug in candidates}
            for i, fut in enumerate(as_completed(futures), start=1):
                slug = futures[fut]
                try:
                    s, updated = fut.result()
                    rows[s] = updated
                except Exception as e:
                    rows[slug]["fail_count"] = int(rows[slug].get("fail_count", 0) or 0) + 1
                    rows[slug]["last_error"] = f"passB_exception:{type(e).__name__}"
                done += 1
                if done % CHECKPOINT_EVERY == 0:
                    write_working(rows)
                    print(f"[{i}/{len(candidates)}] ✅ checkpoint")
                else:
                    print(f"[{i}/{len(candidates)}] {slug}")

    write_working(rows)

    df = pd.read_csv(WORKING_CSV, dtype=str).fillna("")
    df["active_sort"] = df["active"].astype(str).str.lower().isin(["true", "1", "yes", "y"]).astype(int)
    df["order_volume_numeric_sort"] = pd.to_numeric(df["order_volume_numeric"], errors="coerce").fillna(0).astype(int)
    df = df.sort_values(by=["active_sort", "order_volume_numeric_sort", "name"], ascending=[False, False, True])
    df = df.drop(columns=["active_sort", "order_volume_numeric_sort"], errors="ignore")

    published_json = build_published_json_from_df(df)

    # Archive current live files BEFORE overwrite
    archive_existing_published_files()

    # Save new published CSV
    df.to_csv(PUBLISHED_CSV, index=False)

    # Save new published JSON
    with open(PUBLISHED_JSON, "w", encoding="utf-8") as f:
        json.dump(published_json, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Working checkpoint → {WORKING_CSV}")
    print(f"✅ Published CSV → {PUBLISHED_CSV}")
    print(f"✅ Published JSON → {PUBLISHED_JSON}")

if __name__ == "__main__":
    main()
