import pandas as pd
import glob
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse
from datetime import datetime, timedelta
import time
import os

# --------- SETTINGS ---------
REVIEW_LOOKBACK_DAYS = 30
DELAY_BETWEEN_PRODUCTS = 2  # seconds
OUTPUT_FILE = "data/recent_reviews_web_ready.xlsx"
# ----------------------------

# ✅ Find the most recent Feefo report automatically
files = sorted(glob.glob("data/feefo_product_ratings_week_*.xlsx"), reverse=True)
if files:
    INPUT_FILE = files[0]
    print(f"📄 Using latest Feefo report: {INPUT_FILE}")
else:
    raise FileNotFoundError("❌ No Feefo product rating files found in /data/")

# Set up headless browser
options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Load Feefo product report
df = pd.read_excel(INPUT_FILE)
df = df[df["review_count"] > 1]  # Only products with more than 1 review

results = []

for _, row in df.iterrows():
    product_code = str(int(row["Product Code"]))
    review_count = row["review_count"]
    print(f"🔍 Processing Product Code: {product_code}")

    feefo_url = (
        f"https://www.feefo.com/en-US/reviews/notonthehighstreet-com/products/*"
        f"?sku={product_code}&displayFeedbackType=PRODUCT&timeFrame=ALL"
    )

    try:
        driver.get(feefo_url)
        time.sleep(3)

        # Product title
        try:
            title = driver.find_element(By.CSS_SELECTOR, '[data-aqa-id="product-rating-title"]').text.strip()
        except:
            title = ""

        # NOTHS product URL
        try:
            noths_url = driver.find_element(By.ID, "product-info-visit-product-page-button").get_attribute("href")
        except:
            noths_url = ""

        # 🆕 Seller name from NOTHS product page
        seller = ""
        if noths_url:
            try:
                driver.get(noths_url)
                time.sleep(2)
                seller_element = driver.find_element(By.CSS_SELECTOR, 'a[href^="/"]')
                seller = seller_element.text.strip()
            except:
                seller = ""

        results.append({
            "Product Code": product_code,
            "Product Title": title,
            "Seller": seller,
            "Review Count": review_count,
            "NOTHS URL": noths_url,
            "Feefo URL": feefo_url
        })

    except Exception as e:
        print(f"❌ Error processing {product_code}: {e}")

    time.sleep(DELAY_BETWEEN_PRODUCTS)

driver.quit()

# Save results to Excel
output_df = pd.DataFrame(results)
os.makedirs("data", exist_ok=True)
output_df.to_excel(OUTPUT_FILE, index=False)

print(f"\n✅ Saved metadata for {len(results)} products to {OUTPUT_FILE}")
