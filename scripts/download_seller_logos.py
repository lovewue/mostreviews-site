import json
import re
import time
import random
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

BRANDS_JSON = PROJECT_ROOT / "data" / "published" / "brands.json"
OUTPUT_DIR = PROJECT_ROOT / "static" / "img" / "sellers"
REPORT_FILE = PROJECT_ROOT / "data" / "reports" / "seller_logo_download_report.json"


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
BASE = "https://www.notonthehighstreet.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendListBot/1.0; +https://trendlist.co.uk/)",
    "Accept-Language": "en-GB,en;q=0.9",
}

SLEEP_RANGE = (0.8, 1.8)
TIMEOUT = 20
OVERWRITE_EXISTING = False

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def slugify(value: str) -> str:
    value = clean_text(value).lower()
    value = value.replace("&", "and")
    value = re.sub(r"[’']", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def get_brand_slug(row: dict) -> str:
    return clean_text(
        row.get("slug")
        or row.get("seller_slug")
        or row.get("canonical_slug")
        or ""
    ).lower()


def get_brand_name(row: dict) -> str:
    return clean_text(
        row.get("name")
        or row.get("seller_name")
        or row.get("brand_name")
        or ""
    )


def get_brand_url(row: dict, slug: str) -> str:
    urls = row.get("urls", {}) if isinstance(row.get("urls"), dict) else {}

    url = (
        row.get("brand_url")
        or row.get("url")
        or urls.get("brand")
        or ""
    )

    url = clean_text(url)

    if url:
        return url

    return f"{BASE}/partners/{slug}"


def strip_query(url: str) -> str:
    return url.split("?", 1)[0]


def extension_from_url(url: str) -> str:
    clean = strip_query(url).lower()

    for ext in VALID_EXTENSIONS:
        if clean.endswith(ext):
            return ext

    return ".jpg"


def load_brands() -> list[dict]:
    if not BRANDS_JSON.exists():
        raise FileNotFoundError(f"Missing brands file: {BRANDS_JSON}")

    with open(BRANDS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("brands.json must be a list")

    return [row for row in data if isinstance(row, dict)]


def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def find_logo_url(html: str, brand_name: str = "") -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Best match: img alt contains "logo"
    logo_imgs = soup.find_all(
        "img",
        alt=lambda value: value and "logo" in value.lower()
    )

    if logo_imgs:
        src = logo_imgs[0].get("src") or logo_imgs[0].get("data-src")
        if src:
            return src

    # Next best: image URL contains "logo"
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt") or ""

        haystack = f"{src} {alt}".lower()

        if "logo" in haystack:
            return src

    # Optional fallback: if brand name appears in alt and src is contentstack
    brand_words = slugify(brand_name).replace("-", " ")
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt") or ""

        if not src:
            continue

        if "images.contentstack.io" in src and brand_words:
            if slugify(alt).replace("-", " ") in brand_words or brand_words in slugify(alt).replace("-", " "):
                return src

    return ""


def download_logo(logo_url: str, output_path: Path) -> None:
    r = requests.get(logo_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(r.content)


def write_report(rows: list[dict]) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    brands = load_brands()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    report = []

    print(f"📦 Brands loaded: {len(brands)}")
    print(f"🖼️ Logo output dir: {OUTPUT_DIR}")
    print()

    for idx, brand in enumerate(brands, start=1):
        slug = get_brand_slug(brand)
        name = get_brand_name(brand) or slug

        if not slug:
            continue

        existing_files = list(OUTPUT_DIR.glob(f"{slug}.*"))

        if existing_files and not OVERWRITE_EXISTING:
            print(f"⏭️ {idx}/{len(brands)} {slug}: logo already exists")
            report.append({
                "slug": slug,
                "name": name,
                "status": "already_exists",
                "file": str(existing_files[0]),
            })
            continue

        brand_url = get_brand_url(brand, slug)

        print(f"🔍 {idx}/{len(brands)} {slug} → {brand_url}")

        try:
            html = fetch_html(brand_url)
            logo_url = find_logo_url(html, name)

            if not logo_url:
                print("   ⚠️ No logo found")
                report.append({
                    "slug": slug,
                    "name": name,
                    "brand_url": brand_url,
                    "status": "no_logo_found",
                })
                continue

            logo_url = urljoin(brand_url, logo_url)
            ext = extension_from_url(logo_url)
            out_path = OUTPUT_DIR / f"{slug}{ext}"

            download_logo(logo_url, out_path)

            print(f"   ✅ Saved → {out_path.name}")

            report.append({
                "slug": slug,
                "name": name,
                "brand_url": brand_url,
                "logo_url": logo_url,
                "file": str(out_path),
                "status": "saved",
            })

        except Exception as e:
            print(f"   ❌ Failed: {e}")
            report.append({
                "slug": slug,
                "name": name,
                "brand_url": brand_url,
                "status": "failed",
                "error": str(e),
            })

        if idx % 25 == 0:
            write_report(report)
            print(f"💾 Report checkpoint saved ({idx})")

        time.sleep(random.uniform(*SLEEP_RANGE))

    write_report(report)

    saved = sum(1 for r in report if r.get("status") == "saved")
    skipped = sum(1 for r in report if r.get("status") == "already_exists")
    missing = sum(1 for r in report if r.get("status") == "no_logo_found")
    failed = sum(1 for r in report if r.get("status") == "failed")

    print()
    print("🏁 Logo download complete")
    print(f"✅ Saved: {saved}")
    print(f"⏭️ Already existed: {skipped}")
    print(f"⚠️ No logo found: {missing}")
    print(f"❌ Failed: {failed}")
    print(f"🧾 Report: {REPORT_FILE}")


if __name__ == "__main__":
    main()
