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


BASE_TEMPLATE = load_text(TEMPLATES_DIR / "legacy-base.html")
HEADER_TEMPLATE = load_text(PARTIALS_DIR / "header.html")
FOOTER_TEMPLATE = load_text(PARTIALS_DIR / "footer.html")
HOMEPAGE_TEMPLATE = load_text(TEMPLATES_DIR / "homepage.html")

# NOTE: Brand directory templates retired 2026-07 (brands-index.html,
# brands-top-100.html, brand.html) — no longer loaded here.

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


def format_long_date(value: str) -> str:
    """
    '2026-09-19' -> '19th September 2026'.

    Returns the input unchanged if it isn't a date we recognise, so a missing
    or malformed timestamp degrades to whatever was there rather than raising
    mid-render.
    """
    value = (value or "").strip()[:10]
    if not value:
        return ""

    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return value

    day = dt.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

    return f"{day}{suffix} {dt.strftime('%B %Y')}"


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


def clean_product_list(products):
    if not products:
        return []
    return [p for p in products if isinstance(p, dict)]


def top_n_with_ties(products, limit, value_key="reviews"):
    clean_products = clean_product_list(products)

    if not clean_products:
        return []

    clean_products = sorted(
        clean_products,
        key=lambda p: (p.get(value_key) or 0),
        reverse=True
    )

    if len(clean_products) <= limit:
        return clean_products

    cutoff_value = clean_products[limit - 1].get(value_key) or 0
    return [p for p in clean_products if (p.get(value_key) or 0) >= cutoff_value]


def format_int(value) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"


# -----------------------------------------------------------------------------
# Rank / review helpers
# -----------------------------------------------------------------------------
def add_dense_ranks(products, value_key):
    clean_products = clean_product_list(products)

    if not clean_products:
        return []

    ranked = []
    prev_value = None
    current_rank = 0

    for idx, p in enumerate(clean_products, start=1):
        value = p.get(value_key) or 0

        if value != prev_value:
            current_rank = idx
            prev_value = value

        item = dict(p)
        item["rank"] = current_rank
        ranked.append(item)

    return ranked


