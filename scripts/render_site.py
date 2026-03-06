import json
import shutil
from pathlib import Path
from datetime import datetime


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DERIVED_ROOT = DATA_DIR / "derived" / "monthly"

TEMPLATES_DIR = PROJECT_ROOT / "templates"
PARTIALS_DIR = TEMPLATES_DIR / "partials"

STATIC_SRC = PROJECT_ROOT / "static"

OUTPUT_ROOT = PROJECT_ROOT / "site"
STATIC_DST = OUTPUT_ROOT / "static"


# -----------------------------------------------------------------------------
# Template loading
# -----------------------------------------------------------------------------
def load_text(path: Path) -> str:
    """Load a text file from disk."""
    return path.read_text(encoding="utf-8")


BASE_TEMPLATE = load_text(TEMPLATES_DIR / "base.html")
HEADER_TEMPLATE = load_text(PARTIALS_DIR / "header.html")
FOOTER_TEMPLATE = load_text(PARTIALS_DIR / "footer.html")


def render_page(title: str, content: str, static_path: str) -> str:
    """
    Render a full page using the base template and shared partials.
    """
    html = BASE_TEMPLATE
    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{HEADER}}", HEADER_TEMPLATE)
    html = html.replace("{{FOOTER}}", FOOTER_TEMPLATE)
    html = html.replace("{{CONTENT}}", content)
    html = html.replace("{{STATIC}}", static_path)
    return html


# -----------------------------------------------------------------------------
# Data helpers
# -----------------------------------------------------------------------------
def load_json(path: Path):
    """Load JSON from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_html(path: Path, html: str):
    """Save HTML to disk, creating parent folders if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def format_month(month: str) -> str:
    """Convert YYYY-MM -> Month YYYY."""
    dt = datetime.strptime(month, "%Y-%m")
    return dt.strftime("%B %Y")


def get_month_dirs():
    """Return list of available months sorted newest first."""
    months = []

    if not DERIVED_ROOT.exists():
        return months

    for p in DERIVED_ROOT.iterdir():
        if p.is_dir():
            months.append(p.name)

    months.sort(reverse=True)
    return months


def top_n_with_ties(products, limit):
    """
    Return the top N products including ties on review_count_month.
    """
    if not limit or len(products) <= limit:
        return products

    cutoff_reviews = products[limit - 1].get("review_count_month") or 0

    return [
        p for p in products
        if (p.get("review_count_month") or 0) >= cutoff_reviews
    ]


def add_dense_ranks(products):
    """
    Add ranking numbers with ties based on review_count_month.

    Example:
    10, 9, 9, 8 -> ranks 1, 2, 2, 4
    """
    ranked = []

    prev_reviews = None
    prev_rank = 0

    for i, p in enumerate(products, start=1):
        reviews = p.get("review_count_month") or 0

        if reviews == prev_reviews:
            rank = prev_rank
        else:
            rank = i

        item = dict(p)
        item["rank"] = rank
        ranked.append(item)

        prev_reviews = reviews
        prev_rank = rank

    return ranked


def build_rank_lookup(products):
    """
    Build SKU -> rank lookup from a product list.
    """
    ranked = add_dense_ranks(products)

    return {
        p["sku"]: p["rank"]
        for p in ranked
        if p.get("sku")
    }


def apply_rank_movement(products, previous_rank_lookup):
    """
    Add rank movement indicators based on previous month rank.

    Examples:
    ▲ 12       = ranked 12 last month, now higher
    ▼ 3        = ranked 3 last month, now lower
    –          = same rank as last month
    NO REVIEWS = product had no reviews last month
    """
    ranked = add_dense_ranks(products)
    enriched = []

    for p in ranked:
        item = dict(p)

        sku = item.get("sku")
        current_rank = item.get("rank")
        prev_rank = previous_rank_lookup.get(sku)

        if prev_rank is None:
            item["movement_label"] = "NEW"
            item["movement_class"] = "new"
        elif prev_rank == current_rank:
            item["movement_label"] = "–"
            item["movement_class"] = "same"
        elif prev_rank > current_rank:
            item["movement_label"] = f"▲ {prev_rank}"
            item["movement_class"] = "up"
        else:
            item["movement_label"] = f"▼ {prev_rank}"
            item["movement_class"] = "down"

        enriched.append(item)

    return enriched


