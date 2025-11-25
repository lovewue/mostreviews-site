from jinja2 import Environment, FileSystemLoader
from urllib.parse import urlparse, parse_qs, quote, unquote
import os
import json
import shutil
from collections import defaultdict
import urllib.parse

# === Config ===
STATIC_PATH = "/docs/noths/static"
DATA_DIR = "data"
DOCS_DIR = "docs"

# === AWIN / URL Helpers ===

NOTHS_HOSTS = {"www.notonthehighstreet.com", "notonthehighstreet.com"}


def normalize_product_url(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip()
    if not u:
        return None
    # force https
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    # ensure www
    try:
        p = urlparse(u)
        if p.netloc == "notonthehighstreet.com":
            u = u.replace("https://notonthehighstreet.com", "https://www.notonthehighstreet.com", 1)
    except Exception:
        pass
    # strip query/fragment
    u = u.split("?", 1)[0].split("#", 1)[0]
    return u


def build_awin(product_url: str) -> str:
    return (
        "https://www.awin1.com/cread.php?"
        "awinmid=18484&awinaffid=1018637&clickref=MostReviewed&ued=" +
        quote(product_url, safe="")
    )


def validate_or_rebuild_awin(awin_url: str | None, product_url: str | None) -> str | None:
    """Return a good AWIN link if possible; otherwise return normalized product_url."""
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
                        return awin_url  # OK as-is
        except Exception:
            pass
        # Mismatch or parse fail → rebuild
        return build_awin(product_url)

    # No AWIN provided → build one
    return build_awin(product_url)


def _extract_noths_url(record: dict) -> str | None:
    """
    Try to find a clean NOTHS product URL in the record.
    Only trust URLs that clearly point at notonthehighstreet.com.
    """
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
        if host in NOTHS_HOSTS:
            return u_norm

    return None


def ensure_awin_primary_link(record: dict) -> dict:
    """
    Prefer a proper AWIN deeplink (with `ued=`) built from a NOTHS URL.
    If we can't find a NOTHS URL, only trust existing AWIN links
    that already have a `ued` parameter.
    """
    # 1) Find a trustworthy NOTHS URL
    noths_url = _extract_noths_url(record)
    record["raw_product_url"] = noths_url

    # 2) If we have a NOTHS URL, build/validate AWIN from that
    if noths_url:
        awin_link = validate_or_rebuild_awin(record.get("awin"), noths_url)
        record["awin"] = awin_link
        # Product URL becomes AWIN deeplink if we got one, otherwise fall back to NOTHS
        record["product_url"] = awin_link or noths_url
        return record

    # 3) No NOTHS URL: only use AWIN if it's already a proper deeplink (has ued=)
    awin = (record.get("awin") or "").strip()
    if awin:
        try:
            p = urlparse(awin)
            qs = parse_qs(p.query)
            if "awin1.com" in p.netloc and qs.get("ued"):
                record["product_url"] = awin
        except Exception:
            pass

    return record


# === Load shared data once ===
with open(os.path.join(DATA_DIR, "partners_merged.json"), "r", encoding="utf-8") as f:
    ALL_PARTNERS = json.load(f)

with open(os.path.join(DATA_DIR, "top_products_last_12_months.json"), "r", encoding="utf-8") as f:
    TOP_PRODUCTS_12M = json.load(f)

# Make sure every product in the core dataset uses AWIN as the primary URL where possible
TOP_PRODUCTS_12M = [ensure_awin_primary_link(p) for p in TOP_PRODUCTS_12M]

# === Setup Jinja ===
env = Environment(loader=FileSystemLoader("templates"))


# --- Money / Price Helpers ---
def _coerce_price(val):
    """Convert a raw price value (string, int, float) into a float or None."""
    if val is None:
        return None
    try:
        s = str(val).replace(",", "").strip()
        return float(s)
    except Exception:
        return None


def _money(value, currency="GBP"):
    """Format a number into a currency string (default £)."""
    p = _coerce_price(value)
    if p is None:
        return ""
    symbol = "£" if currency.upper() in ("GBP", "UKP") else (
        "€" if currency.upper() == "EUR" else "$"
    )
    return f"{symbol}{p:,.2f}"


# Register Jinja filter for displaying prices nicely
env.filters["money"] = _money


# === Logo helper ===
def find_logo_url(slug: str) -> str | None:
    for logo_dir in ["Partner_Logo", "Seller_Logo"]:
        for ext in ("jpg", "jpeg", "png", "webp", "svg"):
            local_path = os.path.join(logo_dir, f"{slug}.{ext}")
            if os.path.exists(local_path):
                return f"/{logo_dir}/{slug}.{ext}"
    return None


# === NOTHS index ===
def render_noths_index():
    import random

    partner_lookup = {p["slug"]: p for p in ALL_PARTNERS if p.get("active", True)}

    # --- Review totals per partner ---
    review_totals = {}
    for p in TOP_PRODUCTS_12M:
        if not p.get("available", True):
            continue
        slug = (p.get("seller_slug") or "").lower().strip()
        if slug and slug in partner_lookup:
            review_totals[slug] = review_totals.get(slug, 0) + int(p.get("review_count", 0))

    top_partners = sorted(
        [{"slug": slug, "name": partner_lookup[slug]["name"], "total_reviews": count}
         for slug, count in review_totals.items()],
        key=lambda x: x["total_reviews"],
        reverse=True
    )[:3]

    # --- New joiners in 2025 ---
    partners_2025 = [
        p for p in ALL_PARTNERS
        if p.get("since", "").endswith("2025") and p.get("active", True)
    ]
    partners_2025 = sorted(
        partners_2025,
        key=lambda x: int(str(x.get("review_count", 0)).replace(",", "")),
        reverse=True
    )[:3]

    # --- Partners with most products ---
    partners_with_counts = []
    for p in ALL_PARTNERS:
        if not p.get("active", True):
            continue
        try:
            count = int(str(p.get("product_count", 0)).replace(",", ""))
        except:
            count = 0
        partners_with_counts.append({
            "slug": p["slug"],
            "name": p["name"],
            "product_count": count
        })

    top_product_partners = sorted(
        partners_with_counts,
        key=lambda x: x["product_count"],
        reverse=True
    )[:3]

    # --- Most Reviewed Products (true top 3) ---
    top_products_sorted = sorted(
        [p for p in TOP_PRODUCTS_12M if p.get("available", True)],
        key=lambda x: int(x.get("review_count", 0)),
        reverse=True
    )[:3]
    top_products_sample = top_products_sorted

    # --- Louise Thompson random sample ---
    lt_products_sample = []
    lt_path = os.path.join(DATA_DIR, "christmas_louise_thompson.json")
    if os.path.exists(lt_path):
        with open(lt_path, "r", encoding="utf-8") as f:
            lt_data = json.load(f)
            # NOTE: these items may not yet be enriched; used just for sample
            lt_products_sample = random.sample(lt_data, k=min(3, len(lt_data)))

    # --- Christmas Catalogue random sample ---
    top_christmas_catalogue_sample = []
    catalogue_path = os.path.join(DATA_DIR, "christmas_catalogue_products.json")
    if os.path.exists(catalogue_path):
        with open(catalogue_path, "r", encoding="utf-8") as f:
            top_christmas_catalogue = json.load(f)
            top_christmas_catalogue_sample = random.sample(
                top_christmas_catalogue, k=min(3, len(top_christmas_catalogue))
            )
    else:
        top_christmas_catalogue = []

    # --- Top Christmas products (true top 3 by reviews) ---
    with open(os.path.join(DATA_DIR, "top_products_christmas.json"), "r", encoding="utf-8") as f:
        christmas_products = json.load(f)
    full_by_sku = {str(p.get("sku")): p for p in TOP_PRODUCTS_12M}
    enriched_christmas = []
    for item in christmas_products:
        sku = str(item.get("sku"))
        base = full_by_sku.get(sku, {})
        try:
            review_count = int(str(base.get("review_count", 0)).replace(",", ""))
        except:
            review_count = 0
        enriched_christmas.append({
            "sku": sku,
            "name": item.get("name") or base.get("name", ""),
            "review_count": review_count,
        })
    top_christmas_products = sorted(
        enriched_christmas,
        key=lambda x: x["review_count"],
        reverse=True
    )[:3]

    # --- Load all-time top products (for homepage card images) ---
    all_time_path = os.path.join(DATA_DIR, "top_100_all_time.json")
    top_all_time = []
    if os.path.exists(all_time_path):
        with open(all_time_path, "r", encoding="utf-8") as f:
            top_all_time = json.load(f)
        top_all_time = top_all_time[:6]

    # --- A, middle, Z logos ---
    active_partners = [p for p in ALL_PARTNERS if p.get("active", True)]
    partners_sorted = sorted(active_partners, key=lambda p: p.get("name", "").lower())
    az_partners = []
    a_partner = next((p for p in partners_sorted if p.get("name", "").upper().startswith("A")), None)
    if a_partner:
        az_partners.append(a_partner)
    if partners_sorted:
        az_partners.append(partners_sorted[len(partners_sorted) // 2])
    z_partner = next((p for p in reversed(partners_sorted) if p.get("name", "").upper().startswith("Z")), None)
    if z_partner:
        az_partners.append(z_partner)

    # --- Render ---
    template = env.get_template("noths/index.html")
    html = template.render(
        title="NOTHS Partners and Products",
        static_path=STATIC_PATH,
        lt_products_sample=lt_products_sample,
        top_products_sample=top_products_sample,
        top_partners=top_partners,
        partners_2025=partners_2025,
        top_product_partners=top_product_partners,
        top_christmas_products=top_christmas_products,
        az_partners=az_partners,
        top_christmas_catalogue=top_christmas_catalogue_sample,
        top_all_time=top_all_time,
    )

    os.makedirs(f"{DOCS_DIR}/noths", exist_ok=True)
    with open(f"{DOCS_DIR}/noths/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("✅ Rendered NOTHS index")


# === Copy static assets ===
def copy_static_assets():
    if os.path.exists("static"):
        shutil.copytree("static", f"{DOCS_DIR}/static", dirs_exist_ok=True)
        print("✅ Copied static assets")
    for folder in ["Partner_Logo", "Seller_Logo"]:
        if os.path.exists(folder):
            shutil.copytree(folder, f"{DOCS_DIR}/{folder}", dirs_exist_ok=True)
            print(f"✅ Copied {folder}")


# === Partner pages ===
def render_partner_pages():
    products_by_partner = defaultdict(list)
    for p in TOP_PRODUCTS_12M:
        slug = (p.get("seller_slug") or "").lower().strip()
        if slug:
            products_by_partner[slug].append(p)

    template = env.get_template("noths/partners/partner.html")
    logo_cache = {}
    print("📦 Rendering partner pages...")

    expected_paths = set()
    count = 0
    skipped = 0

    for partner in ALL_PARTNERS:
        slug = partner.get("slug", "").lower().strip()
        active = partner.get("active", True)

        if not slug:
            print(f"⚠️ Skipping partner with no slug: {partner}")
            continue

        if not active:
            skipped += 1
            print(f"⏭️ Skipped inactive partner: {slug}")
            continue

        top_products = sorted(
            [p for p in products_by_partner.get(slug, []) if p.get("available", True)],
            key=lambda p: p.get("review_count", 0),
            reverse=True,
        )

        if slug not in logo_cache:
            logo_cache[slug] = find_logo_url(slug)
        partner["logo"] = logo_cache[slug]

        first_letter = slug[0]
        output_dir = os.path.join(DOCS_DIR, "noths", "partners", first_letter)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{slug}.html")

        expected_paths.add(os.path.normpath(output_path))

        html = template.render(
            partner=partner,
            top_products=top_products,
            static_path=STATIC_PATH,
        )
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        count += 1
        if count <= 10 or count % 500 == 0:
            print(f"  ✅ Wrote {output_path}")

    # --- Cleanup inactive pages ---
    import time

    def safe_remove(path, retries=3, delay=0.5):
        """Try to remove a file with retries for Windows lock issues."""
        for attempt in range(retries):
            try:
                os.remove(path)
                return True
            except PermissionError:
                if attempt < retries - 1:
                    time.sleep(delay)
                else:
                    print(f"⚠️ Could not delete locked file: {path}")
                    return False
        return False

    base_dir = os.path.join(DOCS_DIR, "noths", "partners")
    removed = 0
    for root, _dirs, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".html"):
                full_path = os.path.normpath(os.path.join(root, file))
                if full_path not in expected_paths:
                    if safe_remove(full_path):
                        removed += 1

    print(f"🧹 Removed {removed} inactive partner pages")
    print(f"✅ Rendered {count} active partner pages (skipped {skipped})")


# === Partner index A–Z ===
def render_partner_index():
    partners = [p for p in ALL_PARTNERS if p.get("active", True)]
    grouped = defaultdict(list)
    for p in partners:
        name = str(p.get("name", "")).strip()
        slug = str(p.get("slug", "")).strip().lower()
        if not name or not slug:
            continue
        first_letter = name[0].upper()
        if not first_letter.isalpha():
            first_letter = "#"
        grouped[first_letter].append(p)

    sorted_grouped = {
        letter: sorted(group, key=lambda p: str(p.get("name", "")).lower())
        for letter, group in sorted(grouped.items())
    }

    template = env.get_template("noths/partners/index.html")
    os.makedirs(f"{DOCS_DIR}/noths/partners", exist_ok=True)
    out_path = f"{DOCS_DIR}/noths/partners/index.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.render(
            letters=sorted(sorted_grouped.keys()),
            partners_by_letter=sorted_grouped,
            static_path=STATIC_PATH
        ))
    print("📇 Rendered partners/index.html")


# === Partner by year ===
def render_partner_by_year():
    partners = [p for p in ALL_PARTNERS if p.get("active", True)]
    grouped = defaultdict(list)

    # Group partners by join year
    for p in partners:
        since_raw = str(p.get("since", "")).strip()
        year = since_raw[-4:] if since_raw[-4:].isdigit() else "Unknown"
        grouped[year].append(p)

    # Sort years (descending) and partners alphabetically
    sorted_grouped = {
        year: sorted(group, key=lambda p: p["name"].lower())
        for year, group in sorted(grouped.items(), reverse=True)
    }

    total_partners = sum(len(group) for group in sorted_grouped.values())

    template = env.get_template("noths/partners/by-year.html")
    os.makedirs(f"{DOCS_DIR}/noths/partners", exist_ok=True)
    out_path = f"{DOCS_DIR}/noths/partners/by-year.html"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            template.render(
                partners_by_year=sorted_grouped,
                total_partners=total_partners,
                static_path=STATIC_PATH,
            )
        )

    print(f"📅 Rendered partners/by-year.html — {total_partners:,} total partners")


