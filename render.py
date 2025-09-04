from jinja2 import Environment, FileSystemLoader
import os
import json
import shutil
from collections import defaultdict

# Setup Jinja2 environment
env = Environment(loader=FileSystemLoader('templates'))

STATIC_PATH = "/output/noths/static"

# === Render Homepage ===
def render_noths_index():
    template = env.get_template('noths/index.html')
    os.makedirs('output/noths', exist_ok=True)
    html = template.render(title="NOTHS Sellers and Products", static_path=STATIC_PATH)
    with open('output/noths/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("✅ Rendered NOTHS index → output/noths/index.html")

# === Copy static assets ===
def copy_static_assets():
    if os.path.exists('static'):
        shutil.copytree('static', 'output/static', dirs_exist_ok=True)
        print("✅ Copied static assets → output/static/css")
    else:
        print("⚠️  Skipped static assets: 'static/css' folder not found.")

# === Render individual seller pages ===
def render_seller_pages():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    with open('data/top_products_last_12_months.json', 'r', encoding='utf-8') as f:
        all_products = json.load(f)

    # Group top products by seller_slug
    products_by_seller = defaultdict(list)
    for p in all_products:
        slug = p.get("seller_slug", "").lower().strip()
        if slug:
            products_by_seller[slug].append(p)

    template = env.get_template('noths/sellers/seller.html')
    count, updated = 0, 0

    print("📦 Rendering seller pages...")

    for seller in sellers:
        slug = str(seller.get('slug', '')).strip().lower()
        name = str(seller.get('name', '')).strip()
        if not slug or not name:
            continue

        top_products = sorted(products_by_seller.get(slug, []), key=lambda p: p.get("review_count", 0), reverse=True)[:5]

        first_letter = slug[0]
        output_dir = f"output/noths/sellers/{first_letter}"
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/{slug}.html"
        html = template.render(
            slug=slug,
            name=name,
            url=seller.get('url', '#'),
            awin=seller.get('awin', '#'),
            since=seller.get('since', 'Unknown'),
            reviews=seller.get('reviews', 0),
            product_count=int(float(seller.get('product_count', 0))),
            top_products=top_products,
            static_path=STATIC_PATH
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

    print(f"✅ Rendered {count} seller pages → /output/noths/sellers/[a-z]/ ({updated} updated)")


# === Render A–Z index ===
def render_seller_index():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

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
    os.makedirs('output/noths/sellers', exist_ok=True)
    output_path = 'output/noths/sellers/index.html'
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
    os.makedirs('output/noths/sellers', exist_ok=True)
    with open('output/noths/sellers/by-year.html', 'w', encoding='utf-8') as f:
        f.write(template.render(context))
    print("📅 Rendered sellers/by-year.html")

# === Render Top Sellers by Reviews ===
def render_seller_most_reviews_grouped():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    active_sellers = [s for s in sellers if s.get("active", True)]
    for s in active_sellers:
        try:
            s["reviews"] = int(str(s.get("reviews", 0)).replace(",", ""))
        except:
            s["reviews"] = 0
        s["slug"] = s.get("slug", "").strip().lower()
        s["name"] = s.get("name", "").strip()

    review_bands = [30000, 20000, 10000, 5000, 2500, 1000]
    sellers_by_band = {band: [] for band in review_bands}

    for seller in active_sellers:
        for band in review_bands:
            if seller["reviews"] >= band:
                sellers_by_band[band].append(seller)
                break

    for band in review_bands:
        sellers_by_band[band] = sorted(sellers_by_band[band], key=lambda s: s["name"].lower())

    template = env.get_template("noths/sellers/seller-most-reviews.html")
    os.makedirs("output/noths/sellers", exist_ok=True)
    with open("output/noths/sellers/seller-most-reviews.html", "w", encoding="utf-8") as f:
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
    os.makedirs("output/noths/sellers", exist_ok=True)
    with open("output/noths/sellers/seller-most-products.html", "w", encoding='utf-8') as f:
        f.write(template.render(bands=bands, sellers_by_band=sellers_by_band))

    print("📦 Rendered grouped seller-most-products.html")

# === Render Top Products (Last 12 Months, Top 100) ===
def render_top_100_products():
    with open("data/top_products_last_12_months.json", "r", encoding="utf-8") as f:
        products = json.load(f)

    top_100 = sorted(products, key=lambda x: x.get("review_count", 0), reverse=True)[:100]

    template = env.get_template("noths/products/products-last-12-months.html")
    os.makedirs("output/noths/products", exist_ok=True)
    with open("output/noths/products/products-last-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(products=top_100))

    print("🔝 Rendered products-last-12-months.html (Top 100 only)")

# === Render Site Homepage ===
def render_site_homepage():
    template = env.get_template('home.html')
    os.makedirs('output', exist_ok=True)
    html = template.render()
    with open('output/home.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("🏠 Rendered main site homepage → output/home.html")


# === Render Top Sellers Last 12 Months ===
def render_top_sellers_12_months():
    with open('data/top_products_last_12_months.json', 'r', encoding='utf-8') as f:
        products = json.load(f)

    seller_totals = defaultdict(lambda: {'name': '', 'slug': '', 'total_reviews': 0})

    for p in products:
        slug = p.get("seller_slug", "").strip().lower()
        name = p.get("seller_name", "").strip()
        reviews = int(p.get("review_count", 0))

        if slug and name:
            seller_totals[slug]['slug'] = slug
            seller_totals[slug]['name'] = name
            seller_totals[slug]['total_reviews'] += reviews

    top_sellers = sorted(seller_totals.values(), key=lambda x: x["total_reviews"], reverse=True)[:100]

    template = env.get_template('noths/sellers/top-sellers-12-months.html')
    os.makedirs('output/noths/sellers', exist_ok=True)

    with open('output/noths/sellers/top-sellers-12-months.html', 'w', encoding='utf-8') as f:
        f.write(template.render(sellers=top_sellers))

    print("📈 Rendered top-sellers-12-months.html")


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
render_top_sellers_12_months()

