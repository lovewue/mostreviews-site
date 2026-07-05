import json
import re
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
DERIVED_MONTHLY_DIR = ROOT / "data" / "derived" / "monthly"
MODEL = "gpt-4.1-mini"

client = OpenAI()


def find_latest_month_dir() -> Path:
    month_dirs = [p for p in DERIVED_MONTHLY_DIR.iterdir() if p.is_dir()]
    if not month_dirs:
        raise FileNotFoundError(f"No month folders found in {DERIVED_MONTHLY_DIR}")
    return sorted(month_dirs)[-1]


def load_top20_review_source(month_dir: Path) -> list[dict]:
    path = month_dir / "top20_reviews_for_content.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run scripts/build_top20_review_source.py first."
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def month_name(month_dir: Path) -> str:
    month_lookup = {
        "01": "January",
        "02": "February",
        "03": "March",
        "04": "April",
        "05": "May",
        "06": "June",
        "07": "July",
        "08": "August",
        "09": "September",
        "10": "October",
        "11": "November",
        "12": "December",
    }
    _, mm = month_dir.name.split("-")
    return month_lookup.get(mm, month_dir.name)


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def extract_json_block(text: str) -> dict:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    return json.loads(text.strip())


def is_bad_review_text(text: str) -> bool:
    t = clean_text(text)
    lower = t.lower()

    if not t:
        return True

    bad_exact = {
        "n/a",
        ".",
        "good",
        "excellent",
        "fantastic",
        "thank you",
        "very nice",
        "lovely.",
        "beautiful scarf",
        "good purchase",
        "very professional",
        "a very professional experience",
    }
    if lower in bad_exact:
        return True

    if len(t) < 12:
        return True

    negative_markers = [
        "not received",
        "very disappointing",
        "overpriced",
        "too small",
        "too narrow",
        "didn’t arrive",
        "didn't arrive",
        "after mother’s day",
        "after mother's day",
        "late delivery",
        "poor",
        "punctured",
    ]
    if any(x in lower for x in negative_markers):
        return True

    return False


def score_review_text(text: str) -> int:
    t = clean_text(text)
    lower = t.lower()
    score = 0

    if 30 <= len(t) <= 120:
        score += 4
    elif 18 <= len(t) <= 160:
        score += 2

    positive_markers = [
        "love", "loved", "beautiful", "lovely", "perfect", "great",
        "happy", "pleased", "delighted", "gorgeous", "amazing", "ideal"
    ]
    if any(x in lower for x in positive_markers):
        score += 3

    useful_markers = [
        "gift", "present", "delivery", "delivered", "quality",
        "packaged", "wrapped", "keepsake", "soft", "comfortable"
    ]
    if any(x in lower for x in useful_markers):
        score += 2

    if "read more" in lower:
        score -= 2

    return score


def prepare_reviews(product: dict) -> list[dict]:
    raw_reviews = product.get("reviews", []) or []
    cleaned = []

    for r in raw_reviews:
        text = clean_text(r.get("text"))
        if is_bad_review_text(text):
            continue

        cleaned.append(
            {
                "date": clean_text(r.get("date")),
                "text": text,
                "score": score_review_text(text),
            }
        )

    cleaned.sort(key=lambda x: (-x["score"], len(x["text"])))
    return cleaned


def best_short_fallback_quote(reviews: list[dict]) -> str:
    if not reviews:
        return ""
    return reviews[0]["text"]


def build_prompt(product: dict, month_label: str, reviews: list[dict]) -> str:
    review_lines = []
    for i, r in enumerate(reviews[:12], start=1):
        review_lines.append(f"{i}. Date: {r.get('date', '')} | Text: {r.get('text', '')}")

    reviews_block = "\n".join(review_lines) if review_lines else "No reviews available."

    return f"""
You are helping create short-form social content for a data-led gift trends account.

Your task:
- Pick the best short customer review quote for on-screen text.
- The quote must come exactly from one of the supplied reviews.
- Prefer quotes that are:
  - short
  - natural
  - positive
  - specific enough to feel real
  - suitable as the first line of a reel
- Avoid quotes that:
  - depend on reviewer identity
  - are awkward fragments
  - are too generic if there is a stronger option
  - are too long for easy on-screen text
  - are clearly negative

Return STRICT JSON only with these keys:
{{
  "selected_quote": "...",
  "review_date_private": "...",
  "post_line_1": "...",
  "post_line_2": "...",
  "visual": "...",
  "fallback_visual": "...",
  "confidence": "high|medium|low"
}}

Rules:
- post_line_1 should usually be the quote in quotes
- post_line_2 must be exactly: "{product['review_count_month']} reviews in {month_label}"
- Do not include reviewer names
- Do not include the date in the public post text
- selected_quote must exactly match review wording from the supplied reviews
- review_date_private must be the date belonging to the selected quote
- visual should be simple and realistic for quick social content creation
- fallback_visual should be easy if the creator does not have the product in hand
- Keep visual ideas practical, not ad-agency style

Product:
Name: {product.get('name', '')}
Seller: {product.get('seller_name', '')}
SKU: {product.get('sku', '')}
URL: {product.get('product_url', '')}
Reviews this month: {product.get('review_count_month', 0)}

Candidate reviews:
{reviews_block}
""".strip()


