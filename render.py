
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

    template = env.get_template('noths/sellers/seller.html')
    count, updated = 0, 0

    print("📦 Rendering seller pages...")

    for seller in sellers:
        slug = str(seller.get('slug', '')).strip().lower()
        name = str(seller.get('name', '')).strip()
        if not slug or not name:
            continue

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

    # Filter and clean
    active_sellers = [s for s in sellers if s.get("active", True)]
    for s in active_sellers:
        try:
            s["reviews"] = int(str(s.get("reviews", 0)).replace(",", ""))
        except:
            s["reviews"] = 0
        s["slug"] = s.get("slug", "").strip().lower()
        s["name"] = s.get("name", "").strip()

    # Define bands (in descending order)
    review_bands = [30000, 20000, 10000, 5000, 2500, 1000]

    sellers_by_band = {band: [] for band in review_bands}
    for seller in active_sellers:
        for band in review_bands:
            if seller["reviews"] >= band:
                sellers_by_band[band].append(seller)
                break

    # Sort each group alphabetically by name
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


# === Render Top Product Count ===

def render_product_list(filename, template_name, output_name):
    with open(f"data/{filename}", 'r', encoding='utf-8') as f:
        products = json.load(f)

    template = env.get_template(f"noths/products/{template_name}")
    os.makedirs("output/noths/products", exist_ok=True)
    output_path = f"output/noths/products/{output_name}"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(template.render(products=products))

    print(f"🛍️ Rendered {output_name}")

# === Render Home Page ===    

def render_site_homepage():
    template = env.get_template('home.html')
    os.makedirs('output', exist_ok=True)
    html = template.render()
    with open('output/home.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("🏠 Rendered main site homepage → output/home.html")

    

# === Run All ===
render_noths_index()
copy_static_assets()
render_seller_pages()
render_seller_index()
render_seller_by_year()
render_seller_most_reviews_grouped()
render_seller_most_products_grouped()
render_product_list("products_all_time.json", "products-all-time.html", "products-all-time.html")
render_product_list("products_last_12_months.json", "products-last-12-months.html", "products-last-12-months.html")
render_product_list("products_last_month.json", "products-last-month.html", "products-last-month.html")
render_site_homepage()


