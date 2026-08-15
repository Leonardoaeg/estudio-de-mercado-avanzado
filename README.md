# Ecommerce Creative Intelligence (ECI)

Agente de investigación competitiva de ecommerce sobre Meta Ad Library: descubre
anunciantes en un nicho/mercado, verifica que tengan tienda transaccional real, detecta
Shopify, clasifica formato/hook/ángulo/oferta de cada anuncio, agrupa familias creativas,
calcula longevidad y un Scale Signal Score, genera dos rankings (presencia y aceleración)
y produce reportes MD/HTML/CSV/JSON por nicho + un informe maestro comparativo.

Ver [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) para el alcance detallado de esta
v1 (qué está implementado de verdad vs. qué queda documentado como limitación).

## Puesta en marcha

```bash
python -m venv .venv
.venv/Scripts/pip install -e .            # o: .venv/bin/pip install -e .  en Linux/Mac
cp .env.example .env                      # opcional: agrega META_ACCESS_TOKEN si lo tienes
```

Para el scraper de Meta Ad Library (fuente `meta_web_scraper`), instala además el
navegador de Playwright (descarga ~150MB, no se ejecuta automáticamente):

```bash
.venv/Scripts/python -m playwright install chromium
```

## Uso rápido (sin red, para verificar que todo funciona)

```bash
eci research --niche textil --market CO --source mock
eci report --niche textil --market CO
eci rank --niche textil --market CO
eci trends --niche textil --market CO   # requiere >=2 ejecuciones para tener variación real
```

Esto corre en segundos, sin red, y deja un reporte real en `reports/<fecha>_CO_textil/`.
La fuente `mock` es **sintética y determinista** — sirve para probar que el pipeline
completo funciona (nunca debe usarse como inteligencia de mercado real).

## Uso con datos reales

```bash
# Opción A: API oficial de Meta Ad Library (requiere META_ACCESS_TOKEN en .env)
eci research --niche textil --market CO --source meta_graph_api

# Opción B: scraping best-effort de la interfaz pública (requiere playwright install)
eci research --niche textil --market CO --source meta_web_scraper
```

```bash
eci research --niche belleza --market CO --minimum-ads 50
eci research-all --market CO
eci research-all --market CO --shopify-only
eci report-all --market CO                # incluye el informe maestro comparativo
```

## Comandos

| Comando | Qué hace |
|---|---|
| `eci research --niche N --market M [--source S] [--minimum-ads N] [--shopify-only]` | Corre el pipeline completo y genera el reporte del nicho |
| `eci research-all --market M` | Corre `research` para los 5 nichos configurados |
| `eci rank --niche N --market M` | Muestra los dos rankings ya calculados (presencia / aceleración) |
| `eci trends --niche N --market M` | Compara los dos snapshots más recientes por marca |
| `eci report --niche N --market M` | Regenera el reporte desde la base de datos, sin recolectar de nuevo |
| `eci report-all --market M` | Regenera todos los reportes + el informe maestro |

## Arquitectura

```
src/eci/
  sources/        AdLibrarySource (ABC) + MockSource / MetaGraphAPISource / MetaWebScraperSource
  discovery/      expansión de keywords -> subnichos
  ecommerce/      validador (cart/checkout/precio -> ecommerce_score)
  shopify/        detector multi-señal
  classifiers/    formato, hook, ángulo, oferta, nicho, claims risk (heurísticas de texto)
  creative/       familias creativas (SimHash), análisis de landing, diff anuncio-vs-landing
  metrics/        longevidad (incluye ventana de referencia 30-90 días)
  scoring/        Scale Signal Score + Confidence Score (separados)
  ranking/        Highest Presence + Fastest Acceleration
  trends/         TrendEngine + SaturationEngine (sobre snapshots)
  insights/       InsightEngine (estadística -> texto, sin causalidad)
  pipeline/       orchestrator.py (DISCOVER -> ... -> SAVE_SNAPSHOT) + checkpoints
  reports/        templates Jinja2 + generator (MD/HTML/CSV/JSON)
  database/       modelos SQLAlchemy + migrations + repository (UPSERT/dedup)
  cli/            Typer app
config/           settings.yaml, keywords.yaml, niches.yaml, scoring.yaml
data/             raw/ normalized/ cache/ (y eci.db, SQLite)
reports/          salida por ejecución: <fecha>_<mercado>_<nicho>/
tests/unit/       92+ tests, sin red
tests/integration/ tests marcados @pytest.mark.live (requieren red/token), skip por defecto
```

## Base de datos

SQLite por defecto (`data/eci.db`), compatible con Postgres cambiando `ECI_DATABASE_URL`
en `.env` (o `database.url` en `config/settings.yaml`) — el código no cambia, solo el DSN.

Tablas: `research_runs, sources, advertisers, pages(implícita en advertisers), stores, ads,
creative_analysis, creative_families, snapshots, keywords, trends, rankings, errors`.

## Tests

```bash
.venv/Scripts/python -m pytest              # unit tests, sin red (default)
.venv/Scripts/python -m pytest -m live      # + tests que sí requieren red/credenciales
```

## Regla de objetividad

El sistema nunca afirma ventas, ROAS o rentabilidad a partir de señales publicitarias.
Todo dato no verificable se marca `not_available`/`unknown`/`not_verified`, nunca se
inventa. Los reportes distinguen explícitamente HECHO / INFERENCIA / HIPÓTESIS.
