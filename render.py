from jinja2 import Environment, FileSystemLoader
import os
import json
import shutil
from collections import defaultdict

# === Logo helper ===
def find_logo_url(slug: str) -> str | None:
    """Find the first matching logo file for a partner slug."""
    logo_dirs = ["Partner_Logo", "Seller_Logo"]  # check both
    exts = ("jpg", "jpeg", "png", "webp", "svg")

    for logo_dir in logo_dirs:
        for ext in exts:
            local_path = os.path.join(logo_dir, f"{slug}.{ext}")
            if os.path.exists(local_path):
                return f"/{logo_dir}/{slug}.{ext}"
    return None


# === Reusable helper: get top N unique partners from a product list ===
def get_top_partners_from_products(json_file: str, partner_lookup: dict, limit: int = 3, full_by_sku: dict | None = None):
    """
    Return up to `limit` unique partners from a product JSON file.
    If `full_by_sku` is provided, use it to enrich/standardize review_count and
    sort products by review_count desc to mirror the Top-100 page ordering.
    """
    with open(json_file, "r", encoding="utf-8") as f:
        products = json.load(f)

    # Enrich with review counts for consistent ranking (if available)
    enriched = []
    for p in products:
        sku = str(p.get("sku") or "").strip()
        # Prefer review_count from the full dataset if available
        if full_by_sku and sku in full_by_sku:
            rc = full_by_sku[sku].get("review_count", 0)
        else:
            rc = p.get("review_count", 0)
        try:
            rc_int = int(str(rc).replace(",", ""))
        except:
            rc_int = 0
        enriched.append((p, rc_int))

    # Sort by review_count desc
    enriched.sort(key=lambda t: t[1], reverse=True)

    seen_slugs = set()
    partners = []
    for p, _rc in enriched:
        slug = (p.get("seller_slug") or "").lower().strip()
        if not slug or slug in seen_slugs:
            continue
        if slug not in partner_lookup:
            continue
        seen_slugs.add(slug)
        partner = partner_lookup[slug]
        partners.append({
            "slug": slug,
            "name": partner.get("name", ""),
            # Provide a ready-to-use logo path if the template wants it
            "logo": find_logo_url(slug),
        })
        if len(partners) >= limit:
            break

    return partners


# === Jinja setup ===
env = Environment(loader=FileSystemLoader("templates"))
STATIC_PATH = "/docs/noths/static"

