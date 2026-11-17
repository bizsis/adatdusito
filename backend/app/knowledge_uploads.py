"""CSV/XLSX adapter and durable orchestration, not a second reference importer.

Only approved product columns are adapted to an UNAS-shaped, textual stream;
reference_products.import_export remains the single row/upsert/checkpoint engine.
"""

import logging
import re
import secrets
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import now
from app.import_parser import analyze, rows, blank_row
from app.reference_products import import_export, fold, gtin_issues
from app.unas_models import ReferenceImportChunk, ReferenceImportRun
from app.unas_schema import registry
from app.worker import celery

log = logging.getLogger(__name__)
FIELDS = {
    "sku": "Cikkszám",
    "name": "Termék Név",
    "brand": "Paraméter: Márka||text",
    "gtin": "Paraméter: EAN||text",
    "category": "Kategória",
    "short_description": "Rövid Leírás",
    "long_description": "Tulajdonságok",
    "image": "Kép link",
    "unit": "Egység",
}
LABELS = {
    "sku": "Cikkszám",
    "name": "Terméknév",
    "brand": "Gyártó / márka",
    "gtin": "EAN / GTIN",
    "category": "Kategória",
    "short_description": "Rövid leírás",
    "long_description": "Termékleírás",
    "image": "Kép URL",
    "unit": "Mértékegység",
    "parameter": "Termékparaméter",
    "exclude": "Kizárva",
}
PRIVATE = re.compile(
    r"(^|[^a-z])(email|e mail|telefon|phone|ugyfel|vevo|vasarlo|customer|szamlaz|szallitasi cim|address|nevjegy|kapcsolattarto|contact|szemely|rendeles|order)([^a-z]|$)"
)
ALIASES = {
    "sku": ["sku", "cikkszam", "articlenr", "itemnumber"],
    "name": ["name", "termek nev", "termeknev", "product_name", "megnevezes"],
    "brand": ["gyarto", "brand", "manufacturer", "marka"],
    "gtin": ["ean", "gtin", "barcode", "vonalkod"],
    "category": ["category", "kategoria"],
    "image": ["image_url", "kep link"],
    "unit": ["unit", "egyseg"],
}
MAX_ROWS = 1_000_000


def automatic(headers):
    mapping = {}
    entries = registry(headers)
    for i, header in enumerate(headers):
        key = fold(header)
        if PRIVATE.search(key):
            continue
        field = next((f for f, values in ALIASES.items() if key in values), None)
        if field is None:
            field = next(
                (f for f, canonical in FIELDS.items() if fold(canonical) == key), None
            )
        if field is None and entries[i]["parameter"] and entries[i]["shareable"]:
            parameter = entries[i]["parameter"]
            if (
                re.fullmatch(r"EAN(?: \d+)?", parameter["name"])
                and not parameter["group_name"]
            ):
                field = "gtin"
            elif parameter["name"] == "Márka" and not parameter["group_name"]:
                field = "brand"
            else:
                field = "parameter"
        if field:
            mapping[str(i)] = field
    # Duplicate standard meanings need an explicit choice. EAN may have several columns.
    for field in FIELDS.keys() - {"gtin"}:
        found = [i for i, value in mapping.items() if value == field]
        if len(found) > 1:
            for i in found:
                del mapping[i]
    return mapping


