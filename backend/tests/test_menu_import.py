import hashlib
import json
import zipfile
import pytest
from app.menu_import import process_archive, kind
from app.web_navigation import navigation


def make_zip(path, windows=False, corrupt=False, unsafe=False):
    groups = []
    members = {}
    nav = "".join(
        f'<li class="megamenu-list-department" data-id="{i}"><a>Root {i}</a></li>'
        for i in range(1, 14)
    )
    for i in range(1, 14):
        panel = f'<div class="megamenu-details-department megamenu-visible" data-id="{i}"><a class="megamenu-item megamenu-item-heading" data-id="10" href="https://www.emag.hu/section/sd">Heading</a><div class="megamenu-group megamenu-group-10"><a class="megamenu-item" data-id="20" href="https://www.emag.hu/category/c">Category</a></div></div>'
        html = f"<div><ul>{nav}</ul>{panel}</div>\n"
        data = html.encode()
        name = f"{i}.html"
        members[name] = data.replace(b"\n", b"\r\n") if windows else data
        groups.append(
            {
                "name": f"Root {i}",
                "html_evidence_file": name,
                "html_sha256": hashlib.sha256(data).hexdigest(),
                "links": [
                    {
                        "name": "Heading",
                        "url": "https://www.emag.hu/section/sd",
                        "explicit_source_attributes": {"data-id": "10"},
                    },
                    {
                        "name": "Category",
                        "url": "https://www.emag.hu/category/c",
                        "explicit_source_attributes": {"data-id": "20"},
                    },
                ],
            }
        )
    if corrupt:
        members["1.html"] += b"tampered"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
        z.writestr(
            "emag-menu-export.json",
            json.dumps(
                {
                    "root_groups": groups,
                    "observed_at": "2026-11-13T00:00:00Z",
                    "page": "https://www.emag.hu/homepage",
                }
            ),
        )
        if unsafe:
            z.writestr("../outside", "bad")
    return path


def test_dom_identity_hierarchy_and_windows_hash_transformation_are_explicit(tmp_path):
    data = process_archive(make_zip(tmp_path / "sample.zip", windows=True))
    nodes = {n["id"]: n for n in data["nodes"]}
    assert len([n for n in nodes.values() if n["parent_id"] is None]) == 13
    assert nodes["web-item-1-20"]["parent_id"] == "web-item-1-10"
    assert (
        nodes["web-item-1-20"]["parent_evidence"]
        == "explicit_group_class_to_heading_data_id"
    )
    assert all(n["canonical_emag_id"] is None for n in nodes.values())
    assert data["html_checksums"]["1.html"]["windows_newline_normalization"]
    assert (
        data["html_checksums"]["1.html"]["file_sha256"]
        != data["html_checksums"]["1.html"]["manifest_sha256"]
    )


def test_modified_evidence_and_unsafe_zip_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="checksum"):
        process_archive(make_zip(tmp_path / "bad.zip", corrupt=True))
    with pytest.raises(ValueError, match="Unsafe"):
        process_archive(make_zip(tmp_path / "unsafe.zip", unsafe=True))


def test_supplied_real_export_derivation_and_link_types():
    nav = navigation()
    data = nav.data
    assert data["manifest_link_count"] == 609
    assert len(data["issues"]) == 79 and data["html_url_disagreements"] == 18
    assert len(nav.nodes) == 636 and len(nav.children[None]) == 13
    assert nav.nodes["web-item-43-3730"]["source_item_id"] == "3730"
    assert nav.nodes["web-dept-79"]["name"] == "Könyvek, Filmek és Irodaszerek"
    assert nav.nodes["web-item-114-3490"]["kind"] == "parameter_filter"
    assert nav.nodes["web-item-114-3487"]["kind"] == "section"
    assert not data["canonical_mappings"] and not data["source_ids_are_marketplace_ids"]
    assert kind("https://www.emag.hu/shop/apple") == "brand"
    assert kind("https://www.emag.hu/lps/campaign") == "campaign"
    assert kind("https://www.emag.hu/shopping-assistant/televizio") == "product_finder"
