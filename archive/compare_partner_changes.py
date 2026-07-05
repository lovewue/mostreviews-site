"""
Compare NOTHS partner changes between runs.

Purpose:
- Detect new sellers
- Detect sellers missing from latest sitemap-derived slug file
- Detect likely removals
- Detect confirmed removals
- Detect reappeared sellers

Inputs:
- data/source/unique_seller_slugs_previous.csv
- data/source/unique_seller_slugs_latest.csv
- data/archive/brands/brands_YYYY-MM-DD.csv   (previous brands snapshot)
- data/published/brands.csv                   (current brands snapshot)

Outputs:
- data/published/partner_changes.json
- data/published/partner_changes.csv
- data/archive/brands/partner_changes_YYYY-MM-DD_HH-MM.json
- data/archive/brands/partner_changes_YYYY-MM-DD_HH-MM.csv

Logic:
- Sitemap comparison is the trigger layer
- Brands comparison is the validation layer
- "confirmed_removed" means:
    missing from latest sitemap
    AND present in previous brands
    AND missing from current brands OR current brand is inactive / product_count == 0
- "reappeared" means:
    was missing before (or absent from previous sitemap/currently back)
    and now present again in latest sitemap/current brands
"""

import csv
import json
import shutil
import datetime
from pathlib import Path

import pandas as pd


# =========================
# PATHS
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

SOURCE_DIR = PROJECT_ROOT / "data" / "source"
PUBLISHED_DIR = PROJECT_ROOT / "data" / "published"
ARCHIVE_DIR = PROJECT_ROOT / "data" / "archive" / "brands"

PREVIOUS_SLUGS_CSV = SOURCE_DIR / "unique_seller_slugs_previous.csv"
CURRENT_SLUGS_CSV = SOURCE_DIR / "unique_seller_slugs_latest.csv"

CURRENT_BRANDS_CSV = PUBLISHED_DIR / "brands.csv"

PARTNER_CHANGES_JSON = PUBLISHED_DIR / "partner_changes.json"
PARTNER_CHANGES_CSV = PUBLISHED_DIR / "partner_changes.csv"


# =========================
# HELPERS
# =========================
def now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")


def today_date() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")


def to_bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def to_int(v) -> int:
    try:
        return int(float(str(v).strip() or "0"))
    except Exception:
        return 0