def canonical_headers(headers, mapping):
    output, positions = [], []
    if any(not str(index).isdigit() or len(str(index)) > 3 for index in mapping):
        raise ValueError("Az oszlopindexek csak nemnegatív egész számok lehetnek.")
    for index, field in sorted(mapping.items(), key=lambda x: int(x[0])):
        i = int(index)
        if not 0 <= i < len(headers) or field not in LABELS:
            raise ValueError("Érvénytelen oszlopmegfeleltetés.")
        if field == "exclude":
            continue
        original = registry([headers[i]])[0]
        if original["field_group"] in {
            "price",
            "stock",
            "visibility",
            "seo",
            "system",
            "shipping",
            "payment",
            "customer_group",
        }:
            raise ValueError(
                "Ár, készlet, rendszer- vagy ügyféladat nem importálható terméktudásként."
            )
        if PRIVATE.search(fold(headers[i])):
            raise ValueError(
                "Személyes vagy ügyféladat oszlopa nem importálható terméktudásként."
            )
        if field == "parameter":
            header = (
                headers[i]
                if headers[i].startswith("Paraméter: ")
                else f"Paraméter: {headers[i]}||text"
            )
            entry = registry([header])[0]
            if not entry["shareable"] or len(entry["parameter"]["name"]) > 255:
                raise ValueError("Ez a paraméter nem osztható meg terméktudásként.")
        else:
            header = FIELDS[field]
            if field == "gtin" and any(h.startswith("Paraméter: EAN") for h in output):
                header = f"Paraméter: EAN {sum(h.startswith('Paraméter: EAN') for h in output)+1}||text"
        if header in output:
            raise ValueError("Egy célmezőhöz több oszlop tartozik; válassz egyet.")
        if len(header) > 500:
            raise ValueError("Túl hosszú paraméternév.")
        output.append(header)
        positions.append(i)
    if "Termék Név" not in output:
        raise ValueError("Terméknév-oszlop szükséges.")
    if "Cikkszám" not in output and not any(
        h.startswith("Paraméter: EAN") for h in output
    ):
        raise ValueError("Cikkszám vagy EAN-oszlop szükséges.")
    return output, positions


@contextmanager
def materialize(db, run):
    with tempfile.NamedTemporaryFile(suffix=Path(run.file_name).suffix.lower()) as file:
        found = False
        for part in db.scalars(
            select(ReferenceImportChunk)
            .where(ReferenceImportChunk.run_id == run.id)
            .order_by(ReferenceImportChunk.ordinal)
            .execution_options(yield_per=16)
        ):
            file.write(part.data)
            found = True
        if not found:
            raise ValueError("A referenciaforrás feltöltött fájlja nem érhető el.")
        file.flush()
        yield file.name


def heartbeat(db, run, token, state):
    with db.no_autoflush:
        status = db.execute(
            select(ReferenceImportRun.state, ReferenceImportRun.ui_task_token).where(
                ReferenceImportRun.id == run.id
            )
        ).one()
    if status != (state, token):
        db.rollback()
        db.refresh(run)
        return False
    run.ui_lease_until = now() + timedelta(minutes=15)
    db.commit()
    return True


