import os
import re
import json
import pandas as pd
from datetime import datetime, timezone

DATA_DIR = "data"
MONTHLY_DIR = os.path.join(DATA_DIR, "monthly")
TOP_N = 250

# Matches: feefo_product_ratings_month_20250501.xlsx
PAT = re.compile(r"^feefo_product_ratings_month_(\d{4})(\d{2})(\d{2})\.xlsx$", re.I)

REQUIRED_COLS = {"Product Code", "rating", "review_count"}


def clean_sku(raw):
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # collapse weird whitespace
    cols = {c: re.sub(r"\s+", " ", str(c)).strip() for c in df.columns}
    return df.rename(columns=cols)


def build_month_payload(xlsx_path: str, month: str) -> dict:
    df = pd.read_excel(xlsx_path)
    df = normalize_columns(df)

    if not REQUIRED_COLS.issubset(set(df.columns)):
        raise ValueError(
            f"Missing required columns in {xlsx_path}\n"
            f"Found: {list(df.columns)}\n"
            f"Required: {sorted(REQUIRED_COLS)}"
        )

    df["sku"] = df["Product Code"].apply(clean_sku)
    df["review_count_month"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0).astype(int)
    df["rating_month"] = pd.to_numeric(df["rating"], errors="coerce")

    # Sort by monthly reviews desc, then rating desc
    df = df.sort_values(["review_count_month", "rating_month"], ascending=[False, False])

    # --- Top N + ties ---
    if len(df) > TOP_N:
        cutoff = int(df.iloc[TOP_N - 1]["review_count_month"])
        df = df[df["review_count_month"] >= cutoff]

    items = []
    for _, r in df.iterrows():
        rating_val = None
        if not pd.isna(r["rating_month"]):
            try:
                rating_val = float(r["rating_month"])
            except Exception:
                rating_val = None

        items.append({
            "sku": r["sku"],
            "review_count_month": int(r["review_count_month"]),
            "rating_month": rating_val,
        })

    return {
        "month": month,
        "source_file": os.path.basename(xlsx_path),
        "generated_at": now_iso(),
        "items": items,
    }


def main():
    if not os.path.exists(DATA_DIR):
        print(f"❌ Missing folder: {DATA_DIR}")
        return

    os.makedirs(MONTHLY_DIR, exist_ok=True)

    month_files = []
    for fname in os.listdir(DATA_DIR):
        m = PAT.match(fname)
        if not m:
            continue
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        month = f"{yyyy}-{mm}"
        month_files.append((month, os.path.join(DATA_DIR, fname)))

    if not month_files:
        print("⚠️ No monthly XLSX files found matching feefo_product_ratings_month_YYYYMMDD.xlsx")
        return

    # newest first
    month_files.sort(key=lambda x: x[0], reverse=True)

    months_written = []
    for month, xlsx_path in month_files:
        out_dir = os.path.join(MONTHLY_DIR, month)
        out_path = os.path.join(out_dir, "top_products.json")
        os.makedirs(out_dir, exist_ok=True)

        try:
            payload = build_month_payload(xlsx_path, month)
        except Exception as e:
            print(f"❌ {month}: failed to build from {xlsx_path}\n   {e}")
            continue

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        months_written.append(month)
        print(f"✅ Wrote {out_path} ({len(payload['items'])} items)")

    # write index.json (newest -> oldest)
    index_path = os.path.join(MONTHLY_DIR, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(months_written, f, indent=2)

    print(f"\n🗓️ Updated monthly index: {index_path} ({len(months_written)} months)")


if __name__ == "__main__":
    main()