def clean_str(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def load_slug_set(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing slug CSV: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty:
        return set()

    slug_col = df.columns[0]
    slugs = (
        df[slug_col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.lower()
    )
    return set(s for s in slugs if s)


def load_brands_map(csv_path: Path) -> dict:
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing brands CSV: {csv_path}")

    df = pd.read_csv(csv_path, dtype=str).fillna("")
    out = {}

    for _, r in df.iterrows():
        slug = clean_str(r.get("slug", "")).lower()
        if not slug:
            continue

        out[slug] = {
            "slug": slug,
            "name": clean_str(r.get("name", "")) or slug,
            "active": to_bool(r.get("active", False)),
            "product_count": to_int(r.get("product_count", 0)),
            "brand_review_count": to_int(r.get("brand_review_count", 0)),
            "location": clean_str(r.get("location", "")),
            "order_volume_label": clean_str(r.get("order_volume_label", "")),
            "order_volume_numeric": to_int(r.get("order_volume_numeric", 0)),
            "tenure_label": clean_str(r.get("tenure_label", "")),
        }

    return out


def find_latest_previous_brands_csv() -> Path:
    """
    Finds the most recent brands_*.csv in archive.
    Assumes current run has not yet archived the new version,
    or that you want the latest archive as the 'previous' version.
    """
    if not ARCHIVE_DIR.exists():
        raise FileNotFoundError(f"Archive dir not found: {ARCHIVE_DIR}")

    files = sorted(ARCHIVE_DIR.glob("brands_*.csv"))
    if not files:
        raise FileNotFoundError("No archived brands CSV files found.")
    return files[-1]


def status_from_current_brand(brand_row: dict | None) -> str:
    if not brand_row:
        return "missing_in_current_brands"
    if not brand_row.get("active", False):
        return "inactive"
    if int(brand_row.get("product_count", 0) or 0) == 0:
        return "zero_products"
    return "active"


# =========================
# MAIN COMPARE
# =========================
def build_change_report():
    prev_brands_csv = find_latest_previous_brands_csv()

    prev_sitemap_slugs = load_slug_set(PREVIOUS_SLUGS_CSV)
    curr_sitemap_slugs = load_slug_set(CURRENT_SLUGS_CSV)

    prev_brands = load_brands_map(prev_brands_csv)
    curr_brands = load_brands_map(CURRENT_BRANDS_CSV)

    prev_brand_slugs = set(prev_brands.keys())
    curr_brand_slugs = set(curr_brands.keys())

    all_slugs = sorted(
        prev_sitemap_slugs
        | curr_sitemap_slugs
        | prev_brand_slugs
        | curr_brand_slugs
    )

    rows = []

    for slug in all_slugs:
        in_prev_sitemap = slug in prev_sitemap_slugs
        in_curr_sitemap = slug in curr_sitemap_slugs
        in_prev_brands = slug in prev_brand_slugs
        in_curr_brands = slug in curr_brand_slugs

        prev_brand = prev_brands.get(slug)
        curr_brand = curr_brands.get(slug)

        prev_name = prev_brand["name"] if prev_brand else slug
        curr_name = curr_brand["name"] if curr_brand else prev_name

        current_brand_state = status_from_current_brand(curr_brand)

        change_type = ""
        confidence = ""
        notes = ""

        # New
        if not in_prev_sitemap and in_curr_sitemap:
            change_type = "new"
            confidence = "high"
            notes = "Appears in current sitemap but not previous sitemap."

        # Missing from sitemap
        elif in_prev_sitemap and not in_curr_sitemap:
            change_type = "missing_from_sitemap"
            confidence = "medium"
            notes = "Present in previous sitemap but absent from current sitemap."

            # Validate against brands layer
            if in_prev_brands and (not in_curr_brands or current_brand_state in ("inactive", "zero_products", "missing_in_current_brands")):
                change_type = "confirmed_removed"
                confidence = "high"
                notes = (
                    "Missing from current sitemap and not live in current brands layer "
                    f"({current_brand_state})."
                )
            else:
                change_type = "removed_candidate"
                confidence = "medium"
                notes = (
                    "Missing from current sitemap, but current brands layer does not fully "
                    "confirm removal."
                )

        # Reappeared
        elif not in_prev_sitemap and in_curr_sitemap and in_prev_brands:
            change_type = "reappeared"
            confidence = "medium"
            notes = "Previously known brand appears again in current sitemap."

        # Present in both
        elif in_prev_sitemap and in_curr_sitemap:
            if not in_prev_brands and in_curr_brands:
                change_type = "new"
                confidence = "medium"
                notes = "Present in both sitemap runs but newly appears in current brands."
            elif in_prev_brands and in_curr_brands:
                # optionally detect reappeared from inactive → active
                prev_active = prev_brand.get("active", False) if prev_brand else False
                curr_active = curr_brand.get("active", False) if curr_brand else False
                prev_pc = prev_brand.get("product_count", 0) if prev_brand else 0
                curr_pc = curr_brand.get("product_count", 0) if curr_brand else 0

                if (not prev_active or prev_pc == 0) and (curr_active and curr_pc > 0):
                    change_type = "reappeared"
                    confidence = "medium"
                    notes = "Brand moved from inactive/zero-products to active."
                else:
                    continue
            else:
                continue

        else:
            # Exists only in brands history, not in sitemap either side
            if in_prev_brands and not in_curr_brands:
                change_type = "confirmed_removed"
                confidence = "medium"
                notes = "Present in previous brands snapshot but absent from current brands and sitemap."
            else:
                continue

        rows.append({
            "date": today_date(),
            "slug": slug,
            "name": curr_name,
            "change_type": change_type,
            "confidence": confidence,
            "in_previous_sitemap": in_prev_sitemap,
            "in_current_sitemap": in_curr_sitemap,
            "in_previous_brands": in_prev_brands,
            "in_current_brands": in_curr_brands,
            "current_brand_state": current_brand_state,
            "previous_product_count": prev_brand["product_count"] if prev_brand else 0,
            "current_product_count": curr_brand["product_count"] if curr_brand else 0,
            "previous_active": prev_brand["active"] if prev_brand else False,
            "current_active": curr_brand["active"] if curr_brand else False,
            "previous_order_volume_label": prev_brand["order_volume_label"] if prev_brand else "",
            "current_order_volume_label": curr_brand["order_volume_label"] if curr_brand else "",
            "previous_location": prev_brand["location"] if prev_brand else "",
            "current_location": curr_brand["location"] if curr_brand else "",
            "notes": notes,
        })

    return rows, prev_brands_csv


# =========================
# WRITE OUTPUTS
# =========================
def write_outputs(rows: list[dict], prev_brands_csv: Path):
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    stamp = now_stamp()

    summary = {
        "run_date": today_date(),
        "run_timestamp": stamp,
        "previous_brands_file": str(prev_brands_csv),
        "previous_sitemap_file": str(PREVIOUS_SLUGS_CSV),
        "current_sitemap_file": str(CURRENT_SLUGS_CSV),
        "current_brands_file": str(CURRENT_BRANDS_CSV),
        "counts": {},
        "changes": rows,
    }

    counts = {}
    for r in rows:
        counts[r["change_type"]] = counts.get(r["change_type"], 0) + 1
    summary["counts"] = counts

    # JSON
    with open(PARTNER_CHANGES_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    archive_json = ARCHIVE_DIR / f"partner_changes_{stamp}.json"
    shutil.copy2(PARTNER_CHANGES_JSON, archive_json)

    # CSV
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "date", "slug", "name", "change_type", "confidence",
            "in_previous_sitemap", "in_current_sitemap",
            "in_previous_brands", "in_current_brands",
            "current_brand_state",
            "previous_product_count", "current_product_count",
            "previous_active", "current_active",
            "previous_order_volume_label", "current_order_volume_label",
            "previous_location", "current_location",
            "notes",
        ])

    df = df.sort_values(by=["change_type", "slug"], ascending=[True, True])
    df.to_csv(PARTNER_CHANGES_CSV, index=False, quoting=csv.QUOTE_MINIMAL)

    archive_csv = ARCHIVE_DIR / f"partner_changes_{stamp}.csv"
    shutil.copy2(PARTNER_CHANGES_CSV, archive_csv)

    print(f"\n✅ Published JSON → {PARTNER_CHANGES_JSON}")
    print(f"✅ Published CSV  → {PARTNER_CHANGES_CSV}")
    print(f"🗄 Archived JSON  → {archive_json}")
    print(f"🗄 Archived CSV   → {archive_csv}")

    print("\nSummary:")
    for k, v in sorted(summary["counts"].items()):
        print(f"  {k}: {v}")


# =========================
# MAIN
# =========================
def main():
    rows, prev_brands_csv = build_change_report()
    write_outputs(rows, prev_brands_csv)


if __name__ == "__main__":
    main()
