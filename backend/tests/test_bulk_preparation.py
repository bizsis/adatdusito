"""CATEGORY-03C: selections, bulk preview/apply and preparation approvals."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import bulk_operations as bo
from app import product_parameters as pp
from app.import_models import SupplierProduct
from app.main import app
from app.models import Membership
from app.product_models import ProductJob, ProductParameterValue
from conftest import login
from test_product_classification import csv, detail, patch, products, run
from test_product_parameters import EBOOK, MAPPING, WASHER, WASHER_DRYER, install_catalog
from test_supplier_import import imports  # noqa: F401

HEAD = "SKU;NAME;CATEGORY;Teljesítmény (kW);Szín;Kapacitás (kg)\n"


@pytest.fixture
def bulk(imports, monkeypatch):
    c, t, s = imports
    install_catalog(t)
    sent = []
    monkeypatch.setattr(bo, "enqueue", sent.append)
    from app import product_jobs

    monkeypatch.setattr(product_jobs, "enqueue_parameters", lambda job_id: None)
    return c, t, s, sent


def seed(c, t, s, layout):
    """layout: list of navigation node ids (None = unclassified); returns product ids."""
    rows = [[f"{i:03d}", f"Termék {i}", "Gépek", "2,1", "fehér", "8"] for i in range(len(layout))]
    run(c, t, s, csv(*rows, head=HEAD), mapping=MAPPING)
    ids = [p["id"] for p in products(c, limit=100)["items"]]
    for pid, node in zip(ids, layout):
        if node:
            r = patch(c, pid, expected_revision=detail(c, pid)["revision"], action="set", navigation_node_id=node)
            assert r.status_code == 200, r.text
    return ids


def select_all(c, **body):
    r = c.post("/api/v1/workspace/product-selections", json=body or {"filters": {}})
    assert r.status_code == 200, r.text
    return r.json()


def finish(t, job_id, **kw):
    with Session(t) as db:
        return bo.advance(db, job_id, **kw)


def job(c, job_id):
    r = c.get(f"/api/v1/workspace/product-jobs/{job_id}")
    assert r.status_code == 200, r.text
    return r.json()


def preview(c, t, selection):
    r = c.post("/api/v1/workspace/parameter-bulk-previews", json={"selection_token": selection["selection_token"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert finish(t, body["preview"]["id"]) == "completed"
    return body["preview"]["id"], body["preview_token"]


def apply_body(token, eligible, key="key-0001", **extra):
    return {"preview_token": token, "confirm": True, "expected_eligible": eligible, "idempotency_key": key, **extra}


def revision(c, pid):
    return detail(c, pid)["revision"]


# --- selections ------------------------------------------------------------------


def test_selection_snapshot_is_server_side_tenant_bound_and_validated(bulk, monkeypatch):
    c, t, s, _ = bulk
    ids = seed(c, t, s, [WASHER, WASHER, None])
    sel = select_all(c, filters={}, exclude_product_ids=[ids[2]])
    assert sel["total"] == 2 and sel["excluded"] == 1 and len(sel["selection_token"]) >= 40
    meta = c.get(f"/api/v1/workspace/product-selections/{sel['id']}").json()
    assert "selection_token" not in meta and meta["total"] == 2 and not meta["expired"]
    page = select_all(c, product_ids=ids[:1])
    assert page["total"] == 1 and page["mode"] == "product_ids"
    assert c.post("/api/v1/workspace/product-selections",
                  json={"filters": {}, "product_ids": ids[:1]}).status_code == 422
    assert c.post("/api/v1/workspace/product-selections",
                  json={"filters": {"state": "conflict"}}).status_code == 422  # empty
    monkeypatch.setattr(bo, "SELECTION_MAX", 2)
    assert c.post("/api/v1/workspace/product-selections", json={"filters": {}}).status_code == 422
    other = TestClient(app, base_url="https://testserver")
    login(other, "other@example.hu")
    assert other.get(f"/api/v1/workspace/product-selections/{sel['id']}").status_code == 404
    assert other.post("/api/v1/workspace/product-selections", json={"product_ids": ids[:1]}).status_code == 404
    assert other.post("/api/v1/workspace/parameter-bulk-previews",
                      json={"selection_token": sel["selection_token"]}).status_code == 409
    # CSRF stays enforced on the new write endpoints.
    assert c.post("/api/v1/workspace/product-selections", json={"filters": {}},
                  headers={"X-CSRF-Token": ""}).status_code == 403


def test_expired_selection_token_is_rejected(bulk):
    c, t, s, _ = bulk
    seed(c, t, s, [WASHER])
    sel = select_all(c)
    with Session(t) as db:
        from app.product_models import ProductSelection

        db.execute(update(ProductSelection).values(expires_at=ProductSelection.created_at))
        db.commit()
    r = c.post("/api/v1/workspace/parameter-bulk-previews", json={"selection_token": sel["selection_token"]})
    assert r.status_code == 409


# --- preview -----------------------------------------------------------------------


def test_preview_counts_every_case_and_writes_nothing(bulk):
    c, t, s, _ = bulk
    ids = seed(c, t, s, [WASHER, WASHER, WASHER, WASHER_DRYER, EBOOK, None])
    revisions = [revision(c, pid) for pid in ids]
    pid, _ = preview(c, t, select_all(c))
    state = job(c, pid)
    assert state["state"] == "completed" and (state["processed"], state["total"]) == (6, 6)
    assert state["outcomes"] == {"eligible": 3, "skipped_pending_review": 1,
                                 "skipped_choice_required": 1, "skipped_no_donor": 1}
    assert state["slots"]["create"] == 3 * 7 and state["source_overwrites"] == 0
    assert state["new_slots"] == {"present": 9, "missing": 12}
    assert [revision(c, x) for x in ids] == revisions
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(ProductParameterValue)) == 0
    items = c.get(f"/api/v1/workspace/product-jobs/{pid}/items", params={"limit": 2}).json()
    assert len(items["items"]) == 2 and items["next_cursor"] == items["items"][1]["product_id"]
    skipped = c.get(f"/api/v1/workspace/product-jobs/{pid}/items",
                    params={"outcome": "skipped_pending_review"}).json()["items"]
    assert [x["product_id"] for x in skipped] == [ids[3]]


def test_one_failing_product_does_not_stop_the_preview(bulk, monkeypatch):
    c, t, s, _ = bulk
    ids = seed(c, t, s, [WASHER, WASHER, WASHER])
    original = pp.compute

    def flaky(db, product, *args, **kwargs):
        if product.id == ids[1]:
            raise RuntimeError("boom")
        return original(db, product, *args, **kwargs)

    monkeypatch.setattr(pp, "compute", flaky)
    pid, _ = preview(c, t, select_all(c))
    assert job(c, pid)["outcomes"] == {"eligible": 2, "error": 1}


def test_runs_are_limited_and_continue_on_the_same_job(bulk, monkeypatch):
    c, t, s, sent = bulk
    seed(c, t, s, [WASHER] * 5)
    monkeypatch.setenv("IMPORT_MAX_PRODUCTS", "2")  # stands in for 50 000 per run
    r = c.post("/api/v1/workspace/parameter-bulk-previews", json={"selection_token": select_all(c)["selection_token"]})
    pid = r.json()["preview"]["id"]
    states = []
    while (state := finish(t, pid, batch=1)) != "completed":
        states.append(state)
    data = job(c, pid)
    assert states == ["pending", "pending"] and data["runs"] == 3 and data["processed"] == 5
    assert sent.count(pid) == 3  # created + two run boundaries re-enqueue themselves


# --- apply -------------------------------------------------------------------------


def test_apply_requires_confirmation_token_count_and_permissions(bulk):
    c, t, s, _ = bulk
    seed(c, t, s, [WASHER, WASHER])
    pid, token = preview(c, t, select_all(c))
    url = f"/api/v1/workspace/parameter-bulk-previews/{pid}/apply"
    assert c.post(url, json={**apply_body(token, 2), "confirm": False}).status_code == 422
    assert c.post(url, json=apply_body(token, 3, key="key-0002")).status_code == 409
    assert c.post(url, json=apply_body("x" * 43, 2, key="key-0003")).status_code == 409
    processor = TestClient(app, base_url="https://testserver")
    login(processor, "processor@example.hu")
    assert processor.post(url, json=apply_body(token, 2, key="key-0004")).status_code == 403
    first = c.post(url, json=apply_body(token, 2))
    assert first.status_code == 200, first.text
    again = c.post(url, json=apply_body(token, 2))
    assert again.json()["replayed"] is True and again.json()["apply"]["id"] == first.json()["apply"]["id"]
    assert c.post(url, json=apply_body(token, 2, reason="más")).status_code == 409  # same key, other body
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(ProductJob).where(ProductJob.kind == bo.APPLY)) == 1


def test_apply_skips_stale_and_changed_products_and_reports_partial_success(bulk):
    c, t, s, _ = bulk
    ids = seed(c, t, s, [WASHER, WASHER, WASHER])
    pid, token = preview(c, t, select_all(c))
    # Product 0 changes after the preview (new revision): stale.
    assert patch(c, ids[0], expected_revision=revision(c, ids[0]), action="set",
                 navigation_node_id=WASHER, reason="újra").status_code == 200
    # Product 1 keeps its revision but its computed change differs (new alias).
    alias = {"scope": "tenant", "label": "Kapacitás", "unit": "kg", "emag_parameter_id": 6512,
             "scope_emag_category_id": 385}
    assert c.post("/api/v1/workspace/parameter-aliases", json=alias).status_code == 200
    r = c.post(f"/api/v1/workspace/parameter-bulk-previews/{pid}/apply", json=apply_body(token, 3))
    aid = r.json()["apply"]["id"]
    assert finish(t, aid) == "completed"
    data = job(c, aid)
    assert data["outcomes"] == {"stale": 1, "changed_since_preview": 2}
    # Without the alias change only staleness would remain: retry with a fresh preview.
    assert c.delete("/api/v1/workspace/parameter-aliases/1", params={"expected_version": 1}).status_code == 200
    pid2, token2 = preview(c, t, select_all(c))
    eligible = job(c, pid2)["outcomes"]["eligible"]
    r = c.post(f"/api/v1/workspace/parameter-bulk-previews/{pid2}/apply", json=apply_body(token2, eligible,
                                                                                          key="key-0010"))
    aid2 = r.json()["apply"]["id"]
    before = revision(c, ids[2])
    assert finish(t, aid2) == "completed"
    data = job(c, aid2)
    assert data["outcomes"] == {"applied": 3} and data["source_overwrites"] == 0
    assert revision(c, ids[2]) == before + 1
    results = c.get(f"/api/v1/workspace/product-jobs/{aid2}/items").json()["items"]
    assert {x["apply_outcome"] for x in results} == {"applied"}
    # Retrying the same preview has nothing left to do (idempotent per item).
    r = c.post(f"/api/v1/workspace/parameter-bulk-previews/{pid2}/apply",
               json=apply_body(token2, eligible, key="key-0011"))
    assert r.json()["apply"]["total"] == 0
    assert finish(t, r.json()["apply"]["id"]) == "completed"


def test_locked_values_are_never_written_by_bulk_apply(bulk):
    c, t, s, _ = bulk
    ids = seed(c, t, s, [WASHER])
    assert c.post(f"/api/v1/workspace/products/{ids[0]}/parameters/apply",
                  json={"expected_revision": revision(c, ids[0])}).status_code == 200
    r = c.patch(f"/api/v1/workspace/products/{ids[0]}/parameters/emag:6506",
                json={"expected_revision": revision(c, ids[0]), "action": "set", "value": "1999", "unit": "W"})
    assert r.status_code == 200
    run(c, t, s, csv(["000", "Termék 0", "Gépek", "2,5", "fekete", "8"], head=HEAD), mapping=MAPPING)
    pid, token = preview(c, t, select_all(c))
    data = job(c, pid)
    assert data["slots"]["blocked_locked"] == 1 and data["outcomes"] == {"eligible": 1}
    aid = c.post(f"/api/v1/workspace/parameter-bulk-previews/{pid}/apply",
                 json=apply_body(token, 1)).json()["apply"]["id"]
    finish(t, aid)
    slots = {x["slot_key"]: x for x in c.get(f"/api/v1/workspace/products/{ids[0]}/parameters").json()["slots"]}
    assert slots["emag:6506"]["value"] == "1999" and slots["emag:6506"]["locked"]
    assert slots["emag:6507"]["value"] == "Fekete"  # same-source refresh only
    assert slots["emag:6506"]["sources"][0]["raw"] == "2,1"  # original source kept on the locked slot


def test_lease_resume_cancel_and_permission_revocation(bulk):
    c, t, s, sent = bulk
    seed(c, t, s, [WASHER] * 3)
    pid, token = preview(c, t, select_all(c))
    aid = c.post(f"/api/v1/workspace/parameter-bulk-previews/{pid}/apply",
                 json=apply_body(token, 3)).json()["apply"]["id"]
    assert finish(t, aid, batch=1, max_batches=1) == "pending"  # worker stopped after one batch
    with Session(t) as db:  # simulate a crashed worker holding an expired lease
        db.execute(update(ProductJob).where(ProductJob.id == aid).values(state="running", lease_until=None))
        db.commit()
    assert job(c, aid)["stalled"] is True
    assert c.post(f"/api/v1/workspace/product-jobs/{aid}/resume").status_code == 200 and sent[-1] == aid
    # The creator loses products.bulk before the next write batch: the job stops.
    with Session(t) as db:
        db.execute(update(Membership).where(Membership.user_id == 2, Membership.tenant_id == 1)
                   .values(role="processor"))
        db.commit()
    assert finish(t, aid) == "cancelled"
    data = job(c, aid)
    assert data["stopped_reason"] == "permission_revoked" and data["outcomes"] == {"applied": 1}
    with Session(t) as db:
        db.execute(update(Membership).where(Membership.user_id == 2, Membership.tenant_id == 1)
                   .values(role="tenant_admin"))
        db.commit()
    assert c.post(f"/api/v1/workspace/product-jobs/{aid}/cancel").status_code == 409  # not running
    other = c.post("/api/v1/workspace/parameter-bulk-previews",
                   json={"selection_token": select_all(c)["selection_token"]}).json()["preview"]["id"]
    assert c.post(f"/api/v1/workspace/product-jobs/{other}/cancel").json()["state"] == "cancelled"
    assert finish(t, other) == "cancelled"


# --- preparation check and approval -------------------------------------------------


def prepare(c, pid):
    r = c.post(f"/api/v1/workspace/products/{pid}/parameters/apply", json={"expected_revision": revision(c, pid)})
    assert r.status_code == 200, r.text


def check(c, t, selection):
    r = c.post("/api/v1/workspace/preparation-checks", json={"selection_token": selection["selection_token"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert finish(t, body["check"]["id"]) == "completed"
    return body["check"]["id"], body["check_token"]


def test_preparation_check_blocks_unresolved_items_but_not_missing_values(bulk):
    c, t, s, _ = bulk
    ids = seed(c, t, s, [WASHER, WASHER, WASHER_DRYER, None, EBOOK])
    prepare(c, ids[0])
    # Product 1: a meaning conflict (two different colour columns).
    run(c, t, s, csv(["001", "Termék 1", "Gépek", "2,1", "fehér", "8", "fekete"],
                     head="SKU;NAME;CATEGORY;Teljesítmény (kW);Szín;Kapacitás (kg);Szín\n"), mapping=MAPPING)
    prepare(c, ids[1])
    cid, _ = check(c, t, select_all(c))
    data = job(c, cid)
    assert data["outcomes"] == {"approvable": 1, "blocked": 4}
    assert data["blocked_reasons"] == {"meaning_conflict": 1, "donor_pending_review": 1, "unclassified": 1,
                                       "donor_choice_required": 1}
    # Missing donor values do not block: they are the research targets.
    assert (data["research_targets"], data["mandatory_research_targets"]) == (4, 1)
    items = {x["product_id"]: x for x in c.get(f"/api/v1/workspace/product-jobs/{cid}/items").json()["items"]}
    assert items[ids[0]]["outcome"] == "approvable" and items[ids[0]]["summary"]["research_targets"] == 4
    # An unapplied change (stale diff) blocks as well.
    run(c, t, s, csv(["100", "Új termék", "Gépek", "2,1", "fehér", "8"], head=HEAD), mapping=MAPPING)
    new = max(p["id"] for p in products(c, limit=100)["items"])
    assert patch(c, new, expected_revision=revision(c, new), action="set", navigation_node_id=WASHER).status_code == 200
    cid2, _ = check(c, t, select_all(c, product_ids=[new]))
    assert job(c, cid2)["blocked_reasons"] == {"not_prepared": 1, "stale_diff": 1}


def test_preparation_approval_lifecycle(bulk, monkeypatch):
    c, t, s, _ = bulk
    ids = seed(c, t, s, [WASHER, WASHER])
    for pid in ids:
        prepare(c, pid)
    diff = c.get("/api/v1/workspace/parameter-diff").json()["items"]
    assert all(x["prepared"] for x in diff)
    assert c.get(f"/api/v1/workspace/products/{ids[0]}/preparation").json()["approval"] is None  # prepared != approved
    cid, token = check(c, t, select_all(c))
    body = {"check_id": cid, "check_token": token, "confirm": True, "expected_approvable": 2,
            "idempotency_key": "approve-0001", "reason": "ellenőrzött kör"}
    processor = TestClient(app, base_url="https://testserver")
    login(processor, "processor@example.hu")
    assert processor.post("/api/v1/workspace/preparation-approvals", json=body).status_code == 403
    assert c.post("/api/v1/workspace/preparation-approvals", json={**body, "confirm": False}).status_code == 422
    assert c.post("/api/v1/workspace/preparation-approvals",
                  json={**body, "expected_approvable": 3, "idempotency_key": "approve-0002"}).status_code == 409
    # Product 1 changes between check and approval: it is skipped, not approved.
    r = c.patch(f"/api/v1/workspace/products/{ids[1]}/parameters/emag:6506",
                json={"expected_revision": revision(c, ids[1]), "action": "lock"})
    assert r.status_code == 200
    r = c.post("/api/v1/workspace/preparation-approvals", json=body)
    assert r.status_code == 200, r.text
    approval = r.json()
    assert (approval["approved"], approval["skipped_stale"], approval["valid"]) == (1, 1, 1)
    assert approval["research_targets"] == 4 and approval["schema_current"] is True
    again = c.post("/api/v1/workspace/preparation-approvals", json=body).json()
    assert again["replayed"] is True and again["id"] == approval["id"]
    state = c.get(f"/api/v1/workspace/products/{ids[0]}/preparation").json()["approval"]
    assert state["valid"] is True and state["research_targets"] == 4
    # Any later product change invalidates the item; revalidation records it.
    prepare(c, ids[0])  # no change -> still valid
    assert c.get(f"/api/v1/workspace/preparation-approvals/{approval['id']}").json()["valid"] == 1
    r = c.patch(f"/api/v1/workspace/products/{ids[0]}/parameters/emag:6506",
                json={"expected_revision": revision(c, ids[0]), "action": "lock"})
    live = c.get(f"/api/v1/workspace/preparation-approvals/{approval['id']}").json()
    assert (live["valid"], live["invalid"]) == (0, 1)
    item = c.get(f"/api/v1/workspace/preparation-approvals/{approval['id']}/items",
                 params={"valid": False}).json()["items"][0]
    assert item["invalid_reason"] == "product_changed"
    r = c.post(f"/api/v1/workspace/preparation-approvals/{approval['id']}/revalidate")
    assert r.status_code == 200 and r.json()["revalidated_at"]
    # A rules/donor-review change makes the whole approval stale.
    monkeypatch.setattr(bo, "schema_fingerprint", lambda: "0" * 64)
    assert c.get(f"/api/v1/workspace/preparation-approvals/{approval['id']}").json()["schema_current"] is False
    r = c.post(f"/api/v1/workspace/preparation-approvals/{approval['id']}/revoke",
               json={"expected_version": 1, "reason": "új szabály"})
    assert r.status_code == 200 and r.json()["state"] == "revoked" and r.json()["version"] == 2
    assert c.post(f"/api/v1/workspace/preparation-approvals/{approval['id']}/revoke",
                  json={"expected_version": 1, "reason": "újra"}).status_code == 409
    other = TestClient(app, base_url="https://testserver")
    login(other, "other@example.hu")
    assert other.get(f"/api/v1/workspace/preparation-approvals/{approval['id']}").status_code == 404
    assert other.get(f"/api/v1/workspace/product-jobs/{cid}").status_code == 404
    listed = c.get("/api/v1/workspace/preparation-approvals", params={"state": "revoked"}).json()["items"]
    assert [x["id"] for x in listed] == [approval["id"]]
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 2  # nothing created or lost
