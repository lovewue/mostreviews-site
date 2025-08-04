from jinja2 import Environment, FileSystemLoader
import os
import json
import shutil
from collections import defaultdict

# Setup Jinja2 environment
env = Environment(loader=FileSystemLoader('templates'))

# Render homepage
def render_homepage():
    template = env.get_template('index.html')
    os.makedirs('output', exist_ok=True)
    rendered_html = template.render(title="Most Reviewed Products")
    with open('output/index.html', 'w', encoding='utf-8') as f:
        f.write(rendered_html)
    print("✅ Rendered index.html to output/index.html")

# Copy static assets
def copy_static_assets():
    if os.path.exists('static'):
        shutil.copytree('static', 'output/static', dirs_exist_ok=True)
        print("✅ Copied static assets to output/static/")
    else:
        print("⚠️  Skipped static assets: 'static/' folder not found.")

# Render individual seller pages
def render_seller_pages():
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    template = env.get_template('sellers/seller.html')
    count = 0
    updated = 0

    print("📦 Rendering seller pages...")

    for seller in sellers:
        slug = str(seller.get('slug', '')).strip().lower()
        name = str(seller.get('name', '')).strip()
        if not slug or not name:
            continue

        first_letter = slug[0]
        output_dir = f"output/sellers/{first_letter}"
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/{slug}.html"
        html = template.render(
            slug=slug,
            name=name,
            url=seller.get('url', '#'),
            since=seller.get('since', 'Unknown'),
            reviews=seller.get('reviews', 0),
            product_count=int(float(seller.get('product_count', 0)))
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

    print(f"✅ Rendered {count} seller pages into /output/sellers/[a-z]/ ({updated} updated)")

# Render A–Z seller index page
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
        "sellers_by_letter": sorted_grouped
    }

    template = env.get_template('sellers/index.html')
    os.makedirs('output/sellers', exist_ok=True)

    output_path = 'output/sellers/index.html'
    html = template.render(context)

    existing_html = ''
    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            existing_html = f.read()

    if html != existing_html:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"📇 Updated sellers/index.html")
    else:
        print(f"📇 sellers/index.html unchanged")

def render_top_100(metric):
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    # Filter only active sellers
    active_sellers = [s for s in sellers if s.get("active", True)]

    # Clean and parse numeric fields
    for seller in active_sellers:
        try:
            if metric == "products":
                seller["products"] = int(str(seller.get("product_count", 0)).replace(",", ""))
            else:
                seller[metric] = int(str(seller.get(metric, 0)).replace(",", ""))
        except:
            seller[metric] = 0

    top_100 = sorted(active_sellers, key=lambda s: s[metric], reverse=True)[:100]

    template = env.get_template(f"top/top-{metric}.html")
    os.makedirs("output/top", exist_ok=True)
    html = template.render(sellers=top_100, metric=metric)

    with open(f"output/top/top-{metric}.html", "w", encoding='utf-8') as f:
        f.write(html)

    print(f"🏆 Rendered top 100 by {metric} → output/top/top-{metric}.html")

# Render seller index by year
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

        try:
            year = since[-4:] if since[-4:].isdigit() else "Unknown"
        except:
            year = "Unknown"

        grouped[year].append(s)

    sorted_grouped = {
        year: sorted(group, key=lambda s: s["name"].lower())
        for year, group in sorted(grouped.items(), reverse=True)
    }

    context = {
        "sellers_by_year": sorted_grouped
    }

    template = env.get_template('sellers/by-year.html')
    os.makedirs('output/sellers', exist_ok=True)

    with open('output/sellers/by-year.html', 'w', encoding='utf-8') as f:
        f.write(template.render(context))

    print(f"📅 Rendered sellers by year → output/sellers/by-year.html")

# Run all
render_homepage()
copy_static_assets()
render_seller_pages()
render_seller_index()
render_top_100("reviews")
render_top_100("products")
render_seller_by_year()
