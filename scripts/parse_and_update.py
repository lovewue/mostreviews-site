import os
import re
import gzip
import json
import shutil
import datetime
import time
import random
import xml.etree.ElementTree as ET

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ===== Paths =====
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SITEMAPS_DIR = os.path.join(DATA_DIR, "sitemaps")
SOURCE_DIR = os.path.join(DATA_DIR, "source")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
SLUGS_ARCHIVE_DIR = os.path.join(ARCHIVE_DIR, "slugs")
PARTNERS_ARCHIVE_DIR = os.path.join(ARCHIVE_DIR, "partners")

OUTPUT_ALL_PRODUCTS = os.path.join(SOURCE_DIR, "all_product_urls.csv")
OUTPUT_SLUGS_LATEST = os.path.join(SOURCE_DIR, "unique_seller_slugs_latest.csv")
PARTNERS_FILE = os.path.join(SOURCE_DIR, "partners.json")

BASE = "https://www.notonthehighstreet.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendListBot/1.0; +https://trendlist.co.uk/)"
}

# ---- Behaviour toggles ----
FETCH_NAMES_FOR_ALL_SLUGS = False
PROGRESS_EVERY = 50
MIN_DELAY = 0.5
MAX_DELAY = 1.2
RETRIES = 3
REQUEST_TIMEOUT = 15

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ===== Helpers =====
def today_stamp():
    return datetime.date.today().strftime("%Y-%m-%d")


def ensure_folders():
    os.makedirs(SITEMAPS_DIR, exist_ok=True)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(SLUGS_ARCHIVE_DIR, exist_ok=True)
    os.makedirs(PARTNERS_ARCHIVE_DIR, exist_ok=True)


def latest_stamp_from_files(folder: str):
    if not os.path.exists(folder):
        return None

    dates = []
    for f in os.listdir(folder):
        m = re.search(r"-(\d{4}-\d{2}-\d{2})\.xml\.gz$", f)
        if m:
            dates.append(m.group(1))
    return max(dates) if dates else None


