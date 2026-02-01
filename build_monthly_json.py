import os
import re
import json
import pandas as pd
from datetime import datetime, timezone

INPUT_XLSX = "data/feefo_product_ratings_month_20260201.xlsx"
MONTH = "2026-01"  # adjust if needed
OUT_JSON = f"data/monthly/{MONTH}/top_products.json"
TOP_N = 250

def clean_sku(raw):
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def main():
    if not os.path.exists(INPUT_XLSX):
        print(f"❌ Input file not found: {INPUT_XLSX}")
        return

    df = pd.read_excel(INPUT_XLSX)

    # Accept either "Product Code" or "Product Code\t..." type headers
    # (sometimes Excel exports can include odd whitespace)
    cols = {c: re.sub(r"\s+", " ", str(c)).strip() for c in df.columns}
    df = df.rename(columns=cols)

    required = {"Product Code", "rating", "review_count"}
    if not required.issubset(set(df.columns)):
        print("❌ Missing required columns.")
        print("   Found columns:", list(df.columns))
        print("   Required:", sorted(required))
        return

    df["sku"] = df["Product Code"].apply(clean_sku)
    df["review_count_month"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0).astype(int)
    df["rating_month"] = pd.to_numeric(df["rating"], errors="coerce")

    # Sort by monthly count, then rating
    df = df.sort_values(["review_count_month", "rating_month"], ascending=[False, False]).head(TOP_N)

    payload = {
        "month": MONTH,
        "generated_at": now_iso(),
        "items": [
            {
                "sku": r["sku"],
                "review_count_month": int(r["review_count_month"]),
                "rating_month": (None if pd.isna(r["rating_month"]) else float(r["rating_month"])),
            }
            for _, r in df.iterrows()
        ]
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"✅ Wrote monthly JSON: {OUT_JSON}")
    print(f"   Items: {len(payload['items'])}")

if __name__ == "__main__":
    main()
