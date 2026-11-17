"""Bounded, deterministic worktable generation from the existing streaming parser.

Snapshots contain source text, UNAS worktable fields and *assigned* donor
parameter definitions. Neither AI, credits, reference writes nor value-list
copies are involved. The native UNAS export is a separate product operation.
"""

import csv
import hashlib
import json
import logging
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from app.models import now
from app.import_models import ImportRun, ImportRow
from app.product_models import ProductClassification
from app.template_models import ImportTemplate, TemplateChunk
from app.import_engine import materialize
from app.import_parser import rows, blank_row
from app.product_catalog import fold, internal_category, parameter_profile_state
from app.product_parameters import Catalog
from app.catalog_store import active_version
from app.worker import celery
from app.db import engine

log = logging.getLogger(__name__)
UNAS_REQUIRED = ["Cikkszám", "Termék Név", "Kategória", "Nettó Ár", "Bruttó Ár"]
UNAS_RECOMMENDED = [
    "Státusz",
    "Rövid Leírás",
    "Tulajdonságok",
    "Kép link",
    "Raktárkészlet",
    "Vásárolható, ha nincs Raktáron",
    "Egység",
    "SEO Title",
    "SEO Description",
    "Kép ALT/TITLE",
    "SEF URL",
    "Akciós Nettó Ár",
    "Akciós Bruttó Ár",
    "Alternatív Kategória 1.",
]
# Only unambiguous source meanings suppress added columns. Purchase/list/sale
# prices with unknown net/gross context are deliberately absent.
ALIASES = {
    "Cikkszám": ["sku", "cikkszam", "article", "itemnumber", "articlenr"],
    "Termék Név": ["name", "product_name", "terméknév", "megnevezés"],
    "Kategória": ["category", "kategoria"],
    "Nettó Ár": ["net price", "net_price"],
    "Bruttó Ár": ["gross price", "gross_price"],
    "Raktárkészlet": ["stock", "quantity"],
    "Egység": ["unit"],
    "Kép link": ["image_url"],
}


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for data in iter(lambda: file.read(60000), b""):
            digest.update(data)
    return digest.hexdigest()


def field_mapping(headers, approved=None):
    """Stable column indices, including duplicate headers; never rename originals."""
    approved = approved or {}
    result = {}
    for field in UNAS_REQUIRED + UNAS_RECOMMENDED:
        if field in approved:
            index = approved[field]
            if not isinstance(index, int) or not 0 <= index < len(headers):
                raise ValueError("Érvénytelen forrásoszlop-megfeleltetés.")
            result[field] = index
            continue
        exact = [i for i, h in enumerate(headers) if fold(h) == fold(field)]
        candidates = exact or [
            i
            for i, h in enumerate(headers)
            if fold(h) in {fold(a) for a in ALIASES.get(field, [])}
        ]
        if len(exact) > 1:
            raise ValueError(
                f"A(z) {field} mező több eredeti oszlopban szerepel; válassz forrásoszlopot a sablonbeállításokban."
            )
        if len(candidates) == 1:
            result[field] = candidates[0]
    if set(approved) - set(UNAS_REQUIRED + UNAS_RECOMMENDED):
        raise ValueError("Ismeretlen UNAS-munkamező.")
    if len(set(result.values())) != len(result):
        raise ValueError("Egy forrásoszlop nem tartozhat több UNAS-mezőhöz.")
    return result


def binding(node_id, donor):
    node = internal_category(node_id)
    if not node:
        raise ValueError("Nem választható belső kategória.")
    if donor is None and len(node["donors"]) == 1:
        donor = node["donors"][0]["emag_category_id"]
    if donor is not None and parameter_profile_state(node_id, donor) != "ready":
        raise ValueError(
            "A paraméterprofil nem jóváhagyott vagy nem ehhez a kategóriához tartozik."
        )
    if donor is None and node["donors"]:
        raise ValueError("Válassz paraméterprofilt a kategóriához.")
    return {"node_id": node_id, "donor": donor, "path": " / ".join(node["path"])}


def assignments(db, run, options):
    """Only accepted product classifications, plus explicit template-only choices."""
    result = {}
    query = (
        select(ImportRow.line, ProductClassification)
        .join(
            ProductClassification,
            ImportRow.product_id == ProductClassification.product_id,
        )
        .where(
            ImportRow.run_id == run.id, ProductClassification.tenant_id == run.tenant_id
        )
    )
    for line, item in db.execute(query):
        if item.status == "auto_classified" or item.origin == "manual":
            if (
                parameter_profile_state(
                    item.navigation_node_id, item.donor_emag_category_id
                )
                == "ready"
            ):
                result[line] = binding(
                    item.navigation_node_id, item.donor_emag_category_id
                )
    for key, item in options.get("rows", {}).items():
        result[int(key)] = binding(item["node_id"], item.get("donor"))
    default = options.get("category")
    return result, (
        binding(default["node_id"], default.get("donor")) if default else None
    )