def build_review_lookup(products):
    clean_products = clean_product_list(products)
    return {
        p["sku"]: (p.get("review_count_month") or 0)
        for p in clean_products
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
    products = clean_product_list(products)

    if limit:
        products = top_n_with_ties(products, limit, value_key="review_count_month")

    if not products:
        rows = []
    else:
        if "rank" not in products[0]:
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
                name_html = f'<a href="{awin_url}">{display_name}</a>'
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
</div>
"""


def is_unresolved_brand(p) -> bool:
    """
    True for partner rows that do not represent a real NOTHS brand.

    build_enriched_monthly.py now drops these before they reach the summary,
    but older derived files still on disk may contain the synthetic
    slug="unknown" / name="Unknown brand" bucket. Rendering that produced a
    fake #1 brand linking to a dead /partners/unknown page, so filter it here
    too rather than relying on the data being freshly rebuilt.
    """
    placeholders = {"", "none", "null", "unknown", "unknown brand", "unknown seller"}
    slug = str(p.get("seller_slug") or "").strip().lower()
    name = str(p.get("seller_name") or "").strip().lower()
    return (not slug) or slug in placeholders or name in placeholders


def render_partners(partners, limit=10):
    # Brands are ranked exactly like products: filter out the placeholder
    # "Unknown brand" bucket first, then take the top N *including ties* so the
    # list never cuts arbitrarily through a block of brands on equal reviews.
    partners = [p for p in partners if not is_unresolved_brand(p)]

    if limit:
        partners = top_n_with_ties(
            partners, limit, value_key="total_reviews_month"
        )

    if partners:
        partners = add_dense_ranks(partners, value_key="total_reviews_month")

    rows = []

    for idx, p in enumerate(partners):
        seller_name = p.get("seller_name") or p.get("seller_slug")
        seller_slug = p.get("seller_slug") or slugify_brand_name(seller_name)
        reviews = p.get("total_reviews_month") or 0

        same_as_prev = (
            idx > 0
            and reviews == (partners[idx - 1].get("total_reviews_month") or 0)
        )

        same_as_next = (
            idx < len(partners) - 1
            and reviews == (partners[idx + 1].get("total_reviews_month") or 0)
        )

        rank_num = p.get("rank", "")
        rank_display = f"{rank_num}=" if (same_as_prev or same_as_next) else str(rank_num)

        # NOTE: previously linked to the retired internal /brands/{slug}/
        # page. Now links straight to the real NOTHS seller page via the
        # existing AWIN affiliate link builder.
        awin_url = build_awin_link(seller_slug)
        seller_html = f'<a href="{awin_url}" target="_blank" rel="sponsored noopener">{seller_name}</a>'

        rows.append(
            f"""
<tr>
    <td class="rank">{rank_display}</td>
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
</div>
"""


def render_leaderboard_products(items, limit=100, last_month=False, link_only_if_available=False):
    items = clean_product_list(items)

    if limit:
        items = top_n_with_ties(items, limit, value_key="reviews")

    if not items:
        rows = []
    else:
        if "rank" not in items[0]:
            items = add_dense_ranks(items, value_key="reviews")

        rows = []

        for idx, p in enumerate(items):
            rank_num = p.get("rank", "")

            same_as_prev = (
                idx > 0 and
                (p.get("reviews") or 0) == (items[idx - 1].get("reviews") or 0)
            )

            same_as_next = (
                idx < len(items) - 1 and
                (p.get("reviews") or 0) == (items[idx + 1].get("reviews") or 0)
            )

            is_tied = same_as_prev or same_as_next

            rank_display = f"{rank_num}=" if is_tied else str(rank_num)

            name = p.get("name") or f"Product {p.get('sku')}"
            seller = p.get("seller_name") or "Unknown brand"
            reviews = p.get("reviews") or 0
            url = p.get("product_url")
            available = p.get("available")

            should_link = bool(url and available is True) if link_only_if_available else bool(url)
            awin_url = build_awin_product_link(url, clickref="TrendListProduct")

            display_name = name + ("*" if available is not True else "")

            should_link = bool(url and available is True) if link_only_if_available else bool(url)

            if should_link and awin_url:
                name_html = f'<a href="{awin_url}">{display_name}</a>'
            else:
                name_html = display_name

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
# Sortable table
# -----------------------------------------------------------------------------
# Self-contained: scoped <style> plus a small vanilla sorter, both emitted with
# the table rather than added to the global stylesheet, so nothing else on the
# site is affected. The page is static HTML on GitHub Pages — there is no
# framework here and no reason to introduce one for 200 rows.
#
# The rank column deliberately keeps its by-orders value when you sort by
# something else, so a row reads "ranked 143rd overall, but look where it sits
# on orders per year". Same for the "=" tie markers: they state a fact about
# order bands, which stays true whatever the row order.
TABLE_SORT_ASSETS = """
<style>
table.sortable th[data-sort] { cursor: pointer; user-select: none; white-space: nowrap; }
table.sortable th[data-sort]:hover { text-decoration: underline; }
table.sortable th[data-sort]::after { content: " \\2195"; opacity: .35; font-size: .85em; }
table.sortable th[aria-sort="ascending"]::after { content: " \\2191"; opacity: 1; }
table.sortable th[aria-sort="descending"]::after { content: " \\2193"; opacity: 1; }
</style>

<script>
(function () {
  var table = document.getElementById("brand-orders");
  if (!table) return;

  var headerRow = table.rows[0];
  var headers = Array.prototype.slice.call(headerRow.cells);

  function sortBy(index, kind, descending) {
    var rows = Array.prototype.slice.call(table.rows, 1);

    rows.sort(function (a, b) {
      var x = a.cells[index], y = b.cells[index];
      var av = x ? x.getAttribute("data-v") : null;
      var bv = y ? y.getAttribute("data-v") : null;

      if (kind === "num") {
        // Missing values (-1) always sink, whichever way the column is sorted,
        // so a brand with no rating never outranks one that has one.
        var an = parseFloat(av), bn = parseFloat(bv);
        if (isNaN(an)) an = -1;
        if (isNaN(bn)) bn = -1;
        if (an < 0 && bn >= 0) return 1;
        if (bn < 0 && an >= 0) return -1;
        return descending ? bn - an : an - bn;
      }

      av = av || ""; bv = bv || "";
      return descending ? bv.localeCompare(av) : av.localeCompare(bv);
    });

    var frag = document.createDocumentFragment();
    rows.forEach(function (r) { frag.appendChild(r); });
    table.appendChild(frag);

    headers.forEach(function (h) { h.removeAttribute("aria-sort"); });
    headers[index].setAttribute("aria-sort", descending ? "descending" : "ascending");
  }

  headers.forEach(function (header, index) {
    var kind = header.getAttribute("data-sort");
    if (!kind) return;

    header.setAttribute("tabindex", "0");
    header.setAttribute("role", "button");

    // Which way a column should go on its FIRST click. Numbers are almost
    // always most useful high-to-low, but rank is the exception — rank 1 is
    // the best rank, so it leads ascending. Declared per column via
    // data-first rather than guessed from the type.
    var firstDescending = header.getAttribute("data-first") !== "asc" && kind === "num";

    function activate() {
      // Clicking the column that is already sorted flips it; clicking a new
      // one starts in that column's natural direction.
      var current = header.getAttribute("aria-sort");
      var descending = current === "descending" ? false
                     : current === "ascending" ? true
                     : firstDescending;
      sortBy(index, kind, descending);
    }

    header.addEventListener("click", activate);
    header.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
    });
  });
})();
</script>
"""


def render_brand_orders_leaderboard(items, limit=100):
    """
    Brands ranked by lifetime orders taken on NOTHS.

    Same tie handling as every other leaderboard here, but the tie block is
    doing more work: NOTHS publishes orders rounded to two significant figures
    ("690K+"), so brands that share a band really are indistinguishable in the
    public data and all get "=".
    """
    items = clean_product_list(items)

    if limit:
        items = top_n_with_ties(items, limit, value_key="orders")

    if items:
        items = add_dense_ranks(items, value_key="orders")

    rows = []

    for idx, b in enumerate(items):
        seller_name = b.get("seller_name") or b.get("seller_slug")
        seller_slug = b.get("seller_slug") or slugify_brand_name(seller_name)

        orders = b.get("orders") or 0
        orders_label = b.get("orders_label") or f"{orders:,}"
        years = b.get("years_on_noths") or 0
        months = b.get("months_on_noths") or (years * 12)
        tenure = b.get("tenure_label") or (f"{years} years" if years else "—")
        rating = b.get("brand_rating")
        per_year = b.get("orders_per_year")
        reviews = b.get("reviews_last_12_months") or 0

        same_as_prev = idx > 0 and orders == (items[idx - 1].get("orders") or 0)
        same_as_next = (
            idx < len(items) - 1 and orders == (items[idx + 1].get("orders") or 0)
        )

        rank_num = b.get("rank", "")
        rank_display = f"{rank_num}=" if (same_as_prev or same_as_next) else str(rank_num)

        # A brand that has stopped trading keeps its lifetime orders but must
        # not be linked — same convention as the product leaderboards. Note
        # this tests "trading", not "active": most brands that stop selling on
        # NOTHS leave the storefront up and empty rather than removing it, so
        # linking on "the page still loads" sends buyers to an empty shop.
        is_open = b.get("trading") is not False

        if is_open:
            awin_url = build_awin_link(seller_slug)
            seller_html = (
                f'<a href="{awin_url}" target="_blank" rel="sponsored noopener">{seller_name}</a>'
            )
        else:
            seller_html = f"{seller_name}*"

        rating_html = f"{rating:.1f}" if rating else "—"
        per_year_html = f"{int(per_year):,}" if per_year else "—"

        # data-v carries the raw number for every sortable cell. The visible
        # text is a rounded band ("690K+"), a formatted count or an em dash,
        # none of which sort correctly as strings — "1.4M+" would land between
        # "130K+" and "22K+". The sorter reads data-v and never the text.
        rows.append(
            f"""
