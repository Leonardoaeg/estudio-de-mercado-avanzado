# IMPLEMENTATION_PLAN.md — Ecommerce Creative Intelligence (ECI)

## 0. Contexto e inspección previa

- No existía ningún proyecto de código para esto. En `Desktop/asistenteclaude` hay un sistema **no relacionado**
  (auditor de conversaciones Lucid Bot). En `Desktop/Investigacion de Productos` no había nada.
  Los "agentes de investigación" existentes en este entorno son **skills de prompt** (`investigacion-mercado-whatsapp`,
  `cazador-de-angulos`) que hacen web-search vía LLM, no un sistema de scraping/BD/scoring reproducible.
  → Decisión: proyecto nuevo, autocontenido, en `Desktop/ecommerce-creative-intelligence/` (carpeta hermana),
  para no mezclar con el dominio de Lucid Bot.
- Entorno: Windows 11, Python 3.12.10 disponible vía `python`, Node 25 disponible, acceso a internet OK desde Bash.
- Paquetes ya presentes globalmente: httpx, pandas, pydantic, SQLAlchemy. Faltan: typer, jinja2, pytest, playwright,
  beautifulsoup4, lxml, alembic → se instalan en un venv local del proyecto (`.venv`).

## 1. Alcance real de esta primera versión (honestidad sobre límites)

El prompt original pide un sistema con ~50 subsistemas (incluyendo análisis visual de video con IA, hashing
perceptual de imágenes, motor de tendencias multi-snapshot, etc.). Construir *todo* eso al nivel de un producto
maduro es un esfuerzo de varias semanas. Esta v1 es un **MVP robusto y realmente funcional end-to-end**, con
arquitectura ya preparada para escalar cada módulo. Se declara explícitamente qué queda con heurísticas (no IA
generativa/visión) y qué queda pendiente de credenciales que el usuario debe aportar.

Regla operativa (sección 50 del prompt): ninguna limitación bloquea el proyecto. Cada límite se documenta,
se marca el dato como `not_verified`/`unknown`, se crea una interfaz desacoplada, y se sigue adelante.

### Implementado en v1 (real, con código y tests)
- Arquitectura completa de carpetas, config YAML, CLI Typer con todos los comandos pedidos.
- Base de datos SQLite (compatible Postgres vía SQLAlchemy Core/ORM) + migrations SQL + upsert/dedup.
- Capa `sources` con **abstracción `AdLibrarySource`** y 3 implementaciones:
  - `MetaGraphAPISource`: cliente real contra la Ad Library API oficial de Meta (`graph.facebook.com/ads_archive`).
    Funciona en cuanto el usuario aporte `META_ACCESS_TOKEN` en `.env`. Sin token → error controlado, no inventa datos.
  - `MetaWebScraperSource`: scraper con Playwright sobre la Ad Library pública (`facebook.com/ads/library`), con
    retry/backoff/jitter/timeouts/checkpoints. Requiere `playwright install chromium` (no ejecutado en este entorno
    por tiempo/red del sandbox); queda listo para correr localmente.
  - `MockSource`: fuente determinística basada en fixtures, usada por tests y por la demo end-to-end offline.
- Discovery engine (expansión de keywords → subnichos) — puro, testeado.
- Ecommerce validator (heurística de carrito/checkout/precio) — real, hace fetch HTTP real, testeado con fixtures.
- Shopify detector multi-señal — real, testeado.
- Clasificadores por heurística de texto (formato, hook, ángulo, oferta, nicho, claims de riesgo) — reales,
  basados en reglas/regex sobre el texto del anuncio (`primary_text`/`headline`/`description`), **no** sobre
  análisis visual de frames de video (ver limitaciones). Cada clasificación expone `confidence` y
  `classification_confidence`.
