import json
from pathlib import Path

# Load seller data
with open("data/sellers.json", "r", encoding="utf-8") as f:
    sellers = json.load(f)

# Output folder (local build)
output_dir = Path("sellers")
output_dir.mkdir(parents=True, exist_ok=True)

# HTML template (basic structure)
template = Path("templates/seller_template.html").read_text(encoding="utf-8")

# Generate pages
for seller in sellers:
    html = template
    for key, value in seller.items():
        html = html.replace(f"{{{{ {key} }}}}", str(value))
    
    # Output file path: /sellers/[slug].html
    file_path = output_dir / f"{seller['slug']}.html"
    file_path.write_text(html, encoding="utf-8")
    print(f"✅ Created: {file_path.name}")

print("\n✅ All seller pages generated in the 'sellers' folder.")
