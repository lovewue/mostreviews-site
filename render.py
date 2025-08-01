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

    template = env.get_template('sellers/seller.html')
    count = 0

    for seller in sellers:
        first_letter = seller['slug'][0].lower()
        output_dir = f"output/sellers/{first_letter}"
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/{seller['slug']}.html"
        html = template.render(
            slug=seller['slug'],
            name=seller['name'],
            url=seller['url'],
            since=seller.get('since', 'Unknown'),
            reviews=seller.get('reviews', 0),
            product_count=seller.get('product_count', 0)
        )

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        count += 1

    print(f"✅ Rendered {count} seller pages into /output/sellers/[a-z]/")


render_seller_pages()

