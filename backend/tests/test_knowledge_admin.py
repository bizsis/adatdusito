"""Admin imports: real APIs/DB, existing upsert engine and strict sharing boundaries."""

import io
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from openpyxl import Workbook
from app import knowledge_uploads as jobs
from app.unas_models import (
    ReferenceProduct,
    ReferenceProductAttribute,
    ReferenceProductIdentifier,
    ReferenceProductSource,
    ReferenceImportRun,
)
from app.models import Audit
from app.reference_products import lookup
from conftest import login

BASE = "/api/v1/knowledge-admin"
DATA = "SKU;NAME;EAN;Gyártó;Nettó Ár;Email;Teljesítmény\n0001;Mosógép;5201137061819;Minta;123;secret@example.invalid;800 W\n0002;Másik;5904517345546;Minta;234;other@example.invalid;900 W\n"


@pytest.fixture
def admin(environment, monkeypatch):
    client, target, _, statements = environment
    sent = []
    monkeypatch.setattr(jobs, "enqueue", sent.append)
    login(client)
    return client, target, sent, statements


def upload(admin, data=None, **extra):
    c, target, sent, _ = admin
    r = c.post(
        BASE + "/uploads",
        data={
            "source_name": "Mintaforrás",
            "scope": "system",
            "reuse_authorized": "true",
            **extra,
        },
        files={"file": ("sample.csv", data if data is not None else DATA.encode())},
    )
    assert r.status_code == 200, r.text
    id = r.json()["id"]
    assert id in sent
    with Session(target) as db:
        jobs.process(db, id)
    result = c.get(BASE + f"/imports/{id}")
    assert result.json()["state"] == "preview", result.text
    return result.json()


def start(admin, run, mapping=None):
    c, target, _, _ = admin
    r = c.post(
        BASE + f"/imports/{run['id']}/start",
        json={"mapping": mapping if mapping is not None else run["mapping"]},
    )
    assert r.status_code == 200, r.text
    with Session(target) as db:
        jobs.process(db, run["id"])
    result = c.get(BASE + f"/imports/{run['id']}").json()
    assert result["state"] in ("completed", "partial"), result
    return result


def test_csv_recognition_privacy_preview_stats_and_lookup(admin):
    c, target, _, statements = admin
    run = upload(admin)
    assert run["mapping"] == {"0": "sku", "1": "name", "2": "gtin", "3": "brand"}
    assert run["preview"][0]["line"] == 2
    assert run["preview"][0]["values"][4:] == ["[Kizárva]"] * 3
    mapping = {**run["mapping"], "6": "parameter"}
    preview = c.post(BASE + f"/imports/{run['id']}/preview", json={"mapping": mapping})
    assert (
        preview.status_code == 200
        and preview.json()["preview"][0]["values"][6] == "800 W"
    )
    assert c.get(BASE + f"/imports/{run['id']}").json()["mapping"] == run["mapping"]
    done = start(admin, run, mapping)
    assert done["counters"]["created"] == 2
    source = c.get(BASE + f"/sources/{run['source_id']}").json()
    assert source["products"] == 2 and source["parameters"] == 2
    assert source["quality"]["valid_gtin_products"] == 2
    assert source["contribution"] == "automatic"
    with Session(target) as db:
        p = db.scalar(
            select(ReferenceProduct).where(ReferenceProduct.source_sku == "0001")
        )
        assert p.name == "Mosógép" and "Nettó Ár" not in p.raw and "Email" not in p.raw
        found = lookup(db, gtin="5201137061819")
        assert found and not found[0]["overwrites_supplier_data"]
        assert "secret@" not in str(found)
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER"))
        for s in statements
    )
    assert c.get(BASE + f"/sources/{run['source_id']}/imports").json()["total"] == 1
    assert c.get(BASE + f"/sources/{run['source_id']}/audit").json()["total"] == 2


def test_repeat_is_duplicate_free_and_verified_product_not_overwritten(admin):
    c, target, _, _ = admin
    run = upload(admin)
    start(admin, run)
    repeated = c.post(BASE + f"/imports/{run['id']}/repeat").json()
    with Session(target) as db:
        jobs.process(db, repeated["id"])
        assert db.scalar(select(func.count()).select_from(ReferenceProduct)) == 2
        assert db.get(ReferenceImportRun, repeated["id"]).counters["unchanged"] == 2
        p = db.scalar(
            select(ReferenceProduct).where(ReferenceProduct.source_sku == "0001")
        )
        p.verification = "verified"
        db.commit()
    second = upload(
        admin,
        DATA.replace("Mosógép", "Nem szabad felülírni").encode(),
        source_id=str(run["source_id"]),
    )
    result = start(admin, second)
    assert result["counters"]["protected"] == 1
    with Session(target) as db:
        assert (
            db.scalar(
                select(ReferenceProduct).where(ReferenceProduct.source_sku == "0001")
            ).name
            == "Mosógép"
        )