- Creative Family Detector: agrupación por shingling + SimHash sobre copy/hook/producto/landing — real, testeado.
- Métricas de longevidad, incluida la referencia pedida por el usuario: **ventana de referencia 30–90 días**
  (`reference_min_age_days=30`, `reference_max_age_days=90`, configurable en `scoring.yaml`) como señal de
  persistencia más fiable que anuncios recién lanzados (<30d) o outliers (>90d).
- Scale Signal Score (0-100, pesos configurables) + Confidence Score (0-100) separados.
- Dos rankings por nicho: Highest Advertising Presence / Fastest Advertising Acceleration.
- Snapshots + comparación entre snapshots (nuevos/eliminados/familias nuevas) — real sobre SQLite.
- Trend engine + Saturation engine — reales sobre snapshots almacenados.
- Insight engine (estadística → texto, sin afirmaciones causales).
- Claims Risk Analyzer para Salud/Suplementos.
- Landing page analyzer (extrae producto/precio/oferta/reviews/garantía/checkout) — real, sin comprar nada.
- Reportes MD/HTML/CSV/JSON con Jinja2, estructura de 21 secciones pedida, tabla Top10, Deep Dive.
- CLI: `eci research`, `eci research-all`, `eci rank`, `eci trends`, `eci report`, `eci report-all`,
  `--shopify-only`, `--minimum-ads`.
- Tests unitarios reales (pytest) para: normalización URL, parsing fechas, dedup, shopify, ecommerce validator,
  clasificadores, scoring, ranking, family detector, snapshots, generación de reportes, claims risk.
  Tests de integración "live" separados y marcados `@pytest.mark.live` (skip por defecto, requieren red/token).
- Test end-to-end offline usando `MockSource`: corre el pipeline completo DISCOVER→REPORT sin red y genera un
  reporte real en `reports/`.

### Actualización 2026-08-14 — scraper real validado contra Meta Ad Library en vivo

