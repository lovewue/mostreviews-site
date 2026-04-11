import json
from pathlib import Path

INPUT = Path("agents/top_products_analysis/data/signals.json")
OUTPUT = Path("agents/top_products_analysis/data/insights.json")


def explain(p):
    s = p["signals"]

    reasons = []

    if s.get("has_personalised"):
        reasons.append("Personalisation increases relevance")

    if s.get("has_birthday"):
        reasons.append("Clear birthday occasion")

    if s.get("price_band") == "10_20":
        reasons.append("Strong impulse gift price band")

    if s.get("has_gift"):
        reasons.append("Explicit gifting positioning")

    return reasons


def main():
    with open(INPUT, "r", encoding="utf-8") as f:
        products = json.load(f)

    output = []

    for p in products:
        output.append({
            **p,
            "insight": explain(p)
        })

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
