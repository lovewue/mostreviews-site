import json
import time
import random
import requests
from bs4 import BeautifulSoup
from pathlib import Path

INPUT = Path("agents/top_products_analysis/data/top20.json")
OUTPUT = Path("agents/top_products_analysis/data/scraped.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def scrape_product(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        title = soup.find("h1")
        title = title.get_text(strip=True) if title else None

        price = soup.select_one('[data-testid="price"]')
        if price:
            price = price.get_text(strip=True)

        description = soup.select_one('[data-testid="description"]')
        if description:
            description = description.get_text(" ", strip=True)

        seller = soup.select_one('[data-testid="seller-name"]')
        if seller:
            seller = seller.get_text(strip=True)

        image = soup.select_one("img")
        image = image["src"] if image else None

        return {
            "title": title,
            "price": price,
            "description": description,
            "seller": seller,
            "image": image
        }

    except Exception as e:
        print("Error:", e)
        return {}


def main():
    with open(INPUT, "r", encoding="utf-8") as f:
        products = json.load(f)

    output = []

    for p in products:
        url = p["product_url"]
        print("Scraping:", url)

        data = scrape_product(url)

        output.append({
            **p,
            **data
        })

        time.sleep(random.uniform(1, 2))

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
