import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

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
PARTNERS_JSON = PROJECT_ROOT / "partners_search.json"  # optional helper file
MONTHLY_ROOT = DATA_DIR / "monthly"
MONTHLY_INDEX_FILE = MONTHLY_ROOT / "index.json"


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
FEEFO_PRODUCT_URL = (
    "https://www.feefo.com/en-US/reviews/notonthehighstreet-com/products/*"
    "?sku={sku}&displayFeedbackType=PRODUCT&timeFrame=ALL"
)

MAX_TO_PROCESS = None          # e.g. 20 for testing, or None for all
SAVE_EVERY = 10
PAGE_WAIT_SECONDS = 15
HEADLESS = False
MIN_SLEEP = 1.0
MAX_SLEEP = 2.0

# If ChromeDriver is already on PATH, leave as None
CHROMEDRIVER_PATH = None


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
    if url.lower() in {"not found", "error", ""}:
        return None
    return url


def parse_seller_slug_from_product_url(url: str | None) -> str | None:
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


def is_placeholder(value) -> bool:
    if value is None:
        return True
    s = str(value).strip().lower()
    return s in {
        "",
        "unknown",
        "unknown brand",
        "unknown seller",
        "not found",
        "error",
        "none",
        "null",
    }


def normalise_placeholder(value):
    if is_placeholder(value):
        return None
    return value


# -----------------------------------------------------------------------------
# Optional seller name lookup
# -----------------------------------------------------------------------------
def load_partner_lookup() -> dict:
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
# Cache I/O
# -----------------------------------------------------------------------------
def load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)

        cleaned = {}
        for r in items:
            sku = clean_sku(r.get("sku", ""))
            if not sku:
                continue

            r = {k: normalise_placeholder(v) for k, v in r.items()}
            r["sku"] = sku
            cleaned[sku] = r

        return cleaned

    return {}


def save_cache(cache_by_sku: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    items = list(cache_by_sku.values())
    items.sort(key=lambda r: r.get("sku", ""))

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Monthly helpers
# -----------------------------------------------------------------------------
def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_latest_month_skus() -> tuple[str | None, list[str]]:
    if not MONTHLY_INDEX_FILE.exists():
        print(f"⚠️ Monthly index not found: {MONTHLY_INDEX_FILE}")
        return None, []

    try:
        index_data = load_json(MONTHLY_INDEX_FILE)
        months = index_data.get("months", [])
        if not months:
            print("⚠️ No months found in monthly index")
            return None, []

        latest_entry = sorted(
            [m for m in months if isinstance(m, dict) and m.get("month")],
            key=lambda x: x["month"],
            reverse=True,
        )[0]

        latest_month = latest_entry["month"]

        json_file = latest_entry.get("json_file")
        if json_file:
            month_file = Path(json_file)
            if not month_file.is_absolute():
                month_file = PROJECT_ROOT / month_file
        else:
            month_file = MONTHLY_ROOT / latest_month / "top_products.json"

        if not month_file.exists():
            print(f"⚠️ Latest month file not found: {month_file}")
            return latest_month, []

        month_data = load_json(month_file)
        skus = []
        for item in month_data.get("items", []):
            sku = clean_sku(item.get("sku", ""))
            if sku:
                skus.append(sku)

        return latest_month, sorted(set(skus))

    except Exception as e:
        print(f"⚠️ Could not load latest month SKUs: {e}")
        return None, []


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


# -----------------------------------------------------------------------------
# Page helpers
# -----------------------------------------------------------------------------
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
                "source": "feefo_selenium",
                "name": product_name,
                "product_url": product_url,
                "seller_slug": seller_slug,
            }

        return {
            "status": "not_found",
            "source": "feefo_selenium",
            "name": None,
            "product_url": None,
            "seller_slug": None,
        }

    except TimeoutException:
        return {
            "status": "error",
            "source": "feefo_selenium",
            "name": None,
            "product_url": None,
            "seller_slug": None,
        }
    except WebDriverException:
        return {
            "status": "error",
            "source": "feefo_selenium",
            "name": None,
            "product_url": None,
            "seller_slug": None,
        }


def is_product_live_selenium(driver: webdriver.Chrome, url: str | None) -> bool:
    url = clean_url(url)
    if not url:
        return False

    try:
        driver.get(url)
        WebDriverWait(driver, PAGE_WAIT_SECONDS).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        current_url = (driver.current_url or "").lower()
        return "/product/" in current_url

    except Exception:
        return False


