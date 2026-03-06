import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
CACHE_FILE = DATA_DIR / "cache" / "products_cache.json"

ALL_TIME_FILE = DATA_DIR / "feefo_product_ratings_all_20260301.xlsx"
LAST_12_MONTHS_FILE = DATA_DIR / "feefo_product_ratings_year_20260301.xlsx"

OUT_DIR = DATA_DIR / "derived" / "leaderboards"
OUT_ALL_TIME = OUT_DIR / "top_products_all_time.json"
OUT_LAST_12 = OUT_DIR / "top_products_last_12_months.json"

PARTNERS_JSON = PROJECT_ROOT / "partners_search.json"  # optional helper file


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TOP_N = 250              # e.g. 100 for testing, or None for all rows
SAVE_EVERY = 25
HEADLESS = False          # set True once happy
PAGE_WAIT_SECONDS = 15
MIN_SLEEP = 0.8
MAX_SLEEP = 1.6

# If ChromeDriver is already on PATH, leave as None
CHROMEDRIVER_PATH = None

FEEFO_PRODUCT_URL = (
    "https://www.feefo.com/en-US/reviews/notonthehighstreet-com/products/*"
    "?sku={sku}&displayFeedbackType=PRODUCT&timeFrame=ALL"
)


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_sku(raw) -> str:
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None


def clean_url(url: str | None) -> str | None:
    if not url:
        return None
    url = str(url).strip()
    if url.lower() in {"", "not found", "error"}:
        return None
    return url


def parse_seller_slug_from_product_url(url: str | None) -> str | None:
    """
    Extract seller slug from URLs like:
    https://www.notonthehighstreet.com/liviandbelle/product/extra-large-personalised-snowy-wreath
    """
    url = clean_url(url)
    if not url:
        return None

    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 3 and parts[1] == "product":
            return parts[0].lower()
    except Exception:
        return None

    return None


def normalise_placeholder(value):
    if isinstance(value, str) and value.strip().lower() in {
        "not found",
        "unknown",
        "unknown seller",
        "error",
        "",
    }:
        return None
    return value


def safe_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def safe_int(value, default=0):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


# -----------------------------------------------------------------------------
# Optional seller name lookup
# -----------------------------------------------------------------------------
def load_partner_lookup() -> dict:
    """
    Load an optional partner slug -> seller name lookup.

    Expected structure:
        [
          {"slug": "wue", "name": "Wue"},
          ...
        ]
    """
    if PARTNERS_JSON.exists():
        try:
            with open(PARTNERS_JSON, "r", encoding="utf-8") as f:
                partners = json.load(f)

            lookup = {
                p["slug"]: p["name"]
                for p in partners
                if p.get("slug") and p.get("name")
            }

            print(f"📂 Loaded {len(lookup)} partners from {PARTNERS_JSON}")
            return lookup

        except Exception as e:
            print(f"⚠️ Could not load {PARTNERS_JSON}: {e}")

    return {}


partner_lookup = load_partner_lookup()
seller_name_cache = {}


def get_seller_name(slug: str | None, fallback: str | None = None) -> str | None:
    if not slug:
        return fallback

    if slug in seller_name_cache:
        return seller_name_cache[slug]

    if slug in partner_lookup:
        seller_name_cache[slug] = partner_lookup[slug]
        return partner_lookup[slug]

    name = slug.replace("-", " ").title()
    seller_name_cache[slug] = name
    return name


# -----------------------------------------------------------------------------
# Cache helpers
# -----------------------------------------------------------------------------
def load_cache() -> dict:
    """
    Load product cache keyed by SKU.
    """
    if not CACHE_FILE.exists():
        return {}

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)

    cleaned = {}
    for row in items:
        sku = clean_sku(row.get("sku", ""))
        if not sku:
            continue

        row = {k: normalise_placeholder(v) for k, v in row.items()}
        row["sku"] = sku
        cleaned[sku] = row

    print(f"📦 Loaded cache: {len(cleaned)} products")
    return cleaned


