from jinja2 import Environment, FileSystemLoader
import os

# Setup Jinja2 environment to read from 'templates' folder
env = Environment(loader=FileSystemLoader('templates'))

# Load the index page template
template = env.get_template('index.html')

# Create output folder if it doesn't exist
os.makedirs('output', exist_ok=True)

# Render the template with any variables you want to pass
rendered_html = template.render(title="Most Reviewed Products")

# Write the result to a static HTML file
with open('output/index.html', 'w', encoding='utf-8') as f:
    f.write(rendered_html)

print("✅ Rendered index.html to output/index.html")

import shutil

# Copy static assets into output/static/
shutil.copytree('static', 'output/static', dirs_exist_ok=True)

import json

def render_seller_pages():
    # Load seller data
    with open('data/sellers.json', 'r', encoding='utf-8') as f:
        sellers = json.load(f)

    # Make sure output folder exists
    os.makedirs('output/sellers', exist_ok=True)

    # Load the seller template
    template = env.get_template('sellers/seller.html')

    for seller in sellers:
        html = template.render(
            slug=seller['slug'],
            name=seller['name'],
            url=seller['url'],
            since=seller.get('since', 'Unknown'),
            reviews=seller.get('reviews', 0),
            product_count=seller.get('product_count', 0)
        )

        output_path = f"output/sellers/{seller['slug']}.html"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

    print(f"✅ Rendered {len(sellers)} seller pages to /output/sellers/")

render_seller_pages()

