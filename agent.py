# agent.py (save file to /data)
import os
from datetime import datetime
import requests
import pandas as pd

API_TOKEN = os.getenv("FEEFO_API_TOKEN")

url = "https://api.feefo.com/api/20/products/ratings"
params = {
    "review_count": "true",
    "since_period": "week",
    "page_size": 1000,
    "merchant_identifier": "notonthehighstreet-com"
}

headers = {
    "Accept": "application/json",
    "Authorization": f"Token {API_TOKEN}"
}

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
        print(f"Error {response.status_code}: {response.text}")
        break

if all_products:
    df = pd.DataFrame(all_products)
    today = datetime.utcnow().strftime("%Y%m%d")
    os.makedirs("data", exist_ok=True)
    output_file = f"data/feefo_product_ratings_week_{today}.xlsx"
    df.to_excel(output_file, index=False)
    print(f"✅ Data saved to {output_file}")
else:
    print("⚠️ No product data found.")
