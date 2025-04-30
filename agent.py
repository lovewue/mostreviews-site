import requests
import pandas as pd
import os
from datetime import datetime

# Load API token securely
API_TOKEN = os.getenv("FEEFO_API_TOKEN")

# Feefo API endpoint and query parameters
url = "https://api.feefo.com/api/20/products/ratings"
params = {
    "review_count": "true",
    "since_period": "month",
    "page_size": 1000,
    "merchant_identifier": "notonthehighstreet-com"
}

headers = {
    "Accept": "application/json",
    "Authorization": f"Token {API_TOKEN}"
}

# Collect product data
all_products = []
page = 1

while True:
    params["page"] = page
    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        products = data.get("products", [])
        if not products:
            break
        all_products.extend(products)
        page += 1
    else:
        print(f"❌ Error {response.status_code}: {response.text}")
        break

# Process and save to Excel
if all_products:
    df = pd.DataFrame(all_products)

    # ✅ Print actual column names for debugging
    print("Original columns:", df.columns.tolist())

    # ✅ Case-insensitive rename from 'sku' to 'Product Code'
    lower_cols = {col.lower(): col for col in df.columns}
    if "sku" in lower_cols:
        original_col = lower_cols["sku"]
        df.rename(columns={original_col: "Product Code"}, inplace=True)

    # ✅ Move 'Product Code' to front if it exists
    if "Product Code" in df.columns:
        columns = ["Product Code"] + [col for col in df.columns if col != "Product Code"]
        df = df[columns]

    # ✅ Optional: print new column order
    print("New column order:", df.columns.tolist())

    # Create output folder and file
    today = datetime.utcnow().strftime("%Y%m%d")
    os.makedirs("data", exist_ok=True)
    output_file = f"data/feefo_product_ratings_week_{today}.xlsx"
    df.to_excel(output_file, index=False)

    print(f"✅ Data saved to {output_file}")
else:
    print("⚠️ No product data found.")
