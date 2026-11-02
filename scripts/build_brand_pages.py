#!/usr/bin/env python3
"""
Brand pages: docs/brands/<slug>/index.html, one per trading NOTHS brand.

Built entirely from data the monthly pipeline already produces, so there is
nothing to maintain by hand:

  data/cache/brand_stats.json                      orders band, rating, years, trading
  data/derived/leaderboards/top_products_*.json    each brand's most-reviewed products
  data/derived/leaderboards/top_brands_*.json      brand ranks (reviews 12m, orders)
  data/derived/monthly/<month>/enriched_products   this month's top-50 appearances
  data/cache/feed_products.json                    images + prices (Awin feed)

Fair to small brands, safe for search:
  - Every TRADING brand gets a page (page up and products listed). Brands
    with an empty or closed shop get none: sending traffic to an empty shop
    helps nobody.
  - Only pages with real substance are indexable (INDEX_MIN_REVIEWED_12M
    products reviewed in the last 12 months, or INDEX_MIN_ORDERS lifetime
    orders). The rest carry <meta name="robots" content="noindex,follow">:
    still built, still linked from the directory, but they don't count
    against the site as thin content.
  - Only flattering numbers are shown. A rank appears only when it is a good
    one (top RANK_SHOW_MAX); a small brand's page leads with what it has —
    years on NOTHS, rating, reviewed products — never with what it lacks.

Usage:
  python scripts/build_brand_pages.py                 # all trading brands
  python scripts/build_brand_pages.py --only wue lisaangeljewellery
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import render_site as rs  # noqa: E402

DATA = rs.DATA_DIR
LB = DATA / "derived" / "leaderboards"
OUT_ROOT = rs.OUTPUT_ROOT / "brands"
SITE = "https://trendlist.co.uk"

INDEX_MIN_REVIEWED_12M = 3
INDEX_MIN_ORDERS = 1000
RANK_SHOW_MAX = 300          # brand ranks shown only when inside this
PRODUCT_RANK_SHOW_MAX = 100  # product ranks (all-time / 12m) shown only inside this
TOP_12M = 6
TOP_ALL_TIME = 6


def load(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def latest_month() -> str | None:
    months = sorted(p.name for p in (DATA / "derived" / "monthly").glob("20??-??") if p.is_dir())
    return months[-1] if months else None


def is_trading(b: dict) -> bool:
    return bool(b.get("active")) and (b.get("product_count") or 0) > 0


# -----------------------------------------------------------------------------
# Data, loaded once
# -----------------------------------------------------------------------------
class Data:
    def __init__(self):
        self.stats = (load(DATA / "cache" / "brand_stats.json", {}) or {}).get("brands") or {}

        self.products_12m = defaultdict(list)
        for i in (load(LB / "top_products_last_12_months.json", {}) or {}).get("items") or []:
            if i.get("seller_slug") and (i.get("reviews") or 0) > 0:
                self.products_12m[i["seller_slug"]].append(i)

        # The all-time file is ~96 MB; keep only what pages use.
        self.products_all = defaultdict(list)
        for i in (load(LB / "top_products_all_time.json", {}) or {}).get("items") or []:
            slug = i.get("seller_slug")
            if slug and (i.get("reviews") or 0) > 0 and len(self.products_all[slug]) < TOP_ALL_TIME * 3:
                self.products_all[slug].append({
                    k: i.get(k) for k in ("rank", "sku", "name", "product_url", "available", "reviews", "rating")
                })

        self.rank_12m = {
            b["seller_slug"]: b
            for b in (load(LB / "top_brands_last_12_months.json", {}) or {}).get("items") or []
            if b.get("seller_slug")
        }
        self.rank_orders = {
            b["seller_slug"]: b
            for b in (load(LB / "top_brands_all_time_orders.json", {}) or {}).get("items") or []
            if b.get("seller_slug")
        }

        self.month = latest_month()
        self.month_products = defaultdict(list)
        if self.month:
            items = load(DATA / "derived" / "monthly" / self.month / "enriched_products.json", []) or []
            top = rs.add_dense_ranks(
                rs.top_n_with_ties(rs.drop_unidentified(items), 50, value_key="review_count_month"),
                value_key="review_count_month",
            )
            for p in top:
                if p.get("seller_slug"):
                    self.month_products[p["seller_slug"]].append(p)

        self.feed = rs.feed_products()

    def display_name(self, slug: str) -> str:
        for source in (self.rank_12m.get(slug), self.rank_orders.get(slug)):
            if source and source.get("seller_name"):
                return source["seller_name"]
        for p in self.products_12m.get(slug, [])[:1]:
            if p.get("seller_name"):
                return p["seller_name"]
        name = (self.stats.get(slug) or {}).get("name") or slug
        # NOTHS page titles look like "Wue | Jewellery & Gifts"; keep the brand.
        return name.split(" | ")[0].strip()


# -----------------------------------------------------------------------------
# Page
# -----------------------------------------------------------------------------
def product_card(p: dict, feed: dict, note: str) -> str:
    entry = feed.get(str(p.get("sku") or "").strip()) or {}
    live = p.get("available") is True and bool(entry)
    url = p.get("product_url") or entry.get("url") or ""
    href = rs.build_awin_product_link(url, clickref="TrendListBrand") if (url and live) else ""
    img = entry.get("thumb") or entry.get("image") or ""
    name = rs.html_attr(p.get("name") or entry.get("name") or "")
    price = entry.get("price")
    price_html = f'<div class="pick-price">£{price:,.2f}</div>' if (live and isinstance(price, (int, float))) else ""
    img_html = (
        f'<img src="{rs.html_attr(img)}" alt="{name}" width="200" height="200" loading="lazy" decoding="async">'
        if (img and live) else '<div class="brand-card-noimg"></div>'
    )
    status = "" if live else '<p class="pick-blurb">No longer available</p>'
    inner = f"""
    {img_html}
    <div class="pick-name">{name}</div>
    {price_html}
    <p class="pick-blurb">{note}</p>{status}"""
    if href:
        return f'<a class="pick-card" href="{href}" rel="sponsored noopener" target="_blank">{inner}\n</a>'
    return f'<div class="pick-card pick-card-static">{inner}\n</div>'


def highlights(slug: str, d: Data, top12, topall) -> list[str]:
    out = []
    best_all = min((p for p in topall if p.get("rank")), key=lambda p: p["rank"], default=None)
    if best_all and best_all["rank"] <= PRODUCT_RANK_SHOW_MAX:
        out.append(
            f'<strong>#{best_all["rank"]}</strong> most-reviewed product on NOTHS of all time: '
            f'{rs.html_attr(best_all.get("name") or "")}'
        )
    best_12 = min((p for p in top12 if p.get("rank")), key=lambda p: p["rank"], default=None)
    if best_12 and best_12["rank"] <= PRODUCT_RANK_SHOW_MAX:
        out.append(
            f'<strong>#{best_12["rank"]}</strong> most-reviewed product of the last 12 months: '
            f'{rs.html_attr(best_12.get("name") or "")}'
        )
    r12 = d.rank_12m.get(slug)
    if r12 and (r12.get("rank") or 10**9) <= RANK_SHOW_MAX:
        out.append(f'<strong>#{r12["rank"]}</strong> brand on NOTHS by reviews in the last 12 months')
    ro = d.rank_orders.get(slug)
    if ro and ro.get("trading") is not False and (ro.get("rank") or 10**9) <= RANK_SHOW_MAX:
        out.append(f'<strong>#{ro["rank"]}</strong> brand on NOTHS by all-time orders')
    mp = d.month_products.get(slug) or []
    if mp and d.month:
        month_label = rs.format_month(d.month)
        n = len(mp)
        out.append(
            f'<strong>{n}</strong> product{"s" if n != 1 else ""} in the '
            f'<a href="../../months/{d.month}.html">top 50 for {month_label}</a>'
        )
    return out


def build_page(slug: str, d: Data) -> tuple[str, bool] | None:
    b = d.stats.get(slug) or {}
    if not is_trading(b):
        return None

    name = d.display_name(slug)
    name_html = rs.html_attr(name)
    top12 = sorted(d.products_12m.get(slug, []), key=lambda p: -(p.get("reviews") or 0))
    topall = sorted(d.products_all.get(slug, []), key=lambda p: -(p.get("reviews") or 0))

    reviewed_12m = len(top12)
    reviews_12m = sum(p.get("reviews") or 0 for p in top12)
    orders = b.get("orders") or 0
    indexable = reviewed_12m >= INDEX_MIN_REVIEWED_12M or orders >= INDEX_MIN_ORDERS

    facts = []
    if b.get("tenure_label"):
        facts.append(f'<span><strong>{rs.html_attr(b["tenure_label"])}</strong> on NOTHS</span>')
    if b.get("brand_rating"):
        facts.append(f'<span><strong>{b["brand_rating"]}/5</strong> brand rating</span>')
    if b.get("orders_label"):
        facts.append(f'<span><strong>{rs.html_attr(b["orders_label"])}</strong> orders</span>')
    if b.get("product_count"):
        facts.append(f'<span><strong>{b["product_count"]:,}</strong> products</span>')
    if reviews_12m:
        facts.append(
            f'<span><strong>{reviews_12m:,}</strong> product review{"s" if reviews_12m != 1 else ""} '
            "in the last 12 months</span>"
        )

    hl = highlights(slug, d, top12, topall)
    hl_html = (
        '<ul class="brand-highlights">' + "".join(f"<li>{h}</li>" for h in hl) + "</ul>"
    ) if hl else ""

    shop_href = rs.build_awin_link(slug, clickref="TrendListBrand")

    def live_first(items):
        """Products people can buy first; unavailable ones only to fill in."""
        live = [p for p in items if p.get("available") is True and str(p.get("sku")) in d.feed]
        gone = [p for p in items if p not in live]
        return live + (gone if len(live) < 2 else [])

    top12 = live_first(top12)

    sections = []
    if top12:
        cards = "".join(
            product_card(p, d.feed, f'{p.get("reviews") or 0:,} review{"s" if (p.get("reviews") or 0) != 1 else ""} in 12 months')
            for p in top12[:TOP_12M]
        )
        sections.append(f"""
