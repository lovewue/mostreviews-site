import json
import re
from pathlib import Path


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "products_cache.json"
PARTNERS_JSON = PROJECT_ROOT / "data" / "partners_search.json"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
BAD_NAMES = {
    "",
    "unknown",
    "unknown seller",
    "not found",
    "error",
    "none",
    "null",
}


def clean_text(value):
    """Collapse whitespace and trim text."""
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None


def slug_fallback_name(slug):
    """
    Safe fallback display name from slug.
    """
    if not slug:
        return None
    return slug.replace("-", " ").title()


def normalise_for_compare(value):
    """
    Lowercase alphanumeric-only comparison form.
    Helps compare:
    'Lily Designs London' vs 'lilydesignslondon'
    """
    value = clean_text(value)
    if not value:
        return None
    return re.sub(r"[^a-z0-9]", "", value.lower())


def load_partner_lookup():
    """
    Load slug -> canonical seller name from partners_search.json
    """
    if not PARTNERS_JSON.exists():
        print(f"⚠️ partners_search.json not found: {PARTNERS_JSON}")
        return {}

    with open(PARTNERS_JSON, "r", encoding="utf-8") as f:
        partners = json.load(f)

    lookup = {}
    for row in partners:
        slug = clean_text(row.get("slug"))
        name = clean_text(row.get("name"))
        if slug and name:
            lookup[slug] = name

    print(f"📂 Loaded {len(lookup)} canonical seller names")
    return lookup


def looks_like_name_matches_slug(slug, seller_name):
    """
    Return True if the seller name plausibly matches the slug.
    Example:
    lilydesignslondon <-> Lily Designs London  => True
    lilydesignslondon <-> Kutuu                 => False
    """
    if not slug or not seller_name:
        return False

    slug_norm = normalise_for_compare(slug)
    name_norm = normalise_for_compare(seller_name)

    if not slug_norm or not name_norm:
        return False

    return slug_norm == name_norm


def resolve_name_strict(slug, current_name, partner_lookup):
    """
    Strict seller-name resolution:

    1. If slug exists in partners_search.json, always use that.
    2. If current name is missing/bad, use slug fallback.
    3. If current name clearly does not match slug, use slug fallback.
    4. Otherwise keep current name.
    """
    slug = clean_text(slug)
    current_name = clean_text(current_name)

    if not slug:
        return current_name

    if slug in partner_lookup:
        return partner_lookup[slug]

    if not current_name or current_name.lower() in BAD_NAMES:
        return slug_fallback_name(slug)

    if not looks_like_name_matches_slug(slug, current_name):
        return slug_fallback_name(slug)

    return current_name


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    if not CACHE_FILE.exists():
        raise FileNotFoundError(f"Cache file not found: {CACHE_FILE}")

    partner_lookup = load_partner_lookup()

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)

    fixed = 0
    unchanged = 0
    missing_slug = 0

    examples = []

    for row in items:
        slug = clean_text(row.get("seller_slug"))
        old_name = clean_text(row.get("seller_name"))

        if not slug:
            missing_slug += 1
            continue

        new_name = resolve_name_strict(slug, old_name, partner_lookup)

        if new_name != old_name:
            row["seller_name"] = new_name
            fixed += 1

            if len(examples) < 20:
                examples.append((slug, old_name, new_name))
        else:
            unchanged += 1

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    print("✅ Cache repair complete")
    print(f"Fixed:        {fixed}")
    print(f"Unchanged:    {unchanged}")
    print(f"Missing slug: {missing_slug}")
    print()
    print("Sample fixes:")
    for slug, old_name, new_name in examples:
        print(f"  {slug}: {old_name!r} -> {new_name!r}")
    print()
    print(f"💾 Saved: {CACHE_FILE}")


if __name__ == "__main__":
    main()
