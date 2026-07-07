from __future__ import annotations

from jinja2 import Environment, FileSystemLoader
from urllib.parse import urlparse, parse_qs, quote, unquote
import os
import re
import json
import shutil

# === Config ===
STATIC_PATH = "/docs/noths/static"
DATA_DIR = "data"
DOCS_DIR = "docs"

PRODUCT_IMAGES_DIR = "Product_Images"

# === AWIN / URL Helpers ===
NOTHS_HOSTS = {"www.notonthehighstreet.com", "notonthehighstreet.com"}


def normalize_product_url(u: str | None) -> str | None:
    if not u:
        return None

    if not isinstance(u, str):
        u = str(u)

    u = u.strip()
    if not u:
        return None

    # force https
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]

    # ensure www for NOTHS
    try:
        p = urlparse(u)
        host = (p.netloc or "").lower()
        if host == "notonthehighstreet.com":
            u = u.replace(
                "https://notonthehighstreet.com",
                "https://www.notonthehighstreet.com",
                1,
            )
    except Exception:
        pass

    # strip query/fragment
    u = u.split("?", 1)[0].split("#", 1)[0]
    return u


def build_awin(product_url: str) -> str:
    return (
        "https://www.awin1.com/cread.php?"
        "awinmid=18484&awinaffid=1018637&clickref=MostReviewed&ued="
        + quote(product_url, safe="")
    )


def validate_or_rebuild_awin(awin_url: str | None, product_url: str | None) -> str | None:
    """Return a good AWIN link if possible; otherwise return AWIN url (if any) or None."""
    product_url = normalize_product_url(product_url)
    if not product_url:
        return awin_url or None

    if awin_url:
        try:
            p = urlparse(awin_url.strip())
            if "awin1.com" in p.netloc and p.path.endswith("/cread.php"):
                qs = parse_qs(p.query)
                ued = qs.get("ued", [None])[0]
                if ued:
                    ued_decoded = normalize_product_url(unquote(ued))
                    if ued_decoded == product_url:
                        return awin_url  # OK
        except Exception:
            pass
        return build_awin(product_url)

    return build_awin(product_url)


def _extract_noths_url(record: dict) -> str | None:
    """Try to find a clean NOTHS product URL in the record."""
    candidates = [
        record.get("product_url"),
        record.get("url"),
        record.get("raw_product_url"),
    ]

    for u in candidates:
        u_norm = normalize_product_url(u)
        if not u_norm:
            continue
        try:
            host = urlparse(u_norm).netloc.lower()
        except Exception:
            continue
        if host in NOTHS_HOSTS and "/product/" in u_norm:
            return u_norm

    return None


def ensure_awin_primary_link(record: dict) -> dict:
    """
    Prefer a proper AWIN deeplink (with `ued=`) built from a NOTHS URL.
    If NOTHS URL exists → ensure record["awin"] and set record["product_url"]=awin.
    """
    noths_url = _extract_noths_url(record)
    record["raw_product_url"] = noths_url

    if noths_url:
        awin_link = validate_or_rebuild_awin(record.get("awin"), noths_url)
        record["awin"] = awin_link
        record["product_url"] = awin_link or noths_url
        return record

    # No NOTHS URL: only keep AWIN if it's already proper deeplink with ued=
    raw_awin = record.get("awin", "")
    awin = raw_awin.strip() if isinstance(raw_awin, str) else ""

    if awin:
        try:
            p = urlparse(awin)
            qs = parse_qs(p.query)
            if ("awin1.com" in p.netloc) and p.path.endswith("/cread.php") and qs.get("ued"):
                record["awin"] = awin
                record["product_url"] = awin
            else:
                record["awin"] = None
        except Exception:
            record["awin"] = None

    return record


# === Monthly + cache data ===
PRODUCTS_CACHE_PATH = os.path.join(DATA_DIR, "cache", "products_cache.json")
MONTHLY_DIR = os.path.join(DATA_DIR, "monthly")
MONTHLY_INDEX = os.path.join(MONTHLY_DIR, "index.json")