# === Partner most reviews ===
def render_partner_most_reviews_grouped():
    active_partners = [p for p in ALL_PARTNERS if p.get("active", True)]
    for p in active_partners:
        try:
            p["review_count"] = int(str(p.get("review_count", 0)).replace(",", ""))
        except:
            p["review_count"] = 0

    review_bands = [30000, 20000, 10000, 5000, 2500, 1000]
    partners_by_band = {band: [] for band in review_bands}

    for partner in active_partners:
        for band in review_bands:
            if partner["review_count"] >= band:
                partners_by_band[band].append(partner)
                break

    for band in review_bands:
        partners_by_band[band].sort(key=lambda p: p["name"].lower())

    template = env.get_template("noths/partners/partner-most-reviews.html")
    os.makedirs(f"{DOCS_DIR}/noths/partners", exist_ok=True)
    with open(f"{DOCS_DIR}/noths/partners/partner-most-reviews.html", "w", encoding="utf-8") as f:
        f.write(template.render(bands=review_bands, partners_by_band=partners_by_band))
    print("🏆 Rendered partner-most-reviews.html")


# === Partner most products ===
def render_partner_most_products_grouped():
    active = [p for p in ALL_PARTNERS if p.get("active", True)]
    for p in active:
        try:
            p["product_count"] = int(str(p.get("product_count", 0)).replace(",", ""))
        except:
            p["product_count"] = 0

    bands = [3000, 2000, 1000, 500, 250]
    partners_by_band = {b: [] for b in bands}
    for p in active:
        for b in bands:
            if p["product_count"] >= b:
                partners_by_band[b].append(p)
                break

    for b in bands:
        partners_by_band[b].sort(key=lambda p: p["name"].lower())

    template = env.get_template("noths/partners/partner-most-products.html")
    os.makedirs(f"{DOCS_DIR}/noths/partners", exist_ok=True)
    with open(f"{DOCS_DIR}/noths/partners/partner-most-products.html", "w", encoding="utf-8") as f:
        f.write(template.render(bands=bands, partners_by_band=partners_by_band))
    print("📦 Rendered partner-most-products.html")


