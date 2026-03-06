import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# This script:
# 1. Scans the data folder for files named like:
#       feefo_product_ratings_month_YYYYMMDD.xlsx
# 2. Builds a monthly JSON file for each one
# 3. Writes the output to:
#       data/monthly/YYYY-MM/top_products.json
# 4. Creates / updates:
#       data/monthly/index.json
#
# Important change from the old version:
# - NO cap is applied
# - All rows are kept in the monthly JSON
# - No manual input file / month / output folder editing needed
# -----------------------------------------------------------------------------

DATA_DIR = Path("data")
INPUT_PATTERN = "feefo_product_ratings_month_*.xlsx"
OUTPUT_ROOT = DATA_DIR / "monthly"
INDEX_FILE = OUTPUT_ROOT / "index.json"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_sku(raw) -> str:
    """
    Normalise product codes into a clean string SKU.

    Handles cases where Excel reads numeric product codes as floats,
    e.g. 1494342.0 -> "1494342"
    """
    try:
        return str(int(float(raw))).strip()
    except Exception:
        return str(raw).strip()


def normalise_headers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean column headers by removing tabs / extra whitespace.

    Example:
        'Product   Code' -> 'Product Code'
    """
    cols = {c: re.sub(r"\s+", " ", str(c)).strip() for c in df.columns}
    return df.rename(columns=cols)


def parse_month_from_filename(filepath: Path) -> str:
    """
    Extract YYYY-MM from a filename like:
        feefo_product_ratings_month_20260301.xlsx
    and convert it to the reporting month:
        2026-02

    The naming convention appears to use the first day of the following month
    for the file date, while the report itself is for the previous month.
    """
    match = re.search(r"feefo_product_ratings_month_(\d{8})\.xlsx$", filepath.name)
    if not match:
        raise ValueError(f"Filename does not match expected pattern: {filepath.name}")

    file_date = datetime.strptime(match.group(1), "%Y%m%d")

    # Move back one month
    year = file_date.year
    month = file_date.month - 1

    if month == 0:
        month = 12
        year -= 1

    return f"{year:04d}-{month:02d}"


def build_payload_from_xlsx(input_xlsx: Path, month: str) -> dict:
    """
    Read a monthly Feefo XLSX and convert it into the JSON payload used
    by the rest of the site pipeline.
    """
    df = pd.read_excel(input_xlsx)
    df = normalise_headers(df)

    required = {"Product Code", "rating", "review_count"}
    found = set(df.columns)

    if not required.issubset(found):
        raise ValueError(
            f"Missing required columns in {input_xlsx.name}. "
            f"Found: {list(df.columns)} | Required: {sorted(required)}"
        )

    # Create clean working columns
    df["sku"] = df["Product Code"].apply(clean_sku)
    df["review_count_month"] = (
        pd.to_numeric(df["review_count"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    df["rating_month"] = pd.to_numeric(df["rating"], errors="coerce")

    # Remove rows with blank / invalid SKU
    df = df[df["sku"].astype(str).str.strip() != ""]

    # Sort:
    # 1. review count descending
    # 2. rating descending
    # 3. sku ascending for stability
    df = df.sort_values(
        ["review_count_month", "rating_month", "sku"],
        ascending=[False, False, True]
    )

    payload = {
        "month": month,
        "generated_at": now_iso(),
        "source_file": input_xlsx.name,
        "item_count": int(len(df)),
        "items": [
            {
                "sku": r["sku"],
                "review_count_month": int(r["review_count_month"]),
                "rating_month": (
                    None if pd.isna(r["rating_month"]) else float(r["rating_month"])
                ),
            }
            for _, r in df.iterrows()
        ],
    }

    return payload


def write_json(filepath: Path, payload: dict) -> None:
    """Write a JSON payload to disk, creating folders if needed."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Main build logic
# -----------------------------------------------------------------------------
def main() -> None:
    """
    Build monthly JSON files for all matching Feefo monthly XLSX files,
    then write / refresh the monthly index.
    """
    input_files = sorted(DATA_DIR.glob(INPUT_PATTERN))

    if not input_files:
        print(f"❌ No input files found in: {DATA_DIR}")
        print(f"   Pattern: {INPUT_PATTERN}")
        return

    monthly_index = []
    built_count = 0
    failed_count = 0

    print(f"🔎 Found {len(input_files)} monthly XLSX file(s).")
    print()

    for input_xlsx in input_files:
        try:
            month = parse_month_from_filename(input_xlsx)
            out_json = OUTPUT_ROOT / month / "top_products.json"

            payload = build_payload_from_xlsx(input_xlsx, month)
            write_json(out_json, payload)

            item_count = payload.get("item_count", len(payload.get("items", [])))
            top_count = payload["items"][0]["review_count_month"] if payload["items"] else 0
            bottom_count = payload["items"][-1]["review_count_month"] if payload["items"] else 0

            monthly_index.append(
                {
                    "month": month,
                    "source_file": input_xlsx.name,
                    "json_file": f"data/monthly/{month}/top_products.json",
                    "item_count": item_count,
                    "top_review_count_month": top_count,
                    "bottom_review_count_month": bottom_count,
                    "generated_at": payload["generated_at"],
                }
            )

            built_count += 1

            print(f"✅ Built: {month}")
            print(f"   Source: {input_xlsx}")
            print(f"   Output: {out_json}")
            print(f"   Items: {item_count}")
            print(f"   Review count range: {top_count} → {bottom_count}")
            print()

        except Exception as e:
            failed_count += 1
            print(f"❌ Failed: {input_xlsx.name}")
            print(f"   Error: {e}")
            print()

    # Sort index newest first
    monthly_index = sorted(monthly_index, key=lambda x: x["month"], reverse=True)

    index_payload = {
        "generated_at": now_iso(),
        "month_count": len(monthly_index),
        "months": monthly_index,
    }

    write_json(INDEX_FILE, index_payload)

    print("--------------------------------------------------")
    print("Build complete")
    print("--------------------------------------------------")
    print(f"✅ Monthly JSON files built: {built_count}")
    print(f"❌ Monthly JSON files failed: {failed_count}")
    print(f"🗂️ Index written: {INDEX_FILE}")


if __name__ == "__main__":
    main()