# -----------------------------------------------------------------------------
# Merge logic
# -----------------------------------------------------------------------------
def merge_with_existing(existing: dict | None, fresh: dict) -> dict:
    existing = existing or {}
    existing = {k: normalise_placeholder(v) for k, v in existing.items()}

    merged = dict(existing)

    for key in ["name", "seller_slug", "seller_name", "product_url"]:
        if fresh.get(key):
            merged[key] = fresh[key]

    for key in [
        "available",
        "updated_at",
        "last_checked_at",
        "lookup_status",
        "lookup_method",
        "lookup_attempts",
        "sku",
    ]:
        if key in fresh:
            merged[key] = fresh[key]

    return merged


# -----------------------------------------------------------------------------
# Recovery helpers
# -----------------------------------------------------------------------------
def record_needs_recovery(record: dict | None) -> bool:
    if not record:
        return True

    return (
        is_placeholder(record.get("name"))
        or is_placeholder(record.get("seller_slug"))
        or is_placeholder(record.get("seller_name"))
    )


def build_meta_with_selenium(
    driver: webdriver.Chrome,
    sku: str,
    existing: dict | None = None,
) -> dict:
    existing = existing or {}
    previous_attempts = int(existing.get("lookup_attempts", 0) or 0)

    feefo = get_feefo_data_selenium(driver, sku)

    if feefo["status"] in {"ok", "partial"} and (
        feefo.get("name") or feefo.get("product_url") or feefo.get("seller_slug")
    ):
        seller_slug = feefo.get("seller_slug")
        seller_name = get_seller_name(seller_slug)

        url = feefo.get("product_url")
        available = is_product_live_selenium(driver, url) if url else False

        if url and available:
            lookup_status = "recovered_via_feefo_selenium"
        elif url:
            lookup_status = "historical_feefo_match_selenium"
        else:
            lookup_status = "partial_feefo_selenium"

        timestamp = now_iso()
        fresh = {
            "sku": sku,
            "name": feefo.get("name"),
            "seller_slug": seller_slug,
            "seller_name": seller_name,
            "product_url": url,
            "available": available,
            "lookup_status": lookup_status,
            "lookup_method": "feefo_selenium",
            "lookup_attempts": previous_attempts + 1,
            "updated_at": timestamp,
            "last_checked_at": timestamp,
        }
        return merge_with_existing(existing, fresh)

    timestamp = now_iso()
    fresh = {
        "sku": sku,
        "available": existing.get("available", False),
        "lookup_status": "not_found_selenium",
        "lookup_method": "feefo_selenium",
        "lookup_attempts": previous_attempts + 1,
        "updated_at": timestamp,
        "last_checked_at": timestamp,
    }
    return merge_with_existing(existing, fresh)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> None:
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Cache file:   {CACHE_FILE}")
    print(f"Cache exists: {CACHE_FILE.exists()}")
    print()

    cache = load_cache()
    latest_month, latest_month_skus = load_latest_month_skus()

    print(f"📦 Cache SKUs:         {len(cache)}")
    if latest_month:
        print(f"🗂 Latest month:       {latest_month}")
        print(f"🆕 Latest month SKUs:  {len(latest_month_skus)}")
    print()

    to_process = sorted(
        sku
        for sku in latest_month_skus
        if record_needs_recovery(cache.get(sku))
    )

    if MAX_TO_PROCESS:
        to_process = to_process[:MAX_TO_PROCESS]

    print(f"🔧 SKUs to recover:    {len(to_process)}")
    print()

    if not to_process:
        print("✅ No unresolved SKUs found for the latest month.")
        return

    driver = make_driver()

    try:
        for i, sku in enumerate(to_process, 1):
            existing = cache.get(sku, {})
            meta = build_meta_with_selenium(driver, sku, existing)
            cache[sku] = meta

            print(
                f"✅ {i}: cached {sku} – "
                f"{meta.get('name') or '[no name]'} "
                f"(slug={meta.get('seller_slug') or '[none]'}, "
                f"status={meta.get('lookup_status')}, "
                f"avail={meta.get('available')})"
            )

            if i % SAVE_EVERY == 0:
                save_cache(cache)
                print(f"💾 Progress saved ({i} items)")

            time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))

    finally:
        save_cache(cache)
        print()
        print(f"✅ Saved updated cache → {CACHE_FILE}")
        print("🏁 Selenium recovery complete.")
        driver.quit()


if __name__ == "__main__":
    main()
