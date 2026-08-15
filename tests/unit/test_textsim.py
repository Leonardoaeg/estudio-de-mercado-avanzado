from eci.utils.textsim import creative_fingerprint, hamming_distance, shingles, similarity, simhash


def test_shingles_basic():
    result = shingles("hola mundo cruel hoy", k=2)
    assert "hola mundo" in result
    assert "mundo cruel" in result


def test_simhash_identical_text_zero_distance():
    a = simhash("oferta especial hoy 20% de descuento")
    b = simhash("oferta especial hoy 20% de descuento")
    assert hamming_distance(a, b) == 0


def test_similarity_identical_is_one():
    assert similarity("mismo texto exacto aqui", "mismo texto exacto aqui") == 1.0


def test_similarity_very_different_text_is_low():
    sim = similarity(
        "oferta especial en vestidos de fiesta con envio gratis",
        "tutorial de programacion en python para principiantes",
    )
    assert sim < 0.75


def test_similarity_near_duplicate_is_high():
    a = "No vas a creer el antes y despues con vestido modelo 2. Oferta 20% off solo hoy."
    b = "No vas a creer el antes y despues con vestido modelo 2! Oferta 20% off solo hoy!!"
    assert similarity(a, b) > 0.85


def test_creative_fingerprint_stable_and_deterministic():
    fp1 = creative_fingerprint("copy a", "hook a", "producto a", "landing.com", "comprar")
    fp2 = creative_fingerprint("copy a", "hook a", "producto a", "landing.com", "comprar")
    assert fp1 == fp2
    assert isinstance(fp1, str)


def test_creative_fingerprint_ignores_missing_parts():
    fp = creative_fingerprint("copy a", None, None, None, None)
    assert isinstance(fp, str) and len(fp) == 16
