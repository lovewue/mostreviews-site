import json
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CSV_FILE = PROJECT_ROOT / "data" / "published" / "brands.csv"
JSON_FILE = PROJECT_ROOT / "data" / "published" / "brands.json"


def main():
    df = pd.read_csv(CSV_FILE)

    records = df.to_dict(orient="records")

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"✅ Wrote {len(records)} brands → {JSON_FILE}")


if __name__ == "__main__":
    main()
