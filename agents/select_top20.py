import json
from pathlib import Path

INPUT = Path("data/derived/monthly/2026-03/enriched_products.json")
OUTPUT = Path("agents/top_products_analysis/data/top20.json")

TOP_N = 20


def main():
    with open(INPUT, "r", encoding="utf-8") as f:
        products = json.load(f)

    # filter valid urls
    products = [
        p for p in products
        if p.get("product_url")
    ]

    # sort by monthly reviews
    products.sort(
        key=lambda x: x.get("review_count_month", 0),
        reverse=True
    )

    top20 = products[:TOP_N]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(top20, f, indent=2)

    print(f"Saved top {TOP_N} products")


if __name__ == "__main__":
    main()
