"""Offline, bounded parsing of operator-supplied public menu evidence.

ZIP contents are data, never instructions or executable HTML. The resulting
navigation IDs belong to the webshop namespace, never to Marketplace categories.
"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import PurePosixPath
from urllib.parse import urlparse
import zipfile


class Element:
    def __init__(self, tag="document", attrs=(), parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []

    @property
    def classes(self):
        return set(self.attrs.get("class", "").split())

    def descendants(self):
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()

    def text(self):
        return " ".join(
            "".join(
                c.text() if isinstance(c, Element) else c for c in self.children
            ).split()
        )


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element()
        self.current = self.root
        self.depth = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in {
            "br",
            "hr",
            "meta",
            "link",
            "input",
            "img",
            "wbr",
            "source",
            "area",
            "embed",
        }:
            self.depth += 1
            if self.depth > 128:
                raise ValueError("HTML depth limit")
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node.parent and node.tag != tag:
            node = node.parent
        if node.parent:
            self.current = node.parent
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        self.current.children.append(data)


def kind(url):
    if not url:
        return "section"
    path = urlparse(url).path.lower()
    if "/filter/" in path:
        return "parameter_filter"
    if path.startswith("/shop/"):
        return "brand"
    if path.startswith("/shopping-assistant/"):
        return "product_finder"
    if path.startswith("/search/"):
        return "search"
    if path.startswith(("/lps/", "/lp/")):
        return "campaign"
    if path.startswith("/label/"):
        return "collection"
    if path.endswith("/c"):
        return "category"
    if path.endswith("/sd"):
        return "section"
    if path.endswith("/d"):
        return "department_link"
    return "unknown_link"


def public_url(url):
    if not url:
        return None
    p = urlparse(url)
    if (
        p.scheme != "https"
        or not p.hostname
        or not (p.hostname == "emag.hu" or p.hostname.endswith(".emag.hu"))
        or p.username
        or p.password
        or p.query
        or p.fragment
    ):
        raise ValueError("Expected sanitized public eMAG URL")
    return url


def process_archive(path):
    raw = path.read_bytes()
    if len(raw) > 20_000_000:
        raise ValueError("Archive size limit")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if sum(i.file_size for i in infos) > 30_000_000 or any(
            i.file_size > 5_000_000 for i in infos
        ):
            raise ValueError("Uncompressed size limit")
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or any(
            PurePosixPath(n).is_absolute()
            or ".." in PurePosixPath(n).parts
            or "\\" in n
            for n in names
        ):
            raise ValueError("Unsafe archive member")
        manifest = json.loads(archive.read("emag-menu-export.json").decode("utf-8"))
        groups = manifest["root_groups"]
        if len(groups) != 13:
            raise ValueError("Expected 13 observed departments")
        documents = {}
        hashes = {}
        for group in groups:
            name = group["html_evidence_file"]
            data = archive.read(name)
            digest = hashlib.sha256(data).hexdigest()
            expected = group.get("html_sha256")
            normalized_digest = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
            if digest != expected and normalized_digest != expected:
                raise ValueError("HTML evidence checksum mismatch: " + name)
            documents[name] = Document(data.decode("utf-8")).root
            hashes[name] = {
                "file_sha256": digest,
                "manifest_sha256": expected,
                "windows_newline_normalization": digest != expected,
            }
        # The most complete DOM snapshot retains every lazily loaded department.
        complete = max(
            documents.values(),
            key=lambda d: sum("megamenu-item" in n.classes for n in d.descendants()),
        )
        departments = [
            n
            for n in complete.descendants()
            if n.tag == "li"
            and "megamenu-list-department" in n.classes
            and n.attrs.get("data-id")
        ]
        if len(departments) != 13:
            raise ValueError("HTML does not prove 13 department identities/order")
        nodes = []
        issues = []
        manifest_links = 0
        url_conflicts = 0
        for order, department in enumerate(departments):
            depid = department.attrs["data-id"]
            depname = department.text()
            rootid = "web-dept-" + depid
            # Join the capture to the active panel ID, not a Marketplace name/ID.
            matches = []
            for group in groups:
                doc = documents[group["html_evidence_file"]]
                panels = [
                    n
                    for n in doc.descendants()
                    if "megamenu-details-department" in n.classes
                    and n.attrs.get("data-id") == depid
                    and "megamenu-visible" in n.classes
                ]
                if panels and group["name"] == depname:
                    matches.append((group, panels[0]))
            if len(matches) != 1:
                raise ValueError(
                    "Ambiguous or missing active department capture: " + depid
                )
            group, panel = matches[0]
            links = group["links"]
            manifest_links += len(links)
            by_id = {}
            for link in links:
                sourceid = link.get("explicit_source_attributes", {}).get("data-id")
                if not sourceid or sourceid in by_id:
                    raise ValueError("Missing/duplicate menu-item ID in manifest")
                by_id[sourceid] = link
            nodes.append(
                dict(
                    id=rootid,
                    parent_id=None,
                    root_id=rootid,
                    name=depname,
                    source_department_id=depid,
                    source_item_id=None,
                    kind="department",
                    url=None,
                    order=order,
                    hierarchy_status="verified_dom",
                    parent_evidence="department_dom_order",
                    canonical_emag_id=None,
                )
            )
            elements = [n for n in panel.descendants() if "megamenu-item" in n.classes]
            ids = {n.attrs.get("data-id") for n in elements}
            if len(ids) != len(elements) or None in ids:
                raise ValueError("Missing/duplicate HTML menu item ID")
            seen = set()
            for position, element in enumerate(elements):
                sid = element.attrs["data-id"]
                itemid = f"web-item-{depid}-{sid}"
                captured = by_id.get(sid)
                htmlurl = element.attrs.get("href")
                url = public_url(captured["url"] if captured else htmlurl)
                if captured and element.text() != captured["name"].strip():
                    raise ValueError("Manifest/HTML item label disagreement: " + itemid)
                conflict = bool(captured and htmlurl and htmlurl != url)
                url_conflicts += int(conflict)
                if captured:
                    seen.add(sid)
                parent = rootid
                status = "verified_dom"
                proof = "department_panel_contains_item"
                parent_group = None
                ancestor = element.parent
                while ancestor is not panel and ancestor is not None:
                    if "megamenu-group" in ancestor.classes:
                        groupids = [
                            c.removeprefix("megamenu-group-")
                            for c in ancestor.classes
                            if c.startswith("megamenu-group-")
                        ]
                        parent_group = groupids[0] if len(groupids) == 1 else None
                        if parent_group and parent_group in ids:
                            parent = f"web-item-{depid}-{parent_group}"
                            proof = "explicit_group_class_to_heading_data_id"
                        else:
                            status = "needs_review"
                            proof = "department_only_unlabelled_or_missing_group"
                            issues.append(
                                {
                                    "node_id": itemid,
                                    "reason": proof,
                                    "group_id": parent_group,
                                }
                            )
                        break
                    ancestor = ancestor.parent
                nodes.append(
                    dict(
                        id=itemid,
                        parent_id=parent,
                        root_id=rootid,
                        name=captured["name"] if captured else element.text(),
                        source_department_id=depid,
                        source_item_id=sid,
                        kind=kind(url),
                        url=url,
                        order=position,
                        hierarchy_status=status,
                        parent_evidence=proof,
                        source_group_id=parent_group,
                        canonical_emag_id=None,
                        manifest_observed=bool(captured),
                        url_evidence="manifest_data_id" if captured else "html_only",
                        html_url_disagreement=conflict,
                    )
                )
            if seen != set(by_id):
                raise ValueError("Manifest item missing from its department HTML")
        # Headings whose members are exclusively non-category links are not a
        # taxonomy section (brand shops / finders / filter-facet headings).
        byid = {n["id"]: n for n in nodes}
        children = {}
        for n in nodes:
            children.setdefault(n["parent_id"], []).append(n)
        for n in reversed(nodes):
            if (
                n["kind"] == "section"
                and children.get(n["id"])
                and all(
                    c["kind"] not in {"category", "section"} for c in children[n["id"]]
                )
            ):
                n["kind"] = "related_section"
        for n in nodes:
            parent = n["parent_id"]
            seen = {n["id"]}
            while parent:
                if parent in seen or parent not in byid:
                    raise ValueError("Invalid parsed navigation hierarchy")
                seen.add(parent)
                parent = byid[parent]["parent_id"]
        return {
            "format": "adatdusito.web-navigation.v1",
            "source_url": manifest.get("page"),
            "observed_at": manifest["observed_at"],
            "archive_sha256": hashlib.sha256(raw).hexdigest(),
            "html_checksums": hashes,
            "manifest_link_count": manifest_links,
            "nodes": nodes,
            "verified_root_ids": [n["id"] for n in nodes if n["kind"] == "department"],
            "issues": issues,
            "html_url_disagreements": url_conflicts,
            "mapping_policy": "explicit_reviewed_identity_only",
            "full_category_tree_verified": False,
            "canonical_mappings": {},
            "source_ids_are_marketplace_ids": False,
        }
