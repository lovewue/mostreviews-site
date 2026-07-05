import csv
import re
import time
import random
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


BASE = Path(r"C:\Users\richa\OneDrive - Wue\Documents 1\GitHub\mostreviews-site")

BRANDS_CSV = BASE / "data" / "published" / "brands.csv"
OUTPUT_CSV = BASE / "data" / "working" / "brands_out_of_stock_only_selenium.csv"

START_FROM = 0          # change if you want to resume
MAX_BRANDS = None       # e.g. 200 for testing, or None for all
HEADLESS = False        # set True once happy
SLEEP_RANGE = (1.2, 2.4)


def norm(x):
    if x is None:
        return ""
    return str(x).strip()


def pick(row, *keys):
    for key in keys:
        if key in row and norm(row[key]):
            return row[key]
    return ""


def build_brand_url(row):
    slug = norm(pick(row, "slug", "seller_slug", "partner_slug"))
    url = norm(pick(
        row,
        "url",
        "brand_url",
        "page_url",
        "partner_url",
        "partner_page_url",
        "noths_url",
        "link",
    ))

    if not url and slug:
        url = f"https://www.notonthehighstreet.com/partners/{slug}#products"

    if url and "#products" not in url:
        url = url.rstrip("/") + "#products"

    return slug, url


def make_driver():
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(45)
    return driver


def accept_cookies_if_present(driver):
    texts = [
        "Accept",
        "Accept all",
        "Allow all",
        "I agree",
    ]
    for txt in texts:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        f"//button[normalize-space()='{txt}' or .//span[normalize-space()='{txt}']]"
                    )
                )
            )
            btn.click()
            time.sleep(1)
            return
        except Exception:
            pass


def wait_for_page(driver):
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(2)


def slow_scroll(driver, steps=8):
    last_height = driver.execute_script("return document.body.scrollHeight")
    for i in range(steps):
        driver.execute_script(
            "window.scrollTo(0, arguments[0]);",
            int((i + 1) * last_height / steps)
        )
        time.sleep(1.0)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)


def visible_text(driver):
    return driver.find_element(By.TAG_NAME, "body").text


def parse_showing_count(text):
    m = re.search(r"Showing\s+([\d,]+)\s+products", text, flags=re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0


def count_product_state(text):
    out_of_stock = len(re.findall(r"\bOut of stock\b", text, flags=re.I))
    estimated_delivery = len(re.findall(r"Estimated delivery", text, flags=re.I))
    return out_of_stock, estimated_delivery


def classify_brand(driver, url):
    driver.get(url)
    wait_for_page(driver)
    accept_cookies_if_present(driver)

    # let JS settle and try to load product grid
    slow_scroll(driver, steps=10)

    text = visible_text(driver)

    showing_count = parse_showing_count(text)
    out_of_stock_count, estimated_delivery_count = count_product_state(text)

    # fallback check: sometimes a brand page says no products
    no_products = bool(re.search(r"\bNo products\b", text, flags=re.I))

    if no_products or showing_count == 0:
        status = "no_products"
    elif out_of_stock_count > 0 and estimated_delivery_count == 0:
        status = "out_of_stock_only_visible"
    elif estimated_delivery_count > 0:
        status = "has_in_stock_visible"
    else:
        status = "unclear"

    return {
        "status": status,
        "showing_count": showing_count,
        "visible_out_of_stock": out_of_stock_count,
        "visible_in_stock": estimated_delivery_count,
        "error": "",
    }


def save_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "slug",
                "name",
                "url",
                "showing_count",
                "visible_out_of_stock",
                "visible_in_stock",
                "status",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    with open(BRANDS_CSV, "r", encoding="utf-8-sig", newline="") as f:
        brands = list(csv.DictReader(f))

    if MAX_BRANDS is not None:
        brands = brands[START_FROM:START_FROM + MAX_BRANDS]
    else:
        brands = brands[START_FROM:]

    driver = make_driver()
    results = []

    try:
        for i, row in enumerate(brands, start=1):
            slug, url = build_brand_url(row)
            name = norm(pick(row, "name", "seller_name", "brand_name", "partner_name"))

            if not slug:
                continue

            if not url:
                results.append({
                    "slug": slug,
                    "name": name,
                    "url": "",
                    "showing_count": 0,
                    "visible_out_of_stock": 0,
                    "visible_in_stock": 0,
                    "status": "missing_url",
                    "error": "",
                })
                continue

            print(f"[{i}/{len(brands)}] {slug}")

            try:
                info = classify_brand(driver, url)
            except Exception as e:
                info = {
                    "status": "fetch_failed",
                    "showing_count": 0,
                    "visible_out_of_stock": 0,
                    "visible_in_stock": 0,
                    "error": str(e),
                }

            results.append({
                "slug": slug,
                "name": name,
                "url": url,
                "showing_count": info["showing_count"],
                "visible_out_of_stock": info["visible_out_of_stock"],
                "visible_in_stock": info["visible_in_stock"],
                "status": info["status"],
                "error": info["error"],
            })

            if i % 25 == 0:
                save_csv(OUTPUT_CSV, results)
                print(f"   saved checkpoint: {len(results)} rows")

            time.sleep(random.uniform(*SLEEP_RANGE))

    finally:
        driver.quit()

    save_csv(OUTPUT_CSV, results)

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1

    print(f"\nDone: {len(results)} brands written")
    print(f"Output: {OUTPUT_CSV}")
    print("\nStatus summary:")
    for k, v in sorted(summary.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
