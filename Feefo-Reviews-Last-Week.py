import requests
import pandas as pd

API_TOKEN = "notonthehighstreet"  # Replace with your Feefo API token

# Base URL for Products Ratings API
url = "https://api.feefo.com/api/20/products/ratings?review_count=true&since_period=week&page_size=100&merchant_identifier=notonthehighstreet-com"

headers = {
    "Accept": "application/json",
    "Authorization": f"Token {API_TOKEN}"
}

# Initialize a list to store product data
all_products = []
page = 1
page_size = 1000  # You can set this up to 1000 (maximum allowed)

while True:
    # Add the page parameter to the URL to request the next page
    response = requests.get(url, headers=headers, params={"page": page, "page_size": page_size})

    if response.status_code == 200:
        data = response.json()

        # Extract product details
        products = data.get("products", [])

        # If no more products are found, stop the loop
        if not products:
            break

        # Append the products from the current page to the all_products list
        all_products.extend(products)

        # Move to the next page
        page += 1
    else:
        print(f"Error {response.status_code}: {response.text}")
        break

# If there is data, create a DataFrame and save to Excel
if all_products:
    df = pd.DataFrame(all_products)

    # Save to Excel
    df.to_excel("feefo_product_ratings_month_010425.xlsx", index=False)

    print("Data successfully saved to 'feefo_product_ratings_month_010425.xlsx'.")
else:
    print("No product data found.")
