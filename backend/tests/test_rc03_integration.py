"""RC-03: TEMPLATE-01 worktables use the UNAS-REF-01 schema registry; approved eMAG-UNAS
mappings never produce a second column for the same UNAS field or parameter.

The mappings below are test-only (they exercise the three placement paths), not business
decisions."""

import csv
import io

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reference_products import import_export
from app.unas_models import ParameterMapping, UnasFieldDefinition, UnasParameterDefinition
from test_import_templates import download, generate, source, templates  # noqa: F401
from test_supplier_import import imports  # noqa: F401
from test_product_parameters import VACUUM, WASHER, install_catalog
from test_unas_reference import ROWS, export


def approve(db, category, parameter, name, *, unas_parameter=None, unas_field=None):
    db.add(ParameterMapping(
        mapping_key=f"{category}:{parameter}:{unas_parameter or '-'}:{unas_field or '-'}",
        emag_category_id=category, emag_parameter_id=parameter, emag_parameter_name=name,
        unas_parameter_id=unas_parameter, unas_field_id=unas_field, status="approved",
        origin="manual"))


def test_template_uses_registry_and_routes_mapped_parameters_without_duplicates(templates,
                                                                                 tmp_path):
    client, target, _, _ = templates
    install_catalog(target)
    with Session(target) as db:
        import_export(db, export(tmp_path, ROWS))  # registers the UNAS schema
        param = {p.name: p.id for p in db.scalars(select(UnasParameterDefinition))
                 if not p.group_name}
        field = {f.header: f.id for f in db.scalars(select(UnasFieldDefinition))}
        # (1) eMAG parameter -> UNAS parameter: the column takes the UNAS header.
        approve(db, 385, 6511, "Szélesség (cm)", unas_parameter=param["Szélesség"])
        # (2) the same UNAS target from two donors: one shared column.
        approve(db, 385, 6506, "Teljesítmény (W)", unas_parameter=param["Méret"])
        approve(db, 58, 5801, "Teljesítmény (W)", unas_parameter=param["Méret"])
        # (3) target already a worktable column: no extra parameter column.
        approve(db, 385, 6507, "Szín", unas_field=field["Rövid Leírás"])
        db.commit()
        size_header = db.get(UnasParameterDefinition, param["Méret"]).header
        width_header = db.get(UnasParameterDefinition, param["Szélesség"]).header
    run = source(templates, "SKU;NAME;Teljesítmény (W)\n001;Mosó;2000\n002;Porszívó;1800\n"
                 .encode())
    item = generate(templates, run,
                    {"category": {"node_id": WASHER}, "rows": {"3": {"node_id": VACUUM}}})
    columns = item["manifest"]["columns"]
    headers = [c["header"] for c in columns]
    assert len(headers) == len(set(headers))
    unas = {c["header"]: c for c in columns if c["kind"] == "unas"}
    assert unas["Bruttó Ár"]["in_registry"] and unas["Bruttó Ár"]["registry_requirement"] == \
        "required"
    assert unas["SEO Title"]["in_registry"] and unas["SEO Title"]["registry_requirement"] == \
        "optional"
    # TEMPLATE-01's own work field that the UNAS export does not contain is made visible.
    assert unas["Alternatív Kategória 1."]["in_registry"] is False
    assert width_header in headers and "Szélesség (cm) [eMAG 385/6511]" not in headers
    shared = next(c for c in columns if c["header"] == size_header)
    assert sorted(shared["donors"]) == [58, 385]
    assert {p["key"] for p in shared["emag_parameters"]} == {"emag:385:6506", "emag:58:5801"}
    assert not any("[eMAG 58/5801]" in h or "[eMAG 385/6506]" in h for h in headers)
    assert not any(h.startswith("Szín [eMAG") for h in headers)
    assert unas["Rövid Leírás"]["emag_parameters"][0]["key"] == "emag:385:6507"
    # Unmapped parameters keep TEMPLATE-01's own header and identity.
    assert "Kapacitás (kg) [eMAG 385/6508]" in headers
    # Values: the shared column takes the source value for both donors' rows.
    data = list(csv.reader(io.StringIO(download(client, run, item).decode("utf-8-sig")),
                           delimiter=";"))
    index = data[0].index(size_header)
    assert (data[1][index], data[2][index]) == ("2000", "1800")
    assert len(data[0]) == len(set(data[0]))
    sheet = load_workbook(io.BytesIO(download(client, run, item, "xlsx"))).active
    assert [c.value for c in sheet[1]] == data[0]


def test_empty_registry_keeps_template_01_behaviour(templates):
    """Without a registered schema the worktable is exactly TEMPLATE-01's."""
    item = generate(templates, source(templates))
    unas = [c for c in item["manifest"]["columns"] if c["kind"] == "unas"]
    assert unas and all(c["in_registry"] is False for c in unas)
    assert not any("emag_parameters" in c for c in item["manifest"]["columns"])