<tr>
    <td class="rank" data-v="{rank_num or 0}">{rank_display}</td>
    <td data-v="{(seller_name or '').lower()}">{seller_html}</td>
    <td class="reviews" data-v="{orders}">{orders_label}</td>
    <td class="reviews col-peryear" data-v="{int(per_year) if per_year else -1}">{per_year_html}</td>
    <td class="reviews col-tenure" data-v="{months if months else -1}">{tenure}</td>
    <td class="reviews col-rating" data-v="{rating if rating else -1}">{rating_html}</td>
    <td class="reviews col-reviews" data-v="{reviews}">{reviews:,}</td>
</tr>
"""
        )

    return f"""
<div class="table-scroll">
<table id="brand-orders" class="sortable">
    <tr>
        <th data-sort="num" data-first="asc" title="Rank by total orders">#</th>
        <th data-sort="text">Brand</th>
        <th data-sort="num" aria-sort="descending">Orders</th>
        <th data-sort="num" class="col-peryear">Orders / year</th>
        <th data-sort="num" class="col-tenure">On NOTHS</th>
        <th data-sort="num" class="col-rating">Rating</th>
        <th data-sort="num" class="col-reviews">Reviews (last 12 months)</th>
    </tr>
    {''.join(rows)}
</table>
</div>

