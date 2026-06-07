"""Pitcher-name normalisation for matching MLB feed names to sportsbook prop names.

Books and the MLB API disagree on accents, punctuation, suffixes and casing
(e.g. "Luis L. Ortiz" vs "Luis Ortiz", "José Ramírez" vs "Jose Ramirez"). We
normalise both sides before comparing.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_name(name: str) -> str:
    if not name:
        return ""
    # strip accents
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in decomposed if not unicodedata.combining(c))
    ascii_name = ascii_name.lower()
    # drop common suffixes
    ascii_name = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", ascii_name)
    # keep letters/spaces only, collapse whitespace
    ascii_name = re.sub(r"[^a-z\s]", " ", ascii_name)
    return re.sub(r"\s+", " ", ascii_name).strip()


def names_match(a: str, b: str) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    pa, pb = na.split(), nb.split()
    if not pa or not pb:
        return False
    # last-name-only query (e.g. "Nola") matches on surname alone
    if len(pa) == 1 or len(pb) == 1:
        return pa[-1] == pb[-1]
    # otherwise require first-initial + surname (handles middle initials/names)
    return pa[-1] == pb[-1] and pa[0][0] == pb[0][0]
