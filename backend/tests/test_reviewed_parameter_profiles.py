"""Reviewed equivalences, complete audit, separate profile flags/value domains."""

from pathlib import Path
from copy import deepcopy
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.category_export import load_category_export
from app.category_tree import CategoryTree
from app.fixed_navigation import resolve_fixed
from app.parameter_profiles import reviewed_bindings
from app.web_navigation import navigation
from app.catalog_import import SourceReader, import_catalog, activate
from app.models import CatalogVersion
from test_fixed_category_catalog import frozen_data
from conftest import login


@pytest.fixture
def extra_reference_categories():
    tree = load_category_export(
        Path(__file__).parent / "fixtures/emag_categories_export.tsv"
    )
    ids = [411, 34, 292, 5, 371, 372, 2780, 2782, 1337, 829, 1330, 3570, 3528]
    return [dict(tree.rows[tree.external[external]]) for external in ids]


@pytest.fixture
def extra_reference_parameters(extra_reference_categories):
    return [
        dict(
            id=12000 + i,
            category_id=r["id"],
            emag_parameter_id=60000,
            name="Profiltípus",
            type_id=2,
            display_order=0,
            is_mandatory=r["emag_category_id"] in (371, 2782),
            is_filter=True,
            allow_new_value=False,
        )
        for i, r in enumerate(extra_reference_categories)
        if r["emag_category_id"] not in (829, 3570)
    ]


@pytest.fixture
def extra_reference_values(extra_reference_categories, extra_reference_parameters):
    external = {r["id"]: r["emag_category_id"] for r in extra_reference_categories}
    return [
        dict(
            id=120000 + i,
            parameter_id=p["id"],
            value_text=f"profil-{external[p['category_id']]}",
            value_order=0,
        )
        for i, p in enumerate(extra_reference_parameters)
    ]


def test_all_missing_and_zero_parameter_cases_have_reviewed_donors_without_changing_other_edges():
    tree = load_category_export(
        Path(__file__).parent / "fixtures/emag_categories_export.tsv"
    )
    before = deepcopy(tree.rows)
    nav = resolve_fixed(navigation(), tree)
    assert len(nav.nodes) == 583 and len(nav.roots) == 13
    assert len(nav.bindings) == 457 and len(nav.parameter_donors) == 457
    assert nav.reference_coverage["unavailable_parameter_binding_count"] == 0
    assert nav.reference_coverage["ambiguous_parameter_binding_count"] == 0
    assert nav.reference_coverage["categories_with_parameter_set"] == 457
    assert nav.reference_coverage["parameter_profile_count"] == 555
    assert nav.reference_coverage["multi_profile_category_count"] == 23
    assert nav.profile_warnings == [] and tree.rows == before
    assert len(reviewed_bindings()["rules"]) == 457
    for key, donors in nav.parameter_donors.items():
        assert all(tree.counts[c]["total"] > 0 for c in donors)
        assert len(donors) == len(set(donors))
    assert "web-item-43-3550" not in nav.nodes
    assert not any(
        x["id"] == "web-item-43-3550" for x in nav.related("web-item-43-3547")
    )
    expected = {
        "Szabadonálló mosogatógépek": (411, 36),
        "Robotgépek": (34, 23),
        "Elektromos grillsütők": (292, 17),
        "Monitorok": (5, 39),
    }
    for label, (external, total) in expected.items():
        key = next(k for k, n in nav.nodes.items() if n["name"] == label)
        assert tree.rows[nav.bindings[key]]["emag_category_id"] == external
        assert tree.counts[nav.bindings[key]]["total"] == total
    for path, external in [
        (
            ("Telefon, Tablet, Laptop", "Mobiltelefon tartozékok", "Egyéb tartozékok"),
            2774,
        ),
        (("Telefon, Tablet, Laptop", "Tabletek és tartozékok", "Töltők"), 2786),
        (
            (
                "Telefon, Tablet, Laptop",
                "Tabletek és tartozékok",
                "Kábelek és adapterek",
            ),
            2785,
        ),
        (
            (
                "Fotó-Videó, Okos eszközök",
                "Fényképezőgép tartozékok",
                "Egyéb tartozékok",
            ),
            71,
        ),
        (
            ("Autó- és motor felszerelések", "Autós műszaki cikkek", "Akkumulátorok"),
            1425,
        ),
    ]:
        key = next(
            k
            for k in nav.nodes
            if tuple(nav.nodes[p]["name"] for p in nav.path(k)) == path
        )
        assert tree.rows[nav.bindings[key]]["emag_category_id"] == external
    pet = "web-item-615-4281"
    assert [tree.rows[c]["emag_category_id"] for c in nav.parameter_donors[pet]] == [
        1337
    ]
    for flags in (0, 1, None):
        variant = CategoryTree(
            [{**r, "is_allowed": flags} for r in tree.rows.values()], tree.counts
        )
        assert (
            resolve_fixed(navigation(), variant).parameter_donors
            == nav.parameter_donors
        )


