"""Pipeline stage constants + a tiny helper to persist the current checkpoint onto the
`research_runs` row (section 43: "Cada etapa debe poder reanudarse"). Because every write
in this pipeline goes through UPSERT/dedup (database/repository.py), simply re-running
`eci research` with the same niche/market is itself the resume mechanism — no ad, store,
or advertiser is ever duplicated — while `stage` gives an observable record of how far a
run got, for the case where it was interrupted or a stage errored out.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from eci.database.models import ResearchRun

STAGES = [
    "DISCOVER",
    "COLLECT",
    "NORMALIZE",
    "DEDUPLICATE",
    "VERIFY_ECOMMERCE",
    "DETECT_SHOPIFY",
    "CLASSIFY_NICHE",
    "ANALYZE_CREATIVES",
    "CREATE_FAMILIES",
    "CALCULATE_METRICS",
    "SCORE",
    "RANK",
    "GENERATE_REPORT",
    "SAVE_SNAPSHOT",
    "DONE",
]


def set_stage(session: Session, run: ResearchRun, stage: str) -> None:
    assert stage in STAGES, f"Unknown stage {stage}"
    run.stage = stage
    session.flush()
