"""Text similarity primitives used by the Creative Family Detector.

Implements a small, dependency-free SimHash + shingling scheme. This is a text-level
proxy for "these ads are the same creative concept" — it does not look at pixels or video
frames (see IMPLEMENTATION_PLAN.md limitations). It is deliberately simple and fully
unit-testable without any ML dependency.
"""

from __future__ import annotations

import hashlib
import re

_TOKEN_RE = re.compile(r"[a-z0-9áéíóúñü]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def shingles(text: str, k: int = 3) -> set[str]:
    """Word k-shingles (contiguous k-word sequences), the standard input to SimHash."""
    tokens = _tokenize(text)
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def simhash(text: str, *, k: int = 3, bits: int = 64) -> int:
    """A standard SimHash: hash each shingle, then majority-vote each bit position."""
    weights = [0] * bits
    tokens = shingles(text, k=k)
    if not tokens:
        return 0
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            bit = (h >> i) & 1
            weights[i] += 1 if bit else -1
    fingerprint = 0
    for i, w in enumerate(weights):
        if w > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def similarity(a_text: str, b_text: str, *, k: int = 3, bits: int = 64) -> float:
    """0..1 similarity derived from SimHash Hamming distance (1.0 = identical concept)."""
    fa = simhash(a_text, k=k, bits=bits)
    fb = simhash(b_text, k=k, bits=bits)
    dist = hamming_distance(fa, fb)
    return 1.0 - (dist / bits)


def creative_fingerprint(*parts: str | None) -> str:
    """A stable, storable fingerprint string for a creative, combining several text fields
    (copy, hook, product, landing, CTA). Used both for family grouping and for dedup."""
    joined = " || ".join(p.strip() for p in parts if p)
    fp = simhash(joined)
    return f"{fp:016x}"