Se instaló Playwright chromium y se reescribió `meta_web_scraper.py` completo: la primera
versión asumía texto en inglés ("Library ID:", "Started running on") que **no coincide**
con la UI real (en español desde Colombia usa "Identificador de la biblioteca:", "En
circulación desde el ..."). Se navegó la Ad Library real en vivo (browser tool), se
capturó el texto exacto, y se reescribió el parser (`parse_ad_library_text`, función pura
y testeada) en base a la estructura real observada. Probado en vivo: `search_ads('vestido',
'CO')` trae 40 anuncios reales con `ad_id`, `page_name`, fecha, copy y **landing_url real**
(decodificado del redirect-shim `l.facebook.com/l.php?u=...`, sin seguir el redirect).

**Nueva regla de negocio (instrucción del operador, 2026-08-14):** marcas grandes o
marketplaces generales (SHEIN, Mercado Libre, Amazon, etc. — lista en
`config/excluded_brands.yaml`) se excluyen de rankings/Deep Dive/CSV de tiendas — nunca se
presentan como ejemplo de tienda pequeña. Sus anuncios sí alimentan las secciones
agregadas de patrones creativos (hooks/ángulos/ofertas) como referencia de mercado. Ver
`src/eci/classifiers/brand_exclusion.py`.

**Limitación de este sandbox (no del código):** la validación de ecommerce/Shopify hace
fetch HTTP real a cada tienda; este entorno de pruebas específico restringe HTTPS saliente
a dominios de terceros arbitrarios (confirmado con tests `live`: `google.com` funciona,
la mayoría de tiendas reales fallan con `CERTIFICATE_VERIFY_FAILED`). En una máquina con
acceso normal a internet esto no debería ocurrir.

### Explícitamente NO implementado / limitado en v1 (declarado, no inventado)
- **Análisis visual real de video/imagen** (frames, OCR sobre creatividades, perceptual hashing de imágenes):
  requiere descargar creatividades (Playwright) + un modelo de visión. La interfaz `CreativeAnalyzer` está
  desacoplada y lista, pero v1 sólo analiza el **texto** del anuncio. Todo campo derivado de visión se guarda
  como `not_available` hasta conectar un backend de visión.
- **Ejecución real de scraping a gran escala contra Meta**: no se ejecutó en este entorno (requiere
  `playwright install` + horas de scraping respetuoso con rate limits). El código está listo; el usuario debe
  correrlo localmente.
- **Token oficial de Meta Ad Library API**: no lo tengo; el usuario debe generarlo y ponerlo en `.env`.
- Migraciones tipo Alembic completas: se usa un enfoque más simple (`migrations/*.sql` + `create_all` de
  SQLAlchemy) documentado como suficiente para v1; Alembic queda como mejora futura (arquitectura ya compatible).

## 2. Arquitectura de módulos (carpetas)

Ver árbol final en `README.md`. Resumen de responsabilidades por carpeta ya creada:
`sources` (fuentes de datos) → `discovery` → `ecommerce` + `shopify` (validación) → `classifiers` + `creative`
(análisis) → `metrics` + `scoring` → `ranking` → `trends` (snapshots) → `insights` → `reports` → `cli`.
`database`/`models` son transversales. `pipeline/orchestrator.py` conecta todo con checkpoints/resume.

## 3. Base de datos (SQLite, compatible Postgres)

Tablas: `research_runs, sources, advertisers, pages, stores, ads, creative_analysis, creative_families,
creative_family_members, snapshots, snapshot_ads, keywords, trends, rankings, errors`.
Claves de dedup: `ad_id` (único por fuente+id), `page_id`, `domain` canónico de `store_url`, fingerprint de
familia creativa (hash). UPSERT vía `INSERT ... ON CONFLICT` (SQLite) / equivalente ORM `merge`.

## 4. Pipeline (fases, cada una reanudable vía checkpoint en `research_runs.stage`)

DISCOVER → COLLECT → NORMALIZE → DEDUPLICATE → VERIFY_ECOMMERCE → DETECT_SHOPIFY → CLASSIFY_NICHE →
ANALYZE_CREATIVES → CREATE_FAMILIES → CALCULATE_METRICS → SCORE → RANK → GENERATE_REPORT → SAVE_SNAPSHOT.

## 5. Orden de implementación real seguido

Fases 1-20 del prompt, colapsadas en el orden: scaffolding+config → DB/models → utils (url/date/http/textsim) →
sources (mock primero, para poder testear todo sin red; luego graph API y scraper) → discovery → ecommerce/shopify
→ classifiers → creative families → metrics/longevity → scoring → ranking → trends/saturation → insights →
reports → CLI → tests → E2E offline con MockSource.

## 6. Riesgos conocidos

1. Meta puede bloquear/cambiar el HTML de la Ad Library en cualquier momento → scraper aislado en un módulo,
   con manejo de error que marca `not_verified` y continúa (no rompe el run).
2. Rate limiting de Meta y de las tiendas destino → retry+backoff+jitter+cache local en `data/cache`.
3. Falsos positivos de Shopify con una sola señal débil → exigimos ≥2 señales para `shopify_detected=true`.
4. Clasificación de hooks/ángulos/ofertas es heurística de texto, no semántica profunda → confidence baja
   explícita, y el reporte nunca presenta esto como verdad absoluta.
5. Sin token de Meta ni `playwright install`, el pipeline real no trae datos — el E2E con `MockSource` prueba que
   el cableado funciona; el research real depende de que el usuario complete esos dos requisitos.

## 7. Criterios de aceptación de esta v1

- `pytest tests/unit` pasa en verde.
- `eci research --niche textil --market CO --source mock` corre sin red y llena la base de datos.
- `eci report --niche textil --market CO` genera MD+HTML+CSV+JSON reales en `reports/<fecha>_<mercado>_<nicho>/`.
- `eci rank` y `eci trends` funcionan sobre datos ya recolectados (mock o reales).
- El reporte contiene explícitamente HECHO/INFERENCIA/HIPÓTESIS y nunca afirma ventas/ROAS.