def test_source_restriction_audit_and_reimport_preserve_decision(admin):
    c, target, _, _ = admin
    run = upload(admin)
    start(admin, run)
    response = c.put(
        BASE + f"/sources/{run['source_id']}",
        json={
            "name": "Korlátozott forrás",
            "usage_status": "revoked",
            "usage_note": "Jogosultság visszavonva",
            "enrichment_enabled": False,
        },
    )
    assert response.status_code == 200
    second = upload(admin, source_id=str(run["source_id"]))
    start(admin, second)
    with Session(target) as db:
        assert not lookup(db, gtin="5201137061819")
        source = db.get(ReferenceProductSource, run["source_id"])
        assert (
            source.usage_status == "revoked"
            and source.usage_basis == "administrator_decision"
        )
        assert db.scalar(select(Audit).where(Audit.action == "knowledge.source.update"))


def test_tenant_source_is_prepared_but_never_used_as_shared_knowledge(admin):
    c, target, _, _ = admin
    run = upload(admin, scope="tenant", tenant_id="1", reuse_authorized="false")
    start(admin, run)
    source = c.get(BASE + f"/sources/{run['source_id']}").json()
    assert source["tenant_id"] == 1 and source["contribution"] == "pending"
    with Session(target) as db:
        # Even an older usage-management API must not open a tenant source globally.
        item = db.get(ReferenceProductSource, run["source_id"])
        item.enrichment_enabled = True
        item.usage_status = "approved_enrichment"
        db.commit()
        assert lookup(db, gtin="5201137061819") == []


def test_blocked_columns_cannot_be_relabeled_as_parameters(admin):
    c, _, _, _ = admin
    run = upload(admin)
    for column in ("4", "5"):
        response = c.post(
            BASE + f"/imports/{run['id']}/start",
            json={"mapping": {**run["mapping"], column: "parameter"}},
        )
        assert response.status_code == 422
    assert c.get(BASE + f"/imports/{run['id']}").json()["state"] == "preview"


def test_system_authorization_csrf_origin_and_workspace(admin):
    c, _, _, _ = admin
    run = upload(admin)
    for user in (
        "admin@example.hu",
        "processor@example.hu",
        "reviewer@example.hu",
        "other@example.hu",
    ):
        login(c, user)
        assert c.get(BASE + "/sources").status_code == 403
        assert (
            c.post(
                BASE + f"/imports/{run['id']}/start", json={"mapping": run["mapping"]}
            ).status_code
            == 403
        )
    login(c)
    saved = c.headers.pop("X-CSRF-Token")
    assert c.post(BASE + f"/imports/{run['id']}/cancel").status_code == 403
    c.headers["X-CSRF-Token"] = saved
    assert (
        c.post(
            BASE + f"/imports/{run['id']}/cancel",
            headers={"Origin": "https://bad.invalid"},
        ).status_code
        == 403
    )
    assert c.get(BASE + "/sources/999999").status_code == 404


def test_xlsx_zero_padded_ids_and_formula_exclusion(admin):
    c, target, sent, _ = admin
    w = Workbook()
    s = w.active
    s.append(["Cikkszám", "Termék Név", "EAN", "Gyártó"])
    s.append([12, "Teszt", "5201137061819", "=1+1"])
    s.cell(2, 1).number_format = "00000"
    b = io.BytesIO()
    w.save(b)
    result = c.post(
        BASE + "/uploads",
        data={"source_name": "XLSX", "scope": "system", "reuse_authorized": "true"},
        files={"file": ("sample.xlsx", b.getvalue())},
    )
    id = result.json()["id"]
    with Session(target) as db:
        jobs.process(db, id)
    run = c.get(BASE + f"/imports/{id}").json()
    start(admin, run)
    with Session(target) as db:
        p = db.scalar(select(ReferenceProduct))
        assert p.source_sku == "00012" and not p.brand
        assert any(
            e["code"] == "excluded_cell" for e in db.get(ReferenceImportRun, id).errors
        )


def test_gtin_only_source_uses_stable_internal_key(admin):
    run = upload(admin, b"EAN;NAME\n5201137061819;A\n5904517345546;B\n")
    done = start(admin, run)
    assert done["counters"]["created"] == 2
    with Session(admin[1]) as db:
        assert db.scalar(
            select(ReferenceProduct).where(
                ReferenceProduct.source_sku == "gtin:5201137061819"
            )
        )


