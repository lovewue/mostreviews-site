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
