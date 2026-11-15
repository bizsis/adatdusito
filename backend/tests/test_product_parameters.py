"""CATEGORY-03A: parameter slots, aliases, units, locks, donor changes and runs."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import product_jobs
from app import product_parameters as pp
from app.catalog_constants import ACTIVE_KEY, COMMON_ID_START, SOURCE
from app.main import app
from app.models import (
    CatalogCategory,
    CatalogLink,
    CatalogLinkEntry,
    CatalogParameter,
    CatalogSourceMapping,
    CatalogValue,
    CatalogVersion,
    Setting,
)
from app.product_models import ProductEvent, ProductParameterValue
from conftest import login
from test_product_classification import csv, detail, first_id, patch, run
from test_supplier_import import imports  # noqa: F401

WASHER = "web-item-114-3490"  # Elöltöltős mosógépek -> 385 (reviewed)
WASHER_DRYER = "web-item-114-3492"  # -> 385 (pending_review)
VACUUM = "web-item-114-3751"  # Porzsákos porszívók -> 58 (reviewed)
EBOOK = "web-item-43-3697"  # 103 / 313 (two profiles)

# (emag_category_id, [(emag_parameter_id, name, mandatory, allow_new_value, values)])
DONORS = {
    385: [
        (6506, "Teljesítmény (W)", True, True, []),
        (6507, "Szín", False, False, ["Fehér", "Fekete"]),
        (6508, "Kapacitás (kg)", True, True, []),
        (6509, "Energiaosztály", True, False, ["A", "B"]),
        (6510, "Zajszint (dB)", False, True, []),
        (6511, "Szélesség (cm)", False, True, []),
        (6512, "Programok száma", False, True, []),
    ],
    58: [
        (5801, "Teljesítmény (W)", True, True, []),
        (5802, "Porzsák kapacitás (l)", False, True, []),
    ],
    103: [(10301, "Kijelző mérete (inch)", True, True, [])],
}
HEAD = "SKU;NAME;CATEGORY;Teljesítmény (kW);Szín;Kapacitás (kg);Zajszint;Szélesség (mm);Garancia\n"
MAPPING = {"0": "sku", "1": "name", "2": "category"}


def install_catalog(target):
    with Session(target) as db:
        db.add(CatalogVersion(id=1, source_key=SOURCE, status="ready", phase="done", cursor=0,
                              source_state={}, counters={}, verification={"complete": True}))
        db.add(Setting(key=ACTIVE_KEY, value="1"))
        db.flush()
        link, value = COMMON_ID_START + 1000, COMMON_ID_START + 5000
        for n, (donor, params) in enumerate(DONORS.items()):
            category = COMMON_ID_START + n + 1
            db.add(CatalogCategory(id=category, key=f"{SOURCE}:category:{donor}", name=str(donor)))
            for order, (emag_id, name, mandatory, allow, values) in enumerate(params):
                link += 1
                db.add(CatalogParameter(id=link, key=f"p{link}", name=name, type_id=1))
                db.add(CatalogLink(id=link, key=f"l{link}"))
                db.flush()
                db.add(CatalogLinkEntry(version_id=1, link_id=link, category_id=category, parameter_id=link,
                                        name=name, emag_parameter_id=emag_id, display_order=order,
                                        is_mandatory=mandatory, is_filter=False, allow_new_value=allow))
                for text in values:
                    value += 1
                    db.add(CatalogValue(id=value, key=f"v{value}", parameter_id=link, value_text=text))
                    db.flush()
                    db.add(CatalogSourceMapping(version_id=1, kind="value", source_key=SOURCE, source_id=value,
                                                target_id=value, context_id=link, payload_sha256="x"))
        db.commit()


@pytest.fixture
def params(imports, monkeypatch):
    c, t, s = imports
    install_catalog(t)
    sent = []
    monkeypatch.setattr(product_jobs, "enqueue_parameters", sent.append)
    return c, t, s, sent


def rows(*values, head=HEAD):
    return csv(*values, head=head)


def washer(c, t, s, power="2,1", color="fehér", node=WASHER, donor=None, head=HEAD, extra=None):
    values = extra or ["001", "Mosógép A", "Gépek", power, color, "8", "52", "600", "2 év"]
    run(c, t, s, rows(values, head=head), mapping=MAPPING)
    pid = first_id(c)
    body = dict(expected_revision=detail(c, pid)["revision"], action="set", navigation_node_id=node)
    if donor:
        body["donor_emag_category_id"] = donor
    assert patch(c, pid, **body).status_code == 200
    return pid


def revision(c, pid):
    return detail(c, pid)["revision"]


def apply(c, pid, expected=None):
    r = c.post(f"/api/v1/workspace/products/{pid}/parameters/apply",
               json={"expected_revision": expected or revision(c, pid)})
    assert r.status_code == 200, r.text
    return r.json()


def slots(body):
    return {s["slot_key"]: s for s in body["slots"]}


def edit(c, pid, key, **body):
    return c.patch(f"/api/v1/workspace/products/{pid}/parameters/{key}",
                   json={"expected_revision": revision(c, pid), **body})


# --- pure rules -----------------------------------------------------------------


def test_units_numbers_and_labels_are_deterministic():
    assert pp.parse_number("2,1 kW") == (Decimal("2.1"), "kW", False)
    assert pp.parse_number("1.200")[2] is True  # thousands separator is not guessed
    assert pp.parse_number("kb. 5") is None
    assert pp.format_number(pp.convert(Decimal("2.1"), "kW", "W")[0]) == "2100"
    assert pp.format_number(pp.convert(Decimal("600"), "mm", "cm")[0]) == "60"
    assert pp.format_number(pp.convert(Decimal("1500"), "g", "kg")[0]) == "1.5"
    assert pp.convert(Decimal("1"), "GB", "MB") is None  # ambiguous: never converted
    assert pp.convert(Decimal("1"), "kg", "cm") is None
    assert pp.label_key("Teljesítmény") == "teljesitmeny"
    assert len(pp.slot_key_for_source("x" * 400)) <= 191


# --- slots from source values -----------------------------------------------------


def test_preview_does_not_write_and_apply_builds_expected_slots(params):
    c, t, s, _ = params
    pid = washer(c, t, s)
    rev = revision(c, pid)
    preview = c.post(f"/api/v1/workspace/products/{pid}/parameters/preview", json={})
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"]["create"] == 8 and revision(c, pid) == rev
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(ProductParameterValue)) == 0
    body = apply(c, pid)
    got = slots(body)
    power = got["emag:6506"]
    assert (power["state"], power["value"], power["unit"], power["origin"]) == ("present", "2100", "W", "source")
    assert power["unit_conversion"] == {"from": "kW", "to": "W", "factor": "1000", "raw_number": "2,1"}
    assert power["sources"][0]["raw"] == "2,1" and power["sources"][0]["header"] == "Teljesítmény (kW)"
    assert "unit_converted" in power["reason_codes"]
    color = got["emag:6507"]
    assert (color["state"], color["value"]) == ("present", "Fehér") and color["value_id"]
    assert got["emag:6508"]["value"] == "8"
    assert got["emag:6509"]["state"] == "missing" and got["emag:6509"]["origin"] == "added_slot"
    assert got["emag:6509"]["mandatory"] is True
    noise = got["emag:6510"]
    assert noise["state"] == "review" and "unit_unverified" in noise["reason_codes"]
    assert got["emag:6511"]["value"] == "60" and got["emag:6511"]["unit"] == "cm"
    assert got["emag:6512"]["state"] == "missing"
    assert got["src:Garancia"]["state"] == "source_only" and got["src:Garancia"]["value"] == "2 év"
    assert body["revision"] == rev + 1 and body["applied"]["create"] == 8
    # Idempotent: a second apply changes nothing and keeps the revision.
    again = apply(c, pid)
    assert again["applied"] == {"create": 0, "update": 0, "remove": 0, "keep": 8, "blocked_locked": 0}
    assert again["revision"] == rev + 1
    diff = c.get("/api/v1/workspace/parameter-diff").json()["items"][0]
    assert diff["prepared"] and diff["mandatory_missing"] == 1
    assert diff["counts"]["present"] == 4 and diff["counts"]["source_only"] == 1
    assert diff["parameter_profile_state"] == "ready"
    filtered = c.get("/api/v1/workspace/parameter-diff", params={"state": "conflict"}).json()
    assert filtered["items"] == []
    assert c.get("/api/v1/workspace/parameter-diff",
                 params={"mandatory_missing": True}).json()["items"][0]["product_id"] == pid


def test_conflicting_sources_and_not_allowed_values(params):
    c, t, s, _ = params
    head = "SKU;NAME;CATEGORY;Szín;Szín;Energiaosztály\n"
    pid = washer(c, t, s, head=head, extra=["001", "A", "Gépek", "Fehér", "Fekete", "C"])
    got = slots(apply(c, pid))
    color = got["emag:6507"]
    assert color["state"] == "conflict" and color["value"] is None
    assert {x["source_key"] for x in color["candidates"]} == {"Szín", "Szín #2"}
    assert len(color["sources"]) == 2  # nothing dropped, no duplicate slot
    assert not any(k.startswith("src:Szín") for k in got)
    energy = got["emag:6509"]
    assert energy["state"] == "invalid" and "value_not_allowed" in energy["reason_codes"]
    assert energy["sources"][0]["raw"] == "C"
    # Manual resolution: accept one candidate (locked, audited, revisioned).
    r = edit(c, pid, "emag:6507", action="accept_candidate", source_key="Szín #2")
    assert r.status_code == 200, r.text
    color = slots(r.json())["emag:6507"]
    assert (color["state"], color["value"], color["origin"], color["locked"]) == ("present", "Fekete", "user", True)
    # Bound value list: free text is refused, an allowed value_id is accepted.
    assert edit(c, pid, "emag:6509", action="set", value="Z").status_code == 422
    with Session(t) as db:
        value_a = db.scalar(select(CatalogValue.id).where(CatalogValue.value_text == "A"))
    r = edit(c, pid, "emag:6509", action="set", value_id=value_a)
    assert slots(r.json())["emag:6509"]["value"] == "A"


def test_wrong_unit_and_text_for_numeric_parameter_are_invalid(params):
    c, t, s, _ = params
    head = "SKU;NAME;CATEGORY;Teljesítmény (kg);Kapacitás (kg)\n"
    pid = washer(c, t, s, head=head, extra=["001", "A", "Gépek", "5", "nagy"])
    got = slots(apply(c, pid))
    assert got["emag:6506"]["state"] == "invalid" and "unit_mismatch" in got["emag:6506"]["reason_codes"]
    assert got["emag:6508"]["state"] == "invalid" and "not_numeric" in got["emag:6508"]["reason_codes"]
    assert got["emag:6508"]["sources"][0]["raw"] == "nagy"


# --- aliases ------------------------------------------------------------------------


def test_tenant_alias_maps_label_and_global_alias_needs_system_permission(params, environment):
    c, t, s, _ = params
    head = "SKU;NAME;CATEGORY;Watt (W)\n"
    pid = washer(c, t, s, head=head, extra=["001", "A", "Gépek", "1800"])
    got = slots(apply(c, pid))
    assert got["emag:6506"]["state"] == "missing" and got["src:Watt (W)"]["state"] == "source_only"
    alias = {"scope": "tenant", "label": "Watt", "unit": "W", "emag_parameter_id": 6506,
             "scope_emag_category_id": 385, "reason": "beszállítói fejléc"}
    r = c.post("/api/v1/workspace/parameter-aliases", json=alias)
    assert r.status_code == 200, r.text
    created = r.json()
    assert c.post("/api/v1/workspace/parameter-aliases", json=alias).status_code == 409
    assert c.post("/api/v1/workspace/parameter-aliases",
                  json={**alias, "emag_parameter_id": 9999}).status_code == 422
    assert c.post("/api/v1/workspace/parameter-aliases", json={**alias, "scope": "global"}).status_code == 403
    got = slots(apply(c, pid))
    power = got["emag:6506"]
    assert (power["state"], power["value"], power["origin"]) == ("present", "1800", "alias")
    assert power["alias"] == {"id": created["id"], "version": 1, "scope": "tenant"}
    assert "src:Watt (W)" not in got
    # Revoking keeps history and never erases the stored value automatically.
    r = c.delete(f"/api/v1/workspace/parameter-aliases/{created['id']}", params={"expected_version": 1})
    assert r.status_code == 200 and r.json()["state"] == "revoked" and r.json()["version"] == 2
    assert c.delete(f"/api/v1/workspace/parameter-aliases/{created['id']}",
                    params={"expected_version": 1}).status_code == 409
    got = slots(apply(c, pid))
    assert got["emag:6506"]["value"] == "1800" and got["emag:6506"]["state"] == "conflict"
    listed = c.get("/api/v1/workspace/parameter-aliases", params={"state": "revoked"}).json()["items"]
    assert [a["id"] for a in listed] == [created["id"]]
    # A superadmin may create a global alias; other tenants see it, not tenant aliases.
    root = TestClient(app, base_url="https://testserver")
    login(root)
    assert root.post("/api/v1/auth/tenant", json={"tenant_id": 1}).status_code == 200
    r = root.post("/api/v1/workspace/parameter-aliases",
                  json={**alias, "scope": "global", "label": "Power"})
    assert r.status_code == 200 and r.json()["scope"] == "global", r.text
    seen = c.get("/api/v1/workspace/parameter-aliases", params={"scope": "global"}).json()["items"]
    assert [a["label"] for a in seen] == ["Power"]
    # The admin of the tenant cannot revoke a global alias.
    assert c.delete(f"/api/v1/workspace/parameter-aliases/{r.json()['id']}",
                    params={"expected_version": 1}).status_code == 403


# --- donor protection --------------------------------------------------------------


def test_pending_review_and_choice_required_donors_get_no_emag_slots(params):
    c, t, s, _ = params
    pid = washer(c, t, s, node=WASHER_DRYER)
    got = slots(apply(c, pid))
    assert got and all(k.startswith("src:") for k in got)
    assert all("donor_not_ready" in x["reason_codes"] for x in got.values())
    assert c.get(f"/api/v1/workspace/products/{pid}/parameters").json()["classification"][
        "parameter_profile_state"] == "pending_review"
    # Multi-profile without explicit choice: no slots; with explicit choice: donor slots.
    edit_body = dict(expected_revision=revision(c, pid), action="set", navigation_node_id=EBOOK)
    assert patch(c, pid, **edit_body).status_code == 200
    got = slots(apply(c, pid))
    assert not any(k.startswith("emag:") for k in got)
    assert patch(c, pid, expected_revision=revision(c, pid), action="set", navigation_node_id=EBOOK,
                 donor_emag_category_id=103).status_code == 200
    got = slots(apply(c, pid))
    assert got["emag:10301"]["state"] == "missing"


# --- locks, refresh, donor change -----------------------------------------------------


def test_lock_wins_over_feed_refresh_and_same_source_refresh_is_logged(params):
    c, t, s, _ = params
    pid = washer(c, t, s)
    apply(c, pid)
    r = edit(c, pid, "emag:6506", action="set", value="2000", unit="W", reason="adatlap")
    assert r.status_code == 200
    assert slots(r.json())["emag:6506"]["locked"] is True
    run(c, t, s, rows(["001", "Mosógép A", "Gépek", "2,3", "fekete", "8", "52", "600", "3 év"]), mapping=MAPPING)
    got = slots(apply(c, pid))
    assert got["emag:6506"]["value"] == "2000" and "source_changed_locked" in got["emag:6506"]["reason_codes"]
    assert got["emag:6507"]["value"] == "Fekete" and "source_refreshed" in got["emag:6507"]["reason_codes"]
    assert got["src:Garancia"]["value"] == "3 év"
    with Session(t) as db:
        kinds = [e.kind for e in db.scalars(select(ProductEvent).where(ProductEvent.product_id == pid))]
    assert "parameter_manual" in kinds and "parameter_source_refresh" in kinds
    # Unlock + reset recomputes from the source.
    r = edit(c, pid, "emag:6506", action="reset")
    assert r.status_code == 200, r.text
    assert slots(r.json())["emag:6506"]["value"] == "2300"


def test_donor_change_drops_empty_slots_and_keeps_filled_values(params):
    c, t, s, _ = params
    pid = washer(c, t, s)
    apply(c, pid)
    assert patch(c, pid, expected_revision=revision(c, pid), action="set",
                 navigation_node_id=VACUUM).status_code == 200
    got = slots(apply(c, pid))
    assert "emag:6509" not in got and "emag:6512" not in got  # empty old slots removed
    assert got["emag:6507"]["state"] == "detached" and got["emag:6507"]["value"] == "Fehér"
    # "Kapacitás (kg)" only resembles "Porzsák kapacitás (l)": review, never auto.
    assert got["emag:5802"]["state"] == "review" and got["emag:5802"]["value"] is None
    assert got["emag:5802"]["candidates"][0]["source_key"] == "Kapacitás (kg)"
    assert got["src:Kapacitás (kg)"]["state"] == "source_only"
    # The new donor's power parameter is filled from the same source column.
    assert got["emag:5801"]["value"] == "2100"


# --- concurrency, tenant, permissions ------------------------------------------------


def test_stale_revision_tenant_isolation_and_permissions(params):
    c, t, s, _ = params
    pid = washer(c, t, s)
    stale = revision(c, pid)
    apply(c, pid)
    r = c.post(f"/api/v1/workspace/products/{pid}/parameters/apply", json={"expected_revision": stale})
    assert r.status_code == 409
    r = c.patch(f"/api/v1/workspace/products/{pid}/parameters/emag:6506",
                json={"expected_revision": stale, "action": "lock"})
    assert r.status_code == 409
    other = TestClient(app, base_url="https://testserver")
    login(other, "other@example.hu")
    assert other.get(f"/api/v1/workspace/products/{pid}/parameters").status_code == 404
    assert other.get("/api/v1/workspace/parameter-diff").json()["items"] == []
    processor = TestClient(app, base_url="https://testserver")
    login(processor, "processor@example.hu")
    view = processor.get(f"/api/v1/workspace/products/{pid}/parameters")
    assert view.status_code == 200 and view.json()["capabilities"] == {"edit": False}
    assert processor.post(f"/api/v1/workspace/products/{pid}/parameters/apply",
                          json={"expected_revision": revision(c, pid)}).status_code == 403
    assert processor.post("/api/v1/workspace/parameter-runs", json={"mode": "apply"}).status_code == 403
    assert c.patch(f"/api/v1/workspace/products/{pid}/parameters/emag:999",
                   json={"expected_revision": revision(c, pid), "action": "lock"}).status_code == 404


def test_no_active_catalog_is_503(imports):
    c, t, s = imports
    run(c, t, s, rows(["001", "A", "Gépek", "2", "fehér", "8", "52", "600", "2 év"]), mapping=MAPPING)
    pid = first_id(c)
    assert c.post(f"/api/v1/workspace/products/{pid}/parameters/preview", json={}).status_code == 503


# --- background runs -----------------------------------------------------------------


def test_run_limit_continuation_preview_and_idempotent_apply(params, monkeypatch):
    c, t, s, sent = params
    run(c, t, s, rows(*[[f"00{i}", f"T{i}", "Gépek", "2", "fehér", "8", "52", "600", "2 év"]
                        for i in range(5)]), mapping=MAPPING)
    sc = c.get("/api/v1/workspace/category-maps").json()["items"][0]["source_category"]["id"]
    assert c.put(f"/api/v1/workspace/category-maps/{sc}", json={
        "expected_revision": None, "state": "approved", "navigation_node_id": WASHER}).status_code == 200
    monkeypatch.setenv("IMPORT_MAX_PRODUCTS", "2")  # stands in for the 50 000 per-run limit
    preview = c.post("/api/v1/workspace/parameter-runs", json={"mode": "preview"}).json()["job"]
    with Session(t) as db:
        assert product_jobs.advance_parameters(db, preview["id"], batch=1) == "completed"
        assert db.scalar(select(func.count()).select_from(ProductParameterValue)) == 0
    state = c.get(f"/api/v1/workspace/product-jobs/{preview['id']}").json()
    assert (state["processed"], state["limit"], state["has_more"]) == (2, 2, True)
    assert state["slots"]["create"] == 16 and state["products_changed"] == 2
    start, applied = 0, 0
    while True:
        job = c.post("/api/v1/workspace/parameter-runs",
                     json={"mode": "apply", "start_after_product_id": start}).json()["job"]
        assert sent[-1] == job["id"]
        with Session(t) as db:
            product_jobs.advance_parameters(db, job["id"], batch=1)
        state = c.get(f"/api/v1/workspace/product-jobs/{job['id']}").json()
        applied += state["products_changed"]
        if not state["has_more"]:
            break
        start = state["next_start_after_product_id"]
    assert applied == 5  # 5 stored products > 2 per run: continuation covers all
    with Session(t) as db:
        assert db.scalar(select(func.count(func.distinct(ProductParameterValue.product_id)))) == 5
    again = c.post("/api/v1/workspace/parameter-runs", json={"mode": "apply"}).json()["job"]
    with Session(t) as db:
        product_jobs.advance_parameters(db, again["id"])
    state = c.get(f"/api/v1/workspace/product-jobs/{again['id']}").json()
    assert state["products_changed"] == 0 and state["slots"]["keep"] == 16  # still 2 per run


def test_run_is_resumable_and_superseded_by_same_scope(params):
    c, t, s, _ = params
    run(c, t, s, rows(*[[f"00{i}", f"T{i}", "Gépek", "2", "fehér", "8", "52", "600", "2 év"]
                        for i in range(3)]), mapping=MAPPING)
    first = c.post("/api/v1/workspace/parameter-runs", json={"mode": "apply"}).json()["job"]
    with Session(t) as db:
        assert product_jobs.advance_parameters(db, first["id"], batch=1, max_batches=1) == "pending"
    second = c.post("/api/v1/workspace/parameter-runs", json={"mode": "apply"}).json()["job"]
    with Session(t) as db:
        assert product_jobs.advance_parameters(db, first["id"]) == "superseded"
        assert product_jobs.advance_parameters(db, second["id"]) == "completed"
    state = c.get(f"/api/v1/workspace/product-jobs/{second['id']}").json()
    assert state["processed"] == 3 and state["products_not_ready"] == 3  # unclassified: src only
