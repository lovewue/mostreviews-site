from jinja2 import Environment, FileSystemLoader
import os
import json
import shutil
from collections import defaultdict

# Find logo URL

def find_logo_url(slug: str) -> str | None:
    """Find the first matching logo file for a seller slug."""
    logo_dir = "Seller_Logo"   # adjust if yours is /static/Seller_Logo
    # Extensions to check in order
    for ext in ("jpg", "jpeg", "png", "webp", "svg"):
        local_path = os.path.join(logo_dir, f"{slug}.{ext}")
        if os.path.exists(local_path):
            return f"/{logo_dir}/{slug}.{ext}"
    return None


# Setup Jinja2 environment
env = Environment(loader=FileSystemLoader('templates'))

STATIC_PATH = "/docs/noths/static"

# === Render Homepage ===
def render_noths_index():
    template = env.get_template('noths/index.html')
    os.makedirs('docs/noths', exist_ok=True)
    html = template.render(title="NOTHS Sellers and Products", static_path=STATIC_PATH)
    with open('docs/noths/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("✅ Rendered NOTHS index → docs/noths/index.html")

# === Copy static assets ===
def copy_static_assets():
    if os.path.exists('static'):
        shutil.copytree('static', 'docs/static', dirs_exist_ok=True)
        print("✅ Copied static assets → docs/static/css")
    else:
        print("⚠️  Skipped static assets: 'static/css' folder not found.")

# === Render individual seller pages ===
def render_seller_pages():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    with open('data/top_products_last_12_months.json', 'r', encoding='utf-8') as f:
        all_products = json.load(f)

    products_by_seller = defaultdict(list)
    for p in all_products:
        slug = p.get("seller_slug", "").lower().strip()
        if slug:
            products_by_seller[slug].append(p)

    template = env.get_template('noths/sellers/seller.html')
    count, updated = 0, 0

    print("📦 Rendering seller pages...")

    for seller in sellers:
        if not seller.get("active", True):
            continue

        slug = str(seller.get('slug', '')).strip().lower()
        name = str(seller.get('name', '')).strip()
        if not slug or not name:
            continue

        top_products = sorted(
            products_by_seller.get(slug, []),
            key=lambda p: p.get("review_count", 0),
            reverse=True
        )[:5]

        # NEW: find a logo for any supported extension
        logo = find_logo_url(slug)

        first_letter = slug[0]
        output_dir = f"docs/noths/sellers/{first_letter}"
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/{slug}.html"
        html = template.render(
            slug=slug,
            name=name,
            url=seller.get('url', '#'),
            awin=seller.get('awin', '#'),
            since=seller.get('since', 'Unknown'),
            review_count=seller.get('review_count', 0),
            product_count=int(float(seller.get('product_count', 0))),
            top_products=top_products,
            static_path=STATIC_PATH,
            logo=logo,  # ← pass to template
        )

        existing_html = ''
        if os.path.exists(output_path):
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_html = f.read()

        if html != existing_html:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html)
            updated += 1
            if updated <= 10 or updated % 500 == 0:
                print(f"  ✅ Updated: {output_path}")

        count += 1

    print(f"✅ Rendered {count} seller pages → /docs/noths/sellers/[a-z]/ ({updated} updated)")

# === Render A–Z index ===
def render_seller_index():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    sellers = [s for s in sellers if s.get("active", True)]

    grouped = defaultdict(list)
    for s in sellers:
        name = str(s.get('name', '')).strip()
        slug = str(s.get('slug', '')).strip().lower()
        if not name or not slug:
            continue
        first_letter = name[0].upper()
        if not first_letter.isalpha():
            first_letter = '#'
        s['slug'] = slug
        grouped[first_letter].append(s)

    sorted_grouped = {
        letter: sorted(group, key=lambda s: str(s.get('name', '')).lower())
        for letter, group in sorted(grouped.items())
    }

    context = {
        "letters": sorted(sorted_grouped.keys()),
        "sellers_by_letter": sorted_grouped,
        "static_path": STATIC_PATH
    }

    template = env.get_template('noths/sellers/index.html')
    os.makedirs('docs/noths/sellers', exist_ok=True)
    output_path = 'docs/noths/sellers/index.html'
    html = template.render(context)

    existing_html = ''
    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            existing_html = f.read()

    if html != existing_html:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print("📇 Updated sellers/index.html")
    else:
        print("📇 sellers/index.html unchanged")

# === Render by year index ===
def render_seller_by_year():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    sellers = [s for s in sellers if s.get("active", True)]

    grouped = defaultdict(list)
    for s in sellers:
        since_raw = s.get("since", "")
        since = str(since_raw).strip()
        slug = s.get("slug", "").strip().lower()
        name = s.get("name", "").strip()
        if not since or not slug or not name:
            continue
        year = since[-4:] if since[-4:].isdigit() else "Unknown"
        grouped[year].append(s)

    sorted_grouped = {
        year: sorted(group, key=lambda s: s["name"].lower())
        for year, group in sorted(grouped.items(), reverse=True)
    }

    context = {
        "sellers_by_year": sorted_grouped,
        "static_path": STATIC_PATH
    }

    template = env.get_template('noths/sellers/by-year.html')
    os.makedirs('docs/noths/sellers', exist_ok=True)
    with open('docs/noths/sellers/by-year.html', 'w', encoding='utf-8') as f:
        f.write(template.render(context))
    print("📅 Rendered sellers/by-year.html")

