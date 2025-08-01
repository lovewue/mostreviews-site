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
            product_count=seller.get('products', 0)
        )

        # Only overwrite if changed
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

# Run all
render_homepage()
copy_static_assets()
render_seller_pages()
render_seller_index()