<h2>Most reviewed in the last 12 months</h2>
<div class="picks-grid">{cards}</div>""")

    shown = {str(p.get("sku")) for p in top12[:TOP_12M]}
    # The point is traffic: lead with products people can buy. Discontinued
    # favourites only fill in when a brand has nothing live to show.
    all_rest = live_first([p for p in topall if str(p.get("sku")) not in shown])[:TOP_ALL_TIME]
    if all_rest:
        cards = "".join(
            product_card(p, d.feed, f'{p.get("reviews") or 0:,} reviews all time')
            for p in all_rest
        )
        sections.append(f"""
<h2>All-time favourites</h2>
<div class="picks-grid">{cards}</div>""")

    if not sections:
        sections.append(
            f"<p>{name_html} hasn't collected product reviews on NOTHS yet that we can rank. "
            "Take a look at their shop to see their latest products.</p>"
        )

    intro_bits = []
    if b.get("tenure_label"):
        intro_bits.append(f"{name_html} has been selling on Not On The High Street for {rs.html_attr(b['tenure_label'])}")
    else:
        intro_bits.append(f"{name_html} sells on Not On The High Street")
    if reviewed_12m == 1:
        tail = ", and one of its products has been reviewed in the last 12 months."
    elif reviewed_12m:
        tail = f", and {reviewed_12m} of its products have been reviewed in the last 12 months."
    else:
        tail = "."
    intro = intro_bits[0] + tail

    body = f"""
