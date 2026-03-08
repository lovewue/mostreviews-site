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
LEADERBOARDS_ROOT = DATA_DIR / "derived" / "leaderboards"

TEMPLATES_DIR = PROJECT_ROOT / "templates"
PARTIALS_DIR = TEMPLATES_DIR / "partials"

STATIC_SRC = PROJECT_ROOT / "static"

OUTPUT_ROOT = PROJECT_ROOT / "site"
STATIC_DST = OUTPUT_ROOT / "static"


# -----------------------------------------------------------------------------
# Template loading
# -----------------------------------------------------------------------------
def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


BASE_TEMPLATE = load_text(TEMPLATES_DIR / "base.html")
HEADER_TEMPLATE = load_text(PARTIALS_DIR / "header.html")
FOOTER_TEMPLATE = load_text(PARTIALS_DIR / "footer.html")


def render_page(title: str, content: str, static_path: str) -> str:
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
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_html(path: Path, html: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def format_month(month: str) -> str:
    dt = datetime.strptime(month, "%Y-%m")
    return dt.strftime("%B %Y")


def format_percent(value) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "0.0%"


def get_month_dirs():
    months = []
    if not DERIVED_ROOT.exists():
        return months

    for p in DERIVED_ROOT.iterdir():
        if p.is_dir():
            months.append(p.name)

    months.sort(reverse=True)
    return months


def top_n_with_ties(products, limit, value_key):
    if not limit or len(products) <= limit:
        return products

    cutoff_value = products[limit - 1].get(value_key) or 0
    return [p for p in products if (p.get(value_key) or 0) >= cutoff_value]


# -----------------------------------------------------------------------------
# Rank helpers
# -----------------------------------------------------------------------------
def add_dense_ranks(products, value_key):
    ranked = []

    prev_value = None
    prev_rank = 0

    for i, p in enumerate(products, start=1):
        value = p.get(value_key) or 0

        if value == prev_value:
            rank = prev_rank
        else:
            rank = i

        item = dict(p)
        item["rank"] = rank
        ranked.append(item)

        prev_value = value
        prev_rank = rank

    return ranked


def build_rank_lookup(products):
    ranked = add_dense_ranks(products, value_key="review_count_month")
    return {p["sku"]: p["rank"] for p in ranked if p.get("sku")}


def apply_rank_movement(products, previous_rank_lookup):
    ranked = add_dense_ranks(products, value_key="review_count_month")
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


# -----------------------------------------------------------------------------
# Copy static
# -----------------------------------------------------------------------------
def copy_static():
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
def render_monthly_stats(summary):
    total_reviews = summary.get("total_reviews_month", 0)
    products_reviewed = summary.get("product_count_with_reviews", 0)
    products_with_5_plus = summary.get("products_with_5_plus_reviews", 0)
    avg_reviews = summary.get("average_reviews_per_product", 0)
    top_100_share = summary.get("top_100_share_of_reviews", 0)

    return f"""
<div class="stats">
    <div class="stat">
        <div class="stat-label">Total reviews</div>
        <div class="stat-value">{total_reviews:,}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Products reviewed</div>
        <div class="stat-value">{products_reviewed:,}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Products with 5+ reviews</div>
        <div class="stat-value">{products_with_5_plus:,}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Average reviews per product</div>
        <div class="stat-value">{avg_reviews:.1f}</div>
    </div>
</div>

<p class="stats-note">
    Top 100 share of reviews: <strong>{format_percent(top_100_share)}</strong>
</p>
"""


def render_leaderboard_stats(
    total_reviews,
    total_products_reviewed,
    threshold_label,
    threshold_value,
    average_reviews_per_product,
    top_100_share_of_reviews,
):
    return f"""
<div class="stats">
    <div class="stat">
        <div class="stat-label">Total reviews</div>
        <div class="stat-value">{total_reviews:,}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Total products reviewed</div>
        <div class="stat-value">{total_products_reviewed:,}</div>
    </div>
    <div class="stat">
        <div class="stat-label">{threshold_label}</div>
        <div class="stat-value">{threshold_value:,}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Average reviews per product</div>
        <div class="stat-value">{average_reviews_per_product:.1f}</div>
    </div>
</div>

<p class="stats-note">
    Top 100 share of reviews: <strong>{format_percent(top_100_share_of_reviews)}</strong>
</p>
"""


def render_products(products, limit=None, show_last_month=False):
    if limit:
        products = top_n_with_ties(products, limit, value_key="review_count_month")

    if not products or "rank" not in products[0]:
        products = add_dense_ranks(products, value_key="review_count_month")

    rows = []

    for idx, p in enumerate(products):
        rank_num = p.get("rank", "")

        same_as_prev = (
            idx > 0 and
            (p.get("review_count_month") or 0) == (products[idx - 1].get("review_count_month") or 0)
        )
        rank_display = f"{rank_num}=" if same_as_prev else str(rank_num)

        name = p.get("name") or f"Product {p.get('sku')}"
        seller = p.get("seller_name") or "Unknown brand"
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
            last_month_cell = (
                f'<td class="last-month rank-change {movement_class}">{movement_label}</td>'
            )

        rows.append(
            f"""
<tr>
    <td class="rank">{rank_display}</td>
    <td>
        {name_html}
        <div class="partner">{seller}</div>
    </td>
    <td class="reviews">{reviews:,}</td>
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
    rows = []

    for i, p in enumerate(partners[:limit], start=1):
        seller_name = p.get("seller_name") or p.get("seller_slug") or "Unknown brand"
        reviews = p.get("total_reviews_month") or 0

        rows.append(
            f"""
<tr>
    <td class="rank">{i}</td>
    <td>{seller_name}</td>
    <td class="reviews">{reviews:,}</td>
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


def render_leaderboard_products(items, limit=100, last_month=False, link_only_if_available=False):
    if limit:
        items = top_n_with_ties(items, limit, value_key="reviews")

    if not items or "rank" not in items[0]:
        items = add_dense_ranks(items, value_key="reviews")

    rows = []

    for idx, p in enumerate(items):
        rank_num = p.get("rank", "")

        same_as_prev = (
            idx > 0 and
            (p.get("reviews") or 0) == (items[idx - 1].get("reviews") or 0)
        )
        rank_display = f"{rank_num}=" if same_as_prev else str(rank_num)

        name = p.get("name") or f"Product {p.get('sku')}"
        seller = p.get("seller_name") or "Unknown brand"
        reviews = p.get("reviews") or 0
        url = p.get("product_url")
        available = p.get("available")

        should_link = False
        if link_only_if_available:
            should_link = bool(url and available is True)
        else:
            should_link = bool(url)

        if should_link:
            name_html = f'<a href="{url}">{name}</a>'
        else:
            name_html = name

        last_month_cell = ""
        if last_month:
            movement_label = p.get("movement_label", "")
            movement_class = p.get("movement_class", "")
            last_month_cell = (
                f'<td class="last-month rank-change {movement_class}">{movement_label}</td>'
            )

        rows.append(
            f"""
<tr>
    <td class="rank">{rank_display}</td>
    <td>
        {name_html}
        <div class="partner">{seller}</div>
    </td>
    <td class="reviews">{reviews:,}</td>
    {last_month_cell}
</tr>
"""
        )

    last_month_header = "<th>Last Month</th>" if last_month else ""

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
    top_products = top_n_with_ties(products, 20, value_key="review_count_month")

    body = f"""
<h1>Trending Products on NOTHS</h1>

<p>
Snapshot for <strong>{title_month}</strong>.
</p>

{render_monthly_stats(summary)}

<h2>Top Products</h2>
<p><small>Showing top 20 including ties ({len(top_products)} products shown).</small></p>

{render_products(products, limit=20, show_last_month=bool(previous_month))}

<h2>Top Brands</h2>

{render_partners(partners, 10)}

<h2>Explore More</h2>

<ul>
    <li><a href="top-products-all-time.html">Top 100 Products of All Time</a></li>
    <li><a href="top-products-last-12-months.html">Top 100 Products of the Last 12 Months</a></li>
    <li><a href="archive.html">Monthly archive</a></li>
</ul>
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
    top_products = top_n_with_ties(products, 50, value_key="review_count_month")

    body = f"""
<h1>Trending Products – {title_month}</h1>

<p>
Products ranked by number of reviews received during the month.
</p>

{render_monthly_stats(summary)}

<h2>Top Products</h2>
<p><small>Showing top 50 including ties ({len(top_products)} products shown).</small></p>

{render_products(products, limit=50, show_last_month=bool(previous_month))}

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
        month_dir = DERIVED_ROOT / m
        summary_file = month_dir / "summary.json"
        summary = load_json(summary_file) if summary_file.exists() else {}

        total_reviews = summary.get("total_reviews_month", 0)
        label = format_month(m)
        rows.append(f'<li><a href="months/{m}.html">{label}</a> – {total_reviews:,} reviews</li>')

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


def render_top_products_all_time():
    leaderboard_file = LEADERBOARDS_ROOT / "top_products_all_time.json"
    if not leaderboard_file.exists():
        print("⚠️ top_products_all_time.json not found")
        return

    data = load_json(leaderboard_file)
    items = data.get("items", [])

    top_items = top_n_with_ties(items, 100, value_key="reviews")

    body = f"""
<h1>Top 100 Products of All Time</h1>

<p>
The products with the highest recorded Feefo review counts on Not On The High Street.
</p>

{render_leaderboard_stats(
    total_reviews=data.get("total_reviews", 0),
    total_products_reviewed=data.get("total_products_reviewed", len(items)),
    threshold_label="Products with 500+ reviews",
    threshold_value=data.get("products_with_500_plus_reviews", 0) or 0,
    average_reviews_per_product=data.get("average_reviews_per_product", 0) or 0,
    top_100_share_of_reviews=data.get("top_100_share_of_reviews", 0) or 0,
)}

<h2>Leaderboard</h2>
<p><small>Showing top 100 including ties. Product links are shown only where the item is still available.</small></p>

{render_leaderboard_products(items, limit=100, last_month=False, link_only_if_available=True)}

<p>
    <a href="index.html">← Back to homepage</a>
</p>
"""

    html = render_page("Top 100 Products of All Time", body, "static")
    save_html(OUTPUT_ROOT / "top-products-all-time.html", html)

    print("✅ top-products-all-time rendered")


def render_top_products_last_12_months(latest_month=None, previous_month=None):
    leaderboard_file = LEADERBOARDS_ROOT / "top_products_last_12_months.json"
    if not leaderboard_file.exists():
        print("⚠️ top_products_last_12_months.json not found")
        return

    data = load_json(leaderboard_file)
    items = data.get("items", [])

    previous_rank_lookup = {}
    if previous_month:
        prev_dir = DERIVED_ROOT / previous_month
        if prev_dir.exists():
            prev_products = load_json(prev_dir / "enriched_products.json")
            previous_rank_lookup = build_rank_lookup(prev_products)

    if previous_rank_lookup:
        converted = []
        for item in items:
            converted.append(
                {
                    **item,
                    "review_count_month": item.get("reviews"),
                }
            )
        moved = apply_rank_movement(converted, previous_rank_lookup)

        items = []
        for item in moved:
            row = dict(item)
            row["reviews"] = row.get("review_count_month")
            row.pop("review_count_month", None)
            items.append(row)
    else:
        items = add_dense_ranks(items, value_key="reviews")

    top_items = top_n_with_ties(items, 100, value_key="reviews")
    title_suffix = f" – {format_month(latest_month)}" if latest_month else ""

    body = f"""
<h1>Top 100 Products of the Last 12 Months</h1>

<p>
The products with the highest recorded Feefo review counts over the last 12 months.
</p>

{render_leaderboard_stats(
    total_reviews=data.get("total_reviews", 0),
    total_products_reviewed=data.get("total_products_reviewed", len(items)),
    threshold_label="Products with 10+ reviews",
    threshold_value=data.get("products_with_10_plus_reviews", 0) or 0,
    average_reviews_per_product=data.get("average_reviews_per_product", 0) or 0,
    top_100_share_of_reviews=data.get("top_100_share_of_reviews", 0) or 0,
)}

<h2>Leaderboard</h2>
<p><small>Showing top 100 including ties.</small></p>

{render_leaderboard_products(items, limit=100, last_month=bool(previous_rank_lookup), link_only_if_available=False)}

<p>
    <a href="index.html">← Back to homepage</a>
</p>
"""

    html = render_page(f"Top 100 Products of the Last 12 Months{title_suffix}", body, "static")
    save_html(OUTPUT_ROOT / "top-products-last-12-months.html", html)

    print("✅ top-products-last-12-months rendered")


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
    previous_for_homepage = months[1] if len(months) > 1 else None

    print(f"📊 Latest month: {latest}")
    print()

    render_homepage(latest, previous_for_homepage)

    for idx, month in enumerate(months):
        previous_month = months[idx + 1] if idx + 1 < len(months) else None
        render_month(month, previous_month)

    render_archive(months)
    render_top_products_all_time()
    render_top_products_last_12_months(latest, previous_for_homepage)

    print()
    print("🏁 Site render complete")


if __name__ == "__main__":
    main()