PRODUCTS_CACHE = []
if os.path.exists(PRODUCTS_CACHE_PATH):
    with open(PRODUCTS_CACHE_PATH, "r", encoding="utf-8") as f:
        PRODUCTS_CACHE = json.load(f)

# === Setup Jinja ===
env = Environment(loader=FileSystemLoader("templates"))


# --- Money / Price Helpers ---
def _coerce_price(val):
    if val is None:
        return None
    try:
        s = str(val).replace(",", "").strip()
        return float(s)
    except Exception:
        return None


def _money(value, currency="GBP"):
    p = _coerce_price(value)
    if p is None:
        return ""
    symbol = "£" if currency.upper() in ("GBP", "UKP") else ("€" if currency.upper() == "EUR" else "$")
    return f"{symbol}{p:,.2f}"


env.filters["money"] = _money


# ==========================
# MONTHLY HELPERS + RENDER
# ==========================
def _monthly_json_path(month: str) -> str:
    return os.path.join(MONTHLY_DIR, month, "top_products.json")


def _month_has_data(month: str) -> bool:
    # must have data/monthly/{month}/top_products.json
    return os.path.exists(_monthly_json_path(month))


def _month_label_is_valid(name: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}$", name))


def load_monthly_index() -> list[str]:
    """
    Return months like ['2026-01', '2025-12', ...] but ONLY months that
    actually have a top_products.json file (prevents broken links).
    """
    months: list[str] = []

    if os.path.exists(MONTHLY_INDEX):
        with open(MONTHLY_INDEX, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # index.json is an object like {"months": [{"month": "2026-04", ...}, ...]}
        # (as written by build_monthly_json.py), not a plain list of strings.
        if isinstance(raw, dict):
            entries = raw.get("months", [])
            months = [
                str(entry.get("month", "")).strip()
                for entry in entries
                if isinstance(entry, dict) and str(entry.get("month", "")).strip()
            ]
        elif isinstance(raw, list):
            # Fallback: support a plain list of month strings too, in case
            # index.json is ever written in that simpler format.
            months = [str(m).strip() for m in raw if str(m).strip()]
    else:
        # fallback: detect folders under data/monthly
        if os.path.exists(MONTHLY_DIR):
            for name in os.listdir(MONTHLY_DIR):
                if _month_label_is_valid(name) and os.path.isdir(os.path.join(MONTHLY_DIR, name)):
                    months.append(name)

    # Filter to only months that really have the JSON
    months = [m for m in months if _month_label_is_valid(m) and _month_has_data(m)]
    months = sorted(set(months), reverse=True)
    return months


def load_monthly_file(month: str) -> dict:
    path = _monthly_json_path(month)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_unavailable_skus(month: str) -> set[str]:
    unavailable_path = os.path.join(MONTHLY_DIR, month, "unavailable_skus.json")
    if not os.path.exists(unavailable_path):
        return set()
    try:
        with open(unavailable_path, "r", encoding="utf-8") as f:
            return set(str(x).strip() for x in json.load(f) if str(x).strip())
    except Exception:
        return set()


def _has_image(sku: str) -> bool:
    # your monthly image script saves SKU as .jpg
    return os.path.exists(os.path.join(PRODUCT_IMAGES_DIR, f"{sku}.jpg"))


def enrich_month_products(month: str) -> list[dict]:
    monthly = load_monthly_file(month)
    monthly_items = monthly.get("items", [])

    cache_by_sku = {str(p.get("sku", "")).strip(): p for p in PRODUCTS_CACHE if p.get("sku")}
    unavailable = _load_unavailable_skus(month)

    enriched: list[dict] = []
    for row in monthly_items:
        sku = str(row.get("sku", "")).strip()
        if not sku:
            continue

        # Drop if confirmed dead for this month
        if sku in unavailable:
            continue

        # Drop if we don't have an image (prevents broken tiles)
        if not _has_image(sku):
            continue

        meta = cache_by_sku.get(sku)
        if not meta:
            continue

        rec = {
            **meta,
            "review_count_month": int(row.get("review_count_month", 0)),
            "rating_month": row.get("rating_month"),
        }

        rec = ensure_awin_primary_link(rec)
        enriched.append(rec)

    # Sort by monthly reviews then name
    enriched.sort(key=lambda x: (-int(x.get("review_count_month", 0)), (x.get("name") or "").lower()))

    # ---- Top 250 + ties (AFTER filtering) ----
    TOP_N = 250
    if len(enriched) > TOP_N:
        cutoff = int(enriched[TOP_N - 1].get("review_count_month", 0))
        enriched = [p for p in enriched if int(p.get("review_count_month", 0)) >= cutoff]

    # Dense rank on monthly review count
    rank, last = 0, None
    for i, p in enumerate(enriched, start=1):
        count = int(p.get("review_count_month", 0))
        if count != last:
            rank = i
            last = count
        p["rank"] = rank

    return enriched


def render_monthly_products(month: str):
    products = enrich_month_products(month)
    months = load_monthly_index()
    monthly_meta = load_monthly_file(month)
    generated_at = monthly_meta.get("generated_at")

    template = env.get_template("noths/monthly/products.html")
    html = template.render(
        month=month,
        months=months,
        products=products,
        generated_at=generated_at,
        static_path=STATIC_PATH,
    )

    out_dir = os.path.join(DOCS_DIR, "noths", "monthly", month)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"🗓️ Rendered monthly products → {out_path} ({len(products)} products)", flush=True)


