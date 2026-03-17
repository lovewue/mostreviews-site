import json
import shutil
from pathlib import Path
from datetime import datetime
from urllib.parse import quote


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DERIVED_ROOT = DATA_DIR / "derived" / "monthly"
LEADERBOARDS_ROOT = DATA_DIR / "derived" / "leaderboards"
PUBLISHED_ROOT = DATA_DIR / "published"

TEMPLATES_DIR = PROJECT_ROOT / "templates"
PARTIALS_DIR = TEMPLATES_DIR / "partials"

STATIC_SRC = PROJECT_ROOT / "static"

OUTPUT_ROOT = PROJECT_ROOT / "docs"
STATIC_DST = OUTPUT_ROOT / "static"


# -----------------------------------------------------------------------------
# Template loading
# -----------------------------------------------------------------------------
def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


BASE_TEMPLATE = load_text(TEMPLATES_DIR / "base.html")
HEADER_TEMPLATE = load_text(PARTIALS_DIR / "header.html")
FOOTER_TEMPLATE = load_text(PARTIALS_DIR / "footer.html")
HOMEPAGE_TEMPLATE = load_text(TEMPLATES_DIR / "homepage.html")

BRANDS_INDEX_TEMPLATE = load_text(TEMPLATES_DIR / "brands-index.html")
BRANDS_TOP_100_TEMPLATE = load_text(TEMPLATES_DIR / "brands-top-100.html")
BRAND_TEMPLATE = load_text(TEMPLATES_DIR / "brand.html")

ABOUT_TEMPLATE = load_text(TEMPLATES_DIR / "about.html")


def render_page(
    title: str,
    content: str,
    static_path: str,
    root_path: str,
    meta_description: str = "",
    canonical: str = "",
) -> str:
    html = BASE_TEMPLATE

    header_html = (
        HEADER_TEMPLATE
        .replace("{{STATIC}}", static_path)
        .replace("{{ static }}", static_path)
        .replace("{{ROOT}}", root_path)
        .replace("{{ root }}", root_path)
    )

    footer_html = (
        FOOTER_TEMPLATE
        .replace("{{STATIC}}", static_path)
        .replace("{{ static }}", static_path)
        .replace("{{ROOT}}", root_path)
        .replace("{{ root }}", root_path)
    )

    # Uppercase placeholders
    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{HEADER}}", header_html)
    html = html.replace("{{FOOTER}}", footer_html)
    html = html.replace("{{CONTENT}}", content)
    html = html.replace("{{STATIC}}", static_path)
    html = html.replace("{{ROOT}}", root_path)
    html = html.replace("{{META_DESCRIPTION}}", meta_description or title)
    html = html.replace("{{CANONICAL}}", canonical)

    # Lowercase placeholders
    html = html.replace("{{ title }}", title)
    html = html.replace("{{ header }}", header_html)
    html = html.replace("{{ footer }}", footer_html)
    html = html.replace("{{ content }}", content)
    html = html.replace("{{ static }}", static_path)
    html = html.replace("{{ root }}", root_path)
    html = html.replace("{{ meta_description }}", meta_description or title)
    html = html.replace("{{ canonical }}", canonical)

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


def format_int(value) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"


def coerce_int(*values, default=0):
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except Exception:
            try:
                return int(float(value))
            except Exception:
                continue
    return default


def normalise_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(normalise_text(v) for v in value if normalise_text(v))
    if isinstance(value, dict):
        return ", ".join(normalise_text(v) for v in value.values() if normalise_text(v))
    return str(value).strip()


# -----------------------------------------------------------------------------
# Rank / review helpers
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


def build_review_lookup(products):
    return {
        p["sku"]: (p.get("review_count_month") or 0)
        for p in products
        if p.get("sku")
    }


def apply_rank_movement(products, previous_review_lookup):
    ranked = add_dense_ranks(products, value_key="review_count_month")
    enriched = []

    for p in ranked:
        item = dict(p)

        sku = item.get("sku")
        current_reviews = item.get("review_count_month") or 0
        previous_reviews = previous_review_lookup.get(sku, 0)

        item["previous_reviews"] = previous_reviews

        if current_reviews > previous_reviews:
            item["movement_label"] = "▲"
            item["movement_class"] = "up"
        elif current_reviews < previous_reviews:
            item["movement_label"] = "▼"
            item["movement_class"] = "down"
        else:
            item["movement_label"] = "–"
            item["movement_class"] = "same"

        enriched.append(item)

    return enriched