def slug_to_name(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


def polite_delay():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def fetch_partner_name(slug: str, retries: int = RETRIES) -> tuple[str, bool]:
    """
    Fetch the partner's store name from NOTHS. Returns (name, active).

    Notes:
    - Retries on transient edge errors (429/5xx/52x).
    - DOES NOT mark inactive just because of transient errors.
    """
    slug = str(slug).strip().lower()
    url = f"{BASE}/partners/{slug}"

    transient = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}

    for attempt in range(1, retries + 1):
        try:
            r = SESSION.get(url, timeout=REQUEST_TIMEOUT)

            if r.status_code in transient:
                print(f"   ⚠️ {slug} → HTTP {r.status_code} (attempt {attempt}/{retries})")
                if attempt < retries:
                    time.sleep(2 * attempt)
                    continue
                return slug_to_name(slug), True

            if r.status_code != 200:
                print(f"   ⚠️ {slug} → HTTP {r.status_code}")
                return slug_to_name(slug), False

            soup = BeautifulSoup(r.text, "html.parser")

            h1 = soup.find("h1", class_="toga-storefront-intro__maintitle")
            if not h1:
                h1 = soup.find("h1")

            if h1:
                raw_name = h1.get_text(strip=True)
                return raw_name, True

            return slug_to_name(slug), True

        except Exception as e:
            print(f"   ❌ Error fetching {url}: {e} (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(2 * attempt)
                continue

    return slug_to_name(slug), True


def parse_sitemaps(folder: str):
    stamp = today_stamp()

    if not os.path.exists(folder):
        print(f"⚠️ Sitemap folder does not exist: {folder}")
        return [], []

    gz_files = [f for f in os.listdir(folder) if f.endswith(f"-{stamp}.xml.gz")]

    if not gz_files:
        latest = latest_stamp_from_files(folder)
        if not latest:
            print("⚠️ No sitemap files available.")
            return [], []
        print(f"ℹ️ Using latest available sitemaps ({latest})")
        gz_files = [f for f in os.listdir(folder) if f.endswith(f"-{latest}.xml.gz")]

    all_urls = []
    slugs = []
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    product_slug_re = re.compile(r"notonthehighstreet\.com/([^/]+)/product/", re.IGNORECASE)

    for fname in sorted(gz_files):
        path = os.path.join(folder, fname)
        print(f"🔍 Parsing {fname}")

        try:
            with gzip.open(path, "rb") as f:
                root = ET.parse(f).getroot()
        except Exception as e:
            print(f"   ❌ Failed to parse {fname}: {e}")
            continue

        locs = root.findall(".//sm:loc", ns) or root.findall(".//loc")
        for loc in locs:
            url = (loc.text or "").strip()
            if "/product/" in url:
                all_urls.append(url)
                m = product_slug_re.search(url)
                if m:
                    slugs.append(m.group(1).strip().lower())

    all_urls = list(dict.fromkeys(all_urls))
    slugs = list(dict.fromkeys(slugs))
    return all_urls, slugs


def load_partners():
    if os.path.exists(PARTNERS_FILE):
        with open(PARTNERS_FILE, "r", encoding="utf-8") as f:
            partners = json.load(f)
        if not isinstance(partners, list):
            print("⚠️ partners.json is not a list. Resetting to empty list.")
            return []
        return partners
    return []


def update_partners(slugs):
    """
    Append-only update:
    - backup partners.json daily
    - add new partner entries for new slugs only
    """
    partners = load_partners()

    if os.path.exists(PARTNERS_FILE):
        backup_path = os.path.join(PARTNERS_ARCHIVE_DIR, f"partners_{today_stamp()}.json")
        shutil.copy2(PARTNERS_FILE, backup_path)
        print(f"🗄 Backup saved → {backup_path}")

    existing = {
        str(p.get("slug", "")).strip().lower()
        for p in partners
        if isinstance(p, dict) and str(p.get("slug", "")).strip()
    }

    print(f"Using partners file: {PARTNERS_FILE}")
    print(f"Loaded {len(partners)} partner records")
    print(f"Loaded {len(existing)} existing slugs")

    new_entries = []
    total = len(slugs)

    for i, slug in enumerate(slugs, start=1):
        slug = str(slug).strip().lower()

        if slug in existing:
            continue

        polite_delay()
        name, active = fetch_partner_name(slug)

        entry = {
            "slug": slug,
            "name": name,
            "url": f"{BASE}/partners/{slug}",
            "product_count": 0,
            "active": active,
            "since": "",
            "awin": (
                "https://www.awin1.com/cread.php?"
                "awinmid=18484&awinaffid=1018637&clickref=TrendList&ued="
                f"{BASE}/partners/{slug}"
            ),
            "review_count": 0,
            "fail_count": 0,
            "aliases": [],
            "canonical_slug": slug,
        }

        partners.append(entry)
        existing.add(slug)
        new_entries.append(f"{slug} ({name})")

        if len(new_entries) % PROGRESS_EVERY == 0:
            print(f"⏳ Added {len(new_entries)} new partners so far… (scanned {i}/{total})")

    with open(PARTNERS_FILE, "w", encoding="utf-8") as f:
        json.dump(partners, f, indent=2, ensure_ascii=False)

    if new_entries:
        print(f"🆕 Added {len(new_entries)} new partners:")
        for n in new_entries[:10]:
            print(f"   - {n}")
        if len(new_entries) > 10:
            print("   ...")
    else:
        print("✅ No new partners to add")


def main():
    ensure_folders()

    urls, slugs = parse_sitemaps(SITEMAPS_DIR)
    if not urls:
        return

    pd.DataFrame(urls, columns=["URL"]).to_csv(OUTPUT_ALL_PRODUCTS, index=False)
    print(f"✅ Saved all product URLs → {OUTPUT_ALL_PRODUCTS}")
    print(f"ℹ️ Found {len(urls):,} product URLs and {len(slugs):,} unique seller slugs")

    if FETCH_NAMES_FOR_ALL_SLUGS:
        print("⚠️ FETCH_NAMES_FOR_ALL_SLUGS=True (this can take a long time)")
        rows = []
        name_cache = {}
        total = len(slugs)

        for i, slug in enumerate(slugs, start=1):
            if slug in name_cache:
                name = name_cache[slug]
            else:
                polite_delay()
                name, _ = fetch_partner_name(slug)
                name_cache[slug] = name

            rows.append({"slug": slug, "name": name})

            if i % PROGRESS_EVERY == 0 or i == total:
                print(f"⏳ Partner names: {i}/{total} ({i/total:.0%})")
    else:
        rows = [{"slug": s, "name": slug_to_name(s)} for s in slugs]
        print("✅ Wrote seller names using slug_to_name() (fast mode; no NOTHS requests)")

    archive_path = os.path.join(SLUGS_ARCHIVE_DIR, f"unique_seller_slugs_{today_stamp()}.csv")
    pd.DataFrame(rows).to_csv(archive_path, index=False)
    print(f"🗄 Archived slugs → {archive_path}")

    tmp = OUTPUT_SLUGS_LATEST + ".tmp"
    pd.DataFrame(rows).to_csv(tmp, index=False)
    os.replace(tmp, OUTPUT_SLUGS_LATEST)
    print(f"✅ Wrote latest slugs → {OUTPUT_SLUGS_LATEST}")

    update_partners(slugs)


if __name__ == "__main__":
    main()