def test_worker_idempotence_cancel_resume_and_error_rows(admin, monkeypatch):
    c, target, sent, _ = admin
    run = upload(admin, b"SKU;NAME\n001;A\n;No ID\n002;B\n")
    result = start(admin, run)
    assert result["state"] == "partial" and result["errors"][0] == {
        "line": 3,
        "code": "missing_sku",
    }
    with Session(target) as db:
        jobs.process(db, run["id"])
        assert db.scalar(select(func.count()).select_from(ReferenceProduct)) == 2
    second = upload(admin)
    assert c.post(BASE + f"/imports/{second['id']}/cancel").status_code == 200
    assert c.post(BASE + f"/imports/{second['id']}/retry").status_code == 200
    with Session(target) as db:
        jobs.process(db, second["id"])
    assert c.get(BASE + f"/imports/{second['id']}").json()["state"] == "preview"


def test_actual_checkpoint_resume_does_not_duplicate_processed_rows(admin, monkeypatch):
    c, target, _, _ = admin
    run = upload(
        admin,
        ("SKU;NAME\n" + "".join(f"{i:04};Product {i}\n" for i in range(12))).encode(),
    )
    original = jobs.heartbeat
    calls = []

    def interrupt(db, row, token, state):
        if state == "running":
            calls.append(state)
            if len(calls) == 3:
                row.state = "cancelled"
                row.ui_task_token = None
                db.commit()
                return False
        return original(db, row, token, state)

    monkeypatch.setattr(jobs, "heartbeat", interrupt)
    import app.reference_products as importer

    monkeypatch.setattr(importer, "BATCH", 3)
    response = c.post(
        BASE + f"/imports/{run['id']}/start", json={"mapping": run["mapping"]}
    )
    assert response.status_code == 200
    with Session(target) as db:
        jobs.process(db, run["id"])
    paused = c.get(BASE + f"/imports/{run['id']}").json()
    assert paused["state"] == "cancelled" and paused["cursor"] > 1
    monkeypatch.setattr(jobs, "heartbeat", original)
    assert c.post(BASE + f"/imports/{run['id']}/retry").status_code == 200
    with Session(target) as db:
        jobs.process(db, run["id"])
        assert db.scalar(select(func.count()).select_from(ReferenceProduct)) == 12
        assert db.get(ReferenceImportRun, run["id"]).counters["created"] == 12


def test_unlicensed_system_upload_and_invalid_files_are_rejected(admin):
    c, _, _, _ = admin
    for filename, content, extra in [
        ("x.csv", b"a", {}),
        ("x.exe", b"a", {"reuse_authorized": "true"}),
        ("x.csv", b"", {"reuse_authorized": "true"}),
    ]:
        response = c.post(
            BASE + "/uploads",
            data={"source_name": "X", **extra},
            files={"file": (filename, content)},
        )
        assert response.status_code == 422


def test_reference_upload_does_not_replace_native_unas_template_schema(admin, tmp_path):
    from app.unas_registry import TemplateContext
    from app.reference_products import import_export
    from test_unas_reference import export, product

    with Session(admin[1]) as db:
        import_export(
            db, export(tmp_path, [product("legacy", "Native", "5201137061819")])
        )
        expected = TemplateContext(db).schema_source
        assert expected.startswith("unas_export/")
    run = upload(admin)
    start(admin, run)
    with Session(admin[1]) as db:
        assert TemplateContext(db).schema_source == expected
        assert db.get(
            ReferenceProductSource, run["source_id"]
        ).schema_source.startswith("reference_upload/")


def test_api_upload_and_start_are_queued_and_same_source_writes_are_serialized(admin):
    c, target, _, _ = admin
    r = c.post(
        BASE + "/uploads",
        data={"source_name": "Queue test", "reuse_authorized": "true"},
        files={"file": ("source.csv", DATA.encode())},
    )
    assert r.status_code == 200 and r.json()["state"] == "queued"
    with Session(target) as db:
        assert db.scalar(select(func.count()).select_from(ReferenceProduct)) == 0
        jobs.process(db, r.json()["id"])
    run = c.get(BASE + f"/imports/{r.json()['id']}").json()
    second = upload(admin, source_id=str(run["source_id"]))
    assert (
        c.post(
            BASE + f"/imports/{run['id']}/start", json={"mapping": run["mapping"]}
        ).json()["state"]
        == "queued_import"
    )
    assert (
        c.post(
            BASE + f"/imports/{second['id']}/start", json={"mapping": second["mapping"]}
        ).status_code
        == 409
    )
    with Session(target) as db:
        assert db.scalar(select(func.count()).select_from(ReferenceProduct)) == 0