# -----------------------------------------------------------------------------
# URL / AWIN helpers
# -----------------------------------------------------------------------------
def build_brand_url(slug: str) -> str:
    if not slug:
        return ""
    return f"https://www.notonthehighstreet.com/partners/{slug}"


def build_awin_link(slug: str, clickref: str = "TrendList") -> str:
    if not slug:
        return ""
    destination = build_brand_url(slug)
    encoded_destination = quote(destination, safe="")
    return (
        "https://www.awin1.com/cread.php"
        f"?awinmid=18484&awinaffid=1018637&clickref={clickref}&ued={encoded_destination}"
    )


def build_awin_product_link(product_url: str, clickref: str = "TrendListProduct") -> str:
    product_url = (product_url or "").strip()
    if not product_url:
        return ""

    encoded_destination = quote(product_url, safe="")
    return (
        "https://www.awin1.com/cread.php"
        f"?awinmid=18484&awinaffid=1018637&clickref={clickref}&ued={encoded_destination}"
    )


def slugify_brand_name(name: str) -> str:
    return (
        (name or "").strip().lower()
        .replace("&", "and")
        .replace("’", "")
        .replace("'", "")
        .replace(".", "")
        .replace(",", "")
        .replace("/", "-")
        .replace(" ", "-")
    )


# -----------------------------------------------------------------------------
# Brand helpers
# -----------------------------------------------------------------------------
def load_brands():
    brands_file = PUBLISHED_ROOT / "brands.json"
    if not brands_file.exists():
        print("⚠️ brands.json not found")
        return []

    brands = load_json(brands_file)
    if not isinstance(brands, list):
        print("⚠️ brands.json is not a list")
        return []

    cleaned = []

    for b in brands:
        if not isinstance(b, dict):
            continue

        item = dict(b)
        stats = item.get("stats", {}) or {}
        urls = item.get("urls", {}) or {}

        slug = normalise_text(
            item.get("slug")
            or item.get("seller_slug")
            or ""
        ).lower()

        name = normalise_text(
            item.get("name")
            or item.get("seller_name")
            or slug
        )

        product_count = coerce_int(
            item.get("product_count"),
            stats.get("product_count"),
            item.get("products"),
            item.get("product_total"),
            item.get("count"),
            default=0,
        )

        brand_review_count = coerce_int(
            item.get("brand_review_count"),
            stats.get("brand_review_count"),
            item.get("reviews"),
            item.get("review_count"),
            item.get("total_reviews"),
            default=0,
        )

        order_volume_numeric = coerce_int(
            item.get("order_volume_numeric"),
            stats.get("order_volume_numeric"),
            default=0,
        )

        active_raw = item.get("active")
        active = True if active_raw is None else bool(active_raw)

        location = normalise_text(item.get("location", ""))
        tenure_label = normalise_text(
            item.get("tenure_label")
            or stats.get("tenure_label")
            or ""
        )
        order_volume_label = normalise_text(
            item.get("order_volume_label")
            or stats.get("order_volume_label")
            or ""
        )
        brand_url = normalise_text(
            item.get("brand_url")
            or item.get("url")
            or urls.get("brand")
            or build_brand_url(slug)
        )

        awin = build_awin_link(slug, clickref="TrendList")

        inferred_inactive = (product_count == 0 and not location)
        inactive = (not active) or inferred_inactive

        cleaned_item = {
            **item,
            "slug": slug,
            "name": name,
            "active": active,
            "inactive": inactive,
            "product_count": product_count,
            "brand_review_count": brand_review_count,
            "order_volume_numeric": order_volume_numeric,
            "location": location,
            "tenure_label": tenure_label,
            "order_volume_label": order_volume_label,
            "awin": awin,
            "brand_url": brand_url,
        }

        if cleaned_item["slug"]:
            cleaned.append(cleaned_item)

    print(f"✅ loaded {len(cleaned)} brands")
    if cleaned:
        print("First brand sample:", cleaned[0])

    return cleaned


def get_active_brands(brands):
    return [b for b in brands if b.get("slug")]


def get_top_brands(brands, limit=100):
    active = get_active_brands(brands)

    ranked = [b for b in active if b.get("order_volume_numeric", 0) > 0]

    ranked.sort(
        key=lambda b: (
            -int(b.get("order_volume_numeric", 0) or 0),
            -int(b.get("brand_review_count", 0) or 0),
            -int(b.get("product_count", 0) or 0),
            (b.get("name", "") or "").lower(),
        )
    )

    return ranked[:limit]


# -----------------------------------------------------------------------------
# Brand page rendering helpers
# -----------------------------------------------------------------------------
def get_brand_initial(name):
    first = (name or "").strip()[:1].upper()
    if first.isalpha():
        return first
    return "#"