def render_top_100_products():
    import pandas as pd

    # Filter out unavailable products
    available_products = [p for p in TOP_PRODUCTS_12M if p.get("available", True)]
    # Re-ensure links (idempotent)
    available_products = [ensure_awin_primary_link(p) for p in available_products]

    df = pd.DataFrame(available_products)
    df = df.sort_values(by=["review_count", "name"], ascending=[False, True])

    # Dense ranking: ties get same rank
    df["rank"] = df["review_count"].rank(method="min", ascending=False).astype(int)

    # Keep everything with rank ≤ 100
    top_df = df[df["rank"] <= 100]

    print(f"🔝 Rendered Top 100 (actually {len(top_df)} products with ties, excluding unavailable)")

    template = env.get_template("noths/products/products-last-12-months.html")
    os.makedirs(f"{DOCS_DIR}/noths/products", exist_ok=True)
    with open(f"{DOCS_DIR}/noths/products/products-last-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(products=top_df.to_dict(orient="records")))


# === Top Christmas products ===
def render_top_christmas():
    with open(os.path.join(DATA_DIR, "top_products_christmas.json"), "r", encoding="utf-8") as f:
        christmas_list = json.load(f)

    full_by_sku = {str(p.get("sku")): p for p in TOP_PRODUCTS_12M}
    enriched = []

    for item in christmas_list:
        sku = str(item.get("sku"))
        base = full_by_sku.get(sku, {}) or {}

        try:
            review_count = int(str(base.get("review_count", 0)).replace(",", ""))
        except (TypeError, ValueError):
            review_count = 0

        product_url = base.get("product_url") or item.get("product_url") or item.get("url")
        product_url = normalize_product_url(product_url)

        awin_link = validate_or_rebuild_awin(base.get("awin"), product_url)

        record = {
            "sku": sku,
            "name": item.get("name") or base.get("name", ""),
            "product_url": product_url,
            "awin": awin_link,
            "seller_name": base.get("seller_name", ""),
            "seller_slug": base.get("seller_slug", ""),
            "review_count": review_count,
            "available": base.get("available", True),
        }

        enriched.append(ensure_awin_primary_link(record))

    enriched_sorted = sorted(enriched, key=lambda x: x["review_count"], reverse=True)

    current_rank, last_count = 0, None
    for idx, product in enumerate(enriched_sorted, start=1):
        if product["review_count"] != last_count:
            current_rank = idx
            last_count = product["review_count"]
        product["rank"] = current_rank

    template = env.get_template("noths/products/top-100-christmas.html")
    out_path = f"{DOCS_DIR}/noths/products/top-100-christmas.html"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.render(products=enriched_sorted))

    print(f"🎄 Rendered top-100-christmas.html with {len(enriched_sorted)} products")


