"""Resumable supplier import tasks on the existing Celery infrastructure."""

import hashlib
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import engine
from app.models import now
from app.import_models import (
    ImportRun,
    ImportChunk,
    ImportRow,
    SupplierProduct,
    ImportChange,
    ImportProfile,
)
from app.import_parser import analyze, rows, normalize, IDENTIFIERS, FIELDS
from app.worker import celery


def limit(name, default):
    return int(os.getenv(name, str(default)))


@contextmanager
def materialize(db, run):
    with tempfile.NamedTemporaryFile(
        suffix=".xlsx" if run.filename.lower().endswith(".xlsx") else ".csv"
    ) as f:
        wrote = False
        for chunk in db.scalars(
            select(ImportChunk)
            .where(ImportChunk.run_id == run.id)
            .order_by(ImportChunk.ordinal)
            .execution_options(yield_per=16)
        ):
            f.write(chunk.data)
            wrote = True
        if not wrote:
            raise ValueError("A forrásfájl nem érhető el (megőrzési idő lejárt).")
        f.flush()
        yield f.name


def claim(db, run_id):
    run = db.scalar(select(ImportRun).where(ImportRun.id == run_id).with_for_update())
    if not run or run.state not in ("uploaded", "processing"):
        return None
    if run.lease_until and run.lease_until > now():
        return None
    token = secrets.token_hex(16)
    run.task_token = token
    run.lease_until = now() + timedelta(minutes=5)
    db.commit()
    return token