def copy_static():
    """
    Copy static assets (CSS, images, favicon) into the generated site folder.
    Overwrites files without deleting the folder tree.
    """
    STATIC_DST.mkdir(parents=True, exist_ok=True)

    for item in STATIC_SRC.rglob("*"):
        dest = STATIC_DST / item.relative_to(STATIC_SRC)

        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            shutil.copy2(item, dest)

    print("✅ Static assets copied")


# -----------------------------------------------------------------------------
# HTML fragments
# -----------------------------------------------------------------------------
def render_stats(summary):
    """Render a simple stats block from summary.json."""
    return f"""
<div class="stats">
    <div class="stat">
        <div class="stat-label">Products reviewed</div>
        <div class="stat-value">{summary.get("product_count_with_reviews", 0)}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Brands reviewed</div>
        <div class="stat-value">{summary.get("seller_count_with_reviews", 0)}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Top review count</div>
        <div class="stat-value">{summary.get("top_review_count", 0)}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Products with 5+ reviews</div>
        <div class="stat-value">{summary.get("products_with_5_plus_reviews", 0)}</div>
    </div>
</div>
"""


def render_products(products, limit=None, show_last_month=False):
    """
    Render products table.

    If a limit is supplied, apply top-N including ties before rendering.
    Tied ranks are shown with '=' e.g. 2=
    """
    if limit:
        products = top_n_with_ties(products, limit)

    if not products or "rank" not in products[0]:
        products = add_dense_ranks(products)

    rows = []

    for idx, p in enumerate(products):
        rank_num = p.get("rank", "")

        same_as_prev = (
            idx > 0 and
            (p.get("review_count_month") or 0) == (products[idx - 1].get("review_count_month") or 0)
        )
        rank = f"{rank_num}=" if same_as_prev else str(rank_num)

        name = p.get("name") or "Unknown product"
        seller = p.get("seller_name") or "Unknown seller"
        reviews = p.get("review_count_month") or 0
        url = p.get("product_url")

        if url:
            name_html = f'<a href="{url}">{name}</a>'
        else:
            name_html = name

        last_month_cell = ""
        if show_last_month:
            movement_label = p.get("movement_label", "")
            movement_class = p.get("movement_class", "")
            last_month_cell = f'<td class="last-month rank-change {movement_class}">{movement_label}</td>'

        rows.append(
            f"""
<tr>
    <td class="rank">{rank}</td>
    <td>
        {name_html}
        <div class="partner">{seller}</div>
    </td>
    <td class="reviews">{reviews}</td>
    {last_month_cell}
</tr>
"""
        )

    last_month_header = "<th>Last Month</th>" if show_last_month else ""

    return f"""
<table>
    <tr>
        <th>#</th>
        <th>Product</th>
        <th>Reviews</th>
        {last_month_header}
    </tr>
    {''.join(rows)}
</table>
"""


def render_partners(partners, limit=10):
    """Render partner summary table."""
    rows = []

    for i, p in enumerate(partners[:limit], start=1):
        seller_name = p.get("seller_name") or p.get("seller_slug") or "Unknown seller"
        reviews = p.get("total_reviews_month") or 0

        rows.append(
            f"""
<tr>
    <td class="rank">{i}</td>
    <td>{seller_name}</td>
    <td class="reviews">{reviews}</td>
</tr>
"""
        )

    return f"""
<table>
    <tr>
        <th>#</th>
        <th>Brand</th>
        <th>Reviews</th>
    </tr>
    {''.join(rows)}
</table>
"""


