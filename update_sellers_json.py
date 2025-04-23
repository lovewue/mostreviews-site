import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# --- Load sellers.json from data folder ---
data_path = Path("data/sellers.json")
with data_path.open("r", encoding="utf-8") as f:
    sellers = json.load(f)

# --- Scrape function to get updated review count ---
def fetch_review_count(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        h4 = soup.find("h4", class_="toga-storefront-intro__information")
        if h4:
            text = h4.get_text(separator=" ").strip()
            parts = [p.strip() for p in text.split("/")]
            review_part = [p for p in parts if "review" in p.lower()]
            if review_part:
                return f"{int(''.join(filter(str.isdigit, review_part[0]))):,}"
    except Exception as e:
        return f"ERROR: {e}"
    return "--"

# --- Update review counts ---
for seller in sellers:
    print(f"🔄 {seller['slug']}: ", end="")
    updated = fetch_review_count(seller["url"])
    seller["reviews"] = updated
    print(f"{updated}")

# --- Save updated file ---
updated_path = Path("data/sellers_updated.json")
with updated_path.open("w", encoding="utf-8") as f:
    json.dump(sellers, f, indent=2)

print("\n✅ Done! sellers_updated.json has been updated.")