def process(db, id):
    run = db.scalar(
        select(ReferenceImportRun).where(ReferenceImportRun.id == id).with_for_update()
    )
    if not run or run.state not in (
        "queued",
        "queued_import",
        "analyzing",
        "converting",
        "running",
    ):
        return
    if run.ui_task_token and run.ui_lease_until and run.ui_lease_until > now():
        return
    analyzing = run.state in ("queued", "analyzing")
    run.state = "analyzing" if analyzing else "converting"
    token = secrets.token_hex(24)
    run.ui_task_token, run.ui_lease_until = token, now() + timedelta(minutes=15)
    db.commit()
    try:
        with materialize(db, run) as path:
            if analyzing:
                config, analysis = analyze(
                    path, run.file_name, run.ui_config.get("parser", {})
                )
                if any(len(h) > 500 for h in analysis["headers"]):
                    raise ValueError("Túl hosszú forrásfejléc.")
                mapping = automatic(analysis["headers"])
                analysis = {"headers": analysis["headers"]}
                physical = products = 0
                preview = []
                for line, values in rows(path, config):
                    if line <= config["header_line"]:
                        continue
                    physical += 1
                    if physical > MAX_ROWS:
                        raise ValueError("A referenciaimport sorlimitje túllépve.")
                    if not blank_row(values):
                        products += 1
                        if len(preview) < 10:
                            preview.append(
                                {
                                    "line": line,
                                    "values": [
                                        (
                                            str(v)
                                            if len(str(v)) <= 1024
                                            else str(v)[:1024] + "…"
                                        )
                                        for v in values
                                    ],
                                }
                            )
                    if physical % 1000 == 0:
                        run.counters = {"analyzed_rows": physical}
                        if not heartbeat(db, run, token, "analyzing"):
                            return
                analysis.update({"physical_rows": physical, "data_rows": products})
                run.ui_config = {
                    **run.ui_config,
                    "parser": config,
                    "analysis": analysis,
                    "mapping": mapping,
                    "preview_entries": preview,
                }
                run.counters = {
                    "physical_rows": physical,
                    "data_rows": products,
                    "empty_rows": physical - products,
                }
                run.state = "preview"
                run.ui_task_token = run.ui_lease_until = None
                db.commit()
                return
            conf = run.ui_config
            headers, positions = canonical_headers(
                conf["analysis"]["headers"], conf["mapping"]
            )
            identities = {
                position: header
                for position, header in zip(positions, headers)
                if header == "Cikkszám"
                or re.match(r"^Paraméter: EAN(?: \d+)?\|\|", header)
            }
            synthetic_sku = "Cikkszám" not in headers
            if synthetic_sku:
                headers = ["Cikkszám"] + headers
            prepared = {
                "headers": headers,
                "total": conf["analysis"]["physical_rows"],
                "warnings": [],
                "excluded_cells": (
                    run.counters.get("excluded_cells", 0) if run.ui_cursor else 0
                ),
            }

            def warn(line, position, code):
                prepared["excluded_cells"] += 1
                if len(prepared["warnings"]) < 200:
                    prepared["warnings"].append(
                        {"line": line, "column": position, "code": code}
                    )

            def adapted_rows():
                for line, values in rows(path, conf["parser"]):
                    if line <= conf["parser"]["header_line"]:
                        continue
                    canonical_line = line - conf["parser"]["header_line"] + 1
                    if canonical_line <= run.ui_cursor:
                        continue
                    selected = []
                    for position in positions:
                        value = values[position] if position < len(values) else ""
                        if position in identities and getattr(
                            value, "uncertain_identifier", False
                        ):
                            value = ""
                            warn(line, position, "uncertain_identifier")
                        if (
                            value
                            and position in identities
                            and identities[position] != "Cikkszám"
                            and gtin_issues(str(value))
                        ):
                            value = ""
                            warn(line, position, "invalid_gtin")
                        if str(value).lstrip().startswith("=") or any(
                            ord(c) < 32 and c not in "\t\r\n" for c in str(value)
                        ):
                            value = ""
                            warn(line, position, "excluded_cell")
                        selected.append(str(value))
                    if synthetic_sku:
                        code = next(
                            (
                                v
                                for h, v in zip(headers[1:], selected)
                                if h.startswith("Paraméter: EAN") and not gtin_issues(v)
                            ),
                            "",
                        )
                        selected.insert(0, f"gtin:{code}" if code else "")
                    yield canonical_line, headers, selected

            prepared["rows"] = adapted_rows
            if not heartbeat(db, run, token, "converting"):
                return
            run.state = "running"
            run.ui_config = {
                **run.ui_config,
                "source_line_offset": conf["parser"]["header_line"] - 1,
            }
            db.commit()
            import_export(
                db,
                path,
                store_key=f"admin-{run.source_id}",
                version=f"upload-{id}",
                run=run,
                prepared=prepared,
                checkpoint=lambda db, row: heartbeat(db, row, token, "running"),
            )
            if run.ui_task_token != token:
                return
            run.ui_task_token = run.ui_lease_until = None
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Reference admin import failed: run_id=%s", id)
        run = db.get(ReferenceImportRun, id)
        if run and run.ui_task_token == token:
            run.state = "failed"
            run.errors = list(run.errors or []) + [
                {"line": None, "code": "processing_failed"}
            ]
            run.ui_task_token = run.ui_lease_until = None
            run.finished_at = now()
            db.commit()


@celery.task(name="reference.admin_import", acks_late=True, reject_on_worker_lost=True)
def import_job(id):
    with Session(engine()) as db:
        process(db, id)


def enqueue(id):
    import_job.delay(id)
