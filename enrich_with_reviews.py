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
REVIEW_LOOKBACK_DAYS = 7
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

# Load product report
df = pd.read_excel(INPUT_FILE)

# Filter products with more than 1 review
df = df[df["review_count"] > 1]

results = []

for _, row in df.iterrows():
    product_code = row["Product Code"]
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

        # Seller name
        try:
            seller = driver.find_element(By.CSS_SELECTOR, 'a[href="#partner-module-id"]').text.strip()
        except:
            seller = ""

        # Product image URL
        try:
            img = driver.find_element(By.CSS_SELECTOR, "img").getAttribute("src")
        except:
            img = ""

        # All reviews + dates
        reviews = driver.find_elements(By.CSS_SELECTOR, '[data-aqa-id="customer-comment-container"]')
        dates = driver.find_elements(By.CSS_SELECTOR, '[data-aqa-id="feedback-purchased-date"]')

        for i in range(min(len(reviews), len(dates))):
            review_text = reviews[i].text.strip()
            date_text = dates[i].text.strip().replace("Date of purchase: ", "")

            try:
                purchase_date = datetime.strptime(date_text, "%d/%m/%Y")
                if purchase_date >= datetime.today() - timedelta(days=REVIEW_LOOKBACK_DAYS):
                    results.append({
                        "Product Code": product_code,
                        "Product Title": title,
                        "Seller": seller,
                        "Review Date": purchase_date.strftime("%Y-%m-%d"),
                        "Review Text": review_text,
                        "Product Image": img,
                        "NOTHS URL": noths_url,
                        "Feefo URL": feefo_url
                    })
            except:
                continue

    except Exception as e:
        print(f"❌ Error processing {product_code}: {e}")

    time.sleep(DELAY_BETWEEN_PRODUCTS)

driver.quit()

# Save to Excel
if results:
    output_df = pd.DataFrame(results)
    os.makedirs("data", exist_ok=True)
    output_df.to_excel(OUTPUT_FILE, index=False)
    print(f"✅ Saved enriched review data to {OUTPUT_FILE}")
else:
    print("⚠️ No recent reviews found to save.")