# -----------------------------------------------------------------------------
# Selenium setup
# -----------------------------------------------------------------------------
def make_driver() -> webdriver.Chrome:
    chrome_options = Options()

    if HEADLESS:
        chrome_options.add_argument("--headless=new")

    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--lang=en-GB")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    if CHROMEDRIVER_PATH:
        service = Service(CHROMEDRIVER_PATH)
        return webdriver.Chrome(service=service, options=chrome_options)

    return webdriver.Chrome(options=chrome_options)


def wait_for_feefo_page(driver: webdriver.Chrome) -> None:
    wait = WebDriverWait(driver, PAGE_WAIT_SECONDS)

    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    wait.until(
        lambda d: (
            len(d.find_elements(By.TAG_NAME, "h1")) > 0
            or len(d.find_elements(By.TAG_NAME, "a")) > 0
        )
    )


def dismiss_cookie_or_popup_if_present(driver: webdriver.Chrome) -> None:
    candidate_xpaths = [
        "//button[contains(., 'Accept')]",
        "//button[contains(., 'I Accept')]",
        "//button[contains(., 'Allow all')]",
        "//button[contains(., 'OK')]",
        "//button[contains(., 'Got it')]",
    ]

    for xpath in candidate_xpaths:
        try:
            buttons = driver.find_elements(By.XPATH, xpath)
            if buttons:
                buttons[0].click()
                time.sleep(1)
                return
        except Exception:
            pass


def get_feefo_data_selenium(driver: webdriver.Chrome, sku: str) -> dict:
    """
    Recover product metadata from Feefo using Selenium.
    """
    url = FEEFO_PRODUCT_URL.format(sku=sku)

    try:
        driver.get(url)
        wait_for_feefo_page(driver)
        dismiss_cookie_or_popup_if_present(driver)

        product_name = None
        product_url = None
        seller_slug = None

        h1_elements = driver.find_elements(By.TAG_NAME, "h1")
        if h1_elements:
            product_name = clean_text(h1_elements[0].text)

        anchors = driver.find_elements(By.TAG_NAME, "a")
        for a in anchors:
            href = clean_url(a.get_attribute("href"))
            if href and "notonthehighstreet.com" in href and "/product/" in href:
                product_url = href
                break

        seller_slug = parse_seller_slug_from_product_url(product_url)

        if product_name or product_url or seller_slug:
            return {
                "status": "ok" if product_url else "partial",
                "name": product_name,
                "product_url": product_url,
                "seller_slug": seller_slug,
            }

        return {
            "status": "not_found",
            "name": None,
            "product_url": None,
            "seller_slug": None,
        }

    except (TimeoutException, WebDriverException):
        return {
            "status": "error",
            "name": None,
            "product_url": None,
            "seller_slug": None,
        }


# -----------------------------------------------------------------------------
# Leaderboard build
# -----------------------------------------------------------------------------
def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c: " ".join(str(c).split()) for c in df.columns}
    return df.rename(columns=cols)


def read_feefo_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    df = pd.read_excel(path)
    df = normalise_columns(df)

    required = {"Product Code", "review_count"}
    if not required.issubset(df.columns):
        raise ValueError(
            f"{path.name} is missing required columns. Found: {list(df.columns)}"
        )

    df["sku"] = df["Product Code"].apply(clean_sku)
    df["reviews"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0).astype(int)

    if "rating" in df.columns:
        df["rating_value"] = pd.to_numeric(df["rating"], errors="coerce")
        df = df.sort_values(
            ["reviews", "rating_value", "sku"],
            ascending=[False, False, True],
        )
    else:
        df["rating_value"] = None
        df = df.sort_values(
            ["reviews", "sku"],
            ascending=[False, True],
        )

    if TOP_N:
        df = df.head(TOP_N)

    return df


