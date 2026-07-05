import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import time

# --- Load sellers.json ---
data_path = Path("data/sellers.json")
with data_path.open("r", encoding="utf-8") as f:
    sellers = json.load(f)

# --- Parse review count as integer ---
def parse_review_count(s):
    try:
        return int(s.replace(",", ""))
    except:
        return 0

# --- Sort and take top 100 ---
top_100 = sorted(sellers, key=lambda s: parse_review_count(s["reviews"]), reverse=True)[:100]
top_slugs = {s["slug"] for s in top_100}

# --- Setup request session with headers ---
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

# --- Scrape function ---
def fetch_review_count(url):
    try:
        response = session.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        h4 = soup.find("h4", class_="toga-storefront-intro__information")
        if h4:
            parts = h4.get_text(separator=" ").split("/")
            for part in parts:
                if "review" in part.lower():
                    digits = ''.join(filter(str.isdigit, part))
                    return f"{int(digits):,}" if digits else "--"
    except Exception as e:
        print(f"❌ Error for {url}: {e}")
    return "--"

# --- Update top 100 sellers only ---
for seller in sellers:
    if seller["slug"] not in top_slugs:
        continue
    print(f"🔄 {seller['slug']}: ", end="")
    count = fetch_review_count(seller["url"])
    seller["reviews"] = count
    print(count)
    time.sleep(1)  # polite delay

# --- Save updated full list ---
output_path = Path("data/sellers_updated_top100.json")
with output_path.open("w", encoding="utf-8") as f:
    json.dump(sellers, f, indent=2)

print("\n✅ Done! Top 100 sellers updated in sellers_updated_top100.json.")
