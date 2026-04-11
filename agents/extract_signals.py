import json
import re
from pathlib import Path

INPUT = Path("agents/top_products_analysis/data/scraped.json")
OUTPUT = Path("agents/top_products_analysis/data/signals.json")


def price_band(price):
    if not price:
        return None

    m = re.search(r"\d+\.?\d*", price)
    if not m:
        return None

    value = float(m.group())

    if value < 10:
        return "under_10"
    if value < 20:
        return "10_20"
    if value < 30:
        return "20_30"
    if value < 50:
        return "30_50"

    return "50_plus"


def analyse_title(title):
    if not title:
        return {}

    t = title.lower()

    return {
        "has_personalised": "personalised" in t,
        "has_gift": "gift" in t,
        "has_birthday": "birthday" in t,
        "has_mum": "mum" in t or "mom" in t,
        "has_for_her": "for her" in t,
        "word_count": len(title.split())
    }


def main():
    with open(INPUT, "r", encoding="utf-8") as f:
        products = json.load(f)

    output = []

    for p in products:
        signals = {
            "price_band": price_band(p.get("price")),
            **analyse_title(p.get("title"))
        }

        output.append({
            **p,
            "signals": signals
        })

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
