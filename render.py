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

    with open("data/products_last_12_months.json", "r", encoding="utf-8") as f:
        all_products = json.load(f)

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

        # Get top 5 products for this seller
        top_products = [
            p for p in all_products
            if str(p.get("seller_slug", "")).strip().lower() == slug
        ]
        top_products = sorted(top_products, key=lambda p: int(p.get("review_count", 0)), reverse=True)[:5]

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

# === Render Top 100 Products ===
def render_top_100_products():
    with open("data/products_last_12_months.json", "r", encoding="utf-8") as f:
        products = json.load(f)

    top_100 = sorted(products, key=lambda p: int(p.get("review_count", 0)), reverse=True)[:100]

    template = env.get_template("noths/products/products-last-12-months.html")
    os.makedirs("output/noths/products", exist_ok=True)
    with open("output/noths/products/products-last-12-months.html", "w", encoding="utf-8") as f:
        f.write(template.render(products=top_100, static_path=STATIC_PATH))

    print("🔝 Rendered products-last-12-months.html (Top 100 only)")

# === Run All ===
render_noths_index()
copy_static_assets()
render_seller_pages()
render_top_100_products()