# === NOTHS Christmas Catalogue ===
def render_noths_christmas_catalogue():
    data_file = os.path.join(DATA_DIR, "christmas_catalogue_products.json")
    with open(data_file, "r", encoding="utf-8") as f:
        christmas_list = json.load(f)

    full_by_sku = {str(p.get("sku")): p for p in TOP_PRODUCTS_12M}
    enriched = []

    for item in christmas_list:
        sku = str(item.get("sku"))
        base = full_by_sku.get(sku, {}) or {}

        try:
            review_count = int(str(base.get("review_count", 0)).replace(",", ""))
        except (TypeError, ValueError):
            review_count = 0

        product_url = base.get("product_url") or item.get("product_url") or item.get("url")
        product_url = normalize_product_url(product_url)

        awin_link = validate_or_rebuild_awin(base.get("awin"), product_url)

        record = {
            "sku": sku,
            "name": item.get("name") or base.get("name", ""),
            "product_url": product_url,
            "awin": awin_link,
            "seller_name": base.get("seller_name", ""),
            "seller_slug": base.get("seller_slug", ""),
            "review_count": review_count,
            "available": base.get("available", True),
        }

        enriched.append(ensure_awin_primary_link(record))

    enriched_sorted = sorted(
        enriched,
        key=lambda x: (-x.get("review_count", 0), x.get("name", "").lower())
    )

    current_rank, last_count = 0, None
    for idx, product in enumerate(enriched_sorted, start=1):
        if product["review_count"] != last_count:
            current_rank = idx
            last_count = product["review_count"]
        product["rank"] = current_rank

    template = env.get_template("noths/products/noths-christmas-catalogue.html")
    html = template.render(products=enriched_sorted)

    output_path = os.path.join(DOCS_DIR, "noths", "products", "noths-christmas-catalogue.html")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"🎄 Rendered NOTHS Christmas Catalogue → {output_path} ({len(enriched_sorted)} products)")