# === Render NOTHS index ===
def render_noths_index():
    # Load top products (for product card & partner review counts)
    with open("data/top_products_last_12_months.json", "r", encoding="utf-8") as f:
        top_products = json.load(f)

    # Build a quick index by SKU for cross-list enrichment
    full_by_sku = {str(p.get("sku")): p for p in top_products}

    # Load partner metadata
    with open("data/partners_merged.json", "r", encoding="utf-8") as f:
        all_partners = json.load(f)

    partner_lookup = {p["slug"]: p for p in all_partners if p.get("active", True)}

    # --- Build review totals by partner (last 12 months) ---
    review_totals = {}
    for p in top_products:
        slug = (p.get("seller_slug") or "").lower().strip()
        if slug and slug in partner_lookup:
            review_totals[slug] = review_totals.get(slug, 0) + int(p.get("review_count", 0))

    top_partners = []
    for slug, count in review_totals.items():
        partner = partner_lookup[slug]
        top_partners.append({
            "slug": slug,
            "name": partner.get("name"),
            "total_reviews": count,
        })

    # Top 3 partners by reviews in last 12 months
    top_partners = sorted(top_partners, key=lambda x: x["total_reviews"], reverse=True)[:3]

    # --- Top 3 partners who joined in 2025, ranked by reviews ---
    partners_2025 = []
    for p in all_partners:
        if not p.get("active", True):
            continue
        since_raw = str(p.get("since", "")).strip()
        year = since_raw[-4:] if since_raw[-4:].isdigit() else "Unknown"
        if year == "2025":
            partners_2025.append(p)

    partners_2025 = sorted(
        partners_2025, key=lambda x: int(str(x.get("review_count", 0)).replace(",", "")), reverse=True
    )[:3]

    # --- Top 3 partners with the most products ---
    partners_with_counts = []
    for p in all_partners:
        if not p.get("active", True):
            continue
        try:
            count = int(str(p.get("product_count", 0)).replace(",", ""))
        except:
            count = 0
        partners_with_counts.append({
            "slug": p.get("slug", "").strip().lower(),
            "name": p.get("name", "").strip(),
            "product_count": count,
        })

    top_product_partners = sorted(
        partners_with_counts, key=lambda x: x["product_count"], reverse=True
    )[:3]

    # --- Top 3 products from Christmas Top 100 (enriched with review counts) ---
    with open("data/top_products_christmas.json", "r", encoding="utf-8") as f:
        christmas_products = json.load(f)

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

    top_christmas_products = sorted(
        enriched_christmas,
        key=lambda x: x["review_count"],
        reverse=True
    )[:3]

    # --- Pick A, middle, and Z logos from A–Z directory ---
    active_partners = [p for p in all_partners if p.get("active", True)]
    partners_sorted = sorted(active_partners, key=lambda p: p.get("name", "").lower())

    az_partners = []

    # First partner starting with 'A'
    a_partner = next(
        (p for p in partners_sorted if p.get("name", "").strip().upper().startswith("A")),
        None
    )
    if a_partner:
        az_partners.append(a_partner)

    # Middle one
    if partners_sorted:
        az_partners.append(partners_sorted[len(partners_sorted)//2])

    # Last partner starting with 'Z'
    z_partner = next(
        (p for p in reversed(partners_sorted) if p.get("name", "").strip().upper().startswith("Z")),
        None
    )
    if z_partner:
        az_partners.append(z_partner)

    # --- Debug prints ---
    print("Top partners:", [p["slug"] for p in top_partners])
    print("2025 partners:", [p["slug"] for p in partners_2025])
    print("Most products partners:", [p["slug"] for p in top_product_partners])
    print("Christmas products:", [(p["sku"], p["review_count"]) for p in top_christmas_products])
    print("A–Z partners:", [p["slug"] for p in az_partners])

    # --- Render template ---
    template = env.get_template("noths/index.html")
    html = template.render(
        title="NOTHS Partners and Products",
        static_path=STATIC_PATH,
        top_products=top_products,                  # full list for slicing in Jinja
        top_partners=top_partners,                  # top 3 by reviews
        partners_2025=partners_2025,                # top 3 new joiners
        top_product_partners=top_product_partners,  # top 3 by product count
        top_christmas_products=top_christmas_products,  # ✅ top 3 enriched Christmas products
        az_partners=az_partners                     # first A, middle, last Z
    )

    # --- Write output ---
    os.makedirs("docs/noths", exist_ok=True)
    with open("docs/noths/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("✅ Rendered NOTHS index → docs/noths/index.html")




# === Copy static assets ===
def copy_static_assets():
    if os.path.exists("static"):
        shutil.copytree("static", "docs/static", dirs_exist_ok=True)
        print("✅ Copied static assets → docs/static/css")
    else:
        print("⚠️  Skipped static assets: 'static/css' folder not found.")

    # ✅ Copy logo folders too
    for folder in ["Partner_Logo", "Seller_Logo"]:
        if os.path.exists(folder):
            shutil.copytree(folder, f"docs/{folder}", dirs_exist_ok=True)
            print(f"✅ Copied {folder} → docs/{folder}")
        else:
            print(f"⚠️  Skipped {folder}: folder not found.")


# === Render individual partner pages ===
def render_partner_pages():
    with open("data/partners_merged.json", "r", encoding="utf-8") as f:
        partners = json.load(f)

    with open("data/top_products_last_12_months.json", "r", encoding="utf-8") as f:
        all_products = json.load(f)

    products_by_partner = defaultdict(list)
    for p in all_products:
        slug = (p.get("seller_slug") or "").lower().strip()
        if slug:
            products_by_partner[slug].append(p)

    template = env.get_template("noths/partners/partner.html")
    count, updated = 0, 0
    logo_cache = {}

    print("📦 Rendering partner pages...")

    for i, partner in enumerate(partners, start=1):
        if not partner.get("active", True):
            continue

        slug = str(partner.get("slug", "")).strip().lower()
        name = str(partner.get("name", "")).strip()
        if not slug or not name:
            continue

        top_products = sorted(
            products_by_partner.get(slug, []),
            key=lambda p: p.get("review_count", 0),
            reverse=True,
        )

        if slug not in logo_cache:
            logo_cache[slug] = find_logo_url(slug)
        partner["logo"] = logo_cache[slug]

        if not partner["logo"]:
            print(f"⚠️  No logo found for partner: {slug}")

        first_letter = slug[0]
        output_dir = f"docs/noths/partners/{first_letter}"
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/{slug}.html"
        html = template.render(
            partner=partner,
            top_products=top_products,
            static_path=STATIC_PATH,
        )

        existing_html = ""
        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                existing_html = f.read()

        if html != existing_html:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)
            updated += 1
            if updated <= 10 or updated % 500 == 0:
                print(f"  ✅ Updated: {output_path}")

        count += 1
        if i % 500 == 0:
            print(f"  ⏳ Processed {i}/{len(partners)} partners...")

    print(f"✅ Rendered {count} partner pages → /docs/noths/partners/[a-z]/ ({updated} updated)")


# === Render A–Z index ===
def render_partner_index():
    with open("data/partners_merged.json", "r", encoding="utf-8") as f:
        partners = json.load(f)

    partners = [p for p in partners if p.get("active", True)]

    grouped = defaultdict(list)
    for p in partners:
        name = str(p.get("name", "")).strip()
        slug = str(p.get("slug", "")).strip().lower()
        if not name or not slug:
            continue
        first_letter = name[0].upper()
        if not first_letter.isalpha():
            first_letter = "#"
        p["slug"] = slug
        grouped[first_letter].append(p)

    sorted_grouped = {
        letter: sorted(group, key=lambda p: str(p.get("name", "")).lower())
        for letter, group in sorted(grouped.items())
    }

    context = {
        "letters": sorted(sorted_grouped.keys()),
        "partners_by_letter": sorted_grouped,
        "static_path": STATIC_PATH,
    }

    template = env.get_template("noths/partners/index.html")
    os.makedirs("docs/noths/partners", exist_ok=True)
    output_path = "docs/noths/partners/index.html"
    html = template.render(context)

    existing_html = ""
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            existing_html = f.read()

    if html != existing_html:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print("📇 Updated partners/index.html")
    else:
        print("📇 partners/index.html unchanged")


# === Render by year index ===
def render_partner_by_year():
    with open("data/partners_merged.json", "r", encoding="utf-8") as f:
        partners = json.load(f)

    partners = [p for p in partners if p.get("active", True)]

    grouped = defaultdict(list)
    for p in partners:
        since_raw = p.get("since", "")
        since = str(since_raw).strip()
        slug = p.get("slug", "").strip().lower()
        name = p.get("name", "").strip()
        if not since or not slug or not name:
            continue
        year = since[-4:] if since[-4:].isdigit() else "Unknown"
        grouped[year].append(p)

    sorted_grouped = {
        year: sorted(group, key=lambda p: p["name"].lower())
        for year, group in sorted(grouped.items(), reverse=True)
    }

    context = {"partners_by_year": sorted_grouped, "static_path": STATIC_PATH}

    template = env.get_template("noths/partners/by-year.html")
    os.makedirs("docs/noths/partners", exist_ok=True)
    with open("docs/noths/partners/by-year.html", "w", encoding="utf-8") as f:
        f.write(template.render(context))
    print("📅 Rendered partners/by-year.html")


# === Render grouped by reviews ===
def render_partner_most_reviews_grouped():
    with open("data/partners_merged.json", "r", encoding="utf-8") as f:
        partners = json.load(f)

    active_partners = [p for p in partners if p.get("active", True)]
    for p in active_partners:
        try:
            p["review_count"] = int(str(p.get("review_count", 0)).replace(",", ""))
        except:
            p["review_count"] = 0
        p["slug"] = p.get("slug", "").strip().lower()
        p["name"] = p.get("name", "").strip()

    review_bands = [30000, 20000, 10000, 5000, 2500, 1000]
    partners_by_band = {band: [] for band in review_bands}

    for partner in active_partners:
        for band in review_bands:
            if partner["review_count"] >= band:
                partners_by_band[band].append(partner)
                break

    for band in review_bands:
        partners_by_band[band] = sorted(
            partners_by_band[band], key=lambda p: p["name"].lower()
        )

    template = env.get_template("noths/partners/partner-most-reviews.html")
    os.makedirs("docs/noths/partners", exist_ok=True)
    with open("docs/noths/partners/partner-most-reviews.html", "w", encoding="utf-8") as f:
        f.write(template.render(bands=review_bands, partners_by_band=partners_by_band))

    print("🏆 Rendered partner-most-reviews.html (grouped by bands)")


# === Render grouped by product count ===
def render_partner_most_products_grouped():
    with open("data/partners_merged.json", "r", encoding="utf-8") as f:
        partners = json.load(f)

    active = [p for p in partners if p.get("active", True)]
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
    os.makedirs("docs/noths/partners", exist_ok=True)
    with open("docs/noths/partners/partner-most-products.html", "w", encoding="utf-8") as f:
        f.write(template.render(bands=bands, partners_by_band=partners_by_band))

    print("📦 Rendered partner-most-products.html")


# === Render Top Products (Last 12 Months, Top 100) ===
def render_top_100_products():
    with open("data/top_products_last_12_months.json", "r", encoding="utf-8") as f:
        products = json.load(f)

    top_100 = sorted(products, key=lambda x: x.get("review_count", 0), reverse=True)[:100]

    template = env.get_template("noths/products/products-last-12-months.html")
    os.makedirs("docs/noths/products", exist_ok=True)
    with open("docs/noths/products/products-last-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(products=top_100))

    print("🔝 Rendered products-last-12-months.html (Top 100 only)")

import urllib.parse

def render_top_christmas():
    # Load Christmas category SKUs
    with open("data/top_products_christmas.json", "r", encoding="utf-8") as f:
        christmas_list = json.load(f)

    # Load enriched full 12-months dataset
    with open("data/top_products_last_12_months.json", "r", encoding="utf-8") as f:
        full_products = json.load(f)

    # Index full dataset by SKU for quick lookup
    full_by_sku = {str(p.get("sku")): p for p in full_products}

    # Enrich Christmas list with full product data (AWIN fallback for missing)
    enriched = []
    for item in christmas_list:
        sku = str(item.get("sku"))
        base = full_by_sku.get(sku, {})

        product_url = base.get("product_url", item.get("url"))
        awin_link = base.get("awin")
        if not awin_link and product_url:
            awin_link = (
                "https://www.awin1.com/cread.php?"
                "awinmid=18484&awinaffid=1018637&clickref=MostReviewed&ued="
                + urllib.parse.quote(product_url, safe="")
            )

        merged = {
            "sku": sku,
            "name": item.get("name") or base.get("name", ""),
            "product_url": product_url,
            "awin": awin_link,
            "seller_name": base.get("seller_name", ""),
            "seller_slug": base.get("seller_slug", ""),
            "review_count": base.get("review_count", 0),
        }
        enriched.append(merged)

    # Sort enriched list by review_count
    enriched_sorted = sorted(enriched, key=lambda x: x.get("review_count", 0), reverse=True)

    # Render with same template as last-12-months
    template = env.get_template("noths/products/top-100-christmas.html")
    out_path = "docs/noths/products/top-100-christmas.html"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.render(products=enriched_sorted))

    print("🎄 Top 100 Christmas page rendered →", out_path)


# === Render Site Homepage ===
def render_site_homepage():
    template = env.get_template("home.html")
    os.makedirs("docs", exist_ok=True)
    html = template.render()
    with open("docs/home.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("🏠 Rendered main site homepage → docs/home.html")


# === Render Top Partners Last 12 Months ===
def render_top_partners_last_12_months():
    with open("data/top_products_last_12_months.json", "r", encoding="utf-8") as f:
        products = json.load(f)
    with open("data/partners_merged.json", "r", encoding="utf-8") as f:
        all_partners = json.load(f)

    partner_lookup = {p["slug"]: p for p in all_partners if p.get("active", True)}

    review_totals = {}
    for p in products:
        slug = (p.get("seller_slug") or "").lower().strip()
        if slug and slug in partner_lookup:
            review_totals[slug] = review_totals.get(slug, 0) + int(p.get("review_count", 0))

    top_partners = []
    for slug, count in review_totals.items():
        partner = partner_lookup[slug]
        top_partners.append({
            "slug": slug,
            "name": partner.get("name"),
            "total_reviews": count,
        })

    top_partners = sorted(top_partners, key=lambda x: x["total_reviews"], reverse=True)[:100]

    template = env.get_template("noths/partners/top-partners-12-months.html")
    os.makedirs("docs/noths/partners", exist_ok=True)
    with open("docs/noths/partners/top-partners-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(partners=top_partners))

    print("🔝 Rendered top-partners-12-months.html (Top 100 only)")


# === Render About Page ===
def render_about_page():
    template = env.get_template("about.html")
    os.makedirs("docs", exist_ok=True)
    with open("docs/about.html", "w", encoding="utf-8") as f:
        f.write(template.render())
    print("📖 Rendered about.html")


# === Create Sitemap ===
def render_sitemap():
    import json
    from datetime import date

    BASE_URL = "https://www.mostreviews.co.uk"
    urls = [
        f"{BASE_URL}/",
        f"{BASE_URL}/noths/products/products-last-12-months.html",
        f"{BASE_URL}/noths/products/top-100-christmas.html",  # NEW
        f"{BASE_URL}/noths/partners/index.html",
        f"{BASE_URL}/noths/partners/by-year.html",
        f"{BASE_URL}/noths/partners/partner-most-reviews.html",
    ]

    # include all seller pages (if search file exists)
    search_json_path = "docs/data/partners_search.json"
    try:
        with open(search_json_path, "r", encoding="utf-8") as f:
            sellers = json.load(f)
        for s in sellers:
            slug = s["slug"]
            first = slug[0].lower()
            urls.append(f"{BASE_URL}/noths/partners/{first}/{slug}.html")
    except FileNotFoundError:
        print(f"⚠️  Skipped seller URLs in sitemap: '{search_json_path}' not found.")

    today = date.today().isoformat()
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

    os.makedirs("docs", exist_ok=True)
    with open("docs/sitemap.xml", "w", encoding="utf-8") as f:
        f.write("\n".join(xml))

    print(f"🗺️  Wrote sitemap.xml with {len(urls)} URLs")


# === Run Everything ===
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
render_sitemap()
render_top_christmas()