def create_snapshot(db, run, options=None):
    if not run.analysis or not run.config.get("header_line"):
        raise ValueError("Előbb várd meg a forrásfájl elemzését.")
    options = options or {}
    assignments(db, run, options)  # Validate before queueing, including donor guards.
    field_mapping(run.analysis.get("headers", []), options.get("mapping"))
    row = ImportTemplate(run_id=run.id, state="queued", options=options, manifest={})
    db.add(row)
    db.commit()
    return row


def latest(db, run_id):
    return db.scalar(
        select(ImportTemplate)
        .where(ImportTemplate.run_id == run_id)
        .order_by(ImportTemplate.id.desc())
        .limit(1)
    )


def build(db, id):
    """A worker claims once. A crashed worker is replaced by a new snapshot.

    Output chunks commit atomically with readiness. Exceptions preserve earlier
    snapshots and leave this one retryable; partial artifacts are never served.
    """
    item = db.get(ImportTemplate, id)
    if not item or item.state == "ready_for_enrichment":
        return
    claimed = db.execute(
        update(ImportTemplate)
        .where(
            ImportTemplate.id == id,
            ImportTemplate.state.in_(["queued", "failed"]),
        )
        .values(state="building", completed_at=now(), error=None)
    ).rowcount
    db.commit()
    if not claimed:
        return
    try:
        item = db.get(ImportTemplate, id)
        run = db.get(ImportRun, item.run_id)
        choices, default = assignments(db, run, item.options)
        version = active_version(db)
        catalog = Catalog(db, version) if version else None
        with materialize(db, run) as source, tempfile.TemporaryDirectory() as directory:
            headers = None
            width = 0
            matched_lines = set()
            donors = set()
            content_count = physical_count = 0
            for line, raw in rows(source, run.config):
                if line == run.config["header_line"]:
                    headers = list(raw)
                if line <= run.config["header_line"]:
                    continue
                physical_count += 1
                if physical_count > 1048575:
                    raise ValueError("A sablon meghaladja az XLSX sorkorlátját.")
                content_count += not blank_row(raw)
                width = max(width, len(raw))
                if line in choices:
                    matched_lines.add(line)
                chosen = choices.get(line, default) if not blank_row(raw) else None
                if chosen and chosen["donor"] is not None:
                    donors.add(chosen["donor"])
            if headers is None:
                raise ValueError("A fejlécsor nem érhető el.")
            if set(choices) - matched_lines:
                raise ValueError(
                    "A kategóriaválasztás nem létező forrássorra hivatkozik."
                )
            headers += [""] * max(0, width - len(headers))
            mapping = field_mapping(headers, item.options.get("mapping"))
            columns = [
                {"key": f"source:{i}", "header": h, "source_index": i, "kind": "source"}
                for i, h in enumerate(headers)
            ]
            for field in UNAS_REQUIRED + UNAS_RECOMMENDED:
                if field not in mapping:
                    mapping[field] = len(columns)
                    columns.append(
                        {
                            "key": f"unas:{field}",
                            "header": field,
                            "kind": "unas",
                            "required": field in UNAS_REQUIRED,
                        }
                    )
            warnings = []
            if not donors:
                warnings.append(
                    "Még nincs hozzárendelt paraméterprofil; a sablon alapmezői letölthetők."
                )
            if donors and not catalog:
                warnings.append(
                    "Nincs aktív katalógus; a paraméteroszlopok még nem tölthetők be."
                )
            for donor in sorted(donors):
                params = catalog.parameters(donor) if catalog else []
                if not params:
                    warnings.append(
                        f"A(z) {donor} profil paraméterkészlete még nem érhető el."
                    )
                for param in params:
                    source_indices = [
                        i
                        for i, h in enumerate(headers)
                        if fold(h) == fold(param["name"])
                    ]
                    columns.append(
                        {
                            **param,
                            "key": f"emag:{donor}:{param['emag_parameter_id']}",
                            "header": f"{param['name']} [eMAG {donor}/{param['emag_parameter_id']}]",
                            "kind": "parameter",
                            "donor": donor,
                            "source_index": (
                                source_indices[0] if len(source_indices) == 1 else None
                            ),
                        }
                    )
            if len(columns) > 16384 or physical_count > 1048575:
                raise ValueError(
                    "A sablon meghaladja az XLSX sor- vagy oszlopkorlátját."
                )
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet("Munkatábla")

            def append(values):
                cells = []
                for value in values:
                    if len(value) > 32767 or any(
                        ord(c) < 32 and c not in "\t\n\r" for c in value
                    ):
                        raise ValueError(
                            "Az XLSX-ben veszteség nélkül nem tárolható cella van a forrásban."
                        )
                    cell = WriteOnlyCell(sheet, value=value)
                    cell.data_type = "s"  # IDs and formulas remain literal text.
                    cell.number_format = "@"
                    cells.append(cell)
                sheet.append(cells)

            csv_path, xlsx_path = (
                Path(directory) / "template.csv",
                Path(directory) / "template.xlsx",
            )
            preview, unsafe = [], False
            with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)
                export_headers = [c["header"] for c in columns]
                writer.writerow(export_headers)
                append(export_headers)
                for line, raw in rows(source, run.config):
                    if line <= run.config["header_line"]:
                        continue
                    values = list(raw) + [""] * (len(columns) - len(raw))
                    chosen = choices.get(line, default) if not blank_row(raw) else None
                    category_index = mapping["Kategória"]
                    if chosen and category_index >= len(headers):
                        values[category_index] = chosen["path"]
                    if chosen:
                        for index, column in enumerate(columns):
                            source_index = column.get("source_index")
                            if (
                                column["kind"] == "parameter"
                                and column["donor"] == chosen["donor"]
                                and source_index is not None
                                and source_index < len(raw)
                            ):
                                values[index] = raw[source_index]
                    unsafe |= any(
                        str(v).lstrip().startswith(("=", "+", "-", "@"))
                        for v in raw
                        if v
                    )
                    writer.writerow(values)
                    append(values)
                    if len(preview) < 10:
                        preview.append({"line": line, "values": list(values)})
            workbook.save(xlsx_path)
            db.execute(delete(TemplateChunk).where(TemplateChunk.template_id == id))
            artifacts = {}
            for format, path in [("csv", csv_path), ("xlsx", xlsx_path)]:
                digest, size = hashlib.sha256(), 0
                with path.open("rb") as file:
                    for ordinal, data in enumerate(iter(lambda: file.read(60000), b"")):
                        size += len(data)
                        if size > 200 * 1024 * 1024:
                            raise ValueError(
                                "A sablonfájl meghaladja a 200 MiB korlátot."
                            )
                        digest.update(data)
                        db.add(
                            TemplateChunk(
                                template_id=id,
                                format=format,
                                ordinal=ordinal,
                                data=data,
                            )
                        )
                        if ordinal % 16 == 0:
                            db.flush()
                artifacts[format] = {"bytes": size, "sha256": digest.hexdigest()}
            if unsafe:
                warnings.append(
                    "A CSV eredeti képletjellegű szöveget is tartalmazhat. Excelben az XLSX-et használd; a CSV-t szövegként importáld."
                )
            item.manifest = {
                "schema_version": "template-1",
                "parser_config": run.config,
                "source_sha256": file_sha256(source),
                "columns": columns,
                "mapping": mapping,
                "rows": physical_count,
                "products": content_count,
                "preview": preview,
                "catalog_version_id": version.id if version else None,
                "assignments": {str(k): v for k, v in choices.items()},
                "default_category": default,
                "warnings": warnings,
                "artifacts": artifacts,
                "native_unas_export": False,
            }
            item.state, item.completed_at = "ready_for_enrichment", now()
            db.commit()
    except Exception as exc:
        db.rollback()
        log.exception("Template generation failed: template_id=%s", id)
        item = db.get(ImportTemplate, id)
        if item:
            item.state = "failed"
            item.error = (
                str(exc)[:300]
                if isinstance(exc, ValueError)
                else "A sablonkészítés sikertelen. Próbáld újra; az eredeti import megmaradt."
            )
            db.commit()


@celery.task(name="supplier.template", acks_late=True, reject_on_worker_lost=True)
def process_template(id):
    with Session(engine()) as db:
        build(db, id)


def enqueue(id):
    process_template.delay(id)


def auto_template(db, run_id):
    """After analysis/import: base snapshot first, refresh with accepted categories."""
    run = db.get(ImportRun, run_id)
    if (
        run
        and run.analysis
        and run.state in ("awaiting_approval", "completed", "partial")
    ):
        previous = latest(db, run.id)
        fingerprint = hashlib.sha256(
            json.dumps(run.config, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        marker = {"_auto_phase": run.state, "_auto_config": fingerprint}
        if (
            previous
            and previous.state != "failed"
            and all(previous.options.get(k) == v for k, v in marker.items())
        ):
            return
        options = {
            k: v
            for k, v in (previous.options if previous else {}).items()
            if not k.startswith("_auto_")
        }
        item = create_snapshot(db, run, {**options, **marker})
        try:
            enqueue(item.id)
        except Exception:
            item.state, item.error = (
                "failed",
                "A sablonfeladat nem indítható. Próbáld újra később.",
            )
            db.commit()
            raise