# === NOTHS Louise Thompson ===
def render_noths_louise_thompson():
    data_file = os.path.join(DATA_DIR, "christmas_louise_thompson.json")
    with open(data_file, "r", encoding="utf-8") as f:
        christmas_list = json.load(f)

    full_by_sku = {str(p.get("sku")): p for p in TOP_PRODUCTS_12M}
    enriched = []

    for item in christmas_list:
        sku = str(item.get("sku"))
        base = full_by_sku.get(sku, {}) or {}

        try:
            review_count = int(str(base.get("review_count", 0)).replace(",", ""))
        except (TypeError, ValueError):
            review_count = 0

        product_url = base.get("product_url") or item.get("product_url") or item.get("url")
        product_url = normalize_product_url(product_url)

        awin_link = validate_or_rebuild_awin(base.get("awin"), product_url)

        price = _coerce_price(base.get("price", item.get("price")))
        price_currency = base.get("price_currency", item.get("price_currency")) or "GBP"

        seller_name = (base.get("seller_name") or item.get("brand") or "").strip()
        seller_slug = (base.get("seller_slug") or "").strip()

        record = {
            "sku": sku,
            "name": (item.get("name") or base.get("name", "")).strip(),
            "product_url": product_url,
            "awin": awin_link,
            "seller_name": seller_name,
            "seller_slug": seller_slug,
            "review_count": review_count,
            "available": base.get("available", True),
            "price": price,
            "price_currency": price_currency,
        }

        enriched.append(ensure_awin_primary_link(record))

    enriched_sorted = sorted(
        enriched,
        key=lambda x: (-x.get("review_count", 0), x.get("name", "").lower())
    )

    current_rank, last_count = 0, None
    for idx, product in enumerate(enriched_sorted, start=1):
        if product["review_count"] != last_count:
            current_rank = idx
            last_count = product["review_count"]
        product["rank"] = current_rank

    template = env.get_template("noths/products/noths-christmas-louise-thompson.html")
    html = template.render(products=enriched_sorted)

    output_path = os.path.join(DOCS_DIR, "noths", "products", "noths-christmas-louise-thompson.html")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"🎄 Rendered NOTHS Louise Thompson → {output_path} ({len(enriched_sorted)} products)")


