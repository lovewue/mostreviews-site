import datetime
import requests
import gzip
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------

BASE = "https://www.notonthehighstreet.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendListBot/1.0; +https://trendlist.co.uk/)"
}

# script location
SCRIPT_DIR = Path(__file__).resolve().parent

# project root
PROJECT_ROOT = SCRIPT_DIR.parent

# output folder
OUTPUT_DIR = PROJECT_ROOT / "data" / "sitemaps"


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

def today_stamp():
    return datetime.date.today().strftime("%Y-%m-%d")


# ---------------------------------------------------
# Main
# ---------------------------------------------------

def main():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stamp = today_stamp()

    index_url = f"{BASE}/sitemap.xml"

    print(f"\n🌐 Fetching sitemap index")
    print(index_url)

    r = requests.get(index_url, headers=HEADERS, timeout=30)
    r.raise_for_status()

    # try gzipped first
    try:
        root = ET.parse(gzip.GzipFile(fileobj=BytesIO(r.content))).getroot()
    except OSError:
        root = ET.fromstring(r.content)

    locs = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")

    sitemap_urls = [loc.text.strip() for loc in locs if loc.text]

    print(f"\n📦 Found {len(sitemap_urls)} child sitemaps")

    downloaded = 0

    for url in sitemap_urls:

        name = url.split("/")[-1]

        out_name = f"{name.replace('.xml.gz','')}-{stamp}.xml.gz"

        out_path = OUTPUT_DIR / out_name

        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"↩️ Skipping {out_name}")
            continue

        print(f"\n🌐 Downloading")
        print(url)

        r = requests.get(url, headers=HEADERS, timeout=60)

        if r.status_code == 404:
            print("❌ 404 – skipping")
            continue

        r.raise_for_status()

        with open(out_path, "wb") as f:
            f.write(r.content)

        print(f"✅ Saved → {out_name}")

        downloaded += 1

    print("\n--------------------------------------")
    print(f"📦 Downloaded {downloaded} sitemaps")
    print(f"📁 Saved to: {OUTPUT_DIR}")
    print("--------------------------------------\n")


if __name__ == "__main__":
    main()