def render_brand_az_nav(brands):
    initials = sorted({get_brand_initial(b.get("name", "")) for b in brands})

    links = []
    for initial in initials:
        links.append(f'<a href="#letter-{initial}">{initial}</a>')

    return '<div class="az-nav">' + "".join(links) + "</div>"


def render_brands_az_sections(brands):
    grouped = {}

    for brand in brands:
        initial = get_brand_initial(brand.get("name", ""))
        grouped.setdefault(initial, []).append(brand)

    sections = []

    for initial in sorted(grouped.keys()):
        cards = []

        for brand in grouped[initial]:
            display_name = brand["name"] + ("*" if brand.get("inactive") else "")
            product_count = "" if brand.get("inactive") else format_int(brand.get("product_count", 0))
            review_count = "" if brand.get("inactive") else format_int(brand.get("brand_review_count", 0))
            location = "" if brand.get("inactive") else brand.get("location", "")

            location_html = f"<li>{location}</li>" if location else ""

            cards.append(
                f"""
<div class="brand-card">
  <h3><a href="brands/{brand['slug']}/index.html">{display_name}</a></h3>
  <ul class="brand-meta">
    <li><strong>Products:</strong> {product_count}</li>
    <li><strong>Reviews:</strong> {review_count}</li>
    {location_html}
  </ul>
</div>
""".strip()
            )

        sections.append(
            f"""
<section class="brand-letter-section" id="letter-{initial}">
  <h2>{initial}</h2>
  <div class="brands-grid">
    {"".join(cards)}
  </div>
</section>
""".strip()
        )

    return "\n".join(sections)


def render_brands_index(brands):
    active = get_active_brands(brands)
    active.sort(key=lambda b: (b.get("name", "") or "").lower())

    body = BRANDS_INDEX_TEMPLATE
    body = body.replace("{{BRAND_COUNT}}", format_int(len(active)))
    body = body.replace("{{AZ_NAV}}", render_brand_az_nav(active))
    body = body.replace("{{BRAND_SECTIONS}}", render_brands_az_sections(active))

    html = render_page(
        "Independent Brands on NOTHS",
        body,
        "static",
        "",
        "Browse brands A–Z on The Trend List.",
    )
    save_html(OUTPUT_ROOT / "brands.html", html)

    print("✅ brand index rendered")


def render_top_brands_rows(brands):
    rows = []

    for idx, brand in enumerate(brands, start=1):
        display_name = brand["name"] + ("*" if brand.get("inactive") else "")
        product_count_value = "" if brand.get("inactive") else format_int(brand.get("product_count", 0))
        location_value = "" if brand.get("inactive") else brand.get("location", "")
        review_count_value = "" if brand.get("inactive") else format_int(brand.get("brand_review_count", 0))

        rows.append(
            f"""
<tr>
  <td class="rank">{idx}</td>
  <td><a href="brands/{brand['slug']}/index.html">{display_name}</a></td>
  <td>{brand.get('order_volume_label', '')}</td>
  <td class="reviews">{review_count_value}</td>
  <td>{product_count_value}</td>
  <td>{location_value}</td>
  <td>{brand.get('tenure_label', '')}</td>
</tr>
""".strip()
        )

    return "\n".join(rows)


def render_brands_top_100(brands):
    top_brands = get_top_brands(brands, limit=100)

    body = BRANDS_TOP_100_TEMPLATE
    body = body.replace("{{ brand_rows }}", render_top_brands_rows(top_brands))

    html = render_page(
        "Top Brands on NOTHS",
        body,
        "static",
        "",
        "Top 100 brands on NOTHS ranked by total order volume.",
    )
    save_html(OUTPUT_ROOT / "top-100-brands.html", html)

    print("✅ top 100 brands rendered")


