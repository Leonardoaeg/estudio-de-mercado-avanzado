"""Sales-angle classifier — section 15."""

from __future__ import annotations

from eci.classifiers._rules import compile_rules, classify_by_rules

ANGLE_RULES = compile_rules(
    {
        "dolor": [r"\bdolor\b", r"sufrimiento", r"molestia", r"cansad[ao] de sufrir"],
        "deseo": [r"deseas", r"sueñas con", r"imagina tener"],
        "comodidad": [r"comodidad", r"cómod[ao]", r"sin esfuerzo", r"fácil de usar"],
        "precio": [r"precio bajo", r"el más barato", r"económico"],
        "ahorro": [r"ahorra", r"ahorro", r"paga menos"],
        "estatus": [r"exclusivo", r"edición limitada", r"lujo", r"vip"],
        "calidad": [r"alta calidad", r"materiales premium", r"durabilidad"],
        "resultado": [r"resultados en", r"funciona de verdad", r"resultados reales"],
        "transformacion": [r"transforma", r"antes y después", r"cambia tu vida"],
        "innovacion": [r"innovador", r"tecnología única", r"nunca antes visto"],
        "rapidez": [r"rápido", r"en minutos", r"al instante"],
        "conveniencia": [r"entrega a domicilio", r"todo en un solo lugar", r"sin salir de casa"],
        "prueba_social": [r"miles de client", r"reseñas", r"testimonios", r"5 estrellas"],
        "comparacion": [r"a diferencia de", r"mejor que", r"comparado con"],
        "garantia": [r"garantía", r"devolución", r"satisfacción garantizada"],
        "escasez": [r"últimas unidades", r"se agota", r"pocas unidades", r"quedan pocas"],
        "regalo": [r"\bregalo\b", r"gratis con tu compra", r"llévate gratis"],
        "bundle": [r"combo", r"paquete", r"kit completo", r"\b2x1\b", r"\b3x2\b"],
        "problema_especifico": [r"problema de", r"solución para", r"acaba con"],
    }
)


def classify_angle(text: str | None) -> tuple[str | None, float]:
    result = classify_by_rules(text, ANGLE_RULES)
    return result.label, result.confidence
