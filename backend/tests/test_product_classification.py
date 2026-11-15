"""CATEGORY-02A: lossless source data, own category vs internal classification."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import product_catalog as pc
from app.import_models import ImportChange, SupplierProduct
from app.main import app
from app.models import CategoryOverride
from app.product_models import ProductClassification
from conftest import login
from test_supplier_import import approve, imports, upload, work  # noqa: F401

MAPPING = {"0": "sku", "1": "name", "2": "category"}
HEAD = "SKU;NAME;CATEGORY;Teljesítmény (W);Szín;Garancia\n"
WASHER = "web-item-114-3490"  # Elöltöltős mosógépek (single donor 385)


def csv(*rows, head=HEAD):
    return (head + "".join(";".join(r) + "\n" for r in rows)).encode("utf-8")


def run(client, target, supplier, content, mapping=MAPPING, **extra):
    id = upload(client, supplier, content)
    work(target, id)
    approve(client, id, mapping=mapping, **extra)
    work(target, id)
    state = client.get(f"/api/v1/imports/runs/{id}").json()
    assert state["state"] in ("completed", "partial"), state
    return id


def products(client, **params):
    r = client.get("/api/v1/workspace/products", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def detail(client, id):
    r = client.get(f"/api/v1/workspace/products/{id}")
    assert r.status_code == 200, r.text
    return r.json()


def first_id(client):
    return products(client)["items"][0]["id"]


def patch(client, id, **body):
    return client.patch(f"/api/v1/workspace/products/{id}/classification", json=body)


def multi_donor_node():
    return next(k for k, n in pc.internal_categories().items() if len(n["donors"]) > 1)


# --- 1. lossless source parameters and change detection -----------------------


def test_every_unmapped_column_is_kept_with_header_unit_and_origin(imports):
    c, t, s = imports
    id = run(c, t, s, csv(["001", "Mosógép A", "Háztartás > Mosógépek", "2100", "Fehér", "2 év"]))
    p = detail(c, first_id(c))
    attrs = {a["key"]: a for a in p["source_attributes"]}
    assert set(attrs) == {"Teljesítmény (W)", "Szín", "Garancia"}
    power = attrs["Teljesítmény (W)"]
    assert (power["label"], power["unit"], power["raw"]) == ("Teljesítmény", "W", "2100")
    assert power["column"] == 3 and power["run_id"] == id and power["line"] == 2 and power["present"]
    assert p["source_category"]["path"] == "Háztartás > Mosógépek"
    assert p["fields"]["category"] == "Háztartás > Mosógépek"
    assert p["revision"] == 1


def test_reimport_detects_and_logs_parameter_changes(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "Mosógép A", "Mosógépek", "2100", "Fehér", "2 év"]))
    pid = first_id(c)
    second = run(c, t, s, csv(["001", "Mosógép A", "Mosógépek", "2300", "Fehér", "3 év"]))
    p = detail(c, pid)
    assert p["revision"] == 2 and products(c)["items"][0]["id"] == pid  # same identity
    attrs = {a["key"]: a["raw"] for a in p["source_attributes"]}
    assert attrs == {"Teljesítmény (W)": "2300", "Szín": "Fehér", "Garancia": "3 év"}
    with Session(t) as db:
        delta = db.scalar(select(ImportChange.delta).where(ImportChange.run_id == second))
    assert delta == {
        "source:Teljesítmény (W)": {"before": "2100", "after": "2300"},
        "source:Garancia": {"before": "2 év", "after": "3 év"},
    }
    # Unchanged re-import: no new change, no revision bump.
    third = run(c, t, s, csv(["001", "Mosógép A", "Mosógépek", "2300", "Fehér", "3 év"]))
    with Session(t) as db:
        assert db.scalar(select(func.count()).where(ImportChange.run_id == third)) == 0
    assert detail(c, pid)["revision"] == 2


def test_removed_columns_and_empty_partial_cells_never_lose_stored_values(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Mosógépek", "2100", "Fehér", "2 év"]))
    pid = first_id(c)
    # The supplier drops the "Garancia" column and leaves "Szín" empty (partial feed).
    run(c, t, s, csv(["001", "A", "Mosógépek", "2100", ""], head="SKU;NAME;CATEGORY;Teljesítmény (W);Szín\n"))
    attrs = {a["key"]: a for a in detail(c, pid)["source_attributes"]}
    assert attrs["Garancia"]["raw"] == "2 év" and attrs["Garancia"]["present"] is False
    assert attrs["Szín"]["raw"] == "Fehér" and attrs["Szín"]["present"] is True
    # A full feed may clear a value explicitly.
    run(c, t, s, csv(["001", "A", "Mosógépek", "2100", ""], head="SKU;NAME;CATEGORY;Teljesítmény (W);Szín\n"),
        feed_type="full")
    attrs = {a["key"]: a for a in detail(c, pid)["source_attributes"]}
    assert attrs["Szín"]["raw"] is None


def test_newly_mapped_column_does_not_overwrite_another_field(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Mosógépek", "2100", "Fehér", "2 év"]))
    pid = first_id(c)
    # Later the operator maps "Szín" to the internal "attributes" field.
    run(c, t, s, csv(["001", "A", "Mosógépek", "2100", "Fekete", "2 év"]),
        mapping={**MAPPING, "4": "attributes"})
    p = detail(c, pid)
    attrs = {a["key"]: a for a in p["source_attributes"]}
    assert p["fields"]["attributes"] == "Fekete"
    assert attrs["Szín"]["raw"] == "Fehér" and attrs["Szín"]["present"] is False
    assert attrs["Teljesítmény (W)"]["raw"] == "2100"


def test_duplicate_and_blank_headers_get_distinct_keys():
    attrs = pc.source_attributes(["SKU", "Méret", "Méret", ""], ["1", "a", "b", "c"], {0}, 1, 2)
    assert list(attrs) == ["Méret", "Méret #2", "Oszlop 4"]
    assert attrs["Méret #2"]["header"] == "Méret" and "header" not in attrs["Méret"]
    assert pc.expand_attribute("Méret #2", attrs["Méret #2"])["header"] == "Méret"
    assert pc.expand_attribute("Hossz (cm)", {"raw": "5"})["unit"] == "cm"
    assert pc.split_header("Súly [kg]") == ("Súly", "kg")
    assert pc.split_header("Megjegyzés (belső használatra, hosszú szöveg)") == (
        "Megjegyzés (belső használatra, hosszú szöveg)", None)


# --- 2-3. own category vs internal classification ---------------------------


def test_without_map_products_need_review_and_suggestions_are_not_applied(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Háztartás > Elöltöltős mosógépek", "", "", ""]))
    item = products(c)["items"][0]
    cls = item["classification"]
    assert cls["status"] == "needs_review" and cls["status_label"] == "Ellenőrzést igényel"
    assert "uncalibrated_suggestion" in cls["reason_codes"]
    assert cls["navigation_node_id"] is None
    assert cls["alternatives"][0]["navigation_node_id"] == WASHER
    assert item["export_category"] == {"kind": "own", "path": "Háztartás > Elöltöltős mosógépek"}


def test_approved_category_map_classifies_without_touching_own_category(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Gépek/Mosó", "", "", ""], ["002", "B", "Gépek/Mosó", "", "", ""]))
    maps = c.get("/api/v1/workspace/category-maps").json()["items"]
    assert maps[0]["product_count"] == 2 and maps[0]["map"] is None
    sc = maps[0]["source_category"]["id"]
    r = c.put(f"/api/v1/workspace/category-maps/{sc}",
              json={"expected_revision": None, "state": "approved", "navigation_node_id": WASHER})
    assert r.status_code == 200, r.text
    assert r.json()["products_changed"] == 2 and r.json()["map"]["donor_emag_category_id"] == 385
    data = products(c)
    assert data["status_counts"] == {"auto_classified": 2, "needs_review": 0}
    item = data["items"][0]
    assert item["classification"]["origin"] == "category_map"
    assert item["classification"]["navigation_path"][-1] == "Elöltöltős mosógépek"
    assert item["source_category"]["path"] == "Gépek/Mosó" and item["fields"]["category"] == "Gépek/Mosó"
    assert item["export_category"] == {"kind": "own", "path": "Gépek/Mosó"}
    # New products of the same own category inherit the map at import time.
    run(c, t, s, csv(["003", "C", "Gépek/Mosó", "", "", ""]))
    assert products(c, status="auto_classified")["status_counts"]["auto_classified"] == 3
    # The global reference assignment was never used.
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(CategoryOverride)) == 0


def test_product_without_own_category_uses_unambiguous_internal_fallback(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "", "", "", ""]))
    item = products(c)["items"][0]
    assert item["source_category"] is None
    assert item["classification"]["reason_codes"] == ["no_source_category"]
    assert item["export_category"]["kind"] == "none"
    r = patch(c, item["id"], expected_revision=item["revision"], action="set", navigation_node_id=WASHER)
    assert r.status_code == 200, r.text
    assert r.json()["export_category"] == {
        "kind": "internal", "path": " > ".join(pc.internal_category(WASHER)["path"])}


# --- 3. manual protection, audit, revision ------------------------------------


def test_manual_decision_is_locked_against_import_and_maps(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Egyéb", "", "", ""], ["002", "B", "Egyéb", "", "", ""]))
    a = products(c)["items"][0]
    r = patch(c, a["id"], expected_revision=a["revision"], action="set",
              navigation_node_id=WASHER, reason="Ellenőrzött termék")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == a["revision"] + 1
    assert body["classification"]["locked"] and body["classification"]["origin"] == "manual"
    assert body["events"][0]["kind"] == "classification_manual"
    assert body["events"][0]["reason"] == "Ellenőrzött termék"
    other = multi_donor_node()
    sc = body["source_category"]["id"]
    r = c.put(f"/api/v1/workspace/category-maps/{sc}",
              json={"expected_revision": None, "state": "approved", "navigation_node_id": other,
                    "donor_emag_category_id": pc.internal_category(other)["donors"][1]["emag_category_id"]})
    assert r.json()["products_changed"] == 1 and r.json()["locked_skipped"] == 1
    assert detail(c, a["id"])["classification"]["navigation_node_id"] == WASHER
    # A re-import with a different own category changes the own category only.
    run(c, t, s, csv(["001", "A", "Új kategória", "", "", ""]))
    p = detail(c, a["id"])
    assert p["source_category"]["path"] == "Új kategória"
    assert p["classification"]["navigation_node_id"] == WASHER and p["classification"]["locked"]
    # Reset returns the product to automatic handling.
    r = patch(c, a["id"], expected_revision=p["revision"], action="reset")
    assert r.status_code == 200, r.text
    assert not r.json()["classification"]["locked"]
    assert r.json()["classification"]["status"] == "needs_review"
    assert r.json()["revision"] == p["revision"] + 1


def test_stale_revision_is_409_and_changes_nothing(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Egyéb", "", "", ""]))
    item = products(c)["items"][0]
    assert patch(c, item["id"], expected_revision=item["revision"], action="set",
                 navigation_node_id=WASHER).status_code == 200
    stale = patch(c, item["id"], expected_revision=item["revision"], action="reset")
    assert stale.status_code == 409
    assert detail(c, item["id"])["classification"]["locked"]
    sc = item["source_category"]["id"]
    ok = c.put(f"/api/v1/workspace/category-maps/{sc}",
               json={"expected_revision": None, "state": "rejected"})
    assert ok.status_code == 200
    again = c.put(f"/api/v1/workspace/category-maps/{sc}",
                  json={"expected_revision": None, "state": "rejected"})
    assert again.status_code == 409
    assert c.delete(f"/api/v1/workspace/category-maps/{sc}", params={"expected_revision": 9}).status_code == 409
    assert c.delete(f"/api/v1/workspace/category-maps/{sc}", params={"expected_revision": 1}).status_code == 200


def test_target_and_donor_validation(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Egyéb", "", "", ""]))
    item = products(c)["items"][0]
    for body in [
        dict(navigation_node_id="web-unknown"),
        dict(navigation_node_id=WASHER, donor_emag_category_id=999999),
        dict(),
    ]:
        assert patch(c, item["id"], expected_revision=item["revision"], action="set", **body).status_code == 422
    node = multi_donor_node()
    r = patch(c, item["id"], expected_revision=item["revision"], action="set", navigation_node_id=node)
    cls = r.json()["classification"]
    assert cls["donor_emag_category_id"] is None
    assert "parameter_profile_choice_required" in cls["reason_codes"] and len(cls["donor_choices"]) > 1
    assert detail(c, item["id"])["revision"] == item["revision"] + 1


# --- 7. threshold and calibration -------------------------------------------


def test_only_calibrated_methods_above_threshold_classify_automatically(imports, monkeypatch, environment):
    c, t, s = imports
    monkeypatch.setitem(pc.CALIBRATED_PRECISION, "exact_name_match", 0.985)
    run(c, t, s, csv(["001", "A", "Elöltöltős mosógépek", "", "", ""]))
    cls = products(c)["items"][0]["classification"]
    assert cls["status"] == "auto_classified" and cls["navigation_node_id"] == WASHER
    assert cls["confidence"] == 0.985
    root = TestClient(app, base_url="https://testserver")
    login(root)
    assert root.get("/api/v1/system/settings").json()["classification"] == {"auto_threshold": 0.98}
    r = root.put("/api/v1/system/settings/classification", json={"auto_threshold": 0.99})
    assert r.status_code == 200, r.text
    assert root.put("/api/v1/system/settings/classification", json={"auto_threshold": 1.5}).status_code == 422
    run(c, t, s, csv(["002", "B", "Felültöltős mosógépek", "", "", ""]))
    review = products(c, status="needs_review")["items"]
    assert [i["fields"]["sku"] for i in review] == ["002"]


# --- isolation and permissions ----------------------------------------------


def test_tenant_isolation_and_permissions(imports, environment):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Egyéb", "", "", ""]))
    item = products(c)["items"][0]
    sc = item["source_category"]["id"]
    other = TestClient(app, base_url="https://testserver")
    login(other, "other@example.hu")
    assert other.get("/api/v1/workspace/products").json()["items"] == []
    assert other.get(f"/api/v1/workspace/products/{item['id']}").status_code == 404
    assert patch(other, item["id"], expected_revision=1, action="set", navigation_node_id=WASHER).status_code == 404
    assert other.put(f"/api/v1/workspace/category-maps/{sc}",
                     json={"expected_revision": None, "state": "rejected"}).status_code == 404
    assert other.get("/api/v1/workspace/category-maps").json()["items"] == []
    processor = TestClient(app, base_url="https://testserver")
    login(processor, "processor@example.hu")
    assert processor.get(f"/api/v1/workspace/products/{item['id']}").json()["capabilities"] == {"classify": False}
    assert patch(processor, item["id"], expected_revision=1, action="set",
                 navigation_node_id=WASHER).status_code == 403
    assert detail(c, item["id"])["capabilities"] == {"classify": True}


def test_internal_category_options(imports):
    c, t, s = imports
    r = c.get("/api/v1/workspace/internal-categories", params={"q": "mosógép"})
    assert r.status_code == 200
    ids = [i["navigation_node_id"] for i in r.json()["items"]]
    assert WASHER in ids
    total = c.get("/api/v1/workspace/internal-categories", params={"limit": 1}).json()["total"]
    assert total == len(pc.internal_categories()) and total > 400


# --- 5. per-run limit and unlimited total --------------------------------------


def test_run_limit_rejects_before_writing_and_total_is_unlimited(imports, monkeypatch):
    c, t, s = imports
    monkeypatch.setenv("IMPORT_MAX_PRODUCTS", "3")
    big = upload(c, s, csv(*[[f"{i:03}", f"T{i}", "K", "", "", ""] for i in range(4)]))
    work(t, big)
    analysis = c.get(f"/api/v1/imports/runs/{big}").json()["analysis"]
    assert analysis["data_rows"] == 4 and analysis["run_product_limit"] == 3
    r = c.post(f"/api/v1/imports/runs/{big}/approve",
               json={"name": "P", "mapping": MAPPING, "identity_field": "sku"})
    assert r.status_code == 422 and "legfeljebb 3 termék" in r.json()["error"]["message"]
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 0
    # Two runs at the limit: 6 products in total, more than one run's maximum.
    run(c, t, s, csv(*[[f"A{i}", f"T{i}", "K", "", "", ""] for i in range(3)]))
    run(c, t, s, csv(*[[f"B{i}", f"T{i}", "K", "", "", ""] for i in range(3)]))
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 6
    page = products(c, limit=4)
    assert len(page["items"]) == 4 and page["next_cursor"] is not None
    rest = products(c, limit=4, cursor=page["next_cursor"])
    assert len(rest["items"]) == 2 and rest["next_cursor"] is None


def test_run_limit_cannot_be_raised_above_50000(monkeypatch):
    from app.import_engine import run_product_limit

    monkeypatch.setenv("IMPORT_MAX_PRODUCTS", "250000")
    assert run_product_limit() == 50_000
    monkeypatch.delenv("IMPORT_MAX_PRODUCTS")
    assert run_product_limit() == 50_000


def test_oversized_automatic_run_fails_without_partial_writes(imports, monkeypatch):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "K", "", "", ""]))
    with Session(t) as db:
        from app.import_models import ImportProfile

        profile = db.scalars(select(ImportProfile)).first()
        profile.config = {**profile.config, "automatic": True}
        db.commit()
    monkeypatch.setenv("IMPORT_MAX_PRODUCTS", "2")
    big = upload(c, s, csv(*[[f"{i:03}", f"T{i}", "K", "", "", ""] for i in range(5)]))
    with pytest.raises(ValueError, match="termékszámkorlát"):
        work(t, big)
    state = c.get(f"/api/v1/imports/runs/{big}").json()
    assert state["state"] == "failed" and "legfeljebb 2 termék" in state["error"]
    with Session(t) as db:
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 1


# --- backfill -------------------------------------------------------------------


def test_backfill_fills_pre_0009_products_resumably(imports):
    from app.product_backfill import run as backfill

    c, t, s = imports
    run(c, t, s, csv(*[[f"{i:03}", f"T{i}", "Egyéb", str(i), "", ""] for i in range(5)]))
    with Session(t) as db:  # simulate products imported before migration 0009
        for p in db.scalars(select(SupplierProduct)):
            p.source_attributes = None
            p.source_category_id = None
        db.query(ProductClassification).delete()
        db.commit()
    with Session(t) as db:
        assert backfill(db, batch=2, max_batches=1)["state"] == "paused"
    with Session(t) as db:
        result = backfill(db, batch=2)
    assert result["state"] == "completed" and result["processed"] == 5
    assert result["attributes_filled"] == 5 and result["classified"] == 5
    with Session(t) as db:
        assert backfill(db)["state"] == "completed"
        p = db.scalars(select(SupplierProduct).order_by(SupplierProduct.id)).first()
        assert p.source_attributes["Teljesítmény (W)"]["raw"] == "0"
        assert p.source_category_id is not None and p.revision == 2
        assert db.scalar(select(func.count()).select_from(ProductClassification)) == 5


# --- server-side search (q) ------------------------------------------------------

SEARCH_HEAD = "SKU;NAME;EAN;CATEGORY\n"
SEARCH_MAPPING = {"0": "sku", "1": "name", "2": "gtin", "3": "category"}


def seed_search(c, t, s):
    rows = [
        ["00012", "Televízió 55 colos", "5901234123457", "TV"],
        ["00013", "Televízió állvány", "5901234123464", "TV"],
        ["A-77", "Mosógép elöltöltős", "4006381333931", "Gépek"],
        ["a_b", "Kábel 50% kedvezmény", "4006381333948", "Kábelek"],
        ["X/1", "Porszívó (zsák nélküli)", "4006381333955", "Gépek"],
    ]
    run(c, t, s, csv(*rows, head=SEARCH_HEAD), mapping=SEARCH_MAPPING)


def skus(data):
    return [i["fields"]["sku"] for i in data["items"]]


def test_search_name_sku_and_gtin_partial_case_and_accent_insensitive(imports):
    c, t, s = imports
    seed_search(c, t, s)
    assert skus(products(c, q="televizio")) == ["00012", "00013"]
    assert skus(products(c, q="TELEVÍZIÓ ÁLLVÁNY")) == ["00013"]
    assert skus(products(c, q="0012")) == ["00012"]
    assert skus(products(c, q="1333931")) == ["A-77"]
    assert skus(products(c, q="a-7")) == ["A-77"]
    assert skus(products(c, q="televízió 55")) == ["00012"]  # every term must match
    assert skus(products(c, q="televízió mosógép")) == []


def test_search_treats_sql_wildcards_and_specials_literally(imports):
    c, t, s = imports
    seed_search(c, t, s)
    assert skus(products(c, q="50%")) == ["a_b"]
    assert skus(products(c, q="%")) == ["a_b"]
    assert skus(products(c, q="a_b")) == ["a_b"]
    assert skus(products(c, q="_")) == ["a_b"]
    assert skus(products(c, q="a%b")) == []
    assert skus(products(c, q="x/1")) == ["X/1"]
    assert skus(products(c, q="(zsák")) == ["X/1"]
    assert skus(products(c, q="' OR 1=1 --")) == []
    assert skus(products(c, q="\\")) == []


def test_search_empty_missing_and_too_long(imports):
    c, t, s = imports
    seed_search(c, t, s)
    assert len(products(c, q="   ")["items"]) == 5
    nothing = products(c, q="nincs ilyen termék")
    assert nothing["items"] == [] and nothing["next_cursor"] is None
    assert nothing["status_counts"] == {"auto_classified": 0, "needs_review": 0}
    assert c.get("/api/v1/workspace/products", params={"q": "x" * 121}).status_code == 422


def test_search_combines_with_filters_counts_and_stable_cursor_pages(imports):
    c, t, s = imports
    seed_search(c, t, s)
    gepek = next(i for i in c.get("/api/v1/workspace/category-maps").json()["items"]
                 if i["source_category"]["path"] == "Gépek")["source_category"]["id"]
    c.put(f"/api/v1/workspace/category-maps/{gepek}",
          json={"expected_revision": None, "state": "approved", "navigation_node_id": WASHER})
    data = products(c, q="40063813339")
    assert data["status_counts"] == {"auto_classified": 2, "needs_review": 1}
    assert skus(products(c, q="40063813339", status="auto_classified")) == ["A-77", "X/1"]
    assert skus(products(c, q="40063813339", source_category_id=gepek, status="needs_review")) == []
    seen, cursor = [], 0
    while True:
        page = products(c, q="59012341234", limit=1, cursor=cursor)
        seen += skus(page)
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    assert seen == ["00012", "00013"]


def test_search_is_tenant_scoped_permission_checked_and_compatible(imports):
    c, t, s = imports
    seed_search(c, t, s)
    other = TestClient(app, base_url="https://testserver")
    login(other, "other@example.hu")
    assert other.get("/api/v1/workspace/products", params={"q": "televízió"}).json()["items"] == []
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get("/api/v1/workspace/products", params={"q": "tv"}).status_code == 401
    legacy = c.get("/api/v1/workspace/products").json()  # pre-02A client call
    assert {"items", "next_cursor", "field_labels"} <= set(legacy)
    assert {"id", "fields", "supplier_name", "source_line"} <= set(legacy["items"][0])


def test_search_text_follows_reimport_and_backfill(imports):
    from app.product_backfill import run as backfill

    c, t, s = imports
    seed_search(c, t, s)
    run(c, t, s, csv(["00012", "Okostelevízió 65", "5901234123457", "TV"], head=SEARCH_HEAD),
        mapping=SEARCH_MAPPING)
    assert skus(products(c, q="okos")) == ["00012"]
    assert skus(products(c, q="55 colos")) == []
    with Session(t) as db:
        for p in db.scalars(select(SupplierProduct)):
            p.search_text = None
        db.commit()
    assert products(c, q="okos")["items"] == []
    with Session(t) as db:
        assert backfill(db)["search_text_filled"] == 5
    assert skus(products(c, q="okos")) == ["00012"]


# --- CATEGORY-02C: donors awaiting review never feed automatic enrichment ----

WASHER_DRYER = "web-item-114-3492"  # Mosó-szárítógépek -> 385 Mosógépek (pending_review)
PENDING_NODES = {"web-item-114-3492": 385, "web-item-114-3820": 58, "web-item-83-4339": 63}


def test_pending_review_donors_are_marked_and_never_defaulted():
    cats = pc.internal_categories()
    for node, donor in PENDING_NODES.items():
        assert [(d["emag_category_id"], d["review_state"]) for d in cats[node]["donors"]] == [
            (donor, "pending_review")
        ]
        assert pc.default_donor(node) is None
        assert pc.parameter_profile_state(node, None) == "pending_review"
        assert pc.parameter_profile_state(node, donor) == "pending_review"
    # The same donor stays reviewed for its other, verified nodes.
    assert pc.default_donor(WASHER) == 385
    assert pc.parameter_profile_state(WASHER, 385) == "ready"
    # Multi-profile nodes always require an explicit choice before enrichment.
    multi = multi_donor_node()
    assert pc.default_donor(multi) is None
    assert pc.parameter_profile_state(multi, None) == "choice_required"
    first = pc.internal_categories()[multi]["donors"][0]["emag_category_id"]
    assert pc.parameter_profile_state(multi, first) == "ready"
    pending = {(k, d["emag_category_id"]) for k, n in cats.items() for d in n["donors"]
               if d["review_state"] != "reviewed"}
    assert pending == set(PENDING_NODES.items())


def test_category_map_to_pending_donor_node_classifies_but_keeps_enrichment_closed(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Gépek/MosóSzárító", "", "", ""]))
    sc = c.get("/api/v1/workspace/category-maps").json()["items"][0]["source_category"]["id"]
    r = c.put(f"/api/v1/workspace/category-maps/{sc}",
              json={"expected_revision": None, "state": "approved", "navigation_node_id": WASHER_DRYER})
    assert r.status_code == 200, r.text
    m = r.json()["map"]
    assert m["donor_emag_category_id"] is None and m["parameter_profile_state"] == "pending_review"
    cls = products(c)["items"][0]["classification"]
    # The category decision itself (CATEGORY-02A) is unchanged ...
    assert cls["status"] == "auto_classified" and cls["navigation_node_id"] == WASHER_DRYER
    # ... but no donor is stored automatically and the enrichment gate is closed.
    assert cls["donor_emag_category_id"] is None
    assert cls["parameter_profile_state"] == "pending_review"
    assert "parameter_profile_pending_review" in cls["reason_codes"]


def test_explicit_manual_pending_donor_is_stored_but_gate_stays_closed(imports):
    c, t, s = imports
    run(c, t, s, csv(["001", "A", "Valami", "", "", ""]))
    pid = first_id(c)
    rev = detail(c, pid)["revision"]
    r = patch(c, pid, expected_revision=rev, action="set", navigation_node_id=WASHER_DRYER,
              donor_emag_category_id=385)
    assert r.status_code == 200, r.text
    cls = r.json()["classification"]
    assert cls["donor_emag_category_id"] == 385 and cls["locked"]
    assert cls["parameter_profile_state"] == "pending_review"
    assert cls["reason_codes"] == ["manual_decision", "parameter_profile_pending_review"]
    # A reviewed single donor is ready.
    r = patch(c, pid, expected_revision=r.json()["revision"], action="set", navigation_node_id=WASHER)
    cls = r.json()["classification"]
    assert (cls["donor_emag_category_id"], cls["parameter_profile_state"]) == (385, "ready")
    assert cls["reason_codes"] == ["manual_decision"]
