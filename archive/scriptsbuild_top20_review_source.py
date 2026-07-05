import json
import random
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DERIVED_MONTHLY_DIR = PROJECT_ROOT / "data" / "derived" / "monthly"
DEBUG_DIR = PROJECT_ROOT / "data" / "debug" / "feefo_reviews"


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
HEADLESS = False
PAGE_WAIT_SECONDS = 20
MIN_SLEEP = 1.0
MAX_SLEEP = 2.0
TOP_N = 20                  # change to 3 for faster testing
MAX_REVIEWS_PER_PRODUCT = 20
SAVE_DEBUG_HTML_WHEN_EMPTY = True


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_sku(raw) -> str:
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def find_latest_month_dir() -> Path:
    month_dirs = [p for p in DERIVED_MONTHLY_DIR.iterdir() if p.is_dir()]
    if not month_dirs:
        raise FileNotFoundError(f"No month folders found in {DERIVED_MONTHLY_DIR}")
    return sorted(month_dirs)[-1]


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def unique_reviews(reviews: list[dict]) -> list[dict]:
    seen = set()
    out = []

    for r in reviews:
        date_val = clean_text(r.get("date"))
        text_val = clean_text(r.get("text"))
        raw_block = clean_text(r.get("raw_block"))

        if not text_val:
            continue

        key = (date_val, text_val)
        if key in seen:
            continue

        seen.add(key)
        out.append(
            {
                "date": date_val,
                "text": text_val,
                "raw_block": raw_block,
            }
        )

    return out


def extract_slug_from_product_url(url: str) -> Optional[str]:
    """
    Example:
    https://www.notonthehighstreet.com/alphabetgifting/product/personalised-happy-birthday-beanz-jelly-bean-tin-gift
    -> personalised-happy-birthday-beanz-jelly-bean-tin-gift
    """
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if not parts:
            return None
        return parts[-1]
    except Exception:
        return None


def build_feefo_url(sku: str, product_url: str) -> Optional[str]:
    slug = extract_slug_from_product_url(product_url)
    if not slug:
        return None

    return (
        "https://www.feefo.com/en-US/reviews/notonthehighstreet-com/"
        f"products/{slug}?sku={sku}&displayFeedbackType=PRODUCT&timeFrame=MONTH"
    )


def looks_valid_for_product(text: str, product_name: str) -> bool:
    """
    Very light sanity filter.
    Prevent obviously wrong cross-product matches like earrings on jelly beans.
    """
    t = clean_text(text).lower()
    p = clean_text(product_name).lower()

    mismatch_pairs = [
        ("earring", "bean"),
        ("earrings", "bean"),
        ("earring", "jelly"),
        ("bracelet", "bean"),
        ("necklace", "bean"),
        ("pyjama", "earring"),
    ]

    for a, b in mismatch_pairs:
        if a in t and b in p:
            return False

    return True


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

    return webdriver.Chrome(options=chrome_options)


def wait_for_feefo_page(driver: webdriver.Chrome) -> None:
    wait = WebDriverWait(driver, PAGE_WAIT_SECONDS)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    wait.until(
        lambda d: len(d.find_elements(By.TAG_NAME, "body")) > 0
    )