{TABLE_SORT_ASSETS}
"""


def render_brands_leaderboard(items, limit=100):
    # Same shape as render_leaderboard_products: top N *including ties*, dense
    # ranks, "=" on any brand sharing a review total with its neighbour.
    items = clean_product_list(items)

    if limit:
        items = top_n_with_ties(items, limit, value_key="total_reviews")

    if items:
        items = add_dense_ranks(items, value_key="total_reviews")

    rows = []

    for idx, b in enumerate(items):
        seller_name = b.get("seller_name") or b.get("seller_slug")
        seller_slug = b.get("seller_slug") or slugify_brand_name(seller_name)
        reviews = b.get("total_reviews") or 0
        products = b.get("reviewed_product_count") or b.get("product_count") or 0

        same_as_prev = (
            idx > 0 and reviews == (items[idx - 1].get("total_reviews") or 0)
        )

        same_as_next = (
            idx < len(items) - 1
            and reviews == (items[idx + 1].get("total_reviews") or 0)
        )

        rank_num = b.get("rank", "")
        rank_display = f"{rank_num}=" if (same_as_prev or same_as_next) else str(rank_num)

        awin_url = build_awin_link(seller_slug)
        seller_html = f'<a href="{awin_url}" target="_blank" rel="sponsored noopener">{seller_name}</a>'

        rows.append(
            f"""
<tr>
    <td class="rank">{rank_display}</td>
    <td>{seller_html}</td>
    <td class="reviews">{reviews:,}</td>
    <td class="reviews">{products:,}</td>
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
        <th>Products reviewed</th>
    </tr>
    {''.join(rows)}
</table>
</div>
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
    body = body.replace("{{TOP_BRANDS}}", render_partners(partners, 10))

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
    top_brands = top_n_with_ties(
        [p for p in partners if not is_unresolved_brand(p)],
        50,
        value_key="total_reviews_month",
    )

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

<h2>Brands With Most Reviews</h2>
<p><small>Showing top 50 including ties ({len(top_brands)} brands shown).</small></p>

{render_partners(partners, 50)}

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
    items = clean_product_list(data.get("items", []))

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

<p class="table-note">* No longer available on NOTHS</p>

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
    items = clean_product_list(data.get("items", []))
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
        "",
        "How The Trend List tracks trending products and brands on Not On The High Street."
    )

    save_html(OUTPUT_ROOT / "about.html", html)

    print("✅ about page rendered")


# -----------------------------------------------------------------------------
# Sitemap rendering
# -----------------------------------------------------------------------------
def generate_sitemap(months):
    base_url = "https://trendlist.co.uk"

    urls = []

    # Core pages
    urls.append(f"{base_url}/")
    urls.append(f"{base_url}/top-products-last-12-months.html")
    urls.append(f"{base_url}/top-products-all-time.html")
    urls.append(f"{base_url}/top-brands-last-12-months.html")
    urls.append(f"{base_url}/top-brands-all-time.html")
    urls.append(f"{base_url}/archive.html")
    urls.append(f"{base_url}/about.html")

    # Monthly pages
    for m in months:
        urls.append(f"{base_url}/months/{m}.html")

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
def render_top_brands_last_12_months():
    leaderboard_file = LEADERBOARDS_ROOT / "top_brands_last_12_months.json"

    if not leaderboard_file.exists():
        print("⚠️ top_brands_last_12_months.json not found")
        return

    data = load_json(leaderboard_file)
    items = clean_product_list(data.get("items", []))
    shown = top_n_with_ties(items, 100, value_key="total_reviews")

    brand_count = data.get("brand_count", len(items)) or 0
    total_reviews = data.get("total_reviews", 0) or 0
    top_100_share = data.get("top_100_share_of_reviews", 0) or 0
    hundred_plus = data.get("brands_with_100_plus_reviews", 0) or 0

    body = f"""
<h1>Top 100 Brands of the Last 12 Months</h1>

<p>
Brands ranked by the total number of Feefo reviews earned across their whole
Not On The High Street range over the last 12 months.
</p>

<div class="stats">
<p>
    Brands with reviews: <strong>{brand_count:,}</strong><br>
    Total reviews: <strong>{total_reviews:,}</strong><br>
    Brands with 100+ reviews: <strong>{hundred_plus:,}</strong><br>
    Top 100 share of reviews: <strong>{top_100_share:.1%}</strong>
</p>
</div>

<h2>Leaderboard</h2>
<p><small>Showing top 100 including ties ({len(shown)} brands shown).</small></p>

{render_brands_leaderboard(items, limit=100)}

<p class="table-note">
This ranks brands on total reviews, so a brand with a large range will tend to
place higher than a brand with a few very popular products. The
"Products reviewed" column shows how many of each brand's products picked up at
least one review.
</p>

<p>
    <a href="index.html">← Back to homepage</a>
</p>
"""

    html = render_page(
        "Top 100 Brands of the Last 12 Months",
        body,
        "static",
        "",
        "The Not On The High Street brands with the most reviews over the last 12 months.",
    )
    save_html(OUTPUT_ROOT / "top-brands-last-12-months.html", html)

    print("✅ top-brands-last-12-months rendered")


