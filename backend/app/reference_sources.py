"""Shared provenance and explicit mapping evidence. Observations are never trees.

Unverified source identities remain pending. No source is automatically joined
by its name, and none of these operations writes pinfo_db or parameter values.
"""

from typing import Literal
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models import ReferenceSource, ReferenceObservation
from app.security import database, require, Identity, audit
from app.db import reference_database
from app.reference import categories

router = APIRouter(prefix="/api/v1/reference/sources", tags=["Referenciaforrások"])


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: Literal[
        "emag_marketplace", "emag_webshop", "emag_sitemap", "emag_documentation"
    ]
    evidence_url: str = Field(max_length=1000)
    content_sha256: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["available", "blocked", "unavailable", "partial"]
    source_category_id: str | None = Field(None, min_length=1, max_length=160)
    canonical_emag_id: int | None = Field(None, gt=0)
    mapping_status: Literal["pending", "confirmed", "rejected"] = "pending"
    evidence_kind: Literal["explicit_marketplace_id", "documented_crosswalk"] | None = (
        None
    )
    summary: str = Field(min_length=10, max_length=2000)

    @field_validator("evidence_url")
    @classmethod
    def public_source(cls, value):
        p = urlparse(value)
        if (
            p.scheme != "https"
            or not p.hostname
            or not (p.hostname == "emag.hu" or p.hostname.endswith(".emag.hu"))
            or p.username
            or p.password
            or p.query
            or p.fragment
            or p.port not in (None, 443)
        ):
            raise ValueError(
                "Publikus, hitelesítési adat nélküli emag.hu HTTPS-hivatkozás szükséges."
            )
        return value

    @model_validator(mode="after")
    def explicit_mapping(self):
        if self.mapping_status == "confirmed" and (
            not self.canonical_emag_id
            or not self.source_category_id
            or not self.evidence_kind
            or not self.content_sha256
            or self.outcome not in ("available", "partial")
        ):
            raise ValueError(
                "Azonosítók, bizonyítéktípus, tartalomhash és elérhető forrás szükséges; a névegyezés nem bizonyíték."
            )
        if self.canonical_emag_id is not None and self.mapping_status != "confirmed":
            raise ValueError(
                "Nem igazolt megfigyeléshez nem kapcsolható kanonikus kategória."
            )
        return self


def observation_json(row):
    return {
        k: getattr(row, k)
        for k in [
            "id",
            "source_key",
            "evidence_url",
            "content_sha256",
            "outcome",
            "source_category_id",
            "canonical_emag_id",
            "mapping_status",
            "evidence_kind",
            "summary",
        ]
    } | {"observed_at": row.observed_at.isoformat() + "Z"}


@router.get("")
def sources(
    who: Identity = Depends(require("reference.read")), db: Session = Depends(database)
):
    rows = db.scalars(select(ReferenceSource).order_by(ReferenceSource.key))
    return {
        "items": [
            {"key": r.key, "name": r.name, "description": r.description} for r in rows
        ],
        "canonical_source": "pinfo_db",
        "webshop_completeness": "unverified",
        "automatic_mapping": False,
    }


@router.get("/observations")
def observations(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    who: Identity = Depends(require("reference.read")),
    db: Session = Depends(database),
):
    rows = db.scalars(
        select(ReferenceObservation)
        .order_by(ReferenceObservation.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [observation_json(r) for r in rows],
        "total": db.scalar(select(func.count()).select_from(ReferenceObservation)),
        "offset": offset,
        "limit": limit,
    }


@router.post("/observations", status_code=201)
def observe(
    body: ObservationInput,
    who: Identity = Depends(require("system.manage")),
    db: Session = Depends(database),
):
    if not db.get(ReferenceSource, body.source_key):
        raise HTTPException(409, "A forrásregiszterhez előbb migráció szükséges.")
    if body.source_category_id and body.source_category_id.startswith(
        ("web-dept-", "web-item-")
    ):
        from app.web_navigation import navigation, BINDABLE_KINDS

        snapshot = navigation()
        node = snapshot.nodes.get(body.source_category_id)
        if not node:
            raise HTTPException(404, "Ismeretlen webshop-navigációs azonosító.")
        if body.mapping_status == "confirmed" and (
            body.source_key != "emag_webshop" or node["kind"] not in BINDABLE_KINDS
        ):
            raise HTTPException(
                409,
                "Márka, kampány, szűrő vagy főcsoport nem feleltethető meg termékkategóriának.",
            )
        # Proofs are scoped to the exact captured source version. A subsequent
        # menu export cannot silently inherit an approval for a reused menu ID.
        body = body.model_copy(
            update={"source_category_id": snapshot.proof_key(body.source_category_id)}
        )
    if body.canonical_emag_id:
        with reference_database() as conn:
            if not conn.scalar(
                select(categories.c.id).where(
                    categories.c.emag_category_id == body.canonical_emag_id
                )
            ):
                raise HTTPException(
                    409,
                    "Ismeretlen kanonikus eMAG-azonosító; megfeleltetésre váró megfigyelésként rögzítsd.",
                )
    record = ReferenceObservation(**body.model_dump(), actor_id=who.user.id)
    db.add(record)
    db.flush()
    audit(
        db,
        who,
        "reference.source_observation",
        record.id,
        source_key=body.source_key,
        mapping_status=body.mapping_status,
    )
    db.commit()
    return observation_json(record)