# === Homepage ===
def render_site_homepage():
    template = env.get_template("home.html")
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(f"{DOCS_DIR}/home.html", "w", encoding="utf-8") as f:
        f.write(template.render())
    print("🏠 Rendered homepage")


# === Top partners last 12 months ===
def render_top_partners_last_12_months():
    import pandas as pd

    partner_lookup = {p["slug"]: p for p in ALL_PARTNERS if p.get("active", True)}

    review_totals = {}
    for p in TOP_PRODUCTS_12M:
        slug = (p.get("seller_slug") or "").lower().strip()
        if slug and slug in partner_lookup:
            review_totals[slug] = review_totals.get(slug, 0) + int(p.get("review_count", 0))

    df = pd.DataFrame([
        {"slug": slug, "name": partner_lookup[slug]["name"], "total_reviews": count}
        for slug, count in review_totals.items()
    ])

    df = df.sort_values(by=["total_reviews", "name"], ascending=[False, True])

    df["rank"] = df["total_reviews"].rank(method="min", ascending=False).astype(int)

    top_df = df[df["rank"] <= 100]

    print(f"🔝 Rendered Top Partners (actually {len(top_df)} with ties)")

    template = env.get_template("noths/partners/top-partners-12-months.html")
    os.makedirs(f"{DOCS_DIR}/noths/partners", exist_ok=True)
    with open(f"{DOCS_DIR}/noths/partners/top-partners-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(partners=top_df.to_dict(orient='records')))


# === Top products all time ===
def render_top_100_all_time():
    data_path = os.path.join(DATA_DIR, "top_100_all_time.json")
    with open(data_path, "r", encoding="utf-8") as f:
        top_all_time = json.load(f)

    top_all_time = [ensure_awin_primary_link(p) for p in top_all_time]

    for p in top_all_time:
        try:
            p["review_count"] = int(p.get("review_count", 0))
        except Exception:
            p["review_count"] = 0

    top_all_time.sort(key=lambda p: p["review_count"], reverse=True)

    if len(top_all_time) > 100:
        print(f"⚠️ Found {len(top_all_time)} entries, trimming to 100")
        top_all_time = top_all_time[:100]

    rank, last_count = 0, None
    for i, p in enumerate(top_all_time, start=1):
        if p["review_count"] != last_count:
            rank = i
        p["rank"] = rank
        last_count = p["review_count"]

    template = env.get_template("noths/products/top-100-all-time.html")
    html = template.render(top_all_time=top_all_time)

    out_path = os.path.join(DOCS_DIR, "noths/products/top-100-all-time.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Rendered Top 100 All Time Products page ({len(top_all_time)} entries)")


# === Most Reviewed Product Per Partner ===
def render_top_product_per_partner():
    """Render a page showing each partner's most reviewed product (5+ reviews)."""
    all_products = TOP_PRODUCTS_12M

    filtered = [p for p in all_products if int(p.get("review_count", 0)) >= 5 and p.get("available", True)]

    best_by_partner = {}
    for p in filtered:
        slug = (p.get("seller_slug") or "").lower().strip()
        if not slug:
            continue
        if slug not in best_by_partner or int(p["review_count"]) > int(best_by_partner[slug]["review_count"]):
            best_by_partner[slug] = p

    products = sorted(best_by_partner.values(), key=lambda x: int(x["review_count"]), reverse=True)
    products = [ensure_awin_primary_link(p) for p in products]

    for i, p in enumerate(products, start=1):
        p["rank"] = i

    json_path = os.path.join(DATA_DIR, "top_product_per_partner.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved JSON → {json_path}")

    template = env.get_template("noths/products/top-per-partner.html")
    os.makedirs(f"{DOCS_DIR}/noths/products", exist_ok=True)
    out_path = f"{DOCS_DIR}/noths/products/top-per-partner.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.render(products=products))

    print(f"🤝 Rendered top-per-partner.html with {len(products)} partners (≥5 reviews)")


# === About page ===
def render_about_page():
    template = env.get_template("about.html")
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(f"{DOCS_DIR}/about.html", "w", encoding="utf-8") as f:
        f.write(template.render())
    print("📖 Rendered about.html")


# === About the Data page ===
def render_about_the_data_page():
    from datetime import datetime
    template = env.get_template("about-the-data.html")

    today_str = datetime.now().strftime("%d.%m.%Y")

    os.makedirs(DOCS_DIR, exist_ok=True)
    out_path = os.path.join(DOCS_DIR, "about-the-data.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.render(last_updated=today_str))

    print(f"📊 Rendered about-the-data.html (Last updated: {today_str})")


# === Sitemap helpers ===
def render_partner_search_json():
    out_path = os.path.join(DOCS_DIR, "data", "partners_search.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    slim = [
        {"name": p.get("name", ""), "slug": p.get("slug", "")}
        for p in ALL_PARTNERS
        if p.get("active", True) and p.get("slug")
    ]

    print(f"🧾 First 5 partners going into search.json: {slim[:5]}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(slim, f, indent=2, ensure_ascii=False)

    print(f"🔎 Rendered partners_search.json → {os.path.abspath(out_path)} ({len(slim)} active partners)")


def render_sitemap():
    BASE_URL = "https://www.mostreviews.co.uk"
    urls = [
        f"{BASE_URL}/",
        f"{BASE_URL}/noths/products/products-last-12-months.html",
        f"{BASE_URL}/noths/products/top-100-christmas.html",
        f"{BASE_URL}/noths/partners/index.html",
        f"{BASE_URL}/noths/partners/by-year.html",
        f"{BASE_URL}/noths/partners/partner-most-reviews.html",
    ]
    search_json_path = "docs/data/partners_search.json"
    try:
        with open(search_json_path, "r", encoding="utf-8") as f:
            sellers = json.load(f)
        for s in sellers:
            slug = s["slug"]
            first = slug[0].lower()
            urls.append(f"{BASE_URL}/noths/partners/{first}/{slug}.html")
    except FileNotFoundError:
        print(f"⚠️ Skipped seller URLs in sitemap: '{search_json_path}' not found.")

    today = __import__("datetime").date.today().isoformat()
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for u in urls:
        xml.append("  <url>")
        xml.append(f"    <loc>{u}</loc>")
        xml.append(f"    <lastmod>{today}</lastmod>")
        xml.append("    <changefreq>weekly</changefreq>")
        xml.append("    <priority>0.8</priority>")
        xml.append("  </url>")
    xml.append("</urlset>")
    with open(f"{DOCS_DIR}/sitemap.xml", "w", encoding="utf-8") as f:
        f.write("\n".join(xml))
    print(f"🗺️ Wrote sitemap.xml with {len(urls)} URLs")


# === Run Everything ===
if __name__ == "__main__":
    copy_static_assets()
    render_noths_index()
    render_top_product_per_partner()
    render_partner_pages()
    render_partner_index()
    render_partner_by_year()
    render_partner_most_reviews_grouped()
    render_partner_most_products_grouped()
    render_top_100_products()
    render_site_homepage()
    render_top_partners_last_12_months()
    render_top_100_all_time()
    render_about_page()
    render_about_the_data_page()
    render_partner_search_json()
    render_sitemap()
    render_top_christmas()
    render_noths_christmas_catalogue()
    render_noths_louise_thompson()