<p class="brand-crumb"><a href="../../brands.html">All brands</a></p>
<h1>{name_html}</h1>
<p>{intro}</p>
<div class="brand-facts">{"".join(facts)}</div>
{hl_html}
<p><a class="brand-shop" href="{shop_href}" rel="sponsored noopener" target="_blank">Shop {name_html} on NOTHS &rarr;</a></p>
{"".join(sections)}
<p class="table-note">
Review counts are Feefo product reviews on Not On The High Street. Orders,
rating and years are from the brand's NOTHS page; NOTHS rounds orders (e.g.
"270K+"). Updated monthly.
</p>
"""

    desc = (
        f"{name} on Not On The High Street: most-reviewed products"
        + (f", {b['orders_label']} orders" if b.get("orders_label") else "")
        + (f", {b['brand_rating']}/5 rating" if b.get("brand_rating") else "")
        + "."
    )
    html = rs.render_page(
        f"{name} on NOTHS: Most-Reviewed Products",
        body,
        "../../static",
        "../../",
        desc,
        f"{SITE}/brands/{slug}/",
    )
    if not indexable:
        html = html.replace("</head>", '  <meta name="robots" content="noindex,follow">\n</head>', 1)
    return html, indexable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="build just these brand slugs")
    args = ap.parse_args()

    d = Data()
    slugs = args.only or sorted(s for s, b in d.stats.items() if is_trading(b))
    built = indexed = 0
    for slug in slugs:
        result = build_page(slug, d)
        if not result:
            print(f"  – {slug}: not trading, no page")
            continue
        html, indexable = result
        out = OUT_ROOT / slug / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        built += 1
        indexed += indexable
    print(f"🏷️  brand pages: {built:,} built, {indexed:,} indexable, {built - indexed:,} noindex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