@pytest.mark.parametrize("owned", [False, True])
def test_profiles_keep_source_flags_and_allowed_values_separate_without_reimport(
    environment, owned
):
    client, target, source, _ = environment
    if owned:
        version = import_catalog(target, SourceReader(source), pause_ms=0)
        activate(target, version)
        with Session(target) as db:
            before = frozen_data(db, version)
    login(client)
    key = "web-item-7-4253"
    details = client.get("/api/v1/reference/navigation/" + key).json()
    assert details["mapping_status"] == "confirmed"
    assert [p["emag_category_id"] for p in details["parameter_profiles"]] == [371, 372]
    assert (
        details["mandatory_parameter_count"] is None
    )  # no fabricated combined requirement
    assert details["optional_parameter_count"] is None
    assert (
        client.get("/api/v1/reference/navigation/" + key + "/parameters").status_code
        == 409
    )
    assert (
        client.get(
            "/api/v1/reference/navigation/" + key + "/parameters?profile_emag_id=3528"
        ).status_code
        == 409
    )
    for external, mandatory in [(371, True), (372, False)]:
        response = client.get(
            f"/api/v1/reference/navigation/{key}/parameters?profile_emag_id={external}"
        ).json()
        assert response["total"] == 1
        param = response["items"][0]
        assert param["is_mandatory"] == mandatory
        vals = client.get(
            f"/api/v1/reference/parameters/{param['id']}/values?view=all"
        ).json()["items"]
        assert [r["value_text"] for r in vals] == [f"profil-{external}"]
    cable = client.get("/api/v1/reference/navigation?q=Töltőkábelek").json()["items"][0]
    assert [p["emag_category_id"] for p in cable["parameter_profiles"]] == [2782, 2780]
    for name, external in [
        ("Robotgépek", 34),
        ("Elektromos grillsütők", 292),
        ("Monitorok", 5),
        ("Szabadonálló mosogatógépek", 411),
    ]:
        node = next(
            r
            for r in client.get(
                "/api/v1/reference/navigation", params={"q": name}
            ).json()["items"]
            if r["name"] == name
        )
        assert node["canonical_emag_id"] == external and node["parameter_count"] == 1
    pet = client.get("/api/v1/reference/navigation/web-item-615-4281").json()
    assert pet["canonical_emag_id"] == 1337
    assert (
        client.get("/api/v1/reference/navigation/web-item-43-3550").status_code == 404
    )
    selected = details["parameter_profiles"][0]
    body = (
        {"category_id": selected["source_category_id"]}
        if owned
        else {"canonical_emag_id": 371}
    )
    assert (
        client.post(
            "/api/v1/reference/navigation/" + key + "/assignment", json=body
        ).status_code
        == 200
    )
    assert [
        p["emag_category_id"]
        for p in client.get("/api/v1/reference/navigation/" + key).json()[
            "parameter_profiles"
        ]
    ] == [371]
    assert (
        client.post(
            "/api/v1/reference/navigation/" + key + "/assignment", json={"reset": True}
        ).status_code
        == 200
    )
    assert [
        p["emag_category_id"]
        for p in client.get("/api/v1/reference/navigation/" + key).json()[
            "parameter_profiles"
        ]
    ] == [371, 372]
    if owned:
        with Session(target) as db:
            assert frozen_data(db, version) == before
            assert db.scalar(select(func.count()).select_from(CatalogVersion)) == 1


def test_missing_reviewed_phone_source_never_falls_back_to_same_named_laptop_accessory():
    tree = CategoryTree(
        [
            dict(
                id=1,
                emag_category_id=327,
                name="Egyéb tartozékok",
                parent_id=450,
                is_allowed=True,
            )
        ],
        {1: {"total": 13}},
    )
    nav = resolve_fixed(navigation(), tree)
    key = next(
        k
        for k in nav.nodes
        if [nav.nodes[p]["name"] for p in nav.path(k)]
        == ["Telefon, Tablet, Laptop", "Mobiltelefon tartozékok", "Egyéb tartozékok"]
    )
    assert key not in nav.bindings
    assert key not in nav.parameter_donors