def advance(db, run_id):
    token = claim(db, run_id)
    if not token:
        return
    try:
        run = db.get(ImportRun, run_id)
        with materialize(db, run) as path:
            if run.state == "uploaded":
                config, analysis = analyze(path, run.filename, run.config)
                profiles = list(
                    db.scalars(
                        select(ImportProfile)
                        .where(
                            ImportProfile.tenant_id == run.tenant_id,
                            ImportProfile.supplier_id == run.supplier_id,
                            ImportProfile.id == run.profile_id
                            if run.profile_id
                            else True,
                        )
                        .order_by(ImportProfile.id.desc())
                    )
                )
                for p in profiles:
                    old = p.config.get("analysis", {})
                    if sorted(old.get("headers", [])) == sorted(analysis["headers"]):
                        # Reorder via stable header identity; duplicate headers need review.
                        headers = analysis["headers"]
                        if len(headers) != len(set(headers)):
                            break
                        mapping = {
                            str(headers.index(old["headers"][int(i)])): v
                            for i, v in p.config["mapping"].items()
                        }
                        drift = []
                        if not analysis.get("preview") or not old.get("preview"):
                            drift.append("insufficient_sample")
                        for col in analysis["columns"]:
                            prev = next(
                                (
                                    c
                                    for c in old["columns"]
                                    if c["header"] == col["header"]
                                ),
                                {},
                            )
                            from decimal import Decimal

                            a, b = prev.get("numeric_mean"), col.get("numeric_mean")
                            if (
                                a
                                and b
                                and Decimal(a) != 0
                                and (
                                    abs(Decimal(b) / Decimal(a)) > 10
                                    or abs(Decimal(b) / Decimal(a)) < Decimal("0.1")
                                )
                            ):
                                drift.append("significant_distribution_changed")
                            if prev.get("numeric_ratio") != col["numeric_ratio"]:
                                drift.append("type_or_distribution_changed")
                            if mapping.get(str(col["index"])) in (
                                "currency",
                                "tax_basis",
                                "price_type",
                            ) and col["samples"] != prev.get("samples"):
                                drift.append("financial_context_changed")
                        analysis["matched_profile_id"] = p.id
                        analysis["drift"] = sorted(set(drift))
                        analysis["suggested_mapping"] = mapping
                        run.profile_id = p.id
                        if p.config.get("automatic") and not drift:
                            run.config = {
                                **{
                                    k: v for k, v in p.config.items() if k != "analysis"
                                },
                                **config,
                                "mapping": mapping,
                                "approved_columns": [
                                    {**c, "column": headers.index(c["header"])}
                                    for c in p.config.get("approved_columns", [])
                                ],
                            }
                            run.approved_by = p.approved_by
                            run.state = "processing"
                        break
                run.analysis = analysis
                if run.state != "processing":
                    run.config = config
                    run.state = "awaiting_approval"
                run.lease_until = None
                run.task_token = None
                db.commit()
                if run.state == "processing":
                    return advance(db, run_id)
                return
            config = run.config
            counts = dict(run.counters or {})
            batch = 0
            for line, raw in rows(path, config):
                if line <= config["header_line"] or line <= run.cursor:
                    continue
                if line > limit("IMPORT_MAX_ROWS", 250000) + config["header_line"]:
                    raise ValueError("Import sorszámkorlát túllépve")
                if batch == 0:
                    db.expire_all()
                    run = db.scalar(
                        select(ImportRun)
                        .where(ImportRun.id == run_id)
                        .with_for_update()
                    )
                    if run.state != "processing" or run.task_token != token:
                        return
                if db.get(ImportRow, (run.id, line)) is not None:
                    run.cursor = line
                    continue  # Durable rows are never applied twice on retry.
                cells = raw
                raw = [str(v) for v in raw]
                issues = []
                values = {}
                provenance = {}
                if not any(v.strip() for v in raw):
                    state = "empty"
                elif len(raw) != len(run.analysis["headers"]):
                    state = "error"
                    issues = ["column_count_mismatch"]
                else:
                    for column, field in config["mapping"].items():
                        index = int(column)
                        value, problems = normalize(field, cells[index])
                        values[field] = value
                        provenance[field] = {
                            "column": index,
                            "header": run.analysis["headers"][index],
                            "raw": raw[index],
                            "excel_format": getattr(cells[index], "excel_format", None),
                            "excel_numeric": getattr(cells[index], "numeric", None),
                        }
                        issues += [field + ":" + problem for problem in problems]
                    for field in ("price_type", "tax_basis", "currency"):
                        if not values.get(field) and config.get(field):
                            values[field] = config[field]
                            provenance[field] = {
                                "profile_id": run.profile_id,
                                "method": "approved_profile_default",
                            }
                    usable = [
                        k
                        for k in IDENTIFIERS | {"name"}
                        if values.get(k)
                        and not any(x.startswith(k + ":") for x in issues)
                    ]
                    state = "ready" if usable else "error"
                    if not usable:
                        issues.append("missing_identity_or_name")
                keyfield = config.get("identity_field")
                keyvalue = values.get(keyfield) if keyfield else None
                # No fuzzy/name-only merge. A missing reliable key remains run-local.
                key = hashlib.sha256(
                    json.dumps(
                        [config.get("identity_namespace", "supplier"), keyvalue]
                        if keyvalue
                        and not any(x.startswith(keyfield + ":") for x in issues)
                        else ["row", run.id, line],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                product = None
                if state == "ready":
                    if counts.get("ready", 0) >= limit("IMPORT_MAX_PRODUCTS", 100000):
                        raise ValueError("Import termékszámkorlát túllépve")
                    product = db.scalar(
                        select(SupplierProduct)
                        .where(
                            SupplierProduct.tenant_id == run.tenant_id,
                            SupplierProduct.supplier_id == run.supplier_id,
                            SupplierProduct.identity_key == key,
                        )
                        .with_for_update()
                    )
                    if product and product.last_run_id == run.id:
                        state = (
                            "duplicate"
                            if all(product.data.get(k) == v for k, v in values.items())
                            else "conflict"
                        )
                        issues.append(
                            "duplicate_key"
                            if state == "duplicate"
                            else "conflicting_duplicate_key"
                        )
                    else:
                        if not product:
                            product = SupplierProduct(
                                tenant_id=run.tenant_id,
                                supplier_id=run.supplier_id,
                                identity_key=key,
                                data={},
                                last_run_id=run.id,
                                last_line=line,
                            )
                            db.add(product)
                            db.flush()
                        previous = product.data
                        if config.get("feed_type") != "full":
                            values = {k: v for k, v in values.items() if v is not None}
                        delta = {
                            k: {"before": previous.get(k), "after": v}
                            for k, v in values.items()
                            if previous.get(k) != v
                        }
                        if delta:
                            db.add(
                                ImportChange(
                                    product_id=product.id,
                                    run_id=run.id,
                                    line=line,
                                    delta=delta,
                                )
                            )
                        # Partial feeds change only mapped fields; never delete missing products.
                        product.data = {**previous, **values}
                        product.last_run_id = run.id
                        product.last_line = line
                existing = db.get(ImportRow, (run.id, line))
                if existing is None:
                    db.add(
                        ImportRow(
                            run_id=run.id,
                            line=line,
                            raw=raw,
                            normalized={
                                "schema_version": "1.0",
                                "normalizer_version": "1.0",
                                "provenance": provenance,
                                "profile_id": run.profile_id,
                                "missing_fields": [
                                    k for k in FIELDS if not values.get(k)
                                ],
                                "uncertain_fields": sorted(
                                    set(i.split(":")[0] for i in issues if ":" in i)
                                ),
                                "mapping": config.get("approved_columns", []),
                            },
                            issues=issues,
                            state=state,
                            product_id=product.id if product else None,
                        )
                    )
                counts[state] = counts.get(state, 0) + 1
                run.cursor = line
                batch += 1
                if batch >= 100:
                    run.counters = dict(counts)
                    run.updated_at = now()
                    run.lease_until = now() + timedelta(minutes=5)
                    db.commit()
                    batch = 0
            if config.get("feed_type") == "full":
                from sqlalchemy import func

                counts["not_seen_in_full_feed"] = db.scalar(
                    select(func.count())
                    .select_from(SupplierProduct)
                    .where(
                        SupplierProduct.tenant_id == run.tenant_id,
                        SupplierProduct.supplier_id == run.supplier_id,
                        SupplierProduct.last_run_id != run.id,
                    )
                )
            run.counters = dict(counts)
            run.state = (
                "partial"
                if counts.get("error") or counts.get("conflict")
                else "completed"
            )
            run.lease_until = None
            run.task_token = None
            run.updated_at = now()
            db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(ImportRun, run_id)
        if run and run.task_token == token:
            run.error = f"{type(exc).__name__}: {str(exc)[:900]}"
            run.state = "failed"
            run.lease_until = None
            run.task_token = None
            db.commit()
        raise


@celery.task(name="supplier.import", acks_late=True, reject_on_worker_lost=True)
def process_import(run_id):
    with Session(engine()) as db:
        advance(db, run_id)


def enqueue(run_id):
    process_import.delay(run_id)