def render_monthly_index():
    months = load_monthly_index()
    if not months:
        print("⚠️ No valid months found under data/monthly. Skipping monthly index.", flush=True)
        return

    latest = months[0]

    template = env.get_template("noths/monthly/index.html")
    html = template.render(
        latest_month=latest,
        months=months,
        static_path=STATIC_PATH,
    )

    out_dir = os.path.join(DOCS_DIR, "noths", "monthly")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"🗓️ Rendered monthly landing → {out_path} (latest={latest})", flush=True)


def copy_static_assets():
    if os.path.exists("static"):
        shutil.copytree("static", f"{DOCS_DIR}/static", dirs_exist_ok=True)
        print("✅ Copied static assets", flush=True)

    for folder in ["Partner_Logo", "Seller_Logo"]:
        if os.path.exists(folder):
            shutil.copytree(folder, f"{DOCS_DIR}/{folder}", dirs_exist_ok=True)
            print(f"✅ Copied {folder}", flush=True)


def render_about_the_data_page():
    from datetime import datetime

    template = env.get_template("about-the-data.html")
    today_str = datetime.now().strftime("%d.%m.%Y")

    os.makedirs(DOCS_DIR, exist_ok=True)
    out_path = os.path.join(DOCS_DIR, "about-the-data.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.render(last_updated=today_str))

    print(f"📊 Rendered about-the-data.html (Last updated: {today_str})", flush=True)


# === Run Everything ===
if __name__ == "__main__":
    copy_static_assets()

    # Monthly pages
    print("➡️ Rendering monthly landing...", flush=True)
    render_monthly_index()

    months = load_monthly_index()
    print(f"➡️ Months found: {months}", flush=True)

    # Render ALL months (not just latest)
    for m in months:
        print(f"➡️ Rendering monthly products for {m}...", flush=True)
        render_monthly_products(m)

    render_about_the_data_page()
    # NOTE: Homepage, archive, top-products pages, about.html, and
    # sitemap.xml are all owned by scripts/render_site.py — run that after
    # this script. This file now only builds the /noths/ subpages and
    # about-the-data.html.

    print()
    print("🏁 render.py complete")