def render_brand_pages(brands):
    active = get_active_brands(brands)

    for brand in active:
        body = BRAND_TEMPLATE

        display_name = brand["name"] + ("*" if brand.get("inactive") else "")
        product_count_value = "" if brand.get("inactive") else format_int(brand.get("product_count", 0))
        review_count_value = "" if brand.get("inactive") else format_int(brand.get("brand_review_count", 0))
        location_value = "" if brand.get("inactive") else str(brand.get("location", "") or "")
        order_volume_value = str(brand.get("order_volume_label", "") or "")

        cta = ""
        destination = str(brand.get("awin", brand.get("brand_url", "")) or "")
        if destination and not brand.get("inactive"):
            cta = f'<p><a class="button" href="{destination}" target="_blank" rel="noopener sponsored">Visit {brand.get("name", "")}</a></p>'

        inactive_note = "<p><em>* Brand no longer on NOTHS.</em></p>" if brand.get("inactive") else ""

        body = body.replace("{{ brand_name }}", display_name)
        body = body.replace("{{ order_volume }}", order_volume_value)
        body = body.replace("{{ reviews }}", review_count_value)
        body = body.replace("{{ products }}", product_count_value)
        body = body.replace("{{ location }}", location_value)
        body = body.replace("{{ tenure }}", str(brand.get("tenure_label", "") or ""))
        body = body.replace("{{ cta }}", cta)
        body = body.replace("{{ inactive_note }}", inactive_note)

        html = render_page(
            f"{brand.get('name', '')} | NOTHS Brand Profile",
            body,
            "../../static",
            "../../",
            f"{brand.get('name', '')} brand profile on The Trend List.",
        )
        save_html(OUTPUT_ROOT / "brands" / brand["slug"] / "index.html", html)

    print(f"✅ {len(active)} brand pages rendered")


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
        available = p.get("available", True)

        awin_url = build_awin_product_link(url, clickref="TrendListProduct")

        display_name = name + ("*" if available is False else "")

        if awin_url and available:
            name_html = f'<a href="{awin_url}" target="_blank" rel="noopener sponsored">{display_name}</a>'
        else:
            name_html = display_name

        last_month_cell = ""
        if show_last_month:
            previous_reviews = p.get("previous_reviews", 0)
            movement_label = p.get("movement_label", "")
            movement_class = p.get("movement_class", "")

            previous_reviews_html = f"{previous_reviews:,}"

            last_month_cell = (
                f'<td class="last-month">'
                f'{previous_reviews_html} '
                f'<span class="rank-change {movement_class}">{movement_label}</span>'
                f'</td>'
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

    last_month_header = '<th class="last-month">Previous Month</th>' if show_last_month else ""

    return f"""
<div class="table-scroll">
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


def render_partners(partners, limit=10, brand_link_prefix="brands/"):
    rows = []

    for i, p in enumerate(partners[:limit], start=1):
        seller_name = p.get("seller_name") or p.get("seller_slug") or "Unknown brand"
        seller_slug = p.get("seller_slug") or slugify_brand_name(seller_name)
        reviews = p.get("total_reviews_month") or 0

        seller_html = f'<a href="{brand_link_prefix}{seller_slug}/index.html">{seller_name}</a>'

        rows.append(
            f"""
<tr>
    <td class="rank">{i}</td>
    <td>{seller_html}</td>
    <td class="reviews">{reviews:,}</td>
</tr>
"""
        )

    return f"""
<div class="table-scroll">
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

        should_link = bool(url and available is True) if link_only_if_available else bool(url)
        awin_url = build_awin_product_link(url, clickref="TrendListProduct")

        if should_link and awin_url:
            name_html = f'<a href="{awin_url}" target="_blank" rel="noopener sponsored">{name}</a>'
        else:
            name_html = name

        last_month_cell = ""
        if last_month:
            movement_label = p.get("movement_label", "")
            movement_class = p.get("movement_class", "")
            last_month_cell = f'<td class="last-month rank-change {movement_class}">{movement_label}</td>'

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

    previous_review_lookup = {}
    if previous_month:
        prev_dir = DERIVED_ROOT / previous_month
        prev_products = load_json(prev_dir / "enriched_products.json")
        previous_review_lookup = build_review_lookup(prev_products)

    products = apply_rank_movement(products, previous_review_lookup)

    title_month = format_month(latest_month)
    top_products = top_n_with_ties(products, 20, value_key="review_count_month")

    body = HOMEPAGE_TEMPLATE
    body = body.replace("{{MONTH}}", title_month)
    body = body.replace("{{MONTHLY_STATS}}", render_monthly_stats(summary))
    body = body.replace("{{TOP_PRODUCTS_COUNT}}", str(len(top_products)))
    body = body.replace(
        "{{TOP_PRODUCTS}}",
        render_products(products, limit=20, show_last_month=bool(previous_month))
    )
    body = body.replace("{{TOP_BRANDS}}", render_partners(partners, 10, brand_link_prefix="brands/"))

    html = render_page(
        "Trending Products on NOTHS",
        body,
        "static",
        "",
        "Trending products on Not On The High Street based on recent reviews.",
    )
    save_html(OUTPUT_ROOT / "index.html", html)

    print("✅ homepage rendered")


def render_month(month, previous_month=None):
    month_dir = DERIVED_ROOT / month

    products = load_json(month_dir / "enriched_products.json")
    partners = load_json(month_dir / "partners_summary.json")
    summary = load_json(month_dir / "summary.json")

    previous_review_lookup = {}
    if previous_month:
        prev_dir = DERIVED_ROOT / previous_month
        prev_products = load_json(prev_dir / "enriched_products.json")
        previous_review_lookup = build_review_lookup(prev_products)

    products = apply_rank_movement(products, previous_review_lookup)

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

<p class="table-note">* Product no longer available on NOTHS</p>

<h2>Top Brands</h2>

{render_partners(partners, 20, brand_link_prefix="../brands/")}

<p>
    <a href="../index.html">← Back to homepage</a>
</p>
"""

    html = render_page(
        f"Trending Products – {title_month}",
        body,
        "../static",
        "../",
        f"Trending products on NOTHS for {title_month}.",
    )
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

    html = render_page(
        "Monthly Archive",
        body,
        "static",
        "",
        "Monthly archive of trending products on NOTHS.",
    )
    save_html(OUTPUT_ROOT / "archive.html", html)

    print("✅ archive rendered")


def render_top_products_all_time():
    leaderboard_file = LEADERBOARDS_ROOT / "top_products_all_time.json"
    if not leaderboard_file.exists():
        print("⚠️ top_products_all_time.json not found")
        return

    data = load_json(leaderboard_file)
    items = data.get("items", [])

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

    html = render_page(
        "Top 100 Products of All Time",
        body,
        "static",
        "",
        "Top 100 products of all time on NOTHS.",
    )
    save_html(OUTPUT_ROOT / "top-products-all-time.html", html)

    print("✅ top-products-all-time rendered")


def render_top_products_last_12_months(latest_month=None, previous_month=None):
    leaderboard_file = LEADERBOARDS_ROOT / "top_products_last_12_months.json"
    if not leaderboard_file.exists():
        print("⚠️ top_products_last_12_months.json not found")
        return

    data = load_json(leaderboard_file)
    items = data.get("items", [])

    items = add_dense_ranks(items, value_key="reviews")

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

{render_leaderboard_products(items, limit=100, last_month=False, link_only_if_available=False)}

<p>
    <a href="index.html">← Back to homepage</a>
</p>
"""

    html = render_page(
        f"Top 100 Products of the Last 12 Months{title_suffix}",
        body,
        "static",
        "",
        "Top 100 products on NOTHS over the last 12 months.",
    )
    save_html(OUTPUT_ROOT / "top-products-last-12-months.html", html)

    print("✅ top-products-last-12-months rendered")

# -----------------------------------------------------------------------------
# About page rendering
# -----------------------------------------------------------------------------    

def render_about():
    body = ABOUT_TEMPLATE

    html = render_page(
        "About The Trend List",
        body,
        "static",
        "How The Trend List tracks trending products and brands on Not On The High Street."
    )

    save_html(OUTPUT_ROOT / "about.html", html)

    print("✅ about page rendered")

# -----------------------------------------------------------------------------
# Sitemap rendering
# -----------------------------------------------------------------------------

def generate_sitemap(months, brands):

    base_url = "https://trendlist.co.uk"

    urls = []

    # Core pages
    urls.append(f"{base_url}/")
    urls.append(f"{base_url}/top-products-last-12-months.html")
    urls.append(f"{base_url}/top-products-all-time.html")
    urls.append(f"{base_url}/top-100-brands.html")
    urls.append(f"{base_url}/brands.html")
    urls.append(f"{base_url}/archive.html")

    # Monthly pages
    for m in months:
        urls.append(f"{base_url}/months/{m}.html")

    # Brand pages
    for brand in brands:
        slug = brand.get("slug")
        if slug:
            urls.append(f"{base_url}/brands/{slug}/")

    # Build XML
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for url in urls:
        xml.append("  <url>")
        xml.append(f"    <loc>{url}</loc>")
        xml.append("  </url>")

    xml.append("</urlset>")

    sitemap = "\n".join(xml)

    save_html(OUTPUT_ROOT / "sitemap.xml", sitemap)

    print("✅ sitemap.xml generated")


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

    brands = load_brands()
    print(f"Brands loaded: {len(brands)}")

    if brands:
        render_brands_index(brands)
        render_brands_top_100(brands)
        render_brand_pages(brands)

    render_about()     

    generate_sitemap(months, brands)

    print()
    print("🏁 Site render complete")


if __name__ == "__main__":
    main()
