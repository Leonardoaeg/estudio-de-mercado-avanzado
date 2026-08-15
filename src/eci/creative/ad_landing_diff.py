"""Ad → Landing comparison — section 27. Purely observational diffing; stores differences,
never conclusions like "this ad is misleading" (that's a HIPÓTESIS a human should judge).
"""

from __future__ import annotations


def diff_ad_vs_landing(ad: dict, landing: dict) -> dict:
    """`ad` has product/price/offer_type; `landing` is the output of analyze_landing().
    Returns a dict of observed discrepancies, each field `not_available` when either side
    lacks the data (never guessed)."""
    if not landing.get("verified"):
        return {
            "price_match": "not_verified",
            "offer_match": "not_verified",
            "reason": landing.get("reason", "landing_not_verified"),
        }

    ad_price = ad.get("price")
    landing_price_text = landing.get("price_text")
    price_match = "not_available"
    if ad_price is not None and landing_price_text:
        try:
            landing_price = float(landing_price_text.replace(".", "").replace(",", "."))
            price_match = "match" if abs(landing_price - ad_price) < max(1, ad_price * 0.05) else "mismatch"
        except ValueError:
            price_match = "not_available"

    ad_offer = ad.get("offer_type")
    offer_match = "not_available"
    if ad_offer and ad_offer != "no_offer":
        landing_signals = {
            "free_shipping": landing.get("has_free_shipping"),
            "bundle": landing.get("has_bundle"),
            "2x1": landing.get("has_bundle"),
            "3x2": landing.get("has_bundle"),
            "guarantee": landing.get("has_guarantee"),
        }
        offer_match = "match" if landing_signals.get(ad_offer) else "not_confirmed_on_landing"

    return {"price_match": price_match, "offer_match": offer_match, "reason": None}
