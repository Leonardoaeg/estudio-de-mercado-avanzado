from eci.classifiers.angle_classifier import classify_angle
from eci.classifiers.claims_risk import analyze_claims_risk, is_claims_sensitive_niche
from eci.classifiers.format_classifier import classify_format, format_distribution
from eci.classifiers.hook_classifier import classify_hook, extract_hook_text
from eci.classifiers.offer_classifier import classify_offer, extract_discount_percentage
from eci.classifiers.style_flags import detect_style_flags
from eci.models.schemas import AdFormat


def test_format_classifier_trusts_valid_hint():
    fmt, confidence = classify_format("video", None)
    assert fmt == AdFormat.VIDEO
    assert confidence == 1.0


def test_format_classifier_ignores_invalid_hint_falls_back_to_text():
    fmt, confidence = classify_format("not_a_format", "mira el video completo aqui")
    assert fmt == AdFormat.VIDEO
    assert 0 < confidence < 1


def test_format_classifier_unknown_when_nothing_available():
    fmt, confidence = classify_format(None, None)
    assert fmt == AdFormat.UNKNOWN
    assert confidence == 0.0


def test_format_distribution_percentages_sum_to_100():
    formats = [AdFormat.VIDEO, AdFormat.VIDEO, AdFormat.IMAGE, AdFormat.CAROUSEL]
    dist = format_distribution(formats)
    assert abs(sum(dist.values()) - 100.0) < 0.01
    assert dist["video"] == 50.0


def test_format_distribution_empty_list():
    dist = format_distribution([])
    assert dist == {"video": 0.0, "image": 0.0, "carousel": 0.0, "unknown": 0.0}


def test_hook_classifier_detects_question():
    label, confidence = classify_hook("¿Sigues sufriendo de dolor de espalda?")
    assert label in ("question", "problem")
    assert confidence > 0


def test_hook_classifier_none_on_empty_text():
    label, confidence = classify_hook(None)
    assert label is None
    assert confidence == 0.0


def test_extract_hook_text_truncates_and_marks_unavailable():
    assert extract_hook_text(None) == "not_available"
    words = extract_hook_text("uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis diecisiete dieciocho", max_words=5)
    assert words.startswith("uno dos tres cuatro cinco")
    assert words.endswith("…")


def test_angle_classifier_ahorro():
    label, confidence = classify_angle("Ahorra dinero hoy con nuestro descuento especial")
    assert label == "ahorro"


def test_offer_classifier_percentage_discount_and_extraction():
    label, confidence = classify_offer("Aprovecha 25% off solo por hoy")
    assert label == "percentage_discount"
    assert extract_discount_percentage("Aprovecha 25% off solo por hoy") == 25.0


def test_offer_classifier_no_offer_default():
    label, confidence = classify_offer("Un texto cualquiera sin ofertas ni descuentos")
    assert label == "no_offer"


def test_offer_classifier_2x1():
    label, _ = classify_offer("Llévate el 2x1 exclusivo de esta semana")
    assert label == "2x1"


def test_style_flags_detects_multiple_independent_flags():
    text = "Testimonio real: mira cómo funciona este producto, a diferencia de otros del mercado."
    flags = detect_style_flags(text)
    assert flags["testimonial_detected"] is True
    assert flags["demonstration_detected"] is True
    assert flags["comparison_detected"] is True


def test_style_flags_none_when_no_text():
    flags = detect_style_flags(None)
    assert all(v is None for v in flags.values())


def test_claims_risk_detects_cure_claim():
    flags = analyze_claims_risk("Este suplemento cura la diabetes y elimina el dolor para siempre")
    assert "cura_enfermedad" in flags
    assert "elimina_definitivo" in flags


def test_claims_risk_empty_for_clean_copy():
    assert analyze_claims_risk("Compra ahora nuestro nuevo vestido con envío gratis") == []


def test_claims_risk_empty_text():
    assert analyze_claims_risk(None) == []


def test_claims_sensitive_niches():
    assert is_claims_sensitive_niche("SALUD") is True
    assert is_claims_sensitive_niche("suplementos") is True
    assert is_claims_sensitive_niche("TEXTIL") is False