# === Render Top Sellers by Reviews ===
def render_seller_most_reviews_grouped():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    active_sellers = [s for s in sellers if s.get("active", True)]
    for s in active_sellers:
        try:
            s["review_count"] = int(str(s.get("review_count", 0)).replace(",", ""))
        except:
            s["review_count"] = 0
        s["slug"] = s.get("slug", "").strip().lower()
        s["name"] = s.get("name", "").strip()

    review_bands = [30000, 20000, 10000, 5000, 2500, 1000]
    sellers_by_band = {band: [] for band in review_bands}

    for seller in active_sellers:
        for band in review_bands:
            if seller["review_count"] >= band:
                sellers_by_band[band].append(seller)
                break

    for band in review_bands:
        sellers_by_band[band] = sorted(sellers_by_band[band], key=lambda s: s["name"].lower())

    template = env.get_template("noths/sellers/seller-most-reviews.html")
    os.makedirs("docs/noths/sellers", exist_ok=True)
    with open("docs/noths/sellers/seller-most-reviews.html", "w", encoding="utf-8") as f:
        f.write(template.render(bands=review_bands, sellers_by_band=sellers_by_band))

    print("🏆 Rendered seller-most-reviews.html (grouped by bands)")

# === Render Top Sellers by Product Count ===
def render_seller_most_products_grouped():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    active = [s for s in sellers if s.get("active", True)]
    for s in active:
        try:
            s["product_count"] = int(str(s.get("product_count", 0)).replace(",", ""))
        except:
            s["product_count"] = 0

    bands = [3000, 2000, 1000, 500, 250]
    sellers_by_band = {b: [] for b in bands}

    for s in active:
        for b in bands:
            if s["product_count"] >= b:
                sellers_by_band[b].append(s)
                break

    for b in bands:
        sellers_by_band[b].sort(key=lambda s: s["name"].lower())

    template = env.get_template("noths/sellers/seller-most-products.html")
    os.makedirs("docs/noths/sellers", exist_ok=True)
    with open("docs/noths/sellers/seller-most-products.html", "w", encoding='utf-8') as f:
        f.write(template.render(bands=bands, sellers_by_band=sellers_by_band))

    print("📦 Rendered grouped seller-most-products.html")

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

# === Render Site Homepage ===
def render_site_homepage():
    template = env.get_template('home.html')
    os.makedirs('output', exist_ok=True)
    html = template.render()
    with open('docs/home.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("🏠 Rendered main site homepage →docs//home.html")

# === Render Top Sellers Last 12 Months ===
def render_top_sellers_last_12_months():
    # Load data
    with open("data/top_products_last_12_months.json", "r", encoding="utf-8") as f:
        products = json.load(f)
    with open("data/sellers.json", "r", encoding="utf-8") as f:
        all_sellers = json.load(f)

    # Build seller lookup
    seller_lookup = {s["slug"]: s for s in all_sellers if s.get("active", True)}

    # Count reviews by seller_slug
    review_totals = {}
    for p in products:
        slug = p.get("seller_slug")
        if slug and slug in seller_lookup:
            review_totals[slug] = review_totals.get(slug, 0) + int(p.get("review_count", 0))

    # Build list of top sellers with review counts
    top_sellers = []
    for slug, count in review_totals.items():
        s = seller_lookup[slug]
        top_sellers.append({
            "slug": slug,
            "name": s.get("name"),
            "total_reviews": count,
        })

    # Sort and take top 100
    top_sellers = sorted(top_sellers, key=lambda x: x["total_reviews"], reverse=True)[:100]

    # Render
    template = env.get_template("noths/sellers/top-sellers-12-months.html")
    os.makedirs("docs/noths/sellers", exist_ok=True)
    with open("docs/noths/sellers/top-sellers-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(sellers=top_sellers))

    print("🔝 Rendered top-sellers-12-months.html (Top 100 only)")


# === Render About Page ===
def render_about_page():
    template = env.get_template("about.html")
    os.makedirs("output", exist_ok=True)
    with open("docs/about.html", "w", encoding="utf-8") as f:
        f.write(template.render())
    print("📖 Rendered about.html")

# === Run Everything ===
render_noths_index()
copy_static_assets()
render_seller_pages()
render_seller_index()
render_seller_by_year()
render_seller_most_reviews_grouped()
render_seller_most_products_grouped()
render_top_100_products()
render_site_homepage()
render_top_sellers_last_12_months()
render_about_page()
