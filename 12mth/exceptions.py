import requests
from bs4 import BeautifulSoup
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# Read SKUs from input Excel file
input_file_path = 'input_skus.xlsx'  # Your file with SKUs in first column
df_input = pd.read_excel(input_file_path)

skus = df_input.iloc[:, 0].tolist()

# Base Feefo URL
feefo_base_url = "https://www.feefo.com/en-GB/reviews/notonthehighstreet-com/products/*?sku={sku}&displayFeedbackType=PRODUCT&timeFrame=ALL"

# List to store results
link_data = []

# Function to extract NOTHS URL from Feefo page
def extract_noths_link(sku):
    try:
        url = feefo_base_url.format(sku=sku)
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the "Visit Product Page" button by its id (as per Feefo HTML)
        product_link_tag = soup.find('a', {'id': 'product-info-visit-product-page-button'})

        noths_url = product_link_tag['href'] if product_link_tag else 'NOTHS link not found'

        print(f"✅ SKU {sku}: {noths_url}")
        return [sku, url, noths_url]

    except Exception as e:
        print(f"❌ SKU {sku}: Error - {e}")
        return [sku, url, 'Error']

# Use ThreadPoolExecutor for speed
with ThreadPoolExecutor(max_workers=10) as executor:
    for result in executor.map(extract_noths_link, skus):
        link_data.append(result)

# Save to Excel
df_output = pd.DataFrame(link_data, columns=["SKU", "Feefo URL", "NOTHS URL"])
output_file_path = 'sku_feefo_noths_links_output.xlsx'
df_output.to_excel(output_file_path, index=False)

print(f"\n✅ File saved: {output_file_path}")
