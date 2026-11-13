"""Rendered desktop/mobile behavior with local build and synthetic API responses.

Backend API semantics are independently tested in test_web_navigation.py.
"""

import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright, expect
from app.web_navigation import navigation, dto
from app.fixed_navigation import resolve_fixed
from app.category_tree import CategoryTree


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_verified_roots_lazy_children_and_separate_review(width, height):
    dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    assert (dist / "index.html").exists(), "Run npm run build in frontend first"
    tree = CategoryTree(
        [
            dict(
                id=1,
                emag_category_id=90001,
                name="Televíziók",
                parent_id=None,
                is_allowed=True,
            ),
            dict(
                id=2,
                emag_category_id=90002,
                name="Televíziók",
                parent_id=None,
                is_allowed=False,
            ),
        ]
    )
    nav = resolve_fixed(navigation(), tree)
    requests = []
    pending = nav.nodes["web-item-43-3730"]

    def route_request(route):
        url = urlparse(route.request.url)
        query = parse_qs(url.query)
        path = url.path
        if not path.startswith("/api/"):
            file = dist / (path.lstrip("/") or "index.html")
            route.fulfill(
                body=file.read_bytes(),
                content_type=mimetypes.guess_type(file.name)[0] or "text/plain",
            )
            return
        if path.endswith("/auth/me"):
            response = {
                "user": {"name": "Teszt Admin", "superadmin": True},
                "permissions": ["reference.read"],
                "memberships": [],
                "csrf_token": "test",
                "tenant_id": None,
                "role": None,
            }
        elif path.endswith("/navigation/coverage"):
            response = {
                "root_count": 13,
                "manifest_link_count": 609,
                "hierarchy_needs_review": 79,
                "confirmed_bindings": 0,
                "reference_coverage": nav.reference_coverage,
            }
        elif path.endswith("/navigation"):
            requests.append(query)
            term = query.get("q", [""])[0]
            if term:
                ids = [
                    k
                    for k in nav.visible
                    if term.casefold() in nav.nodes[k]["name"].casefold()
                ]
            elif query.get("scope") == ["unclassified"]:
                ids = [
                    k
                    for k in nav.visible
                    if k not in nav.bindings and len(nav.candidates.get(k, [])) > 1
                ]
            elif "parent_id" in query:
                ids = nav.tree_children(query["parent_id"][0])
            else:
                ids = nav.roots
            response = {
                "items": [dto(nav, k, {}, tree) for k in ids],
                "total": len(ids),
                "offset": 0,
                "limit": 100,
            }
        else:
            response = {"items": [], "total": 0, "checks": {}}
        route.fulfill(json=response)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("http://navigation.test/**", route_request)
        page.goto("http://navigation.test/")
        page.get_by_role("navigation").get_by_role("button", name="Kategóriák").click()
        expect(page.locator(".tree > ul > li")).to_have_count(13)
        assert not any("parent_id" in q for q in requests)
        expect(page.locator(".tree > ul > li > .tree-row > .tree-name")).to_have_text(
            [nav.nodes[k]["name"] + "Főcsoport" for k in nav.roots]
        )
        toggle = page.get_by_role(
            "button", name="TV és szórakozás alkategóriái", exact=True
        )
        toggle.click()
        expect(
            page.locator(".tree-name").filter(has_text="Televíziók").first
        ).to_be_visible()
        assert any(q.get("parent_id") == ["web-dept-43"] for q in requests)
        toggle.click()
        expect(page.locator(".tree-name").filter(has_text="Televíziók")).to_have_count(
            0
        )
        page.get_by_label("Nézet", exact=True).select_option("unclassified")
        expect(
            page.get_by_text(
                "Csak a több lehetséges paraméterforrással rendelkező kategóriák.",
                exact=False,
            )
        ).to_be_visible()
        expect(
            page.locator(".tree-name").filter(has_text=pending["name"])
        ).to_have_count(1)
        page.get_by_label("Kategóriakeresés", exact=True).fill(pending["name"])
        page.get_by_label("Nézet", exact=True).select_option("tree")
        expect(
            page.locator(".tree-name").filter(has_text=pending["name"])
        ).to_have_count(1)
        page.get_by_label("Kategóriakeresés", exact=True).fill("")
        expect(page.locator(".tree > ul > li")).to_have_count(13)
        assert not errors
        browser.close()