# -----------------------------------------------------------------------------
# Page rendering
# -----------------------------------------------------------------------------
def render_homepage(latest_month, previous_month=None):
    month_dir = DERIVED_ROOT / latest_month

    products = load_json(month_dir / "enriched_products.json")
    partners = load_json(month_dir / "partners_summary.json")
    summary = load_json(month_dir / "summary.json")

    previous_rank_lookup = {}
    if previous_month:
        prev_dir = DERIVED_ROOT / previous_month
        prev_products = load_json(prev_dir / "enriched_products.json")
        previous_rank_lookup = build_rank_lookup(prev_products)

    products = apply_rank_movement(products, previous_rank_lookup)

    title_month = format_month(latest_month)
    top_products = top_n_with_ties(products, 20)

    body = f"""
<h1>Trending Products on NOTHS</h1>

<p>
Snapshot for <strong>{title_month}</strong>.
</p>

{render_stats(summary)}

<h2>Top Products</h2>
<p><small>Showing top 20 including ties ({len(top_products)} products shown).</small></p>

{render_products(products, 20, show_last_month=bool(previous_month))}

<h2>Top Brands</h2>

{render_partners(partners, 10)}

<p>
    <a href="archive.html">Browse monthly archive →</a>
</p>
"""

    html = render_page("Trending Products on NOTHS", body, "static")
    save_html(OUTPUT_ROOT / "index.html", html)

    print("✅ homepage rendered")


def render_month(month, previous_month=None):
    month_dir = DERIVED_ROOT / month

    products = load_json(month_dir / "enriched_products.json")
    partners = load_json(month_dir / "partners_summary.json")
    summary = load_json(month_dir / "summary.json")

    previous_rank_lookup = {}
    if previous_month:
        prev_dir = DERIVED_ROOT / previous_month
        prev_products = load_json(prev_dir / "enriched_products.json")
        previous_rank_lookup = build_rank_lookup(prev_products)

    products = apply_rank_movement(products, previous_rank_lookup)

    title_month = format_month(month)
    top_products = top_n_with_ties(products, 50)

    body = f"""
<h1>Trending Products – {title_month}</h1>

<p>
Products ranked by number of reviews received during the month.
</p>

{render_stats(summary)}

<h2>Top Products</h2>
<p><small>Showing top 50 including ties ({len(top_products)} products shown).</small></p>

{render_products(products, 50, show_last_month=bool(previous_month))}

<h2>Top Brands</h2>

{render_partners(partners, 20)}

<p>
    <a href="../index.html">← Back to homepage</a>
</p>
"""

    html = render_page(f"Trending Products – {title_month}", body, "../static")
    save_html(OUTPUT_ROOT / "months" / f"{month}.html", html)

    print(f"✅ rendered {month}")


def render_archive(months):
    rows = []

    for m in months:
        label = format_month(m)
        rows.append(f'<li><a href="months/{m}.html">{label}</a></li>')

    body = f"""
<h1>Monthly Archive</h1>

<ul>
    {''.join(rows)}
</ul>

<p>
    <a href="index.html">← Back to homepage</a>
</p>
"""

    html = render_page("Monthly Archive", body, "static")
    save_html(OUTPUT_ROOT / "archive.html", html)

    print("✅ archive rendered")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    months = get_month_dirs()

    if not months:
        print("No derived months found.")
        return

    copy_static()

    latest = months[0]

    print(f"📊 Latest month: {latest}")
    print()

    previous_for_homepage = months[1] if len(months) > 1 else None
    render_homepage(latest, previous_for_homepage)

    for idx, month in enumerate(months):
        previous_month = months[idx + 1] if idx + 1 < len(months) else None
        render_month(month, previous_month)

    render_archive(months)

    print()
    print("🏁 Site render complete")


if __name__ == "__main__":
    main()