BRAND_ORDERS_PAGE_LIMIT = 200


def render_top_brands_all_time_orders():
    leaderboard_file = LEADERBOARDS_ROOT / "top_brands_all_time_orders.json"

    if not leaderboard_file.exists():
        print("⚠️ top_brands_all_time_orders.json not found")
        return

    data = load_json(leaderboard_file)
    items = clean_product_list(data.get("items", []))
    shown = top_n_with_ties(items, BRAND_ORDERS_PAGE_LIMIT, value_key="orders")

    brand_count = data.get("brand_count", len(items)) or 0
    total_orders = data.get("total_orders", 0) or 0
    hundred_k_plus = data.get("brands_with_100k_plus_orders", 0) or 0
    million_plus = data.get("brands_with_1m_plus_orders", 0) or 0
    top_100_share = data.get("top_100_share_of_orders", 0) or 0
    top_200_share = data.get("top_200_share_of_orders", 0) or 0
    source_date = (data.get("source_generated_at") or "")[:10]

    source_note = (
        f" Partner pages last read {format_long_date(source_date)}."
        if source_date
        else ""
    )

    body = f"""
<h1>Top 200 Brands by All-Time Orders</h1>

<p>
Every Not On The High Street partner page publishes the number of orders that
brand has taken over its lifetime on the marketplace. Collected here, they rank
{brand_count:,} brands by total orders, the closest thing NOTHS has to a
public sales league table.
</p>

<p>
The top 100 brands account for {top_100_share:.0%} of every order on record;
the top 200, {top_200_share:.0%}.
</p>

<div class="stats">
<p>
    Brands with published order counts: <strong>{brand_count:,}</strong><br>
    Orders between them: <strong>{total_orders:,}</strong><br>
    Brands past 100K orders: <strong>{hundred_k_plus:,}</strong><br>
    Brands past 1M orders: <strong>{million_plus:,}</strong><br>
    Top 100 share of orders: <strong>{top_100_share:.1%}</strong><br>
    Top 200 share of orders: <strong>{top_200_share:.1%}</strong>
</p>
</div>

<h2>Leaderboard</h2>
<p><small>Showing top {BRAND_ORDERS_PAGE_LIMIT} including ties ({len(shown)} brands shown).</small></p>

{render_brand_orders_leaderboard(items, limit=BRAND_ORDERS_PAGE_LIMIT)}

<p class="table-note">* No longer trading on NOTHS. The storefront is empty or gone.
Lifetime orders are kept, because the brand really did take them, but the
name isn't linked since there's nothing there to buy.</p>

<p class="table-note">
NOTHS rounds these figures to two significant figures and adds a "+", so
"690K+" means somewhere between 690,000 and 700,000 orders. Brands sharing a
band are marked "=" because the public data genuinely cannot separate them.
Lifetime orders also reward age, so the "Orders / year" column divides by time
on the marketplace. "Reviews (last 12 months)" is the same brand's Feefo review
total over that period, for current activity rather than lifetime total. Click
any column heading to sort by it; the # column always shows rank by total
orders.{source_note}
</p>

<p>
    <a href="index.html">← Back to homepage</a>
</p>
"""

    html = render_page(
        "Top 200 Brands by All-Time Orders",
        body,
        "static",
        "",
        "The Not On The High Street brands with the most orders of all time.",
    )
    save_html(OUTPUT_ROOT / "top-brands-all-time.html", html)

    print("✅ top-brands-all-time rendered")


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
    render_top_brands_last_12_months()
    render_top_brands_all_time_orders()

    render_about()
    generate_sitemap(months)

    print()
    print("🏁 Site render complete")


if __name__ == "__main__":
    main()