def base_row_from_cache(sku: str, reviews: int, rating: float | None, rank: int, cache: dict) -> dict:
    cache_row = cache.get(sku, {})

    return {
        "rank": rank,
        "sku": sku,
        "name": cache_row.get("name"),
        "seller_slug": cache_row.get("seller_slug"),
        "seller_name": cache_row.get("seller_name"),
        "product_url": cache_row.get("product_url"),
        "available": cache_row.get("available"),
        "reviews": reviews,
        "rating": rating,
        "metadata_source": "cache" if cache_row else "missing",
    }


def needs_feefo_enrichment(row: dict) -> bool:
    """
    Only run Feefo lookup if we are missing core product metadata.
    Seller slug can be derived from product URL.
    """
    return not row.get("name") or not row.get("product_url")


def enrich_row_from_feefo(driver: webdriver.Chrome, row: dict) -> dict:
    """
    Enrich one leaderboard row from Feefo without touching the main cache.
    """
    feefo = get_feefo_data_selenium(driver, row["sku"])

    if feefo["status"] in {"ok", "partial"}:
        if feefo.get("name"):
            row["name"] = feefo["name"]

        if feefo.get("product_url"):
            row["product_url"] = feefo["product_url"]

        if feefo.get("seller_slug"):
            row["seller_slug"] = feefo["seller_slug"]

        if row.get("seller_slug") and not row.get("seller_name"):
            row["seller_name"] = get_seller_name(row["seller_slug"])

        row["metadata_source"] = "feefo"

    return row


def build_leaderboard(path: Path, label: str, cache: dict, driver: webdriver.Chrome | None = None) -> dict:
    df = read_feefo_file(path)

    items = []
    feefo_enriched = 0
    feefo_needed = 0

    for rank, row in enumerate(df.itertuples(index=False), start=1):
        sku = getattr(row, "sku")
        reviews = safe_int(getattr(row, "reviews"))
        rating = safe_float(getattr(row, "rating_value"))

        item = base_row_from_cache(sku, reviews, rating, rank, cache)

        if needs_feefo_enrichment(item):
            feefo_needed += 1

            if driver is not None:
                item = enrich_row_from_feefo(driver, item)

                if item.get("metadata_source") == "feefo":
                    feefo_enriched += 1

                time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))

        items.append(item)

        if rank % SAVE_EVERY == 0:
            print(f"   …processed {rank} rows for {label}")

    output = {
        "leaderboard": label,
        "generated_at": now_iso(),
        "source_file": path.name,
        "product_count": len(items),
        "products_with_name": sum(1 for p in items if p.get("name")),
        "products_missing_name": sum(1 for p in items if not p.get("name")),
        "products_with_seller": sum(1 for p in items if p.get("seller_name")),
        "products_missing_seller": sum(1 for p in items if not p.get("seller_name")),
        "feefo_needed": feefo_needed,
        "feefo_enriched": feefo_enriched,
        "items": items,
    }

    return output


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    cache = load_cache()
    print()

    driver = make_driver()

    try:
        print("🏆 Building all-time leaderboard")
        all_time = build_leaderboard(ALL_TIME_FILE, "all_time", cache, driver)
        save_json(OUT_ALL_TIME, all_time)
        print(
            f"   ✅ Wrote {OUT_ALL_TIME.name} | rows={all_time['product_count']} "
            f"| missing name={all_time['products_missing_name']} "
            f"| feefo enriched={all_time['feefo_enriched']}"
        )
        print()

        print("📈 Building last-12-months leaderboard")
        last_12 = build_leaderboard(LAST_12_MONTHS_FILE, "last_12_months", cache, driver)
        save_json(OUT_LAST_12, last_12)
        print(
            f"   ✅ Wrote {OUT_LAST_12.name} | rows={last_12['product_count']} "
            f"| missing name={last_12['products_missing_name']} "
            f"| feefo enriched={last_12['feefo_enriched']}"
        )
        print()

    finally:
        driver.quit()

    print("🏁 Leaderboards built.")


if __name__ == "__main__":
    main()
