"""
Instagram / TikTok carousel for each curated theme page (Sara Davies'
Christmas picks etc.), in the same house style as the monthly carousel.

Output, per theme, in social_media/themes/<slug>/:

    00_cover.jpg          hook: "<N> Christmas picks from <curator>, ranked
                          by real reviews"
    01_<sku>.jpg ...      the top 5 by all-time reviews (more if the 5th is
                          tied), with rank, review count and rating on the
                          slide. Unlike the monthly carousel, the rank IS
                          shown: here the ranking is the whole point, and
                          the top of these lists is rarely tied.
    06_this_year.jpg      the most-reviewed picks over the last 12 months.
                          Only made when the leader has at least
                          MIN_THIS_YEAR reviews, so a small list doesn't get
                          a slide of 3s and 4s.
    07_full_list.jpg      call to action: the full list on trendlist.co.uk
    caption.txt           ready-to-paste caption
    captions.json         the same, structured, plus brands still needing
                          an Instagram handle

The ranking comes from render_site.rank_theme_products(), so the slides can
never disagree with the web page. Drawing helpers, colours and fonts come
from build_social_assets.py so the two carousels stay one house style.

Images: the theme snapshot stores each product's 1024px "original" image
URL. NOTHS's CDN is reachable from GitHub Actions, which is where this runs.
If a direct download fails it falls back to build_social_assets'
product-page scrape, and if that fails too the slide is made without a
photo rather than dropping the product from the carousel.

Instagram handles live in data/social/brand_handles.json, keyed by NOTHS
seller slug. Fill a handle in once and every future caption uses it. Brands
with no handle are listed in captions.json and at the end of caption.txt.

Usage:
    python scripts/build_theme_social.py
    python scripts/build_theme_social.py --theme sara-davies-christmas-picks
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import requests  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import build_social_assets as bsa  # noqa: E402
from build_theme_picks import THEMES  # noqa: E402
from render_site import load_review_lookups, rank_theme_products  # noqa: E402

THEMES_DATA = PROJECT_ROOT / "data" / "derived" / "themes"
OUT_ROOT = PROJECT_ROOT / "social_media" / "themes"
HANDLES_FILE = PROJECT_ROOT / "data" / "social" / "brand_handles.json"

SITE = "trendlist.co.uk"
TOP_N = 5
MAX_PRODUCT_SLIDES = 7          # cap if the 5th place is a big tie
MIN_THIS_YEAR = 20              # leader's 12-month reviews needed for slide 6
THIS_YEAR_ROWS = 5

SIZE = bsa.COVER_SIZE
S = bsa._SCALE
PURPLE, INK, MUTED, BG = bsa.PURPLE, bsa.INK, bsa.MUTED, bsa.BG_COLOR
F_DISPLAY, F_BOLD, F_REG = bsa.FONT_PATHS_DISPLAY, bsa.FONT_PATHS_BOLD, bsa.FONT_PATHS_REGULAR
font = bsa._load_font

MARGIN = round(76 * S)
TEXT_W = SIZE[0] - MARGIN * 2

HASHTAGS = (
    "#notonthehighstreet #christmasgifts #christmasgiftideas #giftideas "
    "#giftguide #shopsmall #smallbusinessuk"
)


# -----------------------------------------------------------------------------
# Small drawing helpers
# -----------------------------------------------------------------------------
def fit_font(draw, text, paths, max_size, min_size, max_width):
    size = max_size
    while size > min_size:
        f = font(paths, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 2
    return font(paths, min_size)


def draw_line(draw, x, y, text, f, fill):
    b = draw.textbbox((0, 0), text, font=f)
    draw.text((x, y - b[1]), text, font=f, fill=fill)
    return b[3] - b[1]


def draw_wrapped(draw, x, y, text, f, fill, max_width, line_h):
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) > max_width and line:
            draw.text((x, y), line, font=f, fill=fill)
            y += line_h
            line = word
        else:
            line = trial
    if line:
        draw.text((x, y), line, font=f, fill=fill)
        y += line_h
    return y


def new_canvas():
    canvas = Image.new("RGB", SIZE, BG)
    return canvas, ImageDraw.Draw(canvas)


def statement(draw, y, lines, max_size=70):
    """Anton statement lines, one of them knocked out of a purple block.
    All lines share one size: the largest at which every line fits."""
    size = max_size
    while size > 40:
        f = font(F_DISPLAY, round(size * S))
        if all(draw.textlength(t, font=f) <= TEXT_W - round(28 * S) for t, _ in lines):
            break
        size -= 2
    f = font(F_DISPLAY, round(size * S))
    gap = round(26 * S)
    for text, blocked in lines:
        if blocked:
            h = bsa._draw_block_line(draw, MARGIN, y, text, f, round(14 * S), round(12 * S))
            y += h + gap + round(10 * S)
        else:
            y += draw_line(draw, MARGIN, y, text, f, PURPLE) + gap
    return y


def hero(draw, y, text, size=300):
    f = fit_font(draw, text, F_DISPLAY, round(size * S), round(120 * S), TEXT_W)
    return y + draw_line(draw, MARGIN, y, text, f, PURPLE) + round(44 * S)


def kicker(draw, text, y=None):
    f = font(F_BOLD, round(24 * S))
    bsa._draw_tracked(draw, (MARGIN, round(84 * S) if y is None else y),
                      text.upper(), f, MUTED, round(4.5 * S))


# -----------------------------------------------------------------------------
# Slides
# -----------------------------------------------------------------------------
def cover_slide(theme, total, out):
    canvas, draw = new_canvas()
    kicker(draw, "Not on the High Street")
    y = hero(draw, round(140 * S), str(total))
    curator = theme.get("curator", "").upper()
    y = statement(draw, y, [
        ("CHRISTMAS PICKS FROM", False),
        (f"{curator}.", False),
        ("RANKED BY REAL REVIEWS", True),
    ])
    note = (f"Every product in {theme.get('label', 'the selection')} on Not On The "
            "High Street, ranked by how many customers have reviewed it.")
    draw_wrapped(draw, MARGIN, y + round(18 * S), note,
                 font(F_REG, round(30 * S)), MUTED, TEXT_W, round(44 * S))
    bsa._draw_footer(draw, SIZE[0], SIZE[1], MARGIN)
    canvas.save(out, "JPEG", quality=92)


def product_slide(p, total, image_path, out):
    """Laid out from the footer upwards: stat line, seller, name, and the
    photo gets whatever height is left. A two- or three-line product name
    therefore shrinks the photo instead of pushing text into the footer."""
    canvas, draw = new_canvas()
    kicker(draw, f"No. {p['rank_display']} of {total} picks")

    rule_y = SIZE[1] - round(150 * S)

    # Stat line: "1,499 REVIEWS" in the purple block, then rating / stock.
    stat_font = font(F_DISPLAY, round(54 * S))
    stat = f"{p['reviews_all_time']:,} REVIEWS"
    sb = draw.textbbox((0, 0), stat, font=stat_font)
    stat_h = sb[3] - sb[1]
    pad_x, pad_y = round(14 * S), round(12 * S)

    extra = []
    if p.get("rating"):
        extra.append(f"{float(p['rating']):.1f} AVERAGE")
    if not p.get("in_stock", True):
        extra.append("OUT OF STOCK")
    extra_text = "  ·  ".join(extra)
    extra_font = font(F_BOLD, round(28 * S))
    extra_x = MARGIN + (sb[2] - sb[0]) + pad_x + round(36 * S)
    extra_own_line = bool(extra) and (
        extra_x + draw.textlength(extra_text, font=extra_font) + len(extra_text) * 2 * S
        > SIZE[0] - MARGIN
    )

    block_bottom = rule_y - round(64 * S)
    if extra_own_line:
        block_bottom -= round(48 * S)
    stat_y = block_bottom - pad_y - stat_h

    # Seller, then name, stacked upwards from the stat block.
    seller = p.get("seller_name") or ""
    seller_font = font(F_REG, round(32 * S))
    seller_h = draw.textbbox((0, 0), "by Ag", font=seller_font)[3] if seller else 0
    seller_y = stat_y - pad_y - round(34 * S) - seller_h

    name = (p.get("name") or "").upper()
    name_font, name_lines = bsa.fit_product_name(
        draw, name, F_DISPLAY, TEXT_W,
        max_font_size=round(58 * S), min_font_size=round(34 * S),
    )
    line_hs = [draw.textbbox((0, 0), l, font=name_font) for l in name_lines]
    line_gap = round(14 * S)
    name_block_h = sum(b[3] - b[1] for b in line_hs) + line_gap * (len(name_lines) - 1)
    name_y = seller_y - round(16 * S) - name_block_h

    # Photo area: from under the kicker to above the name.
    area_top = round(140 * S)
    area_bottom = name_y - round(44 * S)
    max_w, max_h = int(SIZE[0] * 0.78), area_bottom - area_top

    photo = None
    if image_path and image_path.exists():
        try:
            photo = Image.open(image_path).convert("RGB")
        except Exception:
            photo = None

    if photo is not None and max_h > 100:
        r = min(max_w / photo.width, max_h / photo.height)
        photo = photo.resize((int(photo.width * r), int(photo.height * r)), Image.LANCZOS)
        canvas.paste(photo, ((SIZE[0] - photo.width) // 2,
                             area_top + (max_h - photo.height) // 2))
    else:
        # No photo: the rank fills the space so the slide still works.
        f = fit_font(draw, f"#{p['rank']}", F_DISPLAY, round(420 * S), round(120 * S), TEXT_W)
        while f.size > round(120 * S) and draw.textbbox((0, 0), f"#{p['rank']}", font=f)[3] > max_h:
            f = font(F_DISPLAY, f.size - 10)
        b = draw.textbbox((0, 0), f"#{p['rank']}", font=f)
        draw.text((MARGIN, area_top + (max_h - (b[3] - b[1])) // 2 - b[1]),
                  f"#{p['rank']}", font=f, fill=PURPLE)

    y = name_y
    for line, b in zip(name_lines, line_hs):
        draw.text((MARGIN, y - b[1]), line, font=name_font, fill=PURPLE)
        y += (b[3] - b[1]) + line_gap

    if seller:
        draw_line(draw, MARGIN, seller_y, f"by {seller}", seller_font, MUTED)

    bsa._draw_block_line(draw, MARGIN, stat_y, stat, stat_font, pad_x, pad_y)
    if extra:
        if extra_own_line:
            ex, ey = MARGIN, block_bottom + round(26 * S)
        else:
            ex, ey = extra_x, stat_y + (stat_h - round(28 * S)) // 2
        bsa._draw_tracked(draw, (ex, ey), extra_text, extra_font, MUTED, round(2 * S))

    bsa._draw_footer(draw, SIZE[0], SIZE[1], MARGIN)
    canvas.save(out, "JPEG", quality=92)


def this_year_slide(rows, out):
    canvas, draw = new_canvas()
    kicker(draw, "Last 12 months")
    y = statement(draw, round(140 * S), [
        ("MOST REVIEWED", False),
        ("THIS YEAR", True),
    ], max_size=96)
    y += round(36 * S)

    rule_y = SIZE[1] - round(150 * S)
    row_h = min(round(132 * S), (rule_y - round(60 * S) - y) // len(rows))

    num_font = font(F_DISPLAY, round(min(80, row_h / S * 0.62) * S))
    num_w = max(draw.textlength(f"{r['reviews_last_12']:,}", font=num_font) for r in rows)
    text_x = MARGIN + num_w + round(36 * S)
    name_max = SIZE[0] - MARGIN - text_x
    name_font = font(F_BOLD, round(30 * S))
    seller_font = font(F_REG, round(26 * S))

    for r in rows:
        draw_line(draw, MARGIN, y, f"{r['reviews_last_12']:,}", num_font, PURPLE)
        name = r["name"]
        if draw.textlength(name, font=name_font) > name_max:
            while draw.textlength(name + "…", font=name_font) > name_max:
                name = name[:-1]
            name = name.rstrip(" ,") + "…"
        draw_line(draw, text_x, y + round(4 * S), name, name_font, INK)
        draw_line(draw, text_x, y + round(48 * S), r.get("seller_name") or "", seller_font, MUTED)
        y += row_h

    bsa._draw_footer(draw, SIZE[0], SIZE[1], MARGIN)
    canvas.save(out, "JPEG", quality=92)


def cta_slide(total, out):
    canvas, draw = new_canvas()
    kicker(draw, "The full list")
    y = hero(draw, round(140 * S), f"ALL {total}")
    y = statement(draw, y, [
        ("CHRISTMAS PICKS RANKED", False),
        (f"AT {SITE.upper()}", True),
    ])
    draw_wrapped(draw, MARGIN, y + round(18 * S),
                 "Every product with its all-time and last-12-months review count. Link in bio.",
                 font(F_REG, round(30 * S)), MUTED, TEXT_W, round(44 * S))
    bsa._draw_footer(draw, SIZE[0], SIZE[1], MARGIN, right_label="LINK IN BIO")
    canvas.save(out, "JPEG", quality=92)


# -----------------------------------------------------------------------------
# Images
# -----------------------------------------------------------------------------
def fetch_image(p, raw_path):
    url = p.get("image_url")
    if url:
        try:
            r = requests.get(url, headers=bsa.get_headers(), timeout=20)
            is_image = (
                r.content[:3] == b"\xff\xd8\xff"
                or r.headers.get("Content-Type", "").startswith("image/")
            )
            if r.status_code == 200 and is_image:
                raw_path.write_bytes(r.content)
                Image.open(raw_path).verify()
                return True
        except Exception:
            pass
    try:
        return bool(bsa.get_product_image(p, raw_path))
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Captions
# -----------------------------------------------------------------------------
def load_handles():
    if not HANDLES_FILE.exists():
        return {}
    with open(HANDLES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {k: (v or "").strip().lstrip("@") for k, v in data.items() if not k.startswith("_")}


def update_handles_file(handles, slugs_names):
    """Add any new brand to the handles file with an empty value, so the file
    always lists every brand that has appeared on a slide."""
    HANDLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if HANDLES_FILE.exists():
        with open(HANDLES_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    changed = False
    if "_readme" not in existing:
        existing["_readme"] = (
            "Instagram handle per NOTHS seller slug, without the @. Leave blank "
            "if unknown; blanks are listed in each carousel's captions.json."
        )
        changed = True
    for slug, name in slugs_names:
        if slug and slug not in existing:
            existing[slug] = ""
            changed = True
    if changed:
        ordered = {"_readme": existing.pop("_readme")}
        ordered.update(dict(sorted(existing.items())))
        with open(HANDLES_FILE, "w", encoding="utf-8") as f:
            json.dump(ordered, f, indent=2, ensure_ascii=False)
            f.write("\n")


def build_caption(theme, total, top, this_year, handles):
    curator = theme.get("curator", "")
    lines = [
        f"{curator} picked {total} Christmas gifts for Not On The High Street. "
        "We ranked every one by real customer reviews.",
        "",
        "The most reviewed:",
    ]
    for p in top:
        lines.append(
            f"{p['rank_display']}. {p['name']} by {p['seller_name']} "
            f"({p['reviews_all_time']:,} reviews)"
        )
    if this_year:
        lead = this_year[0]
        lines += [
            "",
            f"Most reviewed in the last 12 months: {lead['name']} by "
            f"{lead['seller_name']} ({lead['reviews_last_12']:,}).",
        ]
    lines += ["", f"All {total} picks, ranked: link in bio ({SITE})", ""]

    featured = []
    for p in top + this_year:
        if p["seller_slug"] not in [s for s, _ in featured]:
            featured.append((p["seller_slug"], p["seller_name"]))

    tags = ["@notonthehighstreet"] + [f"@{handles[s]}" for s, _ in featured if handles.get(s)]
    missing = [{"seller_slug": s, "seller_name": n} for s, n in featured if not handles.get(s)]

    lines.append(" ".join(tags))
    lines.append("")
    lines.append(HASHTAGS)

    return "\n".join(lines), featured, missing


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def build_theme(slug, theme, lookups, handles):
    snap_path = THEMES_DATA / f"{slug}.json"
    if not snap_path.exists():
        print(f"ℹ️ {slug}: no snapshot, skipped")
        return
    with open(snap_path, encoding="utf-8") as f:
        snapshot = json.load(f)

    products = [dict(p) for p in snapshot.get("products", []) if p.get("sku")]
    for p in products:
        # NOTHS stores some names with literal quotes, e.g. "'By Alex'".
        p["seller_name"] = (p.get("seller_name") or "").strip().strip("'\"").strip()
    ranked, unranked = rank_theme_products(products, lookups)
    total = len(ranked) + len(unranked)
    if not ranked:
        print(f"⚠️ {slug}: nothing ranked, skipped")
        return

    # Top N including ties at the Nth place, capped.
    cutoff = ranked[min(TOP_N, len(ranked)) - 1]["reviews_all_time"]
    top = [p for p in ranked if p["reviews_all_time"] >= cutoff][:MAX_PRODUCT_SLIDES]

    by_year = sorted(
        [p for p in ranked if p["reviews_last_12"] > 0],
        key=lambda p: (-p["reviews_last_12"], -p["reviews_all_time"]),
    )[:THIS_YEAR_ROWS]
    this_year = by_year if by_year and by_year[0]["reviews_last_12"] >= MIN_THIS_YEAR else []

    out_dir = OUT_ROOT / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()

    print(f"🎞️ {slug}: {len(top)} product slides"
          + (", plus this-year slide" if this_year else ""))

    files = []
    cover_slide(theme, total, out_dir / "00_cover.jpg")
    files.append("00_cover.jpg")

    images_ok = 0
    for i, p in enumerate(top, start=1):
        raw = out_dir / f"_raw_{p['sku']}.jpg"
        got = fetch_image(p, raw)
        images_ok += got
        name = f"{i:02d}_{p['sku']}.jpg"
        product_slide(p, total, raw if got else None, out_dir / name)
        raw.unlink(missing_ok=True)
        files.append(name)
        print(f"   {'✅' if got else '⚠️ no photo,'} {p['rank_display']}. {p['name']}")

    n = len(top) + 1
    if this_year:
        name = f"{n:02d}_this_year.jpg"
        this_year_slide(this_year, out_dir / name)
        files.append(name)
        n += 1

    name = f"{n:02d}_full_list.jpg"
    cta_slide(total, out_dir / name)
    files.append(name)

    caption, featured, missing = build_caption(theme, total, top, this_year, handles)
    update_handles_file(handles, featured)

    (out_dir / "caption.txt").write_text(
        caption
        + ("\n\n---\nNo Instagram handle on file yet for: "
           + ", ".join(m["seller_name"] for m in missing)
           + "\nAdd them to data/social/brand_handles.json." if missing else "")
        + "\n",
        encoding="utf-8",
    )
    with open(out_dir / "captions.json", "w", encoding="utf-8") as f:
        json.dump({
            "theme": slug,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "product_list_checked_at": snapshot.get("checked_at"),
            "slides": files,
            "caption": caption,
            "products": [
                {k: p.get(k) for k in ("rank_display", "sku", "name", "seller_name",
                                        "seller_slug", "reviews_all_time",
                                        "reviews_last_12", "rating", "product_url")}
                for p in top
            ],
            "this_year": [
                {k: p.get(k) for k in ("sku", "name", "seller_name", "reviews_last_12")}
                for p in this_year
            ],
            "missing_handles": missing,
        }, f, indent=2, ensure_ascii=False)

    print(f"   📝 {len(files)} slides, {images_ok}/{len(top)} photos, "
          f"{len(missing)} brands without a handle")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme")
    args = parser.parse_args()

    selected = {args.theme: THEMES[args.theme]} if args.theme else THEMES
    lookups = load_review_lookups()
    handles = load_handles()

    for slug, theme in selected.items():
        build_theme(slug, theme, lookups, handles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
