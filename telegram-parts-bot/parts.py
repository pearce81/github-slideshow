"""Extract Hyundai / Kia part numbers from free-form chat text.

Hyundai/Kia (Mobis) part numbers are usually written as two blocks of five
characters, e.g. ``86511-2S000``, ``58101-2SA70``, ``31112 3X500`` or
``865112S000``. The first block is normally numeric (the part group), the
second block is alphanumeric (model/variant code). Some older Kia numbers
start with letters (``0K2N1-33-28Z``), which are handled by a second pattern.

Everything is normalised to upper case ``XXXXX-XXXXX`` so the same part is
counted once regardless of how people type it.
"""

import re

# Persian (۰-۹) and Arabic-Indic (٠-٩) digits -> ASCII, plus common dash variants.
_TRANSLATE = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩‐‑‒–—―−_",
    "0123456789" "0123456789" "--------",
)

# 5 digits, optional separator, 5 alphanumerics. Not glued to other word chars.
_MOBIS = re.compile(r"(?<![0-9A-Z])(\d{5})[-\s.]?([0-9A-Z]{5})(?![0-9A-Z])")

# Older Kia style: 0K2N1-33-28Z / 0K30A-10-270 (5-2-3 blocks, dashes required).
_KIA_OLD = re.compile(r"(?<![0-9A-Z])([0-9A-Z]{5})-([0-9A-Z]{2})-([0-9A-Z]{3})(?![0-9A-Z])")


def normalize_text(text: str) -> str:
    return text.translate(_TRANSLATE).upper()


def _looks_like_phone(first: str, second: str, sep_present: bool) -> bool:
    # Iranian mobiles (09xxxxxxxxx) and other pure-digit runs typed without a
    # separator are far more likely to be phone numbers / prices than parts.
    return not sep_present and (first + second).isdigit() and first.startswith("0")


def extract_part_numbers(text: str) -> list[str]:
    """Return unique, normalised part numbers in the order they appear."""
    if not text:
        return []
    norm = normalize_text(text)
    found: list[str] = []

    for m in _KIA_OLD.finditer(norm):
        if any(c.isdigit() for c in m.group(1)):
            found.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")

    for m in _MOBIS.finditer(norm):
        first, second = m.group(1), m.group(2)
        sep_present = m.end(1) != m.start(2)
        if _looks_like_phone(first, second, sep_present):
            continue
        found.append(f"{first}-{second}")

    return list(dict.fromkeys(found))
