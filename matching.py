"""Transparent matching logic for CampusTrace.

No AI, no machine learning: plain word comparison a student can explain.

Name        40 points
Category    20 points
Location    20 points
Date        10 points
Description 10 points
-------------------
Maximum    100 points
"""

import re
from datetime import date, datetime

MATCH_THRESHOLD = 40

STOP_WORDS = {
    "a", "an", "the", "with", "and", "of", "on", "in", "at", "for", "my",
    "is", "it", "was", "to", "from", "back", "some", "this", "that",
}


def normalize_words(text):
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOP_WORDS}


def word_overlap_ratio(text_a, text_b):
    """Overlap of the smaller word set, 0.0 - 1.0."""
    words_a = normalize_words(text_a)
    words_b = normalize_words(text_b)
    if not words_a or not words_b:
        return 0.0
    shared = 0
    for word in words_a:
        if word in words_b:
            shared += 1
            continue
        # allow partial matches like "calculator" vs "calculators"
        if any(word in other or other in word for other in words_b if len(word) > 3 and len(other) > 3):
            shared += 0.75
    return min(1.0, shared / min(len(words_a), len(words_b)))


def parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def date_score(date_a, date_b):
    first = parse_date(date_a)
    second = parse_date(date_b)
    if not first or not second:
        return 0.0
    gap = abs((first - second).days)
    if gap == 0:
        return 10.0
    if gap <= 2:
        return 8.0
    if gap <= 5:
        return 6.0
    if gap <= 10:
        return 4.0
    if gap <= 20:
        return 2.0
    return 0.0


def strip_model_codes(text):
    """Drop words containing digits (model numbers) so 'Casio Scientific
    Calculator' still matches 'Casio fx-991CW Calculator'."""
    if not text:
        return ""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", text)
             if not any(ch.isdigit() for ch in w)]
    return " ".join(words) or text


def calculate_match_score(found_item, lost_item):
    """Return an integer 0-100 similarity score between two item records."""
    score = 0.0

    # Item name similarity - 40%
    score += 40.0 * word_overlap_ratio(
        strip_model_codes(found_item["item_name"]),
        strip_model_codes(lost_item["item_name"]),
    )

    # Category - 20%
    if (found_item["category"] or "").strip() == (lost_item["category"] or "").strip():
        score += 20.0

    # Location - 20%
    if (found_item["location"] or "").strip() == (lost_item["location"] or "").strip():
        score += 20.0

    # Date proximity - 10%
    score += date_score(found_item["item_date"], lost_item["item_date"])

    # Description similarity - 10%
    score += 10.0 * word_overlap_ratio(
        found_item.get("description") if isinstance(found_item, dict) else found_item["description"],
        lost_item.get("description") if isinstance(lost_item, dict) else lost_item["description"],
    )

    return int(round(min(100.0, score)))


def find_matches(found_item, lost_items, threshold=MATCH_THRESHOLD):
    """Public match cards only: name, score, category, location, date, description."""
    matches = []
    try:
        matching_status = found_item["status"]
    except (KeyError, IndexError, TypeError):
        matching_status = None
    expected_status = {"FOUND": "LOST", "LOST": "FOUND"}.get(matching_status)

    for lost in lost_items:
        if lost["id"] == found_item["id"]:
            continue
        if expected_status:
            try:
                candidate_status = lost["status"]
            except (KeyError, IndexError, TypeError):
                candidate_status = None
            if candidate_status != expected_status:
                continue

        name_similarity = word_overlap_ratio(
            strip_model_codes(found_item["item_name"]),
            strip_model_codes(lost["item_name"]),
        )
        description_similarity = word_overlap_ratio(
            found_item.get("description") if isinstance(found_item, dict) else found_item["description"],
            lost.get("description") if isinstance(lost, dict) else lost["description"],
        )
        if not name_similarity and not description_similarity:
            continue

        score = calculate_match_score(found_item, lost)
        if score >= threshold:
            try:
                location_details = lost["location_details"]
            except (KeyError, IndexError, TypeError):
                location_details = ""
            matches.append(
                {
                    "id": lost["id"],
                    "item_name": lost["item_name"],
                    "score": score,
                    "category": lost["category"],
                    "location": lost["location"],
                    "location_details": location_details,
                    "item_date": lost["item_date"],
                    "description": lost["description"],
                }
            )
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches


def pretty_date(value):
    parsed = parse_date(value)
    if not parsed:
        return value or ""
    return parsed.strftime("%d %b %Y")


__all__ = [
    "calculate_match_score",
    "find_matches",
    "pretty_date",
    "MATCH_THRESHOLD",
    "date",
]