def normalise_result(product: dict, parsed: dict, month_label: str) -> dict:
    quote = clean_text(parsed.get("selected_quote"))
    post_line_1 = clean_text(parsed.get("post_line_1"))
    post_line_2 = clean_text(parsed.get("post_line_2")) or f"{product.get('review_count_month', 0)} reviews in {month_label}"

    if quote and not post_line_1:
        post_line_1 = f"\"{quote}\""

    if post_line_1:
        stripped = post_line_1.strip()
        if not stripped.startswith('"'):
            post_line_1 = f"\"{stripped.strip('\"')}\""

    return {
        "sku": product.get("sku", ""),
        "name": product.get("name", ""),
        "seller_name": product.get("seller_name", ""),
        "product_url": product.get("product_url", ""),
        "review_count_month": product.get("review_count_month", 0),
        "selected_quote": quote,
        "review_date_private": clean_text(parsed.get("review_date_private")),
        "post_line_1": post_line_1,
        "post_line_2": post_line_2,
        "visual": clean_text(parsed.get("visual")),
        "fallback_visual": clean_text(parsed.get("fallback_visual")),
        "confidence": clean_text(parsed.get("confidence")) or "medium",
    }


def generate_for_product(product: dict, month_label: str) -> dict:
    prepared_reviews = prepare_reviews(product)
    default_post_line_2 = f"{product.get('review_count_month', 0)} reviews in {month_label}"

    if not prepared_reviews:
        return {
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "seller_name": product.get("seller_name", ""),
            "product_url": product.get("product_url", ""),
            "review_count_month": product.get("review_count_month", 0),
            "selected_quote": "",
            "review_date_private": "",
            "post_line_1": "",
            "post_line_2": default_post_line_2,
            "visual": "Show ranking screenshot, then reveal product screenshot.",
            "fallback_visual": "Text-led post using review count only, then product screenshot.",
            "confidence": "low",
            "note": "No usable review quotes after filtering.",
        }

    prompt = build_prompt(product, month_label, prepared_reviews)
    response = client.responses.create(
        model=MODEL,
        input=prompt,
    )
    raw = response.output_text.strip()

    try:
        parsed = extract_json_block(raw)
        result = normalise_result(product, parsed, month_label)
        return result

    except Exception:
        fallback_quote = best_short_fallback_quote(prepared_reviews)
        return {
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "seller_name": product.get("seller_name", ""),
            "product_url": product.get("product_url", ""),
            "review_count_month": product.get("review_count_month", 0),
            "selected_quote": fallback_quote,
            "review_date_private": "",
            "post_line_1": f"\"{fallback_quote}\"" if fallback_quote else "",
            "post_line_2": default_post_line_2,
            "visual": "Use the quote as on-screen text, then reveal the product screenshot." if fallback_quote else "Show ranking screenshot, then reveal product screenshot.",
            "fallback_visual": "Text-led post using review count only, then product screenshot.",
            "confidence": "medium" if fallback_quote else "low",
            "note": "Model output could not be parsed cleanly; deterministic fallback used.",
            "raw_model_output": raw,
        }


def write_json(out_path: Path, results: list[dict]) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def write_markdown(out_path: Path, results: list[dict], month_label: str) -> None:
    lines = [f"# Content Ideas for {month_label}", ""]
    for i, item in enumerate(results, start=1):
        lines.append(f"## {i}. {item.get('name', '')}")
        lines.append("")
        lines.append("**Post text**")
        lines.append(item.get("post_line_1", "") or "_No quote selected_")
        lines.append(item.get("post_line_2", ""))
        lines.append("")
        lines.append("**Visual**")
        lines.append(item.get("visual", ""))
        lines.append("")
        lines.append("**Fallback visual**")
        lines.append(item.get("fallback_visual", ""))
        lines.append("")
        lines.append("**Private check**")
        lines.append(f"- Review date: {item.get('review_date_private', '')}")
        lines.append(f"- Review count: {item.get('review_count_month', 0)}")
        lines.append(f"- Confidence: {item.get('confidence', '')}")
        lines.append(f"- URL: {item.get('product_url', '')}")
        if item.get("note"):
            lines.append(f"- Note: {item.get('note')}")
        lines.append("")
        lines.append("---")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    latest_month_dir = find_latest_month_dir()
    month_label = month_name(latest_month_dir)

    source = load_top20_review_source(latest_month_dir)
    print(f"Using month: {latest_month_dir.name}")
    print(f"Products to process: {len(source)}")

    results = []
    for idx, product in enumerate(source, start=1):
        print(f"[{idx}/{len(source)}] {product.get('name', '')}")
        result = generate_for_product(product, month_label)
        results.append(result)

    json_path = latest_month_dir / "content_ideas.json"
    md_path = latest_month_dir / "content_ideas.md"

    write_json(json_path, results)
    write_markdown(md_path, results, month_label)

    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")


if __name__ == "__main__":
    main()
