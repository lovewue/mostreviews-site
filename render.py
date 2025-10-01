from jinja2 import Environment, FileSystemLoader
import os
import json
import shutil
from collections import defaultdict
import urllib.parse

# === Config ===
STATIC_PATH = "/docs/noths/static"
DATA_DIR = "data"
DOCS_DIR = "docs"

# === Load shared data once ===
with open(os.path.join(DATA_DIR, "partners_merged.json"), "r", encoding="utf-8") as f:
    ALL_PARTNERS = json.load(f)

with open(os.path.join(DATA_DIR, "top_products_last_12_months.json"), "r", encoding="utf-8") as f:
    TOP_PRODUCTS_12M = json.load(f)

# === Setup Jinja ===
env = Environment(loader=FileSystemLoader("templates"))

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
    partner_lookup = {p["slug"]: p for p in ALL_PARTNERS if p.get("active", True)}

    # --- Review totals ---
    review_totals = {}
    for p in TOP_PRODUCTS_12M:
        slug = (p.get("seller_slug") or "").lower().strip()
        if slug and slug in partner_lookup:
            review_totals[slug] = review_totals.get(slug, 0) + int(p.get("review_count", 0))

    top_partners = sorted(
        [{"slug": slug, "name": partner_lookup[slug]["name"], "total_reviews": count}
         for slug, count in review_totals.items()],
        key=lambda x: x["total_reviews"], reverse=True
    )[:3]

    # --- New joiners in 2025 ---
    partners_2025 = [p for p in ALL_PARTNERS if p.get("since", "").endswith("2025") and p.get("active", True)]
    partners_2025 = sorted(partners_2025, key=lambda x: int(str(x.get("review_count", 0)).replace(",", "")), reverse=True)[:3]

    # --- Most products ---
    partners_with_counts = []
    for p in ALL_PARTNERS:
        if not p.get("active", True):
            continue
        try:
            count = int(str(p.get("product_count", 0)).replace(",", ""))
        except:
            count = 0
        partners_with_counts.append({"slug": p["slug"], "name": p["name"], "product_count": count})

    top_product_partners = sorted(partners_with_counts, key=lambda x: x["product_count"], reverse=True)[:3]

    # --- Christmas top products ---
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
            "product_url": base.get("product_url", item.get("url")),
            "awin": base.get("awin"),
            "seller_name": base.get("seller_name", ""),
            "seller_slug": base.get("seller_slug", ""),
        })

    top_christmas_products = sorted(enriched_christmas, key=lambda x: x["review_count"], reverse=True)[:3]

    # --- A, middle, Z logos ---
    active_partners = [p for p in ALL_PARTNERS if p.get("active", True)]
    partners_sorted = sorted(active_partners, key=lambda p: p.get("name", "").lower())

    az_partners = []
    a_partner = next((p for p in partners_sorted if p.get("name", "").upper().startswith("A")), None)
    if a_partner: az_partners.append(a_partner)
    if partners_sorted: az_partners.append(partners_sorted[len(partners_sorted)//2])
    z_partner = next((p for p in reversed(partners_sorted) if p.get("name", "").upper().startswith("Z")), None)
    if z_partner: az_partners.append(z_partner)

    template = env.get_template("noths/index.html")
    html = template.render(
        title="NOTHS Partners and Products",
        static_path=STATIC_PATH,
        top_products=TOP_PRODUCTS_12M,
        top_partners=top_partners,
        partners_2025=partners_2025,
        top_product_partners=top_product_partners,
        top_christmas_products=top_christmas_products,
        az_partners=az_partners,
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
            products_by_partner.get(slug, []),
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

        # ✅ Normalize path so comparisons match later
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
        f.write(template.render(letters=sorted(sorted_grouped.keys()), partners_by_letter=sorted_grouped, static_path=STATIC_PATH))
    print("📇 Rendered partners/index.html")


# === Partner by year ===
def render_partner_by_year():
    partners = [p for p in ALL_PARTNERS if p.get("active", True)]
    grouped = defaultdict(list)
    for p in partners:
        since_raw = str(p.get("since", "")).strip()
        year = since_raw[-4:] if since_raw[-4:].isdigit() else "Unknown"
        grouped[year].append(p)

    sorted_grouped = {year: sorted(group, key=lambda p: p["name"].lower()) for year, group in sorted(grouped.items(), reverse=True)}

    template = env.get_template("noths/partners/by-year.html")
    os.makedirs(f"{DOCS_DIR}/noths/partners", exist_ok=True)
    out_path = f"{DOCS_DIR}/noths/partners/by-year.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.render(partners_by_year=sorted_grouped, static_path=STATIC_PATH))
    print("📅 Rendered partners/by-year.html")


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

    # Build lookup from the main dataset (12-months)
    full_by_sku = {str(p.get("sku")): p for p in TOP_PRODUCTS_12M}
    enriched = []

    for item in christmas_list:
        sku = str(item.get("sku"))
        base = full_by_sku.get(sku, {})

        try:
            review_count = int(base.get("review_count", 0))
        except (TypeError, ValueError):
            review_count = 0

        # Prefer existing NOTHS/Awin links if available
        product_url = base.get("product_url", item.get("url"))
        awin_link = base.get("awin")
        if not awin_link and product_url:
            awin_link = (
                "https://www.awin1.com/cread.php?"
                "awinmid=18484&awinaffid=1018637&clickref=MostReviewed&ued="
                + urllib.parse.quote(product_url, safe="")
            )

        enriched.append({
            "sku": sku,
            "name": item.get("name") or base.get("name", ""),
            "product_url": product_url,
            "awin": awin_link,
            "seller_name": base.get("seller_name", ""),
            "seller_slug": base.get("seller_slug", ""),
            "review_count": review_count,
            "available": base.get("available", True),
        })

    # Sort by review count (highest first)
    enriched_sorted = sorted(enriched, key=lambda x: x["review_count"], reverse=True)

    # Assign ranking with ties
    current_rank = 0
    last_count = None
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

    # Sort by total_reviews, then name for stability
    df = df.sort_values(by=["total_reviews", "name"], ascending=[False, True])

    # Dense rank so ties share the same rank
    df["rank"] = df["total_reviews"].rank(method="min", ascending=False).astype(int)

    # Keep everything with rank ≤ 100
    top_df = df[df["rank"] <= 100]

    print(f"🔝 Rendered Top Partners (actually {len(top_df)} with ties)")

    template = env.get_template("noths/partners/top-partners-12-months.html")
    os.makedirs(f"{DOCS_DIR}/noths/partners", exist_ok=True)
    with open(f"{DOCS_DIR}/noths/partners/top-partners-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(partners=top_df.to_dict(orient='records')))



# === About page ===
def render_about_page():
    template = env.get_template("about.html")
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(f"{DOCS_DIR}/about.html", "w", encoding="utf-8") as f:
        f.write(template.render())
    print("📖 Rendered about.html")


# === Sitemap ===
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
    render_noths_index()
    copy_static_assets()
    render_partner_pages()
    render_partner_index()
    render_partner_by_year()
    render_partner_most_reviews_grouped()
    render_partner_most_products_grouped()
    render_top_100_products()
    render_site_homepage()
    render_top_partners_last_12_months()
    render_about_page()
    render_partner_search_json()
    render_sitemap()
    render_top_christmas()

