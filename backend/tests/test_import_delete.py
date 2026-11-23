"""IMPORT-DELETE-01: deleting a supplier, an uploaded file, a saved template and a
template version. Only the selected item goes; related data blocks with a clear
409; no cascade from a supplier; the active template version stays; the eMAG
reference database is never touched."""

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import import_api
from app.import_models import ImportChunk, ImportProfile, ImportRun, Supplier
from app.models import Audit
from app.template_models import ImportTemplate, TemplateChunk
from conftest import login
from test_supplier_import import approve, upload, work
from test_template_prep import full_body, prepared, save

BASE = "/api/v1/imports"


@pytest.fixture
def ctx(environment, monkeypatch):
    client, target, _, statements = environment
    monkeypatch.setattr(import_api, "enqueue", lambda id: None)
    login(client, "admin@example.hu")
    supplier = client.post(f"{BASE}/suppliers", json={"name": "Teszt beszállító"}).json()["id"]
    return client, target, supplier, statements


def supplier_names(c):
    r = c.get(f"{BASE}/suppliers")
    assert r.status_code == 200
    return {x["name"] for x in r.json()}


def two_versions(c, t, s):
    run1, view1 = prepared(c, t, s)
    first = save(c, run1, full_body(view1), name="Alap").json()
    run2, view2 = prepared(c, t, s)
    second = save(c, run2, full_body(view2), name="Alap", template_id=first["id"]).json()
    assert (first["version"], second["version"]) == (1, 2)
    return run1, run2, first, second


# --- supplier --------------------------------------------------------------------


def test_empty_supplier_is_deleted_alone_and_list_is_fresh(ctx):
    c, t, s, statements = ctx
    other = c.post(f"{BASE}/suppliers", json={"name": "Marad"}).json()["id"]
    before = len(statements)
    plan = c.get(f"{BASE}/suppliers/{s}/deletion").json()
    assert plan["deletable"] is True and not any(plan["references"].values())
    r = c.delete(f"{BASE}/suppliers/{s}")
    assert r.status_code == 200 and r.json() == {"deleted": True, "supplier_id": s}
    assert supplier_names(c) == {"Marad"}  # only the selected one, list is current
    assert c.delete(f"{BASE}/suppliers/{s}").status_code == 404
    with Session(t) as db:
        assert db.get(Supplier, other) is not None
        assert db.scalar(select(Audit).where(Audit.action == "import.supplier_delete")) is not None
    assert len(statements) == before  # eMAG reference DB untouched


def test_supplier_with_related_data_is_never_cascaded(ctx):
    c, t, s, _ = ctx
    run = upload(c, s, b"SKU;NAME;STOCK\n1;TV;5\n")
    work(t, run)
    r = c.delete(f"{BASE}/suppliers/{s}")
    assert r.status_code == 409
    message = r.json()["error"]["message"]
    assert "1 import" in message and "kaszkád" in message
    with Session(t) as db:
        assert db.get(Supplier, s) is not None and db.get(ImportRun, run) is not None
    # Products from a processed import keep the supplier forever (no cascade).
    approve(c, run)
    work(t, run)
    plan = c.get(f"{BASE}/suppliers/{s}/deletion").json()
    assert plan["deletable"] is False and plan["references"]["supplier_products"] == 1
    assert c.delete(f"{BASE}/suppliers/{s}").status_code == 409
    assert "Teszt beszállító" in supplier_names(c)


def test_supplier_with_only_a_template_is_blocked_until_the_template_goes(ctx):
    c, t, s, _ = ctx
    run, view = prepared(c, t, s)
    tpl = save(c, run, full_body(view)).json()
    r = c.delete(f"{BASE}/suppliers/{s}")
    assert r.status_code == 409 and "mentett sablon" in r.json()["error"]["message"]
    assert c.delete(f"{BASE}/import-templates/{tpl['id']}").status_code == 200
    assert c.delete(f"{BASE}/runs/{run}").status_code == 200
    assert c.delete(f"{BASE}/suppliers/{s}").status_code == 200
    assert "Teszt beszállító" not in supplier_names(c)


