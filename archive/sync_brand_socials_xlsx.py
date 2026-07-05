from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

BRANDS_JSON = ROOT / "data" / "published" / "brands.json"
XLSX_FILE = ROOT / "data" / "source" / "brand_socials.xlsx"

COLUMNS = ["Name", "Slug", "Website", "Instagram", "TikTok", "Facebook"]


def load_brands():
    with open(BRANDS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Adjust this if your JSON is shaped differently
    brands = data if isinstance(data, list) else data.get("brands", [])

    rows = []
    for brand in brands:
        slug = (brand.get("slug") or "").strip()
        name = (brand.get("name") or "").strip()

        if slug and name:
            rows.append({
                "Name": name,
                "Slug": slug,
                "Website": "",
                "Instagram": "",
                "TikTok": "",
                "Facebook": "",
            })

    return rows


def main():
    new_df = pd.DataFrame(load_brands(), columns=COLUMNS)

    if XLSX_FILE.exists():
        existing_df = pd.read_excel(XLSX_FILE).fillna("")

        for col in COLUMNS:
            if col not in existing_df.columns:
                existing_df[col] = ""

        existing_df = existing_df[COLUMNS]

        existing_by_slug = {
            row["Slug"]: row
            for _, row in existing_df.iterrows()
            if str(row["Slug"]).strip()
        }

        merged_rows = []

        for _, row in new_df.iterrows():
            slug = row["Slug"]

            if slug in existing_by_slug:
                old = existing_by_slug[slug]
                merged_rows.append({
                    "Name": row["Name"],
                    "Slug": slug,
                    "Website": old.get("Website", ""),
                    "Instagram": old.get("Instagram", ""),
                    "TikTok": old.get("TikTok", ""),
                    "Facebook": old.get("Facebook", ""),
                })
            else:
                merged_rows.append(row.to_dict())

        final_df = pd.DataFrame(merged_rows, columns=COLUMNS)

    else:
        final_df = new_df

    final_df = final_df.sort_values("Name")

    XLSX_FILE.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_excel(XLSX_FILE, index=False)

    print(f"Saved {len(final_df)} brands to {XLSX_FILE}")


if __name__ == "__main__":
    main()