def test_root_must_switch_out_of_customer_workspace(admin):
    c, _, _, _ = admin
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": 1}).status_code == 200
    assert c.get(BASE + "/sources").status_code == 409
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": None}).status_code == 200
    assert c.get(BASE + "/sources").status_code == 200


def test_bad_gtin_not_stored_as_product_identifier(admin):
    run = upload(admin, b"SKU;NAME;EAN\n001;A;private@example.invalid\n")
    done = start(admin, run)
    assert any(e["code"] == "invalid_gtin" for e in done["errors"])
    with Session(admin[1]) as db:
        assert not db.scalar(
            select(ReferenceProductIdentifier).where(
                ReferenceProductIdentifier.kind == "gtin"
            )
        )


def test_csv_description_longer_than_xlsx_cell_is_preserved(admin):
    text = "Részletes termékleírás " * 2500
    run = upload(admin, ("SKU;NAME;Tulajdonságok\n001;A;" + text + "\n").encode())
    start(admin, run)
    with Session(admin[1]) as db:
        product = db.scalar(select(ReferenceProduct))
        assert product.long_description == text.strip()
        assert len(product.long_description) > 32767


def test_knowledge01_tenant_source_policy_and_background_notification(
    admin, monkeypatch
):
    c, target, _, _ = admin
    from app import knowledge_bridge

    scheduled = []
    monkeypatch.setattr(knowledge_bridge, "schedule_source", scheduled.append)
    with Session(target) as db:
        source = ReferenceProductSource(
            key="tenant:1",
            name="Automatikus ügyfélforrás",
            kind="tenant_import",
            tenant_id=1,
            usage_status="approved_enrichment",
            enrichment_enabled=True,
            contribution="automatic",
            usage_basis="owner_policy:2026-11-17",
            excluded_columns=[],
        )
        db.add(source)
        db.commit()
        id = source.id
    response = c.get(BASE + f"/sources/{id}").json()
    assert response["contribution"] == "automatic"
    updated = c.put(
        BASE + f"/sources/{id}",
        json={
            "name": source.name,
            "usage_status": "approved_enrichment",
            "enrichment_enabled": True,
            "usage_note": "KNOWLEDGE-01 szerződés szerint",
        },
    )
    assert updated.status_code == 200 and scheduled == [id]
    rejected = c.post(
        BASE + "/uploads",
        data={
            "source_name": "X",
            "scope": "tenant",
            "tenant_id": "1",
            "source_id": str(id),
        },
        files={"file": ("source.csv", DATA.encode())},
    )
    assert rejected.status_code == 422


def test_bridge_uses_published_scheduler_only(monkeypatch):
    import sys
    from types import SimpleNamespace
    from app import knowledge_bridge

    called = []
    monkeypatch.setattr(knowledge_bridge, "available", lambda: False)
    assert knowledge_bridge.schedule_source(11) is False
    monkeypatch.setattr(knowledge_bridge, "available", lambda: True)
    monkeypatch.setitem(
        sys.modules,
        "app.knowledge",
        SimpleNamespace(schedule=lambda **kwargs: called.append(kwargs)),
    )
    assert knowledge_bridge.schedule_source(11) is True
    assert called == [{"source_id": 11}]


def test_integrated_import_schedules_once_and_rebuild_uses_shared_source(
    admin, monkeypatch
):
    from app import knowledge as kb
    from app.knowledge_models import KnowledgeLink, KnowledgeObservation

    c, target, _, _ = admin
    published = []
    monkeypatch.setattr(kb, "schedule", lambda **kwargs: published.append(kwargs))
    run = upload(admin)
    start(admin, run)
    assert published == [{"source_id": run["source_id"]}]
    assert c.get("/api/v1/knowledge/stats").status_code == 200
    with Session(target) as db:
        kb.rebuild(db, source_id=run["source_id"])
        assert db.scalar(select(func.count()).select_from(KnowledgeLink)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeObservation)
                .where(KnowledgeObservation.current.is_(True))
            )
            >= 2
        )
    response = c.put(
        BASE + f"/sources/{run['source_id']}",
        json={
            "name": "Kizárt",
            "usage_status": "revoked",
            "enrichment_enabled": False,
            "usage_note": "Felhasználási jog visszavonva",
        },
    )
    assert response.status_code == 200
    assert published == [{"source_id": run["source_id"]}] * 2
    with Session(target) as db:
        kb.rebuild(db, source_id=run["source_id"])
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeObservation)
                .where(KnowledgeObservation.current.is_(True))
            )
            == 0
        )