def test_supplier_delete_is_transactional(ctx, monkeypatch):
    c, t, s, _ = ctx

    def broken(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(import_api, "audit", broken)
    with pytest.raises(RuntimeError):
        c.delete(f"{BASE}/suppliers/{s}")
    with Session(t) as db:
        assert db.get(Supplier, s) is not None  # nothing half-deleted


def test_supplier_delete_permissions_tenant_and_csrf(ctx):
    c, t, s, _ = ctx
    login(c, "other@example.hu")
    assert c.get(f"{BASE}/suppliers/{s}/deletion").status_code == 404
    assert c.delete(f"{BASE}/suppliers/{s}").status_code == 404
    login(c, "reviewer@example.hu")
    assert c.delete(f"{BASE}/suppliers/{s}").status_code == 403
    login(c, "admin@example.hu")
    token = c.headers.pop("X-CSRF-Token")
    assert c.delete(f"{BASE}/suppliers/{s}").status_code == 403
    c.headers["X-CSRF-Token"] = token
    assert c.delete(f"{BASE}/suppliers/{s}", headers={"Origin": "https://evil.example"}).status_code == 403
    with Session(t) as db:
        assert db.get(Supplier, s) is not None


# --- uploaded file ------------------------------------------------------------------


def test_file_that_is_a_template_source_is_blocked_then_fully_removed(ctx):
    c, t, s, statements = ctx
    run, view = prepared(c, t, s)
    other_run, _ = prepared(c, t, s)
    tpl = save(c, run, full_body(view)).json()
    plan = c.get(f"{BASE}/runs/{run}/deletion").json()
    assert plan["deletable"] is False and plan["reason"] == "template_source"
    assert plan["template_source_ids"] == [tpl["id"]]
    r = c.delete(f"{BASE}/runs/{run}")
    assert r.status_code == 409 and "sablon" in r.json()["error"]["message"]
    assert c.delete(f"{BASE}/import-templates/{tpl['id']}").status_code == 200
    # A generated work template of this file is a stored artefact of the file too.
    with Session(t) as db:
        item = ImportTemplate(run_id=run, state="completed", options={}, manifest={})
        db.add(item)
        db.flush()
        db.add(TemplateChunk(template_id=item.id, format="xlsx", ordinal=0, data=b"x"))
        db.commit()
        generated = item.id
    before = len(statements)
    plan = c.get(f"{BASE}/runs/{run}/deletion").json()
    assert plan["deletable"] is True and plan["deletes"]["generated_templates"] == 1
    assert c.delete(f"{BASE}/runs/{run}").status_code == 200
    assert run not in {x["id"] for x in c.get(f"{BASE}/runs").json()}
    with Session(t) as db:
        assert db.get(ImportRun, run) is None
        assert db.scalar(select(func.count()).select_from(ImportChunk).where(ImportChunk.run_id == run)) == 0
        assert db.get(ImportTemplate, generated) is None
        assert db.scalar(select(TemplateChunk).where(TemplateChunk.template_id == generated)) is None
        assert db.get(ImportRun, other_run) is not None  # only the selected file
        assert db.scalar(select(func.count()).select_from(ImportChunk)
                         .where(ImportChunk.run_id == other_run)) > 0
    assert len(statements) == before


# --- saved template and versions -------------------------------------------------------


def test_active_version_is_protected_and_older_version_is_deleted_alone(ctx):
    c, t, s, _ = ctx
    run1, run2, first, second = two_versions(c, t, s)
    other_run, other_view = prepared(c, t, s)
    unrelated = save(c, other_run, full_body(other_view), name="Másik").json()
    url = f"{BASE}/import-templates/{second['id']}/versions"
    r = c.delete(f"{url}/{second['id']}")
    assert r.status_code == 409 and "aktív" in r.json()["error"]["message"]
    plan = c.get(f"{url}/{first['id']}/deletion").json()
    assert plan["deletable"] is True and plan["active_version_id"] == second["id"]
    r = c.delete(f"{url}/{first['id']}")
    assert r.status_code == 200 and r.json()["active_version_id"] == second["id"]
    assert [v["version"] for v in c.get(url).json()] == [2]  # list is current
    listed = {x["name"]: x for x in c.get(f"{BASE}/suppliers/{s}/import-templates").json()["templates"]}
    assert listed["Alap"]["id"] == second["id"] and listed["Alap"]["versions"] == 1
    assert listed["Másik"]["id"] == unrelated["id"]
    # The active template still works: preparation recognises it, results render.
    run3, view3 = prepared(c, t, s)
    assert view3["template"]["id"] in {second["id"], unrelated["id"]}  # same structure, newest wins
    assert c.get(f"{BASE}/import-templates/{second['id']}/result").status_code == 200
    # The single remaining version cannot be removed as a "version".
    r = c.delete(f"{url}/{second['id']}")
    assert r.status_code == 409 and "egyetlen" in r.json()["error"]["message"]


def test_template_delete_removes_all_versions_and_nothing_else(ctx):
    c, t, s, statements = ctx
    run1, run2, first, second = two_versions(c, t, s)
    other_run, other_view = prepared(c, t, s)
    unrelated = save(c, other_run, full_body(other_view), name="Másik").json()
    before = len(statements)
    plan = c.get(f"{BASE}/import-templates/{first['id']}/deletion").json()
    assert plan["deletable"] is True and sorted(plan["deletes"]["version_ids"]) == sorted(
        [first["id"], second["id"]])
    r = c.delete(f"{BASE}/import-templates/{first['id']}")
    assert r.status_code == 200
    names = {x["name"] for x in c.get(f"{BASE}/suppliers/{s}/import-templates").json()["templates"]}
    assert names == {"Másik"}
    assert c.get(f"{BASE}/import-templates/{second['id']}").status_code == 404
    with Session(t) as db:
        assert db.get(ImportProfile, unrelated["id"]) is not None
        assert db.get(ImportRun, run1) is not None and db.get(ImportRun, run2) is not None
        assert db.get(Supplier, s) is not None
    assert len(statements) == before


def test_referenced_template_or_version_is_blocked(ctx):
    c, t, s, _ = ctx
    run1, run2, first, second = two_versions(c, t, s)
    with Session(t) as db:  # an approved import used version 1
        db.execute(update(ImportRun).where(ImportRun.id == run1)
                   .values(profile_id=first["id"], approved_by=2))
        db.commit()
    for url in (f"{BASE}/import-templates/{second['id']}",
                f"{BASE}/import-templates/{second['id']}/versions/{first['id']}"):
        r = c.delete(url)
        assert r.status_code == 409 and "import hivatkozza" in r.json()["error"]["message"]
    plan = c.get(f"{BASE}/import-templates/{second['id']}/deletion").json()
    assert plan["references"]["import_run_ids"] == [run1]
    with Session(t) as db:
        assert db.get(ImportProfile, first["id"]) is not None
        assert db.get(ImportProfile, second["id"]) is not None
        assert db.get(ImportRun, run1).profile_id == first["id"]


def test_unapproved_upload_matches_are_detached_not_blocking(ctx):
    c, t, s, _ = ctx
    run1, run2, first, second = two_versions(c, t, s)
    with Session(t) as db:  # the upload of version 2 matched version 1 by structure
        assert db.get(ImportRun, run2).profile_id == first["id"]
    plan = c.get(f"{BASE}/import-templates/{second['id']}/versions/{first['id']}/deletion").json()
    assert plan["deletable"] is True and plan["detaches"]["run_ids"] == [run2]
    assert c.delete(f"{BASE}/import-templates/{second['id']}/versions/{first['id']}").status_code == 200
    with Session(t) as db:
        run = db.get(ImportRun, run2)
        assert run.profile_id is None and run.analysis["matched_profile_id"] is None
        assert run.analysis["headers"]  # nothing else of the upload changed


def test_template_delete_permissions_tenant_and_foreign_version(ctx):
    c, t, s, _ = ctx
    run1, run2, first, second = two_versions(c, t, s)
    other_run, other_view = prepared(c, t, s)
    unrelated = save(c, other_run, full_body(other_view), name="Másik").json()
    # A version id of another template is not a version of this one.
    assert c.delete(f"{BASE}/import-templates/{second['id']}/versions/{unrelated['id']}").status_code == 404
    login(c, "reviewer@example.hu")
    assert c.delete(f"{BASE}/import-templates/{second['id']}").status_code == 403
    assert c.delete(f"{BASE}/import-templates/{second['id']}/versions/{first['id']}").status_code == 403
    login(c, "other@example.hu")
    assert c.delete(f"{BASE}/import-templates/{second['id']}").status_code == 404
    assert c.get(f"{BASE}/import-templates/{second['id']}/deletion").status_code == 404
    login(c, "admin@example.hu")
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(ImportProfile)) == 3