def dismiss_cookie_or_popup_if_present(driver: webdriver.Chrome) -> None:
    candidate_xpaths = [
        "//button[contains(., 'Accept')]",
        "//button[contains(., 'I Accept')]",
        "//button[contains(., 'Allow all')]",
        "//button[contains(., 'Allow All')]",
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


# -----------------------------------------------------------------------------
# Review extraction
# -----------------------------------------------------------------------------
def extract_reviews(driver: webdriver.Chrome, product_name: str) -> list[dict]:
    """
    Primary selector:
      [data-aqa-id='customer-comment-container']
      [data-aqa-id='customer-comment']

    Date may or may not be present. We'll try nearby selectors but allow blank.
    """
    reviews = []

    try:
        containers = driver.find_elements(
            By.CSS_SELECTOR,
            "[data-aqa-id='customer-comment-container']"
        )

        if not containers:
            return []

        for c in containers:
            try:
                text_el = c.find_element(
                    By.CSS_SELECTOR,
                    "[data-aqa-id='customer-comment']"
                )
                text = clean_text(text_el.text)

                if not text:
                    continue

                if not looks_valid_for_product(text, product_name):
                    continue

                date_text = ""
                date_selectors = [
                    "[data-aqa-id='review-date']",
                    "time",
                    "[datetime]",
                ]

                for selector in date_selectors:
                    try:
                        date_els = c.find_elements(By.CSS_SELECTOR, selector)
                        for d in date_els:
                            candidate = clean_text(d.text) or clean_text(d.get_attribute("datetime"))
                            if candidate:
                                date_text = candidate
                                break
                        if date_text:
                            break
                    except Exception:
                        pass

                reviews.append(
                    {
                        "date": date_text,
                        "text": text,
                        "raw_block": clean_text(c.text),
                    }
                )

            except Exception:
                continue

    except Exception:
        return []

    return unique_reviews(reviews)


def scrape_feefo_reviews_for_product(
    driver: webdriver.Chrome,
    sku: str,
    product_url: str,
    product_name: str,
    debug_name: str = "",
    max_reviews: int = MAX_REVIEWS_PER_PRODUCT,
) -> tuple[list[dict], Optional[str]]:
    url = build_feefo_url(sku, product_url)

    if not url:
        return [], None

    try:
        driver.get(url)
        wait_for_feefo_page(driver)
        time.sleep(2)
        dismiss_cookie_or_popup_if_present(driver)
        time.sleep(2)

        # scroll to load more reviews
        for _ in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        # scroll back up
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        try:
            WebDriverWait(driver, 10).until(
                lambda d: len(
                    d.find_elements(
                        By.CSS_SELECTOR,
                        "[data-aqa-id='customer-comment-container']"
                    )
                ) > 0
            )
        except Exception:
            pass

        reviews = extract_reviews(driver, product_name)
        reviews = reviews[:max_reviews]

        if not reviews and SAVE_DEBUG_HTML_WHEN_EMPTY:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            debug_path = DEBUG_DIR / f"{debug_name}_{sku}.html"
            debug_path.write_text(driver.page_source, encoding="utf-8")
            print(f"⚠️ No reviews found for SKU {sku}. Saved debug HTML: {debug_path}")

        return reviews, url

    except (TimeoutException, WebDriverException) as e:
        print(f"⚠️ Selenium error for SKU {sku}: {e}")
        return [], url

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def build_top20_review_source() -> None:
    latest_month_dir = find_latest_month_dir()
    enriched_path = latest_month_dir / "enriched_products.json"

    if not enriched_path.exists():
        raise FileNotFoundError(f"Missing file: {enriched_path}")

    products = load_json(enriched_path)
    top_products = products[:TOP_N]

    print(f"Using month: {latest_month_dir.name}")
    print(f"Using enriched file: {enriched_path}")
    print(f"Products to process: {len(top_products)}")
    print()

    driver = make_driver()
    output = []

    try:
        for idx, product in enumerate(top_products, start=1):
            sku = clean_sku(product.get("sku", ""))
            name = clean_text(product.get("name"))
            product_url = clean_text(product.get("product_url"))
            debug_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name)[:60] or "product"

            print(f"[{idx}/{len(top_products)}] {sku} | {name}")

            reviews, feefo_url = scrape_feefo_reviews_for_product(
                driver=driver,
                sku=sku,
                product_url=product_url,
                product_name=name,
                debug_name=debug_name,
            )

            if idx == 1:
                print("DEBUG first product reviews:")
                for r in reviews[:5]:
                    print(r)

            output.append(
                {
                    "sku": sku,
                    "name": name,
                    "seller_slug": product.get("seller_slug", ""),
                    "seller_name": product.get("seller_name", ""),
                    "product_url": product_url,
                    "available": product.get("available", True),
                    "review_count_month": product.get("review_count_month", 0),
                    "rating_month": product.get("rating_month", ""),
                    "feefo_review_url": feefo_url or "",
                    "reviews": reviews,
                    "all_reviews_raw": reviews,
                    "reviews_found_total": len(reviews),
                    "reviews_found_in_month": len(reviews),  # scraped quote candidates only
                    "quote_candidate_count": len(reviews),
                }
            )

            print(f"    review quote candidates scraped: {len(reviews)}")
            time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))

    finally:
        driver.quit()

    out_path = latest_month_dir / "top20_reviews_for_content.json"
    save_json(out_path, output)

    print()
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    build_top20_review_source()
