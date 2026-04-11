import json
import re
import time
from pathlib import Path
from collections import Counter, defaultdict

import requests
from bs4 import BeautifulSoup


class Tools:

    def __init__(self, month):
        self.month = month
        self.base = Path(__file__).resolve().parent.parent

        self.month_file = (
            self.base
            / "data"
            / "derived"
            / "monthly"
            / month
            / "enriched_products.json"
        )

        self.top100_file = (
            self.base
            / "data"
            / "derived"
            / "leaderboards"
            / "top_products_last_12_months.json"
        )

        self._load()

    # -------------------------------------------------
    # LOAD DATA
    # -------------------------------------------------

    def _load(self):

        with open(self.month_file, "r", encoding="utf-8") as f:
            self.month_data = json.load(f)

        with open(self.top100_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            self.top100 = data.get("items", [])
        else:
            self.top100 = data

    # -------------------------------------------------
    # DATA ACCESS
    # -------------------------------------------------

    def get_top20_month(self):
        return sorted(
            self.month_data,
            key=lambda x: x.get("review_count_month", 0),
            reverse=True
        )[:20]

    def get_top100_last12(self):
        return self.top100[:100]

    def get_product(self, sku):
        sku = str(sku)

        for p in self.month_data:
            if str(p.get("sku")) == sku:
                return p

        for p in self.top100:
            if str(p.get("sku")) == sku:
                return p

        return None

    # -------------------------------------------------
    # LISTING SCRAPER
    # -------------------------------------------------

    def get_listing(self, sku):

        product = self.get_product(sku)

        if not product:
            return None

        url = product.get("product_url")

        if not url:
            return None

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        start = time.time()
        print(f"SCRAPING: {sku} -> {url}")

        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()

            html = r.text
            soup = BeautifulSoup(html, "html.parser")

        except Exception as e:
            print(f"SCRAPE FAILED: {sku} -> {e}")
            return None

        elapsed = round(time.time() - start, 2)
        print(f"SCRAPE OK: {sku} ({elapsed}s)")

        title = self._text(soup.select_one("h1"))

        description = self._text(
            soup.select_one("[data-testid='product-description']")
        )

        if not description:
            description = self._text(
                soup.select_one("meta[name='description']")
            )

        price = self._text(
            soup.select_one("[data-testid='product-price']")
        )

        if not price:
            price = self._text(
                soup.select_one("[data-testid='price']")
            )

        # Try to isolate actual product gallery images rather than every image on page
        images = soup.select("[data-testid='product-gallery'] img")

        if not images:
            images = soup.select(".product-gallery img")

        image_urls = set()

        for img in images:
            src = img.get("src") or img.get("data-src")
            if src:
                image_urls.add(src)

        image_count = len(image_urls)

        return {
            "url": url,
            "title": title,
            "description_length": len(description),
            "price": price,
            "image_count": image_count,
            "title_word_count": len(title.split()) if title else 0,
            "has_personalisation": "personalised" in title.lower() if title else False,
            "contains_birthday": "birthday" in title.lower() if title else False,
            "contains_family": "family" in title.lower() if title else False,
        }

    # -------------------------------------------------
    # COMPARISONS
    # -------------------------------------------------

    def compare(self, month, group_by):

        top20 = self.get_top20_month()
        top100 = self.get_top100_last12()

        return {
            "top20": self._group(top20, group_by),
            "top100": self._group(top100, group_by),
        }

    def aggregate(self, set_name, month, group_by):

        if set_name == "top20":
            data = self.get_top20_month()
        else:
            data = self.get_top100_last12()

        return self._group(data, group_by)

    def _group(self, data, group_by):

        counts = defaultdict(int)

        for p in data:

            if group_by == "personalised":
                key = "personalised" in p["name"].lower()

            elif group_by == "seller":
                key = p.get("seller_slug")

            elif group_by == "available":
                key = p.get("available")

            elif group_by == "rating_band":
                r = p.get("rating_month") or p.get("rating")
                key = int(r) if r else "unknown"

            elif group_by == "review_band":
                r = p.get("review_count_month") or p.get("reviews")
                key = self._review_band(r)

            elif group_by == "occasion":
                key = self._occasion(p["name"])

            else:
                key = "unknown"

            counts[key] += 1

        return dict(counts)

    # -------------------------------------------------
    # TITLE ANALYSIS
    # -------------------------------------------------

    def title_terms(self, set_name, month):

        if set_name == "top20":
            data = self.get_top20_month()
        else:
            data = self.get_top100_last12()

        words = Counter()

        for p in data:

            tokens = re.findall(r"\w+", p["name"].lower())

            for t in tokens:
                if len(t) > 3:
                    words[t] += 1

        return dict(words.most_common(20))

    # -------------------------------------------------
    # HELPERS
    # -------------------------------------------------

    def _text(self, el):
        if not el:
            return ""

        if hasattr(el, "get_text"):
            return el.get_text(strip=True)

        content = el.get("content")
        return content.strip() if content else ""

    def _review_band(self, r):

        if not r:
            return "0"

        if r >= 20:
            return "20+"
        if r >= 10:
            return "10+"
        if r >= 5:
            return "5+"

        return "1-4"

    def _occasion(self, name):

        name = name.lower()

        if "birthday" in name:
            return "birthday"

        if "mother" in name or "mum" in name:
            return "mother"

        if "dad" in name:
            return "dad"

        if "wedding" in name:
            return "wedding"

        return "other"